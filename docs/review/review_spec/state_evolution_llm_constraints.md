# StateEvolution LLM 状态变更限制规范

## 1. 概述

本文档定义了 StateEvolution Agent 在生成状态变更 (state_changes) 时必须遵守的字段级操作限制。目的是防止 LLM 产生不符合数据模型约束的变更，减少运行时错误和数据不一致。

## 2. 核心原则

### 2.1 操作类型与字段类型的匹配规则

| 操作类型 | 适用字段类型 | 禁止场景 |
|---------|-------------|---------|
| `update` | 标量字段、整个对象替换 | 向列表追加元素（应使用 `add`） |
| `add` | 仅列表类型字段 | 标量字段、非列表对象 |
| `del` | 仅特定白名单列表字段 | 标量字段、非白名单列表 |
| `move` | 仅 `location` 字段 | 其他所有字段 |

### 2.2 字段分类体系

#### 2.2.1 标量字段（Scalar Fields）
- 类型：字符串、整数、布尔值、浮点数
- 操作限制：**仅允许 `update`**
- 示例：`name`, `basic_info`, `status.hp`, `status.san`, `location`（特殊处理见下文）

#### 2.2.2 列表字段（List Fields）
- 类型：`List[T]`
- 操作限制：**允许 `update`（整体替换）、`add`（追加）、`del`（删除）**
- 示例：`inventory`, `description.public`, `neighbors`, `entities.items`

#### 2.2.3 复合对象字段（Object Fields）
- 类型：`BaseModel` 子类
- 操作限制：**仅允许 `update`（整体替换）或子字段点分路径**
- 示例：`status`, `attributes`, `description`, `entities`

#### 2.2.4 特殊字段（Special Fields）
- `location`: 位置字段，**必须使用 `move` 操作**
- `description.public`: 描述列表，**必须使用 `add` 追加，禁止整体替换**

---

## 3. 实体字段限制矩阵

### 3.1 Character（角色）

| 字段路径 | 字段类型 | 允许操作 | 特殊限制 |
|---------|---------|---------|---------|
| `name` | 字符串 | `update` | 非空校验 |
| `basic_info` | 字符串 | `update` | 无 |
| `location` | 字符串 | `move` | 目标必须是地图ID（map-xxx） |
| `description.public` | 列表 | `add` | 推荐，追加描述 |
| `description.public` | 列表 | `update` | 允许但需谨慎（整体替换） |
| `description.hint` | 字符串 | `update` | 仅AI可见，谨慎修改 |
| `inventory` | 列表 | `add`, `del` | 值必须是存在的 item-id |
| `status.hp` | 整数 | `update` | 范围 0-max_hp |
| `status.max_hp` | 整数 | `update` | 通常不修改 |
| `status.san` | 整数 | `update` | 范围 0-100 |
| `status.lucky` | 整数 | `update` | 范围 1-99 |
| `attributes.str` | 整数 | `update` | 范围 1-99 |
| `attributes.con` | 整数 | `update` | 范围 1-99 |
| `attributes.siz` | 整数 | `update` | 范围 1-99 |
| `attributes.dex` | 整数 | `update` | 范围 1-99 |
| `attributes.app` | 整数 | `update` | 范围 1-99 |
| `attributes.int` | 整数 | `update` | 范围 1-99 |
| `attributes.pow` | 整数 | `update` | 范围 1-99 |
| `attributes.edu` | 整数 | `update` | 范围 1-99 |
| `memory.current_event` | 字符串 | `update` | 无 |
| `memory.log` | 列表 | `add` | 追加日志条目 |
| `is_player` | 布尔 | - | **禁止修改** |

### 3.2 Item（物品）

| 字段路径 | 字段类型 | 允许操作 | 特殊限制 |
|---------|---------|---------|---------|
| `name` | 字符串 | `update` | 非空校验 |
| `location` | 字符串 | `move` | 目标必须是 char-xxx 或 map-xxx |
| `description.public` | 列表 | `add` | 追加描述 |
| `description.hint` | 字符串 | `update` | 仅AI可见 |
| `is_portable` | 布尔 | - | **禁止修改** |

