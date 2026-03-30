"""
DM Agent模块 - 意图解析与鉴定判断

该模块负责解析玩家的自然语言输入，判断：
1. 是否为纯对话（is_dialogue）
2. 是否需要鉴定（needs_check）
3. 鉴定类型（check_type）
4. 鉴定属性（check_attributes）
5. 对抗目标（check_target）
6. 生成行动描述（action_description）

使用方法:
    from src.agent.dm_agent import DMAgent
    from src.data.models import DMAgentInput, GameState
    
    agent = DMAgent()
    
    # 解析玩家意图
    result = agent.parse_intent(
        player_input="我要仔细搜查这个房间",
        game_state=game_state
    )
    
    # result是DMAgentOutput对象
    print(result.needs_check)  # True
    print(result.check_type)   # "非对抗鉴定"
"""

import json
import logging
from typing import Dict, List, Optional, Any

from src.data.models import (
    DMAgentOutput,
    GameState,
    LLMRequestEnvelopeV2,
)
from src.agent.llm_service import LLMService
from src.rule.rule_system import get_attribute_value

# 配置日志
logger = logging.getLogger(__name__)

# DMAgent V2 response schema（用于LLM输出约束）
DMAGENT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "request_id": {"type": "string"},
        "result": {
            "type": "object",
            "properties": {
                "turn_intent": {
                    "type": "object",
                    "properties": {
                        "actor_id": {"type": "string"},
                        "raw_input_text": {"type": "string"},
                        "intent_text": {"type": "string"},
                        "interaction_type": {
                            "type": "string",
                            "enum": ["action", "dialogue", "mixed"],
                        },
                        "check_plan": {
                            "type": "object",
                            "properties": {
                                "check_needed": {"type": "boolean"},
                                "check_type": {
                                    "type": ["string", "null"],
                                    "enum": ["非对抗鉴定", "对抗鉴定", None],
                                },
                                "attributes": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "target_id": {"type": ["string", "null"]},
                                "difficulty": {
                                    "type": ["string", "null"],
                                    "enum": ["常规", "困难", "极难", None],
                                },
                            },
                            "required": ["check_needed", "attributes"],
                        },
                        "activation_hint": {
                            "type": "object",
                            "properties": {
                                "response_needed_hint": {"type": "boolean"},
                                "preferred_actor_id": {"type": ["string", "null"]},
                                "candidate_npc_ids_hint": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["response_needed_hint", "candidate_npc_ids_hint"],
                        },
                    },
                    "required": [
                        "actor_id",
                        "raw_input_text",
                        "intent_text",
                        "interaction_type",
                        "check_plan",
                        "activation_hint",
                    ],
                },
                "response_to_player": {
                    "type": ["string", "null"],
                },
            },
            "required": ["turn_intent", "response_to_player"],
        },
        "erro": {
            "type": "string",
            "description": "可选。系统错误反馈；若存在，需据此修正输出"
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
        "extensions": {"type": "object"},
    },
    "required": [
        "schema_version",
        "request_id",
        "result",
    ]
}


