"""
Debug 系统 - 一致性检查器

自动检测内存状态和 IO 层状态不一致的功能。
用于发现物品-持有者关系不同步、inventory 与 location 不匹配等问题。

使用方式:
    # 在 DebugLogger 中启用
    logger = DebugLogger()
    logger.enable_consistency_checking(io_system)

    # 或者在需要时手动使用
    checker = ConsistencyChecker(io_system, logger)
    inconsistencies = checker.check_all_entities(game_state)
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from src.utils.debug_types import InconsistencyRecord, LogLevel
from src.data.models import Character, Item, Map, GameState, StateChange

# 尝试导入 IOSystem 类型（用于类型提示）
try:
    from src.data.io_system import IOSystem
except ImportError:
    IOSystem = Any

# 尝试导入 DebugLogger 类型（用于类型提示）
try:
    from src.utils.debug_logger import DebugLogger
except ImportError:
    DebugLogger = Any


# ============================================================
# 一致性检查器核心类
# ============================================================

# 延迟导入数据模型
def _get_models():
    """延迟导入数据模型"""
    from src.data.models import Character, Item, Map, GameState, StateChange
    return Character, Item, Map, GameState, StateChange


class ConsistencyChecker:
    """自动状态一致性检查器

    检测内存状态和 IO 层状态之间的差异，重点关注：
    - 物品 location 变更后，持有者 inventory 是否同步
    - 角色 inventory 变更后，物品 location 是否同步
    - 地图 entities.items 变更后，物品 location 是否同步

    Attributes:
        io_system: IO 系统实例，用于从存储层读取实体
        logger: DebugLogger 实例，用于记录不一致
    """

    def __init__(self, io_system: Any, logger: Optional[Any] = None):
        """初始化一致性检查器

        Args:
            io_system: IO 系统实例
            logger: DebugLogger 实例（可选）
        """
        self.io_system = io_system
        self.logger = logger

    def check_after_change(
        self,
        entity_id: str,
        field: str,
        memory_state: GameState
    ) -> List[InconsistencyRecord]:
        """在变更应用后执行针对性一致性检查

        根据变更的实体类型和字段，执行相应的重点检查。

        Args:
            entity_id: 变更的实体ID
            field: 变更的字段名
            memory_state: 内存中的游戏状态

        Returns:
            检测到的不一致记录列表
        """
        inconsistencies: List[InconsistencyRecord] = []
        trigger_change = f"{entity_id}.{field}"

        # 场景1: 物品 location 变更后，检查持有者 inventory 同步
        if entity_id.startswith("item-") and field == "location":
            record = self._check_item_location_sync(entity_id, memory_state, trigger_change)
            if record:
                inconsistencies.append(record)

        # 场景2: 角色 inventory 变更后，检查物品 location 同步
        elif entity_id.startswith("char-") and field == "inventory":
            record = self._check_character_inventory_sync(entity_id, memory_state, trigger_change)
            if record:
                inconsistencies.append(record)

        # 场景3: 地图 entities.items 变更后，检查物品 location 同步
        elif entity_id.startswith("map-") and (field == "entities.items" or field.endswith(".items")):
            record = self._check_map_items_sync(entity_id, memory_state, trigger_change)
            if record:
                inconsistencies.append(record)

        # 记录所有检测到的不一致
        if inconsistencies and self.logger:
            for record in inconsistencies:
                self.logger.log_inconsistency(
                    trigger_change=record.trigger_change,
                    differences=[{
                        "entity_id": record.entity_id,
                        "field": record.field,
                        "memory_value": record.memory_value,
                        "io_value": record.io_value,
                        "severity": record.severity
                    }]
                )

        return inconsistencies

    def check_entity_consistency(
        self,
        entity_id: str,
        memory_state: GameState,
        io_entity: Optional[Any] = None
    ) -> Optional[InconsistencyRecord]:
        """检查指定实体的一致性

        对比内存中的实体和 IO 层的实体，检查关键字段是否一致。

        Args:
            entity_id: 实体ID
            memory_state: 内存中的游戏状态
            io_entity: 预加载的 IO 层实体（可选，如果为 None 则从 IO 层读取）

        Returns:
            如果不一致返回 InconsistencyRecord，否则返回 None
        """
        # 确定实体类型并获取内存实体
        memory_entity = None
        if entity_id.startswith("char-"):
            memory_entity = memory_state.characters.get(entity_id)
        elif entity_id.startswith("item-"):
            memory_entity = memory_state.items.get(entity_id)
        elif entity_id.startswith("map-"):
            memory_entity = memory_state.maps.get(entity_id)

        if memory_entity is None:
            return None

        # 如果未提供 io_entity，从 IO 层读取
        if io_entity is None:
            io_entity = self._get_entity_from_io(entity_id)

        if io_entity is None:
            return InconsistencyRecord(
                trigger_change=f"check_entity_consistency({entity_id})",
                entity_id=entity_id,
                field="existence",
                memory_value="exists",
                io_value="not_found",
                severity="error"
            )

        # 检查关键字段
        return self._compare_entity_fields(entity_id, memory_entity, io_entity)

    def verify_inventory_sync(
        self,
        character_id: str,
        memory_state: GameState
    ) -> Optional[InconsistencyRecord]:
        """验证角色 inventory 与物品 location 的双向同步

        检查：
        1. 内存中角色 inventory 的物品，其 location 是否指向该角色
        2. IO 层中角色 inventory 的物品，其 location 是否指向该角色
        3. 内存和 IO 层 inventory 是否一致

        Args:
            character_id: 角色ID
            memory_state: 内存中的游戏状态

        Returns:
            如果不一致返回 InconsistencyRecord，否则返回 None
        """
        trigger_change = f"verify_inventory_sync({character_id})"

        # 获取内存角色
        memory_char = memory_state.characters.get(character_id)
        if not memory_char:
            return None

        # 获取 IO 层角色
        io_char = self._get_entity_from_io(character_id)
        if not io_char:
            return InconsistencyRecord(
                trigger_change=trigger_change,
                entity_id=character_id,
                field="existence",
                memory_value=character_id,
                io_value=None,
                severity="critical"
            )

        # 检查内存中物品 location
        memory_issues = []
        for item_id in memory_char.inventory:
            item = memory_state.items.get(item_id)
            if item and item.location != character_id:
                memory_issues.append({
                    "item_id": item_id,
                    "expected_location": character_id,
                    "actual_location": item.location
                })

        # 检查 IO 层物品 location
        io_issues = []
        for item_id in io_char.inventory:
            item = self._get_entity_from_io(item_id)
            if item and item.location != character_id:
                io_issues.append({
                    "item_id": item_id,
                    "expected_location": character_id,
                    "actual_location": item.location
                })

        # 检查 inventory 一致性
        memory_inv = set(memory_char.inventory)
        io_inv = set(io_char.inventory)

        if memory_issues or io_issues or memory_inv != io_inv:
            return InconsistencyRecord(
                trigger_change=trigger_change,
                entity_id=character_id,
                field="inventory_sync",
                memory_value={
                    "inventory": list(memory_inv),
                    "item_location_issues": memory_issues
                },
                io_value={
                    "inventory": list(io_inv),
                    "item_location_issues": io_issues
                },
                severity="error" if (memory_issues or io_issues) else "warning"
            )

        return None

    def check_all_entities(self, memory_state: GameState) -> List[InconsistencyRecord]:
        """检查所有实体的一致性

        遍历内存状态中的所有实体，检查与 IO 层的一致性。

        Args:
            memory_state: 内存中的游戏状态

        Returns:
            所有检测到的不一致记录列表
        """
        inconsistencies: List[InconsistencyRecord] = []

        # 检查所有角色
        for char_id in memory_state.characters:
            record = self.check_entity_consistency(char_id, memory_state)
            if record:
                inconsistencies.append(record)

            # 额外检查 inventory 同步
            record = self.verify_inventory_sync(char_id, memory_state)
            if record:
                inconsistencies.append(record)

        # 检查所有物品
        for item_id in memory_state.items:
            record = self.check_entity_consistency(item_id, memory_state)
            if record:
                inconsistencies.append(record)

        # 检查所有地图
        for map_id in memory_state.maps:
            record = self.check_entity_consistency(map_id, memory_state)
            if record:
                inconsistencies.append(record)

            # 检查地图 items 同步
            record = self._check_map_items_sync(map_id, memory_state, "check_all_entities")
            if record:
                inconsistencies.append(record)

        # 记录到 logger
        if inconsistencies and self.logger:
            for record in inconsistencies:
                self.logger.log_inconsistency(
                    trigger_change=record.trigger_change,
                    differences=[{
                        "entity_id": record.entity_id,
                        "field": record.field,
                        "memory_value": record.memory_value,
                        "io_value": record.io_value,
                        "severity": record.severity
                    }]
                )

        return inconsistencies

    # ============================================================
    # 内部辅助方法
    # ============================================================

    def _get_entity_from_io(self, entity_id: str) -> Optional[Any]:
        """从 IO 层获取实体"""
        if not self.io_system:
            return None

        try:
            if entity_id.startswith("char-"):
                return self.io_system.get_character(entity_id)
            elif entity_id.startswith("item-"):
                return self.io_system.get_item(entity_id)
            elif entity_id.startswith("map-"):
                return self.io_system.get_map(entity_id)
        except Exception:
            pass
        return None

    def _compare_entity_fields(
        self,
        entity_id: str,
        memory_entity: Any,
        io_entity: Any
    ) -> Optional[InconsistencyRecord]:
        """对比实体的关键字段"""
        differences = []

        # 检查 location 字段
        if hasattr(memory_entity, 'location') and hasattr(io_entity, 'location'):
            if memory_entity.location != io_entity.location:
                differences.append({
                    "field": "location",
                    "memory": memory_entity.location,
                    "io": io_entity.location
                })

        # 检查 inventory 字段（角色）
        if hasattr(memory_entity, 'inventory') and hasattr(io_entity, 'inventory'):
            mem_inv = set(memory_entity.inventory)
            io_inv = set(io_entity.inventory)
            if mem_inv != io_inv:
                differences.append({
                    "field": "inventory",
                    "memory": list(mem_inv),
                    "io": list(io_inv),
                    "added_in_io": list(io_inv - mem_inv),
                    "missing_in_memory": list(mem_inv - io_inv)
                })

        # 检查 entities.items 字段（地图）
        if hasattr(memory_entity, 'entities') and hasattr(io_entity, 'entities'):
            mem_items = set(memory_entity.entities.items)
            io_items = set(io_entity.entities.items)
            if mem_items != io_items:
                differences.append({
                    "field": "entities.items",
                    "memory": list(mem_items),
                    "io": list(io_items)
                })

        if differences:
            return InconsistencyRecord(
                trigger_change=f"check_entity_consistency({entity_id})",
                entity_id=entity_id,
                field="multiple",
                memory_value={d["field"]: d["memory"] for d in differences},
                io_value={d["field"]: d["io"] for d in differences},
                severity="warning"
            )

        return None

    def _check_item_location_sync(
        self,
        item_id: str,
        memory_state: GameState,
        trigger_change: str
    ) -> Optional[InconsistencyRecord]:
        """检查物品 location 变更后的同步状态

        当物品 location 改变时，检查：
        1. 原持有者的 inventory 是否已移除该物品
        2. 新持有者的 inventory 是否已添加该物品
        3. IO 层和内存层是否一致
        """
        memory_item = memory_state.items.get(item_id)
        if not memory_item:
            return None

        io_item = self._get_entity_from_io(item_id)
        if not io_item:
            return InconsistencyRecord(
                trigger_change=trigger_change,
                entity_id=item_id,
                field="existence",
                memory_value=item_id,
                io_value=None,
                severity="critical"
            )

        # 检查物品 location 是否一致
        if memory_item.location != io_item.location:
            return InconsistencyRecord(
                trigger_change=trigger_change,
                entity_id=item_id,
                field="location",
                memory_value=memory_item.location,
                io_value=io_item.location,
                severity="error"
            )

        # 检查持有者的 inventory
        location = memory_item.location
        if location and location.startswith("char-"):
            record = self._verify_holder_inventory(item_id, location, memory_state, trigger_change)
            if record:
                return record

        return None

    def _verify_holder_inventory(
        self,
        item_id: str,
        holder_id: str,
        memory_state: GameState,
        trigger_change: str
    ) -> Optional[InconsistencyRecord]:
        """验证持有者 inventory 中是否包含指定物品"""
        # 检查内存
        memory_char = memory_state.characters.get(holder_id)
        if memory_char and item_id not in memory_char.inventory:
            return InconsistencyRecord(
                trigger_change=trigger_change,
                entity_id=holder_id,
                field="inventory",
                memory_value=memory_char.inventory,
                io_value=f"should contain {item_id}",
                severity="error"
            )

        # 检查 IO 层
        io_char = self._get_entity_from_io(holder_id)
        if io_char and item_id not in io_char.inventory:
            return InconsistencyRecord(
                trigger_change=trigger_change,
                entity_id=holder_id,
                field="inventory",
                memory_value=f"should contain {item_id}",
                io_value=io_char.inventory,
                severity="error"
            )

        return None

    def _check_character_inventory_sync(
        self,
        character_id: str,
        memory_state: GameState,
        trigger_change: str
    ) -> Optional[InconsistencyRecord]:
        """检查角色 inventory 变更后的同步状态

        当角色 inventory 改变时，检查：
        1. 新增的物品 location 是否指向该角色
        2. 移除的物品 location 是否已清空或改变
        3. IO 层和内存层是否一致
        """
        memory_char = memory_state.characters.get(character_id)
        if not memory_char:
            return None

        io_char = self._get_entity_from_io(character_id)
        if not io_char:
            return InconsistencyRecord(
                trigger_change=trigger_change,
                entity_id=character_id,
                field="existence",
                memory_value=character_id,
                io_value=None,
                severity="critical"
            )

        memory_inv = set(memory_char.inventory)
        io_inv = set(io_char.inventory)

        # 检查 inventory 是否一致
        if memory_inv != io_inv:
            return InconsistencyRecord(
                trigger_change=trigger_change,
                entity_id=character_id,
                field="inventory",
                memory_value=list(memory_inv),
                io_value=list(io_inv),
                severity="error"
            )

        # 检查每个物品的 location
        location_issues = []
        for item_id in memory_inv:
            memory_item = memory_state.items.get(item_id)
            io_item = self._get_entity_from_io(item_id)

            if memory_item and memory_item.location != character_id:
                location_issues.append({
                    "item_id": item_id,
                    "issue": "memory_location_mismatch",
                    "expected": character_id,
                    "actual": memory_item.location
                })

            if io_item and io_item.location != character_id:
                location_issues.append({
                    "item_id": item_id,
                    "issue": "io_location_mismatch",
                    "expected": character_id,
                    "actual": io_item.location
                })

        if location_issues:
            return InconsistencyRecord(
                trigger_change=trigger_change,
                entity_id=character_id,
                field="items_location",
                memory_value={"inventory": list(memory_inv), "issues": location_issues},
                io_value={"inventory": list(io_inv)},
                severity="error"
            )

        return None

    def _check_map_items_sync(
        self,
        map_id: str,
        memory_state: GameState,
        trigger_change: str
    ) -> Optional[InconsistencyRecord]:
        """检查地图 entities.items 变更后的同步状态

        当地图 entities.items 改变时，检查：
        1. 新增的 items location 是否指向该地图
        2. 移除的 items location 是否已清空或改变
        3. IO 层和内存层是否一致
        """
        memory_map = memory_state.maps.get(map_id)
        if not memory_map:
            return None

        io_map = self._get_entity_from_io(map_id)
        if not io_map:
            return InconsistencyRecord(
                trigger_change=trigger_change,
                entity_id=map_id,
                field="existence",
                memory_value=map_id,
                io_value=None,
                severity="critical"
            )

        memory_items = set(memory_map.entities.items)
        io_items = set(io_map.entities.items)

        # 检查 items 列表是否一致
        if memory_items != io_items:
            return InconsistencyRecord(
                trigger_change=trigger_change,
                entity_id=map_id,
                field="entities.items",
                memory_value=list(memory_items),
                io_value=list(io_items),
                severity="error"
            )

        # 检查每个物品的 location
        location_issues = []
        for item_id in memory_items:
            memory_item = memory_state.items.get(item_id)
            io_item = self._get_entity_from_io(item_id)

            if memory_item and memory_item.location != map_id:
                location_issues.append({
                    "item_id": item_id,
                    "issue": "memory_location_mismatch",
                    "expected": map_id,
                    "actual": memory_item.location
                })

            if io_item and io_item.location != map_id:
                location_issues.append({
                    "item_id": item_id,
                    "issue": "io_location_mismatch",
                    "expected": map_id,
                    "actual": io_item.location
                })

        if location_issues:
            return InconsistencyRecord(
                trigger_change=trigger_change,
                entity_id=map_id,
                field="items_location",
                memory_value={"items": list(memory_items), "issues": location_issues},
                io_value={"items": list(io_items)},
                severity="error"
            )

        return None


# ============================================================
# 便捷函数
# ============================================================

def create_consistency_checker(
    io_system: IOSystem,
    logger: Optional[DebugLogger] = None
) -> ConsistencyChecker:
    """创建一致性检查器实例的便捷函数"""
    return ConsistencyChecker(io_system, logger)


def check_inventory_sync(
    character_id: str,
    memory_state: GameState,
    io_system: IOSystem
) -> Optional[InconsistencyRecord]:
    """快捷函数：检查角色 inventory 同步状态"""
    checker = ConsistencyChecker(io_system)
    return checker.verify_inventory_sync(character_id, memory_state)


def check_item_holder_sync(
    item_id: str,
    memory_state: GameState,
    io_system: IOSystem
) -> Optional[InconsistencyRecord]:
    """快捷函数：检查物品持有者同步状态"""
    checker = ConsistencyChecker(io_system)
    return checker._check_item_location_sync(item_id, memory_state, f"check_item_holder_sync({item_id})")
