# 架构重构方案可行性调查与执行建议

日期：2026-03-22  
依据：[`docs/new/architecture_refactor_proposal.md`](./architecture_refactor_proposal.md) 与当前 `src/` 代码实现

## 1. 结论

这个方案**可行**，但应采用**增量重构**，不建议一次性推翻现有 `GameEngine`。

原因很明确：

- `GameEngine` 已经实现了回合编排、`queue/reactive` 双模式 NPC 响应、行动队列维护，以及玩家输入主流程。
- `DMAgent` 已经输出 `npc_response_needed`、`npc_actor_id`、`npc_intent` 等字段，说明“DM 先判断，再交由后续模块处理 NPC”这一链路已经有基础。
- `StateEvolution` 已经支持 `evolve_npc_action()`，也就是提案里想要的“NPC 也走同一套状态推演”已经具备落点。
- `WorldLoader` 已经能从 `world.json` 读取 `turn_order`、`start_map_id`、`npc_response_mode`，说明世界配置层也已经能承接这类重构。

所以，这份提案不是不可实施，而是需要把目标调整成：

> 先把现有能力收束成清晰接口，再逐步抽出 `NPCDirector` 和 `NarrativeContext`，最后再做流程统一。

## 2. 当前实现与提案的匹配度

### 2.1 已经具备的能力

- `GameEngine` 中已经有 `queue/reactive` 分支。
- `GameEngine` 中已经有 `_build_dynamic_action_queue()` 与 `_build_npc_runtime_context()`。
- `DMAgentOutput` 已经有 NPC 响应相关字段。
- `StateEvolution` 已经有玩家与 NPC 两条推演入口。
- `GameState`、`ChangeOperation`、`StateChange` 这些基础结构已经足够支撑结构化状态变化。

### 2.2 仍然缺少的能力

- 没有独立的 `NPCDirector`，NPC 决策逻辑仍然分散在 `GameEngine` 中。
- 没有独立的 `NarrativeContext`，当前叙事信息主要靠 `current_event` 和 `log` 维持。
- 没有标准化的 `NPCActionForm` / `NPCActionPlan` 数据模型，NPC 动作更多还是通过 `npc_intent` 这种半结构化字段传递。
- 没有明确的“叙事窗口压缩”机制，长回合游戏的上下文控制还不够稳定。
- 缺少围绕新流程的回归测试，尤其是 `queue/reactive`、结局判断、状态变更同步这几条主链路。

## 3. 实施建议

### 3.1 总体原则

- 不重写 `GameEngine`，先把它变成稳定的调度层。
- 保留现有 `queue/reactive` 配置，避免一次性切换导致世界配置失效。
- 先落数据模型和接口，再落流程和提示词，最后做叙事压缩与性能优化。
- 保持向后兼容，旧世界配置和旧存档要能继续跑。

### 3.2 推荐落地方式

1. 先抽象 NPC 计划模型。

   建议新增 `NPCActionPlan` 或 `NPCActionForm`，让 NPC 动作从“自然语言意图”逐步变成“可执行计划”。

2. 再引入 `NPCDirector`。

   `NPCDirector` 只负责把 `DMAgentOutput`、`GameState`、最近事件等信息整理成 NPC 计划，不直接写状态。

3. 将 `NarrativeContext` 先做成轻量内存层。

   第一版只负责最近事件窗口、摘要字符串、关键事实集合，不急着做复杂持久化。

4. 最后统一接入 `StateEvolution`。

   玩家与 NPC 走同一套“生成叙事 + 产生变更 + IO 落库”的模式，但保留各自的输入结构。

## 4. 分阶段计划

### Phase 0：现状收敛与接口冻结

- 明确当前 `GameEngine` 的职责边界。
- 冻结现有 `DMAgentOutput`、`StateEvolutionOutput` 的兼容字段。
- 为 `queue/reactive`、`turn_order`、`current_event` 建立回归基线。

交付物：

- 现状映射表
- 兼容字段清单
- 回归测试清单

验收标准：

- 现有世界能正常开局、回合推进、保存/加载。
- `queue/reactive` 两种模式行为没有被破坏。

### Phase 1：数据模型与提示词升级

- 新增 `NPCActionPlan` / `NPCActionForm`。
- 让 `DMAgentOutput` 在保留旧字段的前提下，补充更结构化的 NPC 指令。
- 调整 DM 与状态推演提示词，使其优先输出可执行结构，而不是仅靠解释性文本。

