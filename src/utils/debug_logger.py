"""
Debug 系统 - 核心 Logger 类框架

统一调试日志记录器，提供完整的会话、回合、阶段跟踪能力。
严格遵循设计文档 docs/debug_system_design.md 中的规范。
"""

import json
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from src.utils.debug_types import (
    LogLevel,
    EventType,
    LogEntry,
    TurnRecord,
    PhaseRecord,
    StateChangeRecord,
    LLMCallRecord,
    InconsistencyRecord,
    SessionSummary
)
from src.utils.debug_config import DebugConfig, default_config

# 一致性检查器类型（延迟导入避免循环依赖）
ConsistencyChecker = Any


# ============================================================
# DebugLogger 核心类
# ============================================================

class DebugLogger:
    """统一调试日志记录器
    
    负责收集、组织和存储游戏引擎的所有调试信息。
    采用分层结构：Session -> Turn -> Phase -> Events
    
    Attributes:
        session_id: 当前会话ID
        config: Debug 配置
        start_time: 会话开始时间
        session_dir: 会话日志目录
        _current_turn: 当前回合数
        _current_phase: 当前阶段名称
        _turn_records: 所有回合记录
        _phase_stack: 阶段栈（支持嵌套阶段）
        _session_summary: 会话摘要
    
    Example:
        >>> logger = DebugLogger(session_id="abc123")
        >>> logger.start_turn("查看背包")
        >>> logger.start_phase("parse_input")
        >>> # ... 执行解析逻辑 ...
        >>> logger.end_phase({"parsed": "inventory_command"})
        >>> logger.end_turn("你查看了背包...")
        >>> logger.end_session()
    """
    
    def __init__(
        self,
        session_id: Optional[str] = None,
        config: Optional[DebugConfig] = None,
        world_name: str = "",
        player_id: str = ""
    ):
        """初始化 Debug Logger
        
        Args:
            session_id: 会话ID（如果未提供则自动生成）
            config: Debug 配置（使用默认配置如果未提供）
            world_name: 世界名称
            player_id: 玩家角色ID
        """
        self.config = config or default_config
        self.session_id = session_id or self._generate_session_id()
        self.start_time = datetime.now()
        self.world_name = world_name
        self.player_id = player_id
        
        # 初始化目录结构
        self._init_directory_structure()
        
        # 初始化日志处理器
        self._init_handlers()
        
        # 当前状态
        self._current_turn: int = 0
        self._current_phase: Optional[str] = None
        self._phase_start_time: Optional[datetime] = None
        self._turn_records: List[TurnRecord] = []
        self._current_turn_record: Optional[TurnRecord] = None
        self._current_phase_record: Optional[PhaseRecord] = None
        
        # 一致性检查器（可选）
        self._consistency_checker: Optional[Any] = None
        
        # 统计信息
        self._session_summary = SessionSummary(
            session_id=self.session_id,
            world=world_name,
            player_id=player_id,
            start_time=self.start_time
        )
        
        # 写入会话开始标记
        self._log_session_start()
    
    def enable_consistency_checking(self, io_system: Any) -> None:
        """启用一致性检查
        
        Args:
            io_system: IO 系统实例
        """
        try:
            from src.utils.debug_consistency import ConsistencyChecker
            self._consistency_checker = ConsistencyChecker(io_system, self)
        except ImportError:
            self._log_event(
                EventType.WARNING_ISSUED,
                {"message": "Failed to import ConsistencyChecker, consistency checking disabled"},
                level=LogLevel.WARNING
            )
    
    def _generate_session_id(self) -> str:
        """生成唯一的会话ID
        
        格式: YYYYMMDD_HHMMSS_随机码
        
        Returns:
            会话ID字符串
        """
        timestamp = datetime.now().strftime(self.config.session_id_format)
        random_suffix = secrets.token_hex(4)  # 8位十六进制随机码
        return f"{timestamp}_{random_suffix}"
    
    def _init_directory_structure(self) -> None:
        """初始化日志目录结构"""
        base_dir = Path(self.config.log_dir)
        
        # 会话目录
        self.session_dir = base_dir / "sessions" / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        
        # Turns 子目录
        self.turns_dir = self.session_dir / "turns"
        self.turns_dir.mkdir(exist_ok=True)
        
        # 分类日志目录
        if self.config.should_output_categorized():
            self.categorized_dir = base_dir / "categorized"
            self.categorized_dir.mkdir(parents=True, exist_ok=True)
    
    def _init_handlers(self) -> None:
        """初始化日志处理器
        
        根据配置初始化各类日志处理器。
        """
        # 主日志文件路径
        self.master_log_path = self.session_dir / "master.log"
        
        # 结构化时间线文件路径
        self.timeline_path = self.session_dir / "timeline.json"
        
        # 分类日志文件路径
        if self.config.should_output_categorized():
            self.events_log_path = self.categorized_dir / "events.log"
            self.state_log_path = self.categorized_dir / "state_changes.log"
            self.llm_log_path = self.categorized_dir / "llm_interactions.log"
            self.error_log_path = self.categorized_dir / "errors.log"
            self.performance_log_path = self.categorized_dir / "performance.log"
        
        # 当前 turn 目录（在 start_turn 时设置）
        self._current_turn_dir: Optional[Path] = None
    
    def _log_session_start(self) -> None:
        """记录会话开始标记"""
        if not self.config.should_output_master_log():
            return
            
        header = f"""
{'='*67}
🎮 SESSION START: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')} | SessionID: {self.session_id}
World: {self.world_name or 'N/A'} | Player: {self.player_id or 'N/A'}
{'='*67}
"""
        self._write_to_master_log(header)
    
    def _write_to_master_log(self, content: str) -> None:
        """写入主日志文件
        
        Args:
            content: 要写入的内容
        """
        if not self.config.should_output_master_log():
            return
            
        with open(self.master_log_path, "a", encoding="utf-8") as f:
            f.write(content + "\n")
    
    def _log_event(
        self,
        event_type: EventType,
        data: Dict[str, Any],
        level: LogLevel = LogLevel.INFO
    ) -> None:
        """记录通用事件
        
        Args:
            event_type: 事件类型
            data: 事件数据
            level: 日志级别
        """
        if not self.config.is_level_enabled(level):
            return
        
        entry = LogEntry(
            type=event_type,
            timestamp=datetime.now(),
            level=level,
            turn=self._current_turn,
            phase=self._current_phase,
            data=data
        )
        
        # 写入主日志
        self._write_entry_to_master_log(entry)
        
        # 写入分类日志
        self._write_to_categorized_log(entry)
    
    def _write_entry_to_master_log(self, entry: LogEntry) -> None:
        """将日志条目写入主日志"""
        if not self.config.should_output_master_log():
            return
        
        timestamp = entry.timestamp.strftime("%H:%M:%S.%f")[:-3]
        turn_info = f"T{entry.turn:03d}" if entry.turn else "INIT"
        phase_info = f"[{entry.phase}]" if entry.phase else ""
        
        line = f"[{timestamp}] [{turn_info}] {phase_info} {entry.type.value}: {entry.data}"
        self._write_to_master_log(line)
    
    def _write_to_categorized_log(self, entry: LogEntry) -> None:
        """写入分类日志"""
        if not self.config.should_output_categorized():
            return
        
        # 根据事件类型选择日志文件
        log_file = None
        if entry.type in (EventType.ERROR_OCCURRED, EventType.STATE_INCONSISTENCY):
            log_file = self.error_log_path
        elif entry.type in (EventType.LLM_REQUEST, EventType.LLM_RESPONSE, EventType.LLM_RETRY, EventType.LLM_ERROR):
            log_file = self.llm_log_path
        elif entry.type in (EventType.STATE_CHANGE_PROPOSED, EventType.STATE_CHANGE_VALIDATED, 
                           EventType.STATE_CHANGE_APPLIED, EventType.STATE_CHANGE_FAILED, EventType.STATE_SNAPSHOT):
            log_file = self.state_log_path
        elif entry.type == EventType.PERFORMANCE_METRIC:
            log_file = self.performance_log_path
        else:
            log_file = self.events_log_path
        
        if log_file:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
    
    # ========================================================
    # 回合生命周期方法
    # ========================================================
    
    def start_turn(self, player_input: str) -> int:
        """开始新回合
        
        Args:
            player_input: 玩家输入文本
            
        Returns:
            新回合的编号
        """
        self._current_turn += 1
        self._current_turn_record = TurnRecord(
            turn_number=self._current_turn,
            player_input=player_input
        )
        
        # 创建 turn 目录
        self._current_turn_dir = self.turns_dir / f"turn_{self._current_turn:03d}"
        self._current_turn_dir.mkdir(exist_ok=True)
        
        # 记录事件
        self._log_event(
            EventType.TURN_START,
            {"player_input": player_input}
        )
        
        # 写入主日志标题
        if self.config.should_output_master_log():
            header = f"""
{'─'*67}
📝 TURN {self._current_turn:03d} | {datetime.now().strftime('%H:%M:%S')} | Input: "{player_input}"
{'─'*67}"""
            self._write_to_master_log(header)
        
        return self._current_turn
    
    def end_turn(self, narrative_output: str) -> None:
        """结束当前回合
        
        Args:
            narrative_output: 叙事输出文本
        """
        if self._current_turn_record:
            self._current_turn_record.finalize(narrative_output)
            self._turn_records.append(self._current_turn_record)
            
            # 更新统计
            self._session_summary.total_turns = self._current_turn
        
        # 记录事件
        self._log_event(
            EventType.TURN_END,
            {"narrative_length": len(narrative_output)}
        )
        
        # 写入主日志
        if self.config.should_output_master_log():
            duration = self._current_turn_record.duration_ms if self._current_turn_record else 0
            footer = f"""  ✅ TURN {self._current_turn:03d} COMPLETE | Duration: {duration:.0f}ms | Narrative: {len(narrative_output)} chars
{'─'*67}"""
            self._write_to_master_log(footer)
        
        # 保存 timeline
        self._save_timeline()
        
        # 重置当前 turn 状态
        self._current_turn_record = None
        self._current_turn_dir = None
    
    # ========================================================
    # 阶段生命周期方法
    # ========================================================
    
    def start_phase(self, phase_name: str) -> None:
        """开始新阶段
        
        Args:
            phase_name: 阶段名称
        """
        self._current_phase = phase_name
        self._phase_start_time = datetime.now()
        self._current_phase_record = PhaseRecord(name=phase_name)
        
        # 记录事件
        self._log_event(
            EventType.TURN_PHASE_START,
            {"phase": phase_name}
        )
        
        # 写入主日志
        if self.config.should_output_master_log():
            timestamp = self._phase_start_time.strftime("%H:%M:%S.%f")[:-3]
            line = f"  [{timestamp}] ▶️ PHASE: {phase_name}"
            self._write_to_master_log(line)
    
    def end_phase(self, result: Optional[Dict[str, Any]] = None) -> None:
        """结束当前阶段
        
        Args:
            result: 阶段结果数据（可选）
        """
        if self._current_phase_record:
            self._current_phase_record.finalize(result)
            
            if self._current_turn_record:
                self._current_turn_record.add_phase(self._current_phase_record)
        
        duration_ms = self._current_phase_record.duration_ms if self._current_phase_record else 0
        
        # 记录事件
        self._log_event(
            EventType.TURN_PHASE_END,
            {"phase": self._current_phase, "duration_ms": duration_ms, "result": result}
        )
        
        # 写入主日志
        if self.config.should_output_master_log():
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            line = f"  [{timestamp}] ✅ PHASE END: {self._current_phase} | Duration: {duration_ms:.0f}ms"
            self._write_to_master_log(line)
        
        # 重置阶段状态
        self._current_phase = None
        self._phase_start_time = None
        self._current_phase_record = None
    
    # ========================================================
    # LLM 交互日志方法
    # ========================================================
    
    def log_llm_request(
        self,
        agent: str,
        prompt: str,
        model: str,
        tokens: int = 0
    ) -> Path:
        """记录 LLM 请求
        
        Args:
            agent: Agent 名称
            prompt: 完整的 prompt 文本
            model: 使用的模型名称
            tokens: prompt token 数
            
        Returns:
            prompt 保存的文件路径
        """
        # 保存完整 prompt 到文件
        prompt_file = self._current_turn_dir / f"llm_{agent}_request.txt"
        prompt_file.write_text(prompt, encoding="utf-8")
        
        # 记录事件
        self._log_event(
            EventType.LLM_REQUEST,
            {
                "agent": agent,
                "model": model,
                "tokens": tokens,
                "prompt_file": str(prompt_file)
            }
        )
        
        # 写入主日志
        if self.config.should_output_master_log():
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            line = f"    [{timestamp}] 📤 LLM REQUEST [{agent}] | Prompt: {tokens} tokens | Model: {model}"
            self._write_to_master_log(line)
        
        # 更新统计
        self._session_summary.total_llm_calls += 1
        
        return prompt_file
    
    def log_llm_response(
        self,
        agent: str,
        response: str,
        duration_ms: float,
        tokens: int = 0
    ) -> Path:
        """记录 LLM 响应
        
        Args:
            agent: Agent 名称
            response: 完整的响应文本
            duration_ms: 响应耗时（毫秒）
            tokens: response token 数
            
        Returns:
            response 保存的文件路径
        """
        # 保存完整 response 到文件
        response_file = self._current_turn_dir / f"llm_{agent}_response.txt"
        response_file.write_text(response, encoding="utf-8")
        
        # 记录事件
        self._log_event(
            EventType.LLM_RESPONSE,
            {
                "agent": agent,
                "duration_ms": duration_ms,
                "tokens": tokens,
                "response_file": str(response_file)
            }
        )
        
        # 写入主日志
        if self.config.should_output_master_log():
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            line = f"    [{timestamp}] 📥 LLM RESPONSE [{agent}] | Duration: {duration_ms:.0f}ms | Tokens: {tokens}"
            self._write_to_master_log(line)
        
        # 添加到当前 phase 记录
        if self._current_phase_record:
            self._current_phase_record.llm_calls.append({
                "agent": agent,
                "duration_ms": duration_ms,
                "tokens": tokens
            })
        
        return response_file
    
    def log_llm_retry(
        self,
        agent: str,
        attempt: int,
        error: str
    ) -> None:
        """记录 LLM 重试
        
        Args:
            agent: Agent 名称
            attempt: 重试次数
            error: 错误信息
        """
        self._log_event(
            EventType.LLM_RETRY,
            {"agent": agent, "attempt": attempt, "error": error},
            level=LogLevel.WARNING
        )
        
        self._session_summary.total_warnings += 1
    
    def log_llm_error(
        self,
        agent: str,
        error: str,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """记录 LLM 错误
        
        Args:
            agent: Agent 名称
            error: 错误信息
            context: 错误上下文
        """
        self._log_event(
            EventType.LLM_ERROR,
            {"agent": agent, "error": error, "context": context},
            level=LogLevel.ERROR
        )
        
        self._session_summary.total_errors += 1
    
    # ========================================================
    # 状态变更日志方法
    # ========================================================
    
    def log_state_snapshot(
        self,
        game_state: Any,
        label: str
    ) -> Path:
        """记录状态快照
        
        Args:
            game_state: 游戏状态对象
            label: 快照标签（如 "before", "after"）
            
        Returns:
            快照保存的文件路径
        """
        # 序列化状态
        snapshot = self._serialize_game_state(game_state)
        
        # 保存到文件
        snapshot_file = self._current_turn_dir / f"state_{label}.json"
        snapshot_file.write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        # 记录事件
        self._log_event(
            EventType.STATE_SNAPSHOT,
            {"label": label, "file": str(snapshot_file)}
        )
        
        return snapshot_file
    
    def log_state_changes_proposed(
        self,
        changes: List[Any],
        validation_result: Optional[Any] = None
    ) -> None:
        """记录状态变更提案
        
        Args:
            changes: 状态变更列表
            validation_result: 验证结果（可选）
        """
        records = [self._serialize_change(c) for c in changes]
        
        event_data: Dict[str, Any] = {
            "changes": records,
            "count": len(changes)
        }
        
        if validation_result:
            event_data["validation"] = self._serialize_validation_result(validation_result)
        
        self._log_event(
            EventType.STATE_CHANGE_PROPOSED,
            event_data
        )
        
        # 写入主日志
        if self.config.should_output_master_log():
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            lines = [f"    [{timestamp}] 📝 STATE CHANGES PROPOSED | Count: {len(changes)}"]
            for record in records:
                lines.append(f"      ├─ {record['entity_id']}.{record['field']}: {record['old_value']} → {record['new_value']}")
            self._write_to_master_log("\n".join(lines))
    
    def log_state_change_applied(
        self,
        change: Any,
        error_code: int = 0,
        cascading_effects: Optional[List[Dict[str, Any]]] = None,
        game_state: Optional[Any] = None
    ) -> None:
        """记录状态变更应用结果
        
        Args:
            change: 状态变更对象
            error_code: 应用结果错误码（0表示成功）
            cascading_effects: 级联影响列表
            game_state: 当前游戏状态（用于一致性检查，可选）
        """
        record = self._serialize_change(change)
        record["error_code"] = error_code
        record["cascading_effects"] = cascading_effects or []
        
        event_type = EventType.STATE_CHANGE_APPLIED if error_code == 0 else EventType.STATE_CHANGE_FAILED
        
        self._log_event(
            event_type,
            record,
            level=LogLevel.INFO if error_code == 0 else LogLevel.ERROR
        )
        
        if error_code == 0:
            self._session_summary.state_changes_count += 1
        else:
            self._session_summary.total_errors += 1
        
        # 写入主日志
        if self.config.should_output_master_log():
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            status = "✓" if error_code == 0 else "✗"
            line = f"    [{timestamp}] {status} {record['entity_id']}.{record['field']}"
            if cascading_effects:
                for effect in cascading_effects:
                    line += f"\n      ⚠️  Cascading: {effect}"
            self._write_to_master_log(line)
        
        # 一致性检查：变更成功且提供了 game_state 时自动检查
        if error_code == 0 and game_state is not None and self._consistency_checker is not None:
            try:
                entity_id = record.get("entity_id", "")
                field = record.get("field", "")
                if entity_id and field:
                    self._consistency_checker.check_after_change(entity_id, field, game_state)
            except Exception:
                # 一致性检查失败不应影响主流程
                pass
    
    def log_inconsistency(
        self,
        trigger_change: str,
        differences: List[Dict[str, Any]]
    ) -> None:
        """记录状态不一致
        
        Args:
            trigger_change: 触发检查的变更
            differences: 差异列表
        """
        self._log_event(
            EventType.STATE_INCONSISTENCY,
            {
                "trigger_change": trigger_change,
                "differences": differences
            },
            level=LogLevel.WARNING
        )
        
        self._session_summary.inconsistencies_found += 1
        self._session_summary.total_warnings += 1
        
        # 写入主日志
        if self.config.should_output_master_log():
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            lines = [f"    [{timestamp}] ⚠️  INCONSISTENCY DETECTED | Trigger: {trigger_change}"]
            for diff in differences:
                lines.append(f"      - {diff.get('field', 'unknown')}: memory={diff.get('memory_value', '?')}, io={diff.get('io_value', '?')}")
            self._write_to_master_log("\n".join(lines))
    
    # ========================================================
    # 会话结束方法
    # ========================================================
    
    def end_session(self, game_state: Optional[Any] = None) -> SessionSummary:
        """结束会话
        
        Args:
            game_state: 最终游戏状态（可选）
            
        Returns:
            会话摘要
        """
        end_time = datetime.now()
        self._session_summary.end_time = end_time
        self._session_summary.finalize()
        
        # 记录最终状态快照
        if game_state and self.config.should_output_snapshots():
            self.log_state_snapshot(game_state, "final")
        
        # 保存结构化时间线
        self._save_timeline(final=True)
        
        # 写入会话结束标记
        if self.config.should_output_master_log():
            footer = f"""
{'='*67}
🔚 SESSION END: {end_time.strftime('%Y-%m-%d %H:%M:%S')} | Duration: {self._session_summary.duration_seconds:.0f}s
Total Turns: {self._session_summary.total_turns} | LLM Calls: {self._session_summary.total_llm_calls} | Errors: {self._session_summary.total_errors}
{'='*67}
"""
            self._write_to_master_log(footer)
        
        return self._session_summary
    
    # ========================================================
    # 辅助方法
    # ========================================================
    
    def _serialize_game_state(self, game_state: Any) -> Dict[str, Any]:
        """序列化游戏状态
        
        Args:
            game_state: 游戏状态对象
            
        Returns:
            序列化后的字典
        """
        # 如果游戏状态有 to_dict 方法，使用它
        if hasattr(game_state, "to_dict"):
            return game_state.to_dict()
        
        # 否则使用 vars 或 dict
        if hasattr(game_state, "__dict__"):
            return vars(game_state)
        
        return {"state": str(game_state)}
    
    def _serialize_change(self, change: Any) -> Dict[str, Any]:
        """序列化状态变更
        
        Args:
            change: 状态变更对象
            
        Returns:
            序列化后的字典
        """
        if hasattr(change, "to_dict"):
            return change.to_dict()
        
        if hasattr(change, "__dict__"):
            return vars(change)
        
        return {"change": str(change)}
    
    def _serialize_validation_result(self, result: Any) -> Dict[str, Any]:
        """序列化验证结果
        
        Args:
            result: 验证结果对象
            
        Returns:
            序列化后的字典
        """
        if hasattr(result, "to_dict"):
            return result.to_dict()
        
        if hasattr(result, "__dict__"):
            return vars(result)
        
        return {"valid": bool(result), "result": str(result)}
    
    def _save_timeline(self, final: bool = False) -> None:
        """保存结构化时间线
        
        Args:
            final: 是否为最终保存
        """
        if not self.config.should_output_timeline():
            return
        
        timeline = {
            "session_id": self.session_id,
            "world": self.world_name,
            "player_id": self.player_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self._session_summary.end_time.isoformat() if self._session_summary.end_time else None,
            "summary": {
                "total_turns": self._session_summary.total_turns,
                "total_llm_calls": self._session_summary.total_llm_calls,
                "total_errors": self._session_summary.total_errors,
                "total_warnings": self._session_summary.total_warnings,
                "state_changes_count": self._session_summary.state_changes_count,
                "inconsistencies_found": self._session_summary.inconsistencies_found
            },
            "turns": [t.to_dict() for t in self._turn_records]
        }
        
        # 如果当前回合未完成，也包含进去
        if self._current_turn_record:
            timeline["turns"].append(self._current_turn_record.to_dict())
        
        self.timeline_path.write_text(
            json.dumps(timeline, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    
    def get_summary(self) -> SessionSummary:
        """获取当前会话摘要
        
        Returns:
            会话摘要对象
        """
        return self._session_summary
    
    def get_current_turn(self) -> int:
        """获取当前回合数
        
        Returns:
            当前回合编号
        """
        return self._current_turn
    
    def get_current_phase(self) -> Optional[str]:
        """获取当前阶段名称
        
        Returns:
            当前阶段名称，如果没有则返回 None
        """
        return self._current_phase