### 3.3 Map（地图）

| 字段路径 | 字段类型 | 允许操作 | 特殊限制 |
|---------|---------|---------|---------|
| `name` | 字符串 | `update` | 非空校验 |
| `description.public` | 列表 | `add` | 追加描述 |
| `neighbors` | 列表 | `add`, `del` | 值必须是 MapNeighbor 对象 |
| `entities.characters` | 列表 | `add`, `del` | 值必须是存在的 char-id |
| `entities.items` | 列表 | `add`, `del` | 值必须是存在的 item-id |
| `parent_id` | 字符串 | `update` | 目标必须是 map-xxx 或 null |

---

## 4. 操作详细规范

### 4.1 UPDATE 操作

**适用场景：**
- 修改标量字段的值
- 整体替换复合对象（不推荐，除非明确意图）

**约束：**
```json
{
  "id": "char-player-01",
  "field": "status.hp",
  "operation": "update",
  "value": 15
}
```

**禁止：**
- 对列表字段使用 `update` 追加单个元素（应使用 `add`）
- 修改 `is_player`, `is_portable` 等元数据字段
- 修改不存在的字段路径

### 4.2 ADD 操作

**适用场景：**
- 向列表追加元素
- 仅允许白名单列表字段

**白名单字段：**
- `inventory`（角色背包）
- `description.public`（公开描述列表）
- `memory.log`（记忆日志）
- `neighbors`（地图邻居）
- `entities.characters`（地图角色）
- `entities.items`（地图物品）

**约束：**
```json
{
  "id": "char-player-01",
  "field": "description.public",
  "operation": "add",
  "value": {"description": "你获得了新的线索"}
}
```

**禁止：**
- 对非列表字段使用 `add`
- 向 `inventory` 添加不存在的 item-id
- 嵌套列表结构（如 `[["item-1"]]`）

### 4.3 DELETE 操作

**适用场景：**
- 从列表删除特定元素
- 仅允许白名单列表字段

**白名单字段（与 ADD 相同）：**
- `inventory`
- `description.public`
- `memory.log`
- `neighbors`
- `entities.characters`
- `entities.items`

**约束：**
```json
{
  "id": "char-player-01",
  "field": "inventory",
  "operation": "del",
  "value": "item-key-01"
}
```

**重要决策：DEL 字段的提供策略**

| 策略 | 说明 | 建议 |
|-----|------|------|
| **提供 DEL** | 允许 LLM 主动删除物品、描述等 | **推荐**，符合游戏逻辑（丢弃物品、移除描述） |
| **不提供 DEL** | 只允许代码层删除，LLM 只能标记 | 更安全，但限制表达能力 |

**当前决策：提供 DEL，但严格限制白名单**

理由：
1. 游戏需要支持"丢弃物品"、"移除地图实体"等操作
2. 白名单机制可以防止误删关键数据
3. 代码层有备份和回滚机制

**禁止：**
- 对非白名单字段使用 `del`
- 对标量字段使用 `del`（即使设为 null 也应使用 `update`）
- 删除不存在的元素（应静默忽略而非报错）

### 4.4 MOVE 操作

**适用场景：**
- 改变实体位置
- **仅限 `location` 字段**

**角色移动约束：**
- 目标必须是地图ID（`map-xxx`）
- 禁止自然语言地名（如"走廊"、"主厅"）
- 必须使用 `available_exits` 中提供的 `map_id`

**物品移动约束：**
- 目标可以是角色ID（`char-xxx`）或地图ID（`map-xxx`）
- 自动处理级联更新（原持有者 inventory 移除，新持有者 inventory 添加）

