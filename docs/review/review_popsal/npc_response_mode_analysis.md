# NPC响应模式实现现状分析报告

## 概要

当前实现**部分符合**设计预期，但在**输入上下文分离**和**周围角色信息提供**方面存在关键缺陷。

---

## 一、当前实现流程

### 1.1 数据流图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              玩家输入                                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Step 3: DM Agent解析                                                       │
│  ├─ 生成 actionable_npcs: 建议激活的NPC列表                                  │
│  ├─ 生成 npc_response_needed: 是否需要响应                                   │
│  └─ 生成 npc_actor_id: 首选响应NPC                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Step 6: _process_unified_npc_response()                                    │
│  ├─ 解析 actionable_npcs 列表                                               │
│  ├─ 添加 npc_actor_id 到候选列表                                             │
│  └─ 构建 candidate_ids: 最终应激活NPC列表                                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  _plan_npc_actions()                                                        │
│  ├─ 接收 candidate_npc_ids (应激活NPC)                                      │
│  ├─ 调用 NPCDirector.decide_actions()                                       │
│  └─ 传入 game_state, player_intent, narrative_context                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  NPCDirector.decide_actions()                                               │
│  ├─ _filter_actionable_npcs(): 过滤无效NPC (hp<=0, san<=0)                  │
│  ├─ _build_prompt(): 构建输入                                                │
│  │   └─ ❌ 问题：只序列化了应激活NPC的状态                                   │
│  └─ _llm_decide(): 调用LLM决策                                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  _parse_decision()                                                          │
│  ├─ ✅ 检查 npc_id in allowed_npc_ids: 过滤非法NPC                          │
│  └─ 返回有效行动计划                                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、符合设计的部分 ✅

### 2.1 DMAgent生成应激活NPC列表

**位置：** [`src/agent/dm_agent.py:98-102`](src/agent/dm_agent.py:98-102)

```python
"actionable_npcs": {
    "type": "array",
    "items": {"type": "string"},
    "description": "建议在本回合响应阶段可行动的NPC列表"
}
```

**输出模型：** [`src/data/models.py:313`](src/data/models.py:313)

```python
class DMAgentOutput(BaseModel):
    actionable_npcs: List[str] = Field(default_factory=list, description="建议本轮可行动NPC列表")
    npc_response_needed: bool = Field(default=False, description="是否需要NPC响应")
    npc_actor_id: Optional[str] = Field(default=None, description="需要响应的NPC ID")
```

### 2.2 代码解析并验证列表

**位置：** [`src/engine/game_engine.py:1719-1738`](src/engine/game_engine.py:1719-1738)

```python
candidate_ids = list(dm_output.actionable_npcs or [])
if dm_output.npc_actor_id and dm_output.npc_actor_id not in candidate_ids:
    candidate_ids.append(dm_output.npc_actor_id)
```

### 2.3 非法NPC检测系统

**位置：** [`src/agent/npc/npc_director.py:183-196`](src/agent/npc/npc_director.py:183-196)

```python
def _parse_decision(self, data: Dict[str, Any], allowed_npc_ids: List[str]) -> NPCActionDecision:
    raw_actions = data.get("actions") or {}
    actions: Dict[str, NPCActionForm] = {}
    for npc_id, raw_action in raw_actions.items():
        if npc_id not in allowed_npc_ids:  # ✅ 检测非法NPC
            continue  # 跳过不在允许列表中的NPC
        ...
```

**过滤规则：** [`src/agent/npc/npc_director.py:233-242`](src/agent/npc/npc_director.py:233-242)

```python
def _filter_actionable_npcs(self, npc_ids: List[str], game_state: GameState) -> List[str]:
    filtered: List[str] = []
    for npc_id in npc_ids:
        npc = game_state.characters.get(npc_id)
        if not npc or npc.is_player:  # ✅ 排除玩家
            continue
        if npc.status.hp <= 0 or npc.status.san <= 0:  # ✅ 排除死亡/疯狂NPC
            continue
        filtered.append(npc_id)
    return filtered
```

---

## 三、存在问题的部分 ❌

### 3.1 问题1：NPCDirector输入未分两部分

