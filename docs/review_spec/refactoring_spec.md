# AEngine 修补-重构规范文档

**版本:** 1.0  
**日期:** 2026-03-28  
**目标:** 以50回合叙事稳定性为核心，重构信息链路与协议边界

---

## 1. 文档概述

### 1.0 规范约束

本规范不是概念性愿景，而是**可分阶段落地的重构执行约束**。后续所有设计、字段迁移、Prompt改写，都必须同时满足以下约束：

1. **先稳态后迁移**：先修补会破坏事务、持久化、状态一致性的基础问题，再进入主协议重构。
2. **先协议后Prompt**：Prompt 只能表达既定协议，不能反过来承担补丁职责。
3. **先适配后替换**：旧链路必须通过适配器过渡，不能一轮重构中同时拆掉所有旧入口。
4. **事实归代码，表达归LLM**：实体合法性、激活集合、难度枚举、状态写入路径、持久化边界由代码决定；LLM负责意图解释、动作语义表达、局部叙事生成、记忆压缩建议。
5. **链路对象必须可持久化、可回放、可验证**：任何新引入的核心对象，如果既不能存档恢复，也不能进入测试断言，就不算合格协议。

### 1.1 理论依据

本规范基于**信息链路九要素模型**：

| 要素 | 代号 | 说明 | 当前状态 |
|------|------|------|----------|
| 世界事实 | E1 | 结构化真值 (`GameState`) | ✅ 已具备 |
| 输入信号 | E2 | 原始输入 (`raw_input_text`) | ⚠️ 部分混乱 |
| 意图解释 | E3 | 系统理解 (`TurnIntent`) | ⚠️ 与E2混淆 |
| 规则结算 | E4 | 检定事实 (`CheckResult`) | ✅ 已具备 |
| 步骤结算 | E5 | 步骤结果 (`TurnResolution`) | ⚠️ 分散表达 |
| 回合因果链 | E6 | 临时链路 (`TurnTrace`) | ❌ **关键缺失** |
| 叙事投影 | E7 | 展示文本 (`merged_narrative`) | ✅ 已具备 |
| 长期记忆 | E8 | 记忆提交（`DialogueMemory` + `NarrativeMemory`） | ⚠️ 未进推理链 |
| 持久化投影 | E9 | 存档恢复 | ⚠️ 部分实现 |

### 1.2 核心问题诊断

```
当前系统能做的事：
  ✓ 单回合基本运行
  ✓ 玩家阶段事实不易被改写

当前系统不能做的事：
  ✗ 多NPC同回合稳定共享信息
  ✗ 10次以上对话稳定延续
  ✗ 50回合级别的高一致性叙事
```

根本原因：**缺少E6回合因果链**，导致同回合多NPC之间无法共享即时链路结果。

---

## 2. 前置修补项（重构前必须完成）

> ⚠️ **这些修补必须在重构主链路前完成，否则重构后的系统仍将建立在不稳定基础之上。**

### 2.1 高优先级修补（P0 - 阻塞重构）

#### 2.1.1 修复事务原子性破坏（发现2）

**问题：** `\move` 命令在事务快照前直接修改内存
- `InputSystem._cmd_move()` 直接执行 `game_state.current_scene_id = target_map.id`
- 如果后续 `_apply_changes()` 失败，会出现"场景显示"与"玩家位置"不一致

**修补方案：**
```python
# 删除命令阶段对 current_scene_id 的直接写入
# 仅允许通过统一状态变更链路和 _sync_state_change() 更新场景ID
```

**涉及文件：**
- [`src/agent/input_system.py`](src/agent/input_system.py:557)
- [`src/engine/game_engine.py`](src/engine/game_engine.py:838-848)

---

#### 2.1.2 修复回滚链路"假成功"（发现3）

**问题：** `save_game_state()` 内部逐个保存实体时不检查返回码
- 回滚过程可能出现"内存已恢复，持久层部分失败，但系统误判成功"

**修补方案：**
```python
# save_game_state() 必须检查每次 save_* 的返回值
# 任一实体保存失败时立即返回错误，并记录失败点
```

