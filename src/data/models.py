"""
COC文字冒险游戏框架 - 数据模型定义
基于Pydantic的类型安全数据模型
"""

import builtins
from datetime import datetime
from typing import List, Dict, Optional, Any, Union, Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator
from enum import Enum


# ============================================================
# 基础类型定义
# ============================================================

class Description(BaseModel):
    """二级描述系统 - 支持public、hint和add
    
    字段说明:
    - public: 公开描述列表，只读，由系统维护
    - hint: 仅AI知道的隐藏提示，只读
    - add: 新增描述，StateEvolution只能向此字段添加内容
    """
    public: List[Dict[str, str]] = Field(default_factory=list, description="公开描述列表（只读）")
    hint: str = Field(default="", description="仅AI知道的隐藏提示（只读）")
    add: List[Dict[str, str]] = Field(default_factory=list, description="新增描述（StateEvolution可编辑）")
    model_config = ConfigDict(validate_assignment=True)

    @field_validator("public", "add", mode="before")
    @classmethod
    def _normalize_public(cls, value: Any) -> List[Dict[str, str]]:
        """将历史脏数据统一收敛为列表结构。"""
        if value is None:
            return []
        if isinstance(value, dict):
            value = [value]
        elif isinstance(value, str):
            value = [{"description": value}]
        elif not isinstance(value, list):
            value = [{"description": str(value)}]

        normalized: List[Dict[str, str]] = []
        for entry in value:
            if isinstance(entry, dict):
                text = str(entry.get("description", "")).strip()
            else:
                text = str(entry).strip()
            if text:
                normalized.append({"description": text})
        return normalized

    def get_public_text(self) -> str:
        """获取所有公开描述的拼接文本（包含add字段的内容）"""
        lines: List[str] = []
        # 包含public和add字段的所有描述
        all_descriptions = self.public + self.add
        for entry in all_descriptions:
            if isinstance(entry, dict):
                lines.append(str(entry.get("description", "")))
            elif isinstance(entry, str):
                lines.append(entry)
            else:
                lines.append(str(entry))
        return "\n".join(lines)
    
    def add_public_description(self, text: str) -> None:
        """添加新的公开描述到add字段"""
        normalized = str(text).strip()
        if normalized:
            self.add.append({"description": normalized})
    
    def commit_add_to_public(self) -> None:
        """将add字段的内容合并到public字段，然后清空add"""
        if self.add:
            self.public.extend(self.add)
            self.add = []


class Memory(BaseModel):
    """角色记忆系统"""
    current_event: str = Field(default="", description="当前回合可见信息")
    log: List[str] = Field(default_factory=list, description="完整行动日志")

    def push_to_log(self, event: str) -> None:
        """将当前事件压入日志并重置current_event"""
        if self.current_event:
            self.log.append(self.current_event)
        self.current_event = event

    def clear_current(self) -> None:
        """清空current_event（每回合开始时调用）"""
        if self.current_event:
            self.log.append(self.current_event)
            self.current_event = ""


# ============================================================
# 角色属性定义
# ============================================================

class CharacterAttributes(BaseModel):
    """COC角色属性（七大主属性）"""
    str: builtins.int = Field(default=10, ge=1, le=99, description="力量 STRENGTH")
    con: builtins.int = Field(default=10, ge=1, le=99, description="体质 CONSTITUTION")
    siz: builtins.int = Field(default=10, ge=1, le=99, description="体型 SIZE")
    dex: builtins.int = Field(default=10, ge=1, le=99, description="敏捷 DEXTERITY")
    app: builtins.int = Field(default=10, ge=1, le=99, description="外貌 APPEARANCE")
    int: builtins.int = Field(default=10, ge=1, le=99, description="智力 INTELLIGENCE")
    pow: builtins.int = Field(default=10, ge=1, le=99, description="意志 POWER")
    edu: builtins.int = Field(default=10, ge=1, le=99, description="教育 EDUCATION")


class CharacterStatus(BaseModel):
    """角色状态（动态变化）"""
    hp: int = Field(default=10, description="生命值 Hit Points")
    max_hp: int = Field(default=10, description="最大生命值")
    san: int = Field(default=50, ge=0, le=100, description="理智值 Sanity")
    lucky: int = Field(default=50, ge=1, le=99, description="幸运值 Luck")


# ============================================================
# 实体模型定义
# ============================================================

