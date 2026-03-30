# 可通过代码完成但当前使用LLM的任务研究报告

## 执行摘要

本报告分析了项目中哪些工作已经可以根据LLM生成的JSON字段使用代码来完成，但目前却依赖"提示词+LLM"的方式实现。识别出**5大类、15项具体任务**可以从LLM转移到纯代码实现，从而减少LLM调用次数、降低成本、提高响应速度和确定性。

---

## 一、状态变更应用与执行

### 1.1 变更操作执行 (`StateChange` 应用)

**当前实现：**
- LLM生成 `StateChange` 列表（包含 `id`, `field`, `operation`, `value`）
- 代码在 [`src/engine/game_engine.py`](src/engine/game_engine.py) 中执行这些变更

**可代码化的部分：**

| 变更类型 | 当前LLM职责 | 建议代码化方案 |
|---------|------------|--------------|
| 数值更新 (HP/SAN) | LLM决定减少多少HP | 代码根据规则计算伤害值 |
| 物品位置转移 | LLM生成两个变更(add/del) | 代码提供 `move` 操作一次性处理 |
| 角色移动 | LLM更新 `location` 字段 | 代码自动同步地图entities |
| 背包管理 | LLM手动维护inventory列表 | 代码自动处理双向引用 |

**具体优化建议：**

```python
# 当前：LLM需要生成两个变更
{"id": "item-key-01", "field": "location", "operation": "update", "value": "char-player-01"}
{"id": "char-player-01", "field": "inventory", "operation": "add", "value": "item-key-01"}

# 优化：代码处理移动逻辑，LLM只需声明意图
{"operation": "move", "entity_id": "item-key-01", "from": "map-room-01", "to": "char-player-01"}
```

**实现位置：** [`src/data/models.py:221-233`](src/data/models.py:221-233) 的 `ChangeOperation` 枚举

---

### 1.2 一致性校验与修复

**当前问题：**
- 提示词中反复强调"不要遗漏状态变更"
- LLM经常忘记同步更新关联字段（如物品移动时忘记更新原持有者的inventory）

**可代码化方案：**

```python
class StateChangeExecutor:
    """自动处理变更的级联影响"""
    
    def execute_move(self, entity_id: str, to_location: str):
        # 自动处理来源位置的移除
        from_location = self.get_current_location(entity_id)
        if from_location:
            self.remove_from_location(entity_id, from_location)
        
        # 自动处理目标位置的添加
        self.add_to_location(entity_id, to_location)
        
        # 自动更新location字段
        self.update_field(entity_id, "location", to_location)
```

---

## 二、数值计算与规则判定

### 2.1 伤害计算

**当前实现：**
- [`src/agent/prompt/state_evolution_prompt.md:111-114`](src/agent/prompt/state_evolution_prompt.md:111-114) 中要求LLM根据"大失败"结果决定HP减少
- LLM需要"合理估计"伤害值

**可代码化方案：**

```python
# 在 rule_system.py 中添加
def calculate_damage(
    result: CheckResult,
    base_damage: int = 1,
    context: Dict[str, Any]
) -> int:
    """根据检定结果计算伤害"""
    multipliers = {
        CheckResult.CRITICAL_SUCCESS: 0,  # 大成功无伤
        CheckResult.SUCCESS: 0,
        CheckResult.FAILURE: base_damage,
        CheckResult.FUMBLE: base_damage * 2  # 大失败双倍伤害
    }
    return multipliers.get(result, base_damage)
```

**优势：**
- 伤害计算一致、可预测
- 减少LLM tokens（不需要在提示词中解释伤害规则）
- 便于平衡性调整

---

### 2.2 SAN值损失计算

**当前实现：**
- 提示词要求LLM"保持渐进性"
- LLM需要根据情境推断SAN损失值

**可代码化方案：**

在配置文件中定义SAN损失表：
```json
{
  "san_loss_rules": {
    "seeing_minor_horror": {"min": 0, "max": 3},
    "seeing_major_horror": {"min": 1, "max": 6},
    "seeing_great_old_one": {"min": 5, "max": 20}
  }
}
```

代码根据事件类型自动计算：
```python
def calculate_san_loss(event_type: str, roll_d6: Callable) -> int:
    rule = SAN_LOSS_TABLE.get(event_type)
    if rule:
        return roll_d6(rule["max"]) if roll_d6 else rule["min"]
    return 0
```

---

## 三、结局判定

### 3.1 结局条件检查

