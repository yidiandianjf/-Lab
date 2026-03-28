# LLM提示词输入上下文分析

本文档详细列出每个LLM提示词在实际调用时接收的输入上下文,帮助识别冗余或不必要的字段。

---

## 1. System Prompt (DM Agent) - `src/agent/prompt/system_prompt.md`

**调用位置:** `src/agent/dm_agent.py:469-486`

### 1.1 固定部分
- **系统提示词内容** (从文件加载,185行)

### 1.2 动态输入上下文

#### 游戏上下文 (`_build_game_context` 方法生成)
```python
{
    "current_location": {
        "id": "地图ID",
        "name": "地图名称",
        "description": "地图公开描述"
    },
    "current_characters": [
        {
            "id": "角色ID",
            "name": "角色名",
            "is_player": true/false,
            "basic_info": "基本信息",
            "description_public": "公开描述",
            "description_hint": "隐藏信息(提示词)"
        }
    ],
    "current_items": [
        {
            "id": "物品ID",
            "name": "物品名",
            "description_public": "公开描述",
            "description_hint": "隐藏信息(提示词)",
            "is_portable": true/false
        }
    ],
    "player_info": {
        "id": "玩家ID",
        "name": "玩家名",
        "status": {"hp", "max_hp", "san"},
        "attributes": {"str", "con", "dex", "int", "pow", "edu"}
    }
}
```

#### 对话历史
- 最近5轮对话历史 (`max_history=5`)

#### 额外上下文 (additional_context)
| 字段 | 来源 | 说明 |
|------|------|------|
| `npc_response_mode` | 引擎传入 | queue/reactive |
| `npc_response_policy` | 引擎传入 | 模式策略文本 |
| `npc_prelude` | 引擎传入 | 本轮前置NPC行动 |
| `action_queue` | 引擎传入 | 当前行动队列快照 |
| `current_actor_id` | 引擎传入 | 当前行动者ID |
| `narrative_context` | 引擎传入 | 叙事历史上下文 |
| `engine_context` | 引擎传入 | 引擎补充上下文(JSON) |  #修改建议:这是什么?有什么作用
| `player_check_result` | 引擎传入 | 本轮玩家检定结果(JSON) |#修改建议:这是什么?有什么作用

#### 玩家输入
- 原始玩家输入文本

### 1.3 可能的冗余
1. **物品缺少位置信息** - `current_items` 中只有 `description_hint` 但没有 `location`
2. **对话历史格式** - 只是简单字符串列表,没有结构化  #修改建议:结构化
3. **`engine_context` 过于宽泛** - 可能包含不必要的信息

---

## 2. State Evolution Prompt - `src/agent/prompt/state_evolution_prompt.md`

**调用位置:** 
- 玩家行动: `src/agent/state_evolution.py:443-467`
- NPC行动: `src/agent/state_evolution.py:519-547`
- 结局判定: `src/agent/state_evolution.py:562-582`

### 2.1 固定部分
- **系统提示词内容** (从文件加载,282行)

### 2.2 动态输入上下文

#### 基础游戏上下文 (`_build_game_context` 方法)
```python
{
    "current_location": {
        "id": "地图ID",
        "name": "地图名称",
        "description": "地图公开描述"
    },
    "available_exits": [  # 仅在当前地图有邻居时
        {
            "map_id": "目标地图ID",
            "direction": "方向",
            "description": "描述"
        }
    ],
    "current_characters": [
        {
            "id": "角色ID",
            "name": "角色名",
            "is_player": true/false,
            "basic_info": "基本信息",
            "description_public": "公开描述",
            "description_hint": "隐藏信息",  
            "status": {"hp", "max_hp", "san"}
        }
    ],
    "current_items": [
        {
            "id": "物品ID",
            "name": "物品名",
            "location": "位置",
            "is_portable": true/false,
            "description_public": "公开描述",
            "description_hint": "隐藏信息"
        }
    ],
    "all_items_info": {  # 所有物品信息(包括不在当前地图的)
        "item-id": {
            "id", "name", "location", "is_portable",
            "description_public", "description_hint"
        }
    },
    "player_info": {
        "id": "玩家ID",
        "name": "玩家名",
        "basic_info": "基本信息",
        "status": {"hp", "max_hp", "san", "lucky"},
        "attributes": {"str", "con", "dex", "int", "pow", "edu"},
        "location": "位置",
        "inventory": ["物品ID列表"],
        "inventory_details": [  # 背包物品详细信息
            {"id", "name", "description"}
        ]
    },
    "turn_count": 回合数,
    "active_npc": {  # 仅NPC推演时有
        "id", "name", "basic_info",
        "description_public", "description_hint",
        "status": {"hp", "san"},
        "location"
    }
}
```

