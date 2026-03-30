"""
Debug 系统 - 配置系统

支持从 YAML 文件或字典加载配置，包含输出控制、性能跟踪、一致性检查等配置项。
严格遵循设计文档 docs/debug_system_design.md 中的规范。
"""

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, Optional, Union
import os

from src.utils.debug_types import (
    LogLevel,
    OutputConfig,
    PerformanceConfig,
    ConsistencyConfig,
    RetentionConfig
)


# ============================================================
# 默认配置常量
# ============================================================

DEFAULT_LOG_DIR = "logs"
DEFAULT_LOG_LEVEL = LogLevel.DEBUG
DEFAULT_CONFIG_FILE = "debug_config.yaml"

DEFAULT_OUTPUT_CONFIG = OutputConfig(
    master_log=True,
    timeline_json=True,
    categorized=True,
    snapshots=True,
    llm_prompts=True
)

DEFAULT_PERFORMANCE_CONFIG = PerformanceConfig(
    track_llm_latency=True,
    track_phase_duration=True,
    track_memory_usage=False
)

DEFAULT_CONSISTENCY_CONFIG = ConsistencyConfig(
    check_after_each_change=True,
    check_after_turn=True,
    warn_on_inconsistency=True
)

DEFAULT_RETENTION_CONFIG = RetentionConfig(
    keep_sessions=30,
    archive_after_days=7
)


# ============================================================
# DebugConfig 类
# ============================================================

