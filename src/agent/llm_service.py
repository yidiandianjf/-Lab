"""
LLM服务模块 - 封装OpenAI兼容API调用

提供统一的LLM调用接口，支持：
- 任意符合OpenAI API格式的服务
- 自动重试机制（指数退避）
- JSON格式响应解析
- 流式和非流式调用
- 完整的错误处理和降级策略

环境变量配置：
- LLM_API_KEY: sk-xxxxxxxxxxxxxxxx
- LLM_BASE_URL: https://dashscope.aliyuncs.com/compatible-mode/v1
- LLM_MODEL: qwen3.5-122b-a10b
"""

import os
import json
import time
import logging
from typing import List, Dict, Optional, Any, Iterator, Union
from dataclasses import dataclass
from functools import wraps
from pathlib import Path

# 尝试导入OpenAI库
try:
    from openai import OpenAI, APIError, APIConnectionError, RateLimitError
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    # 定义占位符异常类
    class APIError(Exception):
        pass
    class APIConnectionError(Exception):
        pass
    class RateLimitError(Exception):
        pass

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DASHSCOPE_MAX_TOKENS = 16384


# ============================================================
# 异常定义
# ============================================================

class LLMServiceError(Exception):
    """LLM服务基础异常"""
    pass


class LLMAPIError(LLMServiceError):
    """API调用异常"""
    pass


class LLMJSONParseError(LLMServiceError):
    """JSON解析异常"""
    pass


class LLMConfigError(LLMServiceError):
    """配置错误异常"""
    pass


class LLMRetryExhaustedError(LLMServiceError):
    """重试次数耗尽异常"""
    pass


# ============================================================
# 配置数据类
# ============================================================

@dataclass
class LLMConfig:
    """LLM配置类"""
    api_key: str
    base_url: Optional[str] = None
    model: str = "gpt-3.5-turbo"
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    timeout: float = 60.0
    enable_thinking: bool = False  # 是否启用思考模式（非流式调用必须为False）
    structured_output: bool = False  # 是否启用结构化输出

    @staticmethod
    def _resolve_config_path(config_path: str) -> Optional[Path]:
        """Resolve config path from cwd first, then project root."""
        raw_path = Path(config_path).expanduser()
        candidates: List[Path] = []

        if raw_path.is_absolute():
            candidates.append(raw_path)
        else:
            candidates.append(Path.cwd() / raw_path)
            project_root = Path(__file__).resolve().parents[2]
            candidates.append(project_root / raw_path)

        seen = set()
        for candidate in candidates:
            normalized = candidate.resolve(strict=False)
            normalized_key = str(normalized).lower()
            if normalized_key in seen:
                continue
            seen.add(normalized_key)
            if normalized.exists():
                return normalized

        return None
    
    @classmethod
    def from_sources(cls, config_path: str = "config/llm.json") -> "LLMConfig":
        """从配置文件和环境变量加载配置。

        优先级：
        1. 环境变量（便于部署覆盖）
        2. config/llm.json
        3. 默认值
        """
        file_data: Dict[str, Any] = {}
        path = cls._resolve_config_path(config_path)
        if path and path.exists():
            with open(path, "r", encoding="utf-8-sig") as f:
                file_data = json.load(f)

        api_key = os.getenv("LLM_API_KEY") or file_data.get("api_key")
        if not api_key:
            raise LLMConfigError("未配置API Key，请设置 LLM_API_KEY 或 config/llm.json 中的 api_key")

        base_url = os.getenv("LLM_BASE_URL") or file_data.get("base_url")
        model = os.getenv("LLM_MODEL") or file_data.get("model", "gpt-3.5-turbo")

        temperature_env = os.getenv("LLM_TEMPERATURE")
        if temperature_env is not None:
            temperature = float(temperature_env)
        else:
            temperature = float(file_data.get("temperature", 0.7))

        max_tokens_env = os.getenv("LLM_MAX_TOKENS")
        if max_tokens_env is not None:
            max_tokens = int(max_tokens_env)
        else:
            max_tokens = file_data.get("max_tokens")

        timeout_env = os.getenv("LLM_TIMEOUT")
        if timeout_env is not None:
            timeout = float(timeout_env)
        else:
            timeout = float(file_data.get("timeout", 60.0))
        
        # 思考模式设置（默认False，非流式调用必须为False）
        enable_thinking = file_data.get("enable_thinking", False)
        if os.getenv("LLM_ENABLE_THINKING") is not None:
            enable_thinking = os.getenv("LLM_ENABLE_THINKING").lower() in ("true", "1", "yes")
        
        # 结构化输出设置
        structured_output = file_data.get("structured_output", False)
        if os.getenv("LLM_STRUCTURED_OUTPUT") is not None:
            structured_output = os.getenv("LLM_STRUCTURED_OUTPUT").lower() in ("true", "1", "yes")

        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            enable_thinking=enable_thinking,
            structured_output=structured_output,
        )


