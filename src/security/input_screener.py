"""Composable input screener with keyword and optional AI layers."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .ai_filter import AIScreenFilter, APIModelFilter
from .keyword_filter import KeywordFilter

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


@dataclass
class ScreenResult:
    is_blocked: bool
    layer: int
    reason: str
    user_message: str
    detail: Optional[dict] = None


class InputScreener:
    """Input screener with configurable fail-open strategy."""

    def __init__(
        self,
        config_path: str = "config/security_config.json",
        keyword_config: Optional[str] = None,
        ai_filter: Optional[AIScreenFilter] = None,
    ):
        self.config_path = config_path
        self.config = self._load_config(config_path)

        self.enabled = bool(self.config.get("enabled", True))
        keyword_cfg = self.config.get("keyword_filter", {}) or {}
        ai_cfg = self.config.get("ai_filter", {}) or {}
        bypass_cfg = self.config.get("command_bypass", {}) or {}
        fail_cfg = self.config.get("fail_policy", {}) or {}

        self.keyword_enabled = bool(keyword_cfg.get("enabled", True))
        self._ai_cfg = dict(ai_cfg)
        self.ai_config_enabled = bool(ai_cfg.get("enabled", False))
        self.ai_enabled = self.ai_config_enabled
        self.block_level = int((ai_cfg.get("threshold", {}) or {}).get("block_level", 3))
        self.warn_level = int((ai_cfg.get("threshold", {}) or {}).get("warn_level", 2))
        self.ai_timeout_ms = int(ai_cfg.get("timeout_ms", 500))
        self.ai_max_retries = int(ai_cfg.get("max_retries", 1))

        self.on_layer1_error = str(fail_cfg.get("on_layer1_error", "allow")).lower()
        self.on_layer2_error = str(fail_cfg.get("on_layer2_error", "allow")).lower()

        self.bypass_enabled = bool(bypass_cfg.get("enabled", True))
        self.bypass_commands = {
            str(x).strip().lower()
            for x in (bypass_cfg.get("commands", []) or [])
            if str(x).strip()
        }

        resolved_keyword_path = keyword_config or str(keyword_cfg.get("config_path", "config/sensitive_words.json"))
        self.keyword_filter = KeywordFilter(resolved_keyword_path)
        self.ai_filter = ai_filter or self._build_ai_filter(ai_cfg)

        logger.info(
            "Input screener initialized: enabled=%s keyword=%s ai=%s",
            self.enabled,
            self.keyword_enabled,
            self.ai_enabled and self.ai_filter is not None,
        )

    def should_bypass(self, command: Optional[str]) -> bool:
        if not self.bypass_enabled or not command:
            return False
        return str(command).strip().lower() in self.bypass_commands


    def set_ai_enabled(self, enabled: bool) -> bool:
        desired = bool(enabled)
        if desired and self.ai_filter is None and self.ai_config_enabled:
            self.ai_filter = self._build_ai_filter(self._ai_cfg)
        self.ai_enabled = desired and self.ai_filter is not None
        return self.ai_enabled

    def ai_status(self) -> Dict[str, Any]:
        return {
            "enabled": bool(self.ai_enabled and self.ai_filter is not None),
            "configured": bool(self.ai_config_enabled),
            "available": bool(self.ai_filter is not None),
            "timeout_ms": self.ai_timeout_ms,
            "max_retries": self.ai_max_retries,
        }

    @staticmethod
    def _normalized_text_variants(text: str) -> Tuple[str, str]:
        normalized = str(text or "").strip().lower()
        compact = re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)
        return normalized, compact

    @classmethod
    def _find_markers(cls, text: str, markers: Tuple[str, ...]) -> List[str]:
        normalized, compact = cls._normalized_text_variants(text)
        if not normalized:
            return []
        haystacks = (normalized, compact)
        return [marker for marker in markers if any(marker in haystack for haystack in haystacks)]

    @staticmethod
    def _looks_like_system_operation_text(text: str) -> bool:
        normalized = str(text or "").strip().lower()
        if not normalized:
            return False

        technical_markers = (
            "system", "prompt", "injection", "override", "ignore previous", "developer",
            "command", "cmd", "shell", "terminal", "powershell", "bash", "python", "sql",
            "api", "token", "key", "file", "database", "script", "config", "json", "yaml",
            "\u7cfb\u7edf", "\u63d0\u793a\u8bcd", "\u6ce8\u5165", "\u547d\u4ee4", "\u811a\u672c", "\u7ec8\u7aef", "\u6570\u636e\u5e93", "\u6587\u4ef6", "\u5bc6\u94a5", "\u914d\u7f6e",
            "\u5220\u9664", "\u6267\u884c", "\u8fd0\u884c", "\u63a5\u53e3", "\u73af\u5883\u53d8\u91cf",
        )
        if any(marker in normalized for marker in technical_markers):
            return True

        command_patterns = (
            "\\[a-z]+",
            r"[a-z]:\\",
            r"/(?:etc|usr|var|tmp)/",
            r"\b(?:rm|del|copy|move|type|cat|dir|ls|chmod|curl|wget|pip|conda|git)\b",
            r"\b(?:select|insert|update|delete|drop|create)\b\s+",
            r"\.(?:py|json|yaml|yml|db|sql|ps1|bat|sh)\b",
        )
        return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in command_patterns)

    @classmethod
    def _looks_like_explicit_abuse_text(cls, text: str) -> bool:
        abusive_markers = (
            "\u50bb\u903c", "\u50bbb", "\u50bb\u53c9", "\u715e\u7b14", "\u6c99\u6bd4", "\u5e9f\u7269", "\u8d31\u4eba", "\u72d7\u4e1c\u897f", "\u6eda\u5f00", "\u53bb\u6b7b",
            "\u6211\u64cd", "\u64cd\u4f60", "\u8349\u4f60", "\u8349\u4f60\u5988", "\u8349\u6ce5\u9a6c", "\u5367\u69fd", "\u4f60\u5988", "\u4f60\u5988\u7684", "\u4ed6\u5988\u7684", "\u5988\u7684", "\u5c3c\u739b",
            "fuck", "fxxk", "shit", "bitch", "motherfucker",
        )
        return bool(cls._find_markers(text, abusive_markers))

    @classmethod
    def _looks_like_explicit_violence_text(cls, text: str) -> bool:
        violence_markers = (
            "\u6740\u4eba", "\u780d\u4eba", "\u780d\u5934", "\u780d\u6b7b", "\u6253\u6b7b", "\u6345\u6b7b", "\u67aa\u6740", "\u70b8\u6b7b", "\u52d2\u6b7b", "\u7206\u5934",
            "\u788e\u5c38", "\u8840\u6d46", "\u8111\u6d46", "\u8840\u6d41\u6210\u6cb3", "\u5f00\u819b\u7834\u809a", "\u80a2\u89e3", "\u65ad\u80a2",
            "gore", "behead", "kill", "murder",
        )
        return bool(cls._find_markers(text, violence_markers))


    @staticmethod
    def _looks_like_direct_assault_text(text: str) -> bool:
        normalized = str(text or "").strip().lower()
        if not normalized:
            return False
        assault_patterns = (
            r"(?:打|揍|殴打|暴打|毒打)(?:了|过)?(?:他|她|人|童子|书童|小童|孔明|诸葛亮)?(?:一拳|一下|一顿|几下)?",
            r"(?:给|朝|冲着)(?:他|她|人|童子|书童|小童|孔明|诸葛亮)(?:打|揍|踢|踹)(?:一拳|一脚|一顿|几下)?",
            r"(?:踢|踹)(?:了|过)?(?:他|她|人|童子|书童|小童|孔明|诸葛亮)?(?:一脚|一下)?",
            r"(?:扇|抽)(?:了|过)?(?:他|她|人|童子|书童|小童|孔明|诸葛亮)(?:耳光|巴掌)?",
        )
        return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in assault_patterns)

    @classmethod
    def _looks_like_self_harm_text(cls, text: str) -> bool:
        self_harm_markers = (
            "\u81ea\u6740", "\u81ea\u6b8b", "\u5272\u8155", "\u8df3\u697c", "\u4e0a\u540a", "\u8f7b\u751f", "\u670d\u6bd2", "\u541e\u836f", "\u81ea\u5c3d",
            "suicide", "self-harm",
        )
        return bool(cls._find_markers(text, self_harm_markers))

    @classmethod
    def _looks_like_political_sensitive_text(cls, text: str) -> bool:
        sensitive_markers = (
            "\u989c\u8272\u9769\u547d", "\u516d\u56db", "\u516b\u4e5d\u6c11\u8fd0", "\u5929\u5b89\u95e8\u4e8b\u4ef6", "\u53f0\u72ec", "\u6e2f\u72ec", "\u7586\u72ec", "\u6cd5\u8f6e\u529f", "\u98a0\u8986\u56fd\u5bb6\u653f\u6743", "\u63a8\u7ffb\u653f\u5e9c", "\u5206\u88c2\u56fd\u5bb6",
        )
        return bool(cls._find_markers(text, sensitive_markers))

    @classmethod
    def _looks_like_explicit_system_probe_text(cls, text: str) -> bool:
        probe_markers = (
            "系统提示词", "system prompt", "developer message", "api key", "token",
            "密钥", "源码", "配置文件", "数据库", "内部提示",
        )
        return bool(cls._find_markers(text, probe_markers))

    @classmethod
    def _match_local_hard_block(cls, text: str) -> Optional[ScreenResult]:
        if cls._looks_like_explicit_system_probe_text(text):
            return ScreenResult(
                is_blocked=True,
                layer=0,
                reason="local hard block (system_operation): explicit system probe",
                user_message="Input blocked.",
                detail={"category": "system_operation", "matched_words": ["system_probe"]},
            )

        if cls._looks_like_direct_assault_text(text):
            return ScreenResult(
                is_blocked=True,
                layer=0,
                reason="local hard block (violence): direct assault intent",
                user_message="Input blocked.",
                detail={"category": "violence", "matched_words": ["direct_assault"]},
            )

        local_rules: List[Tuple[str, Tuple[str, ...]]] = [
            (
                "abuse",
                (
                    "\u50bb\u903c", "\u50bbb", "\u50bb\u53c9", "\u715e\u7b14", "\u6c99\u6bd4", "\u5e9f\u7269", "\u8d31\u4eba", "\u72d7\u4e1c\u897f", "\u6eda\u5f00", "\u53bb\u6b7b",
                    "\u6211\u64cd", "\u64cd\u4f60", "\u8349\u4f60", "\u8349\u4f60\u5988", "\u8349\u6ce5\u9a6c", "\u5367\u69fd", "\u4f60\u5988", "\u4f60\u5988\u7684", "\u4ed6\u5988\u7684", "\u5988\u7684", "\u5c3c\u739b",
                    "fuck", "fxxk", "shit", "bitch", "motherfucker",
                ),
            ),
            (
                "sexual_content",
                (
                    "\u5f3a\u5978", "\u8f6e\u5978", "\u7ea6\u70ae", "\u88f8\u804a", "\u9ec4\u7247", "\u88f8\u7167", "\u505a\u7231", "\u6027\u4ea4", "porn", "nude",
                ),
            ),
            (
                "violence",
                (
                    "\u6740\u4eba", "\u780d\u4eba", "\u780d\u5934", "\u780d\u6b7b", "\u6253\u6b7b", "\u6345\u6b7b", "\u67aa\u6740", "\u70b8\u6b7b", "\u52d2\u6b7b",
                ),
            ),
            (
                "gore",
                (
                    "\u7206\u5934", "\u788e\u5c38", "\u8840\u6d46", "\u8111\u6d46", "\u8840\u6d41\u6210\u6cb3", "\u5f00\u819b\u7834\u809a", "\u80a2\u89e3", "\u65ad\u80a2",
                ),
            ),
            (
                "self_harm",
                (
                    "\u81ea\u6740", "\u81ea\u6b8b", "\u5272\u8155", "\u8df3\u697c", "\u4e0a\u540a", "\u8f7b\u751f", "\u670d\u6bd2", "\u541e\u836f", "\u81ea\u5c3d",
                ),
            ),
            (
                "politics_sensitive",
                (
                    "\u989c\u8272\u9769\u547d", "\u516d\u56db", "\u516b\u4e5d\u6c11\u8fd0", "\u5929\u5b89\u95e8\u4e8b\u4ef6", "\u53f0\u72ec", "\u6e2f\u72ec", "\u7586\u72ec", "\u6cd5\u8f6e\u529f", "\u98a0\u8986\u56fd\u5bb6\u653f\u6743", "\u63a8\u7ffb\u653f\u5e9c", "\u5206\u88c2\u56fd\u5bb6",
                ),
            ),
        ]

        for category, markers in local_rules:
            matched = cls._find_markers(text, markers)
            if matched:
                return ScreenResult(
                    is_blocked=True,
                    layer=0,
                    reason=f"local hard block ({category}): {', '.join(matched)}",
                    user_message="Input blocked.",
                    detail={"matched_words": matched, "category": category},
                )

        return None

    @classmethod
    def _looks_like_explicit_obscene_text(cls, text: str) -> bool:
        obscene_markers = (
            "\u8272\u60c5", "\u6deb\u79fd", "\u88f8\u804a", "\u88f8\u7167", "\u505a\u7231", "\u6027\u4ea4", "\u7ea6\u70ae", "\u5f3a\u5978", "\u8f6e\u5978",
            "\u9e21\u5df4", "\u9634\u9053", "\u4e73\u623f", "\u9ec4\u7247", "porn", "nude",
        )
        return bool(cls._find_markers(text, obscene_markers))

    @classmethod
    def _looks_like_advertising_text(cls, text: str) -> bool:
        advertising_markers = (
            "vx", "\u5fae\u4fe1", "qq", "\u52a0\u7fa4", "\u79c1\u804a", "\u8054\u7cfb\u65b9\u5f0f", "\u8054\u7cfb\u6211",
            "\u4ee3\u505a", "\u4ee3\u5199", "\u8d2d\u4e70", "\u4e0b\u5355", "\u63a8\u5e7f", "\u8fd4\u5229", "\u5f15\u6d41",
        )
        return bool(cls._find_markers(text, advertising_markers))

    def _should_block_natural_language(self, text: str, ai_result: Any, ai_categories: Set[str]) -> bool:
        if getattr(ai_result, "is_safe", False):
            return False
        if ai_result.risk_level.value < self.block_level:
            return False
        if not ai_categories:
            return False

        if ai_categories & {"prompt_injection", "system_leak"}:
            return self._looks_like_system_operation_text(text)

        if "system_operation" in ai_categories:
            return self._looks_like_system_operation_text(text)

        if "advertising" in ai_categories:
            return self._looks_like_advertising_text(text)

        if ai_categories & {"obscene", "sexual_content"}:
            return self._looks_like_explicit_obscene_text(text)

        if ai_categories & {"violence", "gore"}:
            return self._looks_like_explicit_violence_text(text)

        if "self_harm" in ai_categories:
            return self._looks_like_self_harm_text(text)

        if "politics_sensitive" in ai_categories:
            return self._looks_like_political_sensitive_text(text)

        if ai_categories & {"abuse", "threat"}:
            return self._looks_like_explicit_abuse_text(text)

        return False

    def _should_block_ai_result(self, text: str, context: Dict[str, Any], ai_result: Any, ai_categories: Set[str]) -> bool:
        channel = str((context or {}).get("channel", "") or "").strip().lower()
        if channel == "natural_language":
            return self._should_block_natural_language(text, ai_result, ai_categories)

        return (not getattr(ai_result, "is_safe", False)) and ai_result.risk_level.value >= self.block_level

    def _should_warn_natural_language(self, text: str, ai_categories: Set[str]) -> bool:
        if not ai_categories:
            return False
        if ai_categories & {"prompt_injection", "system_leak", "system_operation"}:
            return self._looks_like_system_operation_text(text)
        if "advertising" in ai_categories:
            return self._looks_like_advertising_text(text)
        if ai_categories & {"obscene", "sexual_content"}:
            return self._looks_like_explicit_obscene_text(text)
        if ai_categories & {"violence", "gore"}:
            return self._looks_like_explicit_violence_text(text)
        if "self_harm" in ai_categories:
            return self._looks_like_self_harm_text(text)
        if "politics_sensitive" in ai_categories:
            return self._looks_like_political_sensitive_text(text)
        if ai_categories & {"abuse", "threat"}:
            return self._looks_like_explicit_abuse_text(text)
        return False

    def _should_emit_ai_warning(self, text: str, context: Dict[str, Any], ai_result: Any, ai_categories: Set[str]) -> bool:
        if ai_result.risk_level.value < self.warn_level:
            return False
        channel = str((context or {}).get("channel", "") or "").strip().lower()
        if channel == "natural_language":
            return self._should_warn_natural_language(text, ai_categories)
        return True

    @classmethod
    def _looks_like_ai_borderline_text(cls, text: str) -> bool:
        """Detect gray-area inputs worth sending to the AI fallback layer."""
        normalized = str(text or "").strip().lower()
        if not normalized:
            return False

        if cls._looks_like_system_operation_text(text):
            return True

        soft_patterns = (
            "(\u6df7\u8d26|\u8be5\u6b7b|\u6eda\u5f00|\u738b\u516b\u86cb|\u757c\u751f|\u8d31\u4eba|\u5e9f\u7269|\u65e0\u803b)",
            "(\u7808\u95e8|\u95ef\u8fdb\u53bb|\u786c\u95ef|\u52a8\u624b|\u63cd\u4ed6|\u6253\u4ed6|\u780d\u4ed6|\u5bb0\u4e86|\u5f04\u6b7b)",
            "(\u8840|\u5c38|\u65ad\u624b|\u65ad\u5934|\u6345\u5200|\u67aa|\u70b8\u836f)",
            "(\u4e0a\u5e8a|\u4eb2\u5634|\u6478\u80f8|\u8131\u8863|\u88f8\u4f53|\u6027\u9a9a\u6270|\u5f3a\u8feb)",
            "(\u4e0d\u60f3\u6d3b|\u6d3b\u4e0d\u4e0b\u53bb|\u7ed3\u675f\u751f\u547d|\u8f7b\u751f)",
            "(\u653f\u5e9c|\u653f\u6743|\u9886\u5bfc\u4eba|\u793a\u5a01|\u6e38\u884c|\u9769\u547d|\u72ec\u7acb|\u5206\u88c2)",
            r"\b(hack|bypass|inject|override|exploit|payload)\b",
        )
        return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in soft_patterns)

    def _should_run_ai_screening(
        self,
        text: str,
        context: Dict[str, Any],
        layer1_action: Optional[str] = None,
    ) -> bool:
        """AI layer should be a real fallback, not a request on every sentence."""
        if not (self.ai_enabled and self.ai_filter):
            return False
        if bool(context.get("bypass_ai", False)):
            return False

        channel = str((context or {}).get("channel", "") or "").strip().lower()
        if channel != "natural_language":
            return True

        if (layer1_action or "").lower() == "warn":
            return True

        return self._looks_like_ai_borderline_text(text)

    def screen(self, text: str, context: Optional[dict] = None) -> ScreenResult:
        context = context or {}
        if not self.enabled:
            return ScreenResult(False, 0, "screener disabled", "", None)
        if not text or not text.strip():
            return ScreenResult(False, 0, "empty input", "", None)

        local_block = self._match_local_hard_block(text)
        if local_block is not None:
            return local_block

        layer1_action: Optional[str] = None
        if self.keyword_enabled:
            try:
                layer1 = self.keyword_filter.check(text)
            except Exception as exc:
                logger.exception("Keyword screening error: %s", exc)
                if self.on_layer1_error == "block":
                    return ScreenResult(True, 1, f"keyword screening error: {exc}", "Input blocked.", {"error": str(exc)})
                layer1 = None

            if layer1:
                layer1_action = str(layer1.action or "").lower()
                if layer1.is_blocked:
                    return ScreenResult(
                        True,
                        1,
                        f"keyword rule matched: {', '.join(layer1.matched_words)}",
                        "Input blocked.",
                        {
                            "matched_words": layer1.matched_words,
                            "category": layer1.category,
                            "level": layer1.level,
                            "action": layer1.action,
                        },
                    )
                if layer1.action == "warn":
                    logger.info("Keyword screening warning: %s", layer1.matched_words)

        if self._should_run_ai_screening(text, context, layer1_action=layer1_action):
            try:
                if self.ai_filter.is_available():
                    ai_result = self.ai_filter.screen(
                        text,
                        context=context,
                        timeout=self.ai_timeout_ms / 1000.0,
                        max_retries=self.ai_max_retries,
                    )
                    ai_categories = {
                        str(one).strip().lower()
                        for one in (ai_result.risk_categories or [])
                        if str(one).strip()
                    }
                    should_block = self._should_block_ai_result(text, context, ai_result, ai_categories)

                    if should_block:
                        return ScreenResult(
                            True,
                            2,
                            ai_result.reason or "ai screening blocked",
                            f"Input blocked. {ai_result.suggestion}",
                            {
                                "risk_level": ai_result.risk_level.name,
                                "confidence": ai_result.confidence,
                                "risk_categories": ai_result.risk_categories,
                            },
                        )

                    if self._should_emit_ai_warning(text, context, ai_result, ai_categories):
                        logger.info(
                            "AI screening warning: safe=%s risk=%s confidence=%.2f categories=%s reason=%s",
                            ai_result.is_safe,
                            ai_result.risk_level.name,
                            ai_result.confidence,
                            ai_result.risk_categories,
                            ai_result.reason,
                        )
            except Exception as exc:
                logger.warning("AI screening error: %s", exc)
                if self.on_layer2_error == "block":
                    return ScreenResult(True, 2, f"ai screening error: {exc}", "Input blocked.", {"error": str(exc)})

        return ScreenResult(False, 0, "passed", "", None)

    def _build_ai_filter(self, ai_cfg: Dict[str, Any]) -> Optional[AIScreenFilter]:
        if not self.ai_config_enabled:
            return None
        provider = str(ai_cfg.get("type", "api") or "api").strip().lower()
        if provider != "api":
            logger.warning("Unsupported AI screening provider '%s'; disabling AI layer", provider)
            return None
        llm_config_path = str(ai_cfg.get("config_path", "config/security_llm.json"))
        try:
            return APIModelFilter.from_sources(config_path=llm_config_path)
        except Exception as exc:
            logger.warning("AI screener init failed; falling back to keyword-only mode: %s", exc)
            return None

    @staticmethod
    def _load_config(config_path: str) -> Dict[str, Any]:
        path = _resolve_config_path(config_path)
        if not path:
            logger.warning("Security config not found; using defaults: %s", config_path)
            return {}
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
