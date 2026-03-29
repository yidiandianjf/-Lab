# 叙事稳定性与信息链路一致性专项研究

**生成日期:** 2026-03-28  
**研究目标:** 从游玩过程中叙事稳定性、临时链路信息保真、状态与自然语言一致性三个角度，审查各个 LLM 的输入/输出上下文设计，并判断系统是否具备 50 回合内稳定叙事的基础。

---

## 1. 先回答当前怀疑点

### 1.1 如果玩家与 NPC 连续对话 10 次以上，NPCDirector 能否保证一致性？

**结论：当前不能保证。**

原因不是单点失效，而是记忆链路分散且没有统一真值：

1. `DMAgent` 理论上支持 `dialogue_history` 输入，但主流程没有把 `dm_dialogue_log` 传回 `parse_intent()`。
   - `src/engine/game_engine.py:402-406`
   - `src/agent/dm_agent.py:177-219`
   - `src/engine/game_engine.py:1142-1146`

2. `NPCDirector` 不接收 `dm_dialogue_log`，只接收：
   - `player_intent`（DM 的当前回合结构化输出）
   - `recent_events[-10:]`
   - `narrative_context`（文本摘要）
   - `npc_states`
   - `src/engine/game_engine.py:1240-1286`
   - `src/agent/npc/npc_director.py:144-156`

3. `narrative_context` 默认窗口只有 5 条近期事件，旧事件会被压缩成摘要行。
   - `src/narrative/narrative_context.py:34-60`

4. `recent_events` 记录的是“回合事件片段”，不是“结构化对话轮次”。  
   连续 10 次以上对话时，系统主要依赖摘要文本和关键词抽取，而不是稳定的对话状态机。

**这意味着：**
- NPCDirector 对长期对话的一致性，依赖压缩后的自然语言摘要而不是结构化对话记忆。
- 一旦摘要丢失语气、承诺、立场变化、称谓指代，NPC 就可能“忘记刚刚自己说过的话”。
- 对于 10 次以上对话，当前链路只具备“弱延续”，不具备“强一致”。

---

### 1.1.1 持久化信息和叙事上下文等自然语言信息能否保障一致性不脱钩？

**结论：只能部分保障，仍然可能脱钩。**

当前系统有两条并行存储线：

1. **结构化真值线**
   - `GameState`
   - 持久层中的 characters/items/maps/meta

2. **自然语言叙事线**
   - `narrative_context`
   - `dm_dialogue_log`
   - `current_event`

**一致性好的地方：**
- 每回合成功合并后的 `merged_narrative` 会写入 `NarrativeContext`
  - `src/engine/game_engine.py:475-490`
- 存档会保存 `dm_dialogue_log` 和 `narrative_context`
  - `src/engine/game_engine.py:230-266`
- 读档会恢复 `dm_dialogue_log` 和 `narrative_context`
  - `src/engine/game_engine.py:171-220`

**一致性不足的地方：**
- `dm_dialogue_log` 会保存，但当前主流程没有再把它喂回 DM/NPCDirector。
- `narrative_context` 中的 `key_facts` 来自文本启发式抽取，不是从 `StateChange` 或 `GameState` 直接生成。
  - `src/narrative/narrative_context.py:121-140`
- `NarrativeMerger` 的 `truth_anchor` 只锚定玩家阶段，不锚定完整 NPC 链。
  - `src/engine/game_engine.py:1683-1699`
  - `src/narrative/prompt/narrative_merger_prompt.md`

**结果：**
- “状态真值”与“叙事记忆”不会立刻分裂，但长期运行后可能出现弱脱钩。
- 当前系统更像“状态正确 + 叙事尽量跟上”，还不是“叙事与状态同源生成”。

---

### 1.2 你的临时链路担忧是否成立？

**结论：成立，而且是当前最大的链路一致性缺口之一。**

你举的例子是：

`玩家攻击 NPC1 失败 -> NPC1 反击 -> NPC2 逃跑`

你希望 `StateEvolution` 在处理 NPC2 时，还能知道：
- 玩家攻击失败
- NPC1 反击成功
- 这些都属于“本回合尚未叙事合并的临时链路信息”

**当前实际情况：**