class Character(BaseModel):
    """角色实体"""
    id: str = Field(..., description="角色唯一标识符")
    name: str = Field(..., description="角色名称")
    basic_info: str = Field(default="", description="基本信息/背景简介")
    description: Description = Field(default_factory=Description, description="描述系统")
    location: str = Field(default="", description="当前位置（地图ID或空）")
    inventory: List[str] = Field(default_factory=list, description="背包物品ID列表")
    status: CharacterStatus = Field(default_factory=CharacterStatus, description="角色状态")
    attributes: CharacterAttributes = Field(default_factory=CharacterAttributes, description="角色属性")
    memory: Memory = Field(default_factory=Memory, description="记忆系统")
    is_player: bool = Field(default=False, description="是否为玩家控制角色")

    class Config:
        extra = "allow"  # 允许额外字段，便于扩展


class Item(BaseModel):
    """物品实体"""
    id: str = Field(..., description="物品唯一标识符")
    name: str = Field(..., description="物品名称")
    description: Description = Field(default_factory=Description, description="描述系统")
    location: str = Field(default="", description="位置（地图ID或角色ID）")
    is_portable: bool = Field(default=True, description="是否可携带")

    class Config:
        extra = "allow"


class MapNeighbor(BaseModel):
    """地图邻居连接"""
    id: str = Field(..., description="相邻地图ID")
    direction: str = Field(..., description="方向（如：北、南、东、西）")
    description: str = Field(default="", description="连接描述（如：一扇木门）")