**期望设计：**
```python
{
    "activated_npcs": [...],  # 应激活NPC的ID列表
    "surrounding_context": {  # 周围角色及环境信息
        "nearby_npcs": [...],  # 周围其他NPC（不应激活但需要感知）
        "player_info": {...},
        "current_map": {...},
        "items": [...]
    }
}
```

**当前实现：** [`src/agent/npc/npc_director.py:147-161`](src/agent/npc/npc_director.py:147-161)

```python
def _build_prompt(...):
    payload = {
        "turn_count": game_state.turn_count,
        "player_id": game_state.player_id,
        "npc_ids": npc_ids,  # ✅ 应激活NPC列表
        "npc_states": [self._serialize_npc_state(game_state, npc_id) for npc_id in npc_ids],
        # ❌ 问题：没有单独的周围角色信息
        # ❌ 问题：没有区分"应激活"和"周围其他角色"
    }
```

**影响：**
- LLM无法感知周围不应激活的NPC（如旁观者、背景角色）
- 可能导致NPC决策缺乏环境感知（不知道周围还有谁）
- 无法做出合理的社交决策（如"在守卫面前不敢偷窃"）

### 3.2 问题2：NPC状态序列化过于简单

**当前实现：** [`src/agent/npc/npc_director.py:163-181`](src/agent/npc/npc_director.py:163-181)

```python
def _serialize_npc_state(self, game_state: GameState, npc_id: str) -> Dict[str, Any]:
    return {
        "npc_id": npc.id,
        "name": npc.name,
        "location": npc.location,
        "status": {"hp": npc.status.hp, "max_hp": npc.status.max_hp, "san": npc.status.san},
        "attributes": {"dex": npc.attributes.dex, "int": npc.attributes.int, "pow": npc.attributes.pow},
        # ❌ 缺少：basic_info（背景）
        # ❌ 缺少：description（性格描述）
        # ❌ 缺少：memory（记忆）
        # ❌ 缺少：与玩家关系
    }
```

### 3.3 问题3：缺少周围环境上下文

**当前prompt输入：** [`src/agent/npc/prompt/npc_director_prompt.md:5-11`](src/agent/npc/prompt/npc_director_prompt.md:5-11)

```markdown
## 输入
- 游戏状态（场景、角色、物品、回合）
- 玩家意图解析结果
- 需要决策的 NPC 列表
- 近期叙事事件
- 触发来源标签（queue/reactive/unified）
- PlayerResolutionAnchor
```

**实际代码只传递了：**
- `npc_states`: 应激活NPC的简单状态
- `player_intent`: 玩家意图
- `recent_events`: 近期事件

**缺失的关键信息：**
- ❌ 当前地图详细信息（出口、描述）
- ❌ 地图上的物品列表
- ❌ 不应激活但同场景的其他NPC
- ❌ 玩家完整状态（背包、属性等）

---

## 四、改进建议

### 4.1 重构NPCDirector输入结构

```python
class NPCDirectorInput(BaseModel):
    """NPC Director的完整输入结构"""
    
    # 第一部分：应激活NPC（需要做出决策的NPC）
    activated_npcs: List[ActivatedNPCInfo] = Field(...)
    
    # 第二部分：周围环境上下文
    surrounding_context: SurroundingContext = Field(...)
    
    # 其他元信息
    player_intent: Optional[DMAgentOutput] = None
    trigger_source: str = "unified"
    recent_events: List[dict] = Field(default_factory=list)
    narrative_context: str = ""


class ActivatedNPCInfo(BaseModel):
    """应激活NPC的完整信息"""
    npc_id: str
    name: str
    basic_info: str  # 背景信息
    description: str  # 性格/外貌描述
    location: str
    status: Dict[str, int]  # hp, max_hp, san
    attributes: Dict[str, int]  # 所有属性
    memory: Dict[str, Any]  # 记忆摘要
    relationship_to_player: str  # 与玩家关系描述


class SurroundingContext(BaseModel):
    """周围环境上下文"""
    current_map: MapInfo  # 当前地图详情
    nearby_npcs: List[NPCSnapshot]  # 周围不应激活但可见的NPC
    visible_items: List[ItemSnapshot]  # 可见物品
    player_snapshot: PlayerSnapshot  # 玩家状态快照


class NPCSnapshot(BaseModel):
    """周围NPC快照（简化信息）"""
    npc_id: str
    name: str
    basic_info: str
    relative_position: str  # "附近", "远处", "门口"等
    attitude_hint: str  # 对当前局势的态度提示
```