**涉及文件：**
- [`src/engine/game_engine.py`](src/engine/game_engine.py:881-887)
- [`src/data/io_system.py`](src/data/io_system.py:835-868)

---

#### 2.1.3 修复新开世界污染问题（发现4）

**问题：** `new_game()` 只重置内存中的 `GameState`，旧世界实体残留会参与 inventory/location 同步

**修补方案：**
```python
# 在 new_game() / 世界导入前增加"清空当前运行库"步骤
# 或引入隔离命名空间，避免旧实体参与新世界关系同步
```

**涉及文件：**
- [`src/engine/game_engine.py`](src/engine/game_engine.py:137)
- [`src/data/init/world_loader.py`](src/data/init/world_loader.py:336-352)

---

#### 2.1.4 限制 DELETE 操作范围（发现5）

**问题：** `DELETE` 语义过宽，可能直接删除模型字段而非列表元素

**修补方案：**
```python
# 限制 DELETE 仅用于白名单列表字段
# 对标量字段统一改为 update -> null/空字符串/默认值，禁止 delattr
```

**涉及文件：**
- [`src/data/io_system.py`](src/data/io_system.py:807-824)
- [`src/agent/state_evolution.py`](src/agent/state_evolution.py:876)

---

### 2.2 中优先级修补（P1 - 重构期间并行）

#### 2.2.1 清理提示词漂移（发现6）

**问题清单：**
- [ ] DM Prompt JSON 示例混入 `---` 和修改建议文本
- [ ] State Evolution Prompt 保留 `Move` 草案备注
- [ ] NPC推演提到 `npc_action` 字段但模型中不存在
- [ ] 提示词仍要求"同时更新 inventory"但IO层已自动处理双向关系

**修补方案：**
- 删除所有 `#修改建议`、占位分隔符、过时字段说明
- 重新声明：哪些关系由代码自动维护，哪些字段允许LLM显式输出

**涉及文件：**
- [`src/agent/prompt/system_prompt.md`](src/agent/prompt/system_prompt.md:89-96)
- [`src/agent/prompt/state_evolution_prompt.md`](src/agent/prompt/state_evolution_prompt.md:71)

---

#### 2.2.2 收敛 queue/unified 模式残留（发现7）

**问题：** `unified` 与 `queue` 行为几乎相同，只是 trigger_source 标记不同。

**修正原则：**
- **不要在前置修补阶段直接删除模式字段和配置项**
- 先完成新协议落地与适配器建设，再把 `npc_response_mode` 降级为兼容字段
- 最终只保留真正有语义差异的模式，或彻底收敛为单一路径

**原因：**
- 当前运行链路仍直接依赖 `npc_response_mode`
- 在重构前删除会破坏“先稳住现状，再迁移协议”的阶段原则
- 模式清理属于**协议收敛阶段**，不属于**基础稳定性修补阶段**

**后续清理清单（不在前置修补阶段执行）：**
1. `src/engine/game_engine.py:106` - `_npc_response_mode` 字段
2. `src/engine/game_engine.py:1353-1366` - `_describe_npc_mode_policy()`
3. `src/engine/game_engine.py:1715` - 模式判断逻辑
4. `src/data/models.py:262-266` - `NpcResponseMode` 枚举
5. `src/data/init/world_loader.py:391-395` - 模式解析
6. `config/world/*/world.json` - npc_response_mode 配置
7. 相关提示词中的模式说明

**当前阶段仅要求：**
- 不再新增新的模式分支
- 在文档中明确：`queue/unified` 属于待收敛兼容语义

**保留：**
- `_action_queue` 内部队列（用于NPC排序）
- `npc_response_mode` 配置项（迁移期兼容）

---

#### 2.2.3 评估并准备 move 操作支持

**当前问题：** LLM需要生成两个变更来完成物品移动
```python
# 当前
{"id": "item-key-01", "field": "location", "operation": "update", "value": "char-player-01"}
{"id": "char-player-01", "field": "inventory", "operation": "add", "value": "item-key-01"}

# 目标方向
{"operation": "move", "entity_id": "item-key-01", "from": "map-room-01", "to": "char-player-01"}
```

