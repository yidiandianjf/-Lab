# COC游戏引擎架构重构完整计划

> 版本: 1.4\
> 日期: 2026-03-22\
> 依据文档: `architecture_refactor_proposal.md`、`architecture_refactor_execution_plan.md`、`plan_new.md`

***

## 目录

1. [项目背景与目标](#1-项目背景与目标)
2. [现状分析](#2-现状分析)
   - [2.5 叙事系统设计决策](#25-叙事系统设计决策)
     - [2.5.8 上下文传递机制](#258-上下文传递机制关键)
3. [重构范围与内容](#3-重构范围与内容)
4. [详细实施步骤](#4-详细实施步骤)
5. [资源需求](#5-资源需求)
6. [风险识别与应对策略](#6-风险识别与应对策略)
7. [质量保障措施](#7-质量保障措施)
8. [验收标准](#8-验收标准)
9. [附录](#9-附录)

## 实施进展（2026-03-22）

### 已完成项

- Phase 1：优先级规则已按不变量实现（hp/san硬过滤 + DEX/hp_ratio/san_ratio + 稳定排序）
- Phase 2：NPCDirector已改为LLM主导并保留规则兜底，支持结构化输出解析
- Phase 3：NPC模块已迁移至`src/agent/npc/`，旧路径保留兼容转发
- Phase 4：运行时流程已统一为方案二主链路（玩家先执行，NPC后置同回合响应）
- Phase 5：回归测试已通过（`unittest discover tests`，46 passed）

### 本轮新增落地

- DM输出新增`actionable_npcs`并纳入系统提示词约束
- 新增世界配置开关：`npc_director_use_llm`、`narrative_merge_use_llm`
- `narrative_context`已传递到DMAgent、NPCDirector、NarrativeMerger链路

***

## 1. 项目背景与目标

### 1.1 项目背景

当前COC游戏引擎采用**7步回合制流程**，NPC行动存在两种模式：

- **queue模式**：玩家输入前强制处理NPC回合
- **reactive模式**：由DM Agent决定是否触发NPC响应

这种设计在长期迭代中积累了以下问题：

| 问题类型  | 具体表现                      | 影响程度 |
| ----- | ------------------------- | ---- |
| 架构分叉  | queue/reactive双轨并行，维护成本高  | P0   |
| 决策偏航  | NPCDirector当前是规则兜底，非LLM主导 | P0   |
| 优先级错误 | 使用归一化比值计算，影响回合排序正确性       | P0   |
| 模块分散  | NPC代码分散，prompt归属不清        | P1   |
| 叙事碎片化 | 各模块独立输出，缺乏全局叙事上下文         | P2   |

### 1.2 重构目标

#### 1.2.1 核心目标

1. **统一行动流程**：采用"方案二"，先执行玩家主流程，再在同一回合上下文内统一处理NPC响应
2. **LLM主导NPC决策**：让NPCDirector成为真正的LLM驱动决策器，规则仅作安全护栏
3. **修正优先级规则**：使用原始DEX值排序，hp/san作为硬过滤条件
4. **模块归属清晰**：NPC代码迁移到agent体系，prompt外置为markdown
5. 叙事系统模块也迁移到agent体系,prompt外置为markdown

#### 1.2.2 明确不做的事项

- 不做方案一（前置统一队列）的完整落地
- 不做GameEngine的一口气重写
- 不做NPC、Narrative、StateEvolution的大一统式重构
- 不立即删除所有旧字段和旧路径
- 不把兼容期和最终态混为一谈
- **不做LLM叙事上下文压缩**：叙事上下文（NarrativeContext）的历史事件压缩仅使用滚动窗口机制，不调用LLM
- **必须做LLM叙事合并**：StateEvolution生成的独立叙事片段必须通过LLM合并为完整连贯的全局叙事

### 1.3 关键决策锁定

以下决策在计划中**不可变**：

| 决策项              | 锁定内容                            | 禁止事项              |
| ---------------- | ------------------------------- | ----------------- |
| 行动流程             | 采用方案二                           | 禁止混搭方案一实现         |
| NPC决策            | LLM主导 + 规则兜底                    | 禁止规则充当主决策树        |
| 优先级              | 原始DEX降序 + hp/san硬过滤             | 禁止归一化比值排序         |
| 模块归属             | NPC迁移到agent体系                   | 禁止在旧路径扩展新功能       |
| Prompt           | 外置markdown                      | 禁止硬编码在Python中     |
| 叙事上下文压缩          | 滚动窗口 + 关键事实提取                   | 禁止使用LLM进行历史事件摘要压缩 |
| 叙事合并             | LLM合并独立叙事片段                     | 禁止直接拼接独立叙事而不合并    |
| Agent相关内容更改具有全局性 | 创建新的agent需要撰写提示词并且提供配套的输入输出代码   | 静止创建不写提示词,不创建配套设施 |
| 提示词需要有全局性        | 提示词需要涵盖这个角色在系统中的作用和系统信息,让其能更好决策 | 禁止使agent的系统提示词孤立  |

***

## 2. 现状分析

### 2.1 已完成模块评估

基于代码库调查，当前实现状态如下：

| 模块               | 状态  | 文件位置                                 | 完成度  | 问题              |
| ---------------- | --- | ------------------------------------ | ---- | --------------- |
| NPCDirector      | ✅存在 | `src/npc/npc_director.py`            | 60%  | 规则型回退规划器，非LLM主导 |
| NarrativeContext | ✅存在 | `src/narrative/narrative_context.py` | 90%  | 功能完整，需深化窗口压缩    |
| 优先级计算            | ✅存在 | `src/engine/game_engine.py`          | 40%  | 使用归一化比值，需修正     |
| queue模式          | ✅存在 | `src/engine/game_engine.py`          | 80%  | 需统一为语义标签        |
| reactive模式       | ✅存在 | `src/engine/game_engine.py`          | 80%  | 需统一为语义标签        |
| Prompt外置         | ✅存在 | `src/agent/prompt/*.md`              | 70%  | NPC专用prompt缺失   |
| NPC数据模型          | ✅存在 | `src/data/npc_planning_models.py`    | 100% | 结构完整            |

### 2.2 优先级计算现状问题

**当前实现**（`_calculate_actor_priority`）：

```python
score = (attributes.dex / 100) * 0.5 + (hp / max_hp) * 0.3 + (san / 100) * 0.2
```

**问题分析**：

- DEX被除以100，导致高DEX角色优势被稀释
- hp/san作为加权因子而非硬过滤，违反设计意图
- 不同分支可能使用不同公式，导致排序不一致

**正确实现**（plan\_new\.md要求）：

```
1. 先过滤不可行动角色（hp <= 0 或 san <= 0 不入队）
2. 对可行动角色，按原始DEX值降序排序
3. 再按hp_ratio降序排序
4. 再按san_ratio降序排序
5. 最后用稳定tiebreaker保证顺序确定性
```

### 2.3 NPCDirector现状问题

**当前实现**：

- 遍历NPC，检查存活状态
- 若`npc_response_needed`为真，设置TALK动作
- 否则默认WAIT动作

**问题分析**：

- 完全是规则逻辑，没有LLM调用
- 无法根据上下文做出智能决策
- 无法协调多NPC之间的行为
- 与原propsal提议完全矛盾:(应该使用DMagent提供的npc列表)

### 2.4 模块分布现状

```
当前结构:
src/
├── npc/                    # NPC代码（当前位置）
│   ├── __init__.py
│   └── npc_director.py
├── agent/
│   ├── dm_agent.py
│   ├── state_evolution.py
│   └── prompt/             # Prompt文件
│       ├── system_prompt.md
│       └── state_evolution_prompt.md
└── narrative/
    └── narrative_context.py

目标结构:
src/
├── agent/
│   ├── dm_agent.py
│   ├── state_evolution.py
│   ├── npc/                # NPC迁移目标位置
│   │   ├── __init__.py
│   │   ├── npc_director.py
│   │   └── prompt/         # NPC专用prompt
│   │       └── npc_director_prompt.md
│   └── prompt/
└── narrative/
```

### 2.5 叙事系统设计决策

#### 2.5.1 叙事系统的两个层次

叙事系统分为两个独立的层次，各自有不同的处理方式：

| 层次        | 功能                           | 是否使用LLM | 说明            |
| --------- | ---------------------------- | ------- | ------------- |
| **叙事生成**  | StateEvolution生成玩家/NPC行动结果叙事 | ✅ 是     | 每个行动者独立生成叙事片段 |
| **叙事合并**  | 将多个独立叙事合并为完整连贯的全局叙事          | ✅ 是     | 解决冲突、统一视角     |
| **上下文压缩** | 历史事件超出窗口时的压缩处理               | ❌ 否     | 使用滚动窗口机制，简单截断 |

#### 2.5.2 问题背景

**当前问题**：

- StateEvolution独立生成玩家叙事和NPC叙事
- 各叙事片段独立、不完整、可能冲突
- 直接拼接会导致叙事断裂和逻辑矛盾

**示例问题**：

```
玩家叙事: "你向守卫挥出一拳，击中了他的腹部"
NPC叙事: "守卫看到玩家攻击，侧身躲开了"

直接拼接 → 逻辑冲突（到底打中没？）
LLM合并 → "你向守卫挥出一拳，但守卫反应迅速侧身躲开，你的拳头只擦过他的护甲"
```

#### 2.5.3 叙事系统架构

```
回合结束
    ↓
收集所有叙事片段 [玩家叙事, NPC1叙事, NPC2叙事, ...]
    ↓
NarrativeMerger.merge() → LLM合并为全局叙事（需要prompt）
    ↓
全局叙事写入NarrativeContext.add_event()
    ↓
{NarrativeContext事件数 > window_size?}
    ↓ 是
滚动窗口压缩 → 最旧事件截断到summary_lines（无需LLM）
    ↓
NarrativeContext.get_context_for_llm() → 组装上下文字符串
    ↓
提供给下一轮所有LLM作为上下文提示词
    ↓
[DMAgent, StateEvolution, NPCDirector, NarrativeMerger...]
```

#### 2.5.4 需要新增的组件

**1. NarrativeMerger 叙事合并器**

```python
class NarrativeMerger:
    """将多个独立叙事片段合并为连贯的全局叙事"""
    
    def merge(
        self,
        fragments: List[NarrativeFragment],
        game_state: GameState,
        context: str = ""
    ) -> str:
        """
        合并叙事片段
        
        Args:
            fragments: 叙事片段列表，每个包含actor_id和narrative
            game_state: 当前游戏状态
            context: 额外上下文信息
            
        Returns:
            合并后的完整叙事文本
        """
        # 构建合并prompt
        prompt = self._build_merge_prompt(fragments, game_state, context)
        
        # 调用LLM进行合并
        response = self.llm_service.call_llm(prompt)
        
        return response
```

**2. 叙事合并Prompt模板**

```markdown
# Narrative Merger System Prompt

## 任务
将多个角色独立的行动叙事合并为一个连贯、完整的回合叙事。

## 输入信息
- 当前场景: {location_name}
- 回合数: {turn_count}
- 叙事片段:
{fragments_text}

## 合并原则
1. 保持时间线一致性：按行动顺序组织事件
2. 解决冲突：如果多个叙事描述同一事件有矛盾，选择最合理的解释
3. 统一视角：使用第三人称全知视角描述
4. 保持连贯：确保因果逻辑通顺
5. 保留细节：不要遗漏重要的状态变化或对话

## 输出格式
返回一段连贯的叙事文本，描述本回合发生的所有事件。
```

#### 2.5.5 当前实现状态

**StateEvolution（已有）**：

- `evolve_player_action()` → 生成玩家叙事
- `evolve_npc_action()` → 生成NPC叙事
- 两者都通过LLM生成独立的`narrative`字段

**NarrativeContext（已有）**：

- 存储事件历史
- 滚动窗口压缩（非LLM）
- 关键事实提取（正则匹配）

**NarrativeMerger（缺失）**：

- 需要新建
- 需要LLM调用
- 需要prompt文件

#### 2.5.6 叙事上下文处理流程（非LLM部分）

```
回合结束
    ↓
全局叙事写入NarrativeContext.add_event()
    ↓
{recent_events.length > window_size?}
    ↓ 是
_compress_oldest() → 截断最旧事件，追加到summary_lines（简单截断，非LLM）
    ↓
_extract_key_facts() → 正则提取关键事实
    ↓
get_context_for_llm() → 组装上下文字符串
    ↓
{输出超过max_context_chars?}
    ↓ 是
_truncate_context() → 从尾部截断
    ↓
供下一轮LLM使用
```

#### 2.5.7 配置参数

| 参数                  | 默认值  | 说明           |
| ------------------- | ---- | ------------ |
| `window_size`       | 5    | 保留详细记录的最近事件数 |
| `max_summary_lines` | 100  | 摘要行数上限       |
| `max_context_chars` | 4000 | 输出给LLM的字符数上限 |

这些参数可通过世界配置文件 `world.json` 的 `narrative_window` 字段调整。

#### 2.5.8 上下文传递机制（关键）

**核心原则**：合并后的全局叙事必须通过 `NarrativeContext.get_context_for_llm()` 提供给所有LLM模块作为上下文提示词。

**上下文传递流程**：

```
┌─────────────────────────────────────────────────────────────┐
│                     回合执行流程                              │
└─────────────────────────────────────────────────────────────┘

1. 玩家行动
   └─> StateEvolution.evolve_player_action() → 生成玩家叙事

2. NPC行动（如有）
   └─> StateEvolution.evolve_npc_action() → 生成NPC叙事

3. 叙事合并
   └─> NarrativeMerger.merge() → 生成全局叙事

4. 写入上下文
   └─> NarrativeContext.add_event(全局叙事)
       └─> 触发滚动窗口压缩（如需要）

5. 获取上下文
   └─> context = NarrativeContext.get_context_for_llm()
       └─> 格式: "Summary:\n...\n\nRecent events:\n...\n\nKey facts:\n..."

6. 传递给下一轮所有LLM
   ├─> DMAgent: 作为 "历史上下文" 注入prompt
   ├─> StateEvolution: 作为 "游戏上下文" 的一部分
   ├─> NPCDirector: 作为 "recent_events" 输入
   └─> NarrativeMerger: 作为合并时的背景信息
```

**Prompt注入示例**：

```markdown
# DMAgent System Prompt

## 历史上下文
{narrative_context}

## 当前任务
解析玩家输入...

---

# StateEvolution System Prompt

## 游戏上下文
{narrative_context}

## 当前任务
推演行动结果...
```

**代码实现要点**：

```python
# GameEngine中统一获取上下文
class GameEngine:
    def _get_narrative_context_for_llm(self) -> str:
        """获取用于LLM的叙事上下文"""
        if self.narrative_context:
            return self.narrative_context.get_context_for_llm()
        return ""
    
    def _build_dm_prompt(self, player_input: str) -> str:
        """构建DM Agent的prompt，注入叙事上下文"""
        narrative = self._get_narrative_context_for_llm()
        return f"""
## 历史上下文
{narrative}

## 玩家输入
{player_input}

## 当前任务
解析玩家意图...
"""
    
    def _build_state_evolution_input(self, ...) -> Dict:
        """构建StateEvolution输入，包含叙事上下文"""
        return {
            "game_state": self.game_state,
            "narrative_context": self._get_narrative_context_for_llm(),
            # ...其他字段
        }
```

**关键约束**：

1. 所有LLM调用必须包含 `narrative_context` 作为输入
2. 上下文格式统一由 `NarrativeContext.get_context_for_llm()` 生成
3. 上下文长度受 `max_context_chars` 限制，超长时从尾部截断
4. 关键事实（key\_facts）必须包含在上下文中，确保重要信息不丢失

***

## 3. 重构范围与内容

### 3.1 P0级重构（必须完成）

| 编号   | 重构项                   | 涉及文件                        | 工作量  |
| ---- | --------------------- | --------------------------- | ---- |
| P0-1 | 修正优先级计算公式             | `game_engine.py`            | 0.5天 |
| P0-2 | NPCDirector改为LLM主导    | `npc_director.py` + 新prompt | 2天   |
| P0-3 | 统一queue/reactive为语义标签 | `game_engine.py`            | 1天   |

### 3.2 P1级重构（重要完成）

| 编号   | 重构项             | 涉及文件         | 工作量  |
| ---- | --------------- | ------------ | ---- |
| P1-1 | NPC模块迁移到agent体系 | 目录重组 + 导入修复  | 1天   |
| P1-2 | NPC专用prompt外置   | 新建markdown文件 | 0.5天 |
| P1-3 | 兼容层明确优先级        | 多处字段处理       | 0.5天 |

### 3.3 P2级重构（优化完成）

| 编号   | 重构项                             | 涉及文件                                                 | 工作量  |
| ---- | ------------------------------- | ---------------------------------------------------- | ---- |
| P2-1 | **NarrativeMerger叙事合并器**（需要LLM） | 新建 `src/narrative/narrative_merger.py`               | 1.5天 |
| P2-2 | 叙事合并Prompt外置                    | 新建 `src/narrative/prompt/narrative_merger_prompt.md` | 0.5天 |
| P2-3 | NarrativeContext窗口压缩深化（非LLM）    | `narrative_context.py`                               | 0.5天 |
| P2-4 | 关键事实提取增强（正则优化）                  | `narrative_context.py`                               | 0.5天 |
| P2-5 | 世界配置叙事窗口支持                      | `world_loader.py`                                    | 0.5天 |

### 3.4 重构边界

**允许修改**：

- `src/engine/game_engine.py` - 优先级计算、流程统一
- `src/npc/npc_director.py` - LLM决策逻辑
- `src/narrative/narrative_context.py` - 压缩策略增强
- `src/data/init/world_loader.py` - 配置扩展
- 新增prompt文件

**禁止修改**：

- `DMAgentOutput`原有字段（保留兼容）
- `StateEvolutionOutput`原有字段（保留兼容）
- 旧世界配置格式（保持可读）
- 旧存档格式（保持可恢复）

***

## 4. 详细实施步骤

### Phase 0：规格收束与基线建立

**目的**：先把"怎么做"写死，再继续改代码。

**任务清单**：

| 任务                    | 交付物    | 负责人   |
| --------------------- | ------ | ----- |
| 0.1 固化方案二作为唯一落地路线     | 本计划文档  | 架构师   |
| 0.2 固化优先级公式           | 不变量清单  | 架构师   |
| 0.3 固化NPCDirector职责边界 | 接口规范   | 架构师   |
| 0.4 固化prompt外置规则      | 文件命名规范 | 架构师   |
| 0.5 建立回归测试基线          | 测试用例集  | 测试工程师 |

**交付物**：

- 本计划文档
- 不变量清单（见附录A）
- 回归测试基线

**验收标准**：

- 后续实现者不会对"方案一还是方案二""是否必须LLM""优先级怎么算"产生歧义

***

### Phase 1：修正队列与行动可行性

**目的**：先修正会直接影响回合排序和行动资格的逻辑。

**任务清单**：

| 任务            | 描述                  | 预计时间 |
| ------------- | ------------------- | ---- |
| 1.1 重写优先级计算   | 使用原始DEX + hp/san硬过滤 | 2小时  |
| 1.2 增加排序确定性测试 | 验证同分条件下顺序稳定         | 1小时  |
| 1.3 增加过滤回归测试  | 验证hp<=0/san<=0不入队   | 1小时  |
| 1.4 验证现有世界运行  | 确保不破坏已有功能           | 1小时  |

**优先级公式实现规范**：

```python
def _calculate_actor_priority(self, actor: Character) -> Tuple[bool, Tuple]:
    """
    返回: (是否可行动, 排序键元组)
    排序键: (-dex, -hp_ratio, -san_ratio, char_id)
    """
    if actor.status.hp <= 0 or actor.status.san <= 0:
        return (False, ())
    
    hp_ratio = actor.status.hp / actor.status.max_hp
    san_ratio = actor.status.san / 100
    
    return (True, (-actor.attributes.dex, -hp_ratio, -san_ratio, actor.id))
```

**验收标准**：

- 排序结果可解释、可预测、可测试
- 不会再出现把低属性角色错误排到前面的情况
- 现有世界可正常运行

***

### Phase 2：NPCDirector LLM主导化

**目的**：让NPC决策从引擎内部规则树中脱离出来，成为真正的LLM驱动决策器。

**任务清单**：

| 任务                | 描述                      | 预计时间 |
| ----------------- | ----------------------- | ---- |
| 2.1 设计NPC专用prompt | 仿照state\_evolution.md格式 | 2小时  |
| 2.2 实现LLM调用逻辑     | 集成到NPCDirector          | 3小时  |
| 2.3 设计结构化输出schema | NPCActionDecision格式     | 1小时  |
| 2.4 实现安全兜底逻辑      | LLM失败时的规则回退             | 2小时  |
| 2.5 编写集成测试        | 验证LLM输出正确解析             | 2小时  |

**NPCDirector输入上下文规范**：

```python
@dataclass
class NPCDirectorContext:
    """NPC导演决策所需上下文"""
    game_state: GameState              # 当前游戏状态(与DMagent一致)
    player_intent: DMAgentOutput       # 玩家意图解析结果
    recent_events: List[NarrativeEvent] # 最近事件（来自NarrativeContext）
    npc_ids: List[charactorSturct]                 # 需决策的NPC的信息的列表
    trigger_source: str                # queue/reactive
    world_context: str                 # 世界背景信息
```

**NPCDirector Prompt模板要点**：

```markdown
# NPC Director System Prompt

## 角色定位
你是游戏世界的NPC导演，负责协调所有NPC的行为决策。

## 输入信息
- 当前游戏状态：{game_state}
- 玩家意图：{player_intent}
- 最近事件：{recent_events}
- 需决策NPC：{npc_ids}

## 输出格式
请输出JSON格式的决策结果：
{
  "decisions": {
    "npc_id_1": {
      "action_type": "talk|attack|move|use_item|investigate|wait|custom",
      "target_id": "目标ID（可选）",
      "intent_description": "NPC想做什么",
      "check_needed": true/false,
      "check_attributes": ["str", "dex", ...],
      "difficulty": "regular|hard|extreme"
    }
  }
}

## 决策原则
1. 根据NPC性格和当前情境做出合理决策
2. 协调多NPC避免行为冲突
3. 保持与世界观的一致性
```

**验收标准**：

- NPC行为通过结构化结果进入后续链路
- 不再依赖if/else决定NPC主意图
- LLM失败时有安全兜底

***

### Phase 3：模块迁移与Prompt外置

**目的**：让代码边界和提示词边界对齐。

**任务清单**：

| 任务                     | 描述                       | 预计时间  |
| ---------------------- | ------------------------ | ----- |
| 3.1 创建src/agent/npc/目录 | 新模块位置                    | 0.5小时 |
| 3.2 迁移npc\_director.py | 移动并更新导入                  | 1小时   |
| 3.3 创建NPC prompt文件     | npc\_director\_prompt.md | 1小时   |
| 3.4 更新所有导入路径           | 修复引用                     | 1小时   |
| 3.5 保留旧路径转发            | 兼容层                      | 0.5小时 |
| 3.6 更新测试导入             | 测试修复                     | 0.5小时 |

**迁移步骤**：

```
Step 1: 创建目录结构
src/agent/npc/
├── __init__.py
├── npc_director.py
└── prompt/
    └── npc_director_prompt.md

Step 2: 移动文件
cp src/npc/npc_director.py src/agent/npc/
cp src/npc/__init__.py src/agent/npc/

Step 3: 创建prompt文件
创建 src/agent/npc/prompt/npc_director_prompt.md

Step 4: 更新导入
修改所有 from src.npc import 为 from src.agent.npc import

Step 5: 保留兼容层
src/npc/__init__.py:
  from src.agent.npc import *  # 转发导入
```

**验收标准**：

- prompt可单独审阅
- NPC逻辑不再散落在多个目录
- 旧导入路径仍可用（兼容）

***

### Phase 4：统一Runtime流程

**目的**：把方案二落成稳定可运行的主链路。

**任务清单**：

| 任务                        | 描述                  | 预计时间 |
| ------------------------- | ------------------- | ---- |
| 4.1 统一NPC响应入口             | 合并queue/reactive调用点 | 2小时  |
| 4.2 让queue/reactive成为语义标签 | 仅标记来源，不分支逻辑         | 2小时  |
| 4.3 验证玩家主流程优先             | 确保玩家行动先执行           | 1小时  |
| 4.4 验证NPC响应时序             | 确保在同一回合上下文          | 1小时  |
| 4.5 清理冗余分支                | 删除重复逻辑              | 1小时  |

**统一流程图**：

```
玩家输入
    ↓
DMAgent解析 → 输出 {player_intent, npc_response_needed, npc_actor_id}
    ↓
RuleSystem执行检定（如需要）
    ↓
StateEvolution.evolve_player_action()
    ↓
应用玩家状态变更 + 输出叙事片段
    ↓
{npc_response_needed?}
    ↓ 是
NPCDirector.decide_actions() → 结构化NPC计划
    ↓
StateEvolution.evolve_npc_action()
    ↓
应用NPC状态变更 + 输出叙事片段
    ↓
NarrativeContext.add_event() → 更新叙事上下文
    ↓
回合结束
```

**验收标准**：

- 主流程可稳定跑通
- NPC响应时序清晰
- 不再出现两套行为逻辑互相抢控制权

***

### Phase 5：回归与收口

**目的**：确认迁移没有破坏现有世界与存档。

**任务清单**：

| 任务            | 描述                   | 预计时间 |
| ------------- | -------------------- | ---- |
| 5.1 补齐优先级回归测试 | 验证排序正确性              | 1小时  |
| 5.2 补齐NPC决策测试 | 验证LLM输出解析            | 1小时  |
| 5.3 验证旧世界配置加载 | mysterious\_library等 | 1小时  |
| 5.4 验证旧存档恢复   | 现有存档文件               | 1小时  |
| 5.5 验证新结构化路径  | 核心场景覆盖               | 2小时  |
| 5.6 编写迁移文档    | 供后续维护参考              | 1小时  |

**测试清单**：

| 测试类型        | 测试项                | 文件                      |
| ----------- | ------------------ | ----------------------- |
| 优先级         | 原始DEX排序优先于比例值      | `test_priority.py`      |
| 优先级         | hp<=0和san<=0直接跳过   | `test_priority.py`      |
| 优先级         | 排序在同分条件下稳定         | `test_priority.py`      |
| NPCDirector | 输出是结构化计划而非纯文本      | `test_npc_director.py`  |
| NPCDirector | LLM失败时有安全兜底        | `test_npc_director.py`  |
| NPCDirector | 不走规则树主决策           | `test_npc_director.py`  |
| 流程          | 玩家主流程先执行           | `test_flow.py`          |
| 流程          | NPC响应在同一回合上下文内发生   | `test_flow.py`          |
| 流程          | 状态变更不破坏后续流程        | `test_flow.py`          |
| 兼容          | 旧世界配置可读            | `test_compatibility.py` |
| 兼容          | 旧存档可恢复             | `test_compatibility.py` |
| 兼容          | 旧字段仍能兜底            | `test_compatibility.py` |
| Prompt      | prompt从markdown加载  | `test_prompt.py`        |
| Prompt      | prompt缺失时明确失败      | `test_prompt.py`        |
| Prompt      | prompt不硬编码在Python中 | `test_prompt.py`        |

**验收标准**：

- 旧配置可运行
- 新逻辑可验证
- 迁移期兼容层可继续存在，但不影响主流程

***

## 5. 资源需求

### 5.1 人力资源

| 角色    | 人数 | 投入时间 | 主要职责           |
| ----- | -- | ---- | -------------- |
| 架构师   | 1  | 全程   | 方案设计、技术决策、代码审查 |
| 后端开发  | 2  | 8天   | 核心模块开发、测试编写    |
| 测试工程师 | 1  | 3天   | 回归测试、验收测试      |
| 文档工程师 | 1  | 1天   | 文档更新、迁移指南      |

### 5.2 时间估算

| 阶段      | 预计时间   | 关键路径             |
| ------- | ------ | ---------------- |
| Phase 0 | 1天     | 规格固化             |
| Phase 1 | 0.5天   | 优先级修正            |
| Phase 2 | 2天     | NPCDirector LLM化 |
| Phase 3 | 1天     | 模块迁移             |
| Phase 4 | 1天     | 流程统一             |
| Phase 5 | 1.5天   | 回归收口             |
| **总计**  | **7天** | <br />           |

### 5.3 技术依赖

| 依赖项      | 用途      | 当前状态 |
| -------- | ------- | ---- |
| LLM API  | NPC决策调用 | 已配置  |
| Pydantic | 数据模型    | 已使用  |
| unittest | 测试框架    | 已使用  |

***

## 6. 风险识别与应对策略

### 6.1 高风险项

| 风险         | 可能性 | 影响 | 应对策略                |
| ---------- | --- | -- | ------------------- |
| LLM导演输出不稳定 | 中   | 高  | 保留结构化schema校验与兜底动作  |
| 队列语义再度分叉   | 中   | 高  | 将方案二写入正式规范，禁止继续开新分支 |
| 提示词再次硬编码   | 中   | 高  | prompt文件化，代码只负责加载   |
| 旧存档加载失败    | 低   | 高  | 新旧字段并存，先保证读取兼容      |

### 6.2 中风险项

| 风险        | 可能性 | 影响 | 应对策略                                         |
| --------- | --- | -- | -------------------------------------------- |
| 兼容层过长     | 中   | 中  | 只保留迁移期必要转发，不扩展新功能                            |
| 叙事压缩丢关键信息 | 中   | 中  | 关键事实单独保存，压缩前后做对照                             |
| NPC行为变得刻板 | 中   | 中  | 保留intent\_description字段，让StateEvolution保持创造力 |

### 6.3 低风险项

| 风险       | 可能性 | 影响 | 应对策略          |
| -------- | --- | -- | ------------- |
| 单次请求延迟增加 | 高   | 低  | 多NPC并行决策，串行执行 |
| 回归测试不足   | 低   | 中  | 先补测试基线，再做模块替换 |

***

## 7. 质量保障措施

### 7.1 代码质量

| 措施   | 工具/方法       | 频率   |
| ---- | ----------- | ---- |
| 语法检查 | py\_compile | 每次提交 |
| 类型检查 | mypy（可选）    | 每次提交 |
| 代码审查 | PR Review   | 每次合并 |
| 静态分析 | IDE内置       | 实时   |

### 7.2 测试覆盖

| 测试类型  | 覆盖目标 | 工具       |
| ----- | ---- | -------- |
| 单元测试  | 核心函数 | unittest |
| 集成测试  | 模块交互 | unittest |
| 回归测试  | 已有功能 | unittest |
| 端到端测试 | 完整流程 | 手动 + 自动  |

### 7.3 文档保障

| 文档类型 | 内容        | 更新时机       |
| ---- | --------- | ---------- |
| 计划文档 | 本文档       | 阶段变更时      |
| 接口文档 | 函数签名、参数说明 | 接口变更时      |
| 迁移指南 | 兼容性说明     | Phase 3完成后 |
| 故障排查 | 常见问题与解决   | Phase 5完成后 |

### 7.4 变更控制

| 控制项  | 审批人   | 记录方式       |
| ---- | ----- | ---------- |
| 计划变更 | 架构师   | 文档版本更新     |
| 接口变更 | 架构师   | 接口文档更新     |
| 代码变更 | 开发负责人 | Git commit |
| 测试变更 | 测试工程师 | 测试用例更新     |

***

## 8. 验收标准

### 8.1 功能验收

| 验收项      | 验收标准                | 验证方法 |
| -------- | ------------------- | ---- |
| 优先级计算    | 使用原始DEX排序，hp/san硬过滤 | 单元测试 |
| NPC决策    | LLM主导，规则兜底          | 集成测试 |
| 流程统一     | queue/reactive为语义标签 | 流程测试 |
| 模块迁移     | NPC代码在agent体系下      | 代码审查 |
| Prompt外置 | 所有prompt为markdown文件 | 文件检查 |

### 8.2 兼容性验收

| 验收项   | 验收标准      | 验证方法 |
| ----- | --------- | ---- |
| 旧世界配置 | 可正常加载运行   | 回归测试 |
| 旧存档   | 可正常恢复     | 回归测试 |
| 旧字段   | 可正常兜底     | 兼容测试 |
| 旧导入路径 | 可正常使用（转发） | 导入测试 |

### 8.3 质量验收

| 验收项   | 验收标准       | 验证方法  |
| ----- | ---------- | ----- |
| 测试通过率 | 100%       | 测试报告  |
| 代码覆盖率 | ≥80%（核心模块） | 覆盖率报告 |
| 文档完整性 | 所有接口有文档    | 文档审查  |
| 无P0缺陷 | 0个P0级缺陷    | 缺陷报告  |

### 8.4 阶段验收清单

| 阶段      | 验收项                 | 状态 |
| ------- | ------------------- | -- |
| Phase 0 | 规格文档完成              | ☑  |
| Phase 0 | 回归基线建立              | ☑  |
| Phase 1 | 优先级测试通过             | ☑  |
| Phase 1 | 现有世界运行正常            | ☑  |
| Phase 2 | NPCDirector LLM调用成功 | ☑  |
| Phase 2 | 结构化输出解析正确           | ☑  |
| Phase 2 | 兜底逻辑可用              | ☑  |
| Phase 3 | 模块迁移完成              | ☑  |
| Phase 3 | Prompt文件创建          | ☑  |
| Phase 3 | 导入路径更新              | ☑  |
| Phase 4 | 主流程跑通               | ☑  |
| Phase 4 | NPC响应时序正确           | ☑  |
| Phase 5 | 回归测试全部通过            | ☑  |
| Phase 5 | 文档更新完成              | ☑  |

***

## 9. 附录

### 附录A：不变量清单

以下不变量在重构过程中必须保持：

```markdown
## 优先级不变量
1. hp <= 0 的角色不入队
2. san <= 0 的角色不入队
3. 可行动角色按原始DEX降序排序
4. DEX相同时按hp_ratio降序排序
5. hp_ratio相同时按san_ratio降序排序
6. 全部相同时按char_id稳定排序

## NPC决策不变量
1. NPCDirector输出必须是结构化NPCActionDecision
2. LLM调用失败时必须有规则兜底
3. 规则逻辑只能作为安全护栏，不能作为主决策

## 流程不变量
1. 玩家主流程必须先执行
2. NPC响应必须在同一回合上下文内发生
3. queue/reactive只能作为触发来源标签

## 兼容性不变量
1. DMAgentOutput原有字段必须保留
2. 旧世界配置必须可读
3. 旧存档必须可恢复
4. 旧导入路径必须可用（转发）

## Prompt不变量
1. 所有prompt必须是markdown文件
2. prompt加载失败必须明确报错
3. 禁止在Python中硬编码prompt内容

## 叙事系统不变量
1. **叙事合并必须使用LLM**：StateEvolution生成的独立叙事片段必须通过LLM合并为完整连贯的全局叙事
2. **上下文压缩禁止LLM**：NarrativeContext的历史事件压缩仅使用滚动窗口机制，不调用LLM
3. **上下文必须传递给所有LLM**：合并后的全局叙事必须通过 `NarrativeContext.get_context_for_llm()` 提供给DMAgent、StateEvolution、NPCDirector等所有LLM模块
4. 叙事上下文必须使用滚动窗口机制
5. 关键事实提取必须使用正则匹配，不调用LLM
6. 上下文输出长度必须受max_context_chars限制
```

### 附录B：文件变更清单

| 操作     | 文件路径                                              | 说明                           |
| ------ | ------------------------------------------------- | ---------------------------- |
| 修改     | `src/engine/game_engine.py`                       | 优先级计算、流程统一、集成NarrativeMerger |
| 修改     | `src/npc/npc_director.py`                         | LLM决策逻辑                      |
| 新建     | `src/agent/npc/__init__.py`                       | 新模块初始化                       |
| 新建     | `src/agent/npc/npc_director.py`                   | 迁移后的NPCDirector              |
| 新建     | `src/agent/npc/prompt/npc_director_prompt.md`     | NPC导演prompt                  |
| 修改     | `src/npc/__init__.py`                             | 改为转发导入                       |
| 修改     | `src/narrative/narrative_context.py`              | 压缩策略增强                       |
| **新建** | `src/narrative/narrative_merger.py`               | **叙事合并器（LLM）**               |
| **新建** | `src/narrative/prompt/narrative_merger_prompt.md` | **叙事合并prompt**               |
| 新建     | `tests/test_priority.py`                          | 优先级测试                        |
| 新建     | `tests/test_flow.py`                              | 流程测试                         |
| 新建     | `tests/test_compatibility.py`                     | 兼容性测试                        |
| 新建     | `tests/test_prompt.py`                            | Prompt测试                     |
| **新建** | `tests/test_narrative_merger.py`                  | **叙事合并器测试**                  |

### 附录C：术语表

| 术语                  | 定义                              |
| ------------------- | ------------------------------- |
| 方案一                 | 前置统一队列：先构建完整NPC行动队列再执行玩家回合      |
| 方案二                 | 后置响应模式：先执行玩家主流程，再处理NPC响应        |
| queue模式             | 玩家输入前强制处理NPC回合的旧模式              |
| reactive模式          | 由DM Agent决定是否触发NPC响应的旧模式        |
| NPCDirector         | NPC导演，负责统一决策所有NPC行为             |
| NarrativeContext    | 叙事上下文，管理全局叙事历史                  |
| NPCActionForm       | NPC行动表单，结构化决策输出                 |
| NPCActionDecision   | 批量NPC决策结果容器                     |
| 滚动窗口                | 叙事上下文的压缩机制，保留最近N个事件的详细信息        |
| 关键事实                | 从叙事文本中提取的重要信息，永不删除              |
| **NarrativeMerger** | **叙事合并器，使用LLM将多个独立叙事合并为连贯全局叙事** |

### 附录D：参考文档

- [architecture\_refactor\_proposal.md](./architecture_refactor_proposal.md) - 原始重构提案
- [architecture\_refactor\_execution\_plan.md](./architecture_refactor_execution_plan.md) - 执行计划
- [plan\_new.md](./plan_new.md) - 新版计划（留档）
- [AGENTS.md](../../AGENTS.md) - 项目开发指南

***

> 文档版本: 1.4\
> 最后更新: 2026-03-22\
> 更新内容: 同步阶段验收状态为已完成；补充本轮落地项（actionable_npcs、LLM开关、narrative_context全链路传递）\
> 维护者: 项目架构组