class MapEntities(BaseModel):
    """地图上的实体"""
    characters: List[str] = Field(default_factory=list, description="角色ID列表")
    items: List[str] = Field(default_factory=list, description="物品ID列表")
    model_config = ConfigDict(validate_assignment=True)

    @field_validator("characters", "items", mode="before")
    @classmethod
    def _normalize_ids(cls, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        elif not isinstance(value, list):
            value = [value]

        flattened: List[str] = []
        seen = set()

        def _append(item: Any) -> None:
            if isinstance(item, str):
                normalized = item.strip()
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    flattened.append(normalized)
            elif isinstance(item, list):
                for inner in item:
                    _append(inner)

        for entry in value:
            _append(entry)
        return flattened


class Map(BaseModel):
    """地图/场景实体"""
    id: str = Field(..., description="地图唯一标识符")
    name: str = Field(..., description="地图名称")
    parent_id: Optional[str] = Field(default=None, description="父级区域ID")
    description: Description = Field(default_factory=Description, description="描述系统")
    neighbors: List[MapNeighbor] = Field(default_factory=list, description="相邻地图")
    entities: MapEntities = Field(default_factory=MapEntities, description="地图上的实体")

    @field_validator("neighbors", mode="before")
    @classmethod
    def _normalize_neighbors(cls, value: Any) -> List[MapNeighbor]:
        if value is None:
            return []
        if isinstance(value, dict):
            value = [value]
        elif not isinstance(value, list):
            value = [value]

        normalized: List[MapNeighbor] = []
        for entry in value:
            if isinstance(entry, MapNeighbor):
                normalized.append(entry)
                continue
            if isinstance(entry, dict):
                try:
                    normalized.append(MapNeighbor(**entry))
                    continue
                except Exception:
                    pass
        return normalized

    class Config:
        extra = "allow"
        validate_assignment = True


# ============================================================
# 游戏状态变更模型
# ============================================================

class ChangeOperation(str, Enum):
    """变更操作类型"""
    UPDATE = "update"
    ADD = "add"
    DELETE = "del"
    MOVE = "move"


class StateChange(BaseModel):
    """状态变更项"""
    id: str = Field(..., description="实体ID")
    field: str = Field(..., description="字段路径（支持点分，如attributes.hp）")
    operation: ChangeOperation = Field(..., description="操作类型")
    value: Any = Field(default=None, description="新值")


# ============================================================
# 鉴定相关模型
# ============================================================

class CheckType(str, Enum):
    """鉴定类型"""
    REGULAR = "非对抗鉴定"
    OPPOSED = "对抗鉴定"


class CheckDifficulty(str, Enum):
    """鉴定难度"""
    REGULAR = "常规"
    HARD = "困难"
    EXTREME = "极难"


class CheckResult(str, Enum):
    """鉴定结果等级"""
    CRITICAL_SUCCESS = "大成功"
    SUCCESS = "成功"
    FAILURE = "失败"
    FUMBLE = "大失败"


class NpcResponseMode(str, Enum):
    """NPC响应模式（收敛后仅保留 unified）。"""
    UNIFIED = "unified"


class CheckInput(BaseModel):
    """规则系统输入"""
    check_type: CheckType = Field(..., description="鉴定类型")
    attributes: List[str] = Field(..., description="使用的属性列表")
    actor_id: str = Field(..., description="行动者ID")
    target_id: Optional[str] = Field(default=None, description="目标ID（对抗鉴定）")
    difficulty: CheckDifficulty = Field(default=CheckDifficulty.REGULAR, description="难度")


class CheckOutput(BaseModel):
    """规则系统输出"""
    result: CheckResult = Field(..., description="鉴定结果")
    dice_roll: int = Field(..., ge=1, le=100, description="骰子结果")
    target_value: int = Field(..., description="目标值")
    actor_value: int = Field(..., description="行动者实际属性值")
    detail: str = Field(default="", description="详细说明")


# ============================================================
# Phase 1 新协议模型（增量引入，兼容旧链路）
# ============================================================

class CheckPlan(BaseModel):
    """E4: 检定计划。"""

    check_needed: bool = Field(default=False)
    check_type: Optional[str] = Field(default=None)
    attributes: Optional[List[str]] = Field(default=None)
    target_id: Optional[str] = Field(default=None)
    difficulty: Optional[str] = Field(default=None)


class ActivationHint(BaseModel):
    """NPC激活建议。"""

    response_needed_hint: bool = Field(default=False)
    preferred_actor_id: Optional[str] = Field(default=None)
    npc_intent_hint: Optional[str] = Field(default=None)
    candidate_npc_ids_hint: Optional[List[str]] = Field(default=None)


class TurnIntent(BaseModel):
    """E3: 意图解释。"""

    actor_id: str = Field(...)
    raw_input_text: str = Field(default="")
    intent_text: str = Field(default="")
    interaction_type: Literal["action", "dialogue", "mixed"] = Field(default="action")
    check_plan: Optional[CheckPlan] = Field(default=None)
    activation_hint: ActivationHint = Field(default_factory=ActivationHint)


class OutcomeSummary(BaseModel):
    """步骤结果摘要。"""

    action_succeeded: bool = Field(default=False)
    outcome_type: str = Field(default="")
    consequence_tags: List[str] = Field(default_factory=list)


class TurnResolution(BaseModel):
    """E5: 步骤结算。"""

    actor_id: str = Field(...)
    phase: Literal["player", "npc"] = Field(default="player")
    intent_text: str = Field(default="")
    check_result: Optional[CheckOutput] = Field(default=None)
    state_changes: List[StateChange] = Field(default_factory=list)
    local_narrative: str = Field(default="")
    outcome: OutcomeSummary = Field(default_factory=OutcomeSummary)


class TurnStep(BaseModel):
    """E6: 回合步骤。"""

    step_id: str = Field(...)
    turn_id: int = Field(default=0)
    actor_id: str = Field(...)
    phase: Literal["player", "npc"] = Field(default="player")
    trigger_source: str = Field(default="")
    intent: TurnIntent = Field(default_factory=lambda: TurnIntent(actor_id=""))
    resolution: TurnResolution = Field(
        default_factory=lambda: TurnResolution(actor_id="")
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class TurnTrace(BaseModel):
    """E6: 回合因果链。"""

    turn_id: int = Field(default=0)
    steps: List[TurnStep] = Field(default_factory=list)

    def append_step(self, step: TurnStep) -> None:
        self.steps.append(step)

    def get_steps_for_actor(self, actor_id: str) -> List[TurnStep]:
        return [one for one in self.steps if one.actor_id == actor_id]


class WorldStateView(BaseModel):
    """E1: 受控世界视图。"""

    current_map: Optional[Dict[str, Any]] = Field(default=None)
    nearby_characters: List[Dict[str, Any]] = Field(default_factory=list)
    nearby_items: List[Dict[str, Any]] = Field(default_factory=list)
    player_state: Optional[Dict[str, Any]] = Field(default=None)
    available_exits: List[Dict[str, Any]] = Field(default_factory=list)


class DialogueMemoryEntry(BaseModel):
    """结构化对话记忆条目。"""

    speaker: str = Field(default="")
    content: str = Field(default="")


class DialogueMemoryView(BaseModel):
    """E8: 对话记忆视图。"""

    recent_dialogues: List[DialogueMemoryEntry] = Field(default_factory=list)


class NarrativeMemoryView(BaseModel):
    """E8: 叙事记忆视图。"""

    summary_lines: List[str] = Field(default_factory=list)
    key_facts: List[str] = Field(default_factory=list)
    stable_facts: List[str] = Field(default_factory=list)


class TurnTraceView(BaseModel):
    """E6: 面向推理侧的回合因果链视图。"""

    turn_id: int = Field(default=0)
    steps: List[TurnStep] = Field(default_factory=list)


class NarrativeMergerInputV2(BaseModel):
    """Phase 6: 叙事合并输入协议。"""

    turn_trace_steps: List[TurnStep] = Field(default_factory=list)
    turn_truth_anchor: Dict[str, Any] = Field(default_factory=dict)
    narrative_memory: NarrativeMemoryView = Field(default_factory=NarrativeMemoryView)


class NarrativeMergerOutputV2(BaseModel):
    """Phase 6: 叙事合并输出协议。"""

    merged_narrative: str = Field(default="")
    turn_summary: str = Field(default="")
    new_key_facts: List[str] = Field(default_factory=list)
    dialogue_updates: List[DialogueMemoryEntry] = Field(default_factory=list)


class TurnTraceDigest(BaseModel):
    """Phase 7: 持久化用回合链摘要。"""

    turn_id: int = Field(default=0)
    summary: str = Field(default="")
    actor_ids: List[str] = Field(default_factory=list)


class PersistenceSnapshotV2(BaseModel):
    """Phase 7: 持久化快照协议。"""

    game_state: "GameState"
    dialogue_memory: DialogueMemoryView = Field(default_factory=DialogueMemoryView)
    narrative_memory: NarrativeMemoryView = Field(default_factory=NarrativeMemoryView)
    recent_turn_traces: List[TurnTraceDigest] = Field(default_factory=list)
    save_version: str = Field(default="2")


class LLMRequestEnvelopeV2(BaseModel):
    """Generic V2 request envelope for LLM-facing protocols."""

    schema_version: str = Field(default="2.0")
    request_id: str = Field(default="")
    turn_id: int = Field(default=0)
    phase: str = Field(default="")
    source: str = Field(default="engine")
    payload: Dict[str, Any] = Field(default_factory=dict)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    memory_policy: Dict[str, Any] = Field(default_factory=dict)
    extensions: Dict[str, Any] = Field(default_factory=dict)


class LLMResponseEnvelopeV2(BaseModel):
    """Generic V2 response envelope for LLM-facing protocols."""

    schema_version: str = Field(default="2.0")
    request_id: str = Field(default="")
    result: Dict[str, Any] = Field(default_factory=dict)
    erro: str = Field(default="")
    warnings: List[str] = Field(default_factory=list)
    extensions: Dict[str, Any] = Field(default_factory=dict)


# ============================================================
# DM Agent 输入输出模型
# ============================================================

class DMAgentInput(BaseModel):
    """DM Agent输入"""
    system_prompt: str = Field(..., description="系统提示词")
    player_input: str = Field(..., description="玩家输入")
    dialogue_history: List[str] = Field(default_factory=list, description="对话历史")
    game_context: Dict[str, Any] = Field(default_factory=dict, description="游戏上下文")
    npc_response_mode: NpcResponseMode = Field(default=NpcResponseMode.UNIFIED, description="NPC响应模式")
    additional_context: Dict[str, Any] = Field(default_factory=dict, description="引擎附加上下文")


class DMAgentOutput(BaseModel):
    """DM Agent输出"""
    interaction_type: Literal["action", "dialogue", "mixed"] = Field(
        default="action",
        description="交互类型：纯动作/纯对话/混合",
    )
    is_dialogue: bool = Field(default=False, description="是否为纯对话")
    response_to_player: str = Field(default="", description="给玩家的回复")
    needs_check: bool = Field(default=False, description="是否需要鉴定")
    check_type: Optional[str] = Field(default=None, description="鉴定类型")
    check_attributes: List[str] = Field(default_factory=list, description="鉴定属性")
    check_target: Optional[str] = Field(default=None, description="对抗目标ID")
    difficulty: Optional[str] = Field(default=None, description="非对抗鉴定难度")
    action_description: str = Field(default="", description="行动的自然语言描述")
    npc_response_needed: bool = Field(default=False, description="是否需要NPC响应")
    npc_actor_id: Optional[str] = Field(default=None, description="需要响应的NPC ID")
    npc_intent: Optional[str] = Field(default=None, description="NPC响应意图描述")
    actionable_npcs: List[str] = Field(default_factory=list, description="建议本轮可行动NPC列表")


class DMAgentOutputV2(BaseModel):
    """Phase 3: 精简后的DM输出协议。"""

    turn_intent: TurnIntent
    response_to_player: Optional[str] = Field(default=None)


# ============================================================
# 状态推演系统模型
# ============================================================

class StateEvolutionInput(BaseModel):
    """状态推演系统输入"""
    system_prompt: str = Field(..., description="系统提示词")
    end_condition: str = Field(default="", description="结局条件")
    check_result: Optional[CheckOutput] = Field(default=None, description="鉴定结果")
    action_description: str = Field(default="", description="行动描述")
    game_context: Dict[str, Any] = Field(default_factory=dict, description="游戏上下文")
    is_npc_action: bool = Field(default=False, description="是否为NPC行动")
    npc_intent: Optional[str] = Field(default=None, description="NPC意图")
    npc_info: Optional[Dict[str, Any]] = Field(default=None, description="NPC信息")
    npc_response_mode: NpcResponseMode = Field(default=NpcResponseMode.UNIFIED, description="NPC响应模式")
    trigger_source: str = Field(default="unified", description="触发来源：unified")


class StateEvolutionOutput(BaseModel):
    """状态推演系统输出"""
    narrative: str = Field(..., description="生成的叙事文本")
    changes: List[StateChange] = Field(default_factory=list, description="状态变更列表")
    resolved: bool = Field(default=True, description="回合是否已解决")
    next_action_hint: Optional[str] = Field(default=None, description="下轮行动提示")
    is_end: bool = Field(default=False, description="是否游戏结束")
    end_narrative: str = Field(default="", description="结局描述")


# ============================================================
# 游戏状态模型
# ============================================================

class GameState(BaseModel):
    """游戏全局状态"""
    characters: Dict[str, Character] = Field(default_factory=dict, description="角色字典")
    items: Dict[str, Item] = Field(default_factory=dict, description="物品字典")
    maps: Dict[str, Map] = Field(default_factory=dict, description="地图字典")
    player_id: Optional[str] = Field(default=None, description="当前玩家角色ID")
    current_scene_id: Optional[str] = Field(default=None, description="当前场景ID")
    turn_order: List[str] = Field(default_factory=list, description="行动顺序列表（角色ID）")
    turn_count: int = Field(default=0, description="当前回合数")
    is_ended: bool = Field(default=False, description="游戏是否结束")

    def get_player(self) -> Optional[Character]:
        """获取玩家角色"""
        if self.player_id:
            return self.characters.get(self.player_id)
        return None
    
    def get_current_map(self) -> Optional[Map]:
        """获取当前地图"""
        player = self.get_player()
        if player and player.location:
            found = self.maps.get(player.location)
            if found:
                return found

        if self.current_scene_id:
            return self.maps.get(self.current_scene_id)
        return None


# ============================================================
# 导出所有模型
# ============================================================

__all__ = [
    # 基础类型
    "Description",
    "Memory",
    # 角色属性
    "CharacterAttributes",
    "CharacterStatus",
    # 实体
    "Character",
    "Item",
    "MapNeighbor",
    "MapEntities",
    "Map",
    # 变更
    "ChangeOperation",
    "StateChange",
    # 鉴定
    "CheckType",
    "CheckDifficulty",
    "CheckResult",
    "NpcResponseMode",
    "CheckInput",
    "CheckOutput",
    # Phase 1 协议
    "CheckPlan",
    "ActivationHint",
    "TurnIntent",
    "OutcomeSummary",
    "TurnResolution",
    "TurnStep",
    "TurnTrace",
    "WorldStateView",
    "DialogueMemoryEntry",
    "DialogueMemoryView",
    "NarrativeMemoryView",
    "TurnTraceView",
    "NarrativeMergerInputV2",
    "NarrativeMergerOutputV2",
    "TurnTraceDigest",
    "PersistenceSnapshotV2",
    "LLMRequestEnvelopeV2",
    "LLMResponseEnvelopeV2",
    # DM Agent
    "DMAgentInput",
    "DMAgentOutput",
    "DMAgentOutputV2",
    # 状态推演
    "StateEvolutionInput",
    "StateEvolutionOutput",
    # 游戏状态
    "GameState",
]