**修正原则：**
- `move` 操作是合理方向，但不应在前置修补阶段和主协议重构并行硬塞进现有链路
- 应在 `TurnResolution` / `StateChange` 协议收敛后，再决定是：
  - 扩展 `ChangeOperation`
  - 还是引入单独的高阶变更对象

**当前阶段要求：**
- 完成设计评估
- 不强制作为 P0 阻塞项

---

### 2.3 前置修补验收标准

| 检查项 | 验证方法 |
|--------|----------|
| 事务原子性 | 在 `_apply_changes()` 中人为抛出异常，验证状态一致性 |
| 回滚可靠性 | 模拟保存失败，验证错误被正确传播 |
| 世界隔离性 | 连续切换两个不同世界，验证无实体残留 |
| DELETE限制 | 尝试对标量字段执行del，验证被拦截 |
| 模式兼容收敛 | 全局搜索 `npc_response_mode`，确认未新增新的分支语义，并已在文档中标记为迁移期兼容字段 |

---

## 3. 重构阶段（前置修补完成后启动）

### 3.1 阶段划分原则

- **每阶段可单独合并**：不允许一次性大规模改动
- **旧协议通过适配器过渡**：不能同时改写所有模块
- **Prompt跟随协议改动**：不允许只靠"补prompt"掩盖链路问题

---

### 3.2 Phase 1：定义新协议与核心数据结构

**目标：** 先把新协议建出来，不直接改业务逻辑

**新增模型：**

```python
# src/data/models.py

class TurnIntent(BaseModel):
    """E3: 意图解释"""
    actor_id: str
    raw_input_text: str          # E2: 原始输入
    intent_text: str             # 系统解释
    interaction_type: Literal["action", "dialogue", "mixed"]
    check_plan: Optional[CheckPlan]
    activation_hint: ActivationHint

class CheckPlan(BaseModel):
    """E4: 检定计划"""
    check_needed: bool
    check_type: Optional[str]
    attributes: Optional[List[str]]
    target_id: Optional[str]
    difficulty: Optional[str]

class TurnResolution(BaseModel):
    """E5: 步骤结算"""
    actor_id: str
    phase: Literal["player", "npc"]
    intent_text: str
    check_result: Optional[CheckOutput]   # 如后续统一命名，也可收敛为 CheckResult
    state_changes: List[StateChange]
    local_narrative: str
    outcome: OutcomeSummary

class TurnStep(BaseModel):
    """E6: 回合步骤"""
    step_id: str
    turn_id: int
    actor_id: str
    phase: Literal["player", "npc"]
    trigger_source: str
    intent: TurnIntent
    resolution: TurnResolution
    timestamp: datetime

class TurnTrace(BaseModel):
    """E6: 回合因果链（关键缺失要素）"""
    turn_id: int
    steps: List[TurnStep]
    
    def append_step(self, step: TurnStep) -> None:
        """NPC执行后立即追加，供后续NPC读取"""
        self.steps.append(step)
    
    def get_steps_for_actor(self, actor_id: str) -> List[TurnStep]:
        """获取特定角色的步骤历史"""
        return [s for s in self.steps if s.actor_id == actor_id]

class ActivationHint(BaseModel):
    """NPC激活建议（原npc_response_needed等字段）"""
    response_needed_hint: bool
    preferred_actor_id: Optional[str]
    npc_intent_hint: Optional[str]
    candidate_npc_ids_hint: Optional[List[str]]

class OutcomeSummary(BaseModel):
    """步骤结果摘要：供后续链路与叙事层消费的结构化结算概括"""
    action_succeeded: bool
    outcome_type: str
    consequence_tags: List[str] = Field(default_factory=list)
```

**字段处理：**

| 当前字段 | 目标对象 | 动作 |
|----------|----------|------|
| `action_description` | `raw_input_text` + `intent_text` | 拆分 |
| `player_check_result` + `player_resolution_anchor` | `TurnResolution` | 合并 |
| 分散的 `check_*` | `CheckPlan` | 合并 |
| `npc_response_needed` | `ActivationHint.response_needed_hint` | 重命名 |

**关键文件：**
- [`src/data/models.py`](src/data/models.py)
- [`src/data/npc_planning_models.py`](src/data/npc_planning_models.py)

