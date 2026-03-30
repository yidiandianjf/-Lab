"""
Debug 系统 - 核心类型定义

定义所有类型常量、枚举和数据类，用于 Debug 日志系统的类型安全。
严格遵循设计文档 docs/debug_system_design.md 中的规范。
"""

from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field


# ============================================================
# 日志级别枚举
# ============================================================

class LogLevel(str, Enum):
    """日志级别定义
    
    按严重程度从低到高排列：
    - DEBUG: 详细调试信息
    - INFO: 一般信息
    - NOTICE: 重要但不紧急（如状态变更）
    - WARNING: 警告
    - ERROR: 错误
    - CRITICAL: 严重错误
    """
    DEBUG = "debug"
    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# ============================================================
# 事件类型枚举
# ============================================================

class EventType(str, Enum):
    """事件类型定义
    
    涵盖游戏引擎中所有需要监控的关键事件点。
    """
    # 输入相关
    PLAYER_INPUT = "player_input"
    COMMAND_PARSED = "command_parsed"
    
    # Turn 流程
    TURN_START = "turn_start"
    TURN_PHASE_START = "turn_phase_start"
    TURN_PHASE_END = "turn_phase_end"
    TURN_END = "turn_end"
    
    # LLM 交互
    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"
    LLM_RETRY = "llm_retry"
    LLM_ERROR = "llm_error"
    
    # 状态变更
    STATE_CHANGE_PROPOSED = "state_change_proposed"
    STATE_CHANGE_VALIDATED = "state_change_validated"
    STATE_CHANGE_APPLIED = "state_change_applied"
    STATE_CHANGE_FAILED = "state_change_failed"
    STATE_SNAPSHOT = "state_snapshot"
    
    # 检定
    CHECK_TRIGGERED = "check_triggered"
    CHECK_RESOLVED = "check_resolved"
    
    # NPC
    NPC_PLAN_GENERATED = "npc_plan_generated"
    NPC_ACTION_EXECUTED = "npc_action_executed"
    
    # 系统
    ERROR_OCCURRED = "error_occurred"
    WARNING_ISSUED = "warning_issued"
    PERFORMANCE_METRIC = "performance_metric"
    
    # 一致性检查
    STATE_INCONSISTENCY = "state_inconsistency"


# ============================================================
# 阶段名称枚举
# ============================================================

class PhaseName(str, Enum):
    """Turn 阶段名称定义"""
    PARSE_INPUT = "parse_input"
    DM_PROCESSING = "dm_processing"
    STATE_EVOLUTION = "state_evolution"
    APPLY_CHANGES = "apply_changes"
    NPC_RESPONSE = "npc_response"
    NARRATIVE_GENERATION = "narrative_generation"


# ============================================================
# 数据类定义
# ============================================================

@dataclass
class LogEntry:
    """日志条目数据类
    
    表示一条完整的日志记录，包含事件类型、时间戳、级别和详细数据。
    
    Attributes:
        type: 事件类型
        timestamp: 记录时间戳
        level: 日志级别
        turn: 当前回合数（可选）
        phase: 当前阶段（可选）
        data: 附加数据字典
    """
    type: EventType
    timestamp: datetime
    level: LogLevel = LogLevel.INFO
    turn: Optional[int] = None
    phase: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "type": self.type.value,
            "timestamp": self.timestamp.isoformat(),
            "level": self.level.value,
            "turn": self.turn,
            "phase": self.phase,
            "data": self.data
        }


