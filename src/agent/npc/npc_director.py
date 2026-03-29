"""LLM-first NPC director with structured fallback."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from src.agent.llm_service import LLMService
from src.data.models import DMAgentOutput, GameState, LLMRequestEnvelopeV2
from src.data.npc_planning_models import NPCActionDecision, NPCActionForm, NPCActionType

from .prompt_loader import load_npc_director_prompt

logger = logging.getLogger(__name__)


NPC_DIRECTOR_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "request_id": {"type": "string"},
        "result": {
            "type": "object",
            "properties": {
                "actions": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {
                            "npc_id": {"type": "string"},
                            "action_type": {
                                "type": "string",
                                "enum": ["attack", "move", "talk", "use_item", "investigate", "wait", "custom"],
                            },
                            "target_id": {"type": ["string", "null"]},
                            "intent_description": {"type": "string"},
                            "expected_outcome": {"type": ["string", "null"]},
                            "check": {
                                "type": "object",
                                "properties": {
                                    "check_needed": {"type": "boolean"},
                                    "check_attributes": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "difficulty": {
                                        "type": "string",
                                        "enum": ["常规", "困难", "极难"],
                                    },
                                    "check_target_id": {"type": ["string", "null"]},
                                },
                                "required": ["check_needed", "check_attributes", "difficulty"],
                            },
                            "trigger_source": {"type": "string"},
                            "metadata": {"type": "object"},
                        },
                        "required": ["npc_id", "action_type", "intent_description", "check", "trigger_source"],
                    },
                },
                "rationale": {"type": "string"},
            },
            "required": ["actions"],
        },
        "erro": {"type": "string"},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "extensions": {"type": "object"},
    },
    "required": ["schema_version", "request_id", "result"],
}


class NPCDirector:
    """Centralized NPC planner that outputs structured action forms."""

    def __init__(
        self,
        llm_service: Optional[LLMService] = None,
        system_prompt: Optional[str] = None,
        use_llm: bool = True,
        debug_logger: Optional[Any] = None,
        debug_agent_name: str = "npc_director",
    ):
        self.use_llm = bool(use_llm)
        self.llm_service = llm_service
        if self.use_llm and self.llm_service is None:
            try:
                self.llm_service = LLMService()
            except Exception as e:
                logger.warning("NPCDirector无法初始化LLM服务，使用规则兜底: %s", e)
                self.llm_service = None
        if not self.use_llm:
            self.llm_service = None

        self.system_prompt = system_prompt or load_npc_director_prompt()
        self.debug_logger = debug_logger
        self.debug_agent_name = debug_agent_name

    def decide_actions(
        self,
        npc_ids: List[str],
        game_state: GameState,
        player_intent: Optional[DMAgentOutput] = None,
        trigger_source: str = "unified",
        recent_events: Optional[List[dict]] = None,
        narrative_context: str = "",
    ) -> NPCActionDecision:
        available_npc_ids = self._filter_actionable_npcs(npc_ids, game_state)
        if not available_npc_ids:
            return NPCActionDecision(actions={}, rationale="没有可行动NPC")

        if self.llm_service:
            llm_result = self._llm_decide(
                available_npc_ids,
                game_state,
                player_intent,
                trigger_source,
                recent_events or [],
                narrative_context,
            )
            if llm_result is not None and llm_result.actions:
                return llm_result

        return self._fallback_decision(
            available_npc_ids,
            game_state,
            player_intent,
            trigger_source,
            recent_events or [],
        )

    def _llm_decide(
        self,
        npc_ids: List[str],
        game_state: GameState,
        player_intent: Optional[DMAgentOutput],
        trigger_source: str,
        recent_events: List[dict],
        narrative_context: str,
    ) -> Optional[NPCActionDecision]:
        request = self._build_request(npc_ids, game_state, player_intent, trigger_source, recent_events, narrative_context)
        prompt = self._build_prompt(request)
        try:
            response = self._call_llm_json_compatible(
                prompt=prompt,
                schema=NPC_DIRECTOR_OUTPUT_SCHEMA,
                debug_logger=self.debug_logger,
                debug_agent=self.debug_agent_name,
                debug_context={
                    "request_id": request.request_id,
                    "phase": "npc_planning",
                    "trigger_source": trigger_source,
                    "npc_count": len(npc_ids),
                },
                debug_call_id=f"{request.request_id}-npc-plan",
            )
            if not response.get("success"):
                logger.warning("NPCDirector LLM调用失败: %s", response.get("error"))
                if self.debug_logger and hasattr(self.debug_logger, "log_llm_retry"):
                    self.debug_logger.log_llm_retry(
                        self.debug_agent_name,
                        1,
                        str(response.get("error", "unknown error")),
                    )
                return None
            data = response.get("data") or {}
            return self._parse_decision(data, npc_ids, request.request_id)
        except Exception as e:
            logger.warning("NPCDirector LLM解析失败，回退规则兜底: %s", e)
            return None

    def _call_llm_json_compatible(self, **kwargs) -> Dict[str, Any]:
        try:
            return self.llm_service.call_llm_json(**kwargs)
        except TypeError as e:
            if "unexpected keyword argument" not in str(e):
                raise
            return self.llm_service.call_llm_json(
                prompt=kwargs.get("prompt", ""),
                schema=kwargs.get("schema", {}),
            )

    def _build_request(
        self,
        npc_ids: List[str],
        game_state: GameState,
        player_intent: Optional[DMAgentOutput],
        trigger_source: str,
        recent_events: List[dict],
        narrative_context: str,
    ) -> LLMRequestEnvelopeV2:
        payload = {
            "trigger_source": trigger_source,
            "activated_npc_ids": npc_ids,
            "surrounding_context": {
                "current_map": (
                    {
                        "id": game_state.get_current_map().id,
                        "name": game_state.get_current_map().name,
                        "description": game_state.get_current_map().description.get_public_text(),
                    }
                    if game_state.get_current_map()
                    else None
                ),
                "nearby_non_activated_npcs": [],
                "nearby_items": [],
                "hazards": [],
            },
            "player_action_summary": player_intent.action_description if player_intent else "",
            "player_turn_resolution": None,
            "turn_trace_so_far": {"turn_id": game_state.turn_count, "steps": []},
            "narrative_memory": {"summary_lines": [], "key_facts": [], "stable_facts": []},
            "npc_world_views": [self._serialize_npc_state(game_state, npc_id) for npc_id in npc_ids],
        }
        return LLMRequestEnvelopeV2(
            request_id=f"turn-{game_state.turn_count}-npc-plan",
            turn_id=game_state.turn_count,
            phase="npc_planning",
            payload=payload,
            constraints={
                "enums": {
                    "mode": ["unified"],
                    "action_type": ["attack", "move", "talk", "use_item", "investigate", "wait", "custom"],
                    "check_difficulty": ["常规", "困难", "极难"],
                },
                "rules": {
                    "must_reference_existing_ids": True,
                    "max_actions_per_turn": 3,
                    "avoid_npc_narrative_conflict": True,
                },
            },
            memory_policy={"prefer_recent_turns": True, "must_follow_player_truth_anchor": True},
            extensions={"recent_events": recent_events[-10:], "narrative_context": narrative_context},
        )

    def _build_prompt(self, request: LLMRequestEnvelopeV2) -> str:
        return (
            f"{self.system_prompt}\n\n"
            "## 请求 JSON\n"
            f"{json.dumps(request.model_dump(mode='json'), ensure_ascii=False, indent=2)}"
        )

    def _serialize_npc_state(self, game_state: GameState, npc_id: str) -> Dict[str, Any]:
        npc = game_state.characters.get(npc_id)
        if not npc:
            return {"npc_id": npc_id}
        return {
            "npc_id": npc.id,
            "name": npc.name,
            "location": npc.location,
            "status": {
                "hp": npc.status.hp,
                "max_hp": npc.status.max_hp,
                "san": npc.status.san,
            },
            "attributes": {
                "str": npc.attributes.str,
                "con": npc.attributes.con,
                "siz": npc.attributes.siz,
                "dex": npc.attributes.dex,
                "app": npc.attributes.app,
                "int": npc.attributes.int,
                "pow": npc.attributes.pow,
                "edu": npc.attributes.edu,
            },
            "basic_info": npc.basic_info,
            "description_public": npc.description.get_public_text() if npc.description else "",
            "description_hint": npc.description.hint if npc.description else "",
            "memory": {
                "current_event": npc.memory.current_event if npc.memory else "",
                "log": list(npc.memory.log) if npc.memory else [],
            },
        }

    def _parse_decision(self, data: Dict[str, Any], allowed_npc_ids: List[str], request_id: str) -> NPCActionDecision:
        if request_id and str(data.get("request_id", "")) not in {"", request_id}:
            raise ValueError("request_id 不匹配")
        result = data.get("result")
        if not isinstance(result, dict):
            raise ValueError("缺少 result 对象")
        raw_actions = result.get("actions") or {}
        actions: Dict[str, NPCActionForm] = {}
        for npc_id, raw_action in raw_actions.items():
            if npc_id not in allowed_npc_ids:
                continue
            if isinstance(raw_action, dict):
                raw_action.setdefault("npc_id", npc_id)
                actions[npc_id] = NPCActionForm(**raw_action)

        return NPCActionDecision(
            actions=actions,
            rationale=str(result.get("rationale", "")).strip(),
        )

    def _fallback_decision(
        self,
        npc_ids: List[str],
        game_state: GameState,
        player_intent: Optional[DMAgentOutput],
        trigger_source: str,
        recent_events: List[dict],
    ) -> NPCActionDecision:
        actions: Dict[str, NPCActionForm] = {}
        player_id = game_state.player_id or ""

        for npc_id in npc_ids:
            action_type = NPCActionType.WAIT
            target_id = None
            intent_description = "保持观察，等待局势变化"

            if player_intent and player_intent.npc_response_needed:
                action_type = NPCActionType.TALK
                target_id = player_id or None
                intent_description = player_intent.npc_intent or "对玩家刚刚的行动做出回应"

            actions[npc_id] = NPCActionForm(
                npc_id=npc_id,
                action_type=action_type,
                target_id=target_id,
                intent_description=intent_description,
                trigger_source=trigger_source,
                metadata={"recent_events_count": len(recent_events)},
            )

        return NPCActionDecision(
            actions=actions,
            rationale="LLM不可用，已使用规则兜底计划",
        )

    def _filter_actionable_npcs(self, npc_ids: List[str], game_state: GameState) -> List[str]:
        filtered: List[str] = []
        for npc_id in npc_ids:
            npc = game_state.characters.get(npc_id)
            if not npc or npc.is_player:
                continue
            if npc.status.hp <= 0 or npc.status.san <= 0:
                continue
            filtered.append(npc_id)
        return filtered


__all__ = ["NPCDirector"]
