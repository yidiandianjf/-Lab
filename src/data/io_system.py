"""
COC文字冒险游戏框架 - IO系统
提供统一的数据读写接口，隔离底层存储实现
支持SQLite + SQLAlchemy 和 JSON文件两种模式
"""

import json
import os
from typing import Any, List, Dict, Optional, Union
from pathlib import Path

from sqlalchemy import create_engine, Column, String, Text, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError

from src.data.models import (
    Character, Item, Map, GameState, StateChange, ChangeOperation
)
from src.utils.consistency_checker import ConsistencyChecker


# ============================================================
# SQLAlchemy模型定义（内部使用）
# ============================================================

Base = declarative_base()


class CharacterORM(Base):
    __tablename__ = "characters"
    id = Column(String, primary_key=True)
    data = Column(Text, nullable=False)  # JSON序列化数据


class ItemORM(Base):
    __tablename__ = "items"
    id = Column(String, primary_key=True)
    data = Column(Text, nullable=False)


class MapORM(Base):
    __tablename__ = "maps"
    id = Column(String, primary_key=True)
    data = Column(Text, nullable=False)


class GameMetaORM(Base):
    __tablename__ = "game_meta"
    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)


# ============================================================
# 错误码定义
# ============================================================

ERROR_SUCCESS = 0
ERROR_ID_NOT_FOUND = 1
ERROR_FIELD_NOT_FOUND = 2
ERROR_OPERATION_INVALID = 3
ERROR_OTHER = 4

ALLOWED_DELETE_LIST_FIELDS = {
    "inventory",
    "neighbors",
    "entities.items",
    "entities.characters",
    "description.public",
    "memory.log",
}


# ============================================================
# IO系统核心类
# ============================================================