@dataclass
class DebugConfig:
    """Debug 系统配置类
    
    统一管理 Debug 系统的所有配置项，支持从 YAML/字典加载。
    
    Attributes:
        enabled: 是否启用调试系统
        log_level: 日志级别
        log_dir: 日志根目录
        outputs: 输出控制配置
        performance: 性能跟踪配置
        consistency: 一致性检查配置
        retention: 日志保留策略配置
        session_id_format: 会话ID格式模板
    
    Example:
        >>> config = DebugConfig.from_yaml("debug_config.yaml")
        >>> print(config.log_level)
        LogLevel.DEBUG
        >>> 
        >>> # 从字典创建
        >>> config_dict = {"enabled": True, "log_level": "info"}
        >>> config = DebugConfig.from_dict(config_dict)
    """
    
    enabled: bool = True
    log_level: LogLevel = DEFAULT_LOG_LEVEL
    log_dir: str = DEFAULT_LOG_DIR
    outputs: OutputConfig = field(default_factory=lambda: DEFAULT_OUTPUT_CONFIG)
    performance: PerformanceConfig = field(default_factory=lambda: DEFAULT_PERFORMANCE_CONFIG)
    consistency: ConsistencyConfig = field(default_factory=lambda: DEFAULT_CONSISTENCY_CONFIG)
    retention: RetentionConfig = field(default_factory=lambda: DEFAULT_RETENTION_CONFIG)
    session_id_format: str = "%Y%m%d_%H%M%S"
    
    def __post_init__(self) -> None:
        """初始化后处理"""
        # 确保 log_level 是 LogLevel 枚举
        if isinstance(self.log_level, str):
            self.log_level = LogLevel(self.log_level.lower())
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "DebugConfig":
        """从字典加载配置
        
        Args:
            config_dict: 配置字典
            
        Returns:
            DebugConfig 实例
            
        Example:
            >>> config_dict = {
            ...     "enabled": True,
            ...     "log_level": "debug",
            ...     "log_dir": "logs",
            ...     "outputs": {
            ...         "master_log": True,
            ...         "timeline_json": True
            ...     }
            ... }
            >>> config = DebugConfig.from_dict(config_dict)
        """
        # 提取各个子配置
        outputs_dict = config_dict.get("outputs", {})
        performance_dict = config_dict.get("performance", {})
        consistency_dict = config_dict.get("consistency", {})
        retention_dict = config_dict.get("retention", {})
        
        # 解析 log_level
        log_level_str = config_dict.get("log_level", "debug")
        log_level = LogLevel(log_level_str.lower()) if isinstance(log_level_str, str) else log_level_str
        
        return cls(
            enabled=config_dict.get("enabled", True),
            log_level=log_level,
            log_dir=config_dict.get("log_dir", DEFAULT_LOG_DIR),
            outputs=OutputConfig(
                master_log=outputs_dict.get("master_log", DEFAULT_OUTPUT_CONFIG.master_log),
                timeline_json=outputs_dict.get("timeline_json", DEFAULT_OUTPUT_CONFIG.timeline_json),
                categorized=outputs_dict.get("categorized", DEFAULT_OUTPUT_CONFIG.categorized),
                snapshots=outputs_dict.get("snapshots", DEFAULT_OUTPUT_CONFIG.snapshots),
                llm_prompts=outputs_dict.get("llm_prompts", DEFAULT_OUTPUT_CONFIG.llm_prompts)
            ),
            performance=PerformanceConfig(
                track_llm_latency=performance_dict.get("track_llm_latency", DEFAULT_PERFORMANCE_CONFIG.track_llm_latency),
                track_phase_duration=performance_dict.get("track_phase_duration", DEFAULT_PERFORMANCE_CONFIG.track_phase_duration),
                track_memory_usage=performance_dict.get("track_memory_usage", DEFAULT_PERFORMANCE_CONFIG.track_memory_usage)
            ),
            consistency=ConsistencyConfig(
                check_after_each_change=consistency_dict.get("check_after_each_change", DEFAULT_CONSISTENCY_CONFIG.check_after_each_change),
                check_after_turn=consistency_dict.get("check_after_turn", DEFAULT_CONSISTENCY_CONFIG.check_after_turn),
                warn_on_inconsistency=consistency_dict.get("warn_on_inconsistency", DEFAULT_CONSISTENCY_CONFIG.warn_on_inconsistency)
            ),
            retention=RetentionConfig(
                keep_sessions=retention_dict.get("keep_sessions", DEFAULT_RETENTION_CONFIG.keep_sessions),
                archive_after_days=retention_dict.get("archive_after_days", DEFAULT_RETENTION_CONFIG.archive_after_days)
            ),
            session_id_format=config_dict.get("session_id_format", "%Y%m%d_%H%M%S")
        )
    
    @classmethod
    def from_yaml(cls, yaml_path: Union[str, Path]) -> "DebugConfig":
        """从 YAML 文件加载配置
        
        Args:
            yaml_path: YAML 文件路径
            
        Returns:
            DebugConfig 实例
            
        Raises:
            FileNotFoundError: 当文件不存在时
            ValueError: 当 YAML 格式无效时
            
        Example:
            >>> config = DebugConfig.from_yaml("config/debug_config.yaml")
        """
        yaml_path = Path(yaml_path)
        
        if not yaml_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {yaml_path}")
        
        try:
            import yaml
            with open(yaml_path, "r", encoding="utf-8") as f:
                config_dict = yaml.safe_load(f)
                
            # YAML 文件可能使用嵌套的 debug 键
            if config_dict and "debug" in config_dict:
                config_dict = config_dict["debug"]
                
            return cls.from_dict(config_dict or {})
            
        except ImportError:
            raise ImportError("加载 YAML 配置需要 PyYAML 库，请安装: pip install pyyaml")
        except Exception as e:
            raise ValueError(f"解析 YAML 配置文件失败: {e}")
    
    def to_dict(self) -> Dict[str, Any]:
        """将配置转换为字典
        
        Returns:
            配置字典
        """
        return {
            "enabled": self.enabled,
            "log_level": self.log_level.value,
            "log_dir": self.log_dir,
            "outputs": asdict(self.outputs),
            "performance": asdict(self.performance),
            "consistency": asdict(self.consistency),
            "retention": asdict(self.retention),
            "session_id_format": self.session_id_format
        }
    
    def to_yaml(self, yaml_path: Union[str, Path]) -> None:
        """将配置保存为 YAML 文件
        
        Args:
            yaml_path: 目标 YAML 文件路径
            
        Example:
            >>> config.to_yaml("config/debug_config.yaml")
        """
        try:
            import yaml
            yaml_path = Path(yaml_path)
            yaml_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    {"debug": self.to_dict()}, 
                    f, 
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False
                )
        except ImportError:
            raise ImportError("保存 YAML 配置需要 PyYAML 库，请安装: pip install pyyaml")
    
    def is_level_enabled(self, level: LogLevel) -> bool:
        """检查指定日志级别是否启用
        
        根据当前配置的 log_level，判断是否应该记录指定级别的事件。
        
        Args:
            level: 要检查的日志级别
            
        Returns:
            如果应该记录该级别则返回 True
            
        Example:
            >>> config = DebugConfig(log_level=LogLevel.INFO)
            >>> config.is_level_enabled(LogLevel.DEBUG)
            False
            >>> config.is_level_enabled(LogLevel.ERROR)
            True
        """
        level_priority = {
            LogLevel.DEBUG: 0,
            LogLevel.INFO: 1,
            LogLevel.NOTICE: 2,
            LogLevel.WARNING: 3,
            LogLevel.ERROR: 4,
            LogLevel.CRITICAL: 5
        }
        return level_priority.get(level, 0) >= level_priority.get(self.log_level, 0)
    
    def get_log_dir_path(self) -> Path:
        """获取日志目录的 Path 对象
        
        Returns:
            日志目录路径
        """
        return Path(self.log_dir)
    
    def should_output_master_log(self) -> bool:
        """是否应该输出主日志"""
        return self.enabled and self.outputs.master_log
    
    def should_output_timeline(self) -> bool:
        """是否应该输出结构化时间线"""
        return self.enabled and self.outputs.timeline_json
    
    def should_output_categorized(self) -> bool:
        """是否应该输出分类日志"""
        return self.enabled and self.outputs.categorized
    
    def should_output_snapshots(self) -> bool:
        """是否应该输出状态快照"""
        return self.enabled and self.outputs.snapshots
    
    def should_output_llm_prompts(self) -> bool:
        """是否应该保存 LLM prompts"""
        return self.enabled and self.outputs.llm_prompts
    
    def should_track_llm_latency(self) -> bool:
        """是否应该跟踪 LLM 延迟"""
        return self.enabled and self.performance.track_llm_latency
    
    def should_track_phase_duration(self) -> bool:
        """是否应该跟踪阶段持续时间"""
        return self.enabled and self.performance.track_phase_duration
    
    def should_check_after_each_change(self) -> bool:
        """是否应该在每次变更后检查一致性"""
        return self.enabled and self.consistency.check_after_each_change
    
    def should_check_after_turn(self) -> bool:
        """是否应该在回合结束后检查一致性"""
        return self.enabled and self.consistency.check_after_turn