---

### 3.3 Phase 2：拆分上下文构建器

**目标：** 把分散在 `GameEngine` 里的上下文拼贴逻辑抽离

**新增构建器：**

```python
# src/engine/context_builders.py 或 src/context/

class WorldStateViewBuilder:
    """构建受控世界视图（E1）"""
    def build(self, game_state: GameState, actor_id: str) -> WorldStateView:
        return WorldStateView(
            current_map=self._get_current_map(game_state, actor_id),
            nearby_characters=self._get_nearby_chars(game_state, actor_id),
            nearby_items=self._get_nearby_items(game_state, actor_id),
            player_state=self._get_player_state(game_state),
            available_exits=self._get_exits(game_state, actor_id)
        )

class DialogueMemoryBuilder:
    """构建对话记忆视图（E8）"""
    def build(self, dialogue_log: List[DialogueEntry]) -> DialogueMemoryView:
        # 结构化对话历史，而非简单字符串拼接
        pass

class TurnTraceContextBuilder:
    """构建回合因果链视图（E6）"""
    def build_for_npc(self, turn_trace: TurnTrace, npc_id: str) -> TurnTraceView:
        # NPC看到的是：玩家步骤 + 已执行的前序NPC步骤
        pass
```

**删除字段：** `engine_context` 这种泛用大包字段

---

### 3.4 Phase 3：重构 DM 层

**目标：** 收缩 DM 职责，不再让它成为链路事实生产者

**DM 新输出协议：**

```python
class DMAgentOutputV2(BaseModel):
    turn_intent: TurnIntent           # E3: 意图解释
    response_to_player: Optional[str] # E7: 直接回复（纯对话早返回）
    # 不再输出整包下游NPC决策字段；只保留 ActivationHint
```

**变更要点：**
1. `candidate_npc_ids` 由代码决定，DM 只提供 `ActivationHint`
2. `npc_response_needed` 转为可选建议，不作为唯一事实开关
3. 对话历史改为结构化 `DialogueMemory`

**涉及文件：**
- [`src/agent/dm_agent.py`](src/agent/dm_agent.py)
- [`src/agent/prompt/system_prompt.md`](src/agent/prompt/system_prompt.md)

---

### 3.5 Phase 4：重构玩家阶段执行链

**目标：** 让玩家阶段产出标准化的 `TurnStep`

**新流程：**

```
raw_input_text 
    → TurnIntent 
    → CheckPlan 
    → CheckResult 
    → TurnResolution 
    → TurnStep 
    → 写入 TurnTrace
```

**StateEvolution 新输入：**

```python
class StateEvolutionInputV2(BaseModel):
    world_state_view: WorldStateView        # E1
    dialogue_memory: DialogueMemoryView     # E8
    narrative_memory: NarrativeMemoryView   # E8
    turn_trace_so_far: TurnTraceView        # E6（关键新增）
    turn_intent: TurnIntent                 # E3
    # 删除：混杂的 game_context, is_npc_action 等字段
```

**StateEvolution 新输出：** `TurnStep`（而非分散的 narrative/changes/resolved）

**实现提醒：**
- `TurnStep` 是回合链对象，`StateEvolution` 更适合直接输出 `TurnResolution`
- `TurnStep` 建议由引擎层负责补充 `turn_id / step_id / trigger_source / timestamp` 后组装
- 这样可以避免执行层和调度层职责再次混淆

**涉及文件：**
- [`src/agent/state_evolution.py`](src/agent/state_evolution.py)
- [`src/engine/game_engine.py`](src/engine/game_engine.py)

---

### 3.6 Phase 5：重构 NPC Director 与执行链

**目标：** 让 Director 基于统一链路上下文规划，多NPC共享即时结果

**NPC 新流程：**

```
TurnTrace 
    → NpcActionPlan[] 
    → NPC Check 
    → NPC TurnStep 
    → TurnTrace 追加 
    → 下一个NPC读取更新后的 TurnTrace
```

**Director 新输入：**