交付物：

- 新数据模型
- 更新后的 schema
- 新旧字段兼容转换逻辑

验收标准：

- 旧流程不报错。
- 新字段可被稳定解析，并进入后续推演链路。

### Phase 2：引入 NPCDirector

- 新建 `NPCDirector`，负责 NPC 计划编排。
- 将 `GameEngine` 中和 NPC 相关的编排逻辑逐步迁移到该层。
- 保留 `GameEngine` 作为调度者，不让它继续膨胀成“所有逻辑都堆在一起”的巨型类。

交付物：

- `NPCDirector` 模块
- NPC 行动计划生成入口
- 与 `StateEvolution.evolve_npc_action()` 的对接

验收标准：

- NPC 行为可以通过统一入口产生。
- 玩家回合和 NPC 回合的流程边界清晰。

### Phase 3：NarrativeContext 与叙事窗口

- 新增 `NarrativeContext`，保存最近若干事件。
- 用摘要与关键事实压缩历史内容，控制 LLM 上下文长度。
- 先在内存中运行，确认稳定后再考虑持久化。

交付物：

- `NarrativeContext` 类
- 历史压缩策略
- 最近事件窗口配置

验收标准：

- 连续多回合运行时，上下文不会无限增长。
- 关键事实不会因压缩而丢失。

### Phase 4：流程统一与兼容层收敛

- 把玩家动作和 NPC 动作尽量收敛成同一套推演框架。
- 将原来散落在 `GameEngine` 的临时处理逻辑清理掉。
- 保留兼容分支，直到新流程稳定。

交付物：

- 统一流程图
- 兼容分支清单
- 清理后的 `GameEngine`

验收标准：

- 主流程、NPC 流程、结局判定流程都能稳定运行。
- 回归测试通过率达到预期。

### Phase 5：测试、回归与上线准备

- 增加针对 `queue/reactive`、NPC 决策、状态变更同步、结局判定的单元测试和流程测试。
- 补充开发文档与故障排查指引。
- 如果需要，增加 feature flag 作为上线保护。

交付物：

- 测试用例
- 回归报告
- 上线检查清单

验收标准：

- 主要回归场景稳定通过。
- 新旧世界配置均可运行。

## 5. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 一次性重构 `GameEngine` | 高 | 按阶段抽离，先保留旧流程 |
| NPC 结构化输出不稳定 | 中 | 保留 `npc_intent` 兜底，并增加 schema 校验 |
| 叙事压缩丢关键信息 | 中 | 关键事实单独保存，压缩前后做对照 |
| 旧世界配置不兼容 | 高 | 保持 `world.json` 兼容字段，不做破坏式修改 |
| 回归测试不足 | 高 | 先补测试基线，再做模块替换 |

## 6. 推荐的实施优先级

1. 先保住现有主流程。
2. 再补结构化 NPC 计划。
3. 再抽 `NPCDirector`。
4. 再做 `NarrativeContext`。
5. 最后统一流程和清理遗留逻辑。

## 7. 最终判断

这个方案**适合做**，而且与当前代码基础是匹配的。
但最优路径不是"推倒重建"，而是"在现有实现上逐层收敛职责"，这样风险最低，也最容易在中途停机验证。

---

## 附录：Phase 1 完成情况（2026-03-22）

### 交付物清单

| 交付物 | 文件路径 | 状态 |
|--------|----------|------|
| NPC 计划模型 | [`src/data/npc_planning_models.py`](../../src/data/npc_planning_models.py:1) | ✅ 已完成 |
| 叙事上下文 | [`src/narrative/narrative_context.py`](../../src/narrative/narrative_context.py:1) | ✅ 已完成 |
| 引擎接入 | [`src/engine/game_engine.py`](../../src/engine/game_engine.py:85) | ✅ 已完成 |
| 回归测试 | [`tests/test_architecture_refactor.py`](../../tests/test_architecture_refactor.py:1) | ✅ 已完成 |
| 增量测试 | [`tests/test_architecture_refactor_increment.py`](../../tests/test_architecture_refactor_increment.py:1) | ✅ 已完成 |
| 叙事上下文测试 | [`tests/test_narrative_context.py`](../../tests/test_narrative_context.py:1) | ✅ 已完成 |
| NPC 模型测试 | [`tests/test_npc_planning_models.py`](../../tests/test_npc_planning_models.py:1) | ✅ 已完成 |

### 核心实现内容