@dataclass
class StateChangeRecord:
    """状态变更记录数据类
    
    记录单个状态变更的完整信息，包括变更前后的值和验证结果。
    
    Attributes:
        entity_id: 实体ID（如 item-book-01）
        entity_type: 实体类型（character/item/location等）
        field: 变更字段名
        old_value: 变更前的值
        new_value: 变更后的值
        validated: 是否通过验证
        error_code: 应用结果错误码（0表示成功）
        error_message: 错误信息（如果有）
        cascading_effects: 级联影响列表
        timestamp: 变更时间戳
    """
    entity_id: str
    entity_type: str
    field: str
    old_value: Any
    new_value: Any
    validated: bool = False
    error_code: int = 0
    error_message: Optional[str] = None
    cascading_effects: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "field": self.field,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "validated": self.validated,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "cascading_effects": self.cascading_effects,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class PhaseRecord:
    """阶段记录数据类
    
    记录一个阶段的开始、结束和相关信息。
    
    Attributes:
        name: 阶段名称
        start_time: 开始时间
        end_time: 结束时间（可选）
        duration_ms: 持续时间毫秒（可选）
        result: 阶段结果数据
        llm_calls: 阶段中发生的LLM调用列表
        state_changes: 阶段中发生的状态变更列表
    """
    name: str
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None
    result: Dict[str, Any] = field(default_factory=dict)
    llm_calls: List[Dict[str, Any]] = field(default_factory=list)
    state_changes: List[StateChangeRecord] = field(default_factory=list)
    
    def finalize(self, result: Optional[Dict[str, Any]] = None) -> None:
        """结束阶段并计算持续时间"""
        self.end_time = datetime.now()
        if result:
            self.result.update(result)
        if self.start_time:
            delta = self.end_time - self.start_time
            self.duration_ms = delta.total_seconds() * 1000
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "name": self.name,
            "start": self.start_time.isoformat() if self.start_time else None,
            "end": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "result": self.result,
            "llm_calls": self.llm_calls,
            "state_changes": [sc.to_dict() for sc in self.state_changes]
        }


@dataclass
class TurnRecord:
    """回合记录数据类
    
    记录一个完整回合的所有信息。
    
    Attributes:
        turn_number: 回合编号
        timestamp: 回合开始时间
        player_input: 玩家输入
        phases: 阶段列表
        narrative_output: 叙事输出
        issues: 本回合发现的问题列表
        duration_ms: 总持续时间
    """
    turn_number: int
    timestamp: datetime = field(default_factory=datetime.now)
    player_input: str = ""
    phases: List[PhaseRecord] = field(default_factory=list)
    narrative_output: str = ""
    issues: List[Dict[str, Any]] = field(default_factory=list)
    duration_ms: Optional[float] = None
    
    def add_phase(self, phase: PhaseRecord) -> None:
        """添加阶段记录"""
        self.phases.append(phase)
    
    def add_issue(self, issue_type: str, severity: str, description: str) -> None:
        """添加问题记录"""
        self.issues.append({
            "type": issue_type,
            "severity": severity,
            "description": description,
            "timestamp": datetime.now().isoformat()
        })
    
    def finalize(self, narrative: str) -> None:
        """结束回合"""
        self.narrative_output = narrative
        if self.phases:
            self.duration_ms = sum(
                p.duration_ms for p in self.phases if p.duration_ms is not None
            )
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "turn_number": self.turn_number,
            "timestamp": self.timestamp.isoformat(),
            "input": self.player_input,
            "phases": [p.to_dict() for p in self.phases],
            "narrative": self.narrative_output,
            "issues": self.issues,
            "duration_ms": self.duration_ms
        }


@dataclass
class LLMCallRecord:
    """LLM 调用记录数据类
    
    记录一次LLM调用的完整信息。
    
    Attributes:
        agent: 调用的Agent名称
        model: 使用的模型
        request_tokens: 请求token数
        response_tokens: 响应token数
        duration_ms: 调用持续时间
        prompt_file: prompt保存文件路径
        response_file: response保存文件路径
        retry_count: 重试次数
        error: 错误信息（如果有）
    """
    agent: str
    model: str
    request_tokens: int = 0
    response_tokens: int = 0
    duration_ms: float = 0.0
    prompt_file: Optional[str] = None
    response_file: Optional[str] = None
    retry_count: int = 0
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "agent": self.agent,
            "model": self.model,
            "request_tokens": self.request_tokens,
            "response_tokens": self.response_tokens,
            "duration_ms": self.duration_ms,
            "prompt_file": self.prompt_file,
            "response_file": self.response_file,
            "retry_count": self.retry_count,
            "error": self.error
        }


