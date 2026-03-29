# StateEvolution NPC 扮演功能 Review 报告

## 日期
2026-03-27

## 审查目标
研究 StateEvolution 提示词中关于 NPC 扮演部分的内容是否可以删除。

## 现状分析

### 1. 提示词中的 NPC 相关内容

| 位置 | 内容 | 建议操作 |
|------|------|----------|
| 第11行 | 职责包含"在NPC推演时，扮演该NPC做出符合其性格的行动" | 修改描述，明确为"生成"而非"扮演" |
| 第124-165行 | NPC推演指南完整章节 | 大幅简化，去除决策相关内容 |
| 第254-272行 | 示例3: NPC推演示例 | 删除或替换为执行层示例 |

### 2. 代码层面的调用关系

**调用点（不能删除的原因）：**
- `src/engine/game_engine.py:598` - `_process_npc_turns_until_player()`
- `src/engine/game_engine.py:708` - `_reactive_npc_flow()`
- `src/engine/game_engine.py:1765` - `_unified_post_npc_flow()`

**核心方法：**
```python
# src/agent/state_evolution.py:192
def evolve_npc_action(
    self,
    npc_id: str,
    game_state: GameState,
    check_result: Optional[CheckOutput] = None,
    npc_intent: Optional[str] = None,
    additional_context: Optional[Dict[str, Any]] = None
) -> StateEvolutionOutput
```

### 3. 职责分工

```
┌─────────────────────────────────────────────────────────────┐
│  NPCDirector (决策层)                                        │
│  - decide_actions()                                         │
│  - 决定NPC"要做什么"（意图决策）                             │
│  - 输出: NPCActionDecision (action_type, intent_description)│
└──────────────────────┬──────────────────────────────────────┘
                       │ npc_intent
                       ↓
┌─────────────────────────────────────────────────────────────┐
│  StateEvolution (执行层)                                     │
│  - evolve_npc_action()                                      │
│  - 将意图转化为"叙事+状态变更"                               │
│  - 输出: StateEvolutionOutput (narrative, changes)          │
└─────────────────────────────────────────────────────────────┘
```

## 核心结论

**不能删除**，但可以**精简**。StateEvolution 的 `evolve_npc_action()` 方法承担着将 NPC 意图转化为具体叙事和状态变更的关键职责，与 NPCDirector 形成"决策-执行"的分层架构。

## 建议的精简方案

### 1. 提示词修改建议

#### (1) 第11行职责描述修改
```diff
- 4. 在NPC推演时，扮演该NPC做出符合其性格的行动 
+ 4. 根据NPC意图生成行动的叙事描述和状态变更
```

#### (2) 第124-165行 NPC推演指南简化

**当前内容过多：**
- NPC决策考量（性格、目标、关系等）→ 应由NPCDirector负责
- 双模式触发语义（已存在但需简化）
- 模拟鉴定说明

**建议精简为：**
```markdown
## NPC行动执行指南

当推演NPC行动时，你的职责是将已决策的NPC意图转化为：

1. **叙事生成**：描述NPC如何执行该行动（保持第二人称视角）
2. **状态变更**：生成行动带来的具体状态变化
3. **检定处理**：若提供了check_result，将其纳入推演

### 输入来源
- npc_intent: NPCDirector提供的意图描述
- check_result: NPC行动的检定结果（如有）

### 约束
- 不要重新决策NPC应该做什么，专注于描述如何做
- 保持与NPC性格一致的表现方式
- 遵循mode/trigger的行为约束（不重复玩家叙事等）
```

#### (3) 删除或替换示例3

当前示例3是NPC推演示例，建议：
- 方案A：直接删除
- 方案B：替换为"执行层"示例，展示如何根据意图生成叙事和变更

### 2. 代码层面无需修改

`evolve_npc_action()` 方法的职责清晰，接口合理，不需要改动。

## 实施建议

1. **先修改提示词**，观察效果
2. **保留回滚能力**，备份原提示词
3. **测试覆盖**：确保 `_process_npc_turns_until_player()`、`_reactive_npc_flow()`、`_unified_post_npc_flow()` 三个调用点正常工作

## 相关文件

- `src/agent/prompt/state_evolution_prompt.md` - 待修改的提示词
- `src/agent/state_evolution.py` - 实现代码
- `src/agent/npc/npc_director.py` - NPC决策层
- `src/engine/game_engine.py` - 调用方

## 决策记录

| 项目 | 决策 |
|------|------|
| 是否删除NPC功能 | ❌ 否 |
| 是否删除`evolve_npc_action()` | ❌ 否 |
| 是否精简提示词 | ✅ 是 |
| 是否修改职责描述 | ✅ 是 |