class DMAgent:
    """
    DM Agent - COC游戏主持人智能体
    
    负责解析玩家输入，判断意图类型，决定是否需要鉴定。
    使用LLM服务进行意图识别，通过Prompt工程实现。
    
    Attributes:
        llm_service: LLM服务实例
        system_prompt: 系统提示词
        max_history: 保留的最大对话历史轮数
    
    Example:
        >>> agent = DMAgent()
        >>> result = agent.parse_intent("我要搜查房间", game_state)
        >>> print(result.check_type)
        '非对抗鉴定'
    """
    
    def __init__(
        self,
        llm_service: Optional[LLMService] = None,
        system_prompt: Optional[str] = None,
        max_history: int = 5,
        debug_logger: Optional[Any] = None,
        debug_agent_name: str = "dm_agent",
    ):
        """
        初始化DM Agent
        
        Args:
            llm_service: LLM服务实例，如果为None则自动创建
            system_prompt: 自定义系统提示词，如果为None则加载默认提示词
            max_history: 保留的最大对话历史轮数
        """
        # 初始化LLM服务
        self.llm_service = llm_service or LLMService()
        
        # 加载系统提示词
        if system_prompt:
            self.system_prompt = system_prompt
        else:
            self.system_prompt = self._load_default_system_prompt()
        
        # 配置参数
        self.max_history = max_history
        self.debug_logger = debug_logger
        self.debug_agent_name = debug_agent_name
        
        logger.info("DM Agent初始化完成")
    
    def _load_default_system_prompt(self) -> str:
        """
        加载默认系统提示词
        
        Returns:
            系统提示词内容
        """
        from src.agent.prompt import load_system_prompt
        prompt = load_system_prompt()
        if not prompt or not prompt.strip():
            raise RuntimeError("DM Agent系统提示词为空")
        return prompt
    
    def parse_intent(
        self,
        player_input: str,
        game_state: Optional[GameState] = None,
        dialogue_history: Optional[List[str]] = None,
        additional_context: Optional[Dict[str, Any]] = None
    ) -> DMAgentOutput:
        """
        解析玩家意图
        
        这是DM Agent的核心方法，分析玩家输入并返回结构化结果。
        
        Args:
            player_input: 玩家的自然语言输入
            game_state: 当前游戏状态（用于构建上下文）
            dialogue_history: 对话历史列表（可选）
        
        Returns:
            DMAgentOutput对象，包含意图解析结果
        
        Raises:
            Exception: 当LLM调用失败时可能抛出异常
        
        Example:
            >>> result = agent.parse_intent("我要开锁", game_state)
            >>> if result.needs_check:
            ...     print(f"需要{result.check_type}")
        """
        if dialogue_history:
            dialogue_history = dialogue_history[-self.max_history:]
        else:
            dialogue_history = []

        request = self._build_request_envelope(
            player_input=player_input,
            game_state=game_state,
            dialogue_history=dialogue_history,
            additional_context=additional_context,
        )
        prompt = self._build_prompt(self.system_prompt, request)
        
        error_feedback = ""

        # 调用LLM进行意图识别（最多重试2次）
        try:
            for attempt in range(1, 3):
                prompt_with_feedback = self._append_error_feedback(prompt, error_feedback)
                response = self._call_llm_json_compatible(
                    prompt=prompt_with_feedback,
                    schema=DMAGENT_OUTPUT_SCHEMA,
                    debug_logger=self.debug_logger,
                    debug_agent=self.debug_agent_name,
                    debug_context={
                        "request_id": request.request_id,
                        "phase": "dm_processing",
                        "player_input": player_input,
                        "has_error_feedback": bool(error_feedback),
                    },
                    debug_call_id=f"{request.request_id}-dm",
                    debug_attempt=attempt,
                )

                if not response.get("success"):
                    error_feedback = response.get("error", "未知错误")
                    logger.warning(f"DM输出失败(第{attempt}次): {error_feedback}")
                    if self.debug_logger and hasattr(self.debug_logger, "log_llm_retry"):
                        self.debug_logger.log_llm_retry(self.debug_agent_name, attempt, error_feedback)
                    continue

                data = response.get("data", {})
                try:
                    output = self._parse_output_strict(data, player_input, request.request_id)
                except Exception as parse_err:
                    llm_erro = str(data.get("erro", "")).strip()
                    error_feedback = str(parse_err)
                    if llm_erro:
                        error_feedback = f"{error_feedback}；LLM erro字段: {llm_erro}"
                    logger.warning(f"DM输出解析失败(第{attempt}次): {error_feedback}")
                    if self.debug_logger and hasattr(self.debug_logger, "log_llm_retry"):
                        self.debug_logger.log_llm_retry(self.debug_agent_name, attempt, error_feedback)
                    continue

                validation_error = self._validate_output(output, game_state)
                if not validation_error:
                    return output

                llm_erro = str(data.get("erro", "")).strip()
                error_feedback = validation_error
                if llm_erro:
                    error_feedback = f"{error_feedback}；LLM erro字段: {llm_erro}"
                logger.warning(f"DM输出校验失败(第{attempt}次): {error_feedback}")
                if self.debug_logger and hasattr(self.debug_logger, "log_llm_retry"):
                    self.debug_logger.log_llm_retry(self.debug_agent_name, attempt, error_feedback)

            return self._create_fallback_output(player_input, f"DM输出校验失败: {error_feedback}")

        except Exception as e:
            logger.error(f"解析意图时发生异常: {e}")
            return self._create_fallback_output(player_input, str(e))

    def _append_error_feedback(self, prompt: str, error_feedback: str) -> str:
        """将系统错误反馈追加到Prompt，用于引导LLM纠正输出。"""
        if not error_feedback:
            return prompt

        return (
            f"{prompt}\n\n"
            "---\n\n"
            "## 系统错误反馈（erro）\n\n"
            f"{error_feedback}\n\n"
            "请根据以上错误反馈修正输出，确保check_attributes只使用当前规则支持的属性字段。"
        )

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

    def _validate_output(self, output: DMAgentOutput, game_state: Optional[GameState]) -> Optional[str]:
        """校验DM输出与规则系统兼容性，返回错误信息或None。"""
        if not output.needs_check:
            return None

        if not output.check_attributes:
            return "needs_check=true 时 check_attributes 不能为空"

        if not game_state:
            return None

        player = game_state.get_player()
        if not player:
            return None

        invalid_attrs = [
            attr for attr in output.check_attributes
            if get_attribute_value(player, str(attr)) is None
        ]
        if invalid_attrs:
            return (
                f"check_attributes 存在规则不支持的属性: {invalid_attrs}。"
                "当前支持: str/con/siz/dex/app/int/pow/edu/hp/san/lucky"
            )

        return None

    def _parse_output_strict(
        self,
        data: Dict[str, Any],
        original_input: str,
        request_id: str,
    ) -> DMAgentOutput:
        """严格解析LLM输出为DMAgentOutput对象，错误将抛出给上层重试逻辑。"""
        if request_id and str(data.get("request_id", "")) not in {"", request_id}:
            raise ValueError("request_id 不匹配")
        result = data.get("result")
        if not isinstance(result, dict):
            raise ValueError("缺少 result 对象")
        turn_intent = result.get("turn_intent") or {}
        if not isinstance(turn_intent, dict) or not turn_intent:
            raise ValueError("缺少 result.turn_intent")
        check_plan = turn_intent.get("check_plan") or {}
        activation_hint = turn_intent.get("activation_hint") or {}
        interaction_type = str(turn_intent.get("interaction_type", "action") or "action")
        if interaction_type not in {"action", "dialogue", "mixed"}:
            interaction_type = "action"
        is_dialogue = interaction_type in {"dialogue", "mixed"}
        needs_check = bool(check_plan.get("check_needed", False))

        return DMAgentOutput(
            interaction_type=interaction_type,
            is_dialogue=is_dialogue,
            response_to_player=result.get("response_to_player") or "",
            needs_check=needs_check,
            check_type=check_plan.get("check_type"),
            check_attributes=list(check_plan.get("attributes") or []),
            check_target=check_plan.get("target_id"),
            difficulty=check_plan.get("difficulty", "常规"),
            action_description=turn_intent.get("intent_text", original_input),
            npc_response_needed=bool(activation_hint.get("response_needed_hint", False)),
            npc_actor_id=activation_hint.get("preferred_actor_id"),
            npc_intent=None,
            actionable_npcs=list(activation_hint.get("candidate_npc_ids_hint") or []),
        )
    
    def _build_game_context(self, game_state: Optional[GameState]) -> Dict[str, Any]:
        """
        构建游戏上下文信息
        
        从游戏状态中提取相关信息，供LLM进行意图判断。
        
        Args:
            game_state: 游戏状态对象
        
        Returns:
            游戏上下文字典
        """
        if not game_state:
            return {}
        
        context = {
            "current_location": None,
            "current_characters": [],
            "current_items": [],
            "player_info": None,
        }
        
        # 获取当前地图信息
        current_map = game_state.get_current_map()
        if current_map:
            context["current_location"] = {
                "id": current_map.id,
                "name": current_map.name,
                "description": current_map.description.get_public_text(),
            }
            
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
                    }
                    context["current_characters"].append(char_info)
            
            # 获取场景中的物品
            for item_id in current_map.entities.items:
                item = game_state.items.get(item_id)
                if item:
                    item_info = {
                        "id": item.id,
                        "name": item.name,
                        "description_public": item.description.get_public_text() if item.description else "",
                        "description_hint": item.description.hint if item.description else "",
                        "is_portable": item.is_portable, #缺少位置信息
                    }
                    context["current_items"].append(item_info)
        
        # 获取玩家信息
        player = game_state.get_player()
        if player:
            context["player_info"] = {
                "id": player.id,
                "name": player.name,
                "status": {
                    "hp": player.status.hp,
                    "max_hp": player.status.max_hp,
                    "san": player.status.san,
                },
                "attributes": {
                    "str": player.attributes.str,
                    "con": player.attributes.con,
                    "dex": player.attributes.dex,
                    "int": player.attributes.int,
                    "pow": player.attributes.pow,
                    "edu": player.attributes.edu,
                }
            }
        
        return context

    def _build_request_envelope(
        self,
        player_input: str,
        game_state: Optional[GameState],
        dialogue_history: List[str],
        additional_context: Optional[Dict[str, Any]] = None,
    ) -> LLMRequestEnvelopeV2:
        game_context = self._build_game_context(game_state)
        additional_context = additional_context or {}
        turn_id = int(getattr(game_state, "turn_count", 0) or 0)
        actor_id = str(getattr(game_state, "player_id", "") or "")

        world_state_view = additional_context.get("world_state_view") or {
            "current_map": game_context.get("current_location"),
            "nearby_characters": game_context.get("current_characters", []),
            "nearby_items": game_context.get("current_items", []),
            "player_state": game_context.get("player_info"),
            "available_exits": [],
        }
        dialogue_memory = additional_context.get("dialogue_memory") or {
            "recent_dialogues": [
                {"speaker": "history", "content": one}
                for one in dialogue_history
                if str(one).strip()
            ]
        }
        narrative_memory = additional_context.get("narrative_memory") or {
            "summary_lines": [],
            "key_facts": [],
            "stable_facts": [],
        }
        turn_trace = additional_context.get("turn_trace_so_far") or {
            "turn_id": turn_id,
            "steps": [],
        }

        return LLMRequestEnvelopeV2(
            request_id=f"turn-{turn_id}-player-parse",
            turn_id=turn_id,
            phase="player",
            payload={
                "raw_input_text": player_input,
                "world_state_view": world_state_view,
                "dialogue_memory": dialogue_memory,
                "narrative_memory": narrative_memory,
                "turn_trace_so_far": turn_trace,
            },
            constraints={
                "enums": {
                    "npc_response_mode": [str(additional_context.get("npc_response_mode", "unified") or "unified")],
                    "interaction_type": ["action", "dialogue", "mixed"],
                    "check_difficulty": ["常规", "困难", "极难"],
                    "allowed_check_attributes": [
                        "str", "con", "siz", "dex", "app", "int", "pow", "edu", "hp", "san", "lucky",
                    ],
                },
                "rules": {
                    "must_be_grounded": True,
                    "forbid_field_invention": True,
                    "actor_id": actor_id,
                },
            },
            memory_policy={
                "max_recent_dialogues": 20,
                "max_summary_lines": 20,
                "drift_anchor_required": True,
            },
            extensions={
                "npc_response_policy": additional_context.get("npc_response_policy", ""),
                "npc_prelude": additional_context.get("npc_prelude", ""),
            },
        )
    
    def _build_prompt(self, system_prompt: str, request: LLMRequestEnvelopeV2) -> str:
        """Build V2 JSON prompt."""
        return (
            f"{system_prompt}\n\n"
            "## 请求 JSON\n"
            f"{json.dumps(request.model_dump(mode='json'), ensure_ascii=False, indent=2)}\n"
        )
    
    def _parse_output(
        self,
        data: Dict[str, Any],
        original_input: str
    ) -> DMAgentOutput:
        """
        解析LLM输出为DMAgentOutput对象
        
        Args:
            data: LLM返回的JSON数据
            original_input: 原始玩家输入
        
        Returns:
            DMAgentOutput对象
        """
        try:
            output = self._parse_output_strict(
                data,
                original_input,
                str(data.get("request_id", "")),
            )
            
            logger.debug(f"意图解析完成: is_dialogue={output.is_dialogue}, needs_check={output.needs_check}")
            return output
            
        except Exception as e:
            logger.error(f"解析输出时发生错误: {e}")
            return self._create_fallback_output(original_input, str(e))
    
    def _create_fallback_output(
        self,
        player_input: str,
        error_message: str
    ) -> DMAgentOutput:
        """
        创建降级输出（当LLM调用失败时使用）
        
        Args:
            player_input: 玩家输入
            error_message: 错误信息
        
        Returns:
            降级DMAgentOutput对象
        """
        logger.warning(f"使用降级输出，错误: {error_message}")
        
        return DMAgentOutput(
            interaction_type="dialogue",
            is_dialogue=True,
            response_to_player=f"我理解你的意图是：{player_input}。让我继续游戏。",
            needs_check=False,
            check_type=None,
            check_attributes=[],
            check_target=None,
            difficulty=None,
            action_description=player_input,
            npc_response_needed=False,
            npc_actor_id=None,
            npc_intent=None,
            actionable_npcs=[],
        )
    
    def quick_parse(
        self,
        player_input: str,
        **context_kwargs
    ) -> DMAgentOutput:
        """
        快速解析（简化接口）
        
        不需要完整的GameState，可以直接传入上下文信息。
        
        Args:
            player_input: 玩家输入
            **context_kwargs: 上下文关键字参数，如 location, characters等
        
        Returns:
            DMAgentOutput对象
        
        Example:
            >>> result = agent.quick_parse(
            ...     "我要开锁",
            ...     location={"name": "废弃仓库", "description": "阴暗潮湿"},
            ...     characters=[{"name": "守卫", "id": "guard1"}]
            ... )
        """
        game_context = {
            "current_location": context_kwargs.get("location"),
            "current_characters": context_kwargs.get("characters", []),
            "current_items": context_kwargs.get("items", []),
            "player_info": context_kwargs.get("player"),
        }
        
        # 构建提示词
        prompt = self._build_prompt(
            self.system_prompt,
            self._build_request_envelope(
                player_input=player_input,
                game_state=None,
                dialogue_history=context_kwargs.get("dialogue_history", []),
                additional_context={
                    "world_state_view": {
                        "current_map": game_context.get("current_location"),
                        "nearby_characters": game_context.get("current_characters", []),
                        "nearby_items": game_context.get("current_items", []),
                        "player_state": game_context.get("player_info"),
                        "available_exits": [],
                    }
                },
            ),
        )
        
        # 调用LLM
        try:
            response = self.llm_service.call_llm_json(
                prompt=prompt,
                schema=DMAGENT_OUTPUT_SCHEMA,
            )
            
            if response.get("success"):
                return self._parse_output(response.get("data", {}), player_input)
            else:
                return self._create_fallback_output(player_input, response.get("error", "调用失败"))
                
        except Exception as e:
            return self._create_fallback_output(player_input, str(e))


# 便捷函数

def create_dm_agent(
    llm_service: Optional[LLMService] = None,
    system_prompt: Optional[str] = None
) -> DMAgent:
    """
    创建DM Agent实例的便捷函数
    
    Args:
        llm_service: LLM服务实例
        system_prompt: 自定义系统提示词
    
    Returns:
        DMAgent实例
    """
    return DMAgent(llm_service=llm_service, system_prompt=system_prompt)


def quick_intent_parse(
    player_input: str,
    game_state: Optional[GameState] = None,
    **kwargs
) -> DMAgentOutput:
    """
    快速意图解析（无需预先创建实例）
    
    Args:
        player_input: 玩家输入
        game_state: 游戏状态
        **kwargs: 其他参数
    
    Returns:
        DMAgentOutput对象
    
    Example:
        >>> from src.agent.dm_agent import quick_intent_parse
        >>> result = quick_intent_parse("我要搜查房间", game_state)
        >>> print(result.check_attributes)
    """
    agent = DMAgent()
    return agent.parse_intent(player_input, game_state=game_state, **kwargs)
