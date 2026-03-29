# 运行时正式规范

> 状态：Draft  
> 日期：2026-03-23  
> 适用范围：当前仓库代码所体现的实际运行时行为  
> 代码基线：以 `src/` 与 `tests/` 为准，本文用于整理当前正式语义，不再回溯原始设计意图

## 1. 文档定位

本文定义当前版本的运行时正式规范，重点回答：

- 引擎启动、加载、保存的正式行为
- 玩家输入进入运行时后的主链路
- NPC 响应模式、队列语义、叙事合并语义
- 配置项、兼容层、错误回滚、测试基线

规范来源以代码为准，核心锚点：

- `src/engine/game_engine.py:50`
- `src/data/models.py:221`
- `src/agent/input_system.py:41`
- `src/agent/npc/npc_director.py:62`
- `src/narrative/narrative_context.py:31`
- `src/narrative/narrative_merger.py:12`
- `src/data/init/world_loader.py:22`
- `src/data/io_system.py:68`

## 2. 运行时总原则

### 2.1 主流程原则

- 运行时主入口为 `GameEngine.process_input()`，见 `src/engine/game_engine.py:310`
- 当前正式主链路为“玩家主流程优先，NPC 在同回合同步后置响应”
- `queue` / `reactive` / `unified` 当前是响应策略与触发标签，不是三套完全独立主链路

### 2.2 真值原则

- 世界状态真值以 `GameState` + 持久化 IO 层为准，见 `src/data/models.py:348`、`src/data/io_system.py:68`
- 叙事文本不是状态真值；状态变更以 `StateChange` 为唯一正式写入格式，见 `src/data/models.py:228`
- 合并叙事时使用 `player_resolution_anchor` 作为真值锚点，见 `src/engine/game_engine.py:1683`、`src/agent/state_evolution.py:425`

### 2.3 工程原则

- LLM 可参与 DM、NPCDirector、NarrativeMerger、StateEvolution
- 每个 LLM 点都必须有降级或兜底路径
- 批量状态变更失败时必须整体回滚当前批次，见 `src/engine/game_engine.py:838`

## 3. 运行时模块边界

| 模块 | 职责 | 代码锚点 |
|---|---|---|
| `GameEngine` | 总调度、回合编排、配置应用、保存加载、状态变更事务、叙事合并 | `src/engine/game_engine.py:50` |
| `InputSystem` | 区分基础命令与自然语言；执行本地命令 | `src/agent/input_system.py:41` |
| `DMAgent` | 解析玩家自然语言为结构化意图 | `src/data/models.py:290` |
| `RuleSystem` | 计算检定结果 | `src/data/models.py:268` |
| `StateEvolution` | 将检定/意图推演为叙事与状态变更 | `src/data/models.py:334`、`src/agent/state_evolution.py:156` |
| `NPCDirector` | 生成结构化 NPC 行动计划 | `src/agent/npc/npc_director.py:62` |
| `NarrativeMerger` | 合并玩家/NPC 叙事片段 | `src/narrative/narrative_merger.py:12` |
| `NarrativeContext` | 维护叙事上下文窗口、摘要、关键事实 | `src/narrative/narrative_context.py:31` |
| `IOSystem` | 持久化实体、应用状态变更、清空 current_event、存取 GameState | `src/data/io_system.py:68` |
| `WorldLoader` | 从世界配置构造 `WorldBundle` 与初始 `GameState` | `src/data/init/world_loader.py:22` |

## 4. 核心数据契约

### 4.1 状态变更契约

- 变更类型为 `StateChange`
- 字段：
  - `id`
  - `field`
  - `operation`
  - `value`
- 操作枚举为：
  - `update`
  - `add`
  - `del`

代码锚点：

- `src/data/models.py:221`
- `src/data/models.py:228`

### 4.2 NPC 响应模式契约

- 正式枚举：
  - `unified`
  - `queue`
  - `reactive`
- 当前模式值由 `GameEngine.set_npc_response_mode()` 归一化设置

代码锚点：

- `src/data/models.py:261`
- `src/engine/game_engine.py:1360`
- `src/engine/game_engine.py:1352`

### 4.3 DM 输出契约

`DMAgentOutput` 当前正式字段：

- `is_dialogue`
- `response_to_player`
- `needs_check`
- `check_type`
- `check_attributes`
- `check_target`
- `difficulty`
- `action_description`
- `npc_response_needed`
- `npc_actor_id`
- `npc_intent`
- `actionable_npcs`

代码锚点：

- `src/data/models.py:300`

### 4.4 NPC 规划契约

`NPCActionForm` 当前正式字段：

