# 🎮 游戏引擎 - 开发者配置模板表单

本模板供游戏开发者使用引擎进行开发，创建属于自己的游戏世界。

---

## 📁 1. 世界配置 (World)

**文件路径**: `config/world/<world_name>/world.json`

```json
{
  "world_id": "world-<world_name>",
  "world_name": "<world_name>",
  "player_id": "char-player-01",
  "start_map_id": "map-room-01",
  "turn_order": [
    "char-player-01",
    "char-npc-01",
    "char-npc-02"
  ],
  "narrative_window": 5,
  "npc_response_mode": "reactive",
  "npc_director_use_llm": true,
  "narrative_merge_use_llm": true,
  "end_condition": "游戏结束条件描述...",
  "entry_scene_narrative": "游戏开始时的场景叙事..."
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `world_id` | string | ✅ | 世界唯一标识符，格式: `world-<name>` |
| `world_name` | string | ✅ | 世界显示名称 |
| `player_id` | string | ✅ | 玩家角色ID（必须在characters目录中存在） |
| `start_map_id` | string | ✅ | 玩家初始所在地图ID |
| `turn_order` | array | ✅ | 回合顺序数组，列出所有角色ID |
| `narrative_window` | int | ✅ | 叙事记忆窗口大小 |
| `npc_response_mode` | string | ✅ | NPC响应模式: `reactive` / `proactive` |
| `npc_director_use_llm` | boolean | ✅ | NPC导演是否使用LLM |
| `narrative_merge_use_llm` | boolean | ✅ | 叙事合并是否使用LLM |
| `end_condition` | string | - | 游戏结束条件描述 |
| `entry_scene_narrative` | string | ✅ | 游戏入口场景叙事文本 |

---

## 👤 2. 人物配置 (Character)

**文件路径**: `config/world/<world_name>/characters/char-<id>.json`

### 玩家角色模板

```json
{
  "id": "char-player-01",
  "name": "<角色名称>",
  "basic_info": "角色的一句话背景介绍...",
  "description": {
    "public": [
      {
        "description": "角色的外观描述..."
      }
    ],
    "hint": "角色的背景、动机、特点提示（DM可见）..."
  },
  "location": "map-room-01",
  "inventory": [],
  "status": {
    "hp": 20,
    "max_hp": 20,
    "san": 60,
    "lucky": 50
  },
  "attributes": {
    "str": 20,
    "con": 20,
    "siz": 20,
    "dex": 20,
    "app": 20,
    "int": 20,
    "pow": 20,
    "edu": 20
  },
  "memory": {
    "current_event": "",
    "log": []
  },
  "is_player": true
}
```

### NPC角色模板

```json
{
  "id": "char-npc-01",
  "name": "<NPC名称>",
  "basic_info": "NPC的一句话背景介绍...",
  "description": {
    "public": [
      {
        "description": "NPC的外观描述..."
      }
    ],
    "hint": "NPC的性格、动机、秘密提示..."
  },
  "location": "map-room-01",
  "inventory": [
    "item-xxx-01"
  ],
  "status": {
    "hp": 10,
    "max_hp": 10,
    "san": 45,
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
    "edu": 10
  },
  "memory": {
    "current_event": "",
    "log": []
  },
  "is_player": false
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | ✅ | 角色唯一ID，格式: `char-<type>-<number>` |
| `name` | string | ✅ | 角色显示名称 |
| `basic_info` | string | ✅ | 角色基本信息（一句话描述） |
| `description.public` | array | ✅ | 角色公开描述数组 |
| `description.public[].description` | string | ✅ | 角色外观描述 |
| `description.hint` | string | - | 角色背景/动机提示（DM可见） |
| `location` | string | ✅ | 角色当前位置地图ID |
| `inventory` | array | - | 角色携带物品ID列表 |
| `status.hp` | int | ✅ | 当前生命值 |
| `status.max_hp` | int | ✅ | 最大生命值 |
| `status.san` | int | ✅ | 理智值 |
| `status.lucky` | int | ✅ | 幸运值 |
| `attributes.str` | int | ✅ | 力量 |
| `attributes.con` | int | ✅ | 体质 |
| `attributes.siz` | int | ✅ | 体型 |
| `attributes.dex` | int | ✅ | 敏捷 |
| `attributes.app` | int | ✅ | 外貌 |
| `attributes.int` | int | ✅ | 智力 |
| `attributes.pow` | int | ✅ | 意志 |
| `attributes.edu` | int | ✅ | 教育 |
| `memory.current_event` | string | - | 当前事件 |
| `memory.log` | array | - | 记忆日志 |
| `is_player` | boolean | ✅ | 是否为玩家角色 |

---

## 🗺️ 3. 房间/地图配置 (Map)

**文件路径**: `config/world/<world_name>/maps/map-<id>.json`

### 房间模板

```json
{
  "id": "map-room-01",
  "name": "<房间名称>",
  "parent_id": "map-area-01",
  "description": {
    "public": [
      {
        "description": "房间的环境描述..."
      }
    ],
    "hint": "房间的秘密、隐藏线索、互动提示..."
  },
  "neighbors": [
    {
      "id": "map-room-02",
      "direction": "北",
      "description": "出口描述..."
    }
  ],
  "entities": {
    "characters": [
      "char-npc-01"
    ],
    "items": [
      "item-xxx-01",
      "item-xxx-02"
    ]
  }
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | ✅ | 地图唯一ID，格式: `map-room-<name>-<number>` |
| `name` | string | ✅ | 地图显示名称 |
| `parent_id` | string | ✅ | 父区域ID |
| `description.public` | array | ✅ | 房间公开描述数组 |
| `description.public[].description` | string | ✅ | 房间环境描述 |
| `description.hint` | string | - | 房间秘密/提示（DM可见） |
| `neighbors` | array | ✅ | 相邻房间数组 |
| `neighbors[].id` | string | ✅ | 相邻房间ID |
| `neighbors[].direction` | string | ✅ | 方向: 北/南/东/西/上/下 |
| `neighbors[].description` | string | ✅ | 出口描述 |
| `entities.characters` | array | - | 场景中存在的角色ID |
| `entities.items` | array | - | 场景中存在的物品ID |

---

## 📦 4. 物品配置 (Item)

**文件路径**: `config/world/<world_name>/items/item-<id>.json`

### 物品模板

```json
{
  "id": "item-xxx-01",
  "name": "<物品名称>",
  "description": {
    "public": [
      {
        "description": "物品的外观描述..."
      }
    ],
    "hint": "物品的用途、背景故事、隐藏线索..."
  },
  "location": "map-room-01",
  "is_portable": true
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | ✅ | 物品唯一ID，格式: `item-<name>-<number>` |
| `name` | string | ✅ | 物品显示名称 |
| `description.public` | array | ✅ | 物品公开描述数组 |
| `description.public[].description` | string | ✅ | 物品外观描述 |
| `description.hint` | string | - | 物品用途/秘密提示 |
| `location` | string | ✅ | 物品位置: 地图ID 或 角色ID |
| `is_portable` | boolean | ✅ | 是否可拾取携带 |

---

## 🏁 5. 结局配置 (Ending)

**文件路径**: `config/world/<world_name>/endings/ending-<id>.json`

### 结局模板

```json
{
  "id": "ending-xxx",
  "priority": 100,
  "condition_expr": "all(player_at:map-room-01,has_item:item-xxx-01)",
  "is_bad_ending": false,
  "end_narrative": "结局叙事文本..."
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | ✅ | 结局唯一ID，格式: `ending-<name>` |
| `priority` | int | ✅ | 优先级（数字越大优先级越高，用于多条件同时满足时选择） |
| `condition_expr` | string | ✅ | 触发条件表达式 |
| `is_bad_ending` | boolean | ✅ | 是否为坏结局 |
| `end_narrative` | string | ✅ | 结局叙事文本 |

### 条件表达式语法

| 语法 | 说明 | 示例 |
|------|------|------|
| `player_at:<map_id>` | 玩家在指定地图 | `player_at:map-room-01` |
| `has_item:<item_id>` | 玩家持有指定物品 | `has_item:item-xxx-01` |
| `player_hp_le_0` | 玩家HP≤0（死亡） | `player_hp_le_0` |
| `all(...)` | 所有条件同时满足 | `all(player_at:...,has_item:...)` |
| `any(...)` | 任一条件满足 | `any(has_item:A,has_item:B)` |

---

## 📂 6. 完整目录结构

```
config/world/<world_name>/
├── world.json              # 世界配置
├── characters/
│   ├── char-player-01.json # 玩家角色
│   ├── char-npc-01.json    # NPC角色
│   └── char-npc-02.json    # NPC角色
├── maps/
│   ├── map-room-01.json    # 房间
│   ├── map-room-02.json    # 房间
│   ├── map-room-03.json    # 房间
│   └── map-room-xx.json    # 更多房间
├── items/
│   ├── item-xxx-01.json    # 物品
│   ├── item-xxx-02.json    # 物品
│   └── item-xxx-xx.json    # 更多物品
└── endings/
    ├── ending-xxx.json     # 结局
    ├── ending-yyy.json     # 结局
    └── ending-zzz.json     # 结局
```

---

## 🔧 快速创建新世界检查清单

- [ ] 创建 `config/world/<新世界名>/` 目录
- [ ] 创建 `world.json` 配置世界基本信息
- [ ] 创建 `characters/` 目录，至少包含1个玩家角色
- [ ] 创建 `maps/` 目录，至少包含1个起始房间
- [ ] 创建 `items/` 目录（可选）
- [ ] 创建 `endings/` 目录，至少包含1个结局
- [ ] 确保所有ID唯一且格式正确
- [ ] 验证 JSON 语法正确性
