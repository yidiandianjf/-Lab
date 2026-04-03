"""Prompt loader for NPC director."""

from pathlib import Path

NPC_DIRECTOR_PROMPT = Path(__file__).parent / "prompt" / "npc_director_prompt.md"


def load_npc_director_prompt() -> str:
    with open(NPC_DIRECTOR_PROMPT, "r", encoding="utf-8") as f:
        return f.read()