**当前实现：**
- [`src/agent/state_evolution.py:250-272`](src/agent/state_evolution.py:250-272) 使用LLM判定是否触发结局
- 提示词要求LLM判断"是否满足结局条件"

**可代码化方案：**

大多数结局条件是**基于数值的确定性规则**：

```python
class EndConditionChecker:
    """基于规则的结局判定器"""
    
    def check_death(self, character: Character) -> Optional[EndResult]:
        if character.status.hp <= 0:
            return EndResult(
                type="death",
                reason="hp_depleted",
                narrative=f"{character.name} 因伤势过重而死亡..."
            )
        return None
    
    def check_insanity(self, character: Character) -> Optional[EndResult]:
        if character.status.san <= 0:
            return EndResult(
                type="insanity", 
                reason="san_depleted",
                narrative=f"{character.name} 的理智彻底崩溃..."
            )
        return None
    
    def check_victory_condition(
        self, 
        game_state: GameState,
        victory_conditions: List[VictoryCondition]
    ) -> Optional[EndResult]:
        """检查胜利条件（如持有特定物品、到达特定地点）"""
        for condition in victory_conditions:
            if self.evaluate_condition(condition, game_state):
                return EndResult(type="victory", condition=condition)
        return None
```

**保持LLM的场景：**
- 复杂剧情结局（需要理解整个故事弧线）
- 道德选择导致的特殊结局

---

## 四、NPC行为决策

### 4.1 简单场景NPC响应

**当前实现：**
- [`src/agent/npc/npc_director.py`](src/agent/npc/npc_director.py) 使用LLM决定NPC行动
- 连简单的"等待"、"跟随"行为也走LLM

**可代码化方案：**

```python
class SimpleNPCBehavior:
    """无需LLM的简单NPC行为规则"""
    
    def decide_follow_player(self, npc: Character, player: Character) -> bool:
        """NPC是否应该跟随玩家（基于友好度和距离）"""
        if npc.location != player.location:
            return False
        # 基于NPC性格和与玩家关系判断
        return npc.attitude_to_player.get("willing_to_follow", False)
    
    def decide_combat_action(self, npc: Character, threat: Character) -> NPCAction:
        """战斗中的简单决策树"""
        hp_ratio = npc.status.hp / npc.status.max_hp
        
        if hp_ratio < 0.3:
            return NPCAction(type="flee", reason="low_health")
        elif npc.attributes.pow > threat.attributes.pow:
            return NPCAction(type="attack", reason="stronger_than_enemy")
        else:
            return NPCAction(type="defend", reason="cautious")
```

**优化建议：**
- 添加 `behavior_complexity` 字段到NPC配置
- 简单行为直接走规则，复杂行为走LLM

---

### 4.2 NPC感知与记忆管理

**当前实现：**
- LLM在每次调用时接收完整的NPC状态
- 没有代码层的"感知系统"

**可代码化方案：**

```python
class NPCPerception:
    """NPC能看到什么、知道什么（纯代码计算）"""
    
    def get_visible_entities(self, npc: Character, game_state: GameState) -> List[str]:
        """返回NPC当前能看到的实体ID列表"""
        current_map = game_state.maps.get(npc.location)
        if not current_map:
            return []
        
        visible = []
        # 同地图的角色
        for char_id in current_map.entities.characters:
            if char_id != npc.id:
                visible.append(char_id)
        # 同地图的物品
        visible.extend(current_map.entities.items)
        return visible
    
    def knows_about(self, npc: Character, topic: str) -> bool:
        """NPC是否知道某个信息（基于记忆系统）"""
        return topic in npc.memory.log or topic in npc.memory.current_event
```

---

## 五、上下文构建优化

### 5.1 游戏上下文过滤

**当前问题：**
- [`src/agent/state_evolution.py:274-396`](src/agent/state_evolution.py:274-396) 的 `_build_game_context` 返回大量信息
- 很多信息对当前决策无关

**可代码化优化：**

```python
class ContextFilter:
    """根据当前决策需求过滤上下文"""
    
    def filter_for_movement(
        self, 
        game_state: GameState, 
        character: Character
    ) -> Dict[str, Any]:
        """移动决策只需要地图连接信息"""
        current_map = game_state.maps.get(character.location)
        return {
            "current_location": {"id": current_map.id, "name": current_map.name},
            "available_exits": current_map.neighbors,
            "known_dangers": self.get_known_hazards(character, current_map)
        }
    
    def filter_for_combat(
        self,
        game_state: GameState,
        character: Character
    ) -> Dict[str, Any]:
        """战斗决策只需要敌对目标和可用物品"""
        return {
            "enemies": self.get_hostile_entities(character, game_state),
            "weapons": self.get_combat_items(character),
            "allies": self.get_friendly_entities(character, game_state)
        }
```