1. `DMAgent` 产出 `action_description`
2. 玩家 `StateEvolution` 产出 `player_narrative + player_changes`
3. `player_resolution_anchor` 会包含：
   - `action_description`
   - `check_result`
   - `player_narrative`
   - `player_changes`
   - `src/engine/game_engine.py:1804-1830`
4. `NPCDirector` 能看到：
   - `player_intent`（含 `action_description`）
   - `narrative_context`
   - 追加到文本中的 `player_resolution_anchor`
   - `src/engine/game_engine.py:1272-1286`
5. `NPC StateEvolution` 能看到：
   - `player_action_description`
   - `player_check_result`
   - `player_resolution_anchor`
   - `npc_action_plan`
   - `narrative_context`
   - `src/engine/game_engine.py:1214-1237`
   - `src/engine/game_engine.py:1765-1775`

**但是关键断点在这里：**
- 在 `_process_unified_npc_response()` 中，多个 NPC 是顺序推演的
- 每个 NPC 的 `npc_output` 只被加入 `fragments`
- 这些临时结果不会在同回合内回写到 `narrative_context`
- 后一个 NPC 推演时，也拿不到前一个 NPC 的 `narrative/check_result/changes`
  - `src/engine/game_engine.py:1749-1799`

**所以当前链路能力是：**
- NPC2 知道玩家阶段的检定结果与叙事事实
- NPC2 不知道 NPC1 刚刚在同回合做了什么

**结论：**
- 玩家阶段 -> NPC阶段：链路是半通的
- NPC1 -> NPC2：链路是断的
- NarrativeMerger 只是在最后补做文本合并，不会反向修复 NPC2 决策时的信息缺失

---

## 2. 当前链路中的四类上下文

为了讨论字段合并/分离，先把当前上下文分成四类：

### 2.1 世界真值上下文

来源：
- `GameState`
- IO 持久层

特点：
- 是唯一应该被视为“结构化事实”的来源
- 应承载角色位置、背包、数值状态、地图连接等

### 2.2 长期叙事记忆上下文

来源：
- `NarrativeContext.summary_lines`
- `NarrativeContext.recent_events`
- `NarrativeContext.key_facts`

特点：
- 面向 LLM 的长期压缩记忆
- 当前是自然语言摘要，不是结构化世界事实

### 2.3 回合内临时链路上下文

当前散落在：
- `action_description`
- `player_check_result`
- `player_resolution_anchor`
- `npc_action_plan`
- `fragments`

特点：
- 表示“当前回合正在发生、尚未落库成统一叙事”的信息
- 目前没有统一数据结构
- 这是链路一致性最弱的一层

### 2.4 对话记忆上下文

来源：
- `dm_dialogue_log`

特点：
- 当前已保存，但未进入主链路消费
- 处于“有存档价值、无推理价值”的悬空状态

---

## 3. 字段合并、字段分离、字段删除建议

## 3.1 应合并的字段

### A. `player_check_result` 与 `player_resolution_anchor`

**当前问题：**
- 两者都在传玩家检定结果
- 一个是裸检定结果，一个是带锚点的扩展对象
- 在 DM、NPC、Narrative 阶段重复出现

**建议：**
- 保留一个统一对象：`turn_resolution`
- 结构建议：

```json
{
  "actor_id": "char-player-01",
  "phase": "player",
  "raw_input": "我要攻击守卫",
  "intent_text": "玩家试图攻击守卫",
  "check": {...},
  "narrative": "...",
  "changes": [...],
  "outcome": {
    "action_succeeded": false,
    "check_outcome": "失败"
  }
}
```

**理由：**
- 一个对象同时覆盖检定、临时叙事、变更、成败结论
- 让下游不需要同时理解两个相近字段

---

### B. `action_description` 与原始输入的角色描述责任

**当前问题：**
- `action_description` 既像“DM 的路由结果”，又像“状态推演的任务文本”
- 但它并不稳定：有时是玩家意图，有时会承载模式提示

**建议：**
- 不要简单删除，而是拆成两个字段后再收敛：
  - `raw_input_text`: 玩家原始输入
  - `intent_text`: 结构化后的客观动作描述

