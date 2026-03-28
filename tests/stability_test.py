#!/usr/bin/env python3
"""
稳定性测试脚本 - 自动运行50+回合不出现bug

使用方法:
    python tests/stability_test.py          # 运行50回合测试
    python tests/stability_test.py --rounds 100    # 运行100回合
    python tests/stability_test.py --rounds 50 --save-interval 10  # 每10回合保存一次
    python tests/stability_test.py --debug    # 启用详细调试日志
"""

import sys
import os
import time
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.io_system import IOSystem, ERROR_SUCCESS
from src.data.init.world_loader import load_initial_world_bundle
from src.engine.game_engine import GameEngine
from src.utils.debug_logger import DebugLogger
from src.utils.debug_config import DebugConfig


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class StabilityTestRunner:
    """稳定性测试运行器"""
    
    def __init__(
        self,
        world_name: str = "mysterious_library",
        db_path: str = "data/stability_test.db",
        debug: bool = False,
        save_interval: int = 10,
        max_rounds: int = 50
    ):
        self.world_name = world_name
        self.db_path = db_path
        self.debug = debug
        self.save_interval = save_interval
        self.max_rounds = max_rounds
        
        self.engine: Optional[GameEngine] = None
        self.test_results: Dict[str, Any] = {
            "start_time": None,
            "end_time": None,
            "total_rounds": 0,
            "successful_rounds": 0,
            "failed_rounds": [],
            "errors": [],
            "llm_calls": 0,
            "state_changes": 0,
            "consistency_issues": [],
            "per_round_stats": [],
        }
        
        # 用于模拟输入的预设动作列表
        self.action_pool = [
            "我要看看房间里有什么",
            "我要搜查这个房间",
            "我要检查书架",
            "我要移动到走廊",
            "我要移动到房间",
            "我要拿起桌上的物品",
            "我要和守卫对话",
            "我要查看我的背包",
            "我要继续前进",
            "我要仔细调查",
            "我要休息一下",
            "我要尝试打开门",
            "我要看看窗外",
            "我要检查门锁",
            "我要从书架上拿一本书",
        ]
        
        self.current_action_index = 0
    
    def setup(self) -> bool:
        """初始化测试环境"""
        try:
            logger.info("=" * 60)
            logger.info("初始化稳定性测试环境")
            logger.info("=" * 60)
            
            # 清理旧的测试数据库
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
                logger.info(f"已清理旧的测试数据库: {self.db_path}")
            
            # 配置Debug
            debug_config = DebugConfig(
                enabled=self.debug,
                log_level="debug" if self.debug else "info",
                log_dir="logs/stability_test",
                outputs={
                    "master_log": True,
                    "timeline_json": True,
                    "categorized": True,
                    "snapshots": True,
                    "llm_prompts": self.debug,
                },
                consistency={
                    "check_after_each_change": True,
                    "check_after_turn": True,
                    "warn_on_inconsistency": True,
                }
            )
            
            # 创建IO系统
            io_system = IOSystem(db_path=self.db_path, mode="sqlite")
            logger.info(f"IO系统已初始化")
            
            # 创建游戏引擎
            self.engine = GameEngine(
                io_system=io_system,
                db_path=self.db_path,
                debug_config=debug_config
            )
            logger.info(f"游戏引擎已初始化")
            
            # 加载世界
            logger.info(f"正在加载世界: {self.world_name}")
            bundle = load_initial_world_bundle(
                io_system,
                player_name=None,
                world_name=self.world_name
            )
            
            self.engine.game_state = bundle.game_state
            self.engine.apply_world_settings(
                world_name=bundle.world_name,
                end_condition=bundle.end_condition,
                npc_response_mode=bundle.npc_response_mode,
                narrative_window=bundle.narrative_window,
                npc_director_use_llm=bundle.npc_director_use_llm,
                narrative_merge_use_llm=bundle.narrative_merge_use_llm,
            )
            
            self.engine.game_state.turn_count = 1
            self.engine._is_game_over = False
            
            logger.info("世界加载成功")
            self.test_results["start_time"] = datetime.now().isoformat()
            
            return True
            
        except Exception as e:
            logger.exception(f"测试环境初始化失败: {e}")
            self.test_results["errors"].append({
                "stage": "setup",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
            return False
    
    def get_next_action(self) -> str:
        """获取下一个测试动作"""
        action = self.action_pool[self.current_action_index]
        self.current_action_index = (self.current_action_index + 1) % len(self.action_pool)
        return action
    
    def run_single_round(self, round_num: int) -> bool:
        """运行单个回合"""
        start_time = time.time()
        
        try:
            logger.info(f"--- 回合 {round_num}/{self.max_rounds} ---")
            
            # 获取下一个动作
            player_input = self.get_next_action()
            logger.info(f"玩家输入: {player_input[:50]}{'...' if len(player_input) > 50 else ''}")
            
            # 处理输入
            result = self.engine.process_input(player_input)
            
            # 记录回合统计
            round_stats = {
                "round": round_num,
                "player_input": player_input,
                "success": result.get("success", False),
                "game_over": result.get("game_over", False),
                "duration_ms": (time.time() - start_time) * 1000,
                "timestamp": datetime.now().isoformat()
            }
            
            self.test_results["per_round_stats"].append(round_stats)
            
            # 检查是否成功
            if result.get("success"):
                self.test_results["successful_rounds"] += 1
                logger.info(f"回合 {round_num} 成功 ✓")
                logger.info(f"叙事: {result.get('narrative', '')[:100]}")
            else:
                self.test_results["failed_rounds"].append(round_num)
                self.test_results["errors"].append({
                    "stage": f"round_{round_num}",
                    "error": result.get("response", "Unknown error"),
                    "timestamp": datetime.now().isoformat()
                })
                logger.error(f"回合 {round_num} 失败 ✗: {result.get('response', '')}")
            
            # 检查游戏是否结束
            if result.get("game_over"):
                logger.warning("游戏提前结束!")
                return False
            
            return True
            
        except Exception as e:
            logger.exception(f"回合 {round_num} 发生异常: {e}")
            self.test_results["failed_rounds"].append(round_num)
            self.test_results["errors"].append({
                "stage": f"round_{round_num}",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
            return False
    
    def save_game(self, round_num: int):
        """保存游戏状态"""
        try:
            save_name = f"stability_test_round_{round_num}"
            success = self.engine.save_game(save_name)
            if success:
                logger.info(f"已保存游戏状态: {save_name}")
            else:
                logger.warning(f"保存游戏失败: {save_name}")
        except Exception as e:
            logger.warning(f"保存游戏异常: {e}")
    
    def run(self) -> Dict[str, Any]:
        """运行完整测试"""
        if not self.setup():
            return self.test_results
        
        try:
            logger.info("=" * 60)
            logger.info(f"开始稳定性测试: {self.max_rounds} 回合")
            logger.info("=" * 60)
            
            for round_num in range(1, self.max_rounds + 1):
                # 运行单回合
                continue_test = self.run_single_round(round_num)
                self.test_results["total_rounds"] += 1
                
                if not continue_test:
                    logger.warning("测试提前终止")
                    break
                
                # 定期保存
                if round_num % self.save_interval == 0:
                    self.save_game(round_num)
                
                # 短暂停，避免API限制
                if self.debug:
                    time.sleep(0.5)
            
            # 最终保存
            if self.test_results["total_rounds"] > 0:
                self.save_game(self.test_results["total_rounds"])
            
        except KeyboardInterrupt:
            logger.info("测试被用户中断")
        except Exception as e:
            logger.exception(f"测试过程发生异常: {e}")
            self.test_results["errors"].append({
                "stage": "main_loop",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
        finally:
            self.test_results["end_time"] = datetime.now().isoformat()
            self.print_summary()
            self.save_results()
        
        return self.test_results
    
    def print_summary(self):
        """打印测试摘要"""
        logger.info("=" * 60)
        logger.info("测试摘要")
        logger.info("=" * 60)
        
        total_time = (
            datetime.fromisoformat(self.test_results["end_time"]) -
            datetime.fromisoformat(self.test_results["start_time"])
        ).total_seconds() if self.test_results["end_time"] else 0
        
        logger.info(f"总时长: {total_time:.2f} 秒")
        logger.info(f"总回合数: {self.test_results['total_rounds']}")
        logger.info(f"成功回合: {self.test_results['successful_rounds']}")
        logger.info(f"失败回合: {len(self.test_results['failed_rounds'])}")
        
        if self.test_results['failed_rounds']:
            logger.warning(f"失败回合列表: {self.test_results['failed_rounds']}")
        
        if self.test_results['errors']:
            logger.error(f"错误数量: {len(self.test_results['errors'])}")
            for error in self.test_results['errors'][:5]:
                logger.error(f"  - {error['stage']}: {error['error']}")
        
        success_rate = (
            self.test_results['successful_rounds'] / self.test_results['total_rounds'] * 100
            if self.test_results['total_rounds'] > 0 else 0
        )
        
        logger.info(f"成功率: {success_rate:.1f}%")
        
        if success_rate >= 95.0:
            logger.info("✓ 测试通过 (≥ 95% 成功率)")
        else:
            logger.warning("✗ 测试失败 (< 95% 成功率)")
    
    def save_results(self):
        """保存测试结果"""
        try:
            results_dir = Path("logs/stability_test")
            results_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            results_file = results_dir / f"stability_test_results_{timestamp}.json"
            
            with open(results_file, 'w', encoding='utf-8') as f:
                json.dump(self.test_results, f, ensure_ascii=False, indent=2)
            
            logger.info(f"测试结果已保存到: {results_file}")
            
        except Exception as e:
            logger.warning(f"保存测试结果失败: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="稳定性测试 - 自动运行多回合测试"
    )
    
    parser.add_argument(
        "--rounds", "-r",
        type=int,
        default=50,
        help="测试回合数 (默认: 50)"
    )
    
    parser.add_argument(
        "--save-interval", "-s",
        type=int,
        default=10,
        help="保存间隔回合数 (默认: 10)"
    )
    
    parser.add_argument(
        "--world", "-w",
        type=str,
        default="mysterious_library",
        help="测试使用的世界 (默认: mysterious_library)"
    )
    
    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        help="启用调试模式"
    )
    
    parser.add_argument(
        "--db",
        type=str,
        default="data/stability_test.db",
        help="测试数据库路径 (默认: data/stability_test.db)"
    )
    
    args = parser.parse_args()
    
    # 设置日志级别
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("调试模式已启用")
    
    # 运行测试
    runner = StabilityTestRunner(
        world_name=args.world,
        db_path=args.db,
        debug=args.debug,
        save_interval=args.save_interval,
        max_rounds=args.rounds
    )
    
    results = runner.run()
    
    # 根据结果退出
    success_rate = (
        results['successful_rounds'] / results['total_rounds'] * 100
        if results['total_rounds'] > 0 else 0
    )
    
    sys.exit(0 if success_rate >= 95.0 else 1)


if __name__ == "__main__":
    main()
