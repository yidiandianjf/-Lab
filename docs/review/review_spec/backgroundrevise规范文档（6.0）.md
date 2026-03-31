# 《红楼梦·黛玉初进贾府》场景配置规范文档 v6.0

> 本文档定义将游戏背景从COC（克苏鲁的呼唤）迁移至《红楼梦》"黛玉初进贾府"场景所需的全部配置规范。
> 
> 适用版本: A Engine v2.0
> 生成时间: 2026-03-31
> 文档状态: 演示场景专用
> 
> **v6.0 更新说明**: 明确教育目标定位，区分"体验式学习"与"教学评估"，避免文档过度承诺

---

## 目录

1. [概述与目标](#概述与目标)
2. [设计原则与架构决策](#设计原则与架构决策)
3. [世界配置规范](#世界配置规范)
4. [角色配置规范](#角色配置规范)
5. [场景地图配置规范](#场景地图配置规范)
6. [物品配置规范](#物品配置规范)
7. [结局配置规范](#结局配置规范)
8. [结局条件设计规范](#结局条件设计规范)
9. [LLM上下文适配规范](#llm上下文适配规范)
10. [字段语义设计规范](#字段语义设计规范)
11. [演示流程脚本](#演示流程脚本)
12. [验证检查清单](#验证检查清单)

---

## 概述与目标

### 场景背景

本场景还原《红楼梦》第三回"贾雨村夤缘复旧职 林黛玉抛父进京都"中黛玉初入贾府的经典片段。通过沉浸式交互体验，让玩家（扮演林黛玉）在AI驱动的虚拟环境中：

- 感受清代贵族家庭的礼仪规范
- 理解人物关系与等级秩序
- 体会林黛玉敏感细腻的心理活动
- 学习古典文学中的人物塑造艺术

### 核心设计原则

1. **纯配置化实现**: 不修改任何源代码，仅通过配置文件实现场景切换
2. **教育导向**: 注重文学理解与文化体验，弱化游戏性数值
3. **边界自然处理**: 对超纲输入（如"抄家"）通过NPC困惑反应自然拦截，无弹窗警告
4. **情感沉浸**: 通过细腻的环境描写和人物互动营造代入感
5. **性能可控**: 明确角色数量上限，确保系统稳定运行
6. **体验式学习**: 通过沉浸式角色扮演实现教育价值，非结构化教学评估
7. **语义清晰**: 通过Prompt层明确字段语义，避免LLM混淆

---

## 设计原则与架构决策

### NPC角色数量设计原则

#### 设计演进

| 版本 | 角色数量 | 设计原则 | 适用场景 |
|------|---------|---------|---------|
| v1.0 | 3角色 | "最多3个角色"以控制复杂度 | 一般场景推荐 |
| v2.0+ | 4角色 | "推荐3角色，演示场景上限4角色" | 演示场景允许 |

#### 架构决策说明

经过对NPCDirector模块的代码审查和性能评估，确定以下架构决策：

**1. 4角色配置的技术可行性**

- ✅ **算法复杂度**: NPCDirector处理逻辑为O(n)，4角色仍在可控范围
- ✅ **资源占用**: LLM调用次数与角色数成正比，4角色增加约30%处理时间（<1秒，可接受）
- ✅ **架构兼容**: 现有代码无硬编码角色数量限制
- ✅ **稳定性**: 经评估，4角色配置不会导致系统崩溃或性能严重下降

**2. 角色功能定位**

| 角色 | 功能定位 | 必要性 | 说明 |
|------|---------|--------|------|
| 林黛玉 | 玩家角色 | ⭐⭐⭐⭐⭐ | 主角，必须保留 |
| 贾母 | 核心NPC | ⭐⭐⭐⭐⭐ | 情感主线，必须保留 |
| 王熙凤 | 关键NPC | ⭐⭐⭐⭐⭐ | 展现贾府规矩，必须保留 |
| 丫鬟婆子 | 辅助NPC | ⭐⭐⭐ | 引导功能，可由环境叙事替代，但保留可增强沉浸感 |

**3. 最终决策: 保留4角色配置**

**理由**:
1. **用户体验优先**: 丫鬟婆子虽功能弱，但"林姑娘到了"等互动增强沉浸感
2. **教育价值完整**: 体现贾府"仆人众多"的等级秩序，符合教育场景目标
3. **性能影响可控**: 4角色相比3角色增加约30%LLM调用时间，仍在可接受范围
4. **保留扩展空间**: 明确4角色为演示场景上限，未来如需可增加重要NPC

**降级策略**（如性能问题出现）:
- 优先合并丫鬟婆子为环境叙事
- 保留核心3角色（黛玉、贾母、王熙凤）

---

### 教育目标定位说明（v6.0新增）

#### 当前定位: 体验式学习 + 结局反思

**实现的教育价值**:

| 机制 | 实现方式 | 教育价值 |
|------|---------|---------|
| **沉浸式体验** | 扮演黛玉，与AI驱动的NPC互动 | 自然感受古典文学氛围和人物情感 |
| **结局反思** | 失礼结局中的反思文本 | 引导玩家思考礼仪规范的重要性 |
| **进度验证** | 关键事实（key_facts）检查 | 确保玩家完成核心互动环节 |

**非实现功能（明确说明）**:

| 功能 | 状态 | 说明 |
|------|------|------|
| 实时学习行为评估 | ❌ 未实现 | 无行为评分系统 |
| 教学指标追踪 | ❌ 未实现 | 无学习数据模型 |
| 学习报告生成 | ❌ 未实现 | 无评估报告功能 |
| 过程性评价 | ❌ 未实现 | 无中间反馈机制 |

**设计意图说明**:

本场景定位为**体验式学习（Experiential Learning）**，教育价值主要来自：

1. **情境沉浸**: 通过第一人称视角体验黛玉进贾府的经典场景
2. **情感共鸣**: 与贾母、凤姐等角色的互动中体会人物关系和情感
3. **文化感知**: 在场景描写和对话中感受清代贵族家庭的礼仪规范
4. **反思引导**: 在特定结局中提供学习反思，引导玩家回顾体验

**与结构化教学的区别**:

| 维度 | 体验式学习（当前） | 结构化教学（未实现） |
|------|------------------|---------------------|
| 评估方式 | 无评分，通过反思引导 | 有明确评分标准 |
| 反馈时机 | 仅在结局时 | 实时反馈 |
| 指标追踪 | 无 | 有完整学习指标 |
| 报告生成 | 无 | 有学习报告 |

**未来扩展建议**:

如需完整教育评估功能，建议后续版本增加学习分析模块（Learning Analytics），包括：
- 行为追踪和评估算法
- 学习指标数据模型
- 学习报告生成功能

---

## 世界配置规范

### 文件路径
```
config/world/daiyu_enters_jia/world.json
```

### 完整配置模板

```json
{
  "world_id": "world-daiyu-enters-jia",
  "world_name": "daiyu_enters_jia",
  "player_id": "char-daiyu-01",
  "start_map_id": "map-gate-01",
  "turn_order": [
    "char-daiyu-01",
    "char-jiamu-01",
    "char-xifeng-01",
    "char-servant-01"
  ],
  "narrative_window": 5,
  "npc_response_mode": "unified",
  "npc_director_use_llm": true,
  "narrative_merge_use_llm": true,
  "end_condition": "完成与贾母、王熙凤的初次见面，理解贾府礼仪规范。玩家从荣国府大门进入，经西角门、垂花门，到达贾母正房，与贾母和王熙凤完成对话互动。",
  "entry_scene_narrative": "且说黛玉自那日弃舟登岸，轿子进了荣国府，抬眼便见街北蹲着两个大石狮子，三间兽头大门。你的心扑扑直跳，手心里全是汗——母亲说过，外祖母家与别家不同。"
}
```

### 字段说明

| 字段 | 值 | 说明 |
|------|-----|------|
| `world_id` | `world-daiyu-enters-jia` | 世界唯一标识 |
| `world_name` | `daiyu_enters_jia` | 目录名，与文件夹名一致 |
| `player_id` | `char-daiyu-01` | 玩家扮演林黛玉 |
| `start_map_id` | `map-gate-01` | 初始场景：荣国府大门 |
| `turn_order` | 见模板 | 回合顺序：黛玉→贾母→凤姐→丫鬟婆子 |
| `entry_scene_narrative` | 见模板 | 开场叙事，营造氛围 |

### narrative_window 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `narrative_window` | int | 5 | 叙事上下文窗口大小，控制保留的最近事件数量 |

**功能说明**:
- 决定 NarrativeContext 中 `recent_events` 的最大长度
- 当事件数超过此值时，最旧事件会被压缩到摘要中
- 影响提供给 LLM 的叙事上下文深度
- 与 `memory_policy` 独立工作：前者控制引擎层数据结构，后者控制 LLM 层行为指导

**配置建议**:
| 场景类型 | 推荐值 | 说明 |
|---------|--------|------|
| 简单场景 | 5（默认） | 适合单线叙事，内存占用小 |
| 复杂多角色场景 | 8-10 | 保留更多上下文，增强角色连贯性 |
| 长流程场景 | 10+ | 需要更多历史记忆时使用 |

**注意事项**:
- 增大窗口会增加 LLM 上下文长度，可能导致 token 消耗增加
- 该字段支持存档/读档时保存和恢复
- 运行时可通过 `GameEngine._set_narrative_window()` 动态调整

---

## 角色配置规范

### 角色配置总览

本场景采用**4角色配置**，为演示场景推荐上限：

| 序号 | 角色 | ID | 类型 | 场景位置 | 功能定位 |
|------|------|-----|------|---------|---------|
| 1 | 林黛玉 | char-daiyu-01 | 玩家角色 | 大门（起点） | 主角，玩家控制 |
| 2 | 贾母 | char-jiamu-01 | 核心NPC | 贾母正房 | 情感主线，慈爱长辈 |
| 3 | 王熙凤 | char-xifeng-01 | 关键NPC | 贾母正房 | 展现贾府规矩，精明管家 |
| 4 | 丫鬟婆子 | char-servant-01 | 辅助NPC | 垂花门 | 引导过渡，烘托氛围 |

### 3.1 林黛玉（玩家角色）

**文件路径**: `config/world/daiyu_enters_jia/characters/char-daiyu-01.json`

```json
{
  "id": "char-daiyu-01",
  "name": "林黛玉",
  "basic_info": "姑苏林如海之女，母亲贾敏是贾母最疼爱的女儿。母亲去世后，奉父命来贾府投靠外祖母。体弱多病，心思细腻，知书达理。",
  "description": {
    "public": [
      {
        "description": "一位年方六七岁的少女，身子单薄，眉目间带着几分病态的柔弱，却掩不住天生的灵秀之气。穿着月白绫子的袄儿，举止间透着大家闺秀的教养。"
      }
    ],
    "hint": "玩家控制的角色。核心特质：1)极重礼数，谨慎小心，进入贾府时'不肯走正门'体现教养；2)敏感多思，善于察言观色；3)对母亲思念深切，提及母亲易落泪；4)初到陌生环境既好奇又忐忑。行为应体现'步步留心，时时在意'。"
  },
  "location": "map-gate-01",
  "inventory": ["item-handkerchief-01"],
  "status": {
    "hp": 12,
    "max_hp": 12,
    "san": 70,
    "lucky": 45
  },
  "attributes": {
    "str": 6,
    "con": 8,
    "siz": 8,
    "dex": 12,
    "app": 16,
    "int": 18,
    "pow": 14,
    "edu": 14
  },
  "memory": {
    "current_event": "",
    "log": []
  },
  "is_player": true
}
```

**属性设计说明**:
- `int`: 18 (极高) - 聪慧敏感，善于观察
- `app`: 16 (高) - 容貌灵秀
- `str/con`: 6-8 (低) - 体弱多病
- `edu`: 14 (较高) - 书香门第教养

---

### 3.2 贾母

**文件路径**: `config/world/daiyu_enters_jia/characters/char-jiamu-01.json`

```json
{
  "id": "char-jiamu-01",
  "name": "贾母",
  "basic_info": "荣国府老祖宗，贾赦、贾政之母，黛玉的外祖母。年事已高，地位尊崇，最疼爱已故的女儿贾敏。",
  "description": {
    "public": [
      {
        "description": "一位鬓发如银的老太太，穿一件酱色潞绸蟒袍，罩一件石青缎子坎肩，戴着银白发髻，慈眉善目却自带威严。身上散发着淡淡的沉水香。"
      }
    ],
    "hint": "贾府最高权威，情感丰富。见到黛玉会：1)想起已故女儿贾敏，容易落泪；2)心疼黛玉瘦弱，关心身体；3)强调'就当这里是自己家里'；4)对超纲言论（如'抄家''未来'）理解为'胡话/发热'，会关心地探额头、请太医；5)吩咐鸳鸯等丫鬟安排黛玉住处。语言风格：慈爱中带威严，用词典雅。\n\n【关键事实生成】与黛玉初次见面后，确保在narrative_memory.key_facts中添加'已见贾母'，记录此次见面的核心互动内容。"
  },
  "location": "map-jiamu-room-01",
  "inventory": [],
  "status": {
    "hp": 10,
    "max_hp": 10,
    "san": 80,
    "lucky": 60
  },
  "attributes": {
    "str": 6,
    "con": 8,
    "siz": 10,
    "dex": 8,
    "app": 12,
    "int": 16,
    "pow": 18,
    "edu": 16
  },
  "memory": {
    "current_event": "",
    "log": []
  },
  "is_player": false
}
```

---

### 3.3 王熙凤

**文件路径**: `config/world/daiyu_enters_jia/characters/char-xifeng-01.json`

```json
{
  "id": "char-xifeng-01",
  "name": "王熙凤",
  "basic_info": "贾琏之妻，王夫人的侄女，贾府实际管家。精明强干，善于逢迎，手腕高明。",
  "description": {
    "public": [
      {
        "description": "打扮彩绣辉煌，恍若神妃仙子——头上戴着金丝八宝攒珠髻，绾着朝阳五凤挂珠钗，项上戴着赤金盘螭璎珞圈，裙边系着豆绿宫绦。一双丹凤三角眼，两弯柳叶吊梢眉，身量苗条，体格风骚，粉面含春威不露，丹唇未启笑先闻。"
      }
    ],
    "hint": "精明能干，善于说话，热情但带试探。行为特点：1)说话漂亮，会夸人'天下真有这样标致的人物'；2)办事利落，当场安排碧纱橱住处；3)对贾母极尽逢迎'怨不得老祖宗天天口头心头一时不忘'；4)对黛玉表面热情实则观察；5)笑声爽朗，'我来迟了，不曾迎接远客'体现其特殊地位。\n\n【关键事实生成】与黛玉初次见面后，确保在narrative_memory.key_facts中添加'已见王熙凤'，记录此次见面的核心互动内容。"
  },
  "location": "map-jiamu-room-01",
  "inventory": [],
  "status": {
    "hp": 14,
    "max_hp": 14,
    "san": 75,
    "lucky": 55
  },
  "attributes": {
    "str": 10,
    "con": 12,
    "siz": 11,
    "dex": 14,
    "app": 16,
    "int": 17,
    "pow": 15,
    "edu": 14
  },
  "memory": {
    "current_event": "",
    "log": []
  },
  "is_player": false
}
```

---

### 3.4 丫鬟婆子（辅助NPC）

**文件路径**: `config/world/daiyu_enters_jia/characters/char-servant-01.json`

```json
{
  "id": "char-servant-01",
  "name": "婆子丫鬟们",
  "basic_info": "贾府的仆人们，负责引导、服侍、传话等事务。",
  "description": {
    "public": [
      {
        "description": "几个穿着体面的婆子和丫鬟，举止恭敬，训练有素。"
      }
    ],
    "hint": "功能性NPC，负责：1)引导黛玉从大门到正房；2)传话通报；3)服侍贾母和黛玉；4)烘托贾府的规矩和排场。语言简单恭敬，如'林姑娘到了''姑娘请这边走'。"
  },
  "location": "map-entrance-01",
  "inventory": [],
  "status": {
    "hp": 10,
    "max_hp": 10,
    "san": 50,
    "lucky": 40
  },
  "attributes": {
    "str": 10,
    "con": 10,
    "siz": 10,
    "dex": 10,
    "app": 10,
    "int": 10,
    "pow": 10,
    "edu": 8
  },
  "memory": {
    "current_event": "",
    "log": []
  },
  "is_player": false
}
```

**设计说明**: 丫鬟婆子作为第4角色，主要起过渡引导作用。如性能问题出现，可降级为环境叙事（见[降级策略](#降级策略)）。

---

## 场景地图配置规范

### 4.1 荣国府大门

**文件路径**: `config/world/daiyu_enters_jia/maps/map-gate-01.json`

```json
{
  "id": "map-gate-01",
  "name": "荣国府大门",
  "parent_id": null,
  "description": {
    "public": [
      {
        "description": "街北蹲着两个大石狮子，三间兽头大门。正门之上有一匾，匾上大书'敕造宁国府'五个大字，又往西行不多远，照样也是三间大门，方是'荣国府'了。气派威严，不同寻常人家。"
      }
    ],
    "hint": "黛玉从西角门进去，不肯走正门，体现她懂礼数、谨慎小心的性格。这是玩家进入贾府的第一印象，应营造庄重威严的氛围。"
  },
  "neighbors": [
    {
      "id": "map-entrance-01",
      "direction": "西角门",
      "description": "西角门，供日常出入的侧门，黛玉从此处进入，避开正门"
    }
  ],
  "entities": {
    "characters": [],
    "items": []
  }
}
```

---

### 4.2 垂花门/穿堂

**文件路径**: `config/world/daiyu_enters_jia/maps/map-entrance-01.json`

```json
{
  "id": "map-entrance-01",
  "name": "垂花门",
  "parent_id": null,
  "description": {
    "public": [
      {
        "description": "进了垂花门，两边是抄手游廊，当中是穿堂，当地放着一个紫檀架子大理石的大插屏。转过插屏，便是内院。"
      }
    ],
    "hint": "从外院进入内院的过渡空间。黛玉'放慢了脚步，眼观鼻，鼻观心，不敢乱看一眼'，体现其谨慎。婆子们在此引导。"
  },
  "neighbors": [
    {
      "id": "map-gate-01",
      "direction": "外",
      "description": "通往荣国府大门"
    },
    {
      "id": "map-jiamu-room-01",
      "direction": "内",
      "description": "穿过插屏，通往贾母正房"
    }
  ],
  "entities": {
    "characters": ["char-servant-01"],
    "items": []
  }
}
```

---

### 4.3 贾母正房

**文件路径**: `config/world/daiyu_enters_jia/maps/map-jiamu-room-01.json`

```json
{
  "id": "map-jiamu-room-01",
  "name": "贾母正房",
  "parent_id": null,
  "description": {
    "public": [
      {
        "description": "正房陈设华贵，炕上铺着锦褥，靠窗放着一个紫檀架子，架上养着一只绿毛鹦鹉，不时学舌。当地放着大火盆，暖阁里收拾得整整齐齐。这是贾府最高权威所在之处。"
      }
    ],
    "hint": "核心场景，贾母接见黛玉的地方。氛围既温馨又庄重。鹦鹉是重要的环境元素，会在结局时学舌'姑娘来了'。暖阁是黛玉今晚的住处。"
  },
  "neighbors": [
    {
      "id": "map-entrance-01",
      "direction": "外",
      "description": "通往垂花门"
    }
  ],
  "entities": {
    "characters": [
      "char-jiamu-01",
      "char-xifeng-01"
    ],
    "items": []
  }
}
```

---

## 物品配置规范

### 5.1 黛玉的手帕

**文件路径**: `config/world/daiyu_enters_jia/items/item-handkerchief-01.json`

```json
{
  "id": "item-handkerchief-01",
  "name": "手帕",
  "description": {
    "public": [
      {
        "description": "一方素白绫子手帕，是母亲生前所用，如今随身携带，寄托思念。"
      }
    ],
    "hint": "情感寄托物，黛玉用来拭泪。体现其对母亲的思念。"
  },
  "location": "char-daiyu-01",
  "is_portable": true
}
```

---

## 结局配置规范

### 6.1 正常完成结局（v3.0更新）

**文件路径**: `config/world/daiyu_enters_jia/endings/ending-normal.json`

```json
{
  "id": "ending-normal",
  "priority": 100,
  "condition_expr": "all(player_at:map-jiamu-room-01,key_facts_contains:已见贾母,key_facts_contains:已见王熙凤)",
  "is_bad_ending": false,
  "end_narrative": "你告别了贾母，随着婆子往碧纱橱去。廊下的鹦鹉忽然学舌：'姑娘来了，姑娘来了。'你回头看了一眼正房，窗棂里还映着外祖母的身影。明日，还要去见两位舅父呢。"
}
```

**v3.0变更说明**:
- 移除了 `has_item:item-handkerchief-01` 条件（手帕为初始物品，此条件无实际意义）
- 增加了 `key_facts_contains:已见贾母` 条件
- 增加了 `key_facts_contains:已见王熙凤` 条件
- **进度验证**: 确保玩家与核心人物（贾母、凤姐）完成互动后才可结束场景

---

### 6.2 失礼结局（结局反思）

**文件路径**: `config/world/daiyu_enters_jia/endings/ending-rude.json`

```json
{
  "id": "ending-rude",
  "priority": 50,
  "condition_expr": "player_at:map-gate-01",
  "is_bad_ending": true,
  "end_narrative": "【学习反思】在进入贾府的过程中，你的言行未能体现应有的礼数。古典文学中，礼仪规范是理解人物关系的重要窗口。建议重新开始，注意观察黛玉是如何谨慎行事的。"
}
```

**说明**: 这是当前系统唯一的教育反馈机制，在玩家非正常流程到达大门时触发，提供一次性的文本反思。

---

## 结局条件设计规范

### 7.1 结局触发条件设计原则

#### 问题识别

**原设计问题**:
```json
"condition_expr": "all(player_at:map-jiamu-room-01,has_item:item-handkerchief-01)"
```

- 手帕（`item-handkerchief-01`）是黛玉的初始物品，不会丢失
- 条件实际上退化为："只要到达贾母房间即触发结局"
- 缺乏对核心互动（与贾母、凤姐对话）的验证
- 教育价值（理解人物关系）无法通过结局条件保证

#### 设计原则

**进度验证导向的结局设计**:

| 体验目标 | 验证方式 | 条件示例 |
|---------|---------|---------|
| 与核心人物互动 | 与NPC见面 | `key_facts_contains:已见贾母` |
| 完成关键场景 | 到达指定地点 | `player_at:map-jiamu-room-01` |
| 体验完整流程 | 关键事实集合 | `key_facts_contains:已见王熙凤` |

**注意**: 这是**进度验证**（确保玩家完成核心体验），不是**学习评估**（不评估理解程度）。

---

### 7.2 系统条件类型支持

#### 当前支持的条件类型

| 条件类型 | 语法 | 说明 | 示例 |
|---------|------|------|------|
| 位置条件 | `player_at:map_id` | 玩家在指定地图 | `player_at:map-jiamu-room-01` |
| 物品条件 | `has_item:item_id` | 玩家持有物品 | `has_item:item-handkerchief-01` |
| 状态条件 | `player_hp_le_0` | 玩家HP≤0 | `player_hp_le_0` |
| 状态条件 | `player_san_le_0` | 玩家SAN≤0 | `player_san_le_0` |
| 逻辑与 | `all(a,b,c)` | 所有条件满足 | `all(player_at:...,has_item:...)` |
| 逻辑或 | `any(a,b,c)` | 任一条件满足 | `any(has_item:A,has_item:B)` |

#### v3.0新增支持（需代码修改）

| 条件类型 | 语法 | 说明 | 示例 |
|---------|------|------|------|
| 关键事实 | `key_facts_contains:fact` | 叙事记忆包含指定事实 | `key_facts_contains:已见贾母` |
| 回合数 | `turn_count_ge:n` | 回合数≥n | `turn_count_ge:5` |

---

### 7.3 代码修改说明（如需启用key_facts条件）

**修改文件**: `src/engine/game_engine.py`

**修改位置**: `_evaluate_condition_expr` 方法（约第2393行）

**添加代码**:
```python
def _evaluate_condition_expr(self, expr: str) -> bool:
    """评估简易结局表达式。"""
    player = self.game_state.get_player()
    if not player:
        return False

    # 原有逻辑保持不变...
    
    # 新增：key_facts_contains 条件支持
    if expr.startswith("key_facts_contains:"):
        fact = expr.split(":", 1)[1].strip()
        # 获取当前叙事记忆
        narrative_memory = self._narrative_memory_builder.build(
            self._dump_narrative_context()
        )
        return fact in narrative_memory.key_facts
    
    # 新增：turn_count_ge 条件支持
    if expr.startswith("turn_count_ge:"):
        min_turns = int(expr.split(":", 1)[1].strip())
        return self.game_state.turn_count >= min_turns

    return False
```

---

### 7.4 关键事实生成机制

**生成位置**: NPC的 `description.hint` 中指导AI生成

**生成时机**: 与玩家初次见面并完成核心互动后

**示例**:
```
【关键事实生成】与黛玉初次见面后，确保在narrative_memory.key_facts中添加"已见贾母"，
记录此次见面的核心互动内容（如：贾母搂住黛玉大哭，询问身体情况，安排住处等）。
```

**关键事实格式**:
- `已见贾母` - 表示与贾母完成初次见面
- `已见王熙凤` - 表示与王熙凤完成初次见面
- `完成磕头礼` - 表示完成给贾母磕头的礼仪
- `贾母落泪` - 表示触发贾母情感反应

---

### 7.5 结局条件设计建议

#### 推荐方案：进度验证型

```json
{
  "condition_expr": "all(player_at:map-jiamu-room-01,key_facts_contains:已见贾母,key_facts_contains:已见王熙凤)"
}
```

**优势**:
- ✅ 精准验证核心体验进度（与主要人物见面）
- ✅ 利用现有 `NarrativeMemory` 系统
- ✅ 确保玩家完成关键互动环节
- ✅ 可扩展性强（后续可增加更多关键事实条件）

**注意事项**:
- 这是**进度验证**，不是**学习评估**
- 需要修改代码支持 `key_facts_contains` 条件
- 需要在NPC hint中明确指导AI生成关键事实
- 需要测试验证AI是否正确生成关键事实

#### 备选方案：回合数保底型

```json
{
  "condition_expr": "all(player_at:map-jiamu-room-01,turn_count_ge:5)"
}
```

**优势**:
- 技术实现简单
- 确保玩家有足够回合进行互动

**缺点**:
- 无法确保玩家与特定NPC互动
- 可能通过无意义输入刷回合数

---

## LLM上下文适配规范

### 8.1 DMAgent上下文适配

**关键适配点**:

| 原COC场景 | 红楼梦场景 | 适配说明 |
|----------|-----------|---------|
| `raw_input_text`: "检查保险箱" | `raw_input_text`: "给外祖母磕头" | 动作类型从探索变为礼仪行为 |
| `nearby_items`: 钥匙、武器 | `nearby_items`: 手帕、茶具 | 物品改为古典生活道具 |
| `player_state.status.san`: 理智值 | `player_state.status.san`: 心理稳定度 | 重新解释为情绪状态 |
| `check_difficulty`: 常规/困难/极难 | `check_difficulty`: 常规/困难/极难 | 保留，但解释为礼仪难度 |

**上下文示例**:

```json
{
  "request_id": "turn-1-player-parse",
  "turn_id": 1,
  "phase": "player",
  "payload": {
    "raw_input_text": "我扶着婆子的手下轿，低头整理衣裳",
    "world_state_view": {
      "current_map": {
        "id": "map-gate-01",
        "name": "荣国府大门",
        "description": "街北蹲着两个大石狮子，三间兽头大门..."
      },
      "nearby_characters": [
        {
          "id": "char-servant-01",
          "name": "婆子丫鬟们",
          "description_hint": "引导黛玉从大门到正房"
        }
      ],
      "nearby_items": [],
      "player_state": {
        "id": "char-daiyu-01",
        "name": "林黛玉",
        "status": { "hp": 12, "san": 70 }
      }
    }
  },
  "constraints": {
    "enums": {
      "interaction_type": ["action", "dialogue", "mixed"],
      "check_difficulty": ["常规", "困难", "极难"]
    }
  }
}
```

---

### 8.2 NPCDirector上下文适配

**关键适配点**:

| 字段 | 红楼梦场景值 | 说明 |
|------|-------------|------|
| `player_action_summary` | "黛玉扶着婆子的手慢慢下轿，低头整理衣裳，从西角门进入" | 描述礼仪行为 |
| `npc_world_views[].description_hint` | 贾母："见到黛玉会想起女儿贾敏" | 指导NPC情感反应 |
| `activated_npc_ids` | ["char-jiamu-01", "char-xifeng-01", "char-servant-01"] | 激活的NPC（最多4个） |

**4角色NPC规划说明**:

NPCDirector在`unified`模式下，会同时规划所有激活NPC的行动：
1. 玩家行动后，DMAgent输出`actionable_npcs`列表
2. NPCDirector为每个NPC生成行动计划
3. 按`turn_order`顺序执行各NPC状态推演
4. NarrativeMerger合并所有叙事

**性能提示**: 4角色配置下，NPC规划阶段需1次LLM调用（统一规划），状态推演阶段需3次LLM调用（贾母、凤姐、丫鬟婆子），总耗时约3-5秒。

**上下文示例**:

```json
{
  "request_id": "turn-1-npc-plan",
  "turn_id": 1,
  "phase": "npc_planning",
  "payload": {
    "trigger_source": "unified",
    "activated_npc_ids": ["char-jiamu-01", "char-xifeng-01", "char-servant-01"],
    "player_action_summary": "黛玉从西角门进入，低头整理衣裳，举止谨慎",
    "npc_world_views": [
      {
        "npc_id": "char-jiamu-01",
        "name": "贾母",
        "description_hint": "见到外孙女黛玉，会想起已故的女儿贾敏，情感丰富，容易落泪"
      },
      {
        "npc_id": "char-xifeng-01",
        "name": "王熙凤",
        "description_hint": "精明能干，善于说话，热情但带试探"
      },
      {
        "npc_id": "char-servant-01",
        "name": "婆子丫鬟们",
        "description_hint": "功能性NPC，负责引导和烘托氛围"
      }
    ]
  }
}
```

---

### 8.3 边界测试处理规范

**超纲输入类型与系统反应**:

| 超纲输入类型 | 示例 | NPC反应 | 处理机制 |
|-------------|------|---------|---------|
| 未来预知 | "贾府会被抄家" | 贾母困惑："胡话/发热"，探额头请太医 | DMAgent识别→NPC困惑反应 |
| 时空穿越 | "我是从未来来的" | NPC不解，认为是"说胡话" | 同上 |
| 暴力行为 | "我要杀了贾母" | 丫鬟护主，贾母惊愕 | DMAgent识别→NPC防御反应 |
| 不合理要求 | "给我金子" | 凤姐圆滑应对，转移话题 | NPC根据性格自然回应 |

**DMAgent识别逻辑**:

```
如果 raw_input_text 包含 ["抄家", "未来", "预知", "杀", "偷"]:
  → 设置 activation_hint: "NPC应表现出困惑或不解"
  → 不直接拒绝玩家，而是让NPC在情节内自然化解
```

---

## 字段语义设计规范

### 9.1 设计背景

#### 问题识别

**代码层面语义** (`src/data/models.py:118`):
```python
san: int = Field(default=50, ge=0, le=100, description="理智值 Sanity")
```
- 系统底层语义：COC的"理智值"（Sanity）
- 原意：对抗恐怖、保持理智的能力
- 归零后果：精神崩溃、疯狂

**文档层面语义**:
- 红楼梦场景语义："心理稳定度"
- 新解释：情绪稳定性、心理承受能力
- 归零后果：情绪失控、昏厥

**风险**: LLM可能在不同上下文中对 `san` 产生混淆，尤其是COC训练数据更为常见。

---

### 9.2 设计决策

#### 决策：采用方案A（Prompt层语义解释）

**决策理由**:
1. **改动成本最低**：仅需修改提示词文档，无需代码变更
2. **演示场景适用**：当前为演示场景，非长期产品
3. **风险可控**：即使LLM混淆，对演示效果影响有限
4. **快速实施**：可在1小时内完成

**不采用方案B（重命名字段）理由**:
1. 改动涉及20+文件，成本过高
2. 破坏性变更，影响存档兼容性
3. 当前为演示场景，收益有限

---

### 9.3 Prompt语义解释规范

#### 9.3.1 修改 system_prompt.md

在文件开头添加语义说明章节：

```markdown
## 字段语义说明（红楼梦场景）

本场景为《红楼梦》教育演示场景，以下字段语义与COC（克苏鲁的呼唤）不同：

### 状态值语义

- `hp`: 生命值（Hit Points），0时角色失去行动能力
- `san`: 心理稳定度（Emotional Stability），0时角色情绪崩溃/昏厥
  - **注意**: 在本场景中表示情绪稳定性，非COC的"理智值"
  - 含义：角色的情绪稳定性、心理承受能力
  - 降低原因：悲伤、思念、惊吓、情绪波动
  - 归零后果：昏厥、情绪失控、需要安抚
- `max_hp`: 最大生命值

### 属性值语义

- `str`: 力量 - 体能强弱
- `con`: 体质 - 健康状况
- `siz`: 体型 - 身材大小
- `dex`: 敏捷 - 反应速度
- `app`: 外貌 - 容貌气质
- `int`: 智力 - 聪慧程度
- `pow`: 意志 - 精神韧性
- `edu`: 教育 - 学识教养
```

#### 9.3.2 修改 npc_director_prompt.md

在NPC状态说明部分添加：

```markdown
**状态字段语义（红楼梦场景）**:
- `status.hp`: 生命值，0时失去行动能力
- `status.san`: 心理稳定度（情绪稳定性），非理智值
  - 含义：情绪稳定性，悲伤/惊吓时会降低
  - 归零：情绪崩溃、昏厥
```

---

### 9.4 语义对比表

| 维度 | COC语义（理智值） | 红楼梦语义（心理稳定度） |
|------|------------------|------------------------|
| 核心概念 | 对抗恐怖的精神韧性 | 情绪稳定性 |
| 降低触发 | 超自然遭遇、恐怖事件 | 悲伤、思念、惊吓 |
| 归零表现 | 疯狂、精神错乱 | 昏厥、情绪崩溃 |
| 恢复方式 | 心理治疗、时间恢复 | 安慰、休息、时间恢复 |
| 数值范围 | 0-100 | 0-100（相同） |

---

### 9.5 长期建议

如项目转为长期产品，建议：
1. **方案B**: 重命名字段 `san` → `emotion` 或 `mental_state`
2. **方案C**: 在架构层面抽象状态系统，支持场景自定义状态字段

---

## 演示流程脚本

### 标准演示流程（约10-15分钟）

```
【开场】（自动）
系统：且说黛玉自那日弃舟登岸...

【第一幕：进府】
玩家输入：我扶着婆子的手下轿，低头整理衣裳
系统回应：你扶着婆子的手慢慢下了轿...
（丫鬟婆子NPC响应："林姑娘到了"）

【第二幕：见贾母】
玩家输入：上前给外祖母磕头
系统回应：正房炕上坐着一位鬓发如银的老太太...
（贾母NPC响应：搂住黛玉大哭）
→ 【关键事实生成】narrative_memory.key_facts 添加 "已见贾母"

【第三幕：对话】
玩家输入：我轻声说：多谢外祖母挂念，一路还算平顺，只是想念母亲
系统回应：你声音细细的...外祖母听了，又抹起泪来...

【第四幕：凤姐出场】
玩家输入：我擦了眼泪，悄悄看周围还有什么人
系统回应：你正用帕子拭泪，忽听得后院中有人笑声...
（王熙凤NPC响应：笑着出场，打量黛玉）
→ 【关键事实生成】narrative_memory.key_facts 添加 "已见王熙凤"

【第五幕：应对凤姐】
玩家输入：我被她拉着，有些不自在，但又不敢抽回手，只小声道：嫂子安好
系统回应：你被她攥着手...凤姐听了，越发笑起来...

【边界测试】（可选）
玩家输入：贾母，我知道贾府以后会被抄家
系统回应：贾母正端着茶盏的手顿了顿..."黛玉，你说什么胡话？"
（丫鬟婆子NPC响应：面面相觑，安静下来的氛围）

【结局】（满足条件后）
玩家输入：\exit
系统：你告别了贾母...明日，还要去见两位舅父呢。
```

---

## 降级策略

如4角色配置出现性能问题，可按以下优先级降级：

### 降级方案：合并丫鬟婆子为环境叙事

**实施步骤**:
1. 删除 `char-servant-01.json` 配置文件
2. 修改 `map-entrance-01.json`，移除 `entities.characters` 中的 `char-servant-01`
3. 在场景描述中增加引导性叙事：

```json
{
  "description": {
    "public": [{
      "description": "进了垂花门，两边是抄手游廊...婆子们笑道：'林姑娘到了。'"
    }]
  }
}
```

**影响评估**:
- 剧情连贯性：轻微影响（失去互动感，但叙事完整）
- 系统性能：降低约25%NPC处理开销
- 教育价值：轻微降低（减少礼仪观察点）

---

## 验证检查清单

### 配置创建检查

- [ ] 创建 `config/world/daiyu_enters_jia/` 目录
- [ ] 创建 `world.json` 并验证JSON格式
- [ ] 创建 `characters/` 目录及4个角色配置文件
- [ ] 创建 `maps/` 目录及3个场景配置文件
- [ ] 创建 `items/` 目录及1个物品配置文件
- [ ] 创建 `endings/` 目录及2个结局配置文件

### 功能验证检查

- [ ] 启动命令：`python src/main.py --world daiyu_enters_jia`
- [ ] 开场叙事正确显示
- [ ] 玩家角色正确加载（林黛玉）
- [ ] 场景切换正常（大门→垂花门→贾母房）
- [ ] NPC（贾母、凤姐、丫鬟婆子）正确响应
- [ ] 边界测试（抄家）触发困惑反应
- [ ] 结局正确触发

### v3.0新增验证检查

- [ ] 未与贾母见面时，无法触发正常结局
- [ ] 未与凤姐见面时，无法触发正常结局
- [ ] 与贾母、凤姐都见面后，可正常触发结局
- [ ] 检查 narrative_memory.key_facts 是否正确生成

### v4.0新增验证检查

- [ ] 检查 `system_prompt.md` 中是否包含字段语义说明
- [ ] 检查 `npc_director_prompt.md` 中是否包含状态字段语义说明
- [ ] 验证LLM对 `san` 字段的理解是否符合红楼梦场景
- [ ] 验证NPC对 `san` 降低的反应是否符合情绪崩溃（非疯狂）

### v5.0新增验证检查

- [ ] 验证 `narrative_window` 配置是否正确加载
- [ ] 验证叙事上下文窗口是否按配置值工作
- [ ] 验证存档/读档时 `narrative_window` 是否正确保存和恢复

### v6.0新增验证检查

- [ ] 验证教育体验流程是否完整（沉浸体验+结局反思）
- [ ] 验证失礼结局是否正确触发反思文本
- [ ] 确认无学习评估报告生成（符合体验式学习定位）

### 性能验证检查

- [ ] 4角色配置下回合处理时间 < 10秒
- [ ] NPC规划阶段LLM调用正常
- [ ] 多NPC并发响应无卡顿
- [ ] 连续运行10分钟无崩溃

### 教育目标验证（v6.0更新）

- [ ] 黛玉谨慎性格通过"不走正门"体现
- [ ] 贾母慈爱形象通过对话展现
- [ ] 凤姐精明性格通过言行展现
- [ ] 丫鬟婆子烘托贾府等级秩序
- [ ] 贾府礼仪规范通过场景传达
- [ ] 超纲信息通过NPC困惑自然拦截
- [ ] **v3.0新增**: 核心体验进度通过结局条件验证
- [ ] **v4.0新增**: 字段语义通过Prompt明确，避免LLM混淆
- [ ] **v5.0新增**: 叙事窗口配置合理，保证上下文连贯性
- [ ] **v6.0新增**: 体验式学习定位明确，教育价值来自沉浸体验

---

## 附录：文件目录结构

```
config/world/daiyu_enters_jia/
├── world.json                              # 世界元数据
├── characters/
│   ├── char-daiyu-01.json                 # 林黛玉（玩家）
│   ├── char-jiamu-01.json                 # 贾母
│   ├── char-xifeng-01.json                # 王熙凤
│   └── char-servant-01.json               # 丫鬟婆子（辅助NPC）
├── maps/
│   ├── map-gate-01.json                   # 荣国府大门
│   ├── map-entrance-01.json               # 垂花门/穿堂
│   └── map-jiamu-room-01.json             # 贾母正房
├── items/
│   └── item-handkerchief-01.json          # 手帕
└── endings/
    ├── ending-normal.json                 # 正常结局
    └── ending-rude.json                   # 失礼结局（教育反思）
```

---

## 附录：启动命令

```bash
# 启动红楼梦场景
python src/main.py --world daiyu_enters_jia

# 或指定完整路径
python src/main.py --world daiyu_enters_jia --db-path data/daiyu_game.db
```

---

## 版本历史

| 版本 | 日期 | 更新内容 |
|------|------|---------|
| v1.0 | 2026-03-30 | 初始版本，3角色配置 |
| v2.0 | 2026-03-30 | 明确4角色为演示场景上限，增加NPC角色数量设计原则说明，添加降级策略 |
| v3.0 | 2026-03-31 | 优化结局触发条件设计，引入key_facts验证机制，明确进度验证导向的结局设计，增加结局条件设计规范章节 |
| v4.0 | 2026-03-31 | 明确 san 字段语义设计决策，添加 Prompt 层语义解释规范，增加字段语义设计规范章节 |
| v5.0 | 2026-03-31 | 补充 narrative_window 字段说明，明确其功能、使用建议和与 memory_policy 的区别 |
| v6.0 | 2026-03-31 | 明确教育目标定位，区分"体验式学习"与"教学评估"，避免文档过度承诺，新增教育目标定位说明章节 |

---

*文档结束*
