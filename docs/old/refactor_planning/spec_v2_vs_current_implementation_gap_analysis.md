# `spec_v2_simplified.md` 与当前实现差异分析

> 日期：2026-03-23  
> 目的：对照最初方案文档与当前代码/重构文档，形成一份可用于后续维护、继续重构和更新正式规范的落实文档。

## 1. 分析范围与依据

本分析同时参考以下材料：

- 原始方案：`docs/old/spec_v2_simplified.md`
- 中间重构提案：`docs/new/architecture_refactor_proposal.md`
- 可行性与执行文档：`docs/old/architecture_refactor_execution_plan.md`
- 集成重构计划：`docs/new/integrated_refactor_plan.md`
- 当前核心实现：
  - `src/engine/game_engine.py`
  - `src/agent/input_system.py`
  - `src/agent/npc/npc_director.py`
  - `src/data/npc_planning_models.py`
  - `src/narrative/narrative_context.py`
  - `src/narrative/narrative_merger.py`
  - `src/data/io_system.py`
  - `src/data/init/world_loader.py`
  - `src/data/models.py`
- 当前回归与增量测试：
  - `tests/test_regression_flow.py`
  - `tests/test_npc_director.py`
  - `tests/test_priority.py`
  - `tests/test_narrative_merger.py`
  - `tests/test_architecture_refactor_increment.py`

## 2. 执行摘要

结论可以先归纳成一句话：

最初的 `spec_v2_simplified.md` 是一个“低复杂度、强 LLM 主导、尽量少写硬逻辑”的绿地设计；当前实现已经演化成一个“保留原始主链路思想，但加入结构化模型、叙事上下文、兼容层、配置开关、回归测试和工程化护栏”的版本。

核心变化有五个：

1. 回合主流程已经从“严格 actor turn loop”演化为“玩家主流程优先，NPC 在同回合后置响应”的统一链路。
2. 队列已经不再是唯一的主调度中心，而更像“排序依据、候选来源和触发标签”的组合机制。
3. NPC 不再主要依赖 `StateEvolution` 自由扮演，而是通过 `NPCDirector + NPCActionForm` 结构化决策，再进入推演链路。
4. 叙事系统从 `current_event/log` 升级为“片段生成 + NarrativeMerger + NarrativeContext”的双层叙事架构。
5. 工程实现显著重于原始 spec：增加了 SQLite 持久化、兼容旧配置/旧路径、LLM 开关、更多命令、更多测试，也因此引入了一些过渡性的历史包袱。

## 3. 差异总览

| 维度 | 原始 `spec_v2_simplified` | 当前实现 | 判断 |
|---|---|---|---|
| 核心定位 | 简化系统、最小硬编码、尽量把解释权交给 LLM | 保留 LLM 主导，但加入大量结构化模型、回退逻辑、配置开关与测试护栏 | 方向升级 |
| 回合流程 | 标准 7 步回合制，玩家/NPC 都是轮到谁就执行谁 | 主流程以玩家输入为起点，NPC 作为同回合 follow-up 统一处理 | 已改道 |
| 队列语义 | 队列是核心调度结构，玩家/NPC 都进入同一套行动顺序 | 队列仍存在，但更多用于排序、选候选 NPC、保留兼容语义 | 部分保留 |
| NPC 决策 | 倾向让 `StateEvolution` 兼容 NPC 扮演 | 现为 `NPCDirector` 先产出结构化计划，再调用 `evolve_npc_action()` | 已重构 |
| 叙事机制 | 主要围绕 `current_event/log` | 现有 `NarrativeContext`、`NarrativeMerger`、truth anchor | 已增强 |
| 存储方案 | 静态 JSON + 运行时存档文件 | 初始世界仍来自 JSON，但运行时默认 SQLite，JSON 模式可选 | 工程化偏移 |
| 配置面 | 相对少量字段 | 增加 `npc_response_mode`、`narrative_window`、LLM 开关、结局文件等 | 已扩展 |
| 向后兼容 | 基本未强调 | 当前实现明显优先兼容老字段、老路径、老模式 | 新增目标 |
| 测试策略 | 以建议为主 | 当前已经建立多层回归测试 | 已落地 |

## 4. 逐项差异分析

### 4.1 架构哲学：从“最小系统”到“受控的 LLM 工程化”

### 原始方案

`spec_v2_simplified.md` 的核心价值观很明确：

- 尽量少写复杂硬逻辑
- 把意图理解与世界演绎的大部分自由度交给 LLM
- 用少量结构化输入输出把各模块串起来

