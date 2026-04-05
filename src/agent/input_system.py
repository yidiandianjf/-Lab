"""
Input系统 - 玩家输入处理模块

负责接收并初步处理玩家输入：
1. 区分基础指令（以\开头）和自然语言
2. 处理基础指令并返回处理结果
3. 将自然语言输入传递给DM Agent
"""

import logging
from typing import Optional, Tuple, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

from src.data.models import (
    Character, Item, Map, GameState, StateChange, ChangeOperation
)
from src.data.io_system import IOSystem
from src.security.input_screener import InputScreener

# 配置日志
logger = logging.getLogger(__name__)


class InputType(Enum):
    """输入类型枚举"""
    BASIC_COMMAND = "basic_command"  # 基础指令
    NATURAL_LANGUAGE = "natural_language"  # 自然语言


@dataclass
class InputResult:
    """??????"""
    input_type: InputType
    command: Optional[str] = None  # ??????
    args: Optional[List[str]] = None  # ????
    natural_input: Optional[str] = None  # ??????
    direct_response: Optional[str] = None  # ??????????????
    changes: Optional[List[StateChange]] = None  # ??????
    engine_action: Optional[Dict[str, Any]] = None  # ??????????????


class InputSystem:
    """
    Input系统 - 玩家输入处理器
    
    功能：
    - 解析玩家输入类型
    - 执行基础指令
    - 传递自然语言给DM Agent
    """
    
    # 基础指令列表
    BASIC_COMMANDS = {
        "look": "???????????",
        "inventory": "????",
        "pickup": "????",
        "drop": "????",
        "use": "????",
        "give": "???????",
        "move": "???????",
        "go": "???????",
        "status": "??????",
        "where": "??????",
        "save": "????",
        "load": "????",
        "reset": "????",
        "debug": "??????",
        "screen": "??AI??",
        "speed": "??????",
        "help": "????",
        "exit": "????",
    }
    
    def __init__(self, io_system: IOSystem, screener: Optional[InputScreener] = None):
        """
        初始化Input系统
        
        Args:
            io_system: IO系统实例，用于数据操作
        """
        self.io = io_system
        self.screener = screener or InputScreener()
        logger.info("Input系统初始化完成")

    def _summarize_text(self, text: str, limit: int = 60) -> str:
        """Summarize text safely to avoid displaying half-sentence fragments."""
        normalized = " ".join((text or "").replace("\n", "；").split())
        if len(normalized) <= limit:
            return normalized

        cut = normalized[:limit]
        best_punct = max(cut.rfind("。"), cut.rfind("；"), cut.rfind("！"), cut.rfind("？"))
        if best_punct >= int(limit * 0.6):
            return cut[: best_punct + 1]
        logger.info("Input系统初始化完成")

    @staticmethod
    def _player_scene(player: Optional[Character]) -> str:
        """Infer demo world from the active player identity."""
        if not player:
            return ""
        player_id = str(getattr(player, "id", "") or "").strip().lower()
        player_name = str(getattr(player, "name", "") or "").strip()
        if player_id == "char-daiyu-01" or player_name == "林黛玉":
            return "daiyu_enters_jia"
        if player_id == "char-liubei-01" or player_name == "刘备":
            return "sanguo_mao_lu"
        return ""

    @classmethod
    def _is_education_scene(cls, player: Optional[Character]) -> bool:
        return cls._player_scene(player) == "daiyu_enters_jia"

    def _status_labels(self, player: Optional[Character]) -> Dict[str, str]:
        """Return display labels for status fields."""
        scene = self._player_scene(player)
        if scene == "daiyu_enters_jia":
            return {
                "hp": "体力",
                "san": "心绪",
                "lucky": "机缘",
            }
        if scene == "sanguo_mao_lu":
            return {
                "hp": "体魄",
                "san": "心志",
                "lucky": "机运",
            }
        return {
            "hp": "HP",
            "san": "SAN",
            "lucky": "幸运",
        }

    def parse_input(self, user_input: str) -> InputResult:
        """
        ??????
        
        Args:
            user_input: ???????
            
        Returns:
            InputResult: ????????
        """
        user_input = user_input.strip()
        
        if not user_input:
            return InputResult(
                input_type=InputType.BASIC_COMMAND,
                direct_response="请输入内容。"
            )

        def _blocked_response(reason: str) -> InputResult:
            logger.warning("输入被拦截: %s", reason)
            return InputResult(
                input_type=InputType.BASIC_COMMAND,
                direct_response="您的输入未通过安全检查，请修改后重试。"
            )

        # ???/?????????????????? AI ??????
        if user_input.startswith("\\"):
            return self._parse_command(user_input[1:])

        # ?? /help ???????????????????
        if user_input.startswith("/"):
            maybe = self._parse_command(user_input[1:])
            if maybe.command in self.BASIC_COMMANDS:
                return maybe

        # ??????
        screen_result = self.screener.screen(
            user_input,
            context={"channel": "natural_language", "bypass_ai": False}
        )
        if screen_result.is_blocked:
            return _blocked_response(screen_result.reason)

        return InputResult(
            input_type=InputType.NATURAL_LANGUAGE,
            natural_input=user_input
        )
    
    def _parse_command(self, command_str: str) -> InputResult:
        """
        解析基础指令
        
        Args:
            command_str: 去除\后的指令字符串
            
        Returns:
            InputResult: 解析结果
        """
        parts = command_str.strip().split()
        if not parts:
            return InputResult(
                input_type=InputType.BASIC_COMMAND,
                direct_response="空指令，请输入具体指令。"
            )
        
        command = parts[0].lower()
        if command == "go":
            command = "move"
        args = parts[1:] if len(parts) > 1 else []
        
        return InputResult(
            input_type=InputType.BASIC_COMMAND,
            command=command,
            args=args,
            natural_input=None
        )
    
    def execute_command(
        self,
        command: str,
        args: List[str],
        game_state: GameState
    ) -> InputResult:
        """
        执行基础指令
        
        Args:
            command: 指令名称
            args: 指令参数
            game_state: 当前游戏状态
            
        Returns:
            InputResult: 包含处理结果和可能的变更
        """
        if command not in self.BASIC_COMMANDS:
            return InputResult(
                input_type=InputType.BASIC_COMMAND,
                command=command,
                args=args,
                direct_response=f"未知指令: {command}。输入 \\help 查看可用指令。",
                changes=[]
            )
        
        # 获取玩家角色
        player = game_state.get_player()
        if not player:
            return InputResult(
                input_type=InputType.BASIC_COMMAND,
                command=command,
                args=args,
                direct_response="错误：未找到玩家角色",
                changes=[]
            )
        
        # 执行对应指令
        handler = getattr(self, f"_cmd_{command}", None)
        if handler:
            payload = handler(args, player, game_state)
            engine_action = None
            if isinstance(payload, tuple) and len(payload) == 3:
                response, changes, engine_action = payload
            else:
                response, changes = payload
            return InputResult(
                input_type=InputType.BASIC_COMMAND,
                command=command,
                args=args,
                direct_response=response,
                changes=changes or [],
                engine_action=engine_action,
            )
        
        return InputResult(
            input_type=InputType.BASIC_COMMAND,
            command=command,
            args=args,
            direct_response=f"指令 {command} 尚未实现",
            changes=[]
        )
    
    def _cmd_look(
        self,
        args: List[str],
        player: Character,
        game_state: GameState
    ) -> Tuple[str, List[StateChange]]:
        """
        查看场景或目标
        
        Args:
            args: 查看目标（可选）
            player: 玩家角色
            game_state: 游戏状态
            
        Returns:
            Tuple[描述文本, 变更列表]
        """
        changes = []
        
        # 获取当前地图
        current_map = game_state.get_current_map()
        if not current_map:
            return "错误：当前不在任何场景中", changes
        
        # 如果没有指定目标，查看当前场景
        if not args:
            # 构建场景描述
            description = f"【{current_map.name}】\n"
            description += current_map.description.get_public_text() + "\n\n"
            
            # 显示相邻场景
            if current_map.neighbors:
                description += "【可通往】\n"
                for neighbor in current_map.neighbors:
                    description += f"  {neighbor.direction}: {neighbor.description}\n"
            
            # 显示场景中的角色
            if current_map.entities.characters:
                description += "\n【在场角色】\n"
                for char_id in current_map.entities.characters:
                    if char_id != player.id:
                        char = game_state.characters.get(char_id)
                        if char:
                            desc = char.description.get_public_text()
                            description += f"  • {char.name}: {self._summarize_text(desc, limit=90)}\n"
            
            # 显示场景中的物品
            if current_map.entities.items:
                description += "\n【可见物品】\n"
                for item_id in current_map.entities.items:
                    item = game_state.items.get(item_id)
                    if item:
                        desc = item.description.get_public_text()
                        description += f"  • {item.name}: {self._summarize_text(desc, limit=80)}\n"
            
            return description, changes
        
        # 查看指定目标
        target_name = " ".join(args).lower()
        
        # 搜索角色
        for char_id in current_map.entities.characters:
            char = game_state.characters.get(char_id)
            if char and (target_name in char.name.lower() or target_name in char_id.lower()):
                labels = self._status_labels(player)
                description = f"【{char.name}】\n"
                description += char.description.get_public_text() + "\n"
                description += (
                    f"\n状态: {labels['hp']} {char.status.hp}/{char.status.max_hp}, "
                    f"{labels['san']} {char.status.san}, {labels['lucky']} {char.status.lucky}"
                )
                return description, changes
        
        # 搜索物品
        for item_id in current_map.entities.items:
            item = game_state.items.get(item_id)
            if item and (target_name in item.name.lower() or target_name in item_id.lower()):
                description = f"【{item.name}】\n"
                description += item.description.get_public_text()
                return description, changes
        
        # 搜索玩家背包
        for item_id in player.inventory:
            item = game_state.items.get(item_id)
            if item and (target_name in item.name.lower() or target_name in item_id.lower()):
                description = f"【{item.name}】(在背包中)\n"
                description += item.description.get_public_text()
                return description, changes
        
        return f"未找到目标: {target_name}", changes
    
    def _cmd_inventory(
        self,
        args: List[str],
        player: Character,
        game_state: GameState
    ) -> Tuple[str, List[StateChange]]:
        """
        查看背包
        
        Args:
            args: 无参数
            player: 玩家角色
            game_state: 游戏状态
            
        Returns:
            Tuple[描述文本, 变更列表]
        """
        changes = []
        
        description = f"【{player.name}的背包】\n"
        
        if not player.inventory:
            description += "背包是空的。"
            return description, changes
        
        for item_id in player.inventory:
            item = game_state.items.get(item_id)
            if item:
                desc = self._summarize_text(item.description.get_public_text(), limit=50)
                description += f"  • {item.name}: {desc}\n"
            else:
                description += f"  • [未知物品: {item_id}]\n"
        
        return description, changes
    
    def _cmd_pickup(
        self,
        args: List[str],
        player: Character,
        game_state: GameState
    ) -> Tuple[str, List[StateChange]]:
        """
        捡起物品
        
        Args:
            args: 物品名称
            player: 玩家角色
            game_state: 游戏状态
            
        Returns:
            Tuple[描述文本, 变更列表]
        """
        changes = []
        
        if not args:
            return "请指定要捡起的物品名。用法: \\pickup <物品名>", changes
        
        item_name = " ".join(args).lower()
        current_map = game_state.get_current_map()
        
        if not current_map:
            return "错误：当前不在任何场景中", changes
        
        # 在场景中寻找物品
        for item_id in list(current_map.entities.items):
            item = game_state.items.get(item_id)
            if item and (item_name in item.name.lower() or item_name in item_id.lower()):
                # 检查是否可携带
                if not item.is_portable:
                    return f"{item.name}无法被携带。", changes
                
                # 创建变更：物品位置改为玩家
                changes.append(StateChange(
                    id=item_id,
                    field="location",
                    operation=ChangeOperation.UPDATE,
                    value=player.id
                ))
                
                # 创建变更：从场景移除物品
                new_items = [i for i in current_map.entities.items if i != item_id]
                changes.append(StateChange(
                    id=current_map.id,
                    field="entities.items",
                    operation=ChangeOperation.UPDATE,
                    value=new_items
                ))
                
                # 创建变更：添加到玩家背包
                new_inventory = player.inventory + [item_id]
                changes.append(StateChange(
                    id=player.id,
                    field="inventory",
                    operation=ChangeOperation.UPDATE,
                    value=new_inventory
                ))
                
                return f"你捡起了 {item.name}。", changes
        
        return f"场景中找不到物品: {item_name}", changes
    
    def _cmd_drop(
        self,
        args: List[str],
        player: Character,
        game_state: GameState
    ) -> Tuple[str, List[StateChange]]:
        """
        放下物品
        
        Args:
            args: 物品名称
            player: 玩家角色
            game_state: 游戏状态
            
        Returns:
            Tuple[描述文本, 变更列表]
        """
        changes = []
        
        if not args:
            return "请指定要放下的物品名。用法: \\drop <物品名>", changes
        
        item_name = " ".join(args).lower()
        current_map = game_state.get_current_map()
        
        if not current_map:
            return "错误：当前不在任何场景中", changes
        
        # 在玩家背包中寻找物品
        for item_id in list(player.inventory):
            item = game_state.items.get(item_id)
            if item and (item_name in item.name.lower() or item_name in item_id.lower()):
                # 创建变更：物品位置改为场景
                changes.append(StateChange(
                    id=item_id,
                    field="location",
                    operation=ChangeOperation.UPDATE,
                    value=current_map.id
                ))
                
                # 创建变更：从玩家背包移除
                new_inventory = [i for i in player.inventory if i != item_id]
                changes.append(StateChange(
                    id=player.id,
                    field="inventory",
                    operation=ChangeOperation.UPDATE,
                    value=new_inventory
                ))
                
                # 创建变更：添加到场景
                new_items = current_map.entities.items + [item_id]
                changes.append(StateChange(
                    id=current_map.id,
                    field="entities.items",
                    operation=ChangeOperation.UPDATE,
                    value=new_items
                ))
                
                return f"你放下了 {item.name}。", changes
        
        return f"背包中没有物品: {item_name}", changes
    
    def _cmd_status(
        self,
        args: List[str],
        player: Character,
        game_state: GameState
    ) -> Tuple[str, List[StateChange]]:
        """
        查看自身状态
        
        Args:
            args: 无参数
            player: 玩家角色
            game_state: 游戏状态
            
        Returns:
            Tuple[描述文本, 变更列表]
        """
        changes = []
        labels = self._status_labels(player)
        
        description = f"【{player.name}】\n"
        description += f"简介: {player.basic_info}\n\n"
        
        # 状态
        description += "【状态】\n"
        description += f"  {labels['hp']}: {player.status.hp}/{player.status.max_hp}\n"
        description += f"  {labels['san']}: {player.status.san}/100\n"
        description += f"  {labels['lucky']}: {player.status.lucky}/99\n\n"
        
        # 属性
        description += "【属性】\n"
        description += f"  力量(STR): {player.attributes.str}\n"
        description += f"  体质(CON): {player.attributes.con}\n"
        description += f"  体型(SIZ): {player.attributes.siz}\n"
        description += f"  敏捷(DEX): {player.attributes.dex}\n"
        description += f"  外貌(APP): {player.attributes.app}\n"
        description += f"  智力(INT): {player.attributes.int}\n"
        description += f"  意志(POW): {player.attributes.pow}\n"
        description += f"  教育(EDU): {player.attributes.edu}\n\n"
        
        # 当前位置
        current_map = game_state.get_current_map()
        if current_map:
            description += f"【位置】{current_map.name}\n"
        
        return description, changes

    def _cmd_move(
        self,
        args: List[str],
        player: Character,
        game_state: GameState
    ) -> Tuple[str, List[StateChange]]:
        """移动到相邻场景，支持 `\\move to=<map_id>`、`\\move to <map_id>`、`\\move <map_id>`、`\\move <方向>`。"""
        changes = []

        current_map = game_state.get_current_map()
        if not current_map:
            return "错误：当前不在任何场景中", changes

        if not args:
            return "请指定目标。用法: \\move to=<map_id> 或 \\move <方向>", changes

        raw_target = " ".join(args).strip()
        normalized_target = raw_target
        lowered_raw = raw_target.lower()
        if lowered_raw.startswith("to="):
            normalized_target = raw_target[3:].strip()
        elif lowered_raw.startswith("to "):
            normalized_target = raw_target[3:].strip()

        target_neighbor = None
        for neighbor in current_map.neighbors:
            if normalized_target == neighbor.id:
                target_neighbor = neighbor
                break
            if normalized_target.lower() == neighbor.direction.lower():
                target_neighbor = neighbor
                break

        if not target_neighbor:
            return f"无法移动到目标: {normalized_target}（目标必须是相邻场景ID或方向）", changes

        target_map = game_state.maps.get(target_neighbor.id)
        if not target_map:
            return f"目标场景不存在: {target_neighbor.id}", changes

        changes.append(StateChange(
            id=player.id,
            field="location",
            operation=ChangeOperation.UPDATE,
            value=target_map.id
        ))

        return f"你移动到了 {target_map.name}。", changes

    def _cmd_where(
        self,
        args: List[str],
        player: Character,
        game_state: GameState
    ) -> Tuple[str, List[StateChange]]:
        """
        查看当前位置
        
        Args:
            args: 无参数
            player: 玩家角色
            game_state: 游戏状态
            
        Returns:
            Tuple[描述文本, 变更列表]
        """
        changes = []
        
        current_map = game_state.get_current_map()
        if not current_map:
            return "你似乎迷失在了虚空之中...", changes
        
        description = f"【当前位置】{current_map.name}\n\n"
        description += f"{current_map.description.get_public_text()}\n\n"
        
        # 显示可通往的方向
        if current_map.neighbors:
            description += "【可通往】\n"
            for neighbor in current_map.neighbors:
                description += f"  {neighbor.direction}: {neighbor.description}\n"
        
        return description, changes

    def _cmd_use(
        self,
        args: List[str],
        player: Character,
        game_state: GameState
    ) -> Tuple[str, List[StateChange]]:
        """使用物品（基础交互，复杂效果交由自然语言流程）。"""
        changes = []
        if not args:
            return "请指定要使用的物品名。用法: \\use <物品名>", changes

        item_name = " ".join(args).lower()
        for item_id in player.inventory:
            item = game_state.items.get(item_id)
            if item and (item_name in item.name.lower() or item_name in item_id.lower()):
                return f"你尝试使用 {item.name}。如需复杂效果，请直接用自然语言描述行动。", changes

        return f"背包中没有物品: {item_name}", changes

    def _cmd_give(
        self,
        args: List[str],
        player: Character,
        game_state: GameState
    ) -> Tuple[str, List[StateChange]]:
        """给予物品给场景内角色，格式：\\give <物品名> to <角色名>。"""
        changes = []
        if not args or "to" not in [a.lower() for a in args]:
            return "用法: \\give <物品名> to <角色名>", changes

        split_idx = [a.lower() for a in args].index("to")
        item_name = " ".join(args[:split_idx]).strip().lower()
        target_name = " ".join(args[split_idx + 1:]).strip().lower()

        if not item_name or not target_name:
            return "用法: \\give <物品名> to <角色名>", changes

        give_item_id = None
        for item_id in player.inventory:
            item = game_state.items.get(item_id)
            if item and (item_name in item.name.lower() or item_name in item_id.lower()):
                give_item_id = item_id
                break

        if not give_item_id:
            return f"背包中没有物品: {item_name}", changes

        current_map = game_state.get_current_map()
        if not current_map:
            return "错误：当前不在任何场景中", changes

        target_char = None
        for char_id in current_map.entities.characters:
            if char_id == player.id:
                continue
            char = game_state.characters.get(char_id)
            if char and (target_name in char.name.lower() or target_name in char_id.lower()):
                target_char = char
                break

        if not target_char:
            return f"未找到角色: {target_name}", changes

        # 物品位置改为目标角色
        changes.append(StateChange(
            id=give_item_id,
            field="location",
            operation=ChangeOperation.UPDATE,
            value=target_char.id
        ))
        # 玩家背包移除
        new_inventory = [i for i in player.inventory if i != give_item_id]
        changes.append(StateChange(
            id=player.id,
            field="inventory",
            operation=ChangeOperation.UPDATE,
            value=new_inventory
        ))
        # 目标角色背包追加
        target_inventory = target_char.inventory + [give_item_id]
        changes.append(StateChange(
            id=target_char.id,
            field="inventory",
            operation=ChangeOperation.UPDATE,
            value=target_inventory
        ))

        item = game_state.items.get(give_item_id)
        item_label = item.name if item else give_item_id
        return f"你把 {item_label} 交给了 {target_char.name}。", changes
    
    def _cmd_save(
        self,
        args: List[str],
        player: Character,
        game_state: GameState
    ) -> Tuple[str, List[StateChange]]:
        """
        保存进度
        
        Args:
            args: 存档名（可选）
            player: 玩家角色
            game_state: 游戏状态
            
        Returns:
            Tuple[描述文本, 变更列表]
        """
        changes = []
        
        save_name = args[0] if args else "auto_save"
        
        # 这里应该调用IO系统的存档功能
        # 暂时返回提示信息
        return f"游戏进度已保存: {save_name}", changes
    
    def _cmd_load(
        self,
        args: List[str],
        player: Character,
        game_state: GameState
    ) -> Tuple[str, List[StateChange]]:
        """
        加载进度
        
        Args:
            args: 存档名（可选）
            player: 玩家角色
            game_state: 游戏状态
            
        Returns:
            Tuple[描述文本, 变更列表]
        """
        changes = []
        
        save_name = args[0] if args else "auto_save"
        
        # 这里应该调用IO系统的读档功能
        # 暂时返回提示信息
        return f"加载存档功能需要在GameEngine中实现: {save_name}", changes
    
    def _cmd_help(
        self,
        args: List[str],
        player: Character,
        game_state: GameState
    ) -> Tuple[str, List[StateChange]]:
        """显示帮助文本。"""
        changes = []

        help_text = "【基础指令列表】\n\n"
        help_text += "信息查看类:\n"
        help_text += "  \\look [目标]   - 查看当前场景或指定目标\n"
        help_text += "  \\inventory     - 查看背包\n"
        help_text += "  \\status        - 查看自身状态\n"
        help_text += "  \\where         - 查看当前位置\n\n"

        help_text += "物品操作类:\n"
        help_text += "  \\pickup <物品名> - 捡起物品\n"
        help_text += "  \\drop <物品名>   - 放下物品\n\n"
        help_text += "  \\use <物品名>    - 使用物品\n"
        help_text += "  \\give <物品名> to <角色> - 给予物品\n\n"
        help_text += "  \\move to=<地图ID>|<方向|地图ID> - 移动到相邻场景\n\n"

        help_text += "游戏控制类:\n"
        help_text += "  \\save [存档名]   - 保存进度\n"
        help_text += "  \\load [存档名]   - 加载进度\n"
        help_text += "  \\reset          - 重置游戏\n"
        help_text += "  \\debug          - 切换调试模式\n"
        help_text += "  \\screen ai on|off|status - 开关AI筛查\n"
        help_text += "  \\speed fast|quality|status - 切换响应速度模式\n"
        help_text += "  \\help           - 显示此帮助\n"
        help_text += "  \\exit           - 退出游戏\n\n"

        help_text += "【自然语言】\n"
        help_text += "直接输入你想做的事情，例如:\n"
        help_text += "  '向书童说明来意，请他代为通报'\n"
        help_text += "  '我愿意在门外继续等候先生醒来'\n"
        help_text += "  '我想稳住心绪，再进内院问安'\n"

        return help_text, changes

    def _cmd_exit(
        self,
        args: List[str],
        player: Character,
        game_state: GameState
    ) -> Tuple[str, List[StateChange]]:
        """
        退出游戏
        
        Args:
            args: 无参数
            player: 玩家角色
            game_state: 游戏状态
            
        Returns:
            Tuple[描述文本, 变更列表]
        """
        changes = []
        
        return "EXIT_GAME", changes

    def _cmd_reset(
        self,
        args: List[str],
        player: Character,
        game_state: GameState
    ) -> Tuple[str, List[StateChange]]:
        """请求引擎重置游戏。"""
        return "RESET_GAME", []

    def _cmd_debug(
        self,
        args: List[str],
        player: Character,
        game_state: GameState
    ) -> Tuple[str, List[StateChange]]:
        """?????????"""
        mode = args[0].lower() if args else "on"
        if mode not in ("on", "off"):
            mode = "on"
        return f"DEBUG_MODE_{mode.upper()}", []

    def _cmd_screen(
        self,
        args: List[str],
        player: Character,
        game_state: GameState
    ) -> Tuple[str, List[StateChange], Dict[str, Any]]:
        changes = []
        normalized_args = [str(arg).strip().lower() for arg in args if str(arg).strip()]
        if normalized_args and normalized_args[0] in {"ai", "aiscreen", "screening"}:
            normalized_args = normalized_args[1:]
        action = normalized_args[0] if normalized_args else "status"
        if action not in {"on", "off", "status"}:
            return r"用法: \screen ai on|off|status", changes, None
        return "", changes, {"type": "ai_screening", "action": action}

    def _cmd_speed(
        self,
        args: List[str],
        player: Character,
        game_state: GameState
    ) -> Tuple[str, List[StateChange], Dict[str, Any]]:
        changes = []
        mode = str(args[0]).strip().lower() if args else "status"
        if mode == "normal":
            mode = "quality"
        if mode not in {"fast", "quality", "status"}:
            return r"用法: \speed fast|quality|status", changes, None
        return "", changes, {"type": "speed_mode", "mode": mode}

    def get_help_text(self) -> str:
        """获取帮助文本"""
        return self._cmd_help([], None, None)[0]


# 导出
__all__ = ["InputSystem", "InputResult", "InputType"]
