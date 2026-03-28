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
from src.data.models import (
    Character, Item, Map, MapNeighbor, GameState, StateChange, ChangeOperation,
    DMAgentOutput, CheckInput, CheckOutput,
    StateEvolutionOutput,
    CheckType, CheckDifficulty
)
from src.agent.input_system import InputSystem, InputResult, InputType
from src.agent.dm_agent import DMAgent
from src.agent.state_evolution import StateEvolution as StateEvolutionAgent
from src.data.init.world_loader import load_initial_world_bundle
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
        """
        # 初始化各子系统
        self.io = io_system or IOSystem(db_path=db_path, mode="sqlite")
        self.input_system = input_system or InputSystem(self.io)
        self.dm_agent = dm_agent or DMAgent()
        self.rule_system = rule_system or RuleSystem()
        self.state_agent = state_agent or StateEvolutionAgent()
        
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
        
        # 回合管理
        self._action_queue: List[str] = []  # 可行动角色队列
        self._current_actor_id: Optional[str] = None  # 当前行动角色
        self._npc_response_mode: str = "unified"
        self.set_npc_response_mode(npc_response_mode)
        
        # 世界配置（可被外部加载器覆盖）
        self.world_name = "default"#修改建议:检查一下各个默认值是否统一
        self.end_condition = "玩家死亡或达成剧情结局"
        self._ending_rules: List[Dict[str, Any]] = []
        
        logger.info("游戏引擎初始化完成")
    
    # ============================================================
    # 游戏生命周期管理
    # ============================================================
    
    def new_game( #修改建议:检查一下这个函数用到没有,main.py里有一个start_new_game 这儿又有一个,思考一下需不需要统一接口
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
            save_data["save_version"] = 1
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
        if npc_response_mode:
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
        
        try:
            # ===== Step 1: 回合开始 =====
            self._turn_start()
            
            # ===== Step 2: 获取行动意图 =====
            input_result = self.input_system.parse_input(user_input)
            
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
                        logging.getLogger().setLevel(logging.INFO)  #修改建议:没有提供关闭调试指令的'\'指令
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
            dm_output = self._dm_agent_parse(
                natural_input,
                npc_prelude_text="",
            )
            
            # 纯对话场景优先返回玩家可见回复，但如果 DM 明确要求 NPC 继续响应，
            # 仍然保留后续流程，避免把“对话”误判成“流程终止”。
            if dm_output.is_dialogue:
                result["response"] = dm_output.response_to_player
                self._record_dm_dialogue(natural_input, dm_output.response_to_player)
                if not dm_output.npc_response_needed:
                    return result
            
            check_output = None
            player_resolution_anchor = self._build_player_resolution_anchor(
                dm_output=dm_output,
                check_result=None,
                evolution_result=None,
            )

            # ===== Step 4: 规则系统鉴定 =====
            if dm_output.needs_check and not dm_output.is_dialogue:
                check_output = self._execute_check(dm_output)
                result["check_result"] = check_output

            # ===== Step 5: 状态推演系统 =====
            evolution_result = None
            if not dm_output.is_dialogue:
                evolution_result = self._state_evolution(
                    dm_output=dm_output,
                    check_result=check_output,
                    player_resolution_anchor=player_resolution_anchor,
                )
                player_resolution_anchor = self._build_player_resolution_anchor(
                    dm_output=dm_output,
                    check_result=check_output,
                    evolution_result=evolution_result,
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
            if evolution_result and evolution_result.changes:
                failures = self._apply_changes(evolution_result.changes)
                if failures:
                    result["success"] = False
                    result["response"] = f"状态变更失败: {failures[0]}"
                    return result

            npc_follow = self._process_unified_npc_response(
                dm_output=dm_output,
                player_check=check_output,
                player_resolution_anchor=player_resolution_anchor,
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
            
        except Exception as e:
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

    def _process_npc_turns_until_player(self) -> Dict[str, Any]:
        """在玩家输入前处理连续NPC回合，直到轮到玩家或游戏结束。"""
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
                trigger="queue",
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
                    trigger="queue",
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
                    source="npc_queue",
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
        # 调用DM Agent（由DM内部构建上下文）
        dm_output = self.dm_agent.parse_intent(
            player_input=player_input,
            game_state=self.game_state,
            additional_context=self._build_dm_additional_context(npc_prelude_text=npc_prelude_text)
        )
        
        logger.debug(f"DM Agent解析结果: needs_check={dm_output.needs_check}")
        return dm_output

    def _process_reactive_npc_response(
        self,
        dm_output: DMAgentOutput,
        player_check: Optional[CheckOutput],
    ) -> Dict[str, Any]:
        """响应式NPC流程：仅在DM判定需要时触发。"""
        if not hasattr(self.state_agent, "evolve_npc_action"):
            return {"game_over": False, "narrative": ""}

        if not dm_output.npc_response_needed:
            return {"game_over": False, "narrative": ""}

        action_plan = self._extract_npc_action_plan(dm_output)
        npc_id = (
            self._extract_npc_actor_from_plan(action_plan)
            or dm_output.npc_actor_id
            or self._pick_default_npc_actor()
        )
        if not npc_id:
            logger.debug("响应模式已开启，但未找到可响应NPC")
            return {"game_over": False, "narrative": ""}

        npc = self.game_state.characters.get(npc_id)
        if not npc or npc.is_player or not self._can_actor_act(npc):
            return {"game_over": False, "narrative": ""}

        npc_check = self._execute_npc_check(npc)
        npc_output = self.state_agent.evolve_npc_action(
            npc_id=npc.id,
            game_state=self.game_state,
            check_result=npc_check,
            npc_intent=dm_output.npc_intent or self._extract_npc_intent_from_plan(action_plan),
            additional_context=self._build_npc_runtime_context(
                trigger="reactive",
                player_check=player_check,
                player_action_description=dm_output.action_description,
                npc_action_plan=action_plan,
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
            self._append_narrative_event(
                actor_id=npc.id,
                actor_name=npc.name,
                text=npc_output.narrative,
                source="npc_reactive",
            )

        return {
            "game_over": npc_output.is_end,
            "narrative": f"[{npc.name}] {npc_output.narrative}" if npc_output.narrative else "",
            "ending": npc_output.end_narrative,
        }

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
        # 调用状态推演
        evolution_output = self.state_agent.evolve_player_action(
            check_result=check_result,
            action_description=dm_output.action_description,
            game_state=self.game_state,
            additional_context={
                "engine_context": self._build_game_context(),
                    "narrative_context": self._get_narrative_context_for_llm(),
                    "player_resolution_anchor": player_resolution_anchor or {},
                "npc_response_mode": self._npc_response_mode,
                "npc_response_policy": self._describe_npc_mode_policy(),
                "npc_response_expected": bool(
                    dm_output.npc_response_needed
                ),
                "npc_response_actor_id": dm_output.npc_actor_id,
            }
        )
        
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
        failures: List[str] = []
        for change in changes:
            normalized_change = self._normalize_state_change(change)
            error_code = self.io.apply_state_change(normalized_change)
            
            if error_code == 0:
                logger.debug(f"变更应用成功: {normalized_change.id}.{normalized_change.field}")
                
                # 同步更新内存中的游戏状态
                self._sync_state_change(normalized_change)
            else:
                error_message = f"{normalized_change.id}.{normalized_change.field} (错误码: {error_code})"
                logger.warning(f"变更应用失败: {error_message}")
                failures.append(error_message)
                self._restore_transaction_snapshot(transaction_snapshot)
                break

        return failures

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
        """对LLM产出的变更做ID容错，避免因格式差异导致变更丢失。"""
        resolved_id = self._resolve_entity_id(change.id)
        if resolved_id == change.id:
            return change

        logger.info(f"变更ID已自动纠正: {change.id} -> {resolved_id}")
        return StateChange(
            id=resolved_id,
            field=change.field,
            operation=change.operation,
            value=change.value,
        )

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
        # 根据变更类型更新内存对象
        if change.id in self.game_state.characters:
            char = self.game_state.characters[change.id]
            self._update_entity_field(char, change.field, change.value, change.operation)
        elif change.id in self.game_state.items:
            item = self.game_state.items[change.id]
            self._update_entity_field(item, change.field, change.value, change.operation)
        elif change.id in self.game_state.maps:
            map_obj = self.game_state.maps[change.id]
            self._update_entity_field(map_obj, change.field, change.value, change.operation)

        if (
            change.id == self.game_state.player_id
            and change.operation == ChangeOperation.UPDATE
            and change.field == "location"
            and isinstance(change.value, str)
        ):
            self.game_state.current_scene_id = change.value
    
    def _update_entity_field(self, entity: Any, field: str, value: Any, operation: ChangeOperation):
        """按操作类型更新实体字段。"""
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
                else:
                    setattr(current, final_field, value)
            elif operation == ChangeOperation.ADD:
                if isinstance(target, list):
                    if field == "neighbors":
                        target.extend(self._normalize_neighbors_value(value))
                    elif isinstance(value, list):
                        target.extend(value)
                    else:
                        target.append(value)
                else:
                    logger.warning(f"ADD操作目标不是列表: {field}")
            elif operation == ChangeOperation.DELETE:
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
            return NPCDirector(use_llm=self._npc_director_use_llm)
        except Exception as e:
            logger.warning(f"初始化NPCDirector失败，将回退旧逻辑: {e}")
            return None

    def _create_narrative_merger(self):
        """Create NarrativeMerger with graceful fallback."""
        if NarrativeMerger is None:
            return None
        try:
            return NarrativeMerger(use_llm=self._narrative_merge_use_llm)
        except Exception as e:
            logger.warning(f"初始化NarrativeMerger失败，将使用拼接回退: {e}")
            return None
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def _refresh_action_queue(self, last_actor_id: Optional[str] = None):
        """刷新行动队列。"""
        self._action_queue = self._build_dynamic_action_queue(last_actor_id=last_actor_id)

    def _build_dm_additional_context(self, npc_prelude_text: str = "") -> Dict[str, Any]:
        """构建DM解析用的动态上下文。"""
        context: Dict[str, Any] = {
            "npc_response_mode": self._npc_response_mode,
            "npc_response_policy": self._describe_npc_mode_policy(),
            "engine_context": self._build_game_context(),
            "action_queue": self._action_queue,
            "current_actor_id": self._current_actor_id,
            "narrative_context": self._get_narrative_context_for_llm(),
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
        """构建NPC推演用的动态上下文，支持queue/reactive双模式。"""
        context: Dict[str, Any] = {
            "engine_context": self._build_game_context(),
            "trigger": trigger,
            "npc_response_mode": self._npc_response_mode,
            "npc_response_policy": self._describe_npc_mode_policy(),
            "action_queue": self._action_queue,
            "current_actor_id": self._current_actor_id,
            "narrative_context": self._get_narrative_context_for_llm(),
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

    def _plan_npc_actions(
        self,
        trigger: str,
        dm_output: Optional[DMAgentOutput] = None,
        candidate_npc_ids: Optional[List[str]] = None,
        player_resolution_anchor: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Use NPCDirector as a unified planning入口，返回{npc_id: plan_dict}。"""
        if not self.npc_director or not hasattr(self.npc_director, "decide_actions"):
            return {}

        npc_ids = candidate_npc_ids or []
        if not npc_ids and dm_output and dm_output.actionable_npcs:
            npc_ids = [npc_id for npc_id in dm_output.actionable_npcs if npc_id in self.game_state.characters]

        if not npc_ids:
            npc_ids = [
                char_id
                for char_id, char in self.game_state.characters.items()
                if not char.is_player and self._can_actor_act(char)
            ]

        if not npc_ids:
            return {}

        recent_events = []
        if hasattr(self.narrative_context, "recent_events"):
            for event in getattr(self.narrative_context, "recent_events", []):
                if hasattr(event, "model_dump"):
                    recent_events.append(event.model_dump())
                elif isinstance(event, dict):
                    recent_events.append(event)

        narrative_context = self._get_narrative_context_for_llm()
        if player_resolution_anchor:
            narrative_context = (
                f"{narrative_context}\n\n"
                "[PlayerResolutionAnchor]\n"
                + json.dumps(player_resolution_anchor, ensure_ascii=False, indent=2)
            ).strip()

        decision = self.npc_director.decide_actions(
            npc_ids=npc_ids,
            game_state=self.game_state,
            player_intent=dm_output,
            trigger_source=trigger,
            recent_events=recent_events,
            narrative_context=narrative_context,
        )

        plans: Dict[str, Any] = {}
        raw_actions = getattr(decision, "actions", {}) if decision else {}
        for npc_id, action in raw_actions.items():
            if hasattr(action, "model_dump"):
                plans[npc_id] = action.model_dump()
            elif isinstance(action, dict):
                plans[npc_id] = action
        return plans

    def _plan_single_npc_action(
        self,
        trigger: str,
        dm_output: Optional[DMAgentOutput],
    ) -> Optional[Dict[str, Any]]:
        """Plan single NPC action with director, falling back to DM fields."""
        preferred_npc_id = dm_output.npc_actor_id if dm_output else None
        candidate_ids: List[str] = []
        if preferred_npc_id:
            candidate_ids.append(preferred_npc_id)
        else:
            default_npc_id = self._pick_default_npc_actor()
            if default_npc_id:
                candidate_ids.append(default_npc_id)

        plans = self._plan_npc_actions(
            trigger=trigger,
            dm_output=dm_output,
            candidate_npc_ids=candidate_ids,
        )

        if preferred_npc_id and preferred_npc_id in plans:
            return plans[preferred_npc_id]
        if plans:
            first_npc_id = next(iter(plans.keys()))
            return plans[first_npc_id]
        return None

    def _extract_npc_action_plan(self, dm_output: DMAgentOutput) -> Optional[Dict[str, Any]]:
        """Get structured NPC action plan from NPCDirector, with DM fallback."""
        plan = self._plan_single_npc_action(trigger="reactive", dm_output=dm_output)
        if plan:
            return plan

        if dm_output.npc_actor_id or dm_output.npc_intent:
            return {
                "npc_id": dm_output.npc_actor_id,
                "intent_description": dm_output.npc_intent or "",
                "trigger_source": "reactive",
            }
        return None

    def _extract_npc_actor_from_plan(self, action_plan: Optional[Dict[str, Any]]) -> Optional[str]:
        """Extract npc actor id from structured plan payload."""
        if not action_plan:
            return None

        if isinstance(action_plan, dict):
            for key in ("npc_id", "actor_id", "character_id"):
                value = action_plan.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    def _describe_npc_mode_policy(self) -> str:
        """返回当前NPC响应模式的策略说明，供Agent动态拼接上下文。"""
        if self._npc_response_mode == "unified":
            return "unified: 玩家主流程先执行，再在同回合内统一处理NPC响应；queue/reactive仅用于触发来源标签。"
        if self._npc_response_mode == "reactive":
            return "reactive: 玩家主流程后仅在DM判定需要响应时触发NPC。"
        return "queue: 玩家主流程后默认触发一次NPC响应，trigger_source标记为queue。"

    def set_npc_response_mode(self, mode: str):
        """设置NPC响应模式：unified(默认) / queue(语义标签) / reactive(语义标签)。"""
        normalized = (mode or "unified").strip().lower()
        if normalized not in {"queue", "reactive", "unified"}:
            logger.warning(f"未知NPC响应模式: {mode}，回退为unified")
            normalized = "unified"
        self._npc_response_mode = normalized

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

    def _flatten_entity_ids(self, raw_ids: Iterable[Any]) -> List[str]:
        """扁平化实体ID列表，忽略非字符串值，避免嵌套list污染后续流程。"""
        result: List[str] = []
        seen = set()
        for value in list(raw_ids or []):
            if isinstance(value, str):
                if value not in seen:
                    seen.add(value)
                    result.append(value)
            elif isinstance(value, list):
                for inner in value:
                    if isinstance(inner, str):
                        if inner not in seen:
                            seen.add(inner)
                            result.append(inner)
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
    ) -> Dict[str, Any]:
        """统一后置NPC流程：玩家行动后处理NPC响应。"""
        if not hasattr(self.state_agent, "evolve_npc_action"):
            return {"game_over": False, "fragments": []}

        should_trigger = self._npc_response_mode in {"queue", "unified"} or dm_output.npc_response_needed
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

        trigger_label = self._npc_response_mode if self._npc_response_mode in {"queue", "reactive"} else "unified"
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
                npc_intent=self._extract_npc_intent_from_plan(plan) or dm_output.npc_intent,
                additional_context=self._build_npc_runtime_context(
                    trigger=trigger_label,
                    player_check=player_check,
                    player_action_description=dm_output.action_description,
                    npc_action_plan=plan,
                    player_resolution_anchor=player_resolution_anchor,
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
