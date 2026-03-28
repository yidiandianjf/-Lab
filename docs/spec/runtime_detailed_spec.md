# COC文字冒险游戏引擎 - 运行时详细规范

> 版本：v1.0  
> 状态：正式版  
> 日期：2026-03-24  
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
| GameEngine | `src/engine/game_engine.py` | 50-1890 |
| 数据模型 | `src/data/models.py` | 1-413 |
| 输入系统 | `src/agent/input_system.py` | 41-833 |
| NPC导演 | `src/agent/npc/npc_director.py` | 62-243 |
| 叙事上下文 | `src/narrative/narrative_context.py` | 31-164 |
| 叙事合并 | `src/narrative/narrative_merger.py` | 12-81 |
| 世界加载 | `src/data/init/world_loader.py` | 22-474 |
| IO系统 | `src/data/io_system.py` | 68-981 |

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
1. 清空现有状态
2. 调用 `WorldLoader` 加载世界配置
3. 应用世界级配置（`apply_world_settings`）
4. 初始化 `turn_count = 1`

#### 4.2.2 存档加载

```python
def load_game(save_name: str = "auto_save") -> bool
```

**加载内容**：
- `GameState` 完整状态
- `dm_dialogue_log` 对话历史
- `narrative_context` 叙事上下文
- `world_metadata` 世界元数据

**兼容处理**：
- `world_metadata` 缺失时从旧字段回退重建
- narrative snapshot 恢复时兼容旧 `summary` 到 `summary_lines`

#### 4.2.3 存档保存

```python
def save_game(save_name: str = "auto_save") -> bool
```

**保存内容**：
- `GameState` 序列化数据
- `dm_dialogue_log` 对话记录
- `narrative_context` 状态快照
- `save_version` 版本标记
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

#### 4.3.2 完整回合流程

```
Step 1: _turn_start()
        └── 清空所有角色 current_event
        └── 初始化/维护行动队列
        └── 确定当前行动者

Step 2: InputSystem.parse_input()
        └── 区分基础命令 vs 自然语言
        └── 基础命令直接执行并返回

Step 3: DMAgent.parse_intent()
        └── 解析玩家意图
        └── 判定是否需要鉴定
        └── 判定是否需要NPC响应

Step 4: RuleSystem.execute_check() (可选)
        └── 执行规则鉴定
        └── 返回 CheckOutput

Step 5: StateEvolution.evolve_player_action()
        └── 生成叙事文本
        └── 生成状态变更列表
        └── 判定是否触发结局

Step 6: _apply_changes()
        └── 批量应用状态变更
        └── 失败时回滚事务

Step 7: _process_unified_npc_response()
        └── NPCDirector 规划NPC行动
        └── StateEvolution 推演NPC行动
        └── 应用NPC状态变更

Step 8: _merge_turn_narratives()
        └── 合并玩家/NPC叙事片段
        └── 生成统一回合叙事

Step 9: 结局判定
        └── StateEvolutionOutput.is_end
        └── state_agent.check_end_condition()
        └── 配置化结局规则兜底

Step 10: _turn_end()
         └── 更新行动队列
         └── 增加回合数
```

### 4.4 事务与回滚

#### 4.4.1 变更应用流程

```python
def _apply_changes(self, changes: List[StateChange]) -> List[str]:
    transaction_snapshot = self._capture_transaction_snapshot()
    failures: List[str] = []
    
    for change in changes:
        normalized_change = self._normalize_state_change(change)
        error_code = self.io.apply_state_change(normalized_change)
        
        if error_code == 0:
            self._sync_state_change(normalized_change)  # 同步内存
        else:
            failures.append(error_message)
            self._restore_transaction_snapshot(transaction_snapshot)
            break
    
    return failures
```

#### 4.4.2 回滚机制

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

### 6.3 纯对话语义

```python
if dm_output.is_dialogue:
    result["response"] = dm_output.response_to_player
    if not dm_output.npc_response_needed:
        return result  # 直接结束
    # 否则继续进入NPC follow-up
```

### 6.4 错误反馈与重试

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
- 操作类型合法
- 值类型正确

---

## 9. NPC响应系统

### 9.1 响应模式

```python
class NpcResponseMode(str, Enum):
    UNIFIED = "unified"    # 统一后置响应（默认）
    QUEUE = "queue"        # 队列标签模式
    REACTIVE = "reactive"  # 响应式触发模式
```

### 9.2 模式语义

| 模式 | 触发条件 | 说明 |
|------|----------|------|
| `unified` | 默认触发 | 玩家主流程后统一处理NPC响应 |
| `queue` | 默认触发 | 同unified，trigger_source标记为queue |
| `reactive` | `dm_output.npc_response_needed == true` | 仅在DM判定需要时触发 |

### 9.3 NPC导演（NPCDirector）

#### 9.3.1 核心职责

- 生成结构化NPC行动计划
- 支持批量NPC决策
- 提供LLM和规则两种决策路径

#### 9.3.2 输出模型

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

#### 9.3.3 行动类型

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

#### 9.3.4 降级策略

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

### 9.4 NPC候选选择顺序

1. `dm_output.actionable_npcs` - DM建议的可行动NPC
2. `dm_output.npc_actor_id` - DM指定的响应NPC
3. `_action_queue` 中首个可行动NPC
4. `_pick_default_npc_actor()` - 同场景可行动NPC兜底

### 9.5 统一响应流程

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

#### 10.1.3 压缩策略

1. **窗口溢出**：当 `recent_events` 超过 `window_size` 时，最旧事件移入摘要
2. **摘要压缩**：事件文本超过120字符时截断并添加省略号
3. **关键事实提取**：自动提取HP、SAN、物品、线索等关键词

### 10.2 叙事合并（NarrativeMerger）

#### 10.2.1 合并策略

```python
def merge(self, fragments, game_state, context, truth_anchor):
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
  "npc_response_mode": "reactive",
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
| 主入口 | `game_engine.py` | 310 |
| 回合开始 | `game_engine.py` | 547 |
| 状态推演 | `game_engine.py` | 801 |
| 变更应用 | `game_engine.py` | 838 |
| 回合结束 | `game_engine.py` | 1117 |
| NPC响应模式设置 | `game_engine.py` | 1352 |
| 动态队列构建 | `game_engine.py` | 1368 |
| 叙事合并 | `game_engine.py` | 1683 |
| 统一NPC响应 | `game_engine.py` | 1705 |

### A.2 数据模型锚点

| 模型 | 文件 | 行号 |
|------|------|------|
| StateChange | `models.py` | 228 |
| NpcResponseMode | `models.py` | 261 |
| DMAgentOutput | `models.py` | 300 |
| StateEvolutionOutput | `models.py` | 334 |
| GameState | `models.py` | 348 |
| NPCActionForm | `npc_planning_models.py` | 40 |
| NPCActionDecision | `npc_planning_models.py` | 60 |

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

---

*文档结束*