#### 玩家行动推演特有上下文
```python
{
    # 运行时上下文
    "npc_response_mode": "queue/reactive",
    "npc_response_expected": true/false,
    "npc_response_actor_id": "NPC ID",
    "npc_response_policy": "策略文本",
    "player_resolution_anchor": {  # JSON对象
        "action_succeeded": true/false,
        "check_result": {...}
    },
    
    # 任务信息
    "check_result": {  # 鉴定结果对象
        "result": "CRITICAL_SUCCESS/SUCCESS/FAILURE/FUMBLE",
        "dice_roll": 数值,
        "target_value": 目标值,
        "actor_value": 实际值,
        "detail": "详情"
    },
    "action_description": "行动描述"
}
```

#### NPC行动推演特有上下文
```python
{
    # 运行时上下文
    "npc_response_mode": "queue/reactive",
    "trigger": "queue/reactive",    
    "npc_response_policy": "策略文本",  #修改建议:这个是啥?
    "player_action_description": "玩家行动描述",
    "player_check_result": {  # JSON对象
        "result", "dice_roll", "target_value", ...
    },
    "player_resolution_anchor": {  # JSON对象
        "action_succeeded": true/false,
        "check_result": {...}
    },
    
    # NPC信息
    "npc_intent": "NPC意图描述",
    "check_result": {  # NPC的鉴定结果(可选)
        "result", "dice_roll", ...
    }
}
```

#### 结局判定特有上下文
- 仅基础游戏上下文 + 结局条件文本

### 2.3 可能的冗余
1. **`all_items_info` 包含所有物品** - 可能过于冗余,当前地图外的物品信息是否真的需要? 
2. **`inventory` 和 `inventory_details` 重复** - 一个是ID列表,一个是详细信息
3. **`available_exits` 信息** - 包含方向、描述、地图ID,可能只需地图ID
4. **`player_resolution_anchor` 和 `player_check_result` 重复** - 两者都包含检定信息

---

## 3. NPC Director Prompt - `src/agent/npc/prompt/npc_director_prompt.md`

**调用位置:** `src/agent/npc/npc_director.py:158-161`

### 3.1 固定部分
- **系统提示词内容** (从文件加载,53行)

### 3.2 动态输入上下文

#### 决策输入 (JSON格式)
```python
{
    "turn_count": 回合数,
    "player_id": "玩家ID",
    "npc_ids": ["NPC ID列表"],
    "trigger_source": "queue/reactive/unified",
    "player_intent": {  # DMAgentOutput的JSON表示   #修改建议:需要被激活的npc,以及玩家的行为描述,其它就删掉
        "is_dialogue": true/false,
        "response_to_player": "...",
        "needs_check": true/false,
        "check_type": "...",
        "check_attributes": [...],
        "check_target": "...",
        "difficulty": "...",
        "action_description": "...",
        "npc_response_needed": true/false,
        "npc_actor_id": "...",
        "npc_intent": "...",
        "actionable_npcs": [...]
    },
    "recent_events": [  # 最近10个事件   #修改建议:叙事上下文文本和最近10个事件有何区别
        {"type", "description", "actor_id", ...}
    ],
    "narrative_context": "叙事上下文文本",
    "npc_states": [  # 每个NPC的状态
        {
            "npc_id": "NPC ID",
            "name": "NPC名",
            "location": "位置",
            "status": {"hp", "max_hp", "san"},
            "attributes": {"dex", "int", "pow"}  # 只有3个属性!#修改建议:提供完整的属性
        }
    ]
}
```