```python
class NPCDirectorInputV2(BaseModel):
    # 第一部分：应激活NPC
    activated_npc_ids: List[str]
    
    # 第二部分：周围环境上下文
    surrounding_context: SurroundingContext
    
    # 第三部分：链路与记忆
    turn_trace_so_far: TurnTraceView        # E6：能读取玩家+前序NPC步骤
    narrative_memory: NarrativeMemoryView   # E8
    npc_world_views: List[NpcWorldView]     # E1：完整属性（STR/CON/EDU等）
    
    # 第四部分：元信息（精简后的）
    player_action_summary: str
    trigger_source: str
```

**关键改进：**
1. Director 不再接收整个 `DMAgentOutput`
2. 补充 `basic_info`, `description`, `memory`, 完整属性
3. 添加周围环境上下文（附近物品、不应激活但同场景的NPC）
4. **同回合每个 NPC 执行后必须先写回 `TurnTrace`，再允许下一个 NPC 开始推理**

**涉及文件：**
- [`src/agent/npc/npc_director.py`](src/agent/npc/npc_director.py)
- [`src/agent/npc/prompt/npc_director_prompt.md`](src/agent/npc/prompt/npc_director_prompt.md)
- [`src/engine/game_engine.py`](src/engine/game_engine.py)

---

### 3.7 Phase 6：重构叙事合并与记忆提交

**目标：** 让 NarrativeMerger 面对完整回合链，而非零散片段

**NarrativeMerger 新输入：**

```python
class NarrativeMergerInputV2(BaseModel):
    turn_trace_steps: List[TurnStep]        # E6：完整因果链
    turn_truth_anchor: TruthAnchor          # E4/E5：结算事实
    narrative_memory: NarrativeMemoryView   # E8
```

**NarrativeMerger 新输出：**

```python
class NarrativeMergerOutputV2(BaseModel):
    merged_narrative: str           # E7：展示叙事
    turn_summary: str               # E8：回合摘要
    new_key_facts: List[str]        # E8：关键事实
    dialogue_updates: List[DialogueMemoryEntry]  # E8：对话立场变化
```

**记忆提交升级：**
- 从"仅保存文本"升级为"更新长期记忆"
- `DialogueMemory` 真正进入推理链
- `NarrativeMemory` 与 `TurnTrace` 职责分离

**涉及文件：**
- [`src/narrative/narrative_merger.py`](src/narrative/narrative_merger.py)
- [`src/narrative/narrative_context.py`](src/narrative/narrative_context.py)
- [`src/narrative/prompt/narrative_merger_prompt.md`](src/narrative/prompt/narrative_merger_prompt.md)

---

### 3.8 Phase 7：重构持久化边界

**目标：** 把对推理有意义的数据纳入持久化协议

**持久化对象（新）：**

```python
class PersistenceSnapshotV2(BaseModel):
    game_state: GameState                   # E1
    dialogue_memory: DialogueMemory         # E8
    narrative_memory: NarrativeMemory       # E8
    recent_turn_traces: List[TurnTraceDigest]  # E6：最近N回合摘要
    save_version: str                       # 迁移版本
```

**改进要点：**
1. 存档不再只保存"能显示的东西"，还要保存"能继续推理的东西"
2. 增加版本化迁移器
3. 明确读档后哪些上下文必须立即可用
4. `DialogueMemory` 与 `NarrativeMemory` 必须能在读档后重新进入推理链，而不是只恢复展示

**涉及文件：**
- [`src/data/io_system.py`](src/data/io_system.py)
- [`src/engine/game_engine.py`](src/engine/game_engine.py)

---

### 3.9 Phase 8：Prompt 收敛与遗留清理

**目标：** 新协议稳定后，清理历史遗留

**删除清单：**
- [ ] Prompt 中的 `#修改建议`、非法 JSON 示例、已废弃字段说明
- [ ] `_process_npc_turns_until_player()` 等旧流程方法
- [ ] `_process_reactive_npc_response()` 等兼容层代码
- [ ] `action_description`, `player_resolution_anchor` 等旧字段
- [ ] `engine_context` 式大包字段

**收敛原则：**
- Prompt 只描述新协议，不保留旧字段兼容说明
- 兼容层只保留在适配器中，不保留在 Prompt 里

---

