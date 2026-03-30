"""世界数据加载器。

支持两种模式：
1. 新版目录化世界：config/world/<world_name>/world.json + 分文件实体目录
2. 旧版单表文件：config/world/characters.json, items.json, maps.json
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, List

from src.data.models import (
    Character, Item, Map, GameState, Description,
    CharacterAttributes, CharacterStatus, Memory,
    MapNeighbor, MapEntities
)
from src.data.io_system import IOSystem


@dataclass
class WorldBundle:
    """完整世界加载结果。"""

    game_state: GameState
    world_name: str
    end_condition: str
    npc_response_mode: str = "unified"
    narrative_window: int = 5
    npc_director_use_llm: bool = True
    narrative_merge_use_llm: bool = True


class WorldLoader:
    """
    世界数据加载器
    
    从config/world/目录下的JSON文件加载初始游戏数据，
    并将其导入到IO系统和GameState中。
    """
    
    def __init__(self, io_system: IOSystem, config_dir: str = "config/world"):
        """
        初始化世界加载器
        
        Args:
            io_system: IO系统实例，用于存储加载的数据
            config_dir: 配置文件目录路径，默认为"config/world"
        """
        self.io = io_system
        self.config_dir = Path(config_dir)
        self.world_name = "default"
        self.world_dir = self.config_dir
        self.manifest: Dict[str, Any] = {}
        self._characters: Dict[str, Character] = {}
        self._items: Dict[str, Item] = {}
        self._maps: Dict[str, Map] = {}
    
    def load_world_bundle(
        self,
        player_name: Optional[str] = None,
        world_name: str = "mysterious_library"  
    ) -> WorldBundle:
        """从配置加载完整世界，并返回带元信息的结果。"""
        self._reset()
        self.world_name = world_name
        self.world_dir = self._resolve_world_dir(world_name)
        self.manifest = self._load_manifest()

        # 加载各类数据
        self._load_characters(player_name)
        self._load_items()
        self._load_maps()

        player_id = self._resolve_player_id()
        start_map_id = self._resolve_start_map_id(player_id)
        turn_order = self._resolve_turn_order(player_id)

        game_state = GameState(
            characters=self._characters,
            items=self._items,
            maps=self._maps,
            player_id=player_id,
            current_scene_id=start_map_id,
            turn_order=turn_order,
            turn_count=0,
            is_ended=False
        )

        self._save_to_io_system()

        return WorldBundle(
            game_state=game_state,
            world_name=self.world_name,
            end_condition=self.manifest.get("end_condition", "玩家死亡或达成剧情结局"),
            npc_response_mode=self._resolve_npc_response_mode(),
            narrative_window=self._resolve_narrative_window(),
            npc_director_use_llm=self._resolve_bool_field("npc_director_use_llm", True),
            narrative_merge_use_llm=self._resolve_bool_field("narrative_merge_use_llm", True),
        )

    def load_world_from_config(
        self,
        player_name: Optional[str] = None,
        world_name: str = "mysterious_library"
    ) -> GameState:
        """
        从配置文件加载完整的世界数据
        
        Args:
            player_name: 玩家自定义名称（可选），如果不提供则使用默认名称
            
        Returns:
            GameState: 初始化好的游戏状态对象
        """
        bundle = self.load_world_bundle(player_name=player_name, world_name=world_name)
        return bundle.game_state

    def _reset(self):
        self._characters = {}
        self._items = {}
        self._maps = {}

    def _resolve_world_dir(self, world_name: str) -> Path:
        candidate = self.config_dir / world_name
        if candidate.exists() and candidate.is_dir():
            return candidate
        return self.config_dir

    def _load_manifest(self) -> Dict[str, Any]:
        manifest_path = self.world_dir / "world.json"
        if not manifest_path.exists():
            return {}

        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.world_name = data.get("world_name", self.world_name)
        return data

    def _iter_entity_files(self, entity_type: str) -> List[Path]:
        """优先读取目录化实体，其次回退旧版单表文件。"""
        entity_dir = self.world_dir / entity_type
        if entity_dir.exists() and entity_dir.is_dir():
            return sorted(entity_dir.glob("*.json"))

        single_file = self.world_dir / f"{entity_type}.json"
        if single_file.exists():
            return [single_file]

        return []
    
    def _load_characters(self, player_name: Optional[str] = None):
        """加载角色数据"""
        files = self._iter_entity_files("characters")
        if not files:
            print("[WorldLoader] 警告: 未找到角色配置")
            return

        try:
            for file_path in files:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # 兼容两种格式：单体对象 或 {"characters": [...]} 聚合对象
                if isinstance(data, dict) and "characters" in data:
                    char_list = data.get("characters", [])
                else:
                    char_list = [data]

                for char_data in char_list:
                # 如果提供了玩家名称，更新玩家角色名称
                    if player_name and char_data.get("is_player"):
                        char_data["name"] = player_name
                
                    # 构建Description对象
                    desc_data = char_data.get("description", {})
                    description = Description(
                        public=desc_data.get("public", []),
                        hint=desc_data.get("hint", "")
                    )
                
                    # 构建Attributes对象
                    attr_data = char_data.get("attributes", {})
                    attributes = CharacterAttributes(
                        str=attr_data.get("str", 10),
                        con=attr_data.get("con", 10),
                        siz=attr_data.get("siz", 10),
                        dex=attr_data.get("dex", 10),
                        app=attr_data.get("app", 10),
                        int=attr_data.get("int", 10),
                        pow=attr_data.get("pow", 10),
                        edu=attr_data.get("edu", 10)
                    )
                
                    # 构建Status对象
                    status_data = char_data.get("status", {})
                    status = CharacterStatus(
                        hp=status_data.get("hp", 10),
                        max_hp=status_data.get("max_hp", status_data.get("hp", 10)),
                        san=status_data.get("san", 50),
                        lucky=status_data.get("lucky", 50)
                    )
                
                    # 构建Memory对象
                    memory_data = char_data.get("memory", {})
                    memory = Memory(
                        current_event=memory_data.get("current_event", ""),
                        log=memory_data.get("log", [])
                    )
                
                    # 创建Character对象
                    character = Character(
                        id=char_data["id"],
                        name=char_data["name"],
                        basic_info=char_data.get("basic_info", ""),
                        description=description,
                        location=char_data.get("location", ""),
                        inventory=char_data.get("inventory", []),
                        status=status,
                        attributes=attributes,
                        memory=memory,
                        is_player=char_data.get("is_player", False)
                    )
                
                    self._characters[character.id] = character
            
            print(f"[WorldLoader] 成功加载 {len(self._characters)} 个角色")
            
        except Exception as e:
            print(f"[WorldLoader] 加载角色数据失败: {e}")
            raise
    
    def _load_items(self):
        """加载物品数据"""
        files = self._iter_entity_files("items")
        if not files:
            print("[WorldLoader] 警告: 未找到物品配置")
            return

        try:
            for file_path in files:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if isinstance(data, dict) and "items" in data:
                    item_list = data.get("items", [])
                else:
                    item_list = [data]

                for item_data in item_list:
                # 构建Description对象
                    desc_data = item_data.get("description", {})
                    description = Description(
                        public=desc_data.get("public", []),
                        hint=desc_data.get("hint", "")
                    )
                
                    # 创建Item对象
                    item = Item(
                        id=item_data["id"],
                        name=item_data["name"],
                        description=description,
                        location=item_data.get("location", ""),
                        is_portable=item_data.get("is_portable", True)
                    )
                
                    self._items[item.id] = item
            
            print(f"[WorldLoader] 成功加载 {len(self._items)} 个物品")
            
        except Exception as e:
            print(f"[WorldLoader] 加载物品数据失败: {e}")
            raise
    
    def _load_maps(self):
        """加载地图数据"""
        files = self._iter_entity_files("maps")
        if not files:
            print("[WorldLoader] 警告: 未找到地图配置")
            return

        try:
            for file_path in files:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if isinstance(data, dict) and "maps" in data:
                    map_list = data.get("maps", [])
                else:
                    map_list = [data]

                for map_data in map_list:
                # 构建Description对象
                    desc_data = map_data.get("description", {})
                    description = Description(
                        public=desc_data.get("public", []),
                        hint=desc_data.get("hint", "")
                    )
                
                    # 构建Neighbors列表
                    neighbors = []
                    for neighbor_data in map_data.get("neighbors", []):
                        neighbor = MapNeighbor(
                            id=neighbor_data["id"],
                            direction=neighbor_data["direction"],
                            description=neighbor_data.get("description", "")
                        )
                        neighbors.append(neighbor)
                
                    # 构建Entities对象
                    entities_data = map_data.get("entities", {})
                    entities = MapEntities(
                        characters=entities_data.get("characters", []),
                        items=entities_data.get("items", [])
                    )
                
                    # 创建Map对象
                    map_obj = Map(
                        id=map_data["id"],
                        name=map_data["name"],
                        parent_id=map_data.get("parent_id"),
                        description=description,
                        neighbors=neighbors,
                        entities=entities
                    )
                
                    self._maps[map_obj.id] = map_obj
            
            print(f"[WorldLoader] 成功加载 {len(self._maps)} 个地图")
            
        except Exception as e:
            print(f"[WorldLoader] 加载地图数据失败: {e}")
            raise
    
    def _save_to_io_system(self):
        """将加载的数据保存到IO系统"""
        # 保存角色
        for character in self._characters.values():
            result = self.io.save_character(character)
            if result != 0:
                print(f"[WorldLoader] 警告: 保存角色 {character.id} 失败，错误码: {result}")
        
        # 保存物品
        for item in self._items.values():
            result = self.io.save_item(item)
            if result != 0:
                print(f"[WorldLoader] 警告: 保存物品 {item.id} 失败，错误码: {result}")
        
        # 保存地图
        for map_obj in self._maps.values():
            result = self.io.save_map(map_obj)
            if result != 0:
                print(f"[WorldLoader] 警告: 保存地图 {map_obj.id} 失败，错误码: {result}")
        
        print(f"[WorldLoader] 数据已保存到IO系统")

    def _resolve_player_id(self) -> Optional[str]:
        player_id = self.manifest.get("player_id")
        if player_id and player_id in self._characters:
            return player_id

        for char in self._characters.values():
            if char.is_player:
                return char.id

        return next(iter(self._characters), None)

    def _resolve_start_map_id(self, player_id: Optional[str]) -> Optional[str]:
        start_map_id = self.manifest.get("start_map_id")
        if start_map_id and start_map_id in self._maps:
            return start_map_id

        if player_id and player_id in self._characters:
            player_location = self._characters[player_id].location
            if player_location in self._maps:
                return player_location

        return next(iter(self._maps), None)

    def _resolve_turn_order(self, player_id: Optional[str]) -> List[str]:
        configured = self.manifest.get("turn_order")
        if isinstance(configured, list):
            return [cid for cid in configured if cid in self._characters]

        if player_id:
            npc_ids = [cid for cid in self._characters.keys() if cid != player_id]
            return [player_id] + npc_ids
        return list(self._characters.keys())

    def _resolve_npc_response_mode(self) -> str:
        configured = str(self.manifest.get("npc_response_mode", "unified") or "unified").strip().lower()
        if configured != "unified":
            print(f"[WorldLoader] npc_response_mode '{configured}' 已废弃，已收敛为 unified")
        return "unified"

    def _resolve_narrative_window(self) -> int:
        configured = self.manifest.get("narrative_window", 5)
        try:
            value = int(configured)
        except (TypeError, ValueError):
            return 5

        return max(1, value)

    def _resolve_bool_field(self, field_name: str, default: bool) -> bool:
        raw_value = self.manifest.get(field_name, default)
        if isinstance(raw_value, bool):
            return raw_value
        if isinstance(raw_value, str):
            normalized = raw_value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return bool(default)
    
    def get_character(self, char_id: str) -> Optional[Character]:
        """获取指定角色"""
        return self._characters.get(char_id)
    
    def get_item(self, item_id: str) -> Optional[Item]:
        """获取指定物品"""
        return self._items.get(item_id)
    
    def get_map(self, map_id: str) -> Optional[Map]:
        """获取指定地图"""
        return self._maps.get(map_id)
    
    def list_characters(self) -> Dict[str, Character]:
        """获取所有角色"""
        return self._characters.copy()
    
    def list_items(self) -> Dict[str, Item]:
        """获取所有物品"""
        return self._items.copy()
    
    def list_maps(self) -> Dict[str, Map]:
        """获取所有地图"""
        return self._maps.copy()


def load_initial_world(
    io_system: IOSystem,
    player_name: Optional[str] = None,
    world_name: str = "mysterious_library"
) -> GameState:
    """
    便捷函数：加载初始世界数据
    
    Args:
        io_system: IO系统实例
        player_name: 玩家自定义名称（可选）
        
    Returns:
        GameState: 初始化好的游戏状态
        
    Example:
        >>> from src.data.io_system import IOSystem
        >>> io = IOSystem(db_path="data/game.db", mode="sqlite")
        >>> game_state = load_initial_world(io, player_name="张三")
    """
    loader = WorldLoader(io_system)
    return loader.load_world_from_config(player_name, world_name=world_name)


def load_initial_world_bundle(
    io_system: IOSystem,
    player_name: Optional[str] = None,
    world_name: str = "mysterious_library"   
) -> WorldBundle:
    """便捷函数：加载世界及其元配置（结局条件等）。"""
    loader = WorldLoader(io_system)
    return loader.load_world_bundle(player_name=player_name, world_name=world_name)