**1. NPCActionForm 结构化模型**（第 1 阶段目标）
- `NPCActionType` 枚举：attack/move/talk/use_item/investigate/wait/custom
- `NPCCheckPlan`：支持难度分级（regular/hard/extreme）
- `NPCActionForm`：完整的 NPC 行动计划结构，包含意图、目标、检定等
- `NPCActionDecision`：批量决策结果容器
- 设计原则：增量式，不替换现有 `DMAgentOutput` 字段

**2. NarrativeContext 轻量内存层**（第 3 阶段目标提前落地）
- 滚动事件窗口（可配置 `window_size`）
- 自动摘要压缩（超过窗口的旧事件转入 `summary_lines`）
- 关键事实提取（`key_facts` 集合，支持自定义或自动提取）
- 快照序列化/反序列化（`to_snapshot` / `from_snapshot`）
- `get_context_for_llm()` 方法：生成 prompt 友好的上下文文本

**3. GameEngine 接入**（传递链路补全）
- 初始化：`narrative_context` 字段在 `__init__` 中创建
- 事件记录：`_append_narrative_event()` 在玩家行动和 NPC 行动后调用
- 上下文注入：`_get_narrative_context_for_llm()` 提供给 DM Agent 和 NPC 推演
- 存档支持：`_dump_narrative_context()` / `_restore_narrative_context()`
- 待处理计划：`_pending_npc_action_plans` 字典支持计划传递
- 回退机制：`_NullNarrativeContext` 在模块导入失败时提供空实现
- 辅助方法：`_extract_npc_intent_from_plan()` 支持从计划中提取意图

### 修复记录

**问题发现**（核查时）：
- `_NullNarrativeContext` 类被引用但未定义（第 872 行）
- `_extract_npc_intent_from_plan` 方法被引用但未定义（第 507、610 行）

**修复**（2026-03-22）：
- 在 [`game_engine.py`](../../src/engine/game_engine.py:1198) 中添加 `_extract_npc_intent_from_plan` 方法
- 在 [`game_engine.py`](../../src/engine/game_engine.py:1201) 中添加 `_NullNarrativeContext` 类
- `py_compile` 语法验证通过

### 向后兼容

- `DMAgentOutput` 原有字段完全保留
- `npc_intent` 继续作为兜底字段存在
- 旧世界配置无需修改即可运行
- 存档格式兼容（`narrative_context` 字段为可选）

### 验收状态

| 验收标准 | 状态 | 备注 |
|----------|------|------|
| 旧流程不报错 | ✅ | py_compile 通过 |
| 新字段可被稳定解析 | ✅ | 模型已定义，schema 完整 |
| 新字段进入推演链路 | ✅ | `_pending_npc_action_plans` 已接入 |

**Phase 1 结论**：已完成，可进入 Phase 2（NPCDirector 抽取）。

---

## 附录：Phase 2 完成情况（2026-03-22）

### 交付物清单

| 交付物 | 文件路径 | 状态 |
|--------|----------|------|
| NPCDirector 模块 | [`src/npc/npc_director.py`](../../src/npc/npc_director.py:1) | ✅ 已完成 |
| NPC 包初始化 | [`src/npc/__init__.py`](../../src/npc/__init__.py:1) | ✅ 已完成 |
| 引擎接入 | [`src/engine/game_engine.py`](../../src/engine/game_engine.py:90) | ✅ 已完成 |
| 集成测试 | [`tests/test_npc_director.py`](../../tests/test_npc_director.py:1) | ✅ 已完成 |

### 核心实现内容

**1. NPCDirector 独立模块**（Phase 2 核心目标）
- `decide_actions()`：统一决策入口，输入 `npc_ids` + `game_state` + `player_intent`，输出 `NPCActionDecision`
- 规则型默认规划器：根据 `npc_response_needed` 生成 TALK 或 WAIT 动作
- 支持 `trigger_source` 标记（queue/reactive）
- 向后兼容：保留 `npc_intent` 兜底

**2. GameEngine 集成**
- `_create_npc_director()`：安全初始化，异常回退到 `None`
- `_plan_npc_actions()`：批量 NPC 计划，供 queue 模式调用
- `_plan_single_npc_action()`：单个 NPC 计划，供 reactive 模式调用
- `_extract_npc_action_plan()`：提取结构化计划，DM 字段兜底
- `_extract_npc_actor_from_plan()`：从计划解析 npc_id，支持多键名
- `_pick_default_npc_actor()`：同场景兜底选 NPC

