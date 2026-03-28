"""
状态推演系统 - 叙事生成与状态变更

该模块是AI权力最大的模块，负责将数值结果转化为世界变化：
1. 根据鉴定结果推演世界变化
2. 生成叙事描述
3. 生成状态变更列表（StateChange）
4. 兼容NPC扮演（替代原独立NPC Agent）
5. 支持结局判定

使用方法:
    from src.agent.state_evolution import StateEvolution
    from src.data.models import StateEvolutionInput, GameState
    
    evolution = StateEvolution()
    
    # 玩家行动推演
    result = evolution.evolve_player_action(
        check_result=check_output,
        action_description="玩家试图撬开保险箱",
        game_state=game_state
    )
    
    # result包含narrative叙事、changes变更列表、is_end是否结局等
"""

import json
import logging
from typing import Dict, List, Optional, Any

from src.data.models import (
    StateEvolutionOutput,
    StateChange,
    ChangeOperation,
    GameState,
    CheckOutput,
    LLMRequestEnvelopeV2,
)
from src.agent.llm_service import LLMService

# 配置日志
logger = logging.getLogger(__name__)

ALLOWED_DELETE_LIST_FIELDS = {
    "inventory",
    "neighbors",
    "entities.items",
    "entities.characters",
    "description.public",
    "memory.log",
}

# StateEvolution V2 response schema（用于LLM输出约束）
STATE_EVOLUTION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "request_id": {"type": "string"},
        "result": {
            "type": "object",
            "properties": {
                "actor_id": {"type": "string"},
                "phase": {"type": "string", "enum": ["player", "npc"]},
                "intent_text": {"type": "string"},
                "check_result": {
                    "type": ["object", "null"],
                    "properties": {
                        "result": {"type": "string"},
                        "dice_roll": {"type": "integer"},
                        "target_value": {"type": "integer"},
                        "actor_value": {"type": "integer"},
                        "detail": {"type": "string"},
                    },
                },
                "state_changes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "field": {"type": "string"},
                            "operation": {"type": "string", "enum": ["update", "add", "del", "move"]},
                            "value": {"type": ["string", "number", "boolean", "array", "object", "null"]},
                        },
                        "required": ["id", "field", "operation"],
                    },
                },
                "local_narrative": {"type": "string"},
                "outcome": {
                    "type": "object",
                    "properties": {
                        "action_succeeded": {"type": "boolean"},
                        "outcome_type": {"type": "string"},
                        "consequence_tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["action_succeeded", "outcome_type", "consequence_tags"],
                },
            },
            "required": ["actor_id", "phase", "intent_text", "state_changes", "local_narrative", "outcome"],
        },
        "erro":{
            "type":"string",
            "description":"报错信息输出错误时返回给llm,使其纠正错误"
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
        "extensions": {"type": "object"},
    },
    "required": ["schema_version", "request_id", "result"]
}


