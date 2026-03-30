"""
Game Engine核心模块 - 游戏引擎主类

整合所有模块的主引擎类：
- 游戏状态管理
- 回合循环（7步流程）
- 协调各模块工作


"""

import logging
import json
import copy
import re
from typing import Optional, Dict, Any, List, Tuple, Iterable
from pathlib import Path

from src.data.io_system import IOSystem
from src.utils.debug_logger import DebugLogger
from src.utils.debug_config import DebugConfig
from src.data.models import (
    Character, Item, Map, MapNeighbor, GameState, StateChange, ChangeOperation,
    DMAgentOutput, CheckInput, CheckOutput,
    StateEvolutionOutput,
    CheckType, CheckDifficulty,
    ActivationHint, CheckPlan, DialogueMemoryView, NarrativeMemoryView,
    OutcomeSummary, TurnIntent, TurnResolution, TurnStep, TurnTrace, TurnTraceDigest,
)
from src.agent.input_system import InputSystem, InputResult, InputType
from src.agent.dm_agent import DMAgent
from src.agent.state_evolution import StateEvolution as StateEvolutionAgent
from src.data.init.world_loader import load_initial_world_bundle
from src.engine.context_builders import (
    DialogueMemoryBuilder,
    NarrativeMemoryBuilder,
    TurnTraceContextBuilder,
    WorldStateViewBuilder,
)
try:
    from src.narrative import NarrativeContext, NarrativeContextSnapshot, NarrativeEvent, NarrativeMerger
except Exception:  # pragma: no cover - optional module
    NarrativeContext = None
    NarrativeContextSnapshot = None
    NarrativeEvent = None
    NarrativeMerger = None
try:
    from src.agent.npc import NPCDirector
except Exception:  # pragma: no cover - optional module
    try:
        from src.npc import NPCDirector
    except Exception:  # pragma: no cover - optional module
        NPCDirector = None
from src.rule.rule_system import RuleSystem

# 配置日志
logger = logging.getLogger(__name__)