### 当前实现

当前实现仍然保留了这个主轴，但明显增加了工程化控制层：

- `DMAgentOutput` 增加了 `npc_response_needed`、`npc_actor_id`、`npc_intent`、`actionable_npcs` 等字段，见 `src/data/models.py`
- `NPCActionForm`、`NPCCheckPlan`、`NPCActionDecision` 提供了结构化 NPC 计划层，见 `src/data/npc_planning_models.py`
- `NPCDirector` 变成 LLM-first、规则兜底的统一 NPC 规划入口，见 `src/agent/npc/npc_director.py`
- `NarrativeMerger` 和 `NarrativeContext` 把叙事从“单次输出”提升为“多片段整合 + 历史上下文管理”，见 `src/narrative/`
- `GameEngine` 内部加入了配置开关、fallback、兼容恢复和错误回滚逻辑，见 `src/engine/game_engine.py`

### 差异判断

这不是对原始方案的背离，而是原始方案在真实落地时被“加护栏”。原因主要有三个：

- 原始设计在复杂 NPC 协调、长程上下文、错误恢复上过于乐观
- LLM 输出需要结构化约束才能稳定进入后续链路
- 一旦开始支持保存/加载、世界配置、旧存档兼容，系统就不再是纯绿地项目

### 4.2 回合流程：从 actor turn loop 变为玩家优先链路

### 原始方案

`spec_v2_simplified.md` 中的 7 步流程是标准回合制：

1. 回合开始
2. 判断当前行动者
3. 玩家或 NPC 各自进入对应流程
4. 规则检定
5. 状态推演
6. 应用变更
7. 回合结束并切换到下一个 actor

这个设计里，玩家与 NPC 更接近“平权 actor”。

### 当前实现

当前主流程在 `src/engine/game_engine.py` 的 `process_input()` 中已经变成：

1. 输入系统处理指令/自然语言
2. `DMAgent.parse_intent()`
3. 玩家检定
4. 玩家 `StateEvolution`
5. 先应用玩家状态变更
6. 再调用 `_process_unified_npc_response()`
7. 合并玩家/NPC 叙事片段

其中 `_process_unified_npc_response()` 明确是“玩家行动后处理 NPC 响应”的后置流程。

虽然 `GameEngine` 里仍然保留了 `_process_npc_turns_until_player()`，但从代码调用关系看，它已经不是当前主流程的核心入口，只更像历史兼容遗留点。

### 差异判断

这是当前实现相对原始 spec 最大的结构性变化。

变化原因：

- 纯 actor turn loop 在交互式 CLI 里会显著打断玩家输入体验
- `queue/reactive` 双模式长期并存导致逻辑分叉
- 后续重构文档已经明确把主链路收敛到“玩家先执行，NPC 同回合后置响应”

影响：

- 原始 spec 中“玩家/NPC 完全同构的回合制”只实现了一部分
- 现实版本更适合互动体验和维护，但需要更新正式规范，否则文档会持续误导

### 4.3 队列语义：从主调度机制变成排序与候选机制

### 原始方案

原始 spec 把行动顺序理解为回合系统的核心：

- 每轮确定当前 actor
- 玩家和 NPC 都在同一套 turn order 中切换
- `resolved=false` 时允许连动

### 当前实现

当前仍然保留 `_action_queue`、`_build_dynamic_action_queue()`、`_calculate_actor_priority()`：

- `_build_dynamic_action_queue()` 在 `src/engine/game_engine.py` 中动态生成队列
- `_calculate_actor_priority()` 当前按 `DEX -> hp_ratio -> san_ratio -> actor.id` 排序
- `hp <= 0` 或 `san <= 0` 的 actor 直接被排除
- `tests/test_priority.py` 与 `tests/test_regression_flow.py` 对这部分行为有回归覆盖

但队列在当前主链路中的作用已经变化：

- 它不再决定“本轮一定先让谁输入”
- 它更多用于：
  - 排序 NPC 响应顺序
  - 在 `DMAgent` 未明确指定 NPC 时提供候选
  - 保留 `queue/reactive/unified` 的行为标签与兼容语义

### 差异判断

原始 spec 的“队列是主调度中心”已不成立。  
当前更准确的说法应该是：

`_action_queue` 是一个动态优先级列表，而不是整个运行时的唯一主时序控制器。

### 4.4 NPC 决策：从 `StateEvolution` 直接扮演，演变为 `NPCDirector + 结构化计划`

### 原始方案

原始 spec 强调：