- `npc_id`
- `action_type`
- `target_id`
- `intent_description`
- `expected_outcome`
- `check`
- `trigger_source`
- `metadata`

`check` 为嵌套 `NPCCheckPlan`：

- `check_needed`
- `check_attributes`
- `difficulty`
- `check_target_id`

代码锚点：

- `src/data/npc_planning_models.py:11`
- `src/data/npc_planning_models.py:31`
- `src/data/npc_planning_models.py:40`
- `src/data/npc_planning_models.py:60`

### 4.5 游戏状态契约

`GameState` 当前正式字段：

- `characters`
- `items`
- `maps`
- `player_id`
- `current_scene_id`
- `turn_order`
- `turn_count`
- `is_ended`

代码锚点：

- `src/data/models.py:348`

## 5. 启动与加载规范

### 5.1 新游戏

- `GameEngine.new_game()` 通过 `WorldLoader` 加载世界并应用世界级配置
- 加载成功后将 `turn_count` 初始化为 `1`

代码锚点：

- `src/engine/game_engine.py:120`
- `src/engine/game_engine.py:280`
- `src/data/init/world_loader.py:55`

### 5.2 存档加载

- `GameEngine.load_game()` 当前从 `data/saves/<save_name>.json` 读取
- 恢复内容包含：
  - `GameState`
  - `dm_dialogue_log`
  - `narrative_context`
  - `world_metadata`
- `world_metadata` 缺失时允许从旧字段回退重建

代码锚点：

- `src/engine/game_engine.py:171`
- `src/engine/game_engine.py:280`
- `tests/test_regression_flow.py:859`

### 5.3 存档保存

- `GameEngine.save_game()` 当前写入 `data/saves/<save_name>.json`
- 保存内容至少包括：
  - `GameState`
  - `dm_dialogue_log`
  - `narrative_context`
  - `save_version`
  - `world_metadata`

代码锚点：

- `src/engine/game_engine.py:230`

## 6. 输入处理规范

### 6.1 输入分类