# ============================================================
# 配置加载辅助函数
# ============================================================

def load_config(
    config_path: Optional[Union[str, Path]] = None,
    env_prefix: str = "DEBUG_"
) -> DebugConfig:
    """加载配置（支持多来源合并）
    
    配置加载优先级（从高到低）：
    1. 指定的配置文件路径
    2. 环境变量
    3. 默认配置
    
    Args:
        config_path: 配置文件路径（可选）
        env_prefix: 环境变量前缀
        
    Returns:
        DebugConfig 实例
        
    Example:
        >>> # 从默认位置加载
        >>> config = load_config()
        >>> 
        >>> # 从指定文件加载
        >>> config = load_config("custom_config.yaml")
        >>> 
        >>> # 使用环境变量覆盖
        >>> # DEBUG_ENABLED=false DEBUG_LOG_LEVEL=error python main.py
    """
    # 从环境变量读取配置路径
    env_config_path = os.getenv(f"{env_prefix}CONFIG")
    
    # 确定配置文件路径
    yaml_path = config_path or env_config_path or DEFAULT_CONFIG_FILE
    
    if yaml_path and Path(yaml_path).exists():
        config = DebugConfig.from_yaml(yaml_path)
    else:
        config = DebugConfig()
    
    # 应用环境变量覆盖
    config = _apply_env_overrides(config, env_prefix)
    
    return config


def _apply_env_overrides(config: DebugConfig, prefix: str) -> DebugConfig:
    """应用环境变量覆盖配置
    
    支持的环境变量：
    - {prefix}ENABLED: 启用/禁用 (true/false)
    - {prefix}LOG_LEVEL: 日志级别
    - {prefix}LOG_DIR: 日志目录
    - {prefix}OUTPUT_MASTER_LOG: 主日志输出 (true/false)
    - {prefix}OUTPUT_TIMELINE_JSON: 时间线输出 (true/false)
    - {prefix}OUTPUT_CATEGORIZED: 分类日志输出 (true/false)
    - {prefix}OUTPUT_SNAPSHOTS: 快照输出 (true/false)
    - {prefix}OUTPUT_LLM_PROMPTS: LLM prompts 输出 (true/false)
    """
    # 基本配置
    if f"{prefix}ENABLED" in os.environ:
        config.enabled = os.getenv(f"{prefix}ENABLED", "true").lower() == "true"
    
    if f"{prefix}LOG_LEVEL" in os.environ:
        level_str = os.getenv(f"{prefix}LOG_LEVEL", "debug").lower()
        try:
            config.log_level = LogLevel(level_str)
        except ValueError:
            pass
    
    if f"{prefix}LOG_DIR" in os.environ:
        config.log_dir = os.getenv(f"{prefix}LOG_DIR", config.log_dir)
    
    # 输出配置
    if f"{prefix}OUTPUT_MASTER_LOG" in os.environ:
        config.outputs.master_log = os.getenv(f"{prefix}OUTPUT_MASTER_LOG", "true").lower() == "true"
    
    if f"{prefix}OUTPUT_TIMELINE_JSON" in os.environ:
        config.outputs.timeline_json = os.getenv(f"{prefix}OUTPUT_TIMELINE_JSON", "true").lower() == "true"
    
    if f"{prefix}OUTPUT_CATEGORIZED" in os.environ:
        config.outputs.categorized = os.getenv(f"{prefix}OUTPUT_CATEGORIZED", "true").lower() == "true"
    
    if f"{prefix}OUTPUT_SNAPSHOTS" in os.environ:
        config.outputs.snapshots = os.getenv(f"{prefix}OUTPUT_SNAPSHOTS", "true").lower() == "true"
    
    if f"{prefix}OUTPUT_LLM_PROMPTS" in os.environ:
        config.outputs.llm_prompts = os.getenv(f"{prefix}OUTPUT_LLM_PROMPTS", "true").lower() == "true"
    
    return config


# ============================================================
# 默认配置实例
# ============================================================

default_config = DebugConfig()
