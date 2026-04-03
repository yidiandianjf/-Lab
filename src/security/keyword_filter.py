"""Keyword-based safety filtering for user input."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
class FilterResult:
    is_blocked: bool
    matched_words: List[str]
    category: str
    level: int
    message: str
    action: str = "allow"


class KeywordFilter:
    """Keyword and regex based filter."""

    def __init__(self, config_path: str = "config/sensitive_words.json"):
        self.config_path = config_path
        self._categories: Dict[str, Dict[str, Any]] = {}
        self._words: List[Tuple[str, str]] = []
        self._patterns: List[Tuple[re.Pattern[str], str, str]] = []
        self.reload()

    def reload(self) -> None:
        path = _resolve_config_path(self.config_path)
        if not path:
            logger.warning("敏感词配置不存在，跳过关键词筛查: %s", self.config_path)
            self._categories = {}
            self._words = []
            self._patterns = []
            return

        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)

        self._categories = data.get("categories", {}) or {}
        self._words = []
        self._patterns = []

        for one in data.get("words", []) or []:
            word = str(one.get("word", "") or "").strip()
            category = str(one.get("category", "") or "default").strip()
            if word:
                self._words.append((word, category))

        for one in data.get("patterns", []) or []:
            pattern_raw = str(one.get("pattern", "") or "").strip()
            category = str(one.get("category", "") or "default").strip()
            description = str(one.get("description", "") or pattern_raw).strip()
            if not pattern_raw:
                continue
            try:
                self._patterns.append((re.compile(pattern_raw, flags=re.IGNORECASE), category, description))
            except re.error as exc:
                logger.warning("忽略非法正则: %s (%s)", pattern_raw, exc)

        logger.info("关键词配置已加载: words=%d patterns=%d", len(self._words), len(self._patterns))

    def check(self, text: str) -> FilterResult:
        text = str(text or "")
        if not text.strip():
            return FilterResult(False, [], "", 0, "", "allow")

        matched_words: List[str] = []
        matched_category = ""
        max_level = 0
        final_action = "allow"

        for word, category in self._words:
            if word.lower() in text.lower():
                matched_words.append(word)
                level, action = self._get_category_policy(category)
                if level >= max_level:
                    max_level = level
                    matched_category = category
                    final_action = action

        for pattern, category, description in self._patterns:
            if pattern.search(text):
                matched_words.append(f"pattern:{description}")
                level, action = self._get_category_policy(category)
                if level >= max_level:
                    max_level = level
                    matched_category = category
                    final_action = action

        if not matched_words:
            return FilterResult(False, [], "", 0, "", "allow")

        is_blocked = final_action == "block"
        return FilterResult(
            is_blocked=is_blocked,
            matched_words=matched_words,
            category=matched_category,
            level=max_level,
            message="命中关键词规则",
            action=final_action,
        )

    def _get_category_policy(self, category: str) -> Tuple[int, str]:
        one = self._categories.get(category, {}) or {}
        try:
            level = int(one.get("level", 1))
        except Exception:
            level = 1
        action = str(one.get("action", "block") or "block").strip().lower()
        if action not in {"allow", "warn", "block"}:
            action = "block"
        return level, action

