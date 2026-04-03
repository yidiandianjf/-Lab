# Debug修改报告：`\\help` 意外触发 NPC 行动

## 1. 问题现象

操作序列：
1. 玩家执行动作（如拿起煤油灯）
2. 输入 `\\help`
3. 先出现 NPC 叙事，再出现帮助菜单

该行为不符合预期：`\\help` 应仅展示帮助，不应推进 NPC 回合。

## 2. 根因分析

文件：`src/engine/game_engine.py`

`process_input()` 在解析输入前执行了 NPC 前置回合处理：
- 先 `_turn_start()`
- 紧接 `_process_npc_turns_until_player()`
- 然后才 `parse_input(user_input)`

因此即使输入为基础指令（`\\help`、`\\status` 等），也会触发 NPC 行动。

## 3. 修复策略

目标：基础指令不触发 NPC 前置回合，只有自然语言动作才推进 NPC。

实施方式：
1. 保留 `_turn_start()`
2. 先执行 `parse_input()`
3. 若是基础指令，直接处理并返回
4. 仅在自然语言分支调用 `_process_npc_turns_until_player()`

## 4. 已实施代码修改

### 4.1 核心修复
- 文件：`src/engine/game_engine.py`
- 方法：`process_input()`
- 调整：将 NPC 前置回合调用移动到“自然语言输入分支”中

### 4.2 回归测试
- 文件：`tests/test_regression_flow.py`
- 新增测试：`test_help_command_should_not_trigger_npc_prelude`
- 验证点：
  - `\\help` 仍返回帮助菜单
  - `NpcCapableStateAgent.npc_calls == 0`
  - `DummyRuleSystem.calls == 0`

## 5. 同类风险审查

同类风险点：所有基础指令（`\\help`/`\\status`/`\\inventory`/`\\look`）都可能被前置回合误触发。

本次修复后：
- 基础指令路径统一不会触发 NPC 前置推进
- 自然语言路径保持原有 NPC 推进行为

## 6. 验证结论

通过新增回归测试和全量单测，确认 `\\help` 不再触发 NPC 行动，且原有流程未回归。
