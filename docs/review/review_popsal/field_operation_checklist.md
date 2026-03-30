# 状态变更字段与操作类型检查清单

本文档用于LLM输出JSON变更列表的合规性检查,确保`field`路径和`operation`操作类型的组合正确。

---

## 📋 变更操作类型定义

| 操作 | 含义 | 适用场景 |
|------|------|---------|
| `update` | 更新字段值 | 标量字段(字符串、数字、布尔值) |
| `add` | 向列表添加元素 | 列表类型字段 |
| `del` | 删除列表元素或字段 | 列表类型字段删除元素 |

---

## 🎯 实体字段操作规范

### 1. Character (角色) 字段

#### 1.1 标量字段 - 使用 `update`
| 字段路径 | 类型 | 示例值 | 说明 |
|---------|------|--------|------|
| `name` | str | `"张三"` | 角色名称 |
| `basic_info` | str | `"图书管理员"` | 基本信息 |
| `location` | str | `"map-room-library-01"` | 当前位置(地图ID) |

#### 1.2 状态字段 - 使用 `update`
| 字段路径 | 类型 | 示例值 | 说明 |
|---------|------|--------|------|
| `status.hp` | int | `8` | 生命值 |
| `status.max_hp` | int | `10` | 最大生命值 |
| `status.san` | int | `45` | 理智值 |
| `status.lucky` | int | `50` | 幸运值 |

#### 1.3 属性字段 - 使用 `update`
| 字段路径 | 类型 | 示例值 | 说明 |
|---------|------|--------|------|
| `attributes.str` | int | `12` | 力量 |
| `attributes.con` | int | `10` | 体质 |
| `attributes.siz` | int | `11` | 体型 |
| `attributes.dex` | int | `14` | 敏捷 |
| `attributes.app` | int | `10` | 外貌 |
| `attributes.int` | int | `13` | 智力 |
| `attributes.pow` | int | `12` | 意志 |
| `attributes.edu` | int | `15` | 教育 |

#### 1.4 列表字段 - 使用 `add` / `del`
| 字段路径 | 操作 | value格式 | 说明 |
|---------|------|-----------|------|
| `inventory` | `add` | `"item-key-01"` | 添加物品到背包 |
| `inventory` | `del` | `"item-lantern-01"` | 从背包移除物品 |
| `description.public` | `add` | `{"description": "左臂受伤"}` | 添加公开描述 |
| `memory.log` | `add` | `"遭遇了深潜者"` | 添加记忆日志 |

#### 1.5 ❌ 不支持的操作
| 字段路径 | 错误操作 | 原因 |
|---------|---------|------|
| `description.public` | `update` | 会破坏列表结构,必须使用`add`追加 |
| `inventory` | `update` | 应该用`add`/`del`而不是替换整个列表 |
| `status` | `update` | 不能直接更新整个对象,必须指定子字段 |

---

### 2. Item (物品) 字段

#### 2.1 标量字段 - 使用 `update`
| 字段路径 | 类型 | 示例值 | 说明 |
|---------|------|--------|------|
| `name` | str | `"古老的钥匙"` | 物品名称 |
| `location` | str | `"char-player-01"` / `"map-room-01"` | 位置(角色ID或地图ID) |
| `is_portable` | bool | `true` / `false` | 是否可携带 |

#### 2.2 列表字段 - 使用 `add`
| 字段路径 | 操作 | value格式 | 说明 |
|---------|------|-----------|------|
| `description.public` | `add` | `{"description": "封面上有抓痕"}` | 添加物品描述 |

---

### 3. Map (地图) 字段

#### 3.1 标量字段 - 使用 `update`
| 字段路径 | 类型 | 示例值 | 说明 |
|---------|------|--------|------|
| `name` | str | `"图书馆大厅"` | 地图名称 |
| `parent_id` | str/null | `"map-building-01"` | 父级区域ID |

