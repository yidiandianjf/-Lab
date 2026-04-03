"""Merge fragmented narratives into a coherent turn-level narrative."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.agent.llm_service import LLMService
from src.data.models import (
    LLMRequestEnvelopeV2,
    NarrativeMergerInputV2,
    NarrativeMergerOutputV2,
    NarrativeMemoryView,
    TurnStep,
)

DEFAULT_NARRATIVE_MERGER_LLM_CONFIG_PATH = "config/narrative_merger_llm.json"


class NarrativeMerger:
    """LLM-backed narrative merger with deterministic fallback."""

    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "schema_version": {"type": "string"},
            "request_id": {"type": "string"},
            "result": {
                "type": "object",
                "properties": {
                    "merged_narrative": {"type": "string"},
                    "turn_summary": {"type": "string"},
                    "new_key_facts": {"type": "array", "items": {"type": "string"}},
                    "dialogue_updates": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "speaker": {"type": "string"},
                                "content": {"type": "string"},
                            },
                            "required": ["speaker", "content"],
                        },
                    },
                },
                "required": ["merged_narrative", "turn_summary", "new_key_facts", "dialogue_updates"],
            },
            "erro": {"type": "string"},
            "warnings": {"type": "array", "items": {"type": "string"}},
            "extensions": {"type": "object"},
        },
        "required": ["schema_version", "request_id", "result"],
    }

    def __init__(
        self,
        llm_service: Optional[LLMService] = None,
        system_prompt: Optional[str] = None,
        use_llm: bool = True,
        debug_logger: Optional[Any] = None,
        debug_agent_name: str = "narrative_merger",
    ):
        self.use_llm = bool(use_llm)
        self.llm_service = llm_service
        if self.use_llm and self.llm_service is None:
            try:
                self.llm_service = LLMService.from_config_path(DEFAULT_NARRATIVE_MERGER_LLM_CONFIG_PATH)
            except Exception:
                self.llm_service = None
        if not self.use_llm:
            self.llm_service = None

        self.system_prompt = system_prompt or self._load_default_prompt()
        self.debug_logger = debug_logger
        self.debug_agent_name = debug_agent_name

    def merge(
        self,
        fragments: List[Dict[str, str]],
        game_state: Optional[Any] = None,
        context: str = "",
        truth_anchor: Optional[Dict[str, Any]] = None,
    ) -> str:
        cleaned = [f for f in fragments if (f.get("text") or "").strip()]
        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return cleaned[0]["text"].strip()

        if self.llm_service:
            merged = self._merge_with_llm(cleaned, game_state, context, truth_anchor or {})
            if merged:
                return merged

        return "\n".join(fragment["text"].strip() for fragment in cleaned if fragment.get("text"))

    def _merge_with_llm(
        self,
        fragments: List[Dict[str, str]],
        game_state: Optional[Any],
        context: str,
        truth_anchor: Dict[str, Any],
    ) -> str:
        request = LLMRequestEnvelopeV2(
            request_id=f"turn-{getattr(game_state, 'turn_count', 0) if game_state else 0}-merge-legacy",
            turn_id=(getattr(game_state, "turn_count", 0) if game_state else 0),
            phase="narrative_merge",
            payload={
                "turn_trace_steps": [
                    {
                        "step_id": f"legacy-{idx}",
                        "turn_id": (getattr(game_state, "turn_count", 0) if game_state else 0),
                        "actor_id": str(one.get("actor_id", "")),
                        "phase": "npc",
                        "trigger_source": "legacy",
                        "intent": {"actor_id": str(one.get("actor_id", ""))},
                        "resolution": {"actor_id": str(one.get("actor_id", "")), "phase": "npc", "local_narrative": str(one.get("text", ""))},
                    }
                    for idx, one in enumerate(fragments)
                ],
                "turn_truth_anchor": truth_anchor,
                "narrative_memory": {"summary_lines": [context] if context else [], "key_facts": [], "stable_facts": []},
                "dialogue_memory": {"recent_dialogues": []},
            },
            constraints={"rules": {"must_preserve_turn_truth_anchor": True, "must_not_invent_new_state_change": True}},
            memory_policy={"summary_write_back_required": True, "key_fact_write_back_required": True},
        )
        prompt = (
            f"{self.system_prompt}\n\n"
            "## 请求 JSON\n"
            f"{json.dumps(request.model_dump(mode='json'), ensure_ascii=False, indent=2)}"
        )

        if hasattr(self.llm_service, "call_llm_json"):
            response = self._call_llm_json_compatible(
                prompt=prompt,
                schema=self.OUTPUT_SCHEMA,
                debug_logger=self.debug_logger,
                debug_agent=self.debug_agent_name,
                debug_context={
                    "request_id": request.request_id,
                    "phase": "narrative_merge_legacy",
                    "fragment_count": len(fragments),
                },
                debug_call_id=f"{request.request_id}-merge-legacy",
            )
            if response.get("success"):
                data = response.get("data") or {}
                result = data.get("result") or {}
                return str(result.get("merged_narrative", "")).strip()

        response = self._call_llm_compatible(
            prompt,
            debug_logger=self.debug_logger,
            debug_agent=self.debug_agent_name,
            debug_context={
                "request_id": request.request_id,
                "phase": "narrative_merge_legacy_plain",
                "fragment_count": len(fragments),
            },
            debug_call_id=f"{request.request_id}-merge-legacy-plain",
        )
        if not response.get("success"):
            return ""
        return str(response.get("content", "")).strip()

    def merge_v2(
        self,
        turn_trace_steps: List[TurnStep],
        turn_truth_anchor: Optional[Dict[str, Any]] = None,
        narrative_memory: Optional[NarrativeMemoryView] = None,
    ) -> NarrativeMergerOutputV2:
        """Phase 6 merger API, returns structured output while reusing legacy merger behavior."""
        input_v2 = NarrativeMergerInputV2(
            turn_trace_steps=turn_trace_steps or [],
            turn_truth_anchor=turn_truth_anchor or {},
            narrative_memory=narrative_memory or NarrativeMemoryView(),
        )

        fragments: List[Dict[str, str]] = []
        for step in input_v2.turn_trace_steps:
            text = (step.resolution.local_narrative or "").strip()
            if not text:
                continue
            fragments.append(
                {
                    "actor_id": step.actor_id,
                    "actor_name": step.actor_id,
                    "text": text,
                }
            )

        if self.llm_service and fragments:
            request = LLMRequestEnvelopeV2(
                request_id=f"turn-{(input_v2.turn_trace_steps[0].turn_id if input_v2.turn_trace_steps else 0)}-merge",
                turn_id=(input_v2.turn_trace_steps[0].turn_id if input_v2.turn_trace_steps else 0),
                phase="narrative_merge",
                payload={
                    "turn_trace_steps": [step.model_dump(mode="json") for step in input_v2.turn_trace_steps],
                    "turn_truth_anchor": input_v2.turn_truth_anchor,
                    "narrative_memory": input_v2.narrative_memory.model_dump(),
                    "dialogue_memory": {"recent_dialogues": []},
                },
                constraints={
                    "rules": {
                        "must_preserve_turn_truth_anchor": True,
                        "must_not_invent_new_state_change": True,
                        "max_merged_narrative_chars": 1000,
                    }
                },
                memory_policy={
                    "summary_write_back_required": True,
                    "key_fact_write_back_required": True,
                },
            )
            prompt = (
                f"{self.system_prompt}\n\n"
                "## 请求 JSON\n"
                f"{json.dumps(request.model_dump(mode='json'), ensure_ascii=False, indent=2)}"
            )
            response = self._call_llm_json_compatible(
                prompt=prompt,
                schema=self.OUTPUT_SCHEMA,
                debug_logger=self.debug_logger,
                debug_agent=self.debug_agent_name,
                debug_context={
                    "request_id": request.request_id,
                    "phase": "narrative_merge_v2",
                    "fragment_count": len(fragments),
                    "turn_id": request.turn_id,
                },
                debug_call_id=f"{request.request_id}-merge",
            )
            if response.get("success"):
                data = response.get("data") or {}
                result = data.get("result") or {}
                return NarrativeMergerOutputV2(
                    merged_narrative=str(result.get("merged_narrative", "")).strip(),
                    turn_summary=str(result.get("turn_summary", "")).strip(),
                    new_key_facts=[str(one) for one in result.get("new_key_facts", []) if str(one).strip()],
                    dialogue_updates=list(result.get("dialogue_updates", [])),
                )

        merged = self.merge(
            fragments=fragments,
            game_state=None,
            context="\n".join(input_v2.narrative_memory.summary_lines),
            truth_anchor=input_v2.turn_truth_anchor,
        )
        if not merged:
            merged = "\n".join(fragment.get("text", "") for fragment in fragments if fragment.get("text"))

        new_key_facts: List[str] = []
        for step in input_v2.turn_trace_steps:
            if step.actor_id and step.actor_id not in new_key_facts:
                new_key_facts.append(step.actor_id)

        turn_summary = merged.strip()
        if len(turn_summary) > 200:
            turn_summary = turn_summary[:200].rstrip() + "..."

        return NarrativeMergerOutputV2(merged_narrative=merged, turn_summary=turn_summary, new_key_facts=new_key_facts, dialogue_updates=[])

    def _load_default_prompt(self) -> str:
        prompt_path = Path(__file__).parent / "prompt" / "narrative_merger_prompt.md"
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()

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

    def _call_llm_compatible(self, prompt: str, **kwargs) -> Dict[str, Any]:
        try:
            return self.llm_service.call_llm(prompt, **kwargs)
        except TypeError as e:
            if "unexpected keyword argument" not in str(e):
                raise
            return self.llm_service.call_llm(prompt)