- NPC 可以由 `StateEvolution` 直接扮演
- 通过 `is_npc_action=true` 和 `npc_intent/npc_info` 进入同一推演系统
- 核心目标是“玩家和 NPC 尽量走同一条链路”

### 当前实现

当前版本已经形成明显的两层结构：

1. `NPCDirector.decide_actions()` 先生成 `NPCActionDecision`
2. 每个 NPC 的 `NPCActionForm` 再进入 `StateEvolution.evolve_npc_action()`

也就是说，NPC 不再直接靠推演模块临场决定“要做什么”，而是先被规划，再被推演。

当前特征包括：

- `NPCDirector` 是 LLM-first，失败时回退到规则型默认计划，见 `src/agent/npc/npc_director.py`
- `NPCActionForm` 提供了 `action_type`、`target_id`、`intent_description`、`check`、`trigger_source`、`metadata`
- `GameEngine._plan_npc_actions()` 负责把 `DMAgentOutput`、`NarrativeContext`、recent events、player anchor 送进 director
- `GameEngine` 仍然保留 `dm_output.npc_intent` 作为兜底，说明兼容层仍在

### 差异判断

这是“设计升级”，不是“实现偏离”。

原始 spec 的问题是：

- 它把“NPC 要做什么”和“NPC 这么做会产生什么后果”混在一个 LLM 调用里
- 一旦 NPC 变多，就难以做协调、排序和回退

当前版本把它拆成“决策层 + 推演层”，可维护性显著更高。

### 仍未完全实现的部分

原始 spec 想要的是“玩家/NPC 真正共用同一套完整处理流”。  
当前只能说是“部分同构”：

- 玩家经过 `DMAgent -> RuleSystem -> StateEvolution`
- NPC 经过 `NPCDirector -> （简化 check） -> StateEvolution`

NPC 仍没有经过与玩家完全等价的 DM 解析阶段，且 `_execute_npc_check()` 当前是较简单的固定检定入口，不是完整的通用规则映射。

### 4.5 叙事系统：从 `current_event` 广播，升级为双层叙事架构

### 原始方案

原始 spec 的叙事输出更接近：

- `StateEvolution` 直接产出本轮 `narrative`
- 写入相关角色的 `memory.current_event`
- 每轮开始时清空 `current_event`，压入 `log`

这是一个简洁且直接的方案。

### 当前实现

当前叙事系统已经显著增强：

- `StateEvolution` 继续分别生成玩家和 NPC 片段
- `GameEngine._merge_turn_narratives()` 会把片段交给 `NarrativeMerger.merge()`
- `NarrativeMerger` 是 LLM 优先、失败后拼接 fallback，见 `src/narrative/narrative_merger.py`
- `NarrativeContext` 维护 `recent_events`、`summary_lines`、`key_facts`，并限制 `max_context_chars`，见 `src/narrative/narrative_context.py`
- `player_resolution_anchor` 被注入后续流程，作为叙事合并和 NPC 响应时的真值锚点，见 `src/agent/state_evolution.py` 与 `src/engine/game_engine.py`

### 差异判断

相对原始 spec，这属于“新增出的第二代叙事架构”。

新增原因：

- 玩家叙事和 NPC 叙事分开生成后，如果直接拼接，容易冲突
- 长回合上下文不能只靠 `current_event/log`
- 需要把“真实状态变化”与“叙事措辞”分开，避免模型自说自话

### 评价

这部分是当前实现最明显的增强项，也是最值得反向写回正式规范的地方。  
如果未来要更新主规范，叙事系统不应再按原始 spec 描述，而应以“片段生成 + 合并 + 上下文维护”的模式重写。

### 4.6 存储方案：从 JSON-first 演变为“配置 JSON + 运行时 SQLite”

### 原始方案

原始 spec 的存储设想偏简单：

- 世界初始数据来自 `config/world/`
- 运行时数据加载后写入存档文件
- 更像面向文件的轻量方案

### 当前实现

当前 `IOSystem` 明确支持两种模式，见 `src/data/io_system.py`：

- `sqlite`：默认运行时模式，数据库文件为 `data/game.db`
- `json`：可选模式

同时 `WorldLoader` 负责：

- 从 `config/world/<world_name>/` 的拆分 JSON 目录加载世界
- 兼容旧版单文件世界结构
- 输出包含元信息的 `WorldBundle`

### 差异判断

当前实现相对原始 spec 更偏“配置与运行时分离”：

- 配置层仍是 JSON
- 运行时层默认已是数据库

这说明系统已经不是“轻文件架构的原型”，而是进入了更标准的工程运行态。

### 4.7 世界配置面：从基础字段扩展到运行时策略层

### 原始方案

原始 spec 中世界配置重点主要是：

- `player_id`
- `start_map_id`
- `turn_order`
- `end_condition`

### 当前实现

当前世界配置和加载结果中已经扩展出多组运行策略字段：

- `npc_response_mode`
- `narrative_window`
- `npc_director_use_llm`
- `narrative_merge_use_llm`
- 结局配置文件目录 `config/world/.../endings/`

`WorldBundle` 在 `src/data/init/world_loader.py` 中也已经把这些作为正式字段返回。

### 差异判断

当前世界配置已经不只是“剧情数据”，而是在承担“运行时行为策略”的职责。  
这使世界文件更强大，但也意味着规范文档必须区分：

- 世界内容配置
- 引擎策略配置

否则会继续混淆“世界设计”和“运行时模式”。

### 4.8 输入系统与 CLI：比原始 spec 更丰富，也更偏实用主义

### 原始方案

原始 spec 里的基础命令集主要包括：

- `\look`
- `\inventory`
- `\pickup`
- `\drop`
- `\help`
- `\save`
- `\load`
- `\exit`

### 当前实现

当前 `InputSystem` 和 README 中已经扩展出更多能力：

- `\status`
- `\where`
- `\use`
- `\give`
- `\move`
- `\reset`
- `\debug`
- 部分别名支持

见：

- `src/agent/input_system.py`
- `README.md`
- `src/cli/game_cli.py`

### 差异判断

这部分属于“功能外扩”，不是架构分歧。  
它说明原始 spec 的 CLI 设计只是最小起点，而现实实现已经在朝“可玩性优先”的方向扩展。

### 4.9 向后兼容：这是原始 spec 几乎没有，但现实里必须承担的职责

### 原始方案

原始 spec 基本是从零设计，没有太多“兼容旧世界/旧字段/旧路径”的负担。

### 当前实现

当前实现明显把兼容性当成一个正式目标：

- `WorldLoader` 兼容新旧世界目录格式
- `DMAgentOutput` 保留旧字段，同时增量引入新字段
- `npc_intent` 仍作为 fallback 存在
- `src/npc/` 与 `src/agent/npc/` 共存，说明发生过模块迁移
- 多个测试明确覆盖旧配置与恢复链路，见 `tests/test_regression_flow.py`

### 差异判断

兼容性不是原始方案的一部分，但已经成为当前项目的现实边界条件。  
这意味着未来规范文档不能只写“理想架构”，还必须写清：

- 当前兼容层有哪些
- 哪些是正式接口
- 哪些只是迁移过渡

### 4.10 测试与质量保障：从建议项变成系统组成部分

### 原始方案

原始 spec 有错误处理和调试支持建议，但测试更多是原则性描述。

### 当前实现

测试已经覆盖多个关键重构点：

- 优先级排序：`tests/test_priority.py`
- NPC 规划与结构化落地：`tests/test_npc_director.py`
- 叙事合并 fallback/LLM 路径：`tests/test_narrative_merger.py`
- NarrativeContext 增量能力：`tests/test_architecture_refactor_increment.py`
- 主流程、配置、兼容、回滚：`tests/test_regression_flow.py`

### 差异判断

测试已经从“开发建议”变成“架构的一部分”。  
这意味着后续规范更新时，测试基线也应该被视为正式约束，而不是附录性质的补充说明。

## 5. 当前实现相对原始 spec 的“已兑现 / 偏离 / 超出”清单

### 5.1 已兑现的部分

- `InputSystem -> DMAgent -> RuleSystem -> StateEvolution -> IOSystem` 这条主链路仍然成立
- `memory.current_event` 与 `log` 机制仍存在
- 动态行动优先级仍存在，并且有明确排序规则
- NPC 最终仍然通过 `evolve_npc_action()` 进入统一状态推演体系
- 世界配置仍然以 `config/world/` 为源头

### 5.2 明显偏离的部分

- 原始 spec 的严格 actor 回合制已经不是当前真实主流程
- 原始 spec 中“队列主导全时序”的设定已不再准确
- 原始 spec 中“NPC 直接由 StateEvolution 扮演”的描述已不足以代表现实实现
- 原始 spec 没有覆盖 NarrativeMerger、truth anchor、narrative_context 这些关键运行组件

### 5.3 超出原始 spec 的部分