# ============================================================
# 重试装饰器
# ============================================================

def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    retryable_exceptions: tuple = (APIError, APIConnectionError, RateLimitError, Exception),
):
    """
    指数退避重试装饰器
    
    Args:
        max_retries: 最大重试次数
        base_delay: 基础延迟时间（秒）
        max_delay: 最大延迟时间（秒）
        exponential_base: 指数基数
        retryable_exceptions: 可重试的异常类型
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    
                    if attempt >= max_retries:
                        logger.error(f"函数 {func.__name__} 重试{max_retries}次后仍然失败: {e}")
                        raise LLMRetryExhaustedError(
                            f"重试{max_retries}次后失败: {str(e)}"
                        ) from e
                    
                    # 计算指数退避延迟
                    delay = min(
                        base_delay * (exponential_base ** attempt),
                        max_delay
                    )
                    
                    logger.warning(
                        f"函数 {func.__name__} 第{attempt + 1}次调用失败: {e}, "
                        f"{delay:.1f}秒后重试..."
                    )
                    time.sleep(delay)
            
            # 理论上不会执行到这里
            raise LLMRetryExhaustedError(f"重试失败: {str(last_exception)}")
        
        return wrapper
    return decorator


# ============================================================
# LLM服务类
# ============================================================

class LLMService:
    """
    LLM服务类 - 封装OpenAI兼容API调用
    
    使用示例:
        # 从环境变量创建
        service = LLMService()
        
        # 自定义配置
        config = LLMConfig(api_key="xxx", model="gpt-4")
        service = LLMService(config)
        
        # 调用LLM
        result = service.call_llm("你好")
        
        # JSON格式调用
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        result = service.call_llm_json("提取姓名", schema)
    """
    
    def __init__(self, config: Optional[LLMConfig] = None):
        """
        初始化LLM服务
        
        Args:
            config: LLM配置，如果为None则从环境变量读取
            
        Raises:
            LLMConfigError: 配置错误
            ImportError: OpenAI库未安装
        """
        if not OPENAI_AVAILABLE:
            raise ImportError(
                "未安装openai库，请运行: pip install openai"
            )
        
        self.config = config or LLMConfig.from_sources()
        
        # 初始化OpenAI客户端
        client_kwargs = {"api_key": self.config.api_key, "timeout": self.config.timeout}
        if self.config.base_url:
            client_kwargs["base_url"] = self.config.base_url
        
        self.client = OpenAI(**client_kwargs)
        logger.info(f"LLM服务初始化完成，模型: {self.config.model}")

    @classmethod
    def from_config_path(cls, config_path: str) -> "LLMService":
        """Create a service from a specific config json path."""
        return cls(config=LLMConfig.from_sources(config_path=config_path))

    @staticmethod
    def _pop_debug_options(kwargs: Dict[str, Any]) -> Dict[str, Any]:
        options = {
            "logger": kwargs.pop("debug_logger", None),
            "agent": str(kwargs.pop("debug_agent", "llm")).strip() or "llm",
            "context": kwargs.pop("debug_context", None) or {},
            "call_id": kwargs.pop("debug_call_id", None),
            "attempt": kwargs.pop("debug_attempt", None),
        }
        return options

    def _is_dashscope_request(self, model: Optional[str] = None) -> bool:
        """Return True when the current request targets DashScope's compatible API."""
        base_url = str(self.config.base_url or "").strip().lower()
        model_name = str(model or self.config.model or "").strip().lower()
        return "dashscope.aliyuncs.com" in base_url or model_name.startswith("qwen")

    def _apply_dashscope_non_streaming_options(
        self,
        api_params: Dict[str, Any],
        stream: bool = False,
        enable_thinking: Optional[bool] = None,
    ) -> None:
        """Normalize DashScope-specific options for non-streaming compatible calls."""
        if stream or not self._is_dashscope_request(api_params.get("model")):
            return

        extra_body = dict(api_params.get("extra_body") or {})
        # DashScope requires this field to be explicitly false for non-streaming calls.
        extra_body["enable_thinking"] = False if enable_thinking is None else bool(enable_thinking)
        api_params["extra_body"] = extra_body

    def _normalize_max_tokens(
        self,
        requested_max_tokens: Optional[Any],
        model: Optional[str] = None,
    ) -> Optional[int]:
        """Clamp provider-specific token limits and ignore invalid values."""
        if requested_max_tokens in (None, ""):
            return None

        try:
            max_tokens = int(requested_max_tokens)
        except (TypeError, ValueError):
            logger.warning(f"max_tokens 配置无效，已忽略: {requested_max_tokens}")
            return None

        if max_tokens <= 0:
            logger.warning(f"max_tokens 必须大于 0，已忽略: {max_tokens}")
            return None

        if self._is_dashscope_request(model) and max_tokens > DASHSCOPE_MAX_TOKENS:
            logger.warning(
                "DashScope 兼容接口要求 max_tokens 处于 [1, %s]，已自动从 %s 裁剪到 %s",
                DASHSCOPE_MAX_TOKENS,
                max_tokens,
                DASHSCOPE_MAX_TOKENS,
            )
            return DASHSCOPE_MAX_TOKENS

        return max_tokens
    
    @retry_with_backoff(max_retries=3)
    def call_llm(
        self,
        prompt: str,
        response_format: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
        **kwargs
    ) -> Dict[str, Any]:
        """
        调用LLM并返回结构化响应
        
        Args:
            prompt: 提示文本
            response_format: 响应格式（如JSON模式）
            max_retries: 最大重试次数
            **kwargs: 额外的API参数
            
        Returns:
            包含响应内容的字典
            {
                "success": bool,
                "content": str,
                "model": str,
                "usage": Optional[Dict],
                "error": Optional[str]
            }
        """
        debug_options = self._pop_debug_options(kwargs)
        debug_logger = debug_options.get("logger")
        debug_agent = debug_options.get("agent")
        debug_context = dict(debug_options.get("context") or {})
        debug_call_id = debug_options.get("call_id")
        debug_attempt = debug_options.get("attempt")
        if debug_attempt is not None:
            debug_context["attempt"] = debug_attempt

        started_at = time.time()
        prompt_logged = False
        try:
            messages = [{"role": "user", "content": prompt}]
            
            # 构建API调用参数
            api_params = {
                "model": kwargs.get("model", self.config.model),
                "messages": messages,
                "temperature": kwargs.get("temperature", self.config.temperature),
            }
            
            # 添加可选参数
            request_timeout = kwargs.get("timeout", self.config.timeout)
            if request_timeout is not None:
                api_params["timeout"] = float(request_timeout)
            if response_format:
                api_params["response_format"] = response_format
            
            # 合并额外参数（排除内部参数）
            internal_keys = {"enable_thinking", "debug_logger", "debug_agent", "debug_context", "debug_call_id", "debug_attempt", "max_tokens", "timeout"}
            api_params.update({k: v for k, v in kwargs.items() if k not in api_params and k not in internal_keys})

            requested_max_tokens = kwargs.get("max_tokens", self.config.max_tokens)
            normalized_max_tokens = self._normalize_max_tokens(
                requested_max_tokens,
                model=api_params.get("model"),
            )
            if normalized_max_tokens is not None:
                api_params["max_tokens"] = normalized_max_tokens
            
            # 仅在显式开启时再发送供应商私有参数，提升 OpenAI 兼容网关适配性。
            # 注意：非流式调用中 enable_thinking 必须为 False（阿里云 DashScope 要求）
            enable_thinking = kwargs.get("enable_thinking", self.config.enable_thinking)
            if enable_thinking:
                # 非流式调用不支持 enable_thinking=True，强制设为 False
                logger.warning("非流式调用不支持 enable_thinking=True，已自动禁用思考模式")
                enable_thinking = False
            self._apply_dashscope_non_streaming_options(
                api_params,
                stream=False,
                enable_thinking=enable_thinking,
            )
            
            # 调用API
            if debug_logger and hasattr(debug_logger, "log_llm_request"):
                model_name = kwargs.get("model", self.config.model)
                try:
                    debug_logger.log_llm_request(
                        agent=debug_agent,
                        prompt=prompt,
                        model=model_name,
                        tokens=0,
                        call_id=debug_call_id,
                        context=debug_context,
                    )
                    prompt_logged = True
                except Exception:
                    pass

            response = self.client.chat.completions.create(**api_params)
            
            # 提取响应内容
            content = response.choices[0].message.content
            usage = response.usage.model_dump() if response.usage else None
            
            result = {
                "success": True,
                "content": content,
                "model": response.model,
                "usage": usage,
                "error": None,
            }
            if debug_logger and hasattr(debug_logger, "log_llm_response"):
                duration_ms = (time.time() - started_at) * 1000
                response_context = {
                    "success": True,
                    "usage": usage or {},
                }
                try:
                    debug_logger.log_llm_response(
                        agent=debug_agent,
                        response=json.dumps(result, ensure_ascii=False, indent=2),
                        duration_ms=duration_ms,
                        tokens=0,
                        call_id=debug_call_id,
                        context=response_context,
                    )
                except Exception:
                    pass
            return result
            
        except APIError as e:
            logger.error(f"API调用失败: {e}")
            fallback = self._fallback_response(f"API错误: {str(e)}")
            if debug_logger and hasattr(debug_logger, "log_llm_error"):
                try:
                    if not prompt_logged and hasattr(debug_logger, "log_llm_request"):
                        debug_logger.log_llm_request(
                            agent=debug_agent,
                            prompt=prompt,
                            model=kwargs.get("model", self.config.model),
                            tokens=0,
                            call_id=debug_call_id,
                            context=debug_context,
                        )
                    debug_logger.log_llm_error(
                        agent=debug_agent,
                        error=fallback["error"],
                        context={"call_id": debug_call_id, "attempt": debug_attempt},
                    )
                except Exception:
                    pass
            return fallback
        except Exception as e:
            logger.error(f"调用异常: {e}")
            fallback = self._fallback_response(f"调用异常: {str(e)}")
            if debug_logger and hasattr(debug_logger, "log_llm_error"):
                try:
                    if not prompt_logged and hasattr(debug_logger, "log_llm_request"):
                        debug_logger.log_llm_request(
                            agent=debug_agent,
                            prompt=prompt,
                            model=kwargs.get("model", self.config.model),
                            tokens=0,
                            call_id=debug_call_id,
                            context=debug_context,
                        )
                    debug_logger.log_llm_error(
                        agent=debug_agent,
                        error=fallback["error"],
                        context={"call_id": debug_call_id, "attempt": debug_attempt},
                    )
                except Exception:
                    pass
            return fallback
    
    def call_llm_json(
        self,
        prompt: str,
        schema: Dict[str, Any],
        max_retries: int = 3,
        **kwargs
    ) -> Dict[str, Any]:
        """
        调用LLM并返回JSON格式响应
        
        支持两种模式：
        1. 原生JSON模式（如果API支持）
        2. 提示词约束模式（通用兼容）
        
        Args:
            prompt: 提示文本
            schema: JSON Schema定义
            max_retries: 最大重试次数
            **kwargs: 额外的API参数
            
        Returns:
            包含解析后JSON的字典
            {
                "success": bool,
                "data": Optional[Dict],
                "content": str,
                "model": str,
                "error": Optional[str]
            }
        """
        attempts = max(1, max_retries)
        previous_error = ""
        local_kwargs = dict(kwargs)
        debug_logger = local_kwargs.pop("debug_logger", None)
        debug_agent = str(local_kwargs.pop("debug_agent", "llm_json") or "llm_json")
        debug_base_context = dict(local_kwargs.pop("debug_context", None) or {})
        debug_base_call_id = local_kwargs.pop("debug_call_id", None)
        local_kwargs.pop("debug_attempt", None)
        last_result: Dict[str, Any] = {
            "success": False,
            "data": None,
            "content": "",
            "model": "",
            "error": "未知错误",
        }

        for attempt in range(1, attempts + 1):
            correction_hint = ""
            if previous_error:
                correction_hint = (
                    "\n\n上一次输出存在错误，请严格修正：\n"
                    f"- 错误信息: {previous_error}\n"
                    "请仅输出一个合法JSON对象，不要输出解释文本。"
                )

            json_instruction = (
                f"请根据以下JSON Schema格式返回响应:\n"
                f"{json.dumps(schema, indent=2, ensure_ascii=False)}\n\n"
                f"要求：\n"
                f"1. 只返回JSON对象，不要包含其他文本\n"
                f"2. 确保返回的JSON符合上述Schema\n"
                f"3. 不要添加markdown代码块标记\n"
                f"4. 字段名必须准确，缺失字段请补齐\n"
                f"用户请求：{prompt}"
                f"{correction_hint}"
            )

            # 如果配置启用了结构化输出，使用 json_schema 响应格式
            structured_output = bool(getattr(getattr(self, "config", None), "structured_output", False))
            if structured_output:
                response_format = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "structured_response",
                        "schema": schema
                    }
                }
            else:
                response_format = {"type": "json_object"}
            
            try:
                result = self.call_llm(
                    json_instruction,
                    response_format=response_format,
                    max_retries=max_retries,
                    debug_logger=debug_logger,
                    debug_agent=debug_agent,
                    debug_context={
                        **debug_base_context,
                        "schema": schema,
                        "json_mode": "json_schema" if structured_output else "json_object",
                    },
                    debug_call_id=f"{debug_base_call_id or 'json'}-try-{attempt:02d}",
                    debug_attempt=attempt,
                    **local_kwargs
                )
            except Exception:
                result = self.call_llm(
                    json_instruction,
                    max_retries=max_retries,
                    debug_logger=debug_logger,
                    debug_agent=debug_agent,
                    debug_context={
                        **debug_base_context,
                        "schema": schema,
                        "json_mode": "plain",
                    },
                    debug_call_id=f"{debug_base_call_id or 'json'}-try-{attempt:02d}",
                    debug_attempt=attempt,
                    **local_kwargs
                )

            if not result.get("success"):
                previous_error = result.get("error", "未知错误")
                last_result = {
                    "success": False,
                    "data": None,
                    "content": result.get("content", ""),
                    "model": result.get("model", ""),
                    "error": previous_error,
                }
                logger.warning(f"JSON调用失败，第{attempt}/{attempts}次: {previous_error}")
                if debug_logger and hasattr(debug_logger, "log_llm_retry"):
                    try:
                        debug_logger.log_llm_retry(debug_agent, attempt, previous_error)
                    except Exception:
                        pass
                continue

            content = self._clean_json_content(result.get("content", ""))

            try:
                data = json.loads(content)
                return {
                    "success": True,
                    "data": data,
                    "content": content,
                    "model": result.get("model", ""),
                    "error": None,
                }
            except json.JSONDecodeError as e:
                previous_error = f"JSON解析失败: {str(e)}"
                logger.warning(f"{previous_error}，第{attempt}/{attempts}次，原始内容: {result.get('content', '')}")
                if debug_logger and hasattr(debug_logger, "log_llm_retry"):
                    try:
                        debug_logger.log_llm_retry(debug_agent, attempt, previous_error)
                    except Exception:
                        pass
                last_result = {
                    "success": False,
                    "data": None,
                    "content": result.get("content", ""),
                    "model": result.get("model", ""),
                    "error": previous_error,
                }

        if debug_logger and hasattr(debug_logger, "log_llm_error"):
            try:
                debug_logger.log_llm_error(
                    agent=debug_agent,
                    error=last_result.get("error", "未知错误"),
                    context={"request_context": debug_base_context, "attempts": attempts},
                )
            except Exception:
                pass
        return last_result
    
    @retry_with_backoff(max_retries=3)
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        stream: bool = False,
        **kwargs
    ) -> Union[str, Iterator[str]]:
        """
        对话补全接口
        
        Args:
            messages: 消息列表，格式为 [{"role": "user", "content": "..."}, ...]
            stream: 是否启用流式输出
            **kwargs: 额外的API参数
            
        Returns:
            非流式模式：返回完整响应字符串
            流式模式：返回字符串迭代器
            
        Raises:
            LLMAPIError: API调用失败
        """
        try:
            # 构建API调用参数
            api_params = {
                "model": kwargs.get("model", self.config.model),
                "messages": messages,
                "temperature": kwargs.get("temperature", self.config.temperature),
                "stream": stream,
            }
            
            # 合并额外参数（排除内部参数）
            internal_keys = {"enable_thinking", "debug_logger", "debug_agent", "debug_context", "debug_call_id", "debug_attempt", "max_tokens"}
            api_params.update({k: v for k, v in kwargs.items() if k not in api_params and k not in internal_keys})

            requested_max_tokens = kwargs.get("max_tokens", self.config.max_tokens)
            normalized_max_tokens = self._normalize_max_tokens(
                requested_max_tokens,
                model=api_params.get("model"),
            )
            if normalized_max_tokens is not None:
                api_params["max_tokens"] = normalized_max_tokens
            
            # 仅在显式开启时再发送供应商私有参数，提升 OpenAI 兼容网关适配性。
            # 注意：非流式调用中 enable_thinking 必须为 False（阿里云 DashScope 要求）
            enable_thinking = kwargs.get("enable_thinking", self.config.enable_thinking)
            if enable_thinking:
                if not stream:
                    # 非流式调用不支持 enable_thinking=True，强制设为 False
                    logger.warning("非流式调用不支持 enable_thinking=True，已自动禁用思考模式")
                    enable_thinking = False
            self._apply_dashscope_non_streaming_options(
                api_params,
                stream=stream,
                enable_thinking=enable_thinking if not stream else None,
            )
            
            # 调用API
            response = self.client.chat.completions.create(**api_params)
            
            if stream:
                # 流式模式：返回迭代器
                return self._stream_generator(response)
            else:
                # 非流式模式：返回完整内容
                return response.choices[0].message.content
                
        except (APIError, APIConnectionError, RateLimitError) as e:
            logger.error(f"对话API调用失败: {e}")
            raise LLMAPIError(f"API调用失败: {str(e)}")
        except Exception as e:
            logger.error(f"对话调用异常: {e}")
            raise LLMAPIError(f"调用异常: {str(e)}")
    
    def _stream_generator(self, response) -> Iterator[str]:
        """
        流式响应生成器
        
        Args:
            response: OpenAI流式响应对象
            
        Yields:
            响应文本片段
        """
        try:
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"流式读取异常: {e}")
            raise LLMAPIError(f"流式读取失败: {str(e)}")
    
    def _fallback_response(self, error_message: str) -> Dict[str, Any]:
        """
        生成降级响应
        
        Args:
            error_message: 错误信息
            
        Returns:
            降级响应字典
        """
        return {
            "success": False,
            "content": "",
            "model": self.config.model,
            "usage": None,
            "error": error_message,
        }
    
    @staticmethod
    def _clean_json_content(content: str) -> str:
        """
        清理JSON内容，移除markdown代码块标记
        
        Args:
            content: 原始内容
            
        Returns:
            清理后的JSON字符串
        """
        content = content.strip()
        
        # 移除markdown代码块标记
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        
        if content.endswith("```"):
            content = content[:-3]
        
        return content.strip()


