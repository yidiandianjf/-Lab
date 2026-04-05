"""AI-based safety filtering abstraction and API implementation."""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.agent.llm_service import LLMConfig, LLMService

logger = logging.getLogger(__name__)


def _resolve_config_path(config_path: str) -> Optional[Path]:
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
        key = str(normalized).lower()
        if key in seen:
            continue
        seen.add(key)
        if normalized.exists():
            return normalized
    return None


class RiskLevel(Enum):
    SAFE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class AIScreenResult:
    is_safe: bool
    risk_level: RiskLevel
    confidence: float
    risk_categories: List[str]
    reason: str
    suggestion: str


class AIScreenFilter(ABC):
    @abstractmethod
    def screen(
        self,
        text: str,
        context: Optional[dict] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> AIScreenResult:
        raise NotImplementedError

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError


@dataclass
class SecurityLLMConfig:
    api_key: str
    base_url: Optional[str] = None
    model: str = "gpt-4o-mini"
    temperature: float = 0.0
    max_tokens: Optional[int] = 512
    timeout: float = 30.0
    client_max_retries: int = 0
    enable_thinking: bool = False
    structured_output: bool = True

    @classmethod
    def from_sources(cls, config_path: str = "config/security_llm.json") -> "SecurityLLMConfig":
        file_data: Dict[str, Any] = {}
        path = _resolve_config_path(config_path)
        if path and path.exists():
            with open(path, "r", encoding="utf-8-sig") as f:
                file_data = json.load(f)

        api_key = os.getenv("SECURITY_LLM_API_KEY") or file_data.get("api_key")
        base_url = os.getenv("SECURITY_LLM_BASE_URL") or file_data.get("base_url")
        model = os.getenv("SECURITY_LLM_MODEL") or file_data.get("model", "gpt-4o-mini")
        temperature = float(os.getenv("SECURITY_LLM_TEMPERATURE") or file_data.get("temperature", 0.0))
        max_tokens = int(os.getenv("SECURITY_LLM_MAX_TOKENS") or file_data.get("max_tokens", 512))
        timeout = float(os.getenv("SECURITY_LLM_TIMEOUT") or file_data.get("timeout", 30.0))
        client_max_retries = int(os.getenv("SECURITY_LLM_CLIENT_MAX_RETRIES") or file_data.get("client_max_retries", 0))

        enable_thinking_val = os.getenv("SECURITY_LLM_ENABLE_THINKING")
        if enable_thinking_val is None:
            enable_thinking = bool(file_data.get("enable_thinking", False))
        else:
            enable_thinking = enable_thinking_val.lower() in {"1", "true", "yes"}

        structured_output_val = os.getenv("SECURITY_LLM_STRUCTURED_OUTPUT")
        if structured_output_val is None:
            structured_output = bool(file_data.get("structured_output", True))
        else:
            structured_output = structured_output_val.lower() in {"1", "true", "yes"}

        if not api_key:
            raise ValueError("未配置安全筛查 API Key，请设置 SECURITY_LLM_API_KEY 或 config/security_llm.json")

        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            client_max_retries=client_max_retries,
            enable_thinking=enable_thinking,
            structured_output=structured_output,
        )

    def to_llm_config(self) -> LLMConfig:
        return LLMConfig(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
            client_max_retries=self.client_max_retries,
            enable_thinking=self.enable_thinking,
            structured_output=self.structured_output,
        )


class APIModelFilter(AIScreenFilter):
    """Call API model to classify input safety risk."""

    def __init__(self, llm_service: LLMService):
        self.llm_service = llm_service

    @classmethod
    def from_sources(cls, config_path: str = "config/security_llm.json") -> "APIModelFilter":
        cfg = SecurityLLMConfig.from_sources(config_path)
        service = LLMService(config=cfg.to_llm_config())
        return cls(service)

    def is_available(self) -> bool:
        return self.llm_service is not None

    def screen(
        self,
        text: str,
        context: Optional[dict] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> AIScreenResult:
        schema = {
            "type": "object",
            "properties": {
                "is_safe": {"type": "boolean"},
                "risk_level": {"type": "integer", "minimum": 0, "maximum": 4},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "risk_categories": {"type": "array", "items": {"type": "string"}},
                "reason": {"type": "string"},
                "suggestion": {"type": "string"},
            },
            "required": ["is_safe", "risk_level", "confidence", "risk_categories", "reason", "suggestion"],
            "additionalProperties": False,
        }
        context_text = json.dumps(context or {}, ensure_ascii=False)
        prompt = (
            "??????????????????????\n"
            "??????????/?????????????????????????????????\n"
            "????????????????????????????????????????\n"
            "???????????????????????????????????????? SAFE ? LOW?\n"
            "?????0=SAFE, 1=LOW, 2=MEDIUM, 3=HIGH, 4=CRITICAL?\n"
            "risk_categories ????: ['prompt_injection', 'system_leak', 'system_operation', 'abuse', 'obscene', 'sexual_content', 'violence', 'gore', 'self_harm', 'threat', 'politics_sensitive', 'advertising', 'other']?\n\n"
            f"?????{text}\n"
            f"????{context_text}\n"
            "?????? JSON Schema ???"
        )
        call_kwargs = {"prompt": prompt, "schema": schema, "max_retries": max(1, int(max_retries or 1))}
        if timeout is not None:
            call_kwargs["timeout"] = timeout
        resp = self.llm_service.call_llm_json(**call_kwargs)
        if not resp.get("success"):
            raise RuntimeError(resp.get("error", "AI筛查失败"))
        data = resp.get("data", {}) or {}
        try:
            level = RiskLevel(int(data.get("risk_level", 0)))
        except Exception:
            level = RiskLevel.SAFE
        return AIScreenResult(
            is_safe=bool(data.get("is_safe", True)),
            risk_level=level,
            confidence=float(data.get("confidence", 0.0)),
            risk_categories=[str(x) for x in data.get("risk_categories", []) or []],
            reason=str(data.get("reason", "") or ""),
            suggestion=str(data.get("suggestion", "") or ""),
        )