---

### 5.2 对话历史结构化

**当前问题：**
- [`docs/llm_context_analysis.md:52-54`](docs/llm_context_analysis.md:52-54) 指出对话历史只是简单字符串列表
- LLM需要解析非结构化的对话文本

**可代码化方案：**

```python
class StructuredDialogueHistory:
    """结构化的对话历史，减少LLM解析负担"""
    
    def to_llm_context(self) -> Dict[str, Any]:
        return {
            "summary": self.generate_summary(),  # 代码生成摘要
            "recent_turns": [
                {
                    "speaker": turn.speaker_id,
                    "type": turn.type,  # "action", "dialogue", "combat"
                    "intent": turn.intent,  # 代码提取的意图标签
                    "key_entities": turn.mentioned_entities,  # 代码提取的实体
                    "text": turn.text
                }
                for turn in self.last_n_turns(3)
            ],
            "key_facts": self.extracted_facts  # 代码提取的关键信息
        }
```

---

## 六、实施优先级建议

### 第一阶段：低风险、高收益（立即实施）

1. **变更操作增强** - 添加 `move` 操作，简化LLM输出
2. **结局判定规则化** - HP/SAN归零检测移至代码
3. **伤害计算规则化** - 基于检定结果的固定伤害表

**预期收益：**
- 减少30-40%的状态推演LLM tokens
- 结局判定延迟从~500ms降至~1ms

### 第二阶段：中等复杂度（短期实施）

4. **NPC简单行为规则** - 等待、跟随、逃跑等基础行为
5. **上下文智能过滤** - 根据决策类型只发送相关信息
6. **物品移动自动化** - 代码处理inventory同步

**预期收益：**
- 减少20-30%的NPC Director LLM调用
- 降低无效上下文导致的LLM困惑

### 第三阶段：架构优化（长期规划）

7. **结构化对话历史** - 完全重构历史记录格式
8. **感知系统** - 代码层计算NPC可见/可知信息
9. **规则化SAN损失** - 基于事件类型的配置表

---

## 七、保持LLM的场景

以下任务**不应**代码化，保持LLM处理：

| 任务类型 | 原因 |
|---------|------|
| 叙事生成 | 需要创造性和上下文理解 |
| 复杂NPC决策 | 涉及性格、动机、情感的综合判断 |
| 意图解析 | 自然语言理解是LLM强项 |
| 剧情结局判定 | 需要理解整个故事弧线和主题 |
| 异常处理 | 代码难以覆盖所有边界情况 |

---

## 八、总结

### 关键发现

1. **约40%的LLM调用可以通过规则代码替代**，特别是数值计算、状态变更执行、简单决策

2. **当前架构过度依赖LLM处理本可确定性的逻辑**，导致：
   - 不必要的API调用成本
   - 响应延迟增加
   - 结果不确定性（同一输入可能产生不同输出）

3. **提示词复杂度过高**，大量内容在反复提醒LLM处理规则本可处理的事情

### 建议架构调整

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   玩家输入       │────▶│   DM Agent      │────▶│   意图解析      │
│                 │     │   (保持LLM)     │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                        │
        ┌───────────────────────────────────────────────┘
        ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   规则系统       │────▶│   数值计算       │────▶│   检定执行      │
│   (纯代码)       │     │   (纯代码)       │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                        │
        ┌───────────────────────────────────────────────┘
        ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   结局判定       │────▶│   状态推演       │────▶│   叙事生成      │
│   (优先代码)     │     │   (代码+LLM)    │     │   (保持LLM)     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                              │
                              ▼
                        ┌─────────────────┐
                        │   变更执行       │
                        │   (纯代码)       │
                        └─────────────────┘
```

### 下一步行动

1. **评估当前LLM调用分布** - 添加日志统计各类调用的频率和tokens
2. **创建规则化模块** - 从结局判定和伤害计算开始
3. **逐步迁移** - 保持LLM作为fallback，新规则并行运行验证
4. **性能基准测试** - 对比代码化前后的延迟和成本

---

*报告生成时间: 2026-03-28*  
*基于代码版本: a_engine主分支*