@dataclass
class InconsistencyRecord:
    """不一致记录数据类
    
    记录内存与IO层之间检测到的不一致。
    
    Attributes:
        trigger_change: 触发检查的变更
        entity_id: 实体ID
        field: 不一致的字段
        memory_value: 内存中的值
        io_value: IO层中的值
        detected_at: 检测时间
        severity: 严重程度
    """
    trigger_change: str
    entity_id: str
    field: str
    memory_value: Any
    io_value: Any
    detected_at: datetime = field(default_factory=datetime.now)
    severity: str = "warning"  # warning, error, critical
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "trigger_change": self.trigger_change,
            "entity_id": self.entity_id,
            "field": self.field,
            "memory_value": self.memory_value,
            "io_value": self.io_value,
            "detected_at": self.detected_at.isoformat(),
            "severity": self.severity
        }


@dataclass
class SessionSummary:
    """会话摘要数据类
    
    记录整个游戏会话的统计和摘要信息。
    
    Attributes:
        session_id: 会话ID
        world: 世界名称
        player_id: 玩家角色ID
        start_time: 会话开始时间
        end_time: 会话结束时间
        duration_seconds: 总持续时间（秒）
        total_turns: 总回合数
        total_llm_calls: 总LLM调用次数
        total_errors: 总错误数
        total_warnings: 总警告数
        state_changes_count: 状态变更总数
        inconsistencies_found: 发现的不一致数
        issues: 会话中发现的所有问题
    """
    session_id: str
    world: str = ""
    player_id: str = ""
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_seconds: float = 0.0
    total_turns: int = 0
    total_llm_calls: int = 0
    total_errors: int = 0
    total_warnings: int = 0
    state_changes_count: int = 0
    inconsistencies_found: int = 0
    issues: List[Dict[str, Any]] = field(default_factory=list)
    
    def finalize(self) -> None:
        """计算会话统计信息"""
        if self.start_time and self.end_time:
            delta = self.end_time - self.start_time
            self.duration_seconds = delta.total_seconds()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "session_id": self.session_id,
            "world": self.world,
            "player_id": self.player_id,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "summary": {
                "total_turns": self.total_turns,
                "total_llm_calls": self.total_llm_calls,
                "total_errors": self.total_errors,
                "total_warnings": self.total_warnings,
                "state_changes_count": self.state_changes_count,
                "inconsistencies_found": self.inconsistencies_found
            },
            "issues": self.issues
        }


# ============================================================
# 配置相关类型
# ============================================================

@dataclass
class OutputConfig:
    """输出控制配置"""
    master_log: bool = True
    timeline_json: bool = True
    categorized: bool = True
    snapshots: bool = True
    llm_prompts: bool = True


@dataclass
class PerformanceConfig:
    """性能跟踪配置"""
    track_llm_latency: bool = True
    track_phase_duration: bool = True
    track_memory_usage: bool = False


@dataclass
class ConsistencyConfig:
    """一致性检查配置"""
    check_after_each_change: bool = True
    check_after_turn: bool = True
    warn_on_inconsistency: bool = True


@dataclass
class RetentionConfig:
    """日志保留策略配置"""
    keep_sessions: int = 30
    archive_after_days: int = 7


# ============================================================
# 类型别名
# ============================================================

# 日志数据字典类型
LogData = Dict[str, Any]

# 序列化后的状态快照类型
StateSnapshot = Dict[str, Any]

# 验证结果类型
ValidationResultDict = Dict[str, Union[bool, List[str], Optional[str]]]
