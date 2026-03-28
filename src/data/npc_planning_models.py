"""Structured NPC planning models for incremental architecture refactor."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class NPCActionType(str, Enum):
    """Allowed high-level NPC action categories."""

    ATTACK = "attack"
    MOVE = "move"
    TALK = "talk"
    USE_ITEM = "use_item"
    INVESTIGATE = "investigate"
    WAIT = "wait"
    CUSTOM = "custom"


class NPCCheckDifficulty(str, Enum):
    """Difficulty levels for structured NPC checks."""

    REGULAR = "常规"
    HARD = "困难"
    EXTREME = "极难"


class NPCCheckPlan(BaseModel):
    """Structured check requirement attached to an NPC action."""

    check_needed: bool = Field(default=False)
    check_attributes: List[str] = Field(default_factory=list)
    difficulty: NPCCheckDifficulty = Field(default=NPCCheckDifficulty.REGULAR)
    check_target_id: Optional[str] = Field(default=None)


class NPCActionForm(BaseModel):
    """
    Structured NPC action plan.

    This model is additive and does not replace existing DMAgentOutput fields.
    """

    npc_id: str = Field(..., description="NPC actor id")
    action_type: NPCActionType = Field(default=NPCActionType.WAIT)
    target_id: Optional[str] = Field(default=None)
    intent_description: str = Field(default="", description="Natural language intent")
    expected_outcome: Optional[str] = Field(default=None)
    check: NPCCheckPlan = Field(default_factory=NPCCheckPlan)
    trigger_source: str = Field(
        default="",
        description="pipeline trigger source (unified)",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)


class NPCActionDecision(BaseModel):
    """Batch decision result for one planning pass."""

    actions: Dict[str, NPCActionForm] = Field(default_factory=dict)
    rationale: str = Field(default="")


__all__ = [
    "NPCActionType",
    "NPCCheckDifficulty",
    "NPCCheckPlan",
    "NPCActionForm",
    "NPCActionDecision",
]