**理由：**
- 原始输入保留语言细节和对话语气
- `intent_text` 保留规则/路由所需的规范表达
- 如果完全删掉 `action_description`，会让 DM 到 StateEvolution 的“解释层”消失

**结论：**
- 不是“删掉 action_description”
- 而是“把 action_description 一分为二，再按职责使用”

---

## 3.2 应分离的字段

### A. `player_intent` 不应整包传给 NPCDirector

**当前问题：**
- Director 接收完整 `DMAgentOutput`
- 含 `response_to_player`、`check_type`、`difficulty`、`npc_actor_id` 等过多字段
- 这些字段中有的属于 DM 层，有的属于 NPC 激活层，有的属于纯展示

**建议分离为：**

```json
{
  "activation": {
    "candidate_npc_ids": [...],
    "forced_actor_id": "...",
    "response_needed": true
  },
  "player_turn_resolution": {...},
  "player_dialogue_signal": {
    "raw_input_text": "...",
    "intent_text": "..."
  }
}
```

**理由：**
- Director 需要的是“谁该动”和“玩家刚刚做成/做败了什么”
- 不需要 DM 的完整输出协议

---

### B. 长期叙事记忆 与 同回合临时链路必须分开

**当前问题：**
- `narrative_context` 同时承担长期记忆和回合输入补充
- 但它不会在同回合的多个 NPC 之间即时更新

**建议：**
- 新增 `turn_trace` / `turn_context`
- `narrative_context` 只负责长期记忆
- `turn_trace` 负责当前回合内尚未合并的结构化步骤

**建议结构：**

```json
{
  "turn_id": 12,
  "steps": [
    {
      "actor_id": "char-player-01",
      "kind": "player_action",
      "raw_input_text": "...",
      "intent_text": "...",
      "check": {...},
      "narrative": "...",
      "changes": [...]
    },
    {
      "actor_id": "char-guard-01",
      "kind": "npc_action",
      "plan": {...},
      "check": {...},
      "narrative": "...",
      "changes": [...]
    }
  ]
}
```

**这样做的好处：**
- NPC2 可以读取 NPC1 的结果
- NarrativeMerger 也可以直接吃 `turn_trace.steps`
- 叙事合并后再将最终结果压缩进入 `narrative_context`

---

## 3.3 不应该交给代码判断的字段

这里的意思不是“不要校验”，而是“不要改成纯硬编码决策”。

### A. 应继续交给 LLM 的字段

1. `intent_text` / 玩家动作语义解释  
   原始玩家输入经常有代词、省略、模糊动机，不能完全用规则替代。

2. `npc_intent_description` / NPC行动意图  
   可由 Director 生成，不能完全硬编码。

3. `narrative`
   叙事文本本身仍应由 LLM 负责。

4. `rationale` / Director整体协调理由  
   对系统可解释性有帮助。

### B. 不应再交给 LLM 判断、应收回代码的字段

1. `candidate_npc_ids`
2. `actionable_npcs`
3. `forced_actor_id` 是否合法
4. `check_attributes` 是否在规则支持范围内
5. `check_target` 是否存在
6. `difficulty` 是否属于允许枚举
7. `changes` 的字段路径合法性

**结论：**
- “创造性解释”和“叙事表达”继续交给 LLM
- “合法性、筛选、激活、实体存在性”必须交给代码

---

## 4. 当前提示词和字段是否冗余

**结论：冗余明显，而且存在历史遗留未清理。**

### 4.1 冗余字段

1. `player_check_result` 与 `player_resolution_anchor`
2. `inventory` 与 `inventory_details`
3. `player_intent` 整包传给 Director
4. `narrative_context` 与 `recent_events` 的职责边界不清

### 4.2 历史遗留提示词问题

1. `system_prompt.md` 仍保留 `#修改建议` 与示例中的 `---`
   - `src/agent/prompt/system_prompt.md:89-96`

2. `state_evolution_prompt.md` 仍保留 `Move` 草案说明
   - `src/agent/prompt/state_evolution_prompt.md:71`

3. NPC 推演提示仍提到不存在的 `npc_action` 字段
   - `src/agent/state_evolution.py:540`

4. Prompt 中仍要求物品转移时人工维护 inventory 双向关系
   - 但当前 IO 层已经在做这件事
   - `src/agent/prompt/state_evolution_prompt.md:193`

