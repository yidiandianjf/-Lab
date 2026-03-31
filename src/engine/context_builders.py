"""Context builders for Phase 2 protocol migration."""

from __future__ import annotations

from typing import Any, Dict, List

from src.data.models import (
    DialogueMemoryEntry,
    DialogueMemoryView,
    GameState,
    NarrativeMemoryView,
    TurnTrace,
    TurnTraceView,
    WorldStateView,
)


class WorldStateViewBuilder:
    """Build a constrained world view for LLM-facing pipelines."""

    def build(self, game_state: GameState, actor_id: str) -> WorldStateView:
        actor = game_state.characters.get(actor_id)
        if not actor:
            return WorldStateView()

        current_map = game_state.maps.get(actor.location) or game_state.get_current_map()
        nearby_characters: List[Dict[str, Any]] = []
        nearby_items: List[Dict[str, Any]] = []
        exits: List[Dict[str, Any]] = []

        if current_map:
            for one in current_map.neighbors:
                exits.append(
                    {
                        "id": one.id,
                        "map_id": one.id,
                        "direction": one.direction,
                        "description": one.description,
                    }
                )

            for char_id in list(current_map.entities.characters or []):
                char = game_state.characters.get(char_id)
                if not char:
                    continue
                nearby_characters.append(
                    {
                        "id": char.id,
                        "name": char.name,
                        "is_player": char.is_player,
                        "location": char.location,
                        "basic_info": char.basic_info,
                        "description_public": char.description.get_public_text() if char.description else "",
                        "description_hint": char.description.hint if char.description else "",
                        "description": char.description.get_public_text() if char.description else "",
                        "hint": char.description.hint if char.description else "",
                    }
                )

            for item_id in list(current_map.entities.items or []):
                item = game_state.items.get(item_id)
                if not item:
                    continue
                nearby_items.append(
                    {
                        "id": item.id,
                        "name": item.name,
                        "location": item.location,
                        "is_portable": item.is_portable,
                        "description_public": item.description.get_public_text() if item.description else "",
                        "description_hint": item.description.hint if item.description else "",
                        "description": item.description.get_public_text() if item.description else "",
                        "hint": item.description.hint if item.description else "",
                    }
                )

        return WorldStateView(
            current_map={
                "id": current_map.id,
                "name": current_map.name,
                "description_public": current_map.description.get_public_text(),
                "description_hint": current_map.description.hint,
                "description": current_map.description.get_public_text(),
                "hint": current_map.description.hint,
            }
            if current_map
            else None,
            nearby_characters=nearby_characters,
            nearby_items=nearby_items,
            player_state={
                "id": actor.id,
                "name": actor.name,
                "location": actor.location,
                "description_public": actor.description.get_public_text(),
                "description_hint": actor.description.hint,
                "description": actor.description.get_public_text(),
                "hint": actor.description.hint,
                "status": {
                    "hp": actor.status.hp,
                    "max_hp": actor.status.max_hp,
                    "san": actor.status.san,
                    "lucky": actor.status.lucky,
                },
                "attributes": {
                    "str": actor.attributes.str,
                    "con": actor.attributes.con,
                    "siz": actor.attributes.siz,
                    "dex": actor.attributes.dex,
                    "app": actor.attributes.app,
                    "int": actor.attributes.int,
                    "pow": actor.attributes.pow,
                    "edu": actor.attributes.edu,
                },
            },
            available_exits=exits,
        )


class DialogueMemoryBuilder:
    """Build dialogue memory view from dm dialogue log."""

    def build(self, dialogue_log: List[Dict[str, str]]) -> DialogueMemoryView:
        entries: List[DialogueMemoryEntry] = []
        for one in dialogue_log:
            if not isinstance(one, dict):
                continue
            speaker = str(one.get("speaker", "")).strip()
            content = str(one.get("content", "")).strip()
            if content:
                entries.append(DialogueMemoryEntry(speaker=speaker, content=content))
                continue

            legacy_player = str(one.get("player_input", "")).strip()
            legacy_dm = str(one.get("dm_response", "")).strip()
            if legacy_player:
                entries.append(DialogueMemoryEntry(speaker="player", content=legacy_player))
            if legacy_dm:
                entries.append(DialogueMemoryEntry(speaker="narrator", content=legacy_dm))
        return DialogueMemoryView(recent_dialogues=entries[-20:])


class NarrativeMemoryBuilder:
    """Build narrative memory view from narrative context export payload."""

    def build(self, narrative_payload: Dict[str, Any]) -> NarrativeMemoryView:
        if not isinstance(narrative_payload, dict):
            return NarrativeMemoryView()
        summary_lines = narrative_payload.get("summary_lines", [])
        key_facts = narrative_payload.get("key_facts", [])
        if not isinstance(summary_lines, list):
            summary_lines = []
        if not isinstance(key_facts, list):
            key_facts = []
        return NarrativeMemoryView(
            summary_lines=[str(one) for one in summary_lines if str(one).strip()],
            key_facts=[str(one) for one in key_facts if str(one).strip()],
            stable_facts=[str(one) for one in key_facts if str(one).strip()],
        )


class TurnTraceContextBuilder:
    """Build actor-scoped turn trace views."""

    def build_for_npc(self, turn_trace: TurnTrace, npc_id: str) -> TurnTraceView:
        if not isinstance(turn_trace, TurnTrace):
            return TurnTraceView()
        visible = [step for step in turn_trace.steps if step.actor_id == npc_id or step.phase == "player"]
        return TurnTraceView(turn_id=turn_trace.turn_id, steps=visible)

    def build_full(self, turn_trace: TurnTrace) -> TurnTraceView:
        if not isinstance(turn_trace, TurnTrace):
            return TurnTraceView()
        return TurnTraceView(turn_id=turn_trace.turn_id, steps=list(turn_trace.steps))