# ============================================================
# 便捷函数
# ============================================================

def create_llm_service(config: Optional[LLMConfig] = None) -> LLMService:
    """
    创建LLM服务实例的便捷函数
    
    Args:
        config: 可选的配置对象
        
    Returns:
        LLMService实例
    """
    return LLMService(config)


def quick_call(prompt: str, **kwargs) -> Dict[str, Any]:
    """
    快速调用LLM的便捷函数
    
    Args:
        prompt: 提示文本
        **kwargs: 额外参数
        
    Returns:
        响应字典
    """
    service = LLMService()
    return service.call_llm(prompt, **kwargs)


def quick_json_call(prompt: str, schema: Dict[str, Any], **kwargs) -> Dict[str, Any]:
    """
    快速JSON调用LLM的便捷函数
    
    Args:
        prompt: 提示文本
        schema: JSON Schema
        **kwargs: 额外参数
        
    Returns:
        JSON响应字典
    """
    service = LLMService()
    return service.call_llm_json(prompt, schema, **kwargs)


# ============================================================
# 默认实例
# ============================================================

# 延迟初始化的默认服务实例
_default_service: Optional[LLMService] = None


def get_default_service() -> LLMService:
    """获取默认服务实例（延迟初始化）"""
    global _default_service
    if _default_service is None:
        _default_service = LLMService()
    return _default_service



