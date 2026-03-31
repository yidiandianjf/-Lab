"""
AI阅读实验室 - 主入口文件

功能：
- 解析命令行参数
- 初始化游戏世界
- 启动CLI游戏循环

使用方法:
    python src/main.py                    # 开始新游戏
    python src/main.py --name "林黛玉"     # 指定玩家名称
    python src/main.py --load save1       # 加载存档
    python src/main.py --help             # 显示帮助信息
"""

import sys
import os
import argparse
import logging
from pathlib import Path

# 添加项目根目录到Python路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.io_system import IOSystem
from src.data.init.world_loader import load_initial_world_bundle
from src.engine.game_engine import GameEngine
from src.cli.game_cli import GameCLI


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

DEFAULT_WORLD = "daiyu_enters_jia"
APP_TITLE = "AI阅读实验室"
APP_SUBTITLE = "《红楼梦·黛玉初进贾府》沉浸式教育场景"


def ensure_project_root_cwd():
    """Normalize cwd to project root so relative config/data paths stay stable."""
    try:
        current = Path.cwd().resolve()
    except Exception:
        current = Path.cwd()

    if current != PROJECT_ROOT:
        os.chdir(PROJECT_ROOT)
        logger.info(f"工作目录已切换到项目根目录: {PROJECT_ROOT}")


def parse_arguments():
    """
    解析命令行参数
    
    Returns:
        argparse.Namespace: 解析后的参数对象
    """
    parser = argparse.ArgumentParser(
        description=f"{APP_TITLE} - {APP_SUBTITLE}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python src/main.py                    开始新游戏
  python src/main.py --name "林黛玉"     以指定名称开始新游戏
  python src/main.py --load auto_save   加载自动存档继续游戏
  python src/main.py --db data/my_game.db  使用指定数据库文件
        """
    )
    
    parser.add_argument(
        "--name", "-n",
        type=str,
        default=None,
        help="玩家角色名称（已废弃，默认读取世界配置中的玩家定义）"
    )
    
    parser.add_argument(
        "--load", "-l",
        type=str,
        metavar="SAVE_NAME",
        help="加载指定名称的存档"
    )
    
    parser.add_argument(
        "--db", "-d",
        type=str,
        default="data/game.db",
        help="数据库文件路径（默认为'data/game.db'）"
    )
    
    parser.add_argument(
        "--mode", "-m",
        type=str,
        choices=["sqlite", "json"],
        default="sqlite",
        help="存储模式: sqlite 或 json（默认为sqlite）"
    )
    
    parser.add_argument(
        "--scenario", "-s",
        type=str,
        help="指定剧本/场景ID（可选）"
    )

    parser.add_argument(
        "--world", "-w",
        type=str,
        default=DEFAULT_WORLD,
        help="指定世界配置目录名（位于 config/world/<world_name>）"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="启用调试模式（显示详细日志）"
    )
    
    return parser.parse_args()


def setup_logging(debug: bool = False):
    """
    配置日志级别
    
    Args:
        debug: 是否启用调试模式
    """
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("调试模式已启用")


def initialize_game(args) -> GameEngine:
    """
    初始化游戏引擎
    
    Args:
        args: 命令行参数
        
    Returns:
        GameEngine: 初始化好的游戏引擎实例
    """
    logger.info("正在初始化游戏...")
    
    # 创建IO系统
    io_system = IOSystem(
        db_path=args.db,
        mode=args.mode
    )
    logger.info(f"IO系统已初始化（模式: {args.mode}）")
    
    # 创建游戏引擎
    engine = GameEngine(
        io_system=io_system,
        db_path=args.db
    )
    
    if args.load:
        # 加载存档
        logger.info(f"正在加载存档: {args.load}")
        success = engine.load_game(args.load)
        if not success:
            logger.error("加载存档失败，将开始新游戏")
            _start_new_game(engine, args)
    else:
        # 开始新游戏
        _start_new_game(engine, args)
    
    return engine


def _start_new_game(engine: GameEngine, args):
    """
    开始新游戏
    
    Args:
        engine: 游戏引擎实例
        args: 命令行参数
    """
    logger.info("开始新游戏（使用世界配置中的玩家定义）")
    
    # 从配置文件加载世界数据
    try:
        bundle = load_initial_world_bundle(
            engine.io,
            player_name=None,
            world_name=args.world
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(
            world_name=bundle.world_name,
            end_condition=bundle.end_condition,
            npc_response_mode=bundle.npc_response_mode,
            narrative_window=bundle.narrative_window,
            npc_director_use_llm=bundle.npc_director_use_llm,
            narrative_merge_use_llm=bundle.narrative_merge_use_llm,
            entry_scene_narrative=bundle.entry_scene_narrative,
            prime_entry_scene=True,
        )

        if args.name:
            logger.warning("参数 --name 已废弃，当前版本忽略该参数。")
        
        # 更新游戏状态的其他设置
        engine.game_state.turn_count = 1
        engine._is_game_over = False
        
        logger.info(f"世界数据加载成功: {bundle.world_name}")
        
    except Exception as e:
        logger.error(f"从配置加载世界数据失败: {e}")
        raise RuntimeError("世界配置加载失败，已终止启动") from e


def main():
    """
    主函数 - 游戏入口点
    """
    try:
        ensure_project_root_cwd()
        # 解析命令行参数
        args = parse_arguments()
        
        # 设置日志
        setup_logging(args.debug)
        
        logger.info("=" * 60)
        logger.info(APP_TITLE)
        logger.info(APP_SUBTITLE)
        logger.info("=" * 60)
        
        # 初始化游戏
        engine = initialize_game(args)
        
        # 创建CLI并启动游戏循环
        cli = GameCLI(engine)
        
        logger.info("启动游戏界面...")
        cli.run()
        
    except KeyboardInterrupt:
        logger.info("\n游戏被用户中断")
        sys.exit(0)
        
    except Exception as e:
        logger.exception(f"游戏运行时发生错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