class GameEngine:
    """
    游戏引擎 - 核心控制器
    
    职责：
    1. 管理游戏状态
    2. 执行7步回合流程
    3. 协调Input、DM Agent、规则系统、状态推演系统
    4. 处理存档/读档
    """
    
    def __init__(
        self,
        io_system: Optional[IOSystem] = None,
        input_system: Optional[InputSystem] = None,
        dm_agent: Optional[DMAgent] = None,
        rule_system: Optional[RuleSystem] = None,
        state_agent: Optional[StateEvolutionAgent] = None,
        db_path: str = "data/game.db",
        npc_response_mode: str = "unified",
        narrative_window: int = 5,
        debug_config: Optional[DebugConfig] = None,
        debug_config_path: Optional[str] = None,
    ):
        """
        初始化游戏引擎
        
        Args:
            io_system: IO系统实例（可选）
            input_system: Input系统实例（可选）
            dm_agent: DM Agent实例（可选）
            rule_system: 规则系统实例（可选）
            state_agent: 状态推演Agent实例（可选）
            db_path: 数据库路径
            debug_config: Debug配置（可选，优先级最高）
            debug_config_path: Debug配置文件路径（可选，默认为 debug_config.yaml）
        """
        # 初始化各子系统
        self.io = io_system or IOSystem(db_path=db_path, mode="sqlite")
        self.input_system = input_system or InputSystem(self.io)
        self.dm_agent = dm_agent or DMAgent()
        self.rule_system = rule_system or RuleSystem()
        self.state_agent = state_agent or StateEvolutionAgent()
        
        # 加载Debug配置（优先级：显式传入 > 配置文件 > 默认）
        if debug_config is None:
            try:
                from src.utils.debug_config import load_config
                debug_config = load_config(config_path=debug_config_path)
            except Exception as e:
                logger.debug(f"加载Debug配置失败，使用默认配置: {e}")
                debug_config = None
        
        # 初始化DebugLogger
        try:
            self.debug_logger = DebugLogger(
                config=debug_config,
                world_name="",
                player_id=""
            )
            # 如果配置启用，启用一致性检查
            if debug_config is None or debug_config.enabled:
                self.debug_logger.enable_consistency_checking(self.io)
        except Exception as e:
            logger.warning(f"DebugLogger初始化失败: {e}")
            self.debug_logger = None

        self._bind_debug_logger_to_agents()
        
        # 游戏状态
        self.game_state = GameState()
        self._current_narrative = ""  # 当前回合叙事
        self._ending_text = ""  # 结局文本
        self._is_game_over = False
        self._npc_director_use_llm = True
        self._narrative_merge_use_llm = True
        self.narrative_context = self._create_narrative_context(window_size=narrative_window)
        self.narrative_merger = self._create_narrative_merger()
        self.npc_director = self._create_npc_director()
        self.dm_dialogue_log: List[Dict[str, str]] = []  # DM与玩家对话记录
        self._pending_npc_action_plans: Dict[str, Any] = {}
        self._current_turn_trace = TurnTrace(turn_id=0)
        self._recent_turn_trace_digests: List[TurnTraceDigest] = []
        self._world_view_builder = WorldStateViewBuilder()
        self._dialogue_memory_builder = DialogueMemoryBuilder()
        self._narrative_memory_builder = NarrativeMemoryBuilder()
        self._turn_trace_context_builder = TurnTraceContextBuilder()
        
        # 回合管理
        self._action_queue: List[str] = []  # 可行动角色队列
        self._current_actor_id: Optional[str] = None  # 当前行动角色
        self._npc_response_mode: str = "unified"
        self.set_npc_response_mode(npc_response_mode)
        
        # 世界配置（可被外部加载器覆盖）
        self.world_name = "default"
        self.end_condition = "玩家死亡或达成剧情结局"
        self._ending_rules: List[Dict[str, Any]] = []
        
        logger.info("游戏引擎初始化完成")
    
    # ============================================================
    # 游戏生命周期管理
    # ============================================================
    
    def new_game(
        self,
        world_name: str = "mysterious_library"
    ) -> bool:
        """
        开始新游戏
        
        Args:
            world_name: 世界配置目录名
            
        Returns:
            是否成功启动
        """
        logger.info(f"开始新游戏，世界: {world_name}")
        
        try:
            clear_method = getattr(self.io, "clear_runtime_store", None)
            if callable(clear_method):
                clear_result = clear_method()
                if clear_result != 0:
                    logger.error("启动新游戏失败: 清空运行库失败，错误码: %s", clear_result)
                    return False
            else:
                logger.warning("IO系统未提供 clear_runtime_store，跳过运行库清理")

            # 清空现有状态
            self.game_state = GameState()
            self._is_game_over = False
            self._ending_text = ""
            self._current_narrative = ""
            self.narrative_context = self._create_narrative_context(
                window_size=getattr(self.narrative_context, "window_size", 5) if self.narrative_context else 5
            )
            self._pending_npc_action_plans = {}
            
            bundle = load_initial_world_bundle(
                self.io,
                player_name=None,
                world_name=world_name
            )
            self.game_state = bundle.game_state
            self.apply_world_settings(
                bundle.world_name,
                bundle.end_condition,
                bundle.npc_response_mode,
                bundle.narrative_window,
                bundle.npc_director_use_llm,
                bundle.narrative_merge_use_llm,
            )
            
            # 初始化回合
            self.game_state.turn_count = 1
            
            # 更新 DebugLogger 的世界名和玩家ID
            if self.debug_logger:
                try:
                    self.debug_logger.world_name = bundle.world_name
                    player = self.game_state.get_player()
                    if player:
                        self.debug_logger.player_id = player.id
                except Exception as e:
                    logger.debug(f"DebugLogger更新世界/玩家信息失败: {e}")
            
            logger.info("新游戏启动成功")
            return True
            
        except Exception as e:
            logger.error(f"启动新游戏失败: {e}")
            return False
    
    def load_game(self, save_name: str = "auto_save") -> bool:
        """
        加载存档
        
        Args:
            save_name: 存档名称
            
        Returns:
            是否成功加载
        """
        logger.info(f"加载存档: {save_name}")
        
        try:
            # 从IO系统加载游戏状态
            # 这里需要实现具体的存档加载逻辑
            # 暂时使用JSON模式加载
            import json
            save_path = Path(f"data/saves/{save_name}.json")
            
            if not save_path.exists():
                logger.warning(f"存档不存在: {save_path}")
                return False
            
            with open(save_path, "r", encoding="utf-8") as f:
                save_data = json.load(f)
            self.dm_dialogue_log = save_data.pop("dm_dialogue_log", [])
            self._restore_narrative_context(save_data.pop("narrative_context", None))
            turn_trace_digests_payload = save_data.pop("recent_turn_trace_digests", [])
            restored_digests: List[TurnTraceDigest] = []
            if isinstance(turn_trace_digests_payload, list):
                for one in turn_trace_digests_payload:
                    if isinstance(one, dict):
                        try:
                            restored_digests.append(TurnTraceDigest(**one))
                        except Exception:
                            continue
            self._recent_turn_trace_digests = restored_digests[-20:]
            self._current_turn_trace = TurnTrace(turn_id=int(save_data.get("turn_count", 0) or 0))
            world_metadata = save_data.pop("world_metadata", {})
            if not isinstance(world_metadata, dict):
                world_metadata = {}
            if not world_metadata:
                world_metadata = {
                    "world_name": save_data.pop("world_name", self.world_name),
                    "end_condition": save_data.pop("end_condition", self.end_condition),
                    "npc_response_mode": save_data.pop("npc_response_mode", self._npc_response_mode),
                    "narrative_window": save_data.pop("narrative_window", getattr(self.narrative_context, "window_size", 5) if self.narrative_context else 5),
                    "npc_director_use_llm": save_data.pop("npc_director_use_llm", self._npc_director_use_llm),
                    "narrative_merge_use_llm": save_data.pop("narrative_merge_use_llm", self._narrative_merge_use_llm),
                }
            
            # 恢复游戏状态
            self.game_state = GameState(**save_data)
            self.apply_world_settings(
                world_name=str(world_metadata.get("world_name", self.world_name) or self.world_name),
                end_condition=str(world_metadata.get("end_condition", self.end_condition) or self.end_condition),
                npc_response_mode=str(world_metadata.get("npc_response_mode", self._npc_response_mode) or self._npc_response_mode),
                narrative_window=int(world_metadata.get("narrative_window", getattr(self.narrative_context, "window_size", 5) if self.narrative_context else 5) or 5),
                npc_director_use_llm=bool(world_metadata.get("npc_director_use_llm", self._npc_director_use_llm)),
                narrative_merge_use_llm=bool(world_metadata.get("narrative_merge_use_llm", self._narrative_merge_use_llm)),
            )
            self._is_game_over = False
            
            logger.info("存档加载成功")
            return True
            
        except Exception as e:
            logger.error(f"加载存档失败: {e}")
            return False
    
    def save_game(self, save_name: str = "auto_save") -> bool:
        """
        保存游戏
        
        Args:
            save_name: 存档名称
            
        Returns:
            是否成功保存
        """
        logger.info(f"保存游戏: {save_name}")
        
        try:
            import json
            save_dir = Path("data/saves")
            save_dir.mkdir(parents=True, exist_ok=True)
            
            save_path = save_dir / f"{save_name}.json"
            
            # 序列化游戏状态
            save_data = self.game_state.model_dump()
            save_data["dm_dialogue_log"] = self.dm_dialogue_log
            narrative_state = self._dump_narrative_context()
            if narrative_state:
                save_data["narrative_context"] = narrative_state
            save_data["dialogue_memory"] = self._dialogue_memory_builder.build(self.dm_dialogue_log).model_dump()
            save_data["narrative_memory"] = self._narrative_memory_builder.build(self._dump_narrative_context()).model_dump()
            save_data["recent_turn_trace_digests"] = [
                digest.model_dump() for digest in self._recent_turn_trace_digests[-20:]
            ]
            save_data["save_version"] = 2
            save_data["world_metadata"] = {
                "world_name": self.world_name,
                "end_condition": self.end_condition,
                "npc_response_mode": self._npc_response_mode,
                "narrative_window": getattr(self.narrative_context, "window_size", 5) if self.narrative_context else 5,
                "npc_director_use_llm": self._npc_director_use_llm,
                "narrative_merge_use_llm": self._narrative_merge_use_llm,
            }
            
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
            
            logger.info("游戏保存成功")
            return True
            
        except Exception as e:
            logger.error(f"保存游戏失败: {e}")
            return False
    
    def restart(self):
        """重新开始游戏"""
        target_world = self.world_name if self.world_name else "mysterious_library"
        self.new_game(target_world)

    def apply_world_settings(
        self,
        world_name: str,
        end_condition: str,
        npc_response_mode: Optional[str] = None,
        narrative_window: Optional[int] = None,
        npc_director_use_llm: Optional[bool] = None,
        narrative_merge_use_llm: Optional[bool] = None,
    ):
        """应用世界级配置（例如来自world.json）。"""
        self.world_name = world_name
        self.end_condition = end_condition or self.end_condition
        if npc_response_mode is not None:
            self.set_npc_response_mode(npc_response_mode)
        if narrative_window is not None:
            self._set_narrative_window(narrative_window)
        if npc_director_use_llm is not None:
            self._npc_director_use_llm = bool(npc_director_use_llm)
            self.npc_director = self._create_npc_director()
        if narrative_merge_use_llm is not None:
            self._narrative_merge_use_llm = bool(narrative_merge_use_llm)
            self.narrative_merger = self._create_narrative_merger()
        # 让状态推演系统共享同一结局条件
        self.state_agent.end_condition = self.end_condition
        self._load_ending_rules()
    
    # ============================================================
    # 核心游戏循环
    # ============================================================
    
    def process_input(self, user_input: str) -> Dict[str, Any]:
        """
        处理玩家输入 - 主入口
        
        执行完整的7步回合流程：
        Step 1: 回合开始 - 清空current_event
        Step 2: 获取行动意图 - 解析输入
        Step 3: DM Agent解析
        Step 4: 规则系统鉴定（如果需要）
        Step 5: 状态推演系统
        Step 6: 应用状态变更
        Step 7: 回合结束
        
        Args:
            user_input: 玩家输入
            
        Returns:
            处理结果字典
        """
        result = {
            "response": None,
            "check_result": None,
            "narrative": None,
            "success": True,
            "game_over": False
        }
        
        # DebugLogger: 记录回合开始
        if self.debug_logger:
            try:
                self.debug_logger.start_turn(user_input)
                self.debug_logger.log_state_snapshot(self.game_state, "before")
            except Exception as e:
                logger.debug(f"DebugLogger记录回合开始失败: {e}")
        
        try:
            # ===== Step 1: 回合开始 =====
            self._turn_start()
            self._begin_turn_trace()
            
            # ===== Step 2: 获取行动意图 =====
            # DebugLogger: 记录 parse_input 阶段
            if self.debug_logger:
                try:
                    self.debug_logger.start_phase("parse_input")
                except Exception as e:
                    logger.debug(f"DebugLogger记录阶段失败: {e}")
            
            input_result = self.input_system.parse_input(user_input)
            
            # DebugLogger: 结束 parse_input 阶段
            if self.debug_logger:
                try:
                    self.debug_logger.end_phase({"input_type": input_result.input_type.value if hasattr(input_result.input_type, 'value') else str(input_result.input_type)})
                except Exception as e:
                    logger.debug(f"DebugLogger记录阶段结束失败: {e}")
            
            # 如果是基础指令，直接处理
            if input_result.input_type == InputType.BASIC_COMMAND:
                if input_result.command:
                    cmd_result = self.input_system.execute_command(
                        input_result.command,
                        input_result.args or [],
                        self.game_state
                    )

                    # 处理需要引擎执行的系统命令
                    if input_result.command == "save":
                        save_name = input_result.args[0] if input_result.args else "auto_save"
                        ok = self.save_game(save_name)
                        cmd_result.direct_response = f"游戏进度已保存: {save_name}" if ok else f"保存失败: {save_name}"

                    if input_result.command == "load":
                        save_name = input_result.args[0] if input_result.args else "auto_save"
                        ok = self.load_game(save_name)
                        cmd_result.direct_response = f"加载存档成功: {save_name}" if ok else f"加载存档失败: {save_name}"
                    
                    # 检查退出指令
                    if cmd_result.direct_response == "EXIT_GAME":
                        result["response"] = "游戏已退出"
                        result["game_over"] = True
                        self._is_game_over = True
                        return result

                    if cmd_result.direct_response == "RESET_GAME":
                        self.restart()
                        result["response"] = "游戏已重置并重新开始"
                        return result

                    if cmd_result.direct_response == "DEBUG_MODE_ON":
                        logging.getLogger().setLevel(logging.DEBUG)
                        result["response"] = "调试模式已开启"
                        return result

                    if cmd_result.direct_response == "DEBUG_MODE_OFF":
                        logging.getLogger().setLevel(logging.INFO)
                        result["response"] = "调试模式已关闭"
                        return result
                    
                    # 应用基础指令产生的变更
                    if cmd_result.changes:
                        failures = self._apply_changes(cmd_result.changes)
                        if failures:
                            result["success"] = False
                            result["response"] = f"状态变更失败: {failures[0]}"
                            return result
                    
                    result["response"] = cmd_result.direct_response
                    return result
                else:
                    result["response"] = input_result.direct_response or "未知指令"
                    return result

            # 自然语言输入，继续DM Agent处理
            natural_input = input_result.natural_input
            
            # ===== Step 3: DM Agent解析 =====
            # DebugLogger: 记录 dm_processing 阶段
            if self.debug_logger:
                try:
                    self.debug_logger.start_phase("dm_processing")
                except Exception as e:
                    logger.debug(f"DebugLogger记录阶段失败: {e}")
            
            dm_output = self._dm_agent_parse(
                natural_input,
                npc_prelude_text="",
            )
            
            # DebugLogger: 结束 dm_processing 阶段
            if self.debug_logger:
                try:
                    self.debug_logger.end_phase({
                        "needs_check": dm_output.needs_check,
                        "interaction_type": getattr(dm_output, "interaction_type", "action")
                    })
                except Exception as e:
                    logger.debug(f"DebugLogger记录阶段结束失败: {e}")
            turn_intent = self._build_turn_intent_from_dm(natural_input, dm_output)
            interaction_type = str(getattr(dm_output, "interaction_type", "action") or "action")
            is_dialogue_turn = interaction_type in {"dialogue", "mixed"}
            has_player_action = interaction_type in {"action", "mixed"}
            
            # 纯对话场景优先返回玩家可见回复，但如果 DM 明确要求 NPC 继续响应，
            # 仍然保留后续流程，避免把“对话”误判成“流程终止”。
            if is_dialogue_turn:
                result["response"] = dm_output.response_to_player
                self._record_dm_dialogue(natural_input, dm_output.response_to_player)
                if not dm_output.npc_response_needed and not has_player_action:
                    return result
            
            check_output = None
            player_resolution_anchor = self._build_player_resolution_anchor(
                dm_output=dm_output,
                check_result=None,
                evolution_result=None,
            )

            # ===== Step 4: 规则系统鉴定 =====
            if dm_output.needs_check and has_player_action:
                check_output = self._execute_check(dm_output)
                result["check_result"] = check_output

            # ===== Step 5: 状态推演系统 =====
            # DebugLogger: 记录 state_evolution 阶段
            if self.debug_logger:
                try:
                    self.debug_logger.start_phase("state_evolution")
                except Exception as e:
                    logger.debug(f"DebugLogger记录阶段失败: {e}")
            
            evolution_result = None
            player_turn_resolution: Optional[TurnResolution] = None
            if has_player_action:
                evolution_result = self._state_evolution(
                    dm_output=dm_output,
                    check_result=check_output,
                    player_resolution_anchor=player_resolution_anchor,
                )
            
            # DebugLogger: 记录状态变更提案
            if self.debug_logger and evolution_result and evolution_result.changes:
                try:
                    self.debug_logger.log_state_changes_proposed(
                        changes=evolution_result.changes,
                        validation_result=None
                    )
                except Exception as e:
                    logger.debug(f"DebugLogger记录状态变更提案失败: {e}")
            
            # DebugLogger: 结束 state_evolution 阶段
            if self.debug_logger:
                try:
                    self.debug_logger.end_phase({
                        "has_changes": bool(evolution_result and evolution_result.changes),
                        "changes_count": len(evolution_result.changes) if evolution_result and evolution_result.changes else 0
                    })
                except Exception as e:
                    logger.debug(f"DebugLogger记录阶段结束失败: {e}")

            player_resolution_anchor = self._build_player_resolution_anchor(
                dm_output=dm_output,
                check_result=check_output,
                evolution_result=evolution_result,
            )
            if has_player_action and evolution_result is not None:
                player_turn_resolution = TurnResolution(
                    actor_id=self.game_state.player_id or "",
                    phase="player",
                    intent_text=turn_intent.intent_text,
                    check_result=check_output,
                    state_changes=list(evolution_result.changes or []),
                    local_narrative=evolution_result.narrative or "",
                    outcome=OutcomeSummary(
                        action_succeeded=bool(player_resolution_anchor.get("action_succeeded", True)),
                        outcome_type="player_action",
                        consequence_tags=[],
                    ),
                )

            fragments: List[Dict[str, str]] = []
            if evolution_result and evolution_result.narrative:
                player = self.game_state.get_player()
                fragments.append(
                    {
                        "actor_id": self.game_state.player_id or "",
                        "actor_name": player.name if player else "玩家",
                        "text": evolution_result.narrative,
                    }
                )
            
            # ===== Step 6: 应用状态变更 =====
            # DebugLogger: 记录 apply_changes 阶段
            if self.debug_logger:
                try:
                    self.debug_logger.start_phase("apply_changes")
                except Exception as e:
                    logger.debug(f"DebugLogger记录阶段失败: {e}")
            
            if evolution_result and evolution_result.changes:
                failures = self._apply_changes(evolution_result.changes)
                if failures:
                    # DebugLogger: 记录变更失败
                    if self.debug_logger:
                        try:
                            self.debug_logger.log_state_changes_proposed(
                                changes=evolution_result.changes,
                                validation_result={"failures": failures}
                            )
                            self.debug_logger.end_phase({"status": "failed", "failures": failures})
                        except Exception as e:
                            logger.debug(f"DebugLogger记录失败: {e}")
                    result["success"] = False
                    result["response"] = f"状态变更失败: {failures[0]}"
                    return result
            
            # DebugLogger: 结束 apply_changes 阶段
            if self.debug_logger:
                try:
                    self.debug_logger.end_phase({"status": "success"})
                except Exception as e:
                    logger.debug(f"DebugLogger记录阶段结束失败: {e}")

            if player_turn_resolution is not None:
                self._current_turn_trace.append_step(
                    TurnStep(
                        step_id=f"turn-{self.game_state.turn_count}-player-1",
                        turn_id=self.game_state.turn_count,
                        actor_id=self.game_state.player_id or "",
                        phase="player",
                        trigger_source="player_input",
                        intent=turn_intent,
                        resolution=player_turn_resolution,
                    )
                )

            npc_follow = self._process_unified_npc_response(
                dm_output=dm_output,
                player_check=check_output,
                player_resolution_anchor=player_resolution_anchor,
                player_turn_intent=turn_intent,
            )
            if npc_follow.get("change_failures"):
                result["success"] = False
                result["response"] = f"状态变更失败: {npc_follow['change_failures'][0]}"
                return result
            fragments.extend(npc_follow.get("fragments", []))

            merged_narrative = self._merge_turn_narratives(
                fragments,
                truth_anchor=player_resolution_anchor,
            )

            result["narrative"] = merged_narrative
            self._current_narrative = merged_narrative
            self._record_dm_dialogue(natural_input, merged_narrative)

            if merged_narrative:
                self._append_narrative_event(
                    actor_id=self.game_state.player_id or "",
                    actor_name=self.game_state.get_player().name if self.game_state.get_player() else "",
                    text=merged_narrative,
                    source="turn_merged",
                )

            if npc_follow.get("game_over"):
                self._is_game_over = True
                result["game_over"] = True
                end_text = npc_follow.get("ending") or ""
                if end_text:
                    result["narrative"] = f"{result['narrative']}\n\n{end_text}" if result["narrative"] else end_text
            
            # 更新玩家current_event
            player = self.game_state.get_player()
            if player:
                # Keep current_event aligned with the displayed narrative to avoid
                # next-loop duplicate output showing a different (player-only) version.
                player.memory.current_event = (
                    merged_narrative
                    or (evolution_result.narrative if evolution_result else "")
                    or result.get("response")
                    or ""
                )
            
            # 结局判定采用双轨：AI主判定，代码规则保底。
            if evolution_result and evolution_result.is_end:
                self._is_game_over = True
                self._ending_text = evolution_result.end_narrative or self._evaluate_configured_endings()
                result["game_over"] = True
                if self._ending_text:
                    result["narrative"] += f"\n\n{self._ending_text}"
            else:
                ai_end = None
                if hasattr(self.state_agent, "check_end_condition"):
                    try:
                        ai_end = self.state_agent.check_end_condition(self.game_state)
                    except Exception as e:
                        logger.warning(f"AI结局复核失败，回退代码保底: {e}")

                if ai_end and ai_end.is_end:
                    self._is_game_over = True
                    self._ending_text = ai_end.end_narrative or self._evaluate_configured_endings()
                    result["game_over"] = True
                    if self._ending_text:
                        result["narrative"] += f"\n\n{self._ending_text}"
                else:
                    config_ending_text = self._evaluate_configured_endings()
                    if config_ending_text:
                        self._is_game_over = True
                        self._ending_text = config_ending_text
                        result["game_over"] = True
                        result["narrative"] += f"\n\n{self._ending_text}"
            
            # ===== Step 7: 回合结束 =====
            self._turn_end(resolved=evolution_result.resolved if evolution_result else True)
            self._finalize_turn_trace(merged_narrative=merged_narrative)
            
            # DebugLogger: 记录回合结束
            if self.debug_logger:
                try:
                    self.debug_logger.log_state_snapshot(self.game_state, "after")
                    self.debug_logger.end_turn(merged_narrative or result.get("response", ""))
                except Exception as e:
                    logger.debug(f"DebugLogger记录回合结束失败: {e}")
            
        except Exception as e:
            # DebugLogger: 记录错误
            if self.debug_logger:
                try:
                    from src.utils.debug_types import EventType, LogLevel
                    self.debug_logger._log_event(
                        EventType.ERROR_OCCURRED,
                        {"error": str(e), "phase": "process_input"},
                        level=LogLevel.ERROR
                    )
                except Exception:
                    pass
            logger.error(f"处理输入时发生错误: {e}")
            result["success"] = False
            result["response"] = f"系统错误: {str(e)}"
        
        return result
    
    def _turn_start(self):
        """回合开始 - Step 1"""
        # 通过IO层统一清空事件并入log，保持内存与持久层一致
        self.io.clear_current_events()
        for char in self.game_state.characters.values():
            char.memory.clear_current()
        
        # 初始化或维护行动队列
        if not self._action_queue:
            self._refresh_action_queue()
        
        # 获取当前行动者
        if self._action_queue:
            self._current_actor_id = self._action_queue[0]
        else:
            self._current_actor_id = self.game_state.player_id
        
        logger.debug(f"第 {self.game_state.turn_count} 回合开始，当前行动者: {self._current_actor_id}")

    def _begin_turn_trace(self) -> None:
        """Initialize per-turn trace container."""
        self._current_turn_trace = TurnTrace(turn_id=self.game_state.turn_count)

    def _finalize_turn_trace(self, merged_narrative: str = "") -> None:
        """Persist a compact digest of the current turn trace for save/replay."""
        if not self._current_turn_trace.steps:
            return

        actor_ids = []
        seen = set()
        for step in self._current_turn_trace.steps:
            if step.actor_id and step.actor_id not in seen:
                seen.add(step.actor_id)
                actor_ids.append(step.actor_id)

        summary = merged_narrative.strip()
        if not summary:
            summary = " | ".join(
                (one.resolution.local_narrative or one.intent.intent_text or "").strip()
                for one in self._current_turn_trace.steps
                if (one.resolution.local_narrative or one.intent.intent_text or "").strip()
            )

        digest = TurnTraceDigest(
            turn_id=self._current_turn_trace.turn_id,
            summary=summary,
            actor_ids=actor_ids,
        )
        self._recent_turn_trace_digests.append(digest)
        self._recent_turn_trace_digests = self._recent_turn_trace_digests[-20:]

    def _build_turn_intent_from_dm(self, raw_input_text: str, dm_output: DMAgentOutput) -> TurnIntent:
        """Adapt legacy DM output into TurnIntent protocol object."""
        interaction_type = str(getattr(dm_output, "interaction_type", "action") or "action")
        if interaction_type not in {"action", "dialogue", "mixed"}:
            interaction_type = "action"

        check_plan = CheckPlan(
            check_needed=bool(dm_output.needs_check),
            check_type=dm_output.check_type,
            attributes=list(dm_output.check_attributes or []),
            target_id=dm_output.check_target,
            difficulty=dm_output.difficulty,
        )

        activation_hint = ActivationHint(
            response_needed_hint=bool(dm_output.npc_response_needed),
            preferred_actor_id=dm_output.npc_actor_id,
            npc_intent_hint=dm_output.npc_intent,
            candidate_npc_ids_hint=list(dm_output.actionable_npcs or []),
        )

        return TurnIntent(
            actor_id=self.game_state.player_id or "",
            raw_input_text=raw_input_text,
            intent_text=dm_output.action_description or raw_input_text,
            interaction_type=interaction_type,
            check_plan=check_plan,
            activation_hint=activation_hint,
        )

    def _process_npc_turns_until_player(self) -> Dict[str, Any]:
        """历史兼容入口：统一响应流程下的单步NPC处理。"""
        narratives: List[str] = []
        max_steps = 1

        if not hasattr(self.state_agent, "evolve_npc_action"):
            self._current_actor_id = self.game_state.player_id
            return {
                "game_over": False,
                "narrative": ""
            }

        for _ in range(max_steps):
            if self.is_player_turn() or not self._current_actor_id:
                break

            actor = self.get_current_actor()
            if not actor or actor.is_player or not self._can_actor_act(actor):
                self._turn_end(resolved=True)
                self._turn_start()
                continue

            planned_actions = self._plan_npc_actions(
                trigger="unified",
                candidate_npc_ids=[actor.id],
            )
            if planned_actions:
                self._pending_npc_action_plans.update(planned_actions)

            npc_check = self._execute_npc_check(actor)
            planned_action = self._pending_npc_action_plans.pop(actor.id, None)

            npc_output = self.state_agent.evolve_npc_action(
                npc_id=actor.id,
                game_state=self.game_state,
                check_result=npc_check,
                npc_intent=self._extract_npc_intent_from_plan(planned_action),
                additional_context=self._build_npc_runtime_context(
                    trigger="unified",
                    npc_action_plan=planned_action,
                ),
            )

            if npc_output.changes:
                failures = self._apply_changes(npc_output.changes)
                if failures:
                    return {
                        "game_over": False,
                        "narrative": "",
                        "ending": "",
                        "change_failures": failures,
                    }

            if npc_output.narrative:
                narratives.append(f"[{actor.name}] {npc_output.narrative}")
                self._append_narrative_event(
                    actor_id=actor.id,
                    actor_name=actor.name,
                    text=npc_output.narrative,
                    source="npc_unified",
                )

            if npc_output.is_end:
                self._is_game_over = True
                self._ending_text = npc_output.end_narrative
                ending_text = "\n\n" + self._ending_text if self._ending_text else ""
                return {
                    "game_over": True,
                    "narrative": "\n".join(narratives) + ending_text
                }

            # NPC回合不支持连动，强制收束为一步，避免阻塞玩家输入。
            self._turn_end(resolved=True)
            self._turn_start()

        return {
            "game_over": False,
            "narrative": "\n".join(narratives)
        }

    def _execute_npc_check(self, actor: Character) -> Optional[CheckOutput]:
        """执行NPC回合的基础规则检定。"""
        try:
            check_input = CheckInput(
                check_type=CheckType.REGULAR,
                attributes=["dex"],
                actor_id=actor.id,
                target_id=None,
                difficulty=CheckDifficulty.REGULAR,
            )
            return self.rule_system.execute_check(check_input, self.game_state)
        except Exception as e:
            logger.warning(f"NPC检定失败，回退为无检定推演: actor={actor.id}, err={e}")
            return None
    
    def _dm_agent_parse(self, player_input: str, npc_prelude_text: str = "") -> DMAgentOutput:
        """
        DM Agent解析 - Step 3
        
        Args:
            player_input: 玩家自然语言输入
            
        Returns:
            DM Agent输出
        """
        import time
        start_time = time.time()
        
        # DebugLogger: 记录LLM请求
        if self.debug_logger:
            try:
                prompt_preview = player_input[:500] if len(player_input) > 500 else player_input
                self.debug_logger.log_llm_request(
                    agent="dm_agent",
                    prompt=prompt_preview,
                    model=getattr(self.dm_agent.llm_service, 'model', 'unknown') if hasattr(self.dm_agent, 'llm_service') else 'unknown',
                    tokens=0
                )
            except Exception as e:
                logger.debug(f"DebugLogger记录LLM请求失败: {e}")
        
        # 调用DM Agent（由DM内部构建上下文）
        dm_output = self.dm_agent.parse_intent(
            player_input=player_input,
            game_state=self.game_state,
            additional_context=self._build_dm_additional_context(npc_prelude_text=npc_prelude_text)
        )
        
        duration_ms = (time.time() - start_time) * 1000
        
        # DebugLogger: 记录LLM响应
        if self.debug_logger:
            try:
                response_summary = f"needs_check={dm_output.needs_check}, action={dm_output.action_description[:100] if dm_output.action_description else ''}"
                self.debug_logger.log_llm_response(
                    agent="dm_agent",
                    response=response_summary,
                    duration_ms=duration_ms,
                    tokens=0
                )
            except Exception as e:
                logger.debug(f"DebugLogger记录LLM响应失败: {e}")
        
        logger.debug(f"DM Agent解析结果: needs_check={dm_output.needs_check}")
        return dm_output

    def _pick_default_npc_actor(self) -> Optional[str]:
        """在响应模式下兜底选取一个同场景可行动NPC。"""
        player = self.game_state.get_player()
        if not player:
            return None

        for char_id, char in self.game_state.characters.items():
            if char.is_player:
                continue
            if char.location != player.location:
                continue
            if self._can_actor_act(char):
                return char_id

        return None
    
    def _execute_check(self, dm_output: DMAgentOutput) -> CheckOutput:
        """
        执行规则鉴定 - Step 4
        
        Args:
            dm_output: DM Agent输出
            
        Returns:
            鉴定结果
        """
        player = self.game_state.get_player()
        
        # 构建鉴定输入
        check_type = CheckType.REGULAR
        if dm_output.check_type == "对抗鉴定":
            check_type = CheckType.OPPOSED
        
        difficulty = CheckDifficulty.REGULAR
        if dm_output.difficulty == "困难":
            difficulty = CheckDifficulty.HARD
        elif dm_output.difficulty == "极难":
            difficulty = CheckDifficulty.EXTREME
        
        check_input = CheckInput(
            check_type=check_type,
            attributes=dm_output.check_attributes,
            actor_id=self.game_state.player_id or "",
            target_id=dm_output.check_target,
            difficulty=difficulty
        )
        
        # 执行鉴定
        check_output = self.rule_system.execute_check(
            check_input,
            self.game_state
        )
        
        logger.debug(f"鉴定结果: {check_output.result}, 骰子: {check_output.dice_roll}")
        return check_output
    
    def _state_evolution(
        self,
        dm_output: DMAgentOutput,
        check_result: Optional[CheckOutput],
        player_resolution_anchor: Optional[Dict[str, Any]] = None,
    ) -> StateEvolutionOutput:
        """
        状态推演 - Step 5
        
        Args:
            dm_output: DM Agent输出
            check_result: 鉴定结果（可选）
            
        Returns:
            状态推演结果
        """
        import time
        start_time = time.time()
        
        world_view = self._world_view_builder.build(self.game_state, self.game_state.player_id or "")
        dialogue_memory = self._dialogue_memory_builder.build(self.dm_dialogue_log)
        narrative_memory = self._narrative_memory_builder.build(self._dump_narrative_context())
        turn_trace_view = self._turn_trace_context_builder.build_full(self._current_turn_trace)

        # DebugLogger: 记录LLM请求
        if self.debug_logger:
            try:
                action_desc = dm_output.action_description[:300] if dm_output.action_description else ""
                self.debug_logger.log_llm_request(
                    agent="state_evolution",
                    prompt=f"action: {action_desc}",
                    model=getattr(self.state_agent.llm_service, 'model', 'unknown') if hasattr(self.state_agent, 'llm_service') else 'unknown',
                    tokens=0
                )
            except Exception as e:
                logger.debug(f"DebugLogger记录LLM请求失败: {e}")

        # 调用状态推演
        evolution_output = self.state_agent.evolve_player_action(
            check_result=check_result,
            action_description=dm_output.action_description,
            game_state=self.game_state,
            additional_context={
                "world_state_view": world_view.model_dump(),
                "dialogue_memory": dialogue_memory.model_dump(),
                "narrative_memory": narrative_memory.model_dump(),
                "turn_trace_so_far": turn_trace_view.model_dump(mode="json"),
                "player_resolution_anchor": player_resolution_anchor or {},
                "npc_response_expected": bool(
                    dm_output.npc_response_needed
                ),
                "npc_response_actor_id": dm_output.npc_actor_id,
            }
        )
        
        duration_ms = (time.time() - start_time) * 1000
        
        # DebugLogger: 记录LLM响应和状态变更
        if self.debug_logger:
            try:
                response_summary = f"changes={len(evolution_output.changes)}, narrative_len={len(evolution_output.narrative) if evolution_output.narrative else 0}"
                self.debug_logger.log_llm_response(
                    agent="state_evolution",
                    response=response_summary,
                    duration_ms=duration_ms,
                    tokens=0
                )
            except Exception as e:
                logger.debug(f"DebugLogger记录LLM响应失败: {e}")
        
        logger.debug(f"状态推演完成，变更数: {len(evolution_output.changes)}")
        return evolution_output
    
    def _apply_changes(self, changes: List[StateChange]) -> List[str]:
        """
        应用状态变更 - Step 6
        
        Args:
            changes: 变更列表

        Returns:
            失败信息列表，空列表表示全部成功
        """
        transaction_snapshot = self._capture_transaction_snapshot()
        canonical_changes = self._canonicalize_change_batch(changes)
        failures: List[str] = []
        for normalized_change in canonical_changes:
            error_code = self.io.apply_state_change(normalized_change)
            
            if error_code == 0:
                logger.debug(f"变更应用成功: {normalized_change.id}.{normalized_change.field}")
                
                # 同步更新内存中的游戏状态
                self._sync_state_change(normalized_change)
                
                # DebugLogger: 记录状态变更应用结果（触发一致性检查）
                if self.debug_logger:
                    try:
                        self.debug_logger.log_state_change_applied(
                            change=normalized_change,
                            error_code=error_code,
                            cascading_effects=None,
                            game_state=self.game_state
                        )
                    except Exception as e:
                        logger.debug(f"DebugLogger记录状态变更失败: {e}")
            else:
                error_message = f"{normalized_change.id}.{normalized_change.field} (错误码: {error_code})"
                logger.warning(f"变更应用失败: {error_message}")
                failures.append(error_message)
                
                # DebugLogger: 记录状态变更失败
                if self.debug_logger:
                    try:
                        self.debug_logger.log_state_change_applied(
                            change=normalized_change,
                            error_code=error_code,
                            cascading_effects=None,
                            game_state=None
                        )
                    except Exception as e:
                        logger.debug(f"DebugLogger记录状态变更失败: {e}")
                
                self._restore_transaction_snapshot(transaction_snapshot)
                break

        return failures

    def _canonicalize_change_batch(self, changes: List[StateChange]) -> List[StateChange]:
        """Normalize and deduplicate a batch to avoid redundant dual-writes in one turn."""
        normalized_changes = [self._normalize_state_change(change) for change in changes]

        location_targets: Dict[str, str] = {}
        for change in normalized_changes:
            target = self._extract_location_target(change)
            if target:
                location_targets[change.id] = target

        deduped_changes: List[StateChange] = []
        seen_signatures = set()
        for change in normalized_changes:
            if self._is_redundant_relationship_change(change, location_targets):
                continue

            normalized_value = self._normalize_relationship_value(change.field, change.value)
            canonical_change = change if normalized_value == change.value else StateChange(
                id=change.id,
                field=change.field,
                operation=change.operation,
                value=normalized_value,
            )

            signature = self._state_change_signature(canonical_change)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            deduped_changes.append(canonical_change)

        return deduped_changes

    def _extract_location_target(self, change: StateChange) -> str:
        if change.field != "location":
            return ""
        if change.operation not in {ChangeOperation.MOVE, ChangeOperation.UPDATE}:
            return ""
        if isinstance(change.value, dict):
            return str(change.value.get("to", "") or "")
        return str(change.value or "")

    def _is_redundant_relationship_change(
        self,
        change: StateChange,
        location_targets: Dict[str, str],
    ) -> bool:
        """Drop ADD relationships already implied by a location move in the same batch."""
        if change.operation != ChangeOperation.ADD:
            return False

        if change.field == "inventory":
            owner_id = change.id
            for item_id in self._flatten_entity_ids(change.value):
                if location_targets.get(item_id) != owner_id:
                    return False
            return True

        if change.field == "entities.items":
            map_id = change.id
            for item_id in self._flatten_entity_ids(change.value):
                if location_targets.get(item_id) != map_id:
                    return False
            return True

        if change.field == "entities.characters":
            map_id = change.id
            for char_id in self._flatten_entity_ids(change.value):
                if location_targets.get(char_id) != map_id:
                    return False
            return True

        return False

    def _normalize_relationship_value(self, field: str, value: Any) -> Any:
        if field in {"inventory", "entities.items", "entities.characters"}:
            normalized = self._flatten_entity_ids(value)
            return normalized[0] if isinstance(value, str) and len(normalized) == 1 else normalized
        return value

    def _state_change_signature(self, change: StateChange) -> str:
        """Build a stable signature for change-level deduplication."""
        raw_value = change.value
        try:
            value_key = json.dumps(raw_value, ensure_ascii=False, sort_keys=True, default=str)
        except TypeError:
            value_key = str(raw_value)
        return f"{change.id}|{change.field}|{change.operation.value}|{value_key}"

    def _capture_transaction_snapshot(self) -> Dict[str, Any]:
        """Capture a rollback snapshot before applying a batch of state changes."""
        return {
            "game_state": self._sanitize_game_state_snapshot(self.game_state.model_dump()),
        }

    def _restore_transaction_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """Restore in-memory state and persist the restored snapshot back to IO."""
        try:
            game_state_data = snapshot.get("game_state", {})
            if isinstance(game_state_data, dict):
                sanitized_state = self._sanitize_game_state_snapshot(game_state_data)
                self.game_state = GameState(**copy.deepcopy(sanitized_state))
                persist_method = getattr(self.io, "save_game_state", None)
                if callable(persist_method):
                    persist_result = persist_method(self.game_state)
                    if persist_result != 0:
                        logger.error(
                            "回滚后持久化失败，内存状态已恢复但IO可能暂时不一致: %s",
                            persist_result,
                        )
            else:
                logger.warning("回滚快照无效，跳过状态恢复")
        except Exception as e:
            logger.error(f"恢复事务快照失败: {e}")

    def _sanitize_game_state_snapshot(self, payload: Any) -> Any:
        """Coerce snapshot payloads into a schema-safe shape before restore."""
        if not isinstance(payload, dict):
            return payload

        data = copy.deepcopy(payload)
        for group_name in ("characters", "items", "maps"):
            group = data.get(group_name)
            if isinstance(group, dict):
                for entity_data in group.values():
                    self._sanitize_entity_snapshot(entity_data)
        return data

    def _sanitize_entity_snapshot(self, entity_data: Any) -> None:
        if not isinstance(entity_data, dict):
            return

        description = entity_data.get("description")
        if isinstance(description, dict) and "public" in description:
            description["public"] = self._normalize_public_description_snapshot(
                description.get("public")
            )

        inventory = entity_data.get("inventory")
        if inventory is not None:
            entity_data["inventory"] = self._flatten_snapshot_ids(inventory)

        entities = entity_data.get("entities")
        if isinstance(entities, dict):
            for key in ("characters", "items"):
                if key in entities:
                    entities[key] = self._flatten_snapshot_ids(entities.get(key))

    def _normalize_public_description_snapshot(self, value: Any) -> List[Dict[str, str]]:
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

    def _flatten_snapshot_ids(self, raw_ids: Any) -> List[str]:
        result: List[str] = []
        seen = set()

        def _append(value: Any) -> None:
            if isinstance(value, str):
                normalized = value.strip()
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    result.append(normalized)
            elif isinstance(value, list):
                for inner in value:
                    _append(inner)

        if isinstance(raw_ids, list):
            for item in raw_ids:
                _append(item)
        else:
            _append(raw_ids)
        return result

    def _normalize_state_change(self, change: StateChange) -> StateChange:
        """对LLM产出的变更做ID容错与操作收敛。"""
        resolved_id = self._resolve_entity_id(change.id)

        normalized_operation = change.operation
        normalized_value = change.value
        normalized_field = change.field

        if change.field == "location" and change.operation in {ChangeOperation.ADD, ChangeOperation.UPDATE}:
            normalized_operation = ChangeOperation.MOVE
            logger.info(
                "检测到location的%s操作，已收敛为MOVE: %s.%s",
                change.operation.value,
                resolved_id,
                change.field,
            )

        # DELETE仅允许白名单列表字段；若LLM对标量字段给出DELETE，收敛为UPDATE默认值。
        if change.operation == ChangeOperation.DELETE and change.field in {
            "location",
            "basic_info",
            "name",
            "description.hint",
        }:
            normalized_operation = ChangeOperation.UPDATE
            if change.field == "location":
                normalized_value = ""
            elif change.field in {"basic_info", "name", "description.hint"}:
                normalized_value = ""
            logger.info(
                "检测到标量DELETE，已收敛为UPDATE: %s.%s",
                resolved_id,
                change.field,
            )

        # location字段容错：将自然语言地点（如“走廊”“北”）收敛为真实地图ID。
        if (
            change.field == "location"
            and resolved_id in self.game_state.characters
            and normalized_operation in {ChangeOperation.UPDATE, ChangeOperation.MOVE}
        ):
            if isinstance(normalized_value, dict):
                location_value = dict(normalized_value)
                if "to" not in location_value:
                    for key in ("target", "value", "location"):
                        if key in location_value:
                            location_value["to"] = location_value.get(key)
                            break
                if location_value.get("to"):
                    location_value["to"] = self._resolve_map_id(location_value.get("to"))
                if location_value.get("from"):
                    location_value["from"] = self._resolve_map_id(location_value.get("from"))
                normalized_value = location_value
            elif isinstance(normalized_value, list):
                normalized_value = self._resolve_map_id(normalized_value[0] if normalized_value else "")
            else:
                normalized_value = self._resolve_map_id(normalized_value)

        if normalized_operation == ChangeOperation.MOVE:
            if isinstance(normalized_value, dict):
                move_value = dict(normalized_value)
                if "to" not in move_value:
                    for key in ("target", "value", "location"):
                        if key in move_value:
                            move_value["to"] = move_value.get(key)
                            break
                normalized_value = move_value
            elif isinstance(normalized_value, list):
                normalized_value = normalized_value[0] if normalized_value else ""

        if (
            resolved_id == change.id
            and normalized_operation == change.operation
            and normalized_value == change.value
            and normalized_field == change.field
        ):
            return change

        if resolved_id != change.id:
            logger.info(f"变更ID已自动纠正: {change.id} -> {resolved_id}")
        return StateChange(
            id=resolved_id,
            field=normalized_field,
            operation=normalized_operation,
            value=normalized_value,
        )

    def _resolve_map_id(self, raw_target: Any) -> str:
        """将地图名/方向等模糊位置解析为真实地图ID；无法解析时返回原值。"""
        target = str(raw_target or "").strip()
        if not target:
            return target
        if target in self.game_state.maps:
            return target

        current_map = self.game_state.get_current_map()
        if current_map:
            for neighbor in current_map.neighbors:
                direction = str(getattr(neighbor, "direction", "") or "").strip()
                if target == direction:
                    return neighbor.id

        for map_id, map_obj in self.game_state.maps.items():
            map_name = str(getattr(map_obj, "name", "") or "").strip()
            if target == map_name:
                return map_id
            if map_name and map_name in target:
                return map_id

        lowered = target.lower()
        if current_map:
            for neighbor in current_map.neighbors:
                desc = str(getattr(neighbor, "description", "") or "").lower()
                if desc and lowered in desc:
                    return neighbor.id

        return target

    def _resolve_entity_id(self, raw_id: str) -> str:
        """将近似ID映射到当前游戏中的真实实体ID。"""
        all_ids = set(self.game_state.characters.keys()) | set(self.game_state.items.keys()) | set(self.game_state.maps.keys())
        if raw_id in all_ids:
            return raw_id

        # 常见玩家别名修正
        if raw_id in {"player_001", "player-001", "player001", "char_player_01"} and self.game_state.player_id:
            return self.game_state.player_id

        def normalize(text: str) -> str:
            return re.sub(r"[^a-z0-9]", "", text.lower())

        target = normalize(raw_id)
        if not target:
            return raw_id

        for entity_id in all_ids:
            if normalize(entity_id) == target:
                return entity_id

        return raw_id
    
    def _sync_state_change(self, change: StateChange):
        """
        同步内存中的状态变更
        
        Args:
            change: 状态变更
        """
        tracked_entity = None
        previous_location: Optional[str] = None
        previous_inventory: List[str] = []
        previous_map_items: List[str] = []
        previous_map_characters: List[str] = []

        # 根据变更类型更新内存对象
        if change.id in self.game_state.characters:
            char = self.game_state.characters[change.id]
            tracked_entity = char
            previous_location = char.location if hasattr(char, "location") else None
            if change.field == "inventory":
                previous_inventory = list(char.inventory or [])
            self._update_entity_field(char, change.field, change.value, change.operation)
        elif change.id in self.game_state.items:
            item = self.game_state.items[change.id]
            tracked_entity = item
            previous_location = item.location if hasattr(item, "location") else None
            self._update_entity_field(item, change.field, change.value, change.operation)
        elif change.id in self.game_state.maps:
            map_obj = self.game_state.maps[change.id]
            tracked_entity = map_obj
            if change.field == "entities.items":
                previous_map_items = list(map_obj.entities.items or [])
            elif change.field == "entities.characters":
                previous_map_characters = list(map_obj.entities.characters or [])
            self._update_entity_field(map_obj, change.field, change.value, change.operation)

        if (
            tracked_entity is not None
            and change.field == "location"
            and change.operation in {ChangeOperation.MOVE, ChangeOperation.UPDATE}
        ):
            new_location = str(getattr(tracked_entity, "location", "") or "")
            self._sync_location_relationships(change.id, previous_location or "", new_location)

        if (
            isinstance(tracked_entity, Character)
            and change.field == "inventory"
            and change.operation in {ChangeOperation.ADD, ChangeOperation.UPDATE, ChangeOperation.DELETE}
        ):
            self._sync_inventory_relationships(
                owner_id=tracked_entity.id,
                previous_inventory=previous_inventory,
                current_inventory=list(tracked_entity.inventory or []),
            )

        if (
            isinstance(tracked_entity, Map)
            and change.field == "entities.items"
            and change.operation in {ChangeOperation.ADD, ChangeOperation.UPDATE, ChangeOperation.DELETE}
        ):
            self._sync_map_items_relationships(
                map_id=tracked_entity.id,
                previous_items=previous_map_items,
                current_items=list(tracked_entity.entities.items or []),
            )

        if (
            isinstance(tracked_entity, Map)
            and change.field == "entities.characters"
            and change.operation in {ChangeOperation.ADD, ChangeOperation.UPDATE, ChangeOperation.DELETE}
        ):
            self._sync_map_characters_relationships(
                map_id=tracked_entity.id,
                previous_characters=previous_map_characters,
                current_characters=list(tracked_entity.entities.characters or []),
            )

        if (
            change.id == self.game_state.player_id
            and change.operation in {ChangeOperation.UPDATE, ChangeOperation.MOVE}
            and change.field == "location"
            and isinstance(change.value, (str, dict))
        ):
            if isinstance(change.value, dict):
                target = str(change.value.get("to", "") or "")
            else:
                target = change.value
            if target:
                self.game_state.current_scene_id = target

    def _remove_id_from_list(self, target_list: Any, entity_id: str) -> None:
        if not isinstance(target_list, list):
            return
        while entity_id in target_list:
            target_list.remove(entity_id)

    def _append_unique_id(self, target_list: Any, entity_id: str) -> None:
        if not isinstance(target_list, list):
            return
        if entity_id not in target_list:
            target_list.append(entity_id)

    def _detach_item_from_all_containers(self, item_id: str) -> None:
        for char in self.game_state.characters.values():
            self._remove_id_from_list(char.inventory, item_id)
        for map_obj in self.game_state.maps.values():
            self._remove_id_from_list(map_obj.entities.items, item_id)

    def _detach_character_from_all_maps(self, char_id: str) -> None:
        for map_obj in self.game_state.maps.values():
            self._remove_id_from_list(map_obj.entities.characters, char_id)

    def _sync_location_relationships(self, entity_id: str, previous_location: str, new_location: str) -> None:
        """Keep map entities and inventories aligned with entity.location in memory."""
        if entity_id.startswith("char-"):
            self._detach_character_from_all_maps(entity_id)
            target_map = self.game_state.maps.get(new_location)
            if target_map:
                self._append_unique_id(target_map.entities.characters, entity_id)
            return

        if entity_id.startswith("item-"):
            self._detach_item_from_all_containers(entity_id)

            target_char = self.game_state.characters.get(new_location)
            if target_char:
                self._append_unique_id(target_char.inventory, entity_id)
                return

            target_map = self.game_state.maps.get(new_location)
            if target_map:
                self._append_unique_id(target_map.entities.items, entity_id)
                return

    def _sync_inventory_relationships(
        self,
        owner_id: str,
        previous_inventory: List[str],
        current_inventory: List[str],
    ) -> None:
        previous = set(self._flatten_entity_ids(previous_inventory))
        current = set(self._flatten_entity_ids(current_inventory))

        added = current - previous
        removed = previous - current

        for item_id in added:
            item = self.game_state.items.get(item_id)
            if not item:
                continue
            self._detach_item_from_all_containers(item_id)
            item.location = owner_id
            owner = self.game_state.characters.get(owner_id)
            if owner:
                self._append_unique_id(owner.inventory, item_id)

        for item_id in removed:
            item = self.game_state.items.get(item_id)
            if not item:
                continue
            if item.location == owner_id:
                item.location = ""
            self._detach_item_from_all_containers(item_id)

    def _sync_map_items_relationships(
        self,
        map_id: str,
        previous_items: List[str],
        current_items: List[str],
    ) -> None:
        previous = set(self._flatten_entity_ids(previous_items))
        current = set(self._flatten_entity_ids(current_items))

        added = current - previous
        removed = previous - current

        target_map = self.game_state.maps.get(map_id)
        if not target_map:
            return

        for item_id in added:
            item = self.game_state.items.get(item_id)
            if not item:
                continue
            self._detach_item_from_all_containers(item_id)
            item.location = map_id
            self._append_unique_id(target_map.entities.items, item_id)

        for item_id in removed:
            item = self.game_state.items.get(item_id)
            if not item:
                continue
            if item.location == map_id:
                item.location = ""
            self._detach_item_from_all_containers(item_id)

    def _sync_map_characters_relationships(
        self,
        map_id: str,
        previous_characters: List[str],
        current_characters: List[str],
    ) -> None:
        previous = set(self._flatten_entity_ids(previous_characters))
        current = set(self._flatten_entity_ids(current_characters))

        added = current - previous
        removed = previous - current

        target_map = self.game_state.maps.get(map_id)
        if not target_map:
            return

        for char_id in added:
            char = self.game_state.characters.get(char_id)
            if not char:
                continue
            self._detach_character_from_all_maps(char_id)
            char.location = map_id
            self._append_unique_id(target_map.entities.characters, char_id)

        for char_id in removed:
            char = self.game_state.characters.get(char_id)
            if not char:
                continue
            if char.location == map_id:
                char.location = ""
            self._detach_character_from_all_maps(char_id)
    
    def _update_entity_field(self, entity: Any, field: str, value: Any, operation: ChangeOperation):
        """按操作类型更新实体字段。
        
        特殊处理:
        - description.add: 只能通过ADD操作添加新描述，系统会自动合并到public
        """
        field_parts = field.split('.')
        
        try:
            current = entity
            for part in field_parts[:-1]:
                current = getattr(current, part)
            
            final_field = field_parts[-1]
            target = getattr(current, final_field)

            if operation == ChangeOperation.UPDATE:
                if field == "neighbors":
                    setattr(current, final_field, self._normalize_neighbors_value(value))
                elif field in {"inventory", "entities.items", "entities.characters"}:
                    setattr(current, final_field, self._flatten_entity_ids(value))
                elif field == "description.add":
                    # UPDATE操作不允许用于description.add，必须使用ADD
                    logger.warning("UPDATE操作不允许用于description.add，请使用ADD操作")
                    return
                else:
                    setattr(current, final_field, value)
            elif operation == ChangeOperation.MOVE:
                if field != "location":
                    logger.warning(f"MOVE操作仅支持location字段: {field}")
                    return
                if isinstance(value, dict):
                    target_id = str(value.get("to", "") or "")
                else:
                    target_id = str(value or "")
                if not target_id:
                    logger.warning("MOVE操作缺少目标ID")
                    return
                setattr(current, final_field, target_id)
            elif operation == ChangeOperation.ADD:
                if isinstance(target, list):
                    if field == "neighbors":
                        target.extend(self._normalize_neighbors_value(value))
                    elif field in {"inventory", "entities.items", "entities.characters"}:
                        for one in self._flatten_entity_ids(value):
                            self._append_unique_id(target, one)
                    elif field == "description.add":
                        # 处理description.add字段 - 添加新描述
                        if isinstance(value, list):
                            for desc in value:
                                if isinstance(desc, dict) and desc.get("description"):
                                    target.append(desc)
                                elif isinstance(desc, str):
                                    target.append({"description": desc})
                        elif isinstance(value, dict) and value.get("description"):
                            target.append(value)
                        elif isinstance(value, str):
                            target.append({"description": value})
                        logger.info(f"向 {entity.id}.description.add 添加了新描述")
                    elif isinstance(value, list):
                        target.extend(value)
                    else:
                        target.append(value)
                else:
                    logger.warning(f"ADD操作目标不是列表: {field}")
            elif operation == ChangeOperation.DELETE:
                if field == "description.add":
                    # 不允许DELETE description.add，应该由系统定期合并
                    logger.warning("DELETE操作不允许用于description.add")
                    return
                if isinstance(target, list):
                    if isinstance(value, list):
                        for one in value:
                            if one in target:
                                target.remove(one)
                    else:
                        if value in target:
                            target.remove(value)
                else:
                    setattr(current, final_field, None)
            else:
                logger.warning(f"未知操作类型: {operation}")

            # 清理历史脏数据：避免 entities.items/entities.characters 出现嵌套list导致后续unhashable异常
            if field in {"entities.items", "entities.characters"}:
                normalized = [x for x in self._flatten_entity_ids(getattr(current, final_field)) if isinstance(x, str)]
                setattr(current, final_field, normalized)
            elif field == "neighbors":
                setattr(
                    current,
                    final_field,
                    self._normalize_neighbors_value(getattr(current, final_field)),
                )
        except AttributeError as e:
            logger.warning(f"更新字段失败: {field}, {e}")

    def _commit_description_adds(self) -> None:
        """将所有实体的description.add合并到description.public，然后清空add。
        
        此方法应在回合结束时调用，将LLM添加的描述正式合并到公开描述中。
        """
        # 合并角色描述
        for char in self.game_state.characters.values():
            if char.description and char.description.add:
                char.description.commit_add_to_public()
                logger.debug(f"已合并角色 {char.id} 的描述add到public")
        
        # 合并物品描述
        for item in self.game_state.items.values():
            if item.description and item.description.add:
                item.description.commit_add_to_public()
                logger.debug(f"已合并物品 {item.id} 的描述add到public")
        
        # 合并地图描述
        for map_obj in self.game_state.maps.values():
            if map_obj.description and map_obj.description.add:
                map_obj.description.commit_add_to_public()
                logger.debug(f"已合并地图 {map_obj.id} 的描述add到public")

    def _normalize_neighbors_value(self, value: Any) -> List[MapNeighbor]:
        """Normalize map neighbors to MapNeighbor objects."""
        if value is None:
            return []
        if isinstance(value, dict):
            value = [value]
        elif not isinstance(value, list):
            value = [value]

        normalized: List[MapNeighbor] = []
        seen = set()
        for entry in value:
            if isinstance(entry, MapNeighbor):
                neighbor = entry
            elif isinstance(entry, dict):
                try:
                    neighbor = MapNeighbor(**entry)
                except Exception:
                    continue
            elif hasattr(entry, "model_dump"):
                try:
                    neighbor = MapNeighbor(**entry.model_dump())
                except Exception:
                    continue
            else:
                continue

            if neighbor.id and neighbor.id not in seen:
                seen.add(neighbor.id)
                normalized.append(neighbor)
        return normalized
    
    def _turn_end(self, resolved: bool = True):
        """
        回合结束 - Step 7
        
        Args:
            resolved: 回合是否已解决
        """
        if resolved:
            # 回合已解决：动态重算队列，并将刚行动角色放到队尾避免连续行动。
            self._refresh_action_queue(last_actor_id=self._current_actor_id)
            
            # 增加回合数
            self.game_state.turn_count += 1
            
            # 同步到game_state.turn_order
            self.game_state.turn_order = self._action_queue.copy()
            
        else:
            # 回合未解决（连动机制），保持当前行动者
            logger.debug("回合未解决，保持当前行动者")
        
        logger.debug(f"回合结束，当前回合: {self.game_state.turn_count}, 行动队列: {self._action_queue}")

    def _record_dm_dialogue(self, player_input: str, dm_response: str):
        """记录玩家与DM的对话历史。"""
        self.dm_dialogue_log.append({
            "turn": str(self.game_state.turn_count),
            "player_input": player_input,
            "dm_response": dm_response,
        })

    def _create_narrative_context(self, window_size: int = 5):
        """Create a narrative context instance, with a no-op fallback."""
        if NarrativeContext is None:
            return _NullNarrativeContext()
        return NarrativeContext(window_size=window_size)

    def _set_narrative_window(self, window_size: int) -> None:
        """Resize narrative window while preserving the current context payload."""
        normalized = max(1, int(window_size))
        current = getattr(self.narrative_context, "window_size", None)
        if current == normalized:
            return

        payload = self._dump_narrative_context()
        if payload:
            payload["window_size"] = normalized
            self._restore_narrative_context(payload)
            return

        self.narrative_context = self._create_narrative_context(window_size=normalized)

    def _create_npc_director(self):
        """Create NPCDirector with a safe fallback to None."""
        if NPCDirector is None:
            return None
        try:
            return NPCDirector(
                use_llm=self._npc_director_use_llm,
                debug_logger=self.debug_logger,
            )
        except Exception as e:
            logger.warning(f"初始化NPCDirector失败，将回退旧逻辑: {e}")
            return None

    def _create_narrative_merger(self):
        """Create NarrativeMerger with graceful fallback."""
        if NarrativeMerger is None:
            return None
        try:
            return NarrativeMerger(
                use_llm=self._narrative_merge_use_llm,
                debug_logger=self.debug_logger,
            )
        except Exception as e:
            logger.warning(f"初始化NarrativeMerger失败，将使用拼接回退: {e}")
            return None

    def _bind_debug_logger_to_agents(self):
        if not self.debug_logger:
            return
        self.dm_agent.debug_logger = self.debug_logger
        self.state_agent.debug_logger = self.debug_logger
        self.dm_agent.debug_agent_name = "dm_agent"
        self.state_agent.debug_agent_name = "state_evolution"
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def _refresh_action_queue(self, last_actor_id: Optional[str] = None):
        """刷新行动队列。"""
        self._action_queue = self._build_dynamic_action_queue(last_actor_id=last_actor_id)

    def _build_dm_additional_context(self, npc_prelude_text: str = "") -> Dict[str, Any]:
        """构建DM解析用的动态上下文。"""
        actor_id = self.game_state.player_id or ""
        world_view = self._world_view_builder.build(self.game_state, actor_id)
        dialogue_memory = self._dialogue_memory_builder.build(self.dm_dialogue_log)
        narrative_memory = self._narrative_memory_builder.build(self._dump_narrative_context())
        turn_trace_view = self._turn_trace_context_builder.build_full(self._current_turn_trace)

        context: Dict[str, Any] = {
            "npc_response_mode": self._npc_response_mode,
            "npc_response_policy": self._describe_npc_mode_policy(),
            "world_state_view": world_view.model_dump(),
            "dialogue_memory": dialogue_memory.model_dump(),
            "narrative_memory": narrative_memory.model_dump(),
            "turn_trace_so_far": turn_trace_view.model_dump(mode="json"),
        }
        if npc_prelude_text:
            context["npc_prelude"] = npc_prelude_text
        return context

    def _build_npc_runtime_context(
        self,
        trigger: str,
        player_check: Optional[CheckOutput] = None,
        player_action_description: str = "",
        npc_action_plan: Optional[Dict[str, Any]] = None,
        player_resolution_anchor: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """构建NPC推演用的动态上下文（统一模式）。"""
        actor_id = self._extract_npc_actor_from_plan(npc_action_plan) if npc_action_plan else None
        if not actor_id:
            actor_id = self._pick_default_npc_actor() or (self.game_state.player_id or "")

        world_view = self._world_view_builder.build(self.game_state, actor_id)
        dialogue_memory = self._dialogue_memory_builder.build(self.dm_dialogue_log)
        narrative_memory = self._narrative_memory_builder.build(self._dump_narrative_context())
        turn_trace_view = self._turn_trace_context_builder.build_for_npc(self._current_turn_trace, actor_id)

        context: Dict[str, Any] = {
            "world_state_view": world_view.model_dump(),
            "dialogue_memory": dialogue_memory.model_dump(),
            "narrative_memory": narrative_memory.model_dump(),
            "turn_trace_so_far": turn_trace_view.model_dump(mode="json"),
            "trigger": trigger,
        }
        if player_check:
            context["player_check_result"] = player_check.model_dump()
        if player_action_description:
            context["player_action_description"] = player_action_description
        if npc_action_plan:
            context["npc_action_plan"] = npc_action_plan
        if player_resolution_anchor:
            context["player_resolution_anchor"] = player_resolution_anchor
        return context

    def _extract_npc_actor_from_plan(self, action_plan: Optional[Dict[str, Any]]) -> Optional[str]:
        """从计划中提取NPC行动者ID。"""
        if not isinstance(action_plan, dict):
            return None
        for key in ("npc_id", "actor_id", "character_id"):
            value = action_plan.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _plan_npc_actions(
        self,
        trigger: str,
        candidate_npc_ids: Optional[List[str]] = None,
        dm_output: Optional[DMAgentOutput] = None,
        player_resolution_anchor: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """生成本回合NPC行动计划，优先使用NPCDirector，失败时回退到最小可执行计划。"""
        raw_ids = list(candidate_npc_ids or [])
        if dm_output:
            raw_ids.extend(list(dm_output.actionable_npcs or []))
            if dm_output.npc_actor_id:
                raw_ids.append(dm_output.npc_actor_id)

        deduped_ids: List[str] = []
        seen = set()
        for npc_id in raw_ids:
            if not isinstance(npc_id, str) or not npc_id.strip():
                continue
            normalized = npc_id.strip()
            if normalized in seen:
                continue
            actor = self.game_state.characters.get(normalized)
            if not actor or actor.is_player or not self._can_actor_act(actor):
                continue
            seen.add(normalized)
            deduped_ids.append(normalized)

        if not deduped_ids:
            fallback_npc = self._pick_default_npc_actor()
            if fallback_npc:
                deduped_ids = [fallback_npc]

        if not deduped_ids:
            return {}

        planned: Dict[str, Any] = {}
        if self.npc_director and hasattr(self.npc_director, "decide_actions"):
            try:
                recent_events = list((self._dump_narrative_context() or {}).get("recent_events", []))
                narrative_context = self._get_narrative_context_for_llm()
                if player_resolution_anchor:
                    anchor_text = json.dumps(player_resolution_anchor, ensure_ascii=False)
                    if narrative_context:
                        narrative_context = f"{narrative_context}\n\nPlayerResolutionAnchor: {anchor_text}"
                    else:
                        narrative_context = f"PlayerResolutionAnchor: {anchor_text}"
                decision = self.npc_director.decide_actions(
                    npc_ids=deduped_ids,
                    game_state=self.game_state,
                    player_intent=dm_output,
                    trigger_source=trigger,
                    recent_events=recent_events,
                    narrative_context=narrative_context,
                )
                actions = getattr(decision, "actions", {}) or {}
                for npc_id, action in actions.items():
                    if npc_id not in deduped_ids:
                        continue
                    action_payload = action.model_dump() if hasattr(action, "model_dump") else dict(action)
                    action_payload.setdefault("npc_id", npc_id)
                    action_payload.setdefault("trigger_source", trigger)
                    planned[npc_id] = action_payload
            except Exception as e:
                logger.warning("NPCDirector规划失败，回退最小计划: %s", e)

        if planned:
            return planned

        for npc_id in deduped_ids:
            actor = self.game_state.characters.get(npc_id)
            if not actor:
                continue
            intent_text = "保持观察，等待局势变化"
            action_type = "wait"
            target_id = None
            if dm_output and dm_output.npc_response_needed:
                intent_text = dm_output.npc_intent or "回应玩家的发言与行动"
                action_type = "talk"
                target_id = self.game_state.player_id or None
            planned[npc_id] = {
                "npc_id": npc_id,
                "action_type": action_type,
                "target_id": target_id,
                "intent_description": intent_text,
                "expected_outcome": None,
                "check": {
                    "check_needed": False,
                    "check_attributes": [],
                    "difficulty": "常规",
                    "check_target_id": None,
                },
                "trigger_source": trigger,
                "metadata": {
                    "reason": "engine_fallback_plan",
                    "anchor": player_resolution_anchor or {},
                },
            }

        return planned

    def _describe_npc_mode_policy(self) -> str:
        """返回当前NPC响应模式的策略说明，供Agent动态拼接上下文。"""
        return "unified: 玩家主流程先执行，再在同回合内统一处理NPC响应。"

    def set_npc_response_mode(self, mode: str):
        """设置NPC响应模式（已收敛为 unified）。"""
        normalized = (mode or "unified").strip().lower()
        if normalized != "unified":
            logger.warning("npc_response_mode '%s' 已废弃，已强制收敛为 unified", mode)
        self._npc_response_mode = "unified"

    def _build_dynamic_action_queue(self, last_actor_id: Optional[str] = None) -> List[str]:
        """按可行动性与优先级动态构建行动队列。"""
        ranked: List[Tuple[Tuple[float, float, float, str], str]] = []
        for char_id, actor in self.game_state.characters.items():
            can_act, sort_key = self._calculate_actor_priority(actor)
            if can_act:
                ranked.append((sort_key, char_id))

        ranked.sort(key=lambda x: x[0])
        ordered_ids = [char_id for _, char_id in ranked]

        # 若刚行动角色仍可行动，则放到队尾，避免连续行动。
        if last_actor_id and last_actor_id in ordered_ids:
            ordered_ids.remove(last_actor_id)
            ordered_ids.append(last_actor_id)

        return ordered_ids

    def _calculate_actor_priority(self, actor: Character) -> Tuple[bool, Tuple[float, float, float, str]]:
        """按不变量计算行动优先级排序键。"""
        if not self._can_actor_act(actor):
            return (False, ())

        max_hp = max(1, actor.status.max_hp)
        hp_ratio = actor.status.hp / max_hp
        san_ratio = actor.status.san / 100.0

        return (
            True,
            (
                -float(actor.attributes.dex),
                -float(hp_ratio),
                -float(san_ratio),
                actor.id,
            ),
        )
    
    def _can_actor_act(self, actor: Character) -> bool:
        """检查角色是否还能继续行动"""
        # 检查角色是否存活/有意识
        if actor.status.hp <= 0:
            return False
        if actor.status.san <= 0:
            return False
        return True
    
    def get_current_actor(self) -> Optional[Character]:
        """获取当前行动角色"""
        if self._current_actor_id:
            return self.game_state.characters.get(self._current_actor_id)
        return None
    
    def is_player_turn(self) -> bool:
        """检查是否是玩家回合"""
        return self._current_actor_id == self.game_state.player_id
    
    def _build_game_context(self) -> Dict[str, Any]:
        """构建游戏上下文"""
        current_map = self.game_state.get_current_map()
        player = self.game_state.get_player()

        nearby_characters: List[Dict[str, Any]] = []
        nearby_items: List[Dict[str, Any]] = []

        if current_map:
            for char_id in self._flatten_entity_ids(current_map.entities.characters):
                char = self.game_state.characters.get(char_id)
                if char and char.id != self.game_state.player_id:
                    nearby_characters.append({
                        "id": char.id,
                        "name": char.name,
                        "basic_info": char.basic_info,
                        "location": char.location,
                    })

            for item_id in self._flatten_entity_ids(current_map.entities.items):
                item = self.game_state.items.get(item_id)
                if item:
                    nearby_items.append({
                        "id": item.id,
                        "name": item.name,
                        "location": item.location,
                    })

        return {
            "turn_count": self.game_state.turn_count,
            "player_id": self.game_state.player_id,
            "current_scene_id": self.game_state.current_scene_id,
            "current_location": {
                "id": current_map.id,
                "name": current_map.name,
                "description": current_map.description.get_public_text(),
            } if current_map else None,
            "nearby_characters": nearby_characters,
            "nearby_items": nearby_items,
            "player_status": {
                "hp": player.status.hp,
                "max_hp": player.status.max_hp,
                "san": player.status.san,
                "lucky": player.status.lucky,
            } if player else None,
            "narrative_context": self._dump_narrative_context(),
        }

    def _flatten_entity_ids(self, raw_ids: Any) -> List[str]:
        """扁平化实体ID列表，忽略非字符串值，避免嵌套list污染后续流程。"""
        result: List[str] = []
        seen = set()

        def _append(value: Any) -> None:
            if isinstance(value, str):
                normalized = value.strip()
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    result.append(normalized)
            elif isinstance(value, list):
                for inner in value:
                    _append(inner)

        if isinstance(raw_ids, list):
            for value in raw_ids:
                _append(value)
        else:
            _append(raw_ids)
        return result

    def _append_narrative_event(
        self,
        actor_id: str,
        actor_name: str,
        text: str,
        source: str,
    ) -> None:
        if not self.narrative_context or NarrativeEvent is None:
            return
        self.narrative_context.add_event(
            NarrativeEvent(
                turn=self.game_state.turn_count,
                actor_id=actor_id,
                actor_name=actor_name,
                text=text,
                source=source,
            )
        )

    def _get_narrative_context_for_llm(self) -> str:
        """Return a compact narrative context block for prompt assembly."""
        if not self.narrative_context:
            return ""
        if hasattr(self.narrative_context, "get_context_for_llm"):
            return self.narrative_context.get_context_for_llm()
        return ""

    def _dump_narrative_context(self) -> Dict[str, Any]:
        """Serialize narrative context for save files."""
        if not self.narrative_context:
            return {}
        if hasattr(self.narrative_context, "export_state"):
            return self.narrative_context.export_state()
        return {}

    def _restore_narrative_context(self, payload: Any) -> None:
        """Restore narrative context from a saved snapshot or dict."""
        if not payload:
            self.narrative_context = self._create_narrative_context()
            return

        if isinstance(payload, dict):
            if NarrativeContextSnapshot is None or NarrativeContext is None or NarrativeEvent is None:
                self.narrative_context = self._create_narrative_context(
                    window_size=int(payload.get("window_size", 5) or 5)
                )
                return

            summary_lines = payload.get("summary_lines")
            if not isinstance(summary_lines, list):
                summary_text = str(payload.get("summary", "") or "")
                summary_lines = [line.strip() for line in summary_text.splitlines() if line.strip()]

            snapshot_data = {
                "window_size": int(payload.get("window_size", 5) or 5),
                "recent_events": payload.get("recent_events", []),
                "summary_lines": summary_lines,
                "key_facts": payload.get("key_facts", []),
            }

            try:
                snapshot = NarrativeContextSnapshot(**snapshot_data)
                self.narrative_context = NarrativeContext.from_snapshot(snapshot)
            except Exception:
                self.narrative_context = self._create_narrative_context(
                    window_size=snapshot_data["window_size"]
                )
            return

        self.narrative_context = self._create_narrative_context()

    def _load_ending_rules(self):
        """加载世界配置中的结局规则。"""
        endings_dir = Path("config/world") / self.world_name / "endings"
        self._ending_rules = []

        if not endings_dir.exists() or not endings_dir.is_dir():
            return

        for ending_file in sorted(endings_dir.glob("*.json")):
            try:
                with open(ending_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._ending_rules.append(data)
            except Exception as e:
                logger.warning(f"读取结局配置失败: {ending_file}, {e}")

        self._ending_rules.sort(key=lambda x: x.get("priority", 0), reverse=True)

    def _evaluate_configured_endings(self) -> str:
        """评估配置结局，命中返回结局文本，否则返回空字符串。"""
        if not self._ending_rules:
            return ""

        for ending in self._ending_rules:
            condition_expr = str(ending.get("condition_expr", "")).strip()
            if not condition_expr:
                continue

            if self._evaluate_condition_expr(condition_expr):
                return str(ending.get("end_narrative", "")).strip()

        return ""

    def _evaluate_condition_expr(self, expr: str) -> bool:
        """评估简易结局表达式。"""
        player = self.game_state.get_player()
        if not player:
            return False

        # all(a,b,c)
        if expr.startswith("all(") and expr.endswith(")"):
            args = self._split_expr_args(expr[4:-1])
            return all(self._evaluate_condition_expr(a) for a in args)

        # any(a,b,c)
        if expr.startswith("any(") and expr.endswith(")"):
            args = self._split_expr_args(expr[4:-1])
            return any(self._evaluate_condition_expr(a) for a in args)

        # 基础内置条件
        if expr == "player_hp_le_0":
            return player.status.hp <= 0
        if expr == "player_san_le_0":
            return player.status.san <= 0

        if expr.startswith("player_at:"):
            map_id = expr.split(":", 1)[1].strip()
            return player.location == map_id

        if expr.startswith("has_item:"):
            item_id = expr.split(":", 1)[1].strip()
            return item_id in player.inventory

        return False

    def _split_expr_args(self, raw: str) -> List[str]:
        """按最外层逗号拆分表达式参数。"""
        args: List[str] = []
        depth = 0
        buf: List[str] = []

        for ch in raw:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)

            if ch == "," and depth == 0:
                part = "".join(buf).strip()
                if part:
                    args.append(part)
                buf = []
                continue

            buf.append(ch)

        tail = "".join(buf).strip()
        if tail:
            args.append(tail)

        return args
    
    # ============================================================
    # 查询方法
    # ============================================================
    
    def get_game_state(self) -> GameState:
        """获取当前游戏状态"""
        return self.game_state
    
    def is_game_over(self) -> bool:
        """检查游戏是否结束"""
        return self._is_game_over
    
    def get_ending_text(self) -> str:
        """获取结局文本"""
        return self._ending_text
    
    def get_current_narrative(self) -> str:
        """获取当前叙事"""
        return self._current_narrative
    
    def end_session(self) -> Optional[Any]:
        """结束会话，记录最终状态和日志。
        
        Returns:
            会话摘要（如果DebugLogger可用）
        """
        summary = None
        if self.debug_logger:
            try:
                summary = self.debug_logger.end_session(self.game_state)
                logger.info(f"会话结束，共 {summary.total_turns} 回合，{summary.total_llm_calls} 次LLM调用")
            except Exception as e:
                logger.warning(f"DebugLogger结束会话失败: {e}")
        return summary

    def _extract_npc_intent_from_plan(self, action_plan: Any) -> str:
        """Extract intent description from NPC action plan."""
        if not action_plan:
            return ""
        if isinstance(action_plan, dict):
            return action_plan.get("intent_description", "")
        if hasattr(action_plan, "intent_description"):
            return str(action_plan.intent_description)
        return ""

    def _merge_turn_narratives(
        self,
        fragments: List[Dict[str, str]],
        truth_anchor: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Merge narrative fragments into a single coherent turn narrative."""
        cleaned = [fragment for fragment in fragments if (fragment.get("text") or "").strip()]
        if not cleaned:
            return ""

        if self.narrative_merger and hasattr(self.narrative_merger, "merge_v2"):
            v2_result = self.narrative_merger.merge_v2(
                turn_trace_steps=list(self._current_turn_trace.steps),
                turn_truth_anchor=truth_anchor or {},
                narrative_memory=self._narrative_memory_builder.build(self._dump_narrative_context()),
            )
            if v2_result and v2_result.merged_narrative:
                return v2_result.merged_narrative.strip()

        if self.narrative_merger and hasattr(self.narrative_merger, "merge"):
            merged = self.narrative_merger.merge(
                fragments=cleaned,
                game_state=self.game_state,
                context=self._get_narrative_context_for_llm(),
                truth_anchor=truth_anchor,
            )
            if merged:
                return merged.strip()

        return "\n".join(fragment["text"].strip() for fragment in cleaned if fragment.get("text"))

    def _process_unified_npc_response(
        self,
        dm_output: DMAgentOutput,
        player_check: Optional[CheckOutput],
        player_resolution_anchor: Optional[Dict[str, Any]] = None,
        player_turn_intent: Optional[TurnIntent] = None,
    ) -> Dict[str, Any]:
        """统一后置NPC流程：玩家行动后处理NPC响应。"""
        if not hasattr(self.state_agent, "evolve_npc_action"):
            return {"game_over": False, "fragments": []}

        should_trigger = True
        if not should_trigger:
            return {"game_over": False, "fragments": []}

        candidate_ids = list(dm_output.actionable_npcs or [])
        if dm_output.npc_actor_id and dm_output.npc_actor_id not in candidate_ids:
            candidate_ids.append(dm_output.npc_actor_id)
        if not candidate_ids:
            queue_candidates = [
                actor_id
                for actor_id in self._action_queue
                if actor_id != self.game_state.player_id
                and actor_id in self.game_state.characters
                and self._can_actor_act(self.game_state.characters[actor_id])
            ]
            if queue_candidates:
                candidate_ids.append(queue_candidates[0])
        if not candidate_ids:
            default_npc = self._pick_default_npc_actor()
            if default_npc:
                candidate_ids.append(default_npc)

        if not candidate_ids:
            return {"game_over": False, "fragments": []}

        trigger_label = "unified"
        plans = self._plan_npc_actions(
            trigger=trigger_label,
            dm_output=dm_output,
            candidate_npc_ids=candidate_ids,
            player_resolution_anchor=player_resolution_anchor,
        )
        if not plans:
            return {"game_over": False, "fragments": []}

        queue_order = self._build_dynamic_action_queue()
        ordered_npc_ids = [npc_id for npc_id in queue_order if npc_id in plans]
        for npc_id in plans.keys():
            if npc_id not in ordered_npc_ids:
                ordered_npc_ids.append(npc_id)

        fragments: List[Dict[str, str]] = []
        final_ending = ""
        for npc_id in ordered_npc_ids:
            npc = self.game_state.characters.get(npc_id)
            if not npc or npc.is_player or not self._can_actor_act(npc):
                continue

            plan = plans.get(npc_id)
            npc_check = self._execute_npc_check(npc)
            npc_output = self.state_agent.evolve_npc_action(
                npc_id=npc.id,
                game_state=self.game_state,
                check_result=npc_check,
                npc_intent=self._extract_npc_intent_from_plan(plan),
                additional_context=self._build_npc_runtime_context(
                    trigger=trigger_label,
                    player_check=player_check,
                    player_action_description=dm_output.action_description,
                    npc_action_plan=plan,
                    player_resolution_anchor=player_resolution_anchor,
                ),
            )

            npc_intent_text = self._extract_npc_intent_from_plan(plan) or "NPC响应玩家行动"
            npc_turn_intent = TurnIntent(
                actor_id=npc.id,
                raw_input_text=(player_turn_intent.raw_input_text if player_turn_intent else dm_output.action_description),
                intent_text=npc_intent_text,
                interaction_type="action",
                check_plan=CheckPlan(
                    check_needed=npc_check is not None,
                    check_type="非对抗鉴定" if npc_check is not None else None,
                    attributes=["dex"] if npc_check is not None else None,
                    target_id=None,
                    difficulty="常规" if npc_check is not None else None,
                ),
                activation_hint=ActivationHint(
                    response_needed_hint=True,
                    preferred_actor_id=npc.id,
                    npc_intent_hint=None,
                    candidate_npc_ids_hint=[npc.id],
                ),
            )
            npc_turn_resolution = TurnResolution(
                actor_id=npc.id,
                phase="npc",
                intent_text=npc_intent_text,
                check_result=npc_check,
                state_changes=list(npc_output.changes or []),
                local_narrative=npc_output.narrative or "",
                outcome=OutcomeSummary(
                    action_succeeded=not bool(npc_output.is_end),
                    outcome_type="npc_response",
                    consequence_tags=[],
                ),
            )
            self._current_turn_trace.append_step(
                TurnStep(
                    step_id=f"turn-{self.game_state.turn_count}-npc-{npc.id}",
                    turn_id=self.game_state.turn_count,
                    actor_id=npc.id,
                    phase="npc",
                    trigger_source=trigger_label,
                    intent=npc_turn_intent,
                    resolution=npc_turn_resolution,
                )
            )

            if npc_output.changes:
                failures = self._apply_changes(npc_output.changes)
                if failures:
                    return {
                        "game_over": False,
                        "narrative": "",
                        "ending": "",
                        "change_failures": failures,
                    }

            if npc_output.narrative:
                fragments.append(
                    {
                        "actor_id": npc.id,
                        "actor_name": npc.name,
                        "text": npc_output.narrative,
                    }
                )

            if npc_output.is_end:
                final_ending = npc_output.end_narrative or final_ending
                return {"game_over": True, "fragments": fragments, "ending": final_ending}

        return {"game_over": False, "fragments": fragments, "ending": final_ending}

    def _build_player_resolution_anchor(
        self,
        dm_output: DMAgentOutput,
        check_result: Optional[CheckOutput],
        evolution_result: Optional[StateEvolutionOutput],
    ) -> Dict[str, Any]:
        """Build a deterministic truth anchor from check system + player resolution."""
        check_required = bool(dm_output.needs_check)
        check_outcome = "auto_success"
        action_succeeded = True

        if check_result is not None:
            check_outcome = str(check_result.result.value)
            action_succeeded = check_outcome in {"成功", "大成功"}

        anchor: Dict[str, Any] = {
            "check_required": check_required,
            "check_outcome": check_outcome,
            "action_succeeded": action_succeeded,
            "action_description": dm_output.action_description,
            "consistency_rule": "下游NPC决策与叙事必须与check_outcome保持一致，不得改写胜负事实。",
        }

        if check_result is not None:
            anchor["check_result"] = check_result.model_dump()

        if evolution_result is not None:
            anchor["player_narrative"] = evolution_result.narrative
            anchor["player_changes"] = [change.model_dump() for change in evolution_result.changes]

        return anchor


# ============================================================
# Null Narrative Context Fallback
# ============================================================

class _NullNarrativeContext:
    """Fallback when NarrativeContext is not available."""

    def __init__(self, window_size: int = 5):
        self.window_size = window_size
        self.recent_events: List[Any] = []
        self.summary_lines: List[str] = []
        self.key_facts: set = set()
        self.summary: str = ""

    def add_event(self, event: Any) -> None:
        """No-op event addition."""
        pass

    def get_context_for_llm(self) -> str:
        """Return empty context for LLM prompts."""
        return ""

    def export_state(self) -> Dict[str, Any]:
        """Return empty state for serialization."""
        return {}


# ============================================================
# 便捷函数
# ============================================================

def create_game_engine(
    db_path: str = "data/game.db",
    **kwargs
) -> GameEngine:
    """
    创建游戏引擎实例
    
    Args:
        db_path: 数据库路径
        **kwargs: 其他配置参数
        
    Returns:
        GameEngine实例
    """
    return GameEngine(db_path=db_path, **kwargs)


# 导出
__all__ = [
    "GameEngine",
    "create_game_engine"
]


# 测试入口
if __name__ == "__main__":
    # 简单测试
    engine = create_game_engine()
    print("GameEngine模块测试完成")