### 3.3 可能的冗余/问题
1. **`player_intent` 包含整个DMAgentOutput** - 信息过多,NPC决策真的需要所有字段吗?
2. **`npc_states` 只包含3个属性** - DEX/INT/POW,但战斗可能需要STR/CON
3. **`recent_events` 没有过滤** - 可能包含与当前NPC无关的事件
4. **缺少NPC之间的关系信息** - NPC不知道其他NPC的存在和态度
5. **缺少物品信息** - NPC不知道场景中有哪些物品可用

---

## 4. Narrative Merger Prompt - `src/narrative/prompt/narrative_merger_prompt.md`

**调用位置:** `src/narrative/narrative_merger.py:68-72`

### 4.1 固定部分
- **系统提示词内容** (从文件加载,21行)

### 4.2 动态输入上下文

#### 合并输入 (JSON格式)
```python
{
    "turn_count": 回合数,
    "current_scene_id": "当前场景ID",
    "fragments": [  # 叙事片段列表
        {
            "actor_id": "行动者ID",
            "text": "叙事文本"
        }
    ],
    "context": "上下文文本",
    "truth_anchor": {  # 事实锚点
        "action_succeeded": true/false,
        "check_result": {...},
        "player_changes": [...]
    }
}
```

### 4.3 可能的冗余/问题
1. **提示词过于简单** - 只有21行,缺少具体的合并规则示例
2. **`context` 字段模糊** - 不知道具体包含什么内容
3. **`truth_anchor` 信息可能不完整** - 只包含玩家阶段的信息
4. **缺少角色信息** - 无法根据角色特点调整叙事风格

---

## 总结:各提示词输入对比

| 提示词 | 上下文大小 | 主要冗余 | 缺失信息 |
|--------|-----------|---------|---------|
| **System Prompt** | 中等 | 物品缺位置,对话历史非结构化 | 玩家完整属性 |
| **State Evolution** | 大 | all_items_info, inventory重复, anchor/check_result重复 | - |
| **NPC Director** | 中等 | player_intent字段过多 | NPC间关系,物品信息,完整属性 |
| **Narrative Merger** | 小 | - | 角色信息,合并示例 |

---

## 优化建议

### 高优先级
1. **统一检定信息字段** - `player_resolution_anchor` 和 `player_check_result` 合并
2. **清理State Evolution的物品信息** - 删除 `all_items_info` 或改为按需加载
3. **补充NPC Director的NPC属性** - 添加STR/CON等战斗相关属性

### 中优先级
4. **为NPC Director添加场景物品信息** - 让NPC知道可以使用什么物品
5. **为Narrative Merger添加角色风格信息** - 根据角色特点调整叙事
6. **标准化对话历史格式** - 统一为结构化格式而非简单字符串

### 低优先级
7. **清理inventory重复** - 只保留 `inventory_details`
8. **优化available_exits** - 只保留必要信息

---

## 附录: NPC响应决策部分深度分析

### 背景
用户询问 `system_prompt.md` 中第51-73行的 **"NPC响应决策"** 部分是否有实际作用。

### 代码验证结果

通过搜索 `src/` 目录下所有 Python 文件,确认以下字段的实际使用情况:

| 字段 | 使用次数 | 关键使用位置 | 用途 |
|------|---------|-------------|------|
| `npc_response_needed` | 5处 | `game_engine.py:414, 690, 829, 1715` | 判断是否触发NPC响应 |
| `npc_actor_id` | 6处 | `game_engine.py:696, 831, 1304, 1332` | 指定响应的NPC ID |
| `npc_intent` | 5处 | `game_engine.py:602, 712, 1335, 1769` | NPC响应意图描述 |
| `actionable_npcs` | 3处 | `game_engine.py:1251, 1719` | 建议可参与的NPC列表 |