- SQLite 运行时存储
- `NPCDirector` 的 LLM-first 结构化规划
- `NarrativeContext` 的压缩和关键事实机制
- `NarrativeMerger` 的叙事片段合并
- 世界级 LLM 开关
- 更丰富的 CLI 命令
- 完整的回归测试基线

## 6. 当前实现中的遗留问题与文档风险

这里不是说当前实现“不对”，而是指出“如果继续沿用原始 spec 作为主文档，会出现哪些认知偏差”。

### 6.1 文档风险

- 开发者会误以为当前仍然是严格的 7 步 actor turn 流程
- 开发者会误以为 `queue/reactive` 仍是两套主链路，而不是收敛后的语义标签/触发策略
- 开发者会低估 `NarrativeContext`、`NarrativeMerger`、`NPCDirector` 的系统地位
- 开发者会忽略兼容层和测试基线，从而在修改时误删关键过渡逻辑

### 6.2 代码层面的历史包袱

- `_process_npc_turns_until_player()` 仍然存在，但已不符合当前主链路定位
- `queue/reactive/unified` 的概念在代码中仍带有历史叠加痕迹
- NPC 检定入口还比较简化，离“完全与玩家同构”仍有距离
- 默认值、兼容逻辑和世界策略配置分布在多个模块中，规范没有统一收口

## 7. 建议的规范更新方向

如果后续要把文档体系收敛，我建议按下面的方式处理：

### 7.1 保留 `spec_v2_simplified.md`，但降级为“原始设计基线”

建议在文档头部明确标注：

- 这是最初设计稿
- 不再代表当前运行时真实实现
- 当前真实行为应以新运行时规范和代码为准

### 7.2 新增一份“当前运行时正式规范”

建议内容至少覆盖：

- 当前真实主流程
- `queue/reactive/unified` 的准确语义
- `NPCDirector`、`NPCActionForm`、`NarrativeContext`、`NarrativeMerger` 的职责边界
- 世界配置字段与开关说明
- 向后兼容边界
- 测试基线

### 7.3 把中间提案文档从“方案文档”整理为“演化记录”

目前 `architecture_refactor_proposal.md`、`architecture_refactor_execution_plan.md`、`integrated_refactor_plan.md` 都很有价值，但角色不同：

- 有的是提出目标
- 有的是阶段执行计划
- 有的是落地总结

建议后续在 docs 中明确分层：

- `spec/`：正式规范
- `proposal/`：提案
- `history/`：演化记录
- `review/`：问题审计与阶段总结

## 8. 最终结论

`spec_v2_simplified.md` 没有“失效”，它仍然解释了项目最初为什么这样设计。  
但它已经不能准确描述当前系统。

当前系统的真实状态更接近：

- 保留原始主干模块划分
- 回合流程改为玩家优先、NPC 同回合后置响应
- 队列从主调度器弱化为排序与候选机制
- NPC 通过 `NPCDirector + 结构化计划 + StateEvolution` 运行
- 叙事通过 `NarrativeMerger + NarrativeContext` 统一
- 持久化、兼容层、配置开关、测试基线都已经成为正式系统组成部分

因此，最合理的文档策略不是继续修补原始 spec，而是：

把原始 spec 作为“设计起点”保留，同时基于当前实现重新写一份“运行时正式规范”。

---

## 9. 可直接追踪的代码锚点

为了方便后续继续对照，这里整理一组最关键的实现锚点：

- `src/engine/game_engine.py`
  - `process_input()`
  - `_process_unified_npc_response()`
  - `_process_npc_turns_until_player()`
  - `_build_dynamic_action_queue()`
  - `_calculate_actor_priority()`
  - `_merge_turn_narratives()`
  - `set_npc_response_mode()`
  - `_describe_npc_mode_policy()`
- `src/agent/npc/npc_director.py`
  - `NPCDirector`
  - `decide_actions()`
  - `_fallback_decision()`
- `src/data/npc_planning_models.py`
  - `NPCCheckPlan`
  - `NPCActionForm`
  - `NPCActionDecision`
- `src/narrative/narrative_context.py`
  - `NarrativeContext`
  - `get_context_for_llm()`
- `src/narrative/narrative_merger.py`
  - `NarrativeMerger`
  - `merge()`
- `src/data/init/world_loader.py`
  - `WorldBundle`
  - `_resolve_npc_response_mode()`
  - `_resolve_narrative_window()`
- `src/data/io_system.py`
  - `IOSystem`
  - `apply_state_change()`
  - `save_game_state()`
  - `load_game_state()`
- `src/agent/input_system.py`
  - 帮助命令与基础指令实现