## 4. 字段映射速查表

### 4.1 必须合并的字段

| 字段A | 字段B | 目标对象 |
|-------|-------|----------|
| `player_check_result` | `player_resolution_anchor` | `TurnResolution` |
| 分散的 `check_*` | - | `CheckPlan` |
| `player_narrative` / `player_changes` / `action_succeeded` | - | 归并到 `TurnResolution` 的局部结算字段 |

### 4.2 必须拆分的字段

| 原字段 | 拆分结果 |
|--------|----------|
| `action_description` | `raw_input_text` + `intent_text` |
| `game_context` / `engine_context` | `WorldStateView` + `DialogueMemoryView` + `NarrativeMemoryView` + `TurnTraceView` |
| `narrative_context` | `NarrativeMemory` + `TurnTrace` |

### 4.3 必须下沉代码的字段

| 字段 | 处理方式 |
|------|----------|
| `actionable_npcs` | 代码筛选，DM只提供hint |
| `npc_actor_id` | 代码校验合法性 |
| `check_target` | 代码校验实体存在性 |
| `difficulty` | 代码校验枚举合法性 |

### 4.4 应删除的字段

| 字段 | 原因 |
|------|------|
| `engine_context` | 大包字段，职责不明 |
| `npc_response_mode` | 不应立即删除；迁移期先降级为兼容字段，待 Phase 8 完成协议收敛后再清理 |
| `fragments` | 文本碎片，非结构化因果链 |

---

## 5. 验收标准

### 5.1 链路一致性验收

| 测试项 | 通过标准 |
|--------|----------|
| 玩家阶段事实传递 | 玩家检定结果能稳定传到Director、NPC执行层、NarrativeMerger |
| 同回合因果传递 | 后续NPC能读取前序NPC的临时结果 |
| 叙事合并输入 | NarrativeMerger面对的是完整`TurnTrace.steps`而非零散片段 |

### 5.2 长期稳定性验收

| 测试项 | 通过标准 |
|--------|----------|
| 长对话一致性 | 10轮以上对话能保持角色立场与称谓基本稳定 |
| 50回合漂移 | NarrativeMemory不出现大面积事实漂移 |
| 读档延续性 | 读档后继续10回合推理不出现明显断层 |

### 5.3 工程可落实性验收

| 测试项 | 通过标准 |
|--------|----------|
| 阶段可合并 | 每阶段都可单独合并，不破坏主链路 |
| 适配器过渡 | 旧协议可通过适配器在新系统中运行 |
| 协议对齐 | Prompt与代码协议不再互相漂移 |

---

## 6. 实施时间表（建议）

```
Week 1-2:  前置修补（P0项必须完成）
Week 3:    Phase 1 - 定义新协议
Week 4:    Phase 2 - 拆分上下文构建器
Week 5:    Phase 3 - 重构DM层
Week 6:    Phase 4 - 重构玩家阶段
Week 7:    Phase 5 - 重构NPC阶段（核心）
Week 8:    Phase 6 - 重构叙事合并
Week 9:    Phase 7 - 重构持久化
Week 10:   Phase 8 - Prompt收敛与清理
Week 11+:  稳定性测试与调优
```

---

## 7. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 重构期间功能回归 | 高 | 每阶段必须有适配器，保留回滚能力 |
| 新协议设计缺陷 | 高 | Phase 1后冻结协议2周，验证设计合理性 |
| LLM适应新格式困难 | 中 | 保留旧格式适配层，逐步迁移Prompt |
| 测试覆盖不足 | 高 | 建立5项回归测试（见5.1-5.3） |
| 过早删除兼容模式 | 高 | 模式清理延后到协议稳定后执行，不与P0修补绑定 |

---

## 8. 一句话总结

> **前置修补消除事务与持久化层面的稳定性隐患，八阶段重构将系统从"字段与Prompt松散拼接"升级为"以九要素模型组织、由代码显式维护链路、LLM按统一协议参与的受控叙事系统"。**

**关键成功指标：** 50回合内叙事稳定性，取决于E6(回合因果链)是否完整、E8(长期记忆)是否能稳定提交、E9(读档恢复)是否能延续推理链。