- 空输入：按基础命令错误提示处理
- 以 `\` 开头：按基础命令处理
- 以 `/` 开头且命中已知命令：兼容按基础命令处理
- 其他输入：按自然语言处理

代码锚点：

- `src/agent/input_system.py:93`

### 6.2 正式基础命令集合

当前正式基础命令：

- `look`
- `inventory`
- `pickup`
- `drop`
- `use`
- `give`
- `move`
- `go`
- `status`
- `where`
- `save`
- `load`
- `reset`
- `debug`
- `help`
- `exit`

代码锚点：

- `src/agent/input_system.py:52`
- `src/agent/input_system.py:757`

### 6.3 基础命令执行语义

- 基础命令由 `InputSystem.execute_command()` 执行
- `save` / `load` / `reset` / `debug` / `exit` 由引擎层补充处理其系统语义
- 基础命令产生的 `changes` 也必须经过统一 `_apply_changes()` 事务写入

代码锚点：

- `src/agent/input_system.py:155`
- `src/engine/game_engine.py:336`

## 7. 自然语言主流程规范

当前正式自然语言主链路如下：

1. `GameEngine._turn_start()`
2. `InputSystem.parse_input()`
3. `DMAgent.parse_intent()`
4. 若需要，`RuleSystem.execute_check()`
5. `StateEvolution.evolve_player_action()`
6. 应用玩家 `changes`
7. `_process_unified_npc_response()`
8. `_merge_turn_narratives()`
9. 结局判定
10. `GameEngine._turn_end()`

代码锚点：

- `src/engine/game_engine.py:310`
- `src/engine/game_engine.py:547`
- `src/engine/game_engine.py:761`
- `src/engine/game_engine.py:801`
- `src/engine/game_engine.py:1705`
- `src/engine/game_engine.py:1683`
- `src/engine/game_engine.py:1117`

### 7.1 纯对话语义

- `dm_output.is_dialogue == true` 时优先返回 `response_to_player`
- 若同时 `npc_response_needed == true`，则不提前终止，仍继续进入 NPC follow-up
- 若 `npc_response_needed == false`，则该次输入可直接结束

代码锚点：

- `src/engine/game_engine.py:414`
- `tests/test_regression_flow.py:999`
- `tests/test_regression_flow.py:1021`

## 8. NPC 响应规范

### 8.1 正式入口

- 当前正式 NPC 入口为 `_process_unified_npc_response()`
- `_process_reactive_npc_response()` 与 `_process_npc_turns_until_player()` 不属于当前主链路主入口

代码锚点：

- `src/engine/game_engine.py:1705`
- `src/engine/game_engine.py:681`
- `src/engine/game_engine.py:566`

### 8.2 触发条件

- `unified` / `queue`：默认触发 NPC follow-up
- `reactive`：仅在 `dm_output.npc_response_needed == true` 时触发

代码锚点：

- `src/engine/game_engine.py:1715`
- `src/engine/game_engine.py:1352`

### 8.3 NPC 候选选择顺序

当前候选来源按下列顺序收集：

1. `dm_output.actionable_npcs`
2. `dm_output.npc_actor_id`
3. `_action_queue` 中首个可行动 NPC
4. `_pick_default_npc_actor()`

代码锚点：

- `src/engine/game_engine.py:1719`
- `src/engine/game_engine.py:1723`
- `src/engine/game_engine.py:1733`

### 8.4 NPC 决策与执行

- 规划由 `NPCDirector.decide_actions()` 负责
- 执行由 `StateEvolution.evolve_npc_action()` 负责
- `trigger_source` 使用当前模式标签或 `unified`
- 多 NPC 时按动态队列顺序执行已规划的 NPC

代码锚点：

- `src/agent/npc/npc_director.py:84`
- `src/engine/game_engine.py:1239`
- `src/engine/game_engine.py:1740`
- `src/engine/game_engine.py:1750`

### 8.5 NPCDirector 正式语义

- LLM 可用时，优先走 `_llm_decide()`
- LLM 不可用、失败或无结果时，必须回退 `_fallback_decision()`
- fallback 当前行为是：
  - 默认 `WAIT`
  - 若 `player_intent.npc_response_needed == true`，生成面向玩家的 `TALK`

代码锚点：

- `src/agent/npc/npc_director.py:69`
- `src/agent/npc/npc_director.py:102`
- `src/agent/npc/npc_director.py:198`

## 9. 队列与优先级规范

### 9.1 正式定义

- `_action_queue` 是动态优先级列表，不是唯一主调度器
- 正式构造入口为 `_build_dynamic_action_queue()`

代码锚点：

- `src/engine/game_engine.py:1368`

### 9.2 排序规则

可行动 actor 排序按以下键：

1. `dex` 降序
2. `hp / max_hp` 降序
3. `san / 100` 降序
4. `actor.id` 升序稳定打平

不可行动条件：

- `hp <= 0`
- `san <= 0`

代码锚点：

- `src/engine/game_engine.py:1386`
- `src/engine/game_engine.py:1405`
- `tests/test_priority.py:46`

### 9.3 回合结束队列语义

- `resolved == true` 时，重新计算队列并将刚行动 actor 放到队尾，避免连续行动
- `resolved == false` 时，保持当前 actor
- 同步结果写回 `game_state.turn_order`

代码锚点：

- `src/engine/game_engine.py:1117`

## 10. 叙事规范

### 10.1 叙事生产模型

当前正式叙事分三层：

1. 玩家/NPC 各自产生片段
2. `NarrativeMerger` 合并成单回合叙事
3. `NarrativeContext` 将合并结果纳入历史上下文

代码锚点：

- `src/engine/game_engine.py:1683`
- `src/narrative/narrative_merger.py:12`
- `src/narrative/narrative_context.py:31`

### 10.2 NarrativeMerger 语义

- 无片段：返回空字符串
- 单片段：直接返回该片段
- 多片段：
  - LLM 可用时优先合并
  - 否则回退为按顺序拼接

代码锚点：

- `src/narrative/narrative_merger.py:33`
- `tests/test_narrative_merger.py:18`
- `tests/test_narrative_merger.py:33`

### 10.3 NarrativeContext 语义

- 正式存储结构：
  - `recent_events`
  - `summary_lines`
  - `key_facts`
- 正式限制参数：
  - `window_size`
  - `max_summary_lines`
  - `max_context_chars`
- `get_context_for_llm()` 输出压缩后的 prompt 上下文块

代码锚点：

- `src/narrative/narrative_context.py:31`
- `src/narrative/narrative_context.py:62`
- `src/narrative/narrative_context.py:120`
- `src/narrative/narrative_context.py:164`

### 10.4 current_event 语义

- 每轮开始通过 IO 层清空所有角色 `current_event`，并同步到 log
- 玩家的 `current_event` 在回合结尾保持与最终展示叙事一致

代码锚点：

- `src/engine/game_engine.py:547`
- `src/data/io_system.py:930`
- `src/engine/game_engine.py:496`

## 11. 状态变更与事务规范

### 11.1 批处理规则

- 所有运行时状态变更都必须通过 `_apply_changes()` 批量进入 IO
- 每条变更先做归一化，再调用 `IOSystem.apply_state_change()`
- 变更成功后同步回内存态

代码锚点：

- `src/engine/game_engine.py:838`
- `src/data/io_system.py:662`

### 11.2 回滚规则

- 批处理中任一变更失败，当前批次停止
- 引擎恢复事务快照中的 `GameState`
- 若 IO 支持 `save_game_state()`，则回滚后重新持久化恢复态

代码锚点：

- `src/engine/game_engine.py:850`
- `src/engine/game_engine.py:858`
- `tests/test_regression_flow.py:1042`
- `tests/test_regression_flow.py:1062`

## 12. 结局判定规范

当前正式结局判定是双轨：

1. `StateEvolutionOutput.is_end`
2. `state_agent.check_end_condition()` AI 复核
3. 配置化结局规则兜底

结局规则来源目录：

- `config/world/<world_name>/endings/*.json`

代码锚点：

- `src/engine/game_engine.py:505`
- `src/engine/game_engine.py:1553`
- `tests/test_regression_flow.py:458`

## 13. 世界配置规范

### 13.1 `WorldBundle` 正式字段

- `game_state`
- `world_name`
- `end_condition`
- `npc_response_mode`
- `narrative_window`
- `npc_director_use_llm`
- `narrative_merge_use_llm`

代码锚点：

- `src/data/init/world_loader.py:22`

### 13.2 世界清单正式字段

当前实现实际消费的关键字段：

- `player_id`
- `start_map_id`
- `turn_order`
- `narrative_window`
- `npc_response_mode`
- `npc_director_use_llm`
- `narrative_merge_use_llm`
- `end_condition`

示例：

- `config/world/mysterious_library/world.json`

### 13.3 当前示例世界默认值

`mysterious_library` 当前配置为：

- `npc_response_mode = reactive`
- `narrative_window = 5`
- `npc_director_use_llm = true`
- `narrative_merge_use_llm = true`

代码锚点：

- `config/world/mysterious_library/world.json`

## 14. LLM 开关与降级规范

### 14.1 正式开关

- `npc_director_use_llm`
- `narrative_merge_use_llm`

加载与应用入口：

- `src/data/init/world_loader.py:96`
- `src/engine/game_engine.py:280`

### 14.2 降级要求

- `NPCDirector` 必须支持规则型 fallback
- `NarrativeMerger` 必须支持纯拼接 fallback
- `NarrativeContext` 缺失时引擎必须可退化运行

代码锚点：

- `src/agent/npc/npc_director.py:102`
- `src/narrative/narrative_merger.py:41`
- `src/engine/game_engine.py:1148`

## 15. 兼容层规范

当前兼容层属于正式运行边界的一部分，未清理前不得视为无效代码：

- 旧世界格式兼容：`WorldLoader`
- `/help` 等 slash command 兼容：`InputSystem.parse_input()`
- `npc_intent` 作为 NPC structured plan 缺失时的兜底字段
- narrative snapshot 恢复时兼容旧 `summary` 到 `summary_lines`

代码锚点：

- `src/data/init/world_loader.py:55`
- `src/agent/input_system.py:107`
- `src/engine/game_engine.py:1326`
- `src/engine/game_engine.py:1524`

## 16. 测试基线

当前正式语义至少由以下测试保护：

- 优先级排序：`tests/test_priority.py`
- NPCDirector 规划接入：`tests/test_npc_director.py`
- NarrativeMerger 降级与 LLM 路径：`tests/test_narrative_merger.py`
- NarrativeContext 与结构化增量：`tests/test_architecture_refactor_increment.py`
- 运行主流程、配置、兼容、回滚：`tests/test_regression_flow.py`

这些测试应视为运行时规范的回归基线，不只是示例。

## 17. 当前不应再使用的旧表述

以下表述不再准确，不应继续作为正式规范文本：

- “当前运行时是严格的玩家/NPC actor 轮转回合制”
- “queue 和 reactive 是两套并行主流程”
- “NPC 直接由 StateEvolution 自由决定动作”
- “current_event/log 足以定义完整叙事系统”

## 18. 最小代码引用清单

建议后续润色时优先保留这些锚点：

- `src/engine/game_engine.py:310`
- `src/engine/game_engine.py:547`
- `src/engine/game_engine.py:801`
- `src/engine/game_engine.py:838`
- `src/engine/game_engine.py:1117`
- `src/engine/game_engine.py:1352`
- `src/engine/game_engine.py:1368`
- `src/engine/game_engine.py:1683`
- `src/engine/game_engine.py:1705`
- `src/agent/npc/npc_director.py:62`
- `src/data/npc_planning_models.py:40`
- `src/narrative/narrative_context.py:31`
- `src/narrative/narrative_merger.py:12`
- `src/data/init/world_loader.py:22`
- `src/data/models.py:261`
- `src/data/models.py:300`
- `src/data/models.py:348`