class IOSystem:
    """
    IO系统 - 统一数据读写接口
    支持两种模式：
    1. sqlite: 使用SQLite数据库（推荐用于运行时）
    2. json: 使用JSON文件（推荐用于配置/存档）
    """
    
    def __init__(self, db_path: str = "data/game.db", mode: str = "sqlite"):
        """
        初始化IO系统
        
        Args:
            db_path: 数据库文件路径（sqlite模式）或数据目录路径（json模式）
            mode: 存储模式，"sqlite" 或 "json"
        """
        self.mode = mode
        self.db_path = db_path
        self._session = None
        
        if mode == "sqlite":
            self._init_sqlite()
        elif mode == "json":
            self._init_json()
        else:
            raise ValueError(f"不支持的存储模式: {mode}")
    
    def _init_sqlite(self):
        """初始化SQLite数据库"""
        # 确保目录存在
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        # 创建引擎
        self.engine = create_engine(f"sqlite:///{self.db_path}")
        
        # 启用外键约束
        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
        
        # 创建表
        Base.metadata.create_all(self.engine)
        
        # 创建会话
        Session = sessionmaker(bind=self.engine)
        self._session = Session()
    
    def _init_json(self):
        """初始化JSON文件存储"""
        self.json_dir = Path(self.db_path)
        self.json_dir.mkdir(parents=True, exist_ok=True)
        
        # 子目录
        (self.json_dir / "characters").mkdir(exist_ok=True)
        (self.json_dir / "items").mkdir(exist_ok=True)
        (self.json_dir / "maps").mkdir(exist_ok=True)

    def clear_runtime_store(self) -> int:
        """清空当前运行库存量数据，避免新世界加载时混入旧实体。"""
        try:
            if self.mode == "sqlite":
                self._session.query(CharacterORM).delete()
                self._session.query(ItemORM).delete()
                self._session.query(MapORM).delete()
                self._session.query(GameMetaORM).delete()
                self._session.commit()
            else:
                for folder in ("characters", "items", "maps"):
                    target_dir = self.json_dir / folder
                    if not target_dir.exists():
                        continue
                    for file_path in target_dir.glob("*.json"):
                        file_path.unlink()

                meta_path = self.json_dir / "game_state.json"
                if meta_path.exists():
                    meta_path.unlink()

            return ERROR_SUCCESS
        except Exception as e:
            print(f"[IOSystem] 清空运行库失败: {e}")
            if self.mode == "sqlite":
                self._session.rollback()
            return ERROR_OTHER

    @staticmethod
    def _normalize_public_description_value(value: Any) -> List[Dict[str, str]]:
        """Normalize description.public payloads to the canonical list-of-dicts shape."""
        if value is None:
            return []
        if isinstance(value, dict):
            value = [value]
        elif isinstance(value, str):
            value = [{"description": value}]
        elif not isinstance(value, list):
            value = [{"description": str(value)}]

        normalized: List[Dict[str, str]] = []
        for entry in value:
            if isinstance(entry, dict):
                text = str(entry.get("description", "")).strip()
            else:
                text = str(entry).strip()
            if text:
                normalized.append({"description": text})
        return normalized

    @staticmethod
    def _normalize_neighbors_value(value: Any) -> List[Dict[str, Any]]:
        """Normalize map neighbor payloads to canonical dict shape."""
        if value is None:
            return []
        if isinstance(value, dict):
            value = [value]
        elif not isinstance(value, list):
            value = [value]

        normalized: List[Dict[str, Any]] = []
        seen = set()
        for entry in value:
            if hasattr(entry, "model_dump"):
                entry = entry.model_dump()
            if isinstance(entry, dict):
                neighbor_id = str(entry.get("id", "")).strip()
                direction = str(entry.get("direction", "")).strip()
                description = str(entry.get("description", "")).strip()
                if neighbor_id and direction and neighbor_id not in seen:
                    seen.add(neighbor_id)
                    normalized.append(
                        {
                            "id": neighbor_id,
                            "direction": direction,
                            "description": description,
                        }
                    )
        return normalized
    
    # ============================================================
    # 字符数据操作
    # ============================================================
    
    def get_character(self, char_id: str) -> Optional[Character]:
        """获取指定角色的完整数据"""
        try:
            if self.mode == "sqlite":
                orm_obj = self._session.query(CharacterORM).filter_by(id=char_id).first()
                if orm_obj:
                    return Character(**json.loads(orm_obj.data))
                return None
            else:  # json mode
                file_path = self.json_dir / "characters" / f"{char_id}.json"
                if file_path.exists():
                    with open(file_path, "r", encoding="utf-8") as f:
                        return Character(**json.load(f))
                return None
        except Exception as e:
            print(f"[IOSystem] 获取角色 {char_id} 失败: {e}")
            return None
    
    def save_character(self, character: Character) -> int:
        """保存角色数据"""
        try:
            data = character.model_dump_json(indent=2)
            
            if self.mode == "sqlite":
                orm_obj = self._session.query(CharacterORM).filter_by(id=character.id).first()
                if orm_obj:
                    orm_obj.data = data
                else:
                    orm_obj = CharacterORM(id=character.id, data=data)
                    self._session.add(orm_obj)
                self._session.commit()
            else:  # json mode
                file_path = self.json_dir / "characters" / f"{character.id}.json"
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(data)
            
            return ERROR_SUCCESS
        except Exception as e:
            print(f"[IOSystem] 保存角色 {character.id} 失败: {e}")
            if self.mode == "sqlite":
                self._session.rollback()
            return ERROR_OTHER
    
    def update_character_field(self, char_id: str, field: str, value: Any) -> int:
        """更新角色指定字段"""
        character = self.get_character(char_id)
        if not character:
            return ERROR_ID_NOT_FOUND
        
        try:
            # 支持点分路径，如 "attributes.str"
            parts = field.split(".")
            obj = character
            for part in parts[:-1]:
                if hasattr(obj, part):
                    obj = getattr(obj, part)
                else:
                    return ERROR_FIELD_NOT_FOUND
            
            last_part = parts[-1]
            if hasattr(obj, last_part):
                if field == "inventory":
                    if not isinstance(value, list):
                        return ERROR_OPERATION_INVALID
                    normalized_inventory = []
                    seen = set()
                    for item_id in value:
                        if not isinstance(item_id, str) or not self.get_item(item_id):
                            return ERROR_ID_NOT_FOUND
                        if item_id not in seen:
                            seen.add(item_id)
                            normalized_inventory.append(item_id)
                    value = normalized_inventory
                setattr(obj, last_part, value)
            else:
                return ERROR_FIELD_NOT_FOUND
            
            if field == "inventory":
                return self._save_character_with_inventory_sync(character)
            return self.save_character(character)
        except Exception as e:
            print(f"[IOSystem] 更新角色字段 {char_id}.{field} 失败: {e}")
            return ERROR_OTHER
    
    def delete_character(self, char_id: str) -> int:
        """删除角色"""
        try:
            if self.mode == "sqlite":
                orm_obj = self._session.query(CharacterORM).filter_by(id=char_id).first()
                if orm_obj:
                    self._session.delete(orm_obj)
                    self._session.commit()
                    return ERROR_SUCCESS
                return ERROR_ID_NOT_FOUND
            else:  # json mode
                file_path = self.json_dir / "characters" / f"{char_id}.json"
                if file_path.exists():
                    file_path.unlink()
                    return ERROR_SUCCESS
                return ERROR_ID_NOT_FOUND
        except Exception as e:
            print(f"[IOSystem] 删除角色 {char_id} 失败: {e}")
            if self.mode == "sqlite":
                self._session.rollback()
            return ERROR_OTHER
    
    # ============================================================
    # 物品数据操作
    # ============================================================
    
    def get_item(self, item_id: str) -> Optional[Item]:
        """获取指定物品的完整数据"""
        try:
            if self.mode == "sqlite":
                orm_obj = self._session.query(ItemORM).filter_by(id=item_id).first()
                if orm_obj:
                    return Item(**json.loads(orm_obj.data))
                return None
            else:  # json mode
                file_path = self.json_dir / "items" / f"{item_id}.json"
                if file_path.exists():
                    with open(file_path, "r", encoding="utf-8") as f:
                        return Item(**json.load(f))
                return None
        except Exception as e:
            print(f"[IOSystem] 获取物品 {item_id} 失败: {e}")
            return None
    
    def save_item(self, item: Item) -> int:
        """保存物品数据"""
        try:
            data = item.model_dump_json(indent=2)
            
            if self.mode == "sqlite":
                orm_obj = self._session.query(ItemORM).filter_by(id=item.id).first()
                if orm_obj:
                    orm_obj.data = data
                else:
                    orm_obj = ItemORM(id=item.id, data=data)
                    self._session.add(orm_obj)
                self._session.commit()
            else:  # json mode
                file_path = self.json_dir / "items" / f"{item.id}.json"
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(data)
            
            return ERROR_SUCCESS
        except Exception as e:
            print(f"[IOSystem] 保存物品 {item.id} 失败: {e}")
            if self.mode == "sqlite":
                self._session.rollback()
            return ERROR_OTHER
    
    def update_item_field(self, item_id: str, field: str, value: Any) -> int:
        """更新物品指定字段"""
        item = self.get_item(item_id)
        if not item:
            return ERROR_ID_NOT_FOUND
        
        try:
            parts = field.split(".")
            obj = item
            for part in parts[:-1]:
                if hasattr(obj, part):
                    obj = getattr(obj, part)
                else:
                    return ERROR_FIELD_NOT_FOUND
            
            last_part = parts[-1]
            if hasattr(obj, last_part):
                if field == "location" and isinstance(value, str) and value:
                    if not self.get_character(value) and not self.get_map(value):
                        return ERROR_ID_NOT_FOUND
                setattr(obj, last_part, value)
            else:
                return ERROR_FIELD_NOT_FOUND
            
            if field == "location":
                return self._save_item_with_relationship_sync(item)
            return self.save_item(item)
        except Exception as e:
            print(f"[IOSystem] 更新物品字段 {item_id}.{field} 失败: {e}")
            return ERROR_OTHER
    
    def delete_item(self, item_id: str) -> int:
        """删除物品"""
        try:
            if self.mode == "sqlite":
                orm_obj = self._session.query(ItemORM).filter_by(id=item_id).first()
                if orm_obj:
                    self._session.delete(orm_obj)
                    self._session.commit()
                    return ERROR_SUCCESS
                return ERROR_ID_NOT_FOUND
            else:  # json mode
                file_path = self.json_dir / "items" / f"{item_id}.json"
                if file_path.exists():
                    file_path.unlink()
                    return ERROR_SUCCESS
                return ERROR_ID_NOT_FOUND
        except Exception as e:
            print(f"[IOSystem] 删除物品 {item_id} 失败: {e}")
            if self.mode == "sqlite":
                self._session.rollback()
            return ERROR_OTHER
    
    # ============================================================
    # 地图数据操作
    # ============================================================
    
    def get_map(self, map_id: str) -> Optional[Map]:
        """获取指定地图的完整数据"""
        try:
            if self.mode == "sqlite":
                orm_obj = self._session.query(MapORM).filter_by(id=map_id).first()
                if orm_obj:
                    return Map(**json.loads(orm_obj.data))
                return None
            else:  # json mode
                file_path = self.json_dir / "maps" / f"{map_id}.json"
                if file_path.exists():
                    with open(file_path, "r", encoding="utf-8") as f:
                        return Map(**json.load(f))
                return None
        except Exception as e:
            print(f"[IOSystem] 获取地图 {map_id} 失败: {e}")
            return None
    
    def save_map(self, map_obj: Map) -> int:
        """保存地图数据"""
        try:
            data = map_obj.model_dump_json(indent=2)
            
            if self.mode == "sqlite":
                orm_obj = self._session.query(MapORM).filter_by(id=map_obj.id).first()
                if orm_obj:
                    orm_obj.data = data
                else:
                    orm_obj = MapORM(id=map_obj.id, data=data)
                    self._session.add(orm_obj)
                self._session.commit()
            else:  # json mode
                file_path = self.json_dir / "maps" / f"{map_obj.id}.json"
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(data)
            
            return ERROR_SUCCESS
        except Exception as e:
            print(f"[IOSystem] 保存地图 {map_obj.id} 失败: {e}")
            if self.mode == "sqlite":
                self._session.rollback()
            return ERROR_OTHER

    def _get_all_characters(self) -> List[Character]:
        """加载全部角色。"""
        try:
            if self.mode == "sqlite":
                rows = self._session.query(CharacterORM).all()
                return [Character(**json.loads(row.data)) for row in rows]

            chars: List[Character] = []
            for file_path in sorted((self.json_dir / "characters").glob("*.json")):
                with open(file_path, "r", encoding="utf-8") as f:
                    chars.append(Character(**json.load(f)))
            return chars
        except Exception as e:
            print(f"[IOSystem] 加载全部角色失败: {e}")
            return []

    def _get_all_maps(self) -> List[Map]:
        """加载全部地图。"""
        try:
            if self.mode == "sqlite":
                rows = self._session.query(MapORM).all()
                return [Map(**json.loads(row.data)) for row in rows]

            maps: List[Map] = []
            for file_path in sorted((self.json_dir / "maps").glob("*.json")):
                with open(file_path, "r", encoding="utf-8") as f:
                    maps.append(Map(**json.load(f)))
            return maps
        except Exception as e:
            print(f"[IOSystem] 加载全部地图失败: {e}")
            return []

    def _get_all_items(self) -> List[Item]:
        """加载全部物品。"""
        try:
            if self.mode == "sqlite":
                rows = self._session.query(ItemORM).all()
                return [Item(**json.loads(row.data)) for row in rows]

            items: List[Item] = []
            for file_path in sorted((self.json_dir / "items").glob("*.json")):
                with open(file_path, "r", encoding="utf-8") as f:
                    items.append(Item(**json.load(f)))
            return items
        except Exception as e:
            print(f"[IOSystem] 加载全部物品失败: {e}")
            return []

    def _save_entities(self, characters: List[Character], maps: List[Map], items: List[Item]) -> int:
        """保存一组实体。"""
        for character in characters:
            if self.save_character(character) != ERROR_SUCCESS:
                return ERROR_OTHER
        for map_obj in maps:
            if self.save_map(map_obj) != ERROR_SUCCESS:
                return ERROR_OTHER
        for item in items:
            if self.save_item(item) != ERROR_SUCCESS:
                return ERROR_OTHER
        return ERROR_SUCCESS

    def _save_item_with_relationship_sync(self, item: Item) -> int:
        """保存物品并同步持有者关系。"""
        checker = ConsistencyChecker()
        characters = self._get_all_characters()
        maps = self._get_all_maps()
        item.location = (item.location or "").strip()

        target_char = None
        target_map = None
        if item.location:
            target_char = next((char for char in characters if char.id == item.location), None)
            target_map = next((map_obj for map_obj in maps if map_obj.id == item.location), None)
            if not target_char and not target_map:
                return ERROR_ID_NOT_FOUND

        for character in characters:
            if item.id in character.inventory and (not target_char or character.id != target_char.id):
                character.inventory = [item_id for item_id in character.inventory if item_id != item.id]

        for map_obj in maps:
            if item.id in map_obj.entities.items and (not target_map or map_obj.id != target_map.id):
                map_obj.entities.items = [item_id for item_id in map_obj.entities.items if item_id != item.id]

        if target_char and item.id not in target_char.inventory:
            target_char.inventory.append(item.id)
        if target_map and item.id not in target_map.entities.items:
            target_map.entities.items.append(item.id)

        if checker.check_item_relationships(item, characters, maps):
            print(f"[IOSystem] 物品关系一致性检查失败: {item.id}")
            return ERROR_OTHER

        return self._save_entities(characters, maps, [item])

    def _save_character_with_inventory_sync(self, character: Character) -> int:
        """保存角色并同步背包物品位置。"""
        checker = ConsistencyChecker()
        characters = self._get_all_characters()
        maps = self._get_all_maps()
        items = self._get_all_items()

        current_character = next((char for char in characters if char.id == character.id), character)
        item_lookup = {item.id: item for item in items}

        desired_inventory: List[str] = []
        seen = set()
        for item_id in list(character.inventory):
            if not isinstance(item_id, str):
                return ERROR_OPERATION_INVALID
            if item_id not in item_lookup:
                return ERROR_ID_NOT_FOUND
            if item_id not in seen:
                seen.add(item_id)
                desired_inventory.append(item_id)

        previous_inventory = set(current_character.inventory)
        current_character.inventory = desired_inventory

        added_item_ids = set(desired_inventory) - previous_inventory
        removed_item_ids = previous_inventory - set(desired_inventory)

        for item_id in added_item_ids:
            item = item_lookup[item_id]
            for other_character in characters:
                if other_character.id != current_character.id and item_id in other_character.inventory:
                    other_character.inventory = [value for value in other_character.inventory if value != item_id]
            for map_obj in maps:
                if item_id in map_obj.entities.items:
                    map_obj.entities.items = [value for value in map_obj.entities.items if value != item_id]
            item.location = current_character.id

        for item_id in removed_item_ids:
            item = item_lookup[item_id]
            if item.location == current_character.id:
                item.location = ""

        affected_items = [item_lookup[item_id] for item_id in sorted(added_item_ids | removed_item_ids)]
        if affected_items:
            for item in affected_items:
                if checker.check_item_relationships(item, characters, maps):
                    print(f"[IOSystem] 背包同步后的一致性检查失败: {item.id}")
                    return ERROR_OTHER

        characters = [current_character if char.id == current_character.id else char for char in characters]
        return self._save_entities([current_character], maps, affected_items)
    
    def update_map_field(self, map_id: str, field: str, value: Any) -> int:
        """更新地图指定字段"""
        map_obj = self.get_map(map_id)
        if not map_obj:
            return ERROR_ID_NOT_FOUND
        
        try:
            parts = field.split(".")
            obj = map_obj
            for part in parts[:-1]:
                if hasattr(obj, part):
                    obj = getattr(obj, part)
                else:
                    return ERROR_FIELD_NOT_FOUND
            
            last_part = parts[-1]
            if hasattr(obj, last_part):
                setattr(obj, last_part, value)
            else:
                return ERROR_FIELD_NOT_FOUND
            
            return self.save_map(map_obj)
        except Exception as e:
            print(f"[IOSystem] 更新地图字段 {map_id}.{field} 失败: {e}")
            return ERROR_OTHER
    
    def update_map_description(self, map_id: str, description: str) -> int:
        """更新地图的public描述（便捷方法）"""
        map_obj = self.get_map(map_id)
        if not map_obj:
            return ERROR_ID_NOT_FOUND
        
        map_obj.description.add_public_description(description)
        return self.save_map(map_obj)
    
    def delete_map(self, map_id: str) -> int:
        """删除地图"""
        try:
            if self.mode == "sqlite":
                orm_obj = self._session.query(MapORM).filter_by(id=map_id).first()
                if orm_obj:
                    self._session.delete(orm_obj)
                    self._session.commit()
                    return ERROR_SUCCESS
                return ERROR_ID_NOT_FOUND
            else:  # json mode
                file_path = self.json_dir / "maps" / f"{map_id}.json"
                if file_path.exists():
                    file_path.unlink()
                    return ERROR_SUCCESS
                return ERROR_ID_NOT_FOUND
        except Exception as e:
            print(f"[IOSystem] 删除地图 {map_id} 失败: {e}")
            if self.mode == "sqlite":
                self._session.rollback()
            return ERROR_OTHER
    
    # ============================================================
    # 批量变更接口
    # ============================================================
    
    def apply_changes(self, changes: List[StateChange]) -> List[int]:
        """
        批量应用变更
        
        Args:
            changes: 变更列表，每个元素为StateChange对象
            
        Returns:
            错误码列表，与changes一一对应
        """
        error_codes = []
        
        for change in changes:
            error_code = self._apply_single_change(change)
            error_codes.append(error_code)
        
        return error_codes

    def apply_state_change(self, change: StateChange) -> int:
        """应用单个变更（兼容引擎单条调用）。"""
        return self._apply_single_change(change)
    
    def _apply_single_change(self, change: StateChange) -> int:
        """应用单个变更"""
        try:
            # 确定实体类型
            entity_id = change.id
            
            if entity_id.startswith("char-"):
                entity = self.get_character(entity_id)
                if not entity:
                    return ERROR_ID_NOT_FOUND
                saver = self.save_character
            elif entity_id.startswith("item-"):
                entity = self.get_item(entity_id)
                if not entity:
                    return ERROR_ID_NOT_FOUND
                saver = self.save_item
            elif entity_id.startswith("map-"):
                entity = self.get_map(entity_id)
                if not entity:
                    return ERROR_ID_NOT_FOUND
                saver = self.save_map
            else:
                # 尝试所有类型
                entity = self.get_character(entity_id) or self.get_item(entity_id) or self.get_map(entity_id)
                if not entity:
                    return ERROR_ID_NOT_FOUND
                # 根据实际类型确定saver
                if entity_id.startswith("char-"):
                    saver = self.save_character
                elif entity_id.startswith("item-"):
                    saver = self.save_item
                else:
                    saver = self.save_map
            
            # 执行操作
            if change.operation == ChangeOperation.UPDATE:
                return self._do_update(entity, change.field, change.value, saver)
            elif change.operation == ChangeOperation.ADD:
                return self._do_add(entity, change.field, change.value, saver)
            elif change.operation == ChangeOperation.DELETE:
                return self._do_delete(entity, change.field, change.value, saver)
            elif change.operation == ChangeOperation.MOVE:
                return self._do_move(entity, change.field, change.value)
            else:
                return ERROR_OPERATION_INVALID
                
        except Exception as e:
            print(f"[IOSystem] 应用变更失败 {change}: {e}")
            return ERROR_OTHER
    
    def _do_update(self, entity: Any, field: str, value: Any, saver) -> int:
        """执行更新操作"""
        if isinstance(entity, Character) and field == "inventory":
            if not isinstance(value, list):
                return ERROR_OPERATION_INVALID
            normalized_inventory = []
            seen = set()
            for item_id in value:
                if not isinstance(item_id, str) or not self.get_item(item_id):
                    return ERROR_ID_NOT_FOUND
                if item_id not in seen:
                    seen.add(item_id)
                    normalized_inventory.append(item_id)
            entity.inventory = normalized_inventory
            return self._save_character_with_inventory_sync(entity)

        if isinstance(entity, Item) and field == "location":
            if not isinstance(value, str):
                return ERROR_OPERATION_INVALID
            if value and not self.get_character(value) and not self.get_map(value):
                return ERROR_ID_NOT_FOUND
            entity.location = value
            return self._save_item_with_relationship_sync(entity)

        parts = field.split(".")
        obj = entity
        
        for part in parts[:-1]:
            if hasattr(obj, part):
                obj = getattr(obj, part)
            else:
                return ERROR_FIELD_NOT_FOUND
        
        last_part = parts[-1]
        if hasattr(obj, last_part):
            if field == "description.public":
                setattr(obj, last_part, self._normalize_public_description_value(value))
            elif field == "neighbors":
                setattr(obj, last_part, self._normalize_neighbors_value(value))
            else:
                setattr(obj, last_part, value)
        else:
            return ERROR_FIELD_NOT_FOUND
        
        result = saver(entity)
        return result if result is not None else ERROR_SUCCESS

    def _extract_move_target(self, value: Any) -> tuple[Optional[str], Optional[str]]:
        """Extract move target and optional source from move payload."""
        if isinstance(value, str):
            return value.strip(), None
        if isinstance(value, dict):
            to_value = value.get("to")
            from_value = value.get("from")
            target = str(to_value).strip() if isinstance(to_value, str) else ""
            source = str(from_value).strip() if isinstance(from_value, str) else None
            return target, source
        return "", None

    def _do_move(self, entity: Any, field: str, value: Any) -> int:
        """执行移动操作（角色或物品）。"""
        if field != "location":
            return ERROR_OPERATION_INVALID

        target_id, source_id = self._extract_move_target(value)
        if not target_id:
            return ERROR_OPERATION_INVALID

        if isinstance(entity, Character):
            if source_id and entity.location != source_id:
                return ERROR_OPERATION_INVALID
            if not self.get_map(target_id):
                return ERROR_ID_NOT_FOUND
            entity.location = target_id
            return self.save_character(entity)

        if isinstance(entity, Item):
            if source_id and entity.location != source_id:
                return ERROR_OPERATION_INVALID
            if not self.get_character(target_id) and not self.get_map(target_id):
                return ERROR_ID_NOT_FOUND
            entity.location = target_id
            return self._save_item_with_relationship_sync(entity)

        return ERROR_OPERATION_INVALID
    
    def _do_add(self, entity: Any, field: str, value: Any, saver) -> int:
        """执行添加操作（向数组添加元素）"""
        if isinstance(entity, Character) and field == "inventory":
            if not isinstance(value, str) or not self.get_item(value):
                return ERROR_ID_NOT_FOUND

        parts = field.split(".")
        obj = entity
        
        for part in parts:
            if hasattr(obj, part):
                obj = getattr(obj, part)
            else:
                return ERROR_FIELD_NOT_FOUND
        
        if isinstance(obj, list):
            if field == "description.public":
                obj.extend(self._normalize_public_description_value(value))
            elif field == "neighbors":
                obj.extend(self._normalize_neighbors_value(value))
            elif isinstance(value, list):
                obj.extend(value)
            else:
                obj.append(value)

            # 历史兼容：避免 entities.items/entities.characters 被污染为嵌套list
            if field in {"entities.items", "entities.characters"}:
                normalized = []
                seen = set()
                for one in list(obj):
                    if isinstance(one, str):
                        if one not in seen:
                            seen.add(one)
                            normalized.append(one)
                    elif isinstance(one, list):
                        for inner in one:
                            if isinstance(inner, str) and inner not in seen:
                                seen.add(inner)
                                normalized.append(inner)
                obj[:] = normalized
        else:
            return ERROR_OPERATION_INVALID
        
        result = saver(entity)
        return result if result is not None else ERROR_SUCCESS
    
    def _do_delete(self, entity: Any, field: str, value: Any, saver) -> int:
        """执行删除操作"""
        if field not in ALLOWED_DELETE_LIST_FIELDS:
            return ERROR_OPERATION_INVALID

        parts = field.split(".")
        obj = entity
        
        for part in parts[:-1]:
            if hasattr(obj, part):
                obj = getattr(obj, part)
            else:
                return ERROR_FIELD_NOT_FOUND
        
        last_part = parts[-1]
        if not hasattr(obj, last_part):
            return ERROR_FIELD_NOT_FOUND

        target = getattr(obj, last_part)
        if not isinstance(target, list):
            return ERROR_OPERATION_INVALID

        if isinstance(value, list):
            for one in value:
                if one in target:
                    target.remove(one)
        else:
            if value in target:
                target.remove(value)
        
        result = saver(entity)
        return result if result is not None else ERROR_SUCCESS
    
    # ============================================================
    # 游戏状态管理
    # ============================================================
    
    def save_game_state(self, game_state: GameState) -> int:
        """保存完整游戏状态"""
        try:
            # 保存所有实体
            for char in game_state.characters.values():
                result = self.save_character(char)
                if result != ERROR_SUCCESS:
                    print(f"[IOSystem] 保存游戏状态失败: 角色 {char.id} 保存错误码 {result}")
                    return result
            for item in game_state.items.values():
                result = self.save_item(item)
                if result != ERROR_SUCCESS:
                    print(f"[IOSystem] 保存游戏状态失败: 物品 {item.id} 保存错误码 {result}")
                    return result
            for map_obj in game_state.maps.values():
                result = self.save_map(map_obj)
                if result != ERROR_SUCCESS:
                    print(f"[IOSystem] 保存游戏状态失败: 地图 {map_obj.id} 保存错误码 {result}")
                    return result
            
            # 保存元数据
            meta = {
                "player_id": game_state.player_id,
                "current_scene_id": game_state.current_scene_id,
                "turn_order": game_state.turn_order,
                "turn_count": game_state.turn_count,
                "is_ended": game_state.is_ended
            }
            
            if self.mode == "sqlite":
                orm_obj = self._session.query(GameMetaORM).filter_by(key="game_state").first()
                if orm_obj:
                    orm_obj.value = json.dumps(meta)
                else:
                    orm_obj = GameMetaORM(key="game_state", value=json.dumps(meta))
                    self._session.add(orm_obj)
                self._session.commit()
            else:  # json mode
                meta_path = self.json_dir / "game_state.json"
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2, ensure_ascii=False)
            
            return ERROR_SUCCESS
        except Exception as e:
            print(f"[IOSystem] 保存游戏状态失败: {e}")
            if self.mode == "sqlite":
                self._session.rollback()
            return ERROR_OTHER
    
    def load_game_state(self) -> Optional[GameState]:
        """加载完整游戏状态"""
        try:
            # 加载元数据
            if self.mode == "sqlite":
                orm_obj = self._session.query(GameMetaORM).filter_by(key="game_state").first()
                if not orm_obj:
                    return None
                meta = json.loads(orm_obj.value)
            else:  # json mode
                meta_path = self.json_dir / "game_state.json"
                if not meta_path.exists():
                    return None
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            
            # 加载所有实体
            game_state = GameState(
                player_id=meta.get("player_id"),
                current_scene_id=meta.get("current_scene_id"),
                turn_order=meta.get("turn_order", []),
                turn_count=meta.get("turn_count", 0),
                is_ended=meta.get("is_ended", False)
            )
            
            # 从数据库加载所有实体（简化实现：加载所有）
            if self.mode == "sqlite":
                for orm_char in self._session.query(CharacterORM).all():
                    char = Character(**json.loads(orm_char.data))
                    game_state.characters[char.id] = char
                for orm_item in self._session.query(ItemORM).all():
                    item = Item(**json.loads(orm_item.data))
                    game_state.items[item.id] = item
                for orm_map in self._session.query(MapORM).all():
                    map_obj = Map(**json.loads(orm_map.data))
                    game_state.maps[map_obj.id] = map_obj
            else:  # json mode
                for char_file in (self.json_dir / "characters").glob("*.json"):
                    with open(char_file, "r", encoding="utf-8") as f:
                        char = Character(**json.load(f))
                        game_state.characters[char.id] = char
                for item_file in (self.json_dir / "items").glob("*.json"):
                    with open(item_file, "r", encoding="utf-8") as f:
                        item = Item(**json.load(f))
                        game_state.items[item.id] = item
                for map_file in (self.json_dir / "maps").glob("*.json"):
                    with open(map_file, "r", encoding="utf-8") as f:
                        map_obj = Map(**json.load(f))
                        game_state.maps[map_obj.id] = map_obj
            
            return game_state
        except Exception as e:
            print(f"[IOSystem] 加载游戏状态失败: {e}")
            return None
    
    def clear_current_events(self) -> int:
        """
        清空所有角色的current_event
        每轮开始时调用
        """
        try:
            if self.mode == "sqlite":
                for orm_char in self._session.query(CharacterORM).all():
                    char = Character(**json.loads(orm_char.data))
                    char.memory.clear_current()
                    orm_char.data = char.model_dump_json()
                self._session.commit()
            else:  # json mode
                for char_file in (self.json_dir / "characters").glob("*.json"):
                    with open(char_file, "r", encoding="utf-8") as f:
                        char = Character(**json.load(f))
                    char.memory.clear_current()
                    with open(char_file, "w", encoding="utf-8") as f:
                        f.write(char.model_dump_json(indent=2))
            
            return ERROR_SUCCESS
        except Exception as e:
            print(f"[IOSystem] 清空current_event失败: {e}")
            if self.mode == "sqlite":
                self._session.rollback()
            return ERROR_OTHER
    
    def close(self):
        """关闭IO系统，释放资源"""
        if self.mode == "sqlite" and self._session:
            self._session.close()


# ============================================================
# 便捷工厂函数
# ============================================================

def create_io_system(db_path: str = "data/game.db", mode: str = "sqlite") -> IOSystem:
    """创建IO系统实例"""
    return IOSystem(db_path=db_path, mode=mode)


# 导出
__all__ = [
    "IOSystem",
    "create_io_system",
    "ERROR_SUCCESS",
    "ERROR_ID_NOT_FOUND",
    "ERROR_FIELD_NOT_FOUND",
    "ERROR_OPERATION_INVALID",
    "ERROR_OTHER",
]