---

## 5. 当前输入字段是否被完整解释给 LLM

**结论：解释不完整。**

### 比较清楚的

- `check_result`
- `player_resolution_anchor`
- `npc_response_mode`

### 不够清楚的

1. `engine_context`
   - 只是一大块 JSON，没有明确“能用来做什么、不能用来做什么”

2. `narrative_context`
   - LLM 知道这是上下文，但不知道它是“摘要+近几轮事件+key facts”的混合体

3. `recent_events`
   - 没解释与 `narrative_context` 的职责区别

4. `action_queue`
   - 对 DM 和 StateEvolution 来说意义模糊

5. `npc_action_plan`
   - 给了结构，但没有系统性说明“哪些字段是强约束，哪些是建议”

---

## 6. 对 50 回合叙事稳定性的判断

**结论：当前系统不具备“可自信承诺 50 回合稳定叙事”的条件。**

### 当前的上限更接近：
- 5 回合内：基本可控
- 10 回合左右：开始依赖摘要质量
- 20 回合以上：对话一致性和临时因果链会明显变弱
- 50 回合：如果没有新的结构化链路设计，大概率出现记忆漂移、立场漂移、信息脱钩

### 核心原因

1. 没有统一的“回合内临时链路对象”
2. `dm_dialogue_log` 未进入推理链
3. `NarrativeContext` 主要是自然语言压缩，不是结构化剧情状态
4. 多 NPC 同回合之间不能共享即时结果
5. NarrativeMerger 的锚点只覆盖玩家阶段，不覆盖完整回合链

---

## 7. 建议的目标设计

如果目标是“50 回合内叙事稳定”，建议将链路改为：

### 7.1 DM 层

输入：
- `raw_input_text`
- `dialogue_memory`（结构化）
- `narrative_context`（长期摘要）
- `world_state_view`

输出：
- `intent_text`
- `interaction_type`
- `check_plan`
- `activation_hint`

### 7.2 Player StateEvolution 层

输入：
- `raw_input_text`
- `intent_text`
- `check_result`
- `narrative_context`

输出：
- `turn_step`

### 7.3 NPCDirector 层

输入：
- `turn_trace_so_far`
- `activated_npcs`
- `npc_world_views`
- `narrative_context`

输出：
- `npc_action_plans[]`

### 7.4 NPC StateEvolution 层

输入：
- `turn_trace_so_far`
- 当前 `npc_action_plan`
- 当前 NPC 检定结果
- `narrative_context`

输出：
- 一个新的 `turn_step`

### 7.5 NarrativeMerger 层

输入：
- `turn_trace.steps`
- `narrative_context`
- `turn_truth_anchor`

输出：
- `merged_narrative`
- `turn_summary`
- `new_key_facts`

### 7.6 持久化层

必须同时保存：
- `GameState`
- `NarrativeContext`
- `DialogueMemory`
- 最近 N 回合 `turn_trace` 历史摘要

---

## 8. 最终判断

### 你的几个核心判断里，我认为正确的部分

1. `DMAgent` 更应该是链路路由器，而不是事实生产者  
   这个判断是对的。

2. `StateEvolution` 需要接入叙事上下文  
   当前玩家阶段已经有，但还不够系统化。

3. Director 应该获得被激活 NPC 的完整字段信息  
   对，目前给得过少。

4. 同回合多个 NPC 需要共享未合并的临时链路信息  
   对，这是当前最大缺口之一。

5. 最终应该由叙事层完成合并，再统一回写长期记忆  
   对，这个总方向也是合理的。

### 我不同意的部分

你说 `action_description` 可以直接删掉，原句直接复制过去。  
**我不建议直接删。**

更好的做法是：
- 保留原句：`raw_input_text`
- 保留解释层：`intent_text`

因为系统既需要“玩家说了什么”，也需要“规则理解成了什么动作”。

---

## 9. 一句话结论

当前系统已经有“玩家阶段事实锚点”，但还没有“整回合统一链路锚点”；要把叙事稳定性提升到 50 回合级别，必须把 `dm_dialogue_log`、`NarrativeContext`、`turn_trace` 三者收敛成同一条被代码显式维护的信息链。