**格式：**
```json
// 简写格式
{
  "id": "item-key-01",
  "field": "location",
  "operation": "move",
  "value": "char-player-01"
}

// 显式格式（推荐，便于追踪）
{
  "id": "item-key-01",
  "field": "location",
  "operation": "move",
  "value": {
    "from": "char-guard-01",
    "to": "char-player-01"
  }
}
```

**禁止：**
- 对非 `location` 字段使用 `move`
- 使用自然语言地名作为目标
- 移动到不存在的实体

---

## 5. 字段类型与操作映射表

### 5.1 快速查询表

| 字段模式 | 数据类型 | 推荐操作 | 禁止操作 |
|---------|---------|---------|---------|
| `*.name` | 字符串 | `update` | `add`, `del`, `move` |
| `*.basic_info` | 字符串 | `update` | `add`, `del`, `move` |
| `*.location` | 字符串 | `move` | `update`（不推荐）, `add`, `del` |
| `*.description.public` | 列表 | `add` | - |
| `*.description.hint` | 字符串 | `update` | `add`, `del`, `move` |
| `*.inventory` | 列表 | `add`, `del` | `update`（整体替换） |
| `*.status.*` | 整数 | `update` | `add`, `del`, `move` |
| `*.attributes.*` | 整数 | `update` | `add`, `del`, `move` |
| `*.memory.current_event` | 字符串 | `update` | `add`, `del`, `move` |
| `*.memory.log` | 列表 | `add` | - |
| `*.neighbors` | 列表 | `add`, `del` | `update`（整体替换） |
| `*.entities.characters` | 列表 | `add`, `del` | `update`（整体替换） |
| `*.entities.items` | 列表 | `add`, `del` | `update`（整体替换） |
| `*.is_player` | 布尔 | - | **所有操作禁止** |
| `*.is_portable` | 布尔 | - | **所有操作禁止** |

---

## 6. 提示词层面的限制表达

### 6.1 在 system prompt 中添加的约束段落

```markdown
## 状态变更操作限制（强制遵守）

### 操作类型与字段匹配规则
- **update**: 仅用于标量字段（字符串、数字、布尔值）
- **add**: 仅用于列表字段，且字段必须在白名单中
- **del**: 仅用于白名单列表字段，用于删除特定元素
- **move**: 仅用于 location 字段，用于改变实体位置

### 白名单列表字段（允许 add/del）
- `inventory` - 角色背包物品列表
- `description.public` - 公开描述列表
- `memory.log` - 记忆日志列表
- `neighbors` - 地图邻居列表
- `entities.characters` - 地图角色列表
- `entities.items` - 地图物品列表

### 禁止操作
- 禁止对 `is_player`, `is_portable` 等元数据字段进行任何修改
- 禁止对非列表字段使用 `add` 或 `del`
- 禁止对非 `location` 字段使用 `move`
- 禁止修改不存在的字段路径

### location 字段特殊规则
- 必须使用 `move` 操作，而非 `update`
- 角色移动目标必须是地图ID（map-xxx）
- 物品移动目标可以是角色ID（char-xxx）或地图ID（map-xxx）
- 禁止使用自然语言地名（如"走廊"、"主厅"）
- 优先使用 `available_exits` 中提供的 `map_id`

### 数值字段范围限制
- HP: 0 到 max_hp
- SAN: 0 到 100
- 属性值（STR/CON等）: 1 到 99
```

### 6.2 在 JSON Schema 中添加的约束

```json
{
  "state_changes": {
    "type": "array",
    "items": {
      "type": "object",
      "properties": {
        "id": {"type": "string"},
        "field": {"type": "string"},
        "operation": {
          "type": "string",
          "enum": ["update", "add", "del", "move"]
        },
        "value": {}
      },
      "required": ["id", "field", "operation"],
      "allOf": [
        {
          "if": {
            "properties": {"operation": {"const": "move"}}
          },
          "then": {
            "properties": {"field": {"const": "location"}}
          }
        },
        {
          "if": {
            "properties": {"operation": {"enum": ["add", "del"]}}
          },
          "then": {
            "properties": {
              "field": {
                "enum": [
                  "inventory",
                  "description.public",
                  "memory.log",
                  "neighbors",
                  "entities.characters",
                  "entities.items"
                ]
              }
            }
          }
        }
      ]
    }
  }
}
```