class StateEvolution:
    """
    状态推演系统 - COC游戏世界变化推演器
    
    负责根据鉴定结果生成叙事和状态变更，是连接数值系统和游戏世界的桥梁。
    使用LLM服务进行智能推演，通过Prompt工程实现。
    
    Attributes:
        llm_service: LLM服务实例
        system_prompt: 系统提示词
        end_condition: 结局条件描述
    
    Example:
        >>> evolution = StateEvolution()
        >>> result = evolution.evolve_player_action(check_result, action, game_state)
        >>> print(result.narrative)
        >>> for change in result.changes:
        ...     print(f"{change.id}.{change.field} -> {change.value}")
    """
    
    def __init__(
        self,
        llm_service: Optional[LLMService] = None,
        system_prompt: Optional[str] = None,
        end_condition: str = ""
    ):
        """
        初始化状态推演系统
        
        Args:
            llm_service: LLM服务实例，如果为None则自动创建
            system_prompt: 自定义系统提示词，如果为None则加载默认提示词
            end_condition: 结局条件描述，用于结局判定
        """
        # 初始化LLM服务
        self.llm_service = llm_service or LLMService()
        
        # 加载系统提示词
        if system_prompt:
            self.system_prompt = system_prompt
        else:
            self.system_prompt = self._load_default_system_prompt()
        
        # 结局条件
        self.end_condition = end_condition
        
        logger.info("状态推演系统初始化完成")
    
    def _load_default_system_prompt(self) -> str:
        """
        加载默认系统提示词
        
        Returns:
            系统提示词内容
        """
        from src.agent.prompt import load_state_evolution_prompt
        prompt = load_state_evolution_prompt()
        if not prompt or not prompt.strip():
            raise RuntimeError("状态推演系统提示词为空")
        return prompt
    
    def evolve_player_action(
        self,
        check_result: Optional[CheckOutput],
        action_description: str,
        game_state: GameState,
        additional_context: Optional[Dict[str, Any]] = None
    ) -> StateEvolutionOutput:
        """
        推演玩家行动结果
        
        根据鉴定结果和行动描述，生成叙事和状态变更。
        
        Args:
            check_result: 鉴定结果，如果为None表示自动成功
            action_description: 行动的自然语言描述
            game_state: 当前游戏状态
            additional_context: 额外上下文信息
        
        Returns:
            StateEvolutionOutput对象，包含叙事、变更列表等
        """
        game_context = self._build_game_context(game_state)
        if additional_context:
            game_context.update(additional_context)

        request = self._build_player_request(
            check_result=check_result,
            action_description=action_description,
            game_state=game_state,
            game_context=game_context,
        )
        return self._call_evolution(
            prompt=self._build_prompt(request),
            game_state=game_state,
            request_id=request.request_id,
        )
    
    def evolve_npc_action(
        self,
        npc_id: str,
        game_state: GameState,
        check_result: Optional[CheckOutput] = None,
        npc_intent: Optional[str] = None,
        additional_context: Optional[Dict[str, Any]] = None
    ) -> StateEvolutionOutput:
        """
        推演NPC行动
        
        根据NPC当前状态和意图，生成NPC行动和状态变更。
        替代原独立NPC Agent的功能。
        
        Args:
            npc_id: NPC角色ID
            game_state: 当前游戏状态
            check_result: NPC鉴定结果（可选）
            npc_intent: NPC意图描述（可选）
            additional_context: 额外上下文信息
        
        Returns:
            StateEvolutionOutput对象，包含NPC行动、变更列表等
        """
        # 获取NPC信息
        npc = game_state.characters.get(npc_id)
        if not npc:
            logger.error(f"NPC不存在: {npc_id}")
            return self._create_fallback_output(f"NPC {npc_id} 不存在")
        
        game_context = self._build_game_context(game_state)
        game_context["active_npc"] = {
            "id": npc.id,
            "name": npc.name,
            "basic_info": npc.basic_info,
            "description_public": npc.description.get_public_text() if npc.description else "",
            "description_hint": npc.description.hint if npc.description else "",
            "status": {
                "hp": npc.status.hp,
                "san": npc.status.san,
            },
            "location": npc.location,
        }
        if additional_context:
            game_context.update(additional_context)
        
        request = self._build_npc_request(
            npc_id=npc_id,
            npc_intent=npc_intent,
            check_result=check_result,
            game_state=game_state,
            game_context=game_context,
        )
        return self._call_evolution(
            prompt=self._build_prompt(request),
            game_state=game_state,
            request_id=request.request_id,
        )
    
    def check_end_condition(self, game_state: GameState) -> Optional[StateEvolutionOutput]:
        """
        检查是否满足结局条件
        
        Args:
            game_state: 当前游戏状态
        
        Returns:
            如果满足结局条件，返回结局输出；否则返回None
        """
        if not self.end_condition:
            return None

        game_context = self._build_game_context(game_state)
        request = self._build_end_check_request(game_state=game_state, game_context=game_context)
        result = self._call_evolution(
            prompt=self._build_prompt(request),
            game_state=game_state,
            request_id=request.request_id,
        )
        
        if result.is_end:
            return result
        return None
    
    def _build_game_context(self, game_state: GameState) -> Dict[str, Any]:
        """
        构建游戏上下文信息
        
        从游戏状态中提取角色、物品、地图等完整信息，供LLM进行推演。
        
        Args:
            game_state: 游戏状态对象
        
        Returns:
            游戏上下文字典
        """
        context = {
            "current_location": None,
            "current_characters": [],
            "current_items": [],
            "all_items_info": {},  # 所有物品信息，包括不在当前地图的
            "player_info": None,
            "turn_count": game_state.turn_count,
        }
        
        # 收集所有物品信息（包括名称和描述）
        for item_id, item in game_state.items.items():
            context["all_items_info"][item_id] = {
                "id": item.id,
                "name": item.name,
                "location": item.location,
                "is_portable": item.is_portable,
                "description_public": item.description.get_public_text() if item.description else "",
                "description_hint": item.description.hint if item.description else "",
            }
        
        # 获取当前地图信息
        current_map = game_state.get_current_map()
        if current_map:
            context["current_location"] = {
                "id": current_map.id,
                "name": current_map.name,
                "description": current_map.description.get_public_text(),
            }
            
            # 添加邻居地图信息（包含正确ID，防止LLM幻觉）
            if current_map.neighbors:
                context["available_exits"] = [
                    {
                        "map_id": neighbor.id,
                        "direction": neighbor.direction,
                        "description": neighbor.description
                    }
                    for neighbor in current_map.neighbors
                ]
            
            # 获取场景中的角色
            for char_id in current_map.entities.characters:
                char = game_state.characters.get(char_id)
                if char:
                    char_info = {
                        "id": char.id,
                        "name": char.name,
                        "is_player": char.is_player,
                        "basic_info": char.basic_info,
                        "description_public": char.description.get_public_text() if char.description else "",
                        "description_hint": char.description.hint if char.description else "",
                        "status": {
                            "hp": char.status.hp,
                            "max_hp": char.status.max_hp,
                            "san": char.status.san,
                        },
                    }
                    context["current_characters"].append(char_info)
            
            # 获取场景中的物品
            for item_id in current_map.entities.items:
                item = game_state.items.get(item_id)
                if item:
                    item_info = {
                        "id": item.id,
                        "name": item.name,
                        "location": item.location,
                        "is_portable": item.is_portable,
                        "description_public": item.description.get_public_text() if item.description else "",
                        "description_hint": item.description.hint if item.description else "",
                    }
                    context["current_items"].append(item_info)
        
        # 获取玩家信息
        player = game_state.get_player()
        if player:
            # 获取玩家背包中物品的详细信息
            player_inventory_details = []
            for item_id in player.inventory:
                item = game_state.items.get(item_id)
                if item:
                    player_inventory_details.append({
                        "id": item.id,
                        "name": item.name,
                        "description": item.description.get_public_text() if item.description else "",
                    })
            
            context["player_info"] = {
                "id": player.id,
                "name": player.name,
                "basic_info": player.basic_info,
                "status": {
                    "hp": player.status.hp,
                    "max_hp": player.status.max_hp,
                    "san": player.status.san,
                    "lucky": player.status.lucky,
                },
                "attributes": {
                    "str": player.attributes.str,
                    "con": player.attributes.con,
                    "dex": player.attributes.dex,
                    "int": player.attributes.int,
                    "pow": player.attributes.pow,
                    "edu": player.attributes.edu,
                },
                "location": player.location,
                "inventory": player.inventory,
                "inventory_details": player_inventory_details,
            }
        
        return context

    def _build_player_request(
        self,
        check_result: Optional[CheckOutput],
        action_description: str,
        game_state: GameState,
        game_context: Dict[str, Any],
    ) -> LLMRequestEnvelopeV2:
        turn_id = int(getattr(game_state, "turn_count", 0) or 0)
        turn_intent = game_context.get("turn_intent") or {
            "actor_id": game_state.player_id or "",
            "raw_input_text": action_description,
            "intent_text": action_description,
            "interaction_type": "action",
            "check_plan": {
                "check_needed": check_result is not None,
                "check_type": "非对抗鉴定" if check_result is not None else None,
                "attributes": [],
                "target_id": None,
                "difficulty": "常规" if check_result is not None else None,
            },
            "activation_hint": {
                "response_needed_hint": bool(game_context.get("npc_response_expected", False)),
                "preferred_actor_id": game_context.get("npc_response_actor_id"),
                "candidate_npc_ids_hint": [],
            },
        }
        return LLMRequestEnvelopeV2(
            request_id=f"turn-{turn_id}-player-evolve",
            turn_id=turn_id,
            phase="player",
            payload={
                "world_state_view": game_context.get("world_state_view", {}),
                "dialogue_memory": game_context.get("dialogue_memory", {"recent_dialogues": []}),
                "narrative_memory": game_context.get("narrative_memory", {"summary_lines": [], "key_facts": [], "stable_facts": []}),
                "turn_trace_so_far": game_context.get("turn_trace_so_far", {"turn_id": turn_id, "steps": []}),
                "turn_intent": turn_intent,
                "check_result": check_result.model_dump() if check_result else None,
                "truth_anchor": game_context.get("player_resolution_anchor", {}),
            },
            constraints={
                "enums": {"allowed_change_operations": ["update", "add", "del", "move"]},
                "rules": {
                    "delete_whitelist": sorted(ALLOWED_DELETE_LIST_FIELDS),
                    "update_rule": {"must_use_existing_field": True, "forbid_schema_break": True},
                    "add_rule": {"target_must_be_list": True, "forbid_nested_list_add": True},
                    "delete_rule": {"forbid_scalar_delete": True, "coerce_scalar_delete_to_update": True},
                    "move_rule": {
                        "field_must_be": "location",
                        "value_must_be": "target-id or {from,to}",
                        "char_target_must_be_map": True,
                        "item_target_must_be_char_or_map": True,
                        "from_must_match_current_location_if_provided": True,
                    },
                },
            },
            memory_policy={"drift_anchor_required": True, "max_generated_narrative_chars": 800},
            extensions={"end_condition": self.end_condition},
        )

    def _build_npc_request(
        self,
        npc_id: str,
        npc_intent: Optional[str],
        check_result: Optional[CheckOutput],
        game_state: GameState,
        game_context: Dict[str, Any],
    ) -> LLMRequestEnvelopeV2:
        turn_id = int(getattr(game_state, "turn_count", 0) or 0)
        return LLMRequestEnvelopeV2(
            request_id=f"turn-{turn_id}-npc-evolve-{npc_id}",
            turn_id=turn_id,
            phase="npc",
            payload={
                "active_npc_id": npc_id,
                "npc_action_plan": game_context.get("npc_action_plan", {}),
                "world_state_view": game_context.get("world_state_view", {}),
                "dialogue_memory": game_context.get("dialogue_memory", {"recent_dialogues": []}),
                "narrative_memory": game_context.get("narrative_memory", {"summary_lines": [], "key_facts": [], "stable_facts": []}),
                "turn_trace_so_far": game_context.get("turn_trace_so_far", {"turn_id": turn_id, "steps": []}),
                "player_turn_resolution": game_context.get("player_turn_resolution"),
                "truth_anchor": game_context.get("player_resolution_anchor", {}),
                "npc_intent": npc_intent or "",
                "check_result": check_result.model_dump() if check_result else None,
            },
            constraints={
                "enums": {"allowed_change_operations": ["update", "add", "del", "move"]},
                "rules": {
                    "must_not_override_player_truth": True,
                    "must_not_duplicate_applied_changes": True,
                },
            },
            memory_policy={"max_generated_narrative_chars": 600, "drift_anchor_required": True},
            extensions={"end_condition": self.end_condition},
        )

    def _build_end_check_request(
        self,
        game_state: GameState,
        game_context: Dict[str, Any],
    ) -> LLMRequestEnvelopeV2:
        turn_id = int(getattr(game_state, "turn_count", 0) or 0)
        return LLMRequestEnvelopeV2(
            request_id=f"turn-{turn_id}-end-check",
            turn_id=turn_id,
            phase="end_check",
            payload={
                "world_state_view": game_context.get("world_state_view", {}),
                "dialogue_memory": game_context.get("dialogue_memory", {"recent_dialogues": []}),
                "narrative_memory": game_context.get("narrative_memory", {"summary_lines": [], "key_facts": [], "stable_facts": []}),
                "turn_trace_so_far": game_context.get("turn_trace_so_far", {"turn_id": turn_id, "steps": []}),
                "turn_intent": {
                    "actor_id": game_state.player_id or "",
                    "raw_input_text": "结局判定",
                    "intent_text": "检查当前状态是否触发结局",
                    "interaction_type": "action",
                    "check_plan": {
                        "check_needed": False,
                        "check_type": None,
                        "attributes": [],
                        "target_id": None,
                        "difficulty": None,
                    },
                    "activation_hint": {
                        "response_needed_hint": False,
                        "preferred_actor_id": None,
                        "candidate_npc_ids_hint": [],
                    },
                },
                "check_result": None,
                "truth_anchor": {},
            },
            constraints={
                "enums": {"allowed_change_operations": ["update", "add", "del", "move"]},
                "rules": {
                    "must_only_decide_ending": True,
                    "must_not_invent_new_state_change": True,
                },
            },
            memory_policy={"drift_anchor_required": True, "max_generated_narrative_chars": 400},
            extensions={"end_condition": self.end_condition, "end_check_only": True},
        )

    def _build_prompt(self, request: LLMRequestEnvelopeV2) -> str:
        return (
            f"{self.system_prompt}\n\n"
            "## 请求 JSON\n"
            f"{json.dumps(request.model_dump(mode='json'), ensure_ascii=False, indent=2)}\n"
        )
    
    def _call_evolution(
        self,
        prompt: str,
        game_state: Optional[GameState] = None,
        request_id: str = "",
    ) -> StateEvolutionOutput:
        """
        调用LLM进行状态推演
        
        Args:
            prompt: 提示词
        
        Returns:
            StateEvolutionOutput对象
        """
        error_feedback = ""

        try:
            for attempt in range(1, 3):
                prompt_with_feedback = self._append_error_feedback(prompt, error_feedback)
                response = self.llm_service.call_llm_json(
                    prompt=prompt_with_feedback,
                    schema=STATE_EVOLUTION_OUTPUT_SCHEMA,
                )

                if not response.get("success"):
                    error_msg = response.get("error", "未知错误")
                    logger.error(f"LLM调用失败: {error_msg}")
                    return self._create_fallback_output(f"推演失败: {error_msg}")

                data = response.get("data", {})
                output = self._parse_output(data, request_id=request_id)

                if not game_state:
                    return output

                validation_errors = self.validate_changes(output.changes, game_state)
                if not validation_errors:
                    return output

                llm_erro = str(data.get("erro", "")).strip()
                lines = validation_errors[:3]
                if llm_erro:
                    lines.append(f"LLM erro字段: {llm_erro}")
                error_feedback = "；".join(lines)
                logger.warning(f"状态推演输出校验失败(第{attempt}次): {error_feedback}")

            return self._create_fallback_output(f"状态推演输出校验失败: {error_feedback}")

        except Exception as e:
            logger.error(f"状态推演时发生异常: {e}")
            return self._create_fallback_output(f"异常: {str(e)}")

    def _append_error_feedback(self, prompt: str, error_feedback: str) -> str:
        """将系统错误反馈追加到Prompt，用于引导LLM纠正输出。"""
        if not error_feedback:
            return prompt

        return (
            f"{prompt}\n\n"
            "---\n\n"
            "## 系统错误反馈（erro）\n\n"
            f"{error_feedback}\n\n"
            "请根据以上错误反馈修正输出，返回合法JSON，且state_changes必须只引用当前存在的实体与字段。"
        )
    
    def _parse_output(self, data: Dict[str, Any], request_id: str = "") -> StateEvolutionOutput:
        """
        解析LLM输出为StateEvolutionOutput
        
        Args:
            data: LLM返回的字典数据
        
        Returns:
            StateEvolutionOutput对象
        """
        if request_id and str(data.get("request_id", "")) not in {"", request_id}:
            raise ValueError("request_id 不匹配")

        result = data.get("result")
        if not isinstance(result, dict):
            raise ValueError("缺少 result 对象")

        changes = []
        for change_data in result.get("state_changes", []):
            try:
                # 将字符串operation转换为枚举
                op_str = change_data.get("operation", "update")
                operation = ChangeOperation(op_str)
                
                change = StateChange(
                    id=change_data.get("id", ""),
                    field=change_data.get("field", ""),
                    operation=operation,
                    value=change_data.get("value")
                )
                changes.append(change)
            except (ValueError, KeyError) as e:
                logger.warning(f"解析变更项失败: {e}, 数据: {change_data}")
                continue
        
        return StateEvolutionOutput(
            narrative=result.get("local_narrative", ""),
            changes=changes,
            resolved=True,
            next_action_hint=((data.get("extensions") or {}).get("next_action_hint")),
            is_end=bool(((data.get("extensions") or {}).get("is_end", False))),
            end_narrative=str(((data.get("extensions") or {}).get("end_narrative", ""))),
        )
    
    def _create_fallback_output(self, reason: str) -> StateEvolutionOutput:
        """
        创建失败时的备用输出
        
        Args:
            reason: 失败原因
        
        Returns:
            StateEvolutionOutput对象
        """
        return StateEvolutionOutput(
            narrative=f"状态推演失败: {reason}。请重试或联系管理员。",
            changes=[],
            resolved=True,
            next_action_hint=None,
            is_end=False,
            end_narrative=""
        )

    def _field_path_exists(self, entity: Any, field: str) -> bool:
        """Check whether a dotted field path exists on the target entity."""
        current = entity
        for part in field.split("."):
            if isinstance(current, dict):
                if part not in current:
                    return False
                current = current[part]
                continue
            if hasattr(current, part):
                current = getattr(current, part)
            else:
                return False
        return True

    def validate_changes(
        self,
        changes: List[StateChange],
        game_state: GameState
    ) -> List[str]:
        """
        验证变更列表的合法性
        
        Args:
            changes: 变更列表
            game_state: 游戏状态
        
        Returns:
            错误信息列表，空列表表示验证通过
        """
        errors = []
        
        for i, change in enumerate(changes):
            prefix = f"变更[{i}]"
            
            # 检查实体ID是否存在
            entity_id = change.id
            entity = (
                game_state.characters.get(entity_id) or
                game_state.items.get(entity_id) or
                game_state.maps.get(entity_id)
            )
            
            if not entity:
                errors.append(f"{prefix}: 实体不存在 '{entity_id}'")
                continue
            
            # 检查字段路径是否有效（简单检查）
            field = change.field
            if not field:
                errors.append(f"{prefix}: 字段路径为空")
                continue

            if not self._field_path_exists(entity, field):
                errors.append(f"{prefix}: 字段路径不存在 '{field}'")
                continue
            
            # 根据操作类型进行额外验证
            if change.operation == ChangeOperation.DELETE:
                if field not in ALLOWED_DELETE_LIST_FIELDS:
                    errors.append(f"{prefix}: DELETE仅允许作用于白名单列表字段 '{field}'")
            elif change.operation == ChangeOperation.ADD:
                # ADD操作通常用于列表类型的字段
                if entity_id.startswith("char-") and field == "inventory":
                    if not isinstance(change.value, str):
                        errors.append(f"{prefix}: inventory ADD 的value必须是物品ID字符串")
                    elif change.value not in game_state.items:
                        errors.append(f"{prefix}: inventory ADD 物品不存在 '{change.value}'")
            elif change.operation == ChangeOperation.UPDATE:
                # UPDATE操作需要有值
                if change.value is None:
                    errors.append(f"{prefix}: UPDATE操作需要value")

                if entity_id.startswith("char-") and field == "inventory":
                    if not isinstance(change.value, list):
                        errors.append(f"{prefix}: inventory UPDATE 的value必须是列表")
                    else:
                        for item_id in change.value:
                            if item_id not in game_state.items:
                                errors.append(f"{prefix}: inventory UPDATE 包含不存在物品 '{item_id}'")

                if field == "location" and isinstance(change.value, str):
                    if entity_id.startswith("char-") and change.value not in game_state.maps:
                        errors.append(f"{prefix}: 角色目标位置不存在 '{change.value}'")
                    if entity_id.startswith("item-") and (
                        change.value not in game_state.maps and change.value not in game_state.characters
                    ):
                        errors.append(f"{prefix}: 物品目标位置不存在 '{change.value}'")
            elif change.operation == ChangeOperation.MOVE:
                if field != "location":
                    errors.append(f"{prefix}: MOVE操作仅允许 field=location")
                    continue

                target = ""
                source = None
                if isinstance(change.value, str):
                    target = change.value
                elif isinstance(change.value, dict):
                    target = str(change.value.get("to", "") or "")
                    source = change.value.get("from")
                else:
                    errors.append(f"{prefix}: MOVE的value必须是目标ID字符串或{{from,to}}对象")
                    continue

                if not target:
                    errors.append(f"{prefix}: MOVE缺少目标ID")
                    continue

                if entity_id.startswith("char-") and target not in game_state.maps:
                    errors.append(f"{prefix}: 角色MOVE目标位置不存在 '{target}'")
                if entity_id.startswith("item-") and (
                    target not in game_state.maps and target not in game_state.characters
                ):
                    errors.append(f"{prefix}: 物品MOVE目标位置不存在 '{target}'")
                if source is not None and not isinstance(source, str):
                    errors.append(f"{prefix}: MOVE.from必须为字符串")
        
        return errors