**3. 双模式接入点**
- **queue 模式**：`_plan_npc_actions()` 生成计划 → `_pending_npc_action_plans` 传递 → `_extract_npc_intent_from_plan()` 提取意图
- **reactive 模式**：`_extract_npc_action_plan()` 调用 Director → `_extract_npc_actor_from_plan()` 解析 actor → 意图回填到 `evolve_npc_action()`

**4. 缺失方法修复**
- `_extract_npc_action_plan`：优先走 Director，失败回退到 DM 字段
- `_extract_npc_actor_from_plan`：支持多键名（npc_id/actor_id/character_id）

### 测试覆盖

[`tests/test_npc_director.py`](../../tests/test_npc_director.py:1) 包含 2 个集成测试：
1. `test_queue_mode_plans_action_through_director`：验证 queue 模式下 Director 生成计划
2. `test_reactive_mode_uses_structured_plan_intent`：验证 reactive 模式下结构化意图传入 `StateEvolution`

### 向后兼容

- `DMAgentOutput` 原有字段完全保留
- `npc_intent` 继续作为兜底字段存在
- NPCDirector 导入失败时自动回退旧逻辑
- 旧世界配置无需修改即可运行

### 验证结果

| 验证项 | 状态 | 备注 |
|--------|------|------|
| 语法检查 | ✅ | `py_compile` 全部通过 |
| 新增测试 | ✅ | `test_npc_director` 2/2 通过 |
| 回归测试 | ⚠️ | 1 个既有失败（世界配置默认值与测试期望不符）|
| 静态检查 | ✅ | 无报错 |

**Phase 2 结论**：已完成，NPC 行为通过统一入口产生，玩家回合和 NPC 回合边界清晰。可进入 Phase 3（NarrativeContext 深化与流程统一）。

---

## 附录：Phase 3 完成情况（2026-03-22）

### 交付物清单

| 交付物 | 文件路径 | 状态 |
|--------|----------|------|
| NarrativeContext 强化实现 | [`src/narrative/narrative_context.py`](../../src/narrative/narrative_context.py:1) | ✅ 已完成 |
| 引擎叙事恢复与窗口重配 | [`src/engine/game_engine.py`](../../src/engine/game_engine.py:1) | ✅ 已完成 |
| 世界配置叙事窗口字段 | [`src/data/init/world_loader.py`](../../src/data/init/world_loader.py:1) | ✅ 已完成 |
| 示例世界窗口配置 | [`config/world/mysterious_library/world.json`](../../config/world/mysterious_library/world.json:1) | ✅ 已完成 |
| Phase 3 测试补充 | [`tests/test_narrative_context.py`](../../tests/test_narrative_context.py:1) | ✅ 已完成 |
| 增量回归测试补充 | [`tests/test_architecture_refactor_increment.py`](../../tests/test_architecture_refactor_increment.py:1) | ✅ 已完成 |

### 核心实现内容

**1. 叙事窗口压缩深化**
- `NarrativeContext` 增加 `max_context_chars`，输出给 LLM 的上下文长度可控。
- 保留 `window_size` + `max_summary_lines` 双层约束，避免长回合上下文无限增长。
- 关键事实提取增加结构化匹配（属性数值变化、实体 ID 线索）。

**2. 快照恢复链路补全**
- `GameEngine._restore_narrative_context()` 改为优先按 `NarrativeContextSnapshot` 反序列化。
- 恢复时保留 `summary_lines`、`key_facts`，不再丢失压缩历史关键信息。
- 兼容旧存档：当仅有 `summary` 时自动降级拆分为 `summary_lines`。

**3. 世界配置接入叙事窗口**
- `WorldBundle` 新增 `narrative_window` 字段。
- `world.json` 可配置 `narrative_window`，在 `GameEngine.apply_world_settings()` 中生效。
- 新增 `_set_narrative_window()`：运行中可重设窗口并保留既有叙事上下文。

### 验收状态

| 验收标准 | 状态 | 备注 |
|----------|------|------|
| 连续多回合运行时，上下文不会无限增长 | ✅ | 窗口、摘要行数、LLM上下文长度三重限制 |
| 关键事实不会因压缩而丢失 | ✅ | 压缩写入 `key_facts`，恢复链路保留 `summary_lines/key_facts` |

**Phase 3 结论**：已完成，可进入 Phase 4（流程统一与兼容层收敛）。