**结论:** 这些字段在 `game_engine.py` 中有实际使用,用于驱动NPC响应流程。

### 当前逻辑流程

```
DM Agent(LLM)
    ↓ 解析玩家输入
输出 npc_response_needed / npc_actor_id / npc_intent / actionable_npcs
    ↓
GameEngine 读取并使用这些字段
    ↓
决定是否需要NPC响应、哪个NPC响应、如何响应
```

### 改造建议: 硬编码替代LLM判断

**可删除的提示词内容 (第51-73行,约23行):**
- "8. NPC响应决策" 章节
- queue/reactive 模式详细说明
- 动态上下文字段列表
- 决策要求说明

**建议的硬编码实现方案:**

```python
# 在 game_engine.py 中添加以下方法

class GameEngine:
    def _should_npc_respond(self, dm_output: DMAgentOutput) -> bool:
        """硬编码判断是否需要NPC响应"""
        # 需要检定的行动 → 需要响应(有风险,NPC可能注意到)
        if dm_output.needs_check:
            return True
        
        # 对抗鉴定 → 必须响应
        if dm_output.check_type == "对抗鉴定":
            return True
        
        # 纯对话 → 不需要响应
        if dm_output.is_dialogue and not dm_output.needs_check:
            return False
        
        # 默认: 不需要响应
        return False
    
    def _select_npc_actor(self, dm_output: DMAgentOutput) -> Optional[str]:
        """硬编码选择响应的NPC"""
        scene_npcs = self._get_scene_npcs()
        if not scene_npcs:
            return None
        
        # 优先级1: 对抗目标
        if dm_output.check_target and dm_output.check_target in scene_npcs:
            return dm_output.check_target
        
        # 优先级2: 场景中的第一个可用NPC
        return scene_npcs[0]
        #修改建议:使用队列系统中的优先级来完成
    
    def _get_actionable_npcs(self) -> List[str]:
        """硬编码获取可行动NPC列表"""
        # 返回当前场景中所有HP>0且SAN>0的NPC
        return [
            npc_id for npc_id in self._get_scene_npcs()
            if self._is_npc_actionable(npc_id)
        ]
```

### 改造收益

| 方面 | 效果 |
|------|------|
| **Token消耗** | 减少约23行提示词 |
| **可控性** | 代码逻辑比LLM判断更稳定、可预测 |
| **可维护性** | 易于单元测试和调试 |
| **性能** | 减少LLM思考负担,加快响应速度 |
| **一致性** | 避免LLM理解偏差导致的行为不一致 |

### 注意事项

1. **`npc_intent` 建议保留** - 意图描述较难硬编码,仍需LLM生成
2. **需要更新 `DMAgentOutput` 模型** - 将这些字段改为可选或有默认值
3. **需要更新 `game_engine.py`** - 在读取 `dm_output` 时添加兜底逻辑:

```python
# 改造后的读取逻辑示例
npc_response_needed = (
    dm_output.npc_response_needed
    if dm_output.npc_response_needed is not None
    else self._should_npc_respond(dm_output)
)
```

### 推荐的改造顺序

1. **第一步** - 在 `game_engine.py` 中实现硬编码方法
2. **第二步** - 修改读取逻辑,优先使用代码判断,LLM输出作为可选覆盖
3. **第三步** - 测试验证行为一致性
4. **第四步** - 删除 `system_prompt.md` 中的NPC响应决策部分
5. **第五步** - 更新 `DMAgentOutput` 模型,将这些字段标记为可选

### 最终建议

**可以安全地删除提示词中的NPC响应决策部分**,改为硬编码实现。这符合你之前提到的"#修改建议:能不能对此功能使用硬编码实现,不要依靠llm,提示词,不要依靠提示词"。

唯一需要保留的是 `npc_intent` 字段的生成,因为NPC的具体响应意图较难通过硬编码规则完整覆盖。



#修改建议: 研究哪些工作已经可以根据llm生成的json字段使用代码来完成,但目前使用提示词+llm来完成
#修改建议: 删除queue队列代码已经相关提示词,仅保留目前的npc响应模式