# COC文字冒险游戏引擎 - 运行时详细规范

> 版本：v1.1  
> 状态：已更新（与代码实现同步）  
> 日期：2026-03-29  
> 适用范围：当前仓库代码所体现的实际运行时行为  
> 代码基线：以 `src/` 与 `tests/` 为准

---

## 目录

1. [文档定位与目标](#1-文档定位与目标)
2. [架构总览](#2-架构总览)
3. [核心数据模型](#3-核心数据模型)
4. [游戏引擎核心](#4-游戏引擎核心)
5. [输入处理系统](#5-输入处理系统)
6. [DM Agent系统](#6-dm-agent系统)
7. [规则系统](#7-规则系统)
8. [状态推演系统](#8-状态推演系统)
9. [NPC响应系统](#9-npc响应系统)
10. [叙事系统](#10-叙事系统)
11. [IO与持久化系统](#11-io与持久化系统)
12. [世界加载系统](#12-世界加载系统)
13. [配置与兼容层](#13-配置与兼容层)
14. [测试基线](#14-测试基线)

---

## 1. 文档定位与目标

### 1.1 文档目标

本文档基于当前代码实现，提供运行时系统的完整技术规范，包括：

- 引擎启动、加载、保存的完整流程
- 玩家输入处理的主链路详细说明
- NPC响应模式的语义与实现差异
- 状态变更的事务与回滚机制
- 各模块间的接口契约与数据流

### 1.2 规范来源

所有规范以代码实现为准，核心锚点文件：

| 模块 | 文件路径 | 关键行号 |
|------|----------|----------|
| GameEngine | `src/engine/game_engine.py` | 60-2700 |
| 数据模型 | `src/data/models.py` | 1-625 |
| 输入系统 | `src/agent/input_system.py` | 41-831 |
| NPC导演 | `src/agent/npc/npc_director.py` | 1-310 |
| 叙事合并 | `src/narrative/narrative_merger.py` | 1-230 |
| 世界加载 | `src/data/init/world_loader.py` | 1-474 |
| IO系统 | `src/data/io_system.py` | 68-981 |
| 上下文构建器 | `src/engine/context_builders.py` | 1-156 |

---

## 2. 架构总览

### 2.1 系统架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                         GameEngine                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │  生命周期管理 │  │  回合循环    │  │      配置管理           │  │
│  │  new_game   │  │  process_   │  │  apply_world_settings   │  │
│  │  load_game  │  │   input     │  │  set_npc_response_mode  │  │
│  │  save_game  │  │             │  │                         │  │
│  └─────────────┘  └──────┬──────┘  └─────────────────────────┘  │
└──────────────────────────┼──────────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌────────────┐  ┌────────────┐  ┌────────────┐
    │InputSystem │  │  DMAgent   │  │RuleSystem  │
    │ 输入解析    │  │ 意图解析   │  │ 鉴定计算   │
    └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
          │               │               │
          └───────────────┼───────────────┘
                          ▼
                  ┌──────────────┐
                  │StateEvolution│
                  │  状态推演    │
                  └──────┬───────┘
                         │
           ┌─────────────┼─────────────┐
           ▼             ▼             ▼
    ┌──────────┐  ┌──────────┐  ┌──────────┐
    │NPCDirector│  │Narrative │  │IOSystem  │
    │ NPC规划   │  │ Merger   │  │ 持久化   │
    └──────────┘  └──────────┘  └──────────┘
```

### 2.2 核心设计原则

#### 2.2.1 真值原则
- **状态真值**：以 `GameState` + 持久化IO层为唯一真值来源
- **叙事非真值**：叙事文本仅用于展示，不定义状态
- **变更原子性**：所有状态变更通过 `StateChange` 对象批量应用

#### 2.2.2 降级原则
- 每个LLM调用点必须有规则兜底路径
- `NPCDirector` 失败时回退 `_fallback_decision()`
- `NarrativeMerger` 失败时回退纯文本拼接

#### 2.2.3 事务原则
- 批量状态变更必须整体成功或整体回滚
- 失败时恢复事务快照并重新持久化

---

## 3. 核心数据模型

### 3.1 实体模型

#### 3.1.1 Character（角色）

```python
class Character(BaseModel):
    id: str                          # 唯一标识符，格式：char-<name>-<number>
    name: str                        # 显示名称
    basic_info: str                  # 背景简介
    description: Description         # 二级描述系统
    location: str                    # 所在地图ID
    inventory: List[str]             # 背包物品ID列表
    status: CharacterStatus          # 动态状态（HP/SAN等）
    attributes: CharacterAttributes  # COC七大属性
    memory: Memory                   # 记忆系统
    is_player: bool                  # 是否为玩家角色
```

#### 3.1.2 Item（物品）

```python
class Item(BaseModel):
    id: str                    # 唯一标识符，格式：item-<name>-<number>
    name: str                  # 显示名称
    description: Description   # 二级描述系统
    location: str              # 位置（地图ID或角色ID）
    is_portable: bool          # 是否可携带
```

#### 3.1.3 Map（地图/场景）

```python
class Map(BaseModel):
    id: str                    # 唯一标识符，格式：map-<name>-<number>
    name: str                  # 显示名称
    parent_id: Optional[str]   # 父级区域ID
    description: Description   # 二级描述系统
    neighbors: List[MapNeighbor]   # 相邻地图连接
    entities: MapEntities      # 场景内实体（角色/物品）
```

### 3.2 二级描述系统

```python
class Description(BaseModel):
    public: List[Dict[str, str]]  # 公开描述列表
    add: List[Dict[str,str]] #修改建议:将公开描述和增加描述分离
    hint: str                     # AI专用隐藏提示
```

**归一化规则**：
- 历史脏数据自动收敛为列表结构
- 支持字符串、字典、列表多种输入格式
- 空值自动转为空列表

### 3.3 状态变更模型

```python
class StateChange(BaseModel):
    id: str                    # 实体ID
    field: str                 # 字段路径（支持点分，如attributes.hp）
    operation: ChangeOperation # 操作类型
    value: Any                 # 新值

class ChangeOperation(str, Enum):
    UPDATE = "update"    # 更新字段
    ADD = "add"          # 向列表添加
    DELETE = "del"       # 从列表删除或置空
    MOVE = "move"        # 移动操作（主要用于location字段）
```

### 3.4 游戏状态模型

```python
class GameState(BaseModel):
    characters: Dict[str, Character]     # 角色字典
    items: Dict[str, Item]               # 物品字典
    maps: Dict[str, Map]                 # 地图字典
    player_id: Optional[str]             # 当前玩家角色ID
    current_scene_id: Optional[str]      # 当前场景ID
    turn_order: List[str]                # 行动顺序列表
    turn_count: int                      # 当前回合数
    is_ended: bool                       # 游戏是否结束
```

### 3.5 Phase 1 新协议模型（v2.0）

#### 3.5.1 意图解释模型

```python
class TurnIntent(BaseModel):
    """E3: 意图解释"""
    actor_id: str
    raw_input_text: str          # E2: 原始输入
    intent_text: str             # 系统解释
    interaction_type: Literal["action", "dialogue", "mixed"]
    check_plan: Optional[CheckPlan]
    activation_hint: ActivationHint

class CheckPlan(BaseModel):
    """E4: 检定计划"""
    check_needed: bool
    check_type: Optional[str]
    attributes: Optional[List[str]]
    target_id: Optional[str]
    difficulty: Optional[str]

class ActivationHint(BaseModel):
    """NPC激活建议"""
    response_needed_hint: bool
    preferred_actor_id: Optional[str]
    npc_intent_hint: Optional[str]
    candidate_npc_ids_hint: Optional[List[str]]
```

#### 3.5.2 步骤结算模型

```python
class TurnResolution(BaseModel):
    """E5: 步骤结算"""
    actor_id: str
    phase: Literal["player", "npc"]
    intent_text: str
    check_result: Optional[CheckOutput]
    state_changes: List[StateChange]
    local_narrative: str
    outcome: OutcomeSummary

class OutcomeSummary(BaseModel):
    """步骤结果摘要"""
    action_succeeded: bool
    outcome_type: str
    consequence_tags: List[str] = Field(default_factory=list)

class TurnStep(BaseModel):
    """E6: 回合步骤"""
    step_id: str
    turn_id: int
    actor_id: str
    phase: Literal["player", "npc"]
    trigger_source: str
    intent: TurnIntent
    resolution: TurnResolution
    timestamp: datetime

class TurnTrace(BaseModel):
    """E6: 回合因果链（关键缺失要素）"""
    turn_id: int
    steps: List[TurnStep]
    
    def append_step(self, step: TurnStep) -> None:
        """NPC执行后立即追加，供后续NPC读取"""
        
    def get_steps_for_actor(self, actor_id: str) -> List[TurnStep]:
        """获取特定角色的步骤历史"""
```

#### 3.5.3 上下文视图模型

```python
class WorldStateView(BaseModel):
    """E1: 受控世界视图"""
    current_map: Optional[Dict[str, Any]]
    nearby_characters: List[Dict[str, Any]]
    nearby_items: List[Dict[str, Any]]
    player_state: Optional[Dict[str, Any]]
    available_exits: List[Dict[str, Any]]

class DialogueMemoryEntry(BaseModel):
    """结构化对话记忆条目"""
    speaker: str
    content: str

class DialogueMemoryView(BaseModel):
    """E8: 对话记忆视图"""
    recent_dialogues: List[DialogueMemoryEntry]

class NarrativeMemoryView(BaseModel):
    """E8: 叙事记忆视图"""
    summary_lines: List[str]
    key_facts: List[str]
    stable_facts: List[str]

class TurnTraceView(BaseModel):
    """E6: 面向推理侧的回合因果链视图"""
    turn_id: int
    steps: List[TurnStep]
```

#### 3.5.4 叙事合并v2协议

```python
class NarrativeMergerInputV2(BaseModel):
    """Phase 6: 叙事合并输入协议"""
    turn_trace_steps: List[TurnStep]
    turn_truth_anchor: Dict[str, Any]
    narrative_memory: NarrativeMemoryView

class NarrativeMergerOutputV2(BaseModel):
    """Phase 6: 叙事合并输出协议"""
    merged_narrative: str
    turn_summary: str
    new_key_facts: List[str]
    dialogue_updates: List[DialogueMemoryEntry]

class TurnTraceDigest(BaseModel):
    """Phase 7: 持久化用回合链摘要"""
    turn_id: int
    summary: str
    actor_ids: List[str]
```

#### 3.5.5 LLM请求信封v2

```python
class LLMRequestEnvelopeV2(BaseModel):
    """Generic V2 request envelope for LLM-facing protocols"""
    schema_version: str = Field(default="2.0")
    request_id: str
    turn_id: int
    phase: str
    source: str = Field(default="engine")
    payload: Dict[str, Any]
    constraints: Dict[str, Any]
    memory_policy: Dict[str, Any]
    extensions: Dict[str, Any]
```

---

## 4. 游戏引擎核心

### 4.1 引擎初始化

```python
GameEngine(
    io_system: Optional[IOSystem] = None,
    input_system: Optional[InputSystem] = None,
    dm_agent: Optional[DMAgent] = None,
    rule_system: Optional[RuleSystem] = None,
    state_agent: Optional[StateEvolutionAgent] = None,
    db_path: str = "data/game.db",
    npc_response_mode: str = "unified",
    narrative_window: int = 5,
)
```

### 4.2 生命周期管理

#### 4.2.1 新游戏启动

```python
def new_game(world_name: str = "mysterious_library") -> bool
```

**流程**：
1. 调用 `io.clear_runtime_store()` 清空运行库
2. 调用 `WorldLoader` 加载世界配置
3. 应用世界级配置（`apply_world_settings`）
4. 初始化 `turn_count = 1`
5. 初始化 `TurnTrace` 和上下文构建器

#### 4.2.2 存档加载

```python
def load_game(save_name: str = "auto_save") -> bool
```

**加载内容**：
- `GameState` 完整状态
- `dm_dialogue_log` 对话历史
- `narrative_context` 叙事上下文
- `recent_turn_trace_digests` 回合链摘要（v2新增）
- `world_metadata` 世界元数据
- `dialogue_memory` 对话记忆（v2新增）
- `narrative_memory` 叙事记忆（v2新增）

#### 4.2.3 存档保存

```python
def save_game(save_name: str = "auto_save") -> bool
```

**保存内容**：
- `GameState` 序列化数据
- `dm_dialogue_log` 对话记录
- `narrative_context` 状态快照
- `dialogue_memory` 对话记忆（v2新增）
- `narrative_memory` 叙事记忆（v2新增）
- `recent_turn_trace_digests` 回合链摘要（v2新增）
- `save_version` 版本标记（v2 = 2）
- `world_metadata` 世界元数据

### 4.3 核心游戏循环

#### 4.3.1 主入口

```python
def process_input(self, user_input: str) -> Dict[str, Any]
```

**返回结构**：
```python
{
    "response": str,        # 直接回复文本
    "check_result": dict,   # 鉴定结果（如有）
    "narrative": str,       # 叙事文本
    "success": bool,        # 处理是否成功
    "game_over": bool,      # 游戏是否结束
}
```

#### 4.3.2 完整回合流程（v2更新）

```
Step 1: _turn_start()
        └── 清空所有角色 current_event
        └── 初始化/维护行动队列
        └── 确定当前行动者

Step 2: _begin_turn_trace()
        └── 初始化本回合的 TurnTrace

Step 3: InputSystem.parse_input()
        └── 区分基础命令 vs 自然语言
        └── 基础命令直接执行并返回

Step 4: DMAgent.parse_intent()
        └── 解析玩家意图（输出包含 interaction_type）
        └── 判定是否需要鉴定
        └── 判定是否需要NPC响应

Step 5: _build_turn_intent_from_dm()
        └── 将 DMAgentOutput 转换为 TurnIntent

Step 6: RuleSystem.execute_check() (可选)
        └── 执行规则鉴定
        └── 返回 CheckOutput

Step 7: StateEvolution.evolve_player_action()
        └── 生成叙事文本
        └── 生成状态变更列表
        └── 判定是否触发结局
        └── 使用 WorldStateView/DialogueMemoryView/NarrativeMemoryView/TurnTraceView

Step 8: _apply_changes()
        └── 批量应用状态变更
        └── 失败时回滚事务

Step 9: 组装 player_turn_resolution 并写入 TurnTrace

Step 10: _process_unified_npc_response()
         └── NPCDirector 规划NPC行动
         └── StateEvolution 推演NPC行动
         └── 应用NPC状态变更
         └── 将NPC步骤写入 TurnTrace

Step 11: _merge_turn_narratives()
         └── 使用 NarrativeMerger.merge_v2()（基于 TurnTrace）
         └── 或降级到纯文本拼接

Step 12: 结局判定
         └── StateEvolutionOutput.is_end
         └── state_agent.check_end_condition()
         └── 配置化结局规则兜底

Step 13: _turn_end()
         └── 更新行动队列
         └── 增加回合数

Step 14: _finalize_turn_trace()
         └── 生成本回合摘要
         └── 保存到 recent_turn_trace_digests
```

### 4.4 事务与回滚

#### 4.4.1 变更应用流程

```python
def _apply_changes(self, changes: List[StateChange]) -> List[str]:
    transaction_snapshot = self._capture_transaction_snapshot()
    canonical_changes = self._canonicalize_change_batch(changes)
    failures: List[str] = []
    
    for normalized_change in canonical_changes:
        error_code = self.io.apply_state_change(normalized_change)
        
        if error_code == 0:
            self._sync_state_change(normalized_change)
        else:
            failures.append(error_message)
            self._restore_transaction_snapshot(transaction_snapshot)
            break
    
    return failures
```

#### 4.4.2 变更归一化

```python
def _canonicalize_change_batch(self, changes: List[StateChange]) -> List[StateChange]:
    """Normalize and deduplicate a batch to avoid redundant dual-writes in one turn."""
```

**功能**：
- 归一化所有变更
- 提取 location 目标映射
- 去除冗余的关系变更（如已由 location 变更隐含的 inventory 变更）
- 去重

#### 4.4.3 回滚机制

```python
def _restore_transaction_snapshot(self, snapshot: Dict[str, Any]) -> None:
    # 1. 恢复内存状态
    game_state_data = snapshot.get("game_state", {})
    self.game_state = GameState(**copy.deepcopy(sanitized_state))
    
    # 2. 重新持久化
    persist_method = getattr(self.io, "save_game_state", None)
    if callable(persist_method):
        persist_result = persist_method(self.game_state)
```

### 4.5 上下文构建器（Phase 2新增）

```python
# src/engine/context_builders.py

class WorldStateViewBuilder:
    """构建受控世界视图（E1）"""
    def build(self, game_state: GameState, actor_id: str) -> WorldStateView:
        pass

class DialogueMemoryBuilder:
    """构建对话记忆视图（E8）"""
    def build(self, dialogue_log: List[Dict[str, str]]) -> DialogueMemoryView:
        pass

class NarrativeMemoryBuilder:
    """构建叙事记忆视图（E8）"""
    def build(self, narrative_payload: Dict[str, Any]) -> NarrativeMemoryView:
        pass

class TurnTraceContextBuilder:
    """构建回合因果链视图（E6）"""
    def build_for_npc(self, turn_trace: TurnTrace, npc_id: str) -> TurnTraceView:
        """NPC看到的是：玩家步骤 + 已执行的前序NPC步骤"""
        
    def build_full(self, turn_trace: TurnTrace) -> TurnTraceView:
        """构建完整视图"""
```

---

## 5. 输入处理系统

### 5.1 输入分类

| 输入类型 | 识别规则 | 处理方式 |
|----------|----------|----------|
| 空输入 | `user_input.strip() == ""` | 返回错误提示 |
| 基础命令 | 以 `\` 开头 | 解析并执行命令 |
| 兼容命令 | 以 `/` 开头且命中已知命令 | 按基础命令处理 |
| 自然语言 | 其他所有输入 | 传递给DM Agent |

### 5.2 基础命令列表

```python
BASIC_COMMANDS = {
    "look": "查看当前场景或指定目标",
    "inventory": "查看背包",
    "pickup": "捡起物品",
    "drop": "放下物品",
    "use": "使用物品",
    "give": "给予物品给角色",
    "move": "移动到相邻场景",
    "go": "移动到相邻场景（move别名）",
    "status": "查看自身状态",
    "where": "查看当前位置",
    "save": "保存进度",
    "load": "加载进度",
    "reset": "重置游戏",
    "debug": "切换调试模式",
    "help": "显示帮助",
    "exit": "退出游戏",
}
```

### 5.3 命令执行语义

#### 5.3.1 系统命令特殊处理

以下命令由引擎层补充处理其系统语义：

| 命令 | 引擎处理 |
|------|----------|
| `save` | 调用 `engine.save_game()` |
| `load` | 调用 `engine.load_game()` |
| `reset` | 调用 `engine.restart()` |
| `debug` | 切换日志级别 |
| `exit` | 设置 `game_over = True` |

#### 5.3.2 状态变更命令

`pickup`, `drop`, `give`, `move` 等命令产生 `StateChange` 列表，必须经过统一 `_apply_changes()` 事务写入。

---

## 6. DM Agent系统

### 6.1 核心职责

- 解析玩家自然语言输入为结构化意图
- 判定是否需要规则鉴定
- 指定鉴定类型、属性、难度
- 判定是否需要NPC响应

### 6.2 输出模型

```python
class DMAgentOutput(BaseModel):
    interaction_type: Literal["action", "dialogue", "mixed"]  # 交互类型（v2新增）
    is_dialogue: bool                    # 是否为纯对话
    response_to_player: str              # 给玩家的回复
    needs_check: bool                    # 是否需要鉴定
    check_type: Optional[str]            # 鉴定类型
    check_attributes: List[str]          # 鉴定属性
    check_target: Optional[str]          # 对抗目标ID
    difficulty: Optional[str]            # 难度
    action_description: str              # 行动描述
    npc_response_needed: bool            # 是否需要NPC响应
    npc_actor_id: Optional[str]          # 响应NPC ID
    npc_intent: Optional[str]            # NPC响应意图
    actionable_npcs: List[str]           # 可行动NPC列表
```

### 6.3 DMAgent V2 输出协议

```python
class DMAgentOutputV2(BaseModel):
    """Phase 3: 精简后的DM输出协议"""
    turn_intent: TurnIntent
    response_to_player: Optional[str]
```

### 6.4 纯对话语义

```python
interaction_type = str(getattr(dm_output, "interaction_type", "action") or "action")
is_dialogue_turn = interaction_type in {"dialogue", "mixed"}
has_player_action = interaction_type in {"action", "mixed"}

if is_dialogue_turn:
    result["response"] = dm_output.response_to_player
    if not dm_output.npc_response_needed and not has_player_action:
        return result  # 直接结束
```

### 6.5 错误反馈与重试

DM Agent支持最多2次重试，错误反馈通过 `erro` 字段传递：

```python
for attempt in range(1, 3):
    response = self.llm_service.call_llm_json(prompt, schema)
    if not response.get("success"):
        error_feedback = response.get("error")
        continue
    
    validation_error = self._validate_output(output, game_state)
    if not validation_error:
        return output
    
    error_feedback = validation_error
```

---

## 7. 规则系统

### 7.1 鉴定类型

```python
class CheckType(str, Enum):
    REGULAR = "非对抗鉴定"
    OPPOSED = "对抗鉴定"
```

### 7.2 难度等级

```python
class CheckDifficulty(str, Enum):
    REGULAR = "常规"      # 目标值 = 属性值 × 5
    HARD = "困难"         # 目标值 = 属性值 × 5 // 2
    EXTREME = "极难"      # 目标值 = 属性值 × 5 // 5
```

### 7.3 结果等级

```python
class CheckResult(str, Enum):
    CRITICAL_SUCCESS = "大成功"  # 骰子 == 1 或 <= 目标值/5
    SUCCESS = "成功"             # 骰子 <= 目标值
    FAILURE = "失败"             # 骰子 > 目标值
    FUMBLE = "大失败"            # 骰子 == 100 或 (目标值<50 且 >=96)
```

### 7.4 属性映射

| 属性名 | 计算方式 |
|--------|----------|
| str, con, siz, dex, app, int, pow, edu | 属性值 × 5 |
| hp, san, lucky | 直接使用原始值 |
| luck | lucky 的别名 |

### 7.5 对抗鉴定规则

1. 双方各自进行鉴定
2. 成功等级高者获胜
3. 成功等级相同：目标值高者胜
4. 都失败：目标值高者胜

---

## 8. 状态推演系统

### 8.1 核心职责

- 将鉴定结果转化为叙事文本
- 生成状态变更列表（`StateChange`）
- 判定是否触发游戏结局
- 支持玩家和NPC行动推演

### 8.2 输出模型

```python
class StateEvolutionOutput(BaseModel):
    narrative: str                       # 生成的叙事文本
    changes: List[StateChange]           # 状态变更列表
    resolved: bool                       # 回合是否已解决
    next_action_hint: Optional[str]      # 下轮行动提示
    is_end: bool                         # 是否游戏结束
    end_narrative: str                   # 结局描述
```

### 8.3 玩家行动推演

```python
def evolve_player_action(
    self,
    check_result: Optional[CheckOutput],
    action_description: str,
    game_state: GameState,
    additional_context: Optional[Dict[str, Any]] = None
) -> StateEvolutionOutput
```

**additional_context 包含**（v2更新）：
- `world_state_view`: WorldStateView 字典
- `dialogue_memory`: DialogueMemoryView 字典
- `narrative_memory`: NarrativeMemoryView 字典
- `turn_trace_so_far`: TurnTraceView 字典
- `player_resolution_anchor`: 玩家结算锚点
- `npc_response_expected`: bool
- `npc_response_actor_id`: str

### 8.4 NPC行动推演

```python
def evolve_npc_action(
    self,
    npc_id: str,
    game_state: GameState,
    check_result: Optional[CheckOutput] = None,
    npc_intent: Optional[str] = None,
    additional_context: Optional[Dict[str, Any]] = None
) -> StateEvolutionOutput
```

### 8.5 变更验证

状态推演系统包含变更验证逻辑，确保：
- 实体ID存在
- 字段路径有效
- 操作类型合法（支持 update/add/del/move）
- 值类型正确
- location 字段必须使用 MOVE 操作

---

## 9. NPC响应系统

### 9.1 响应模式（已收敛）

```python
class NpcResponseMode(str, Enum):
    """NPC响应模式（收敛后仅保留 unified）"""
    UNIFIED = "unified"    # 统一后置响应（唯一模式）
```

**注意**：`queue` 和 `reactive` 模式已在代码中收敛为 `unified`，文档中提及的多种模式仅为兼容说明。

### 9.2 NPC导演（NPCDirector）

#### 9.2.1 文件位置

- 主要实现：`src/agent/npc/npc_director.py`
- 兼容导入：`src/npc/npc_director.py`（仅重导出）

#### 9.2.2 核心职责

- 生成结构化NPC行动计划
- 支持批量NPC决策
- 提供LLM和规则两种决策路径

#### 9.2.3 输出模型

```python
class NPCActionForm(BaseModel):
    npc_id: str                          # NPC角色ID
    action_type: NPCActionType           # 行动类型
    target_id: Optional[str]             # 目标ID
    intent_description: str              # 意图描述
    expected_outcome: Optional[str]      # 预期结果
    check: NPCCheckPlan                  # 检定计划
    trigger_source: str                  # 触发来源
    metadata: Dict[str, Any]             # 元数据

class NPCActionDecision(BaseModel):
    actions: Dict[str, NPCActionForm]    # NPCID -> 行动计划
    rationale: str                       # 决策理由
```

#### 9.2.4 行动类型

```python
class NPCActionType(str, Enum):
    ATTACK = "attack"
    MOVE = "move"
    TALK = "talk"
    USE_ITEM = "use_item"
    INVESTIGATE = "investigate"
    WAIT = "wait"
    CUSTOM = "custom"
```

#### 9.2.5 降级策略

```python
def _fallback_decision(...):
    # 默认 WAIT
    action_type = NPCActionType.WAIT
    intent_description = "保持观察，等待局势变化"
    
    # 如果 player_intent.npc_response_needed == true
    if player_intent and player_intent.npc_response_needed:
        action_type = NPCActionType.TALK
        target_id = player_id
        intent_description = player_intent.npc_intent or "对玩家刚刚的行动做出回应"
```

### 9.3 NPC候选选择顺序

1. `dm_output.actionable_npcs` - DM建议的可行动NPC
2. `dm_output.npc_actor_id` - DM指定的响应NPC
3. `_action_queue` 中首个可行动NPC
4. `_pick_default_npc_actor()` - 同场景可行动NPC兜底

### 9.4 统一响应流程

```python
def _process_unified_npc_response(...):
    # 1. 判定是否触发
    should_trigger = self._npc_response_mode in {"queue", "unified"} or dm_output.npc_response_needed
    
    # 2. 收集候选NPC
    candidate_ids = [...]
    
    # 3. NPCDirector 规划行动
    plans = self._plan_npc_actions(trigger=trigger_label, ...)
    
    # 4. 按动态队列顺序执行
    for npc_id in ordered_npc_ids:
        # 执行检定
        npc_check = self._execute_npc_check(npc)
        # 推演行动
        npc_output = self.state_agent.evolve_npc_action(...)
        # 应用变更
        failures = self._apply_changes(npc_output.changes)
        # 写入 TurnTrace
        self._current_turn_trace.append_step(TurnStep(...))
```

---

## 10. 叙事系统

### 10.1 叙事上下文（NarrativeContext）

#### 10.1.1 存储结构

```python
class NarrativeContext:
    window_size: int                     # 窗口大小
    max_summary_lines: int               # 最大摘要行数
    max_context_chars: int               # 最大上下文字符数
    recent_events: List[NarrativeEvent]  # 近期事件
    summary_lines: List[str]             # 摘要行
    key_facts: Set[str]                  # 关键事实
```

#### 10.1.2 事件模型

```python
class NarrativeEvent(BaseModel):
    turn: int
    actor_id: str
    actor_name: str
    text: str
    source: str                          # 来源：turn_merged, npc_queue, npc_reactive
    key_facts: List[str]
```

### 10.2 叙事合并（NarrativeMerger）

#### 10.2.1 合并策略（v2更新）

```python
def merge(self, fragments, game_state, context, truth_anchor):
    """Legacy merge method"""
    cleaned = [f for f in fragments if f.get("text")]
    
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]["text"]
    
    if self.llm_service:
        merged = self._merge_with_llm(cleaned, ...)
        if merged:
            return merged
    
    # 降级：纯文本拼接
    return "\n".join(fragment["text"] for fragment in cleaned)

def merge_v2(
    self,
    turn_trace_steps: List[TurnStep],
    turn_truth_anchor: Optional[Dict[str, Any]] = None,
    narrative_memory: Optional[NarrativeMemoryView] = None,
) -> NarrativeMergerOutputV2:
    """Phase 6 merger API, returns structured output"""
```

#### 10.2.2 真值锚点

```python
def _build_player_resolution_anchor(...):
    return {
        "check_required": bool,
        "check_outcome": str,              # "大成功"/"成功"/"失败"/"大失败"
        "action_succeeded": bool,
        "action_description": str,
        "consistency_rule": "下游NPC决策与叙事必须与check_outcome保持一致",
        "check_result": CheckOutput,
        "player_narrative": str,
        "player_changes": List[StateChange],
    }
```

---

## 11. IO与持久化系统

### 11.1 存储模式

```python
class IOSystem:
    mode: str  # "sqlite" 或 "json"
```

#### 11.1.1 SQLite模式

- 使用 SQLAlchemy ORM
- 表结构：characters, items, maps, game_meta
- 启用外键约束

#### 11.1.2 JSON模式

- 目录结构：
  ```
  data/json/
  ├── characters/
  ├── items/
  ├── maps/
  └── game_state.json
  ```

### 11.2 错误码定义

```python
ERROR_SUCCESS = 0           # 成功
ERROR_ID_NOT_FOUND = 1      # 实体不存在
ERROR_FIELD_NOT_FOUND = 2   # 字段不存在
ERROR_OPERATION_INVALID = 3 # 操作无效
ERROR_OTHER = 4             # 其他错误
```

### 11.3 关系同步

#### 11.3.1 物品位置变更

当物品 `location` 变更时，自动同步：
- 从原持有者（角色/地图）的 inventory/items 中移除
- 添加到新持有者的 inventory/items 中

#### 11.3.2 角色背包变更

当角色 `inventory` 变更时，自动同步：
- 新增物品的位置设为角色ID
- 移除物品的位置清空

### 11.4 current_event管理

```python
def clear_current_events(self) -> int:
    """每轮开始时调用，清空所有角色的current_event并入log"""
```

---

## 12. 世界加载系统

### 12.1 WorldBundle

```python
@dataclass
class WorldBundle:
    game_state: GameState
    world_name: str
    end_condition: str
    npc_response_mode: str = "unified"
    narrative_window: int = 5
    npc_director_use_llm: bool = True
    narrative_merge_use_llm: bool = True
```

### 12.2 世界配置结构

```
config/world/<world_name>/
├── world.json              # 世界清单
├── characters/             # 角色配置
│   ├── char-player-01.json
│   └── char-npc-01.json
├── items/                  # 物品配置
│   └── item-key-01.json
├── maps/                   # 地图配置
│   └── map-room-01.json
└── endings/                # 结局规则
    └── ending_death.json
```

### 12.3 world.json字段

```json
{
  "world_id": "world-mysterious-library",
  "world_name": "mysterious_library",
  "player_id": "char-player-01",
  "start_map_id": "map-room-library-01",
  "turn_order": ["char-player-01", "char-guard-01"],
  "narrative_window": 5,
  "npc_response_mode": "unified",
  "npc_director_use_llm": true,
  "narrative_merge_use_llm": true,
  "end_condition": "...",
  "entry_scene_narrative": "..."
}
```

### 12.4 兼容层

支持两种格式：
1. **新版目录化**：分目录存储实体
2. **旧版单表**：`characters.json`, `items.json`, `maps.json`

---

## 13. 配置与兼容层

### 13.1 LLM开关

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `npc_director_use_llm` | NPCDirector是否使用LLM | `true` |
| `narrative_merge_use_llm` | NarrativeMerger是否使用LLM | `true` |

### 13.2 兼容处理

| 兼容项 | 处理方式 |
|--------|----------|
| 旧世界格式 | `WorldLoader` 自动检测并回退 |
| `/help` 命令 | `InputSystem.parse_input()` 兼容处理 |
| `npc_intent` 兜底 | 结构化plan缺失时使用 |
| narrative snapshot | 旧 `summary` 字段迁移到 `summary_lines` |

### 13.3 结局规则配置

结局规则文件：`config/world/<world_name>/endings/*.json`

```json
{
  "condition_expr": "player_hp_le_0",
  "end_narrative": "你因伤势过重而倒下...",
  "priority": 10
}
```

**条件表达式支持**：
- `player_hp_le_0` - 玩家HP <= 0
- `player_san_le_0` - 玩家SAN <= 0
- `player_at:<map_id>` - 玩家位于指定地图
- `has_item:<item_id>` - 玩家拥有指定物品
- `all(a,b,c)` - 所有条件满足
- `any(a,b,c)` - 任一条件满足

---

## 14. 测试基线

### 14.1 测试文件清单

| 测试文件 | 测试内容 |
|----------|----------|
| `test_priority.py` | 行动优先级排序 |
| `test_npc_director.py` | NPCDirector规划接入 |
| `test_narrative_merger.py` | 叙事合并降级与LLM路径 |
| `test_narrative_context.py` | 叙事上下文管理 |
| `test_regression_flow.py` | 运行主流程、配置、兼容、回滚 |
| `test_architecture_refactor_increment.py` | 架构重构增量测试 |
| `test_llm_json_retry.py` | LLM JSON重试机制 |
| `test_state_evolution_error_feedback.py` | 状态演化错误反馈 |

### 14.2 关键测试场景

#### 14.2.1 优先级测试

```python
def test_priority_order_is_dex_then_hp_ratio_then_san_ratio_then_id():
    # 验证排序键：dex降序 -> hp/max_hp降序 -> san/100降序 -> id升序
```

#### 14.2.2 NPCDirector测试

```python
def test_queue_mode_plans_action_through_director():
    # 验证queue模式下NPCDirector生成行动计划

def test_reactive_mode_uses_structured_plan_intent():
    # 验证reactive模式下使用结构化plan的intent
```

#### 14.2.3 事务回滚测试

```python
def test_transaction_rollback_on_failure():
    # 验证批量变更失败时回滚事务快照
```

---

## 附录A：代码引用索引

### A.1 核心流程锚点

| 功能 | 文件 | 行号 |
|------|------|------|
| 主入口 | `game_engine.py` | 388 |
| 回合开始 | `game_engine.py` | 771 |
| 回合Trace开始 | `game_engine.py` | 790 |
| DM Agent解析 | `game_engine.py` | 947 |
| 状态推演 | `game_engine.py` | 1054 |
| 变更应用 | `game_engine.py` | 1127 |
| 回合结束 | `game_engine.py` | 1841 |
| 回合Trace结束 | `game_engine.py` | 794 |
| NPC响应模式设置 | `game_engine.py` | 1352 |
| 动态队列构建 | `game_engine.py` | 1917 |
| 叙事合并 | `game_engine.py` | 1903 |
| 统一NPC响应 | `game_engine.py` | 1986 |

### A.2 数据模型锚点

| 模型 | 文件 | 行号 |
|------|------|------|
| StateChange | `models.py` | 230 |
| ChangeOperation | `models.py` | 222 |
| NpcResponseMode | `models.py` | 263 |
| DMAgentOutput | `models.py` | 480 |
| DMAgentOutputV2 | `models.py` | 500 |
| StateEvolutionOutput | `models.py` | 525 |
| GameState | `models.py` | 539 |
| TurnIntent | `models.py` | 309 |
| TurnResolution | `models.py` | 328 |
| TurnStep | `models.py` | 340 |
| TurnTrace | `models.py` | 355 |
| NPCActionForm | `npc_planning_models.py` | 40 |
| NPCActionDecision | `npc_planning_models.py` | 60 |
| NarrativeMergerInputV2 | `models.py` | 406 |
| NarrativeMergerOutputV2 | `models.py` | 414 |
| LLMRequestEnvelopeV2 | `models.py` | 441 |

### A.3 上下文构建器锚点

| 构建器 | 文件 | 行号 |
|--------|------|------|
| WorldStateViewBuilder | `context_builders.py` | 18 |
| DialogueMemoryBuilder | `context_builders.py` | 109 |
| NarrativeMemoryBuilder | `context_builders.py` | 124 |
| TurnTraceContextBuilder | `context_builders.py` | 143 |

---

## 附录B：术语表

| 术语 | 说明 |
|------|------|
| COC | Call of Cthulhu，克苏鲁的呼唤TRPG规则 |
| DM | Dungeon Master，游戏主持人 |
| StateChange | 状态变更对象，描述单一字段的变更 |
| NPCDirector | NPC导演，负责规划NPC行动 |
| StateEvolution | 状态推演，将检定结果转化为叙事和变更 |
| Resolution Anchor | 真值锚点，确保NPC响应与玩家检定结果一致 |
| current_event | 角色当前回合事件，每轮开始时清空 |
| turn_order | 行动顺序列表，存储于GameState |
| action_queue | 动态行动队列，引擎内部使用 |
| TurnTrace | 回合因果链，记录本回合所有步骤 |
| TurnStep | 回合步骤，包含意图和结算 |
| TurnIntent | 意图解释，E3要素 |
| TurnResolution | 步骤结算，E5要素 |
| WorldStateView | 受控世界视图，E1要素 |
| DialogueMemoryView | 对话记忆视图，E8要素 |
| NarrativeMemoryView | 叙事记忆视图，E8要素 |

---

## 附录C：版本变更记录

### v1.0 (2026-03-24)
- 初始版本

### v1.1 (2026-03-29)
- 添加 Phase 1 新协议模型（TurnIntent, TurnResolution, TurnStep, TurnTrace等）
- 更新 NPC响应模式为 unified 单一模式
- 添加 ChangeOperation.MOVE 操作
- 更新 DMAgentOutput 添加 interaction_type 字段
- 添加 DMAgentOutputV2, NarrativeMergerInputV2, NarrativeMergerOutputV2
- 添加 LLMRequestEnvelopeV2 协议
- 添加 context_builders.py 模块描述
- 更新游戏循环流程，添加 TurnTrace 相关步骤
- 更新存档格式，添加 dialogue_memory, narrative_memory, recent_turn_trace_digests
- 更新测试基线列表

---

*文档结束*
