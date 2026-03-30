"""Consistency checks for item ownership and placement."""

from __future__ import annotations

from typing import List, Sequence

from src.data.models import Character, Item, Map


class ConsistencyChecker:
    """Validate ownership invariants for items, characters, and maps."""

    def check_item_relationships(
        self,
        item: Item,
        characters: Sequence[Character],
        maps: Sequence[Map],
    ) -> List[str]:
        """Return human-readable issues for an item's holder relationship."""
        issues: List[str] = []
        location = (item.location or "").strip()
        char_holders = [char.id for char in characters if item.id in char.inventory]
        map_holders = [map_obj.id for map_obj in maps if item.id in map_obj.entities.items]

        if location.startswith("char-"):
            if location not in char_holders:
                issues.append(f"item {item.id} not present in holder inventory {location}")
            if map_holders:
                issues.append(f"item {item.id} also present on maps: {map_holders}")
            if len(char_holders) > 1:
                issues.append(f"item {item.id} present in multiple inventories: {char_holders}")
        elif location.startswith("map-"):
            if location not in map_holders:
                issues.append(f"item {item.id} not present in map entities {location}")
            if char_holders:
                issues.append(f"item {item.id} also present in inventories: {char_holders}")
            if len(map_holders) > 1:
                issues.append(f"item {item.id} present in multiple maps: {map_holders}")
        elif location:
            issues.append(f"item {item.id} has unsupported location target: {location}")
            if char_holders or map_holders:
                issues.append(f"item {item.id} still referenced by holders despite invalid location")
        else:
            if char_holders or map_holders:
                issues.append(f"item {item.id} is unassigned but still referenced by holders")

        return issues

    def check_game_state(self, characters: Sequence[Character], maps: Sequence[Map], items: Sequence[Item]) -> List[str]:
        """Check all item ownership relationships in a state snapshot."""
        issues: List[str] = []
        for item in items:
            issues.extend(self.check_item_relationships(item, characters, maps))
        return issues