### 4.2 修改NPCDirector._build_prompt()

```python
def _build_prompt(
    self,
    activated_npc_ids: List[str],  # 重命名以明确语义
    game_state: GameState,
    player_intent: Optional[DMAgentOutput],
    trigger_source: str,
    recent_events: List[dict],
    narrative_context: str,
) -> str:
    # 获取当前地图
    current_map = game_state.get_current_map()
    
    # 第一部分：应激活NPC的详细信息
    activated_npcs = [
        self._serialize_activated_npc(game_state, npc_id)
        for npc_id in activated_npc_ids
    ]
    
    # 第二部分：周围环境上下文
    surrounding_context = {
        "current_map": self._serialize_map(current_map),
        "nearby_npcs": self._serialize_nearby_npcs(
            game_state, 
            current_map, 
            exclude_ids=activated_npc_ids  # 排除应激活NPC
        ),
        "visible_items": self._serialize_visible_items(game_state, current_map),
        "player_snapshot": self._serialize_player_snapshot(game_state),
    }
    
    payload = {
        "activated_npcs": activated_npcs,  # 应激活NPC
        "surrounding_context": surrounding_context,  # 周围环境
        "player_intent": player_intent.model_dump() if player_intent else None,
        "trigger_source": trigger_source,
        "recent_events": recent_events[-10:],
        "nationale": "你只能为 activated_npcs 中的NPC生成行动，但可以参考 surrounding_context 中的信息做决策"
    }
    
    return (
        f"{self.system_prompt}\n\n"
        "## 决策输入(JSON)\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
```

### 4.3 更新NPCDirector提示词

**添加约束：** [`src/agent/npc/prompt/npc_director_prompt.md`](src/agent/npc/prompt/npc_director_prompt.md)

```markdown
## 输入结构说明

### 1. activated_npcs（应激活NPC）
- 这些是本回合需要做出行动的NPC
- **你只能为这些NPC生成行动计划**
- actions字典的key必须是这些NPC的ID之一

### 2. surrounding_context（周围环境上下文）
- 用于决策参考，但不能为这些NPC生成行动
- nearby_npcs: 同场景但不应激活的NPC（旁观者、背景角色）
- visible_items: 场景中的可见物品
- player_snapshot: 玩家当前状态

## 约束
- ✅ 只能给 activated_npcs 中的NPC生成行动
- ✅ 可以参考 surrounding_context 中的nearby_npcs做社交决策
- ❌ 不能给 nearby_npcs 生成行动
- ❌ 不能编造不存在于输入中的NPC
```

---

## 五、总结

| 检查项 | 状态 | 说明 |
|--------|------|------|
| DMAgent生成应激活NPC列表 | ✅ 已实现 | `actionable_npcs` + `npc_actor_id` |
| 代码解析列表 | ✅ 已实现 | `_process_unified_npc_response()` 构建 `candidate_ids` |
| NPCDirector输入分两部分 | ❌ 未实现 | 当前只传递了应激活NPC，缺少周围角色信息 |
| 周围角色信息提供 | ❌ 未实现 | 没有 `surrounding_context` 结构 |
| 非法NPC检测 | ✅ 已实现 | `_parse_decision()` 检查 `allowed_npc_ids` |
| 不应激活NPC过滤 | ✅ 已实现 | `_filter_actionable_npcs()` 过滤死亡/疯狂NPC |

### 优先级建议

1. **高优先级**：重构NPCDirector输入，分离 `activated_npcs` 和 `surrounding_context`
2. **中优先级**：丰富NPC序列化信息（添加basic_info、description、memory）
3. **低优先级**：优化提示词，明确告知LLM两部分输入的区别和使用规则