#### 3.2 列表字段 - 使用 `add`
| 字段路径 | 操作 | value格式 | 说明 |
|---------|------|-----------|------|
| `neighbors` | `add` | `{"id": "map-room-02", "direction": "东", "description": "一扇木门"}` | 添加邻居连接 |
| `entities.characters` | `add` | `"char-guard-01"` | 添加角色到地图 |
| `entities.items` | `add` | `"item-book-01"` | 添加物品到地图 |

#### 3.3 删除操作 - 使用 `del`
| 字段路径 | 操作 | value格式 | 说明 |
|---------|------|-----------|------|
| `entities.characters` | `del` | `"char-npc-01"` | 从地图移除角色 |
| `entities.items` | `del` | `"item-key-01"` | 从地图移除物品 |

---

## ✅ 正确示例

```json
// 角色状态更新 - 正确
{"id": "char-player-01", "field": "status.hp", "operation": "update", "value": 8}
{"id": "char-player-01", "field": "location", "operation": "update", "value": "map-room-02"}

// 背包操作 - 正确
{"id": "char-player-01", "field": "inventory", "operation": "add", "value": "item-key-01"}
{"id": "char-player-01", "field": "inventory", "operation": "del", "value": "item-lantern-01"}

// 描述追加 - 正确(使用add追加到列表)
{"id": "char-player-01", "field": "description.public", "operation": "add", "value": {"description": "左臂受伤"}}
{"id": "item-book-01", "field": "description.public", "operation": "add", "value": {"description": "封面上有抓痕"}}

// 地图实体操作 - 正确
{"id": "map-room-01", "field": "entities.characters", "operation": "add", "value": "char-guard-01"}
{"id": "map-room-01", "field": "entities.items", "operation": "del", "value": "item-key-01"}
```

---

## ❌ 错误示例

```json
// 错误1: description.public 使用 update(会破坏列表)
{"id": "char-player-01", "field": "description.public", "operation": "update", "value": "受伤"}

// 错误2: inventory 使用 update(应该用 add/del)
{"id": "char-player-01", "field": "inventory", "operation": "update", "value": ["item-01"]}

// 错误3: status 直接更新对象
{"id": "char-player-01", "field": "status", "operation": "update", "value": {"hp": 8}}

// 错误4: add 操作 value 不是单个元素
{"id": "char-player-01", "field": "inventory", "operation": "add", "value": ["item-01", "item-02"]}
```

---

## 🔍 审查检查项

### 自动检查规则

1. **字段存在性检查**
   - [ ] `id` 必须在 game_state.characters/items/maps 中存在
   - [ ] `field` 必须是实体模型的有效字段路径

2. **操作类型检查**
   - [ ] 标量字段(str/int/bool) 必须使用 `update`
   - [ ] 列表字段 必须使用 `add` 或 `del`
   - [ ] 嵌套对象字段(如 `status`) 不能直接操作,必须指定子字段

3. **Value格式检查**
   - [ ] `add` 操作的 `value` 必须是单个元素(不是列表)
   - [ ] `description.public` 的 `value` 必须是 `{"description": "..."}` 格式
   - [ ] `location` 更新值必须是存在的地图ID或角色ID
   - [ ] `inventory` add/del 的值必须是存在的物品ID

4. **业务逻辑检查**
   - [ ] 物品转移时,原持有者和新持有者的 inventory 都要更新
   - [ ] 角色移动时,旧地图和新地图的 entities.characters 都要更新
   - [ ] HP/SAN 更新时,数值范围要合理(HP >= 0, 0 <= SAN <= 100)

---

## 📊 快速参考表

| 实体 | 字段模式 | 操作 | value类型 |
|------|---------|------|-----------|
| Character | `status.*` | update | int |
| Character | `attributes.*` | update | int |
| Character | `location` | update | str(地图ID) |
| Character | `inventory` | add/del | str(物品ID) |
| Character | `description.public` | add | `{"description": str}` |
| Item | `location` | update | str(角色ID/地图ID) |
| Item | `description.public` | add | `{"description": str}` |
| Map | `entities.characters` | add/del | str(角色ID) |
| Map | `entities.items` | add/del | str(物品ID) |
| Map | `neighbors` | add | `{"id": str, "direction": str, "description": str}` |