---

## 7. 代码层面的验证逻辑

### 7.1 验证器接口设计

```python
from typing import List, Tuple, Optional
from src.data.models import StateChange, ChangeOperation

class StateChangeValidator:
    """状态变更验证器"""
    
    # 白名单列表字段
    LIST_FIELD_WHITELIST = {
        'inventory',
        'description.public',
        'memory.log',
        'neighbors',
        'entities.characters',
        'entities.items',
    }
    
    # 禁止修改的字段
    FORBIDDEN_FIELDS = {
        'is_player',
        'is_portable',
        'id',
    }
    
    # 数值字段范围
    NUMERIC_RANGES = {
        'status.hp': (0, lambda c: c.status.max_hp),
        'status.san': (0, 100),
        'status.lucky': (1, 99),
        'attributes.str': (1, 99),
        'attributes.con': (1, 99),
        'attributes.siz': (1, 99),
        'attributes.dex': (1, 99),
        'attributes.app': (1, 99),
        'attributes.int': (1, 99),
        'attributes.pow': (1, 99),
        'attributes.edu': (1, 99),
    }
    
    def validate(self, change: StateChange, game_state: GameState) -> Tuple[bool, Optional[str]]:
        """
        验证单个状态变更
        
        Returns:
            (是否通过, 错误信息)
        """
        # 1. 检查禁止字段
        if change.field in self.FORBIDDEN_FIELDS:
            return False, f"Field '{change.field}' is forbidden to modify"
        
        # 2. 检查操作类型与字段匹配
        if change.operation == ChangeOperation.MOVE:
            if change.field != 'location':
                return False, "MOVE operation is only allowed for 'location' field"
        
        elif change.operation in (ChangeOperation.ADD, ChangeOperation.DELETE):
            if change.field not in self.LIST_FIELD_WHITELIST:
                return False, f"ADD/DEL operation is only allowed for whitelist fields: {self.LIST_FIELD_WHITELIST}"
        
        # 3. 检查数值范围
        if change.field in self.NUMERIC_RANGES:
            min_val, max_val = self.NUMERIC_RANGES[change.field]
            if isinstance(max_val, callable):
                entity = self._get_entity(change.id, game_state)
                max_val = max_val(entity) if entity else 999
            if not (min_val <= change.value <= max_val):
                return False, f"Value {change.value} out of range [{min_val}, {max_val}]"
        
        # 4. 检查 location 目标有效性
        if change.operation == ChangeOperation.MOVE:
            valid = self._validate_location_target(change.value, change.id, game_state)
            if not valid:
                return False, f"Invalid location target: {change.value}"
        
        return True, None
    
    def _get_entity(self, entity_id: str, game_state: GameState):
        """获取实体"""
        return (
            game_state.characters.get(entity_id) or
            game_state.items.get(entity_id) or
            game_state.maps.get(entity_id)
        )
    
    def _validate_location_target(self, target: str, entity_id: str, game_state: GameState) -> bool:
        """验证位置目标是否有效"""
        # 角色移动：目标必须是地图
        if entity_id.startswith('char-'):
            return target in game_state.maps
        
        # 物品移动：目标可以是角色或地图
        if entity_id.startswith('item-'):
            return target in game_state.characters or target in game_state.maps
        
        return False
```

### 7.2 集成到 StateEvolution

