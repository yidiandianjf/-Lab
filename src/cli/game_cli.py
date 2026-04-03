"""
CLI前端模块 - 命令行交互界面

功能：
- 命令行交互界面
- 游戏状态展示（场景、角色、物品、事件）
- 输入循环
- 与Game Engine交互
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from src.data.models import (
    Character, Item, Map, GameState, CheckOutput
)

# 配置日志
logger = logging.getLogger(__name__)


# ============================================================
# 文本格式化工具
# ============================================================

class Colors:
    """终端颜色代码"""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    
    # 前景色
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    
    # 背景色
    BG_BLACK = "\033[40m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"


class TextFormatter:
    """文本格式化工具"""
    
    @staticmethod
    def title(text: str) -> str:
        """标题格式"""
        return f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}\n{Colors.BOLD}{Colors.CYAN}{text.center(60)}{Colors.RESET}\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}\n"
    
    @staticmethod
    def section(text: str) -> str:
        """章节标题"""
        return f"\n{Colors.BOLD}{Colors.YELLOW}【{text}】{Colors.RESET}"
    
    @staticmethod
    def highlight(text: str) -> str:
        """高亮文本"""
        return f"{Colors.BOLD}{Colors.GREEN}{text}{Colors.RESET}"
    
    @staticmethod
    def info(text: str) -> str:
        """信息文本"""
        return f"{Colors.CYAN}{text}{Colors.RESET}"
    
    @staticmethod
    def warning(text: str) -> str:
        """警告文本"""
        return f"{Colors.YELLOW}{text}{Colors.RESET}"
    
    @staticmethod
    def error(text: str) -> str:
        """错误文本"""
        return f"{Colors.RED}{text}{Colors.RESET}"
    
    @staticmethod
    def narrative(text: str) -> str:
        """叙事文本"""
        return f"{Colors.WHITE}{text}{Colors.RESET}"
    
    @staticmethod
    def command(text: str) -> str:
        """指令文本"""
        return f"{Colors.MAGENTA}{text}{Colors.RESET}"
    
    @staticmethod
    def box(text: str, width: int = 60) -> str:
        """绘制文本框"""
        lines = text.split('\n')
        result = [f"┌{'─'*width}┐"]
        for line in lines:
            # 截断或填充到指定宽度
            if len(line) > width:
                line = line[:width-3] + "..."
            result.append(f"│{line:<{width}}│")
        result.append(f"└{'─'*width}┘")
        return '\n'.join(result)


# ============================================================
# 显示管理器
# ============================================================

class DisplayManager:
    """游戏显示管理器"""
    
    def __init__(self, use_colors: bool = True):
        self.use_colors = use_colors
        self.formatter = TextFormatter()

    @staticmethod
    def _is_education_scene(world_name: str = "") -> bool:
        return str(world_name or "").strip().lower() == "daiyu_enters_jia"

    @staticmethod
    def _world_copy(world_name: str = "") -> Dict[str, str]:
        normalized = str(world_name or "").strip().lower()
        mapping = {
            "daiyu_enters_jia": {
                "banner_title": "AI 阅读实验室演示场景",
                "banner_subtitle": "红楼梦 · 黛玉初进贾府",
                "banner_tagline": "沉浸式阅读与礼仪体验",
                "welcome_title": "欢迎进入《红楼梦·黛玉初进贾府》教育场景。",
                "welcome_hint": "输入 \\help 查看可用指令，或直接用自然语言描述林黛玉的言行。",
            },
            "sanguo_mao_lu": {
                "banner_title": "AI 阅读实验室演示场景",
                "banner_subtitle": "三国演义 · 三顾茅庐",
                "banner_tagline": "沉浸式阅读与求贤礼仪体验",
                "welcome_title": "欢迎进入《三国演义·三顾茅庐》教育场景。",
                "welcome_hint": "输入 \\help 查看可用指令，或直接用自然语言描述刘备的言行。",
            },
        }
        return mapping.get(
            normalized,
            {
                "banner_title": "AI 阅读实验室",
                "banner_subtitle": "多世界沉浸式教育场景",
                "banner_tagline": "请选择你的阅读情境",
                "welcome_title": "欢迎进入 AI 阅读实验室。",
                "welcome_hint": "输入 \\help 查看可用指令，或直接用自然语言推动情节。",
            },
        )

    def _status_labels(self, world_name: str = "") -> Dict[str, str]:
        normalized = str(world_name or "").strip().lower()
        if normalized == "daiyu_enters_jia":
            return {
                "hp": "体力",
                "san": "心绪",
                "lucky": "机缘",
            }
        if normalized == "sanguo_mao_lu":
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

    def _format_check_detail(self, detail: str, world_name: str = "") -> str:
        normalized = str(detail or "")
        if not normalized:
            return normalized

        normalized_world = str(world_name or "").strip().lower()
        replacements = None
        if normalized_world == "daiyu_enters_jia":
            replacements = {
                "使用属性:": "依据项:",
                "san": "心绪",
                "hp": "体力",
                "lucky": "机缘",
                "luck": "机缘",
                "pow": "心志",
                "dex": "敏捷",
                "app": "风仪",
                "int": "悟性",
                "edu": "学识",
                "str": "气力",
                "con": "体质",
                "siz": "体格",
            }
        elif normalized_world == "sanguo_mao_lu":
            replacements = {
                "使用属性:": "依据项:",
                "san": "心志",
                "hp": "体魄",
                "lucky": "机运",
                "luck": "机运",
                "pow": "志节",
                "dex": "身手",
                "app": "风仪",
                "int": "谋识",
                "edu": "学识",
                "str": "气力",
                "con": "体魄",
                "siz": "体格",
            }

        if replacements:
            for source, target in replacements.items():
                normalized = normalized.replace(source, target)
        return normalized

    def clear_screen(self):
        """清屏"""
        os.system('cls' if os.name == 'nt' else 'clear')
    
    def print_title(self, world_name: str = ""):
        """??????"""
        copy = self._world_copy(world_name)
        lines = [
            "+---------------------------------------------------------------+",
            "|                                                               |",
            f"|{copy['banner_title'].center(63)}|",
            "|                                                               |",
            f"|{copy['banner_subtitle'].center(63)}|",
            "|                                                               |",
            f"|{copy['banner_tagline'].center(63)}|",
            "|                                                               |",
            "+---------------------------------------------------------------+",
        ]
        print("\n".join(lines))

    def print_scene(self, game_state: GameState):
        """打印当前场景"""
        current_map = game_state.get_current_map()
        if not current_map:
            print(self.formatter.error("当前不在任何场景中"))
            return
        
        print(self.formatter.section(f"当前场景: {current_map.name}"))
        print(self.formatter.narrative(current_map.description.get_public_text()))
        
        # 显示可通往的方向
        if current_map.neighbors:
            print(self.formatter.section("可通往"))
            for neighbor in self._normalize_neighbors(current_map.neighbors):
                print(f"  {self.formatter.highlight(neighbor.direction)}: {neighbor.description}")

    def _normalize_neighbors(self, raw_neighbors):
        """Accept both MapNeighbor objects and legacy dict payloads."""
        normalized = []
        for neighbor in raw_neighbors or []:
            if hasattr(neighbor, "direction") and hasattr(neighbor, "description"):
                normalized.append(neighbor)
            elif isinstance(neighbor, dict):
                direction = str(neighbor.get("direction", "")).strip()
                description = str(neighbor.get("description", "")).strip()
                if direction:
                    normalized.append(
                        type("NeighborView", (), {
                            "direction": direction,
                            "description": description,
                        })()
                    )
        return normalized
    
    def print_characters(self, game_state: GameState):
        """打印场景中的角色"""
        current_map = game_state.get_current_map()
        if not current_map or not current_map.entities.characters:
            return

        char_ids = self._flatten_entity_ids(current_map.entities.characters)
        other_chars = [cid for cid in char_ids
                      if cid != game_state.player_id]
        
        if not other_chars:
            return
        
        print(self.formatter.section("在场角色"))
        for char_id in other_chars:
            char = game_state.characters.get(char_id)
            if char:
                desc = self._summarize_text(char.description.get_public_text(), limit=90)
                print(f"  {self.formatter.highlight('*')} {char.name}: {desc}")
    
    def print_items(self, game_state: GameState):
        """打印场景中的物品"""
        current_map = game_state.get_current_map()
        if not current_map or not current_map.entities.items:
            return
        
        print(self.formatter.section("可见物品"))
        for item_id in self._flatten_entity_ids(current_map.entities.items):
            item = game_state.items.get(item_id)
            if item:
                desc = self._summarize_text(item.description.get_public_text(), limit=80)
                print(f"  {self.formatter.highlight('*')} {item.name}: {desc}")

    def _flatten_entity_ids(self, raw_ids: Any) -> List[str]:
        """扁平化实体ID，避免脏数据中的嵌套list导致渲染异常。"""
        result: List[str] = []
        seen = set()
        for value in list(raw_ids or []):
            if isinstance(value, str):
                if value not in seen:
                    seen.add(value)
                    result.append(value)
            elif isinstance(value, list):
                for inner in value:
                    if isinstance(inner, str) and inner not in seen:
                        seen.add(inner)
                        result.append(inner)
        return result

    def _summarize_text(self, text: str, limit: int = 80) -> str:
        """Summarize text safely to avoid cutting mid-sentence fragments."""
        normalized = " ".join((text or "").replace("\n", "；").split())
        if len(normalized) <= limit:
            return normalized

        cut = normalized[:limit]
        best_punct = max(cut.rfind("。"), cut.rfind("；"), cut.rfind("！"), cut.rfind("？"))
        if best_punct >= int(limit * 0.6):
            return cut[: best_punct + 1]
        return cut.rstrip() + "..."
    
    def print_player_status(self, game_state: GameState, world_name: str = ""):
        """打印玩家状态"""
        player = game_state.get_player()
        if not player:
            return
        
        # HP条
        hp_percent = player.status.hp / player.status.max_hp if player.status.max_hp > 0 else 1
        hp_bar = self._make_bar(hp_percent, 20, Colors.RED)
        
        # SAN条
        san_percent = player.status.san / 100
        san_bar = self._make_bar(san_percent, 20, Colors.BLUE)
        labels = self._status_labels(world_name)
        
        print(self.formatter.section(f"{player.name}的状态"))
        print(f"  {labels['hp']}:  [{hp_bar}] {player.status.hp}/{player.status.max_hp}")
        print(f"  {labels['san']}: [{san_bar}] {player.status.san}/100")
        print(f"  {labels['lucky']}: {player.status.lucky}")
    
    def _make_bar(self, percent: float, width: int, color: str) -> str:
        """制作进度条"""
        filled = int(width * percent)
        empty = width - filled
        bar = f"{color}{('#' * filled)}{Colors.DIM}{('-' * empty)}{Colors.RESET}"
        return bar
    
    def print_narrative(self, text: str):
        """打印叙事文本"""
        print(f"\n{self.formatter.narrative(text)}")
    
    def print_check_result(self, check_result: CheckOutput, world_name: str = ""):
        """打印鉴定结果"""
        result_colors = {
            "大成功": Colors.BG_GREEN + Colors.WHITE,
            "成功": Colors.GREEN,
            "失败": Colors.YELLOW,
            "大失败": Colors.BG_RED + Colors.WHITE,
        }

        result_value = getattr(check_result, "result", None)
        if isinstance(check_result, dict):
            result_value = check_result.get("result")

        if isinstance(result_value, list):
            result_value = next((x for x in result_value if x), "")
        elif hasattr(result_value, "value"):
            result_value = result_value.value

        result_text = str(result_value or "未知")
        if "." in result_text:
            result_text = result_text.split(".")[-1]
        result_alias = {
            "CRITICAL_SUCCESS": "大成功",
            "SUCCESS": "成功",
            "FAILURE": "失败",
            "FUMBLE": "大失败",
        }
        result_text = result_alias.get(result_text, result_text)

        color = result_colors.get(result_text, Colors.RESET)
        dice_roll = getattr(check_result, "dice_roll", "-")
        target_value = getattr(check_result, "target_value", "-")
        actor_value = getattr(check_result, "actor_value", "-")
        detail = getattr(check_result, "detail", "")
        if isinstance(check_result, dict):
            dice_roll = check_result.get("dice_roll", "-")
            target_value = check_result.get("target_value", "-")
            actor_value = check_result.get("actor_value", "-")
            detail = check_result.get("detail", "")

        title = "情境判定" if self._is_education_scene(world_name) else "鉴定结果"
        actor_label = "依据值" if self._is_education_scene(world_name) else "属性值"
        print(f"\n{self.formatter.section(title)}")
        print(f"  骰子结果: {dice_roll}")
        print(f"  目标值: {target_value}")
        print(f"  {actor_label}: {actor_value}")
        print(f"  结果: {color}{Colors.BOLD}{result_text}{Colors.RESET}")
        if detail:
            print(f"  详情: {self._format_check_detail(detail, world_name)}")
    
    def print_event(self, event: str):
        """打印事件信息"""
        print(f"\n{self.formatter.info('[事件]')} {event}")
    
    def print_error(self, message: str):
        """打印错误信息"""
        print(f"\n{self.formatter.error('错误:')} {message}")
    
    def print_help(self, help_text: str):
        """打印帮助信息"""
        print(f"\n{help_text}")
    
    def print_game_over(self, ending_text: str = ""):
        """打印游戏结束"""
        print(self.formatter.title("游戏结束"))
        if ending_text:
            print(self.formatter.narrative(ending_text))
        print("\n感谢游玩！")
    
    def print_turn_info(self, turn_count: int):
        """打印回合信息"""
        print(f"\n{Colors.DIM}{'─'*60}{Colors.RESET}")
        print(f"{self.formatter.info(f'第 {turn_count} 回合')}")
        print(f"{Colors.DIM}{'─'*60}{Colors.RESET}")


# ============================================================
# 输入处理器
# ============================================================

class InputHandler:
    """用户输入处理器"""
    
    def __init__(self):
        self.history: List[str] = []
        self.max_history = 50
    
    def get_input(self, prompt: str = "> ") -> str:
        """
        获取用户输入
        
        Args:
            prompt: 提示符
            
        Returns:
            用户输入的字符串
        """
        try:
            user_input = input(prompt).strip()
            if user_input:
                self._add_to_history(user_input)
            return user_input
        except EOFError:
            return "\\exit"
        except KeyboardInterrupt:
            return "\\exit"
    
    def _add_to_history(self, user_input: str):
        """添加到历史记录"""
        self.history.append(user_input)
        if len(self.history) > self.max_history:
            self.history.pop(0)
    
    def confirm(self, message: str) -> bool:
        """
        确认提示
        
        Args:
            message: 提示消息
            
        Returns:
            是否确认
        """
        response = input(f"{message} (y/n): ").strip().lower()
        return response in ('y', 'yes', '是', '确认')
    
    def choose_from_list(self, options: List[str], prompt: str = "请选择: ") -> Optional[int]:
        """
        从列表中选择
        
        Args:
            options: 选项列表
            prompt: 提示信息
            
        Returns:
            选择的索引，取消则返回None
        """
        print(f"\n{prompt}")
        for i, option in enumerate(options, 1):
            print(f"  {i}. {option}")
        print("  0. 取消")
        
        try:
            choice = input("输入编号: ").strip()
            idx = int(choice)
            if idx == 0:
                return None
            if 1 <= idx <= len(options):
                return idx - 1
            print("无效的选项")
            return None
        except ValueError:
            print("请输入数字")
            return None


# ============================================================
# 游戏CLI主类
# ============================================================

class GameCLI:
    """
    游戏CLI前端
    
    提供完整的命令行交互界面
    """
    
    def __init__(self, game_engine=None, use_colors: bool = True):
        """
        初始化CLI
        
        Args:
            game_engine: 游戏引擎实例（可选）
            use_colors: 是否使用颜色
        """
        self.display = DisplayManager(use_colors)
        self.input_handler = InputHandler()
        self.running = False
        self.game_engine = game_engine
        self._last_displayed_narrative: str = ""
        self._loop_error_count: int = 0
        logger.info("CLI前端初始化完成")

    def run(self):
        """启动CLI。"""
        if self.game_engine is None:
            raise ValueError("GameCLI.run 需要可用的 game_engine")

        self.show_welcome()
        self.start_game_loop(self.game_engine)
    
    def show_welcome(self):
        """??????"""
        self.display.clear_screen()
        world_name = getattr(self.game_engine, "world_name", "") if self.game_engine else ""
        copy = self.display._world_copy(world_name)
        self.display.print_title(world_name)
        print(f"\n{copy['welcome_title']}")
        print(f"{copy['welcome_hint']}\n")

    def show_main_menu(self) -> str:
        """
        显示主菜单
        
        Returns:
            用户选择
        """
        print(self.display.formatter.section("主菜单"))
        print("  1. 新游戏")
        print("  2. 加载存档")
        print("  3. 设置")
        print("  4. 退出")
        
        choice = self.input_handler.get_input("请选择: ")
        return choice
    
    def start_game_loop(self, game_engine):
        """
        启动游戏主循环
        
        Args:
            game_engine: 游戏引擎实例
        """
        self.running = True
        
        while self.running:
            try:
                # 显示当前游戏状态
                self._display_game_state(game_engine)
                
                # 获取玩家输入
                user_input = self.input_handler.get_input(
                    f"\n{self.display.formatter.command('>')} "
                )
                
                if not user_input:
                    continue
                
                # 检查退出指令
                if user_input.lower() in ('\\exit', 'exit', 'quit', '退出'):
                    if self.input_handler.confirm("确定要退出游戏吗？"):
                        self.running = False
                        break
                    continue
                
                # 将输入传递给游戏引擎处理
                result = game_engine.process_input(user_input)
                
                # 显示处理结果
                self._display_result(result)
                
                # 检查游戏是否结束
                if game_engine.is_game_over():
                    ending_text = game_engine.get_ending_text()
                    if self._narrative_contains_text(self._last_displayed_narrative, ending_text):
                        ending_text = ""
                    self.display.print_game_over(ending_text)
                    if self.input_handler.confirm("重新开始？"):
                        game_engine.restart()
                    else:
                        self.running = False

                # 当前回合执行完成后重置错误计数
                self._loop_error_count = 0
                    
            except Exception as e:
                self._loop_error_count += 1
                logger.exception(f"游戏循环错误: {e}")
                self.display.print_error(f"发生错误: {str(e)}")
                if self._loop_error_count >= 3:
                    self.display.print_error("连续发生错误，已自动退出游戏循环以避免刷屏。")
                    self.running = False
                    break
    
    def _display_game_state(self, game_engine):
        """显示当前游戏状态"""
        game_state = game_engine.get_game_state()
        
        # 显示回合信息
        self.display.print_turn_info(game_state.turn_count)
        
        # 显示场景
        self.display.print_scene(game_state)
        
        # 显示角色和物品
        self.display.print_characters(game_state)
        self.display.print_items(game_state)
        
        # 显示玩家状态
        self.display.print_player_status(
            game_state,
            world_name=getattr(game_engine, "world_name", ""),
        )
        
        # 显示当前事件（如果有）
        player = game_state.get_player()
        if (
            player
            and player.memory.current_event
            and player.memory.current_event != self._last_displayed_narrative
        ):
            self.display.print_narrative(player.memory.current_event)
    
    def _display_result(self, result: Dict[str, Any]):
        """显示处理结果"""
        if not result:
            return

        if isinstance(result, str):
            print(f"\n{result}")
            return

        if not isinstance(result, dict):
            self.display.print_error(f"无法识别的返回结果类型: {type(result).__name__}")
            return
        
        # 显示直接响应
        if result.get("response"):
            print(f"\n{result['response']}")
        
        # 显示鉴定结果
        if result.get("check_result"):
            world_name = getattr(self.game_engine, "world_name", "") if self.game_engine else ""
            self.display.print_check_result(result["check_result"], world_name=world_name)
        
        # 显示叙事文本
        if result.get("narrative"):
            narrative = result["narrative"]
            self.display.print_narrative(narrative)
            self._last_displayed_narrative = narrative

    @staticmethod
    def _narrative_contains_text(narrative: str, target_text: str) -> bool:
        """Return True when the ending text has already been shown in the narrative block."""
        normalized_narrative = " ".join(str(narrative or "").split())
        normalized_target = " ".join(str(target_text or "").split())
        if not normalized_narrative or not normalized_target:
            return False
        return normalized_target in normalized_narrative
    
    def get_player_name(self) -> str:
        """获取玩家名称"""
        name = self.input_handler.get_input("请输入角色名称: ")
        return name or "调查员"
    
    def show_message(self, message: str, message_type: str = "info"):
        """
        显示消息
        
        Args:
            message: 消息内容
            message_type: 消息类型 (info/warning/error/success)
        """
        if message_type == "error":
            self.display.print_error(message)
        elif message_type == "warning":
            print(self.display.formatter.warning(message))
        elif message_type == "success":
            print(self.display.formatter.highlight(message))
        else:
            print(self.display.formatter.info(message))
    
    def pause(self, message: str = "按Enter继续..."):
        """暂停等待用户输入"""
        input(message)


# ============================================================
# 便捷函数
# ============================================================

def create_cli(game_engine=None, use_colors: bool = True) -> GameCLI:
    """
    创建CLI实例
    
    Args:
        use_colors: 是否使用颜色
        
    Returns:
        GameCLI实例
    """
    return GameCLI(game_engine=game_engine, use_colors=use_colors)


# 导出
__all__ = [
    "GameCLI",
    "DisplayManager",
    "InputHandler",
    "TextFormatter",
    "Colors",
    "create_cli"
]


# 测试入口
if __name__ == "__main__":
    cli = create_cli()
    cli.show_welcome()
    print("CLI模块测试完成")
