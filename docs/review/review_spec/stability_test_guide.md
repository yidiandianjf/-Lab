# 稳定性测试指南

## 概述

本文档介绍如何测试系统在50+回合下的稳定性，确保系统不出现bug或数据不一致。

---

## 一、自动化稳定性测试

### 1.1 快速开始

使用预写的稳定性测试脚本：

```bash
# 运行50回合测试（默认）
python tests/stability_test.py

# 运行100回合测试
python tests/stability_test.py --rounds 100

# 启用详细调试
python tests/stability_test.py --debug

# 每5回合保存一次
python tests/stability_test.py --save-interval 5
```

### 1.2 测试脚本功能

| 功能 | 说明 |
|-----|------|
| **预设动作池** | 循环使用15个预设动作模拟玩家输入 |
| **自动保存** | 定期保存游戏状态，便于复现问题 |
| **DebugLogger集成** | 自动启用一致性检查和详细日志 |
| **结果统计** | 输出成功率、失败回合列表、错误摘要 |
| **JSON报告** | 保存详细测试结果到 `logs/stability_test/` |

### 1.3 测试结果解读

```
============================================================
测试摘要
============================================================
总时长: 345.23 秒
总回合数: 50
成功回合: 48
失败回合: 2
失败回合列表: [12, 37]
错误数量: 2
  - round_12: 状态变更失败
  - round_37: 实体ID不存在
成功率: 96.0%
✓ 测试通过 (≥ 95% 成功率)
```

**通过标准**：≥ 95% 成功率

---

## 二、手动压力测试

### 2.1 使用DebugLogger监控

编辑 `debug_config.yaml` 启用完整调试：

```yaml
debug:
  enabled: true
  log_level: "debug"
  log_dir: "logs"
  
  outputs:
    master_log: true
    timeline_json: true
    categorized: true
    snapshots: true
    llm_prompts: true
  
  consistency:
    check_after_each_change: true
    check_after_turn: true
    warn_on_inconsistency: true
```

然后正常玩游戏50+回合。

### 2.2 测试场景建议

| 场景类型 | 测试动作 | 预期结果 |
|---------|---------|---------|
| **移动测试** | 反复在地图间移动 | location正确更新，inventory正常同步 |
| **物品交互** | 拾取、丢弃、传递物品 | 物品位置和inventory保持一致 |
| **检定测试** | 连续进行高难度检定 | SAN/HP变化在合理范围 |
| **NPC对话** | 与多个NPC连续对话 | NPC响应正常，无状态混乱 |
| **多回合** | 50+回合各种混合动作 | 无崩溃，状态一致性检查通过 |

### 2.3 手动测试检查清单

- [ ] 所有回合无崩溃
- [ ] 无状态变更失败
- [ ] 一致性检查无警告
- [ ] 角色HP/SAN变化合理
- [ ] 物品位置与inventory同步
- [ ] NPC响应正常
- [ ] 叙事连贯，无重复或跳变

---

## 三、单元测试覆盖

运行现有单元测试：

```bash
# 运行所有测试
python -m pytest tests/ -v

# 运行特定测试文件
python -m pytest tests/test_regression_flow.py -v
python -m pytest tests/test_state_evolution_error_feedback.py -v
python -m pytest tests/test_debug_consistency.py -v

# 运行测试并生成覆盖率报告
python -m pytest tests/ --cov=src --cov-report=html
```

### 关键测试文件

| 测试文件 | 覆盖范围 |
|---------|---------|
| `test_regression_flow.py` | 游戏流程、回滚、事务处理 |
| `test_state_evolution_error_feedback.py` | 状态变更验证、错误反馈重试 |
| `test_debug_consistency.py` | 一致性检查功能 |
| `test_npc_director.py` | NPC Director功能 |

---

## 四、常见问题排查

### 4.1 状态变更失败

**症状**：回合失败，错误提示"状态变更失败"

**排查步骤**：
1. 查看 `logs/stability_test/latest/master.log`
2. 检查失败回合的 `state_changes`
3. 验证变更操作是否符合字段限制（参考 `state_evolution_llm_constraints.md`）
4. 使用DebugLogger的timeline.json查看完整历史

### 4.2 数据不一致

**症状**：一致性检查警告

**常见原因**：
- 物品location与inventory不同步
- 角色location与map.entities.characters不同步
- 列表字段被错误操作

**修复**：
1. 检查是否使用了move操作处理location
2. 验证del/add操作是否在白名单字段上
3. 查看DebugLogger的consistency_issues日志

### 4.3 LLM输出格式错误

**症状**：JSON解析失败或schema验证失败

**排查**：
1. 查看 `logs/stability_test/latest/turns/turn_xxx/llm_*_request.txt` 和 `llm_*_response.txt`
2. 检查LLM是否遵守JSON Schema
3. 验证是否有错误反馈重试机制触发

---

## 五、测试报告模板

### 5.1 稳定性测试报告

```
稳定性测试报告
日期: 2026-03-28
测试者: [姓名]
版本: [Git commit hash]

1. 测试概述
   - 测试回合数: 100
   - 持续时间: 620秒
   - 测试世界: mysterious_library

2. 结果统计
   - 成功回合: 98
   - 失败回合: 2
   - 成功率: 98.0%
   - 一致性警告: 1

3. 失败详情
   - 回合23: 状态变更失败 (item.location错误)
   - 回合76: NPC Director超时

4. 结论
   ✓ 测试通过 (≥95% 成功率)
   建议: 优化item.location同步逻辑

5. 附件
   - 完整日志: logs/stability_test/xxx/
   - 测试结果: stability_test_results_xxx.json
```

---

## 六、CI/CD集成

### 6.1 GitHub Actions示例

```yaml
name: Stability Test

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  stability:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      - name: Run stability test (20 rounds)
        run: python tests/stability_test.py --rounds 20
      
      - name: Upload test results
        uses: actions/upload-artifact@v4
        with:
          name: stability-test-results
          path: logs/stability_test/
```

---

## 七、最佳实践

1. **先运行单元测试**：确保基础功能正常
2. **从小规模开始**：先测试10-20回合，确认稳定后再增加
3. **启用DebugLogger**：第一次测试必须启用，便于排查问题
4. **定期保存**：每5-10回合保存一次，便于复现
5. **混合动作**：避免只测试单一操作，使用各种混合场景
6. **对比测试**：修改代码前后运行相同测试，对比结果
7. **保存问题样本**：发现bug时保存游戏状态和日志