```python
class StateEvolution:
    def __init__(self, ...):
        ...
        self._validator = StateChangeValidator()
    
    def _parse_output(self, data: Dict[str, Any]) -> StateEvolutionOutput:
        """解析LLM输出，包含验证"""
        changes = []
        validation_errors = []
        
        for change_data in data.get("state_changes", []):
            try:
                change = StateChange(**change_data)
                
                # 验证变更
                is_valid, error = self._validator.validate(change, self.game_state)
                if not is_valid:
                    validation_errors.append(f"Invalid change {change.id}.{change.field}: {error}")
                    continue
                
                changes.append(change)
            except Exception as e:
                validation_errors.append(f"Failed to parse change: {e}")
        
        if validation_errors:
            logger.warning(f"State changes validation errors: {validation_errors}")
        
        return StateEvolutionOutput(
            state_changes=changes,
            validation_errors=validation_errors,
            ...
        )
```

---

## 8. 决策记录

### 8.1 为什么提供 DEL 操作？

**决策：** 提供 DEL，但限制白名单

**理由：**
1. 游戏逻辑需要：丢弃物品、移除地图实体是常见操作
2. 白名单机制提供安全保障
3. 代码层有事务回滚机制

**替代方案考虑：**
- 仅标记为"待删除"，由代码层执行：增加复杂性，延迟反馈
- 完全禁止删除：限制表达能力，不符合游戏需求

### 8.2 为什么 location 必须使用 move？

**决策：** location 字段强制使用 move 操作

**理由：**
1. 语义清晰：move 明确表示位置变化
2. 便于追踪：move 可以记录 from/to，便于调试
3. 级联处理：move 触发 inventory 同步等级联操作
4. 防止误用：避免 LLM 用 update 随意修改位置

### 8.3 为什么 description.public 推荐 add 而非 update？

**决策：** 推荐 add，但允许 update

**理由：**
1. 追加描述是常见需求（"你发现了..."、"你感觉到..."）
2. update 整体替换会丢失历史描述
3. 保留 update 用于特殊情况（如修正错误描述）

---

## 9. 实施计划

### Phase 1: 提示词更新（立即）
- [ ] 在 state_evolution_prompt.md 中添加"操作限制"段落
- [ ] 更新 JSON Schema 约束
- [ ] 添加示例展示正确/错误的变更格式

### Phase 2: 代码验证（短期）
- [ ] 实现 StateChangeValidator 类
- [ ] 集成到 StateEvolution._parse_output
- [ ] 添加单元测试覆盖各种约束场景

### Phase 3: 运行时监控（中期）
- [ ] 记录 LLM 违反约束的频率和模式
- [ ] 根据数据调整提示词或约束
- [ ] 考虑对频繁违规的字段添加更严格的提示

---

## 10. 附录

### A. 常见错误示例

```json
// 错误：对 location 使用 update
{
  "id": "char-player-01",
  "field": "location",
  "operation": "update",
  "value": "map-corridor-01"
}

// 正确：使用 move
{
  "id": "char-player-01",
  "field": "location",
  "operation": "move",
  "value": "map-corridor-01"
}
```

```json
// 错误：对非白名单字段使用 del
{
  "id": "char-player-01",
  "field": "status.hp",
  "operation": "del",
  "value": null
}

// 正确：使用 update 设为 0
{
  "id": "char-player-01",
  "field": "status.hp",
  "operation": "update",
  "value": 0
}
```

```json
// 错误：向 inventory 添加不存在的物品
{
  "id": "char-player-01",
  "field": "inventory",
  "operation": "add",
  "value": "item-nonexistent"
}

// 正确：确保物品存在
{
  "id": "char-player-01",
  "field": "inventory",
  "operation": "add",
  "value": "item-key-01"
}
```

### B. 变更决策流程图

```
开始
  │
  ▼
确定字段类型
  │
  ├─► 标量字段 ──► 只能 UPDATE
  │
  ├─► 列表字段 ──► 在白名单？
  │       ├─► 是 ──► 允许 ADD/DEL/UPDATE
  │       └─► 否 ──► 只能 UPDATE
  │
  ├─► location ──► 必须使用 MOVE
  │
  └─► 禁止字段 ──► 拒绝
```
