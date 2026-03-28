"""Merge fragmented narratives into a coherent turn-level narrative."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.agent.llm_service import LLMService
from src.data.models import (
    NarrativeMergerInputV2,
    NarrativeMergerOutputV2,
    NarrativeMemoryView,
    TurnStep,
)


class NarrativeMerger:
    """LLM-backed narrative merger with deterministic fallback."""

    def __init__(
        self,
        llm_service: Optional[LLMService] = None,
        system_prompt: Optional[str] = None,
        use_llm: bool = True,
    ):
        self.use_llm = bool(use_llm)
        self.llm_service = llm_service
        if self.use_llm and self.llm_service is None:
            try:
                self.llm_service = LLMService()
            except Exception:
                self.llm_service = None
        if not self.use_llm:
            self.llm_service = None

        self.system_prompt = system_prompt or self._load_default_prompt()

    def merge(
        self,
        fragments: List[Dict[str, str]],
        game_state: Optional[Any] = None,
        context: str = "",
        truth_anchor: Optional[Dict[str, Any]] = None,
    ) -> str:
        cleaned = [f for f in fragments if (f.get("text") or "").strip()]
        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return cleaned[0]["text"].strip()

        if self.llm_service:
            merged = self._merge_with_llm(cleaned, game_state, context, truth_anchor or {})
            if merged:
                return merged

        return "\n".join(fragment["text"].strip() for fragment in cleaned if fragment.get("text"))

    def _merge_with_llm(
        self,
        fragments: List[Dict[str, str]],
        game_state: Optional[Any],
        context: str,
        truth_anchor: Dict[str, Any],
    ) -> str:
        payload = {
            "turn_count": getattr(game_state, "turn_count", 0) if game_state else 0,
            "current_scene_id": getattr(game_state, "current_scene_id", "") if game_state else "",
            "fragments": fragments,
            "context": context,
            "truth_anchor": truth_anchor,
        }

        prompt = (
            f"{self.system_prompt}\n\n"
            "## 合并输入(JSON)\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )
        response = self.llm_service.call_llm(prompt)
        if not response.get("success"):
            return ""
        return str(response.get("content", "")).strip()

    def merge_v2(
        self,
        turn_trace_steps: List[TurnStep],
        turn_truth_anchor: Optional[Dict[str, Any]] = None,
        narrative_memory: Optional[NarrativeMemoryView] = None,
    ) -> NarrativeMergerOutputV2:
        """Phase 6 merger API, returns structured output while reusing legacy merger behavior."""
        input_v2 = NarrativeMergerInputV2(
            turn_trace_steps=turn_trace_steps or [],
            turn_truth_anchor=turn_truth_anchor or {},
            narrative_memory=narrative_memory or NarrativeMemoryView(),
        )

        fragments: List[Dict[str, str]] = []
        for step in input_v2.turn_trace_steps:
            text = (step.resolution.local_narrative or "").strip()
            if not text:
                continue
            fragments.append(
                {
                    "actor_id": step.actor_id,
                    "actor_name": step.actor_id,
                    "text": text,
                }
            )

        merged = self.merge(
            fragments=fragments,
            game_state=None,
            context="\n".join(input_v2.narrative_memory.summary_lines),
            truth_anchor=input_v2.turn_truth_anchor,
        )

        if not merged:
            merged = "\n".join(fragment.get("text", "") for fragment in fragments if fragment.get("text"))

        new_key_facts: List[str] = []
        for step in input_v2.turn_trace_steps:
            if step.actor_id and step.actor_id not in new_key_facts:
                new_key_facts.append(step.actor_id)

        turn_summary = merged.strip()
        if len(turn_summary) > 200:
            turn_summary = turn_summary[:200].rstrip() + "..."

        return NarrativeMergerOutputV2(
            merged_narrative=merged,
            turn_summary=turn_summary,
            new_key_facts=new_key_facts,
            dialogue_updates=[],
        )

    def _load_default_prompt(self) -> str:
        prompt_path = Path(__file__).parent / "prompt" / "narrative_merger_prompt.md"
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
