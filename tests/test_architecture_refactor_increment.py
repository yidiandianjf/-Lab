import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest

from src.data.npc_planning_models import NPCActionForm, NPCActionType
from src.data.init.world_loader import load_initial_world_bundle
from src.data.models import (
    ActivationHint,
    CheckPlan,
    OutcomeSummary,
    TurnIntent,
    TurnResolution,
    TurnStep,
    TurnTrace,
)
from src.engine.context_builders import (
    DialogueMemoryBuilder,
    NarrativeMemoryBuilder,
    TurnTraceContextBuilder,
    WorldStateViewBuilder,
)
from src.engine.game_engine import GameEngine
from src.narrative import NarrativeContext, NarrativeContextSnapshot, NarrativeEvent
from src.narrative.narrative_merger import NarrativeMerger


class _FakeIO:
    def save_character(self, _):
        return 0

    def save_item(self, _):
        return 0

    def save_map(self, _):
        return 0

    def clear_current_events(self):
        return 0

    def apply_state_change(self, _):
        return 0


class ArchitectureRefactorIncrementTests(unittest.TestCase):
    def test_narrative_context_export_contains_recent_events_and_summary(self):
        context = NarrativeContext(window_size=2)
        context.add_event(NarrativeEvent(turn=1, actor_id="player", text="Open the old door"))
        context.add_event(NarrativeEvent(turn=2, actor_id="guard", text="The guard warns you"))
        context.add_event(NarrativeEvent(turn=3, actor_id="player", text="Search for a clue"))

        exported = context.export_state()

        self.assertEqual(len(exported["recent_events"]), 2)
        self.assertIn("summary", exported)
        self.assertIn("key_facts", exported)

    def test_narrative_snapshot_round_trip_preserves_key_facts(self):
        snapshot = NarrativeContextSnapshot(
            window_size=3,
            recent_events=[
                NarrativeEvent(
                    turn=4,
                    actor_id="npc-1",
                    text="NPC loses SAN and sees blood",
                    key_facts=["san_drop:npc-1:1", "blood_seen"],
                )
            ],
            summary_lines=["[Turn 1] player: Found a clue"],
            key_facts=["san_drop:npc-1:1", "blood_seen"],
        )

        rebuilt = NarrativeContext.from_snapshot(snapshot)

        self.assertEqual(rebuilt.window_size, 3)
        self.assertIn("san_drop:npc-1:1", rebuilt.key_facts)
        self.assertIn("blood_seen", rebuilt.key_facts)

    def test_structured_npc_action_form_uses_nested_check_plan(self):
        action = NPCActionForm(
            npc_id="char-guard-01",
            action_type=NPCActionType.TALK,
            target_id="char-player-01",
            intent_description="Warn the player to be quiet",
        )

        dumped = action.model_dump()

        self.assertEqual(dumped["npc_id"], "char-guard-01")
        self.assertEqual(dumped["action_type"], "talk")
        self.assertIn("check", dumped)
        self.assertFalse(dumped["check"]["check_needed"])

    def test_world_bundle_exposes_narrative_window(self):
        bundle = load_initial_world_bundle(_FakeIO(), player_name="测试者", world_name="mysterious_library")
        self.assertGreaterEqual(bundle.narrative_window, 1)

    def test_engine_restore_narrative_context_keeps_summary_and_facts(self):
        engine = GameEngine(io_system=_FakeIO())

        payload = {
            "window_size": 2,
            "recent_events": [
                {
                    "turn": 3,
                    "actor_id": "char-guard-01",
                    "actor_name": "Guard",
                    "text": "Guard reveals a clue about item-key-01",
                    "source": "npc_queue",
                    "key_facts": ["item-key-01"],
                }
            ],
            "summary_lines": ["[Turn 1] player: Moved to map-room-secret-01"],
            "key_facts": ["map-room-secret-01"],
        }
        engine._restore_narrative_context(payload)

        exported = engine._dump_narrative_context()
        self.assertEqual(exported.get("window_size"), 2)
        self.assertIn("map-room-secret-01", exported.get("key_facts", []))
        self.assertIn("item-key-01", exported.get("key_facts", []))
        self.assertTrue(exported.get("summary_lines"))

    def test_turn_trace_append_and_actor_filter(self):
        intent = TurnIntent(
            actor_id="char-player-01",
            raw_input_text="我查看门锁",
            intent_text="玩家尝试检查门锁状态",
            interaction_type="action",
            check_plan=CheckPlan(check_needed=True, check_type="非对抗鉴定", attributes=["int"]),
            activation_hint=ActivationHint(response_needed_hint=False),
        )
        resolution = TurnResolution(
            actor_id="char-player-01",
            phase="player",
            intent_text="玩家尝试检查门锁状态",
            local_narrative="你看到锁芯有新划痕。",
            outcome=OutcomeSummary(action_succeeded=True, outcome_type="inspect"),
        )
        step = TurnStep(
            step_id="turn-1-step-1",
            turn_id=1,
            actor_id="char-player-01",
            phase="player",
            trigger_source="player_input",
            intent=intent,
            resolution=resolution,
        )

        trace = TurnTrace(turn_id=1)
        trace.append_step(step)

        self.assertEqual(len(trace.steps), 1)
        self.assertEqual(len(trace.get_steps_for_actor("char-player-01")), 1)
        self.assertEqual(len(trace.get_steps_for_actor("char-guard-01")), 0)

    def test_turn_step_model_dump_contains_nested_protocol(self):
        step = TurnStep(
            step_id="turn-2-step-1",
            turn_id=2,
            actor_id="char-guard-01",
            phase="npc",
            trigger_source="reactive",
            intent=TurnIntent(
                actor_id="char-guard-01",
                raw_input_text="玩家询问守卫",
                intent_text="守卫回应玩家询问",
                interaction_type="dialogue",
            ),
            resolution=TurnResolution(
                actor_id="char-guard-01",
                phase="npc",
                intent_text="守卫回应玩家询问",
                local_narrative="守卫压低声音给出线索。",
                outcome=OutcomeSummary(action_succeeded=True, outcome_type="talk"),
            ),
        )

        dumped = step.model_dump()
        self.assertIn("intent", dumped)
        self.assertIn("resolution", dumped)
        self.assertEqual(dumped["phase"], "npc")
        self.assertEqual(dumped["intent"]["interaction_type"], "dialogue")

    def test_world_state_view_builder_builds_actor_scoped_view(self):
        bundle = load_initial_world_bundle(_FakeIO(), player_name="测试者", world_name="mysterious_library")
        player_id = bundle.game_state.player_id
        builder = WorldStateViewBuilder()
        view = builder.build(bundle.game_state, player_id)

        dumped = view.model_dump()
        self.assertIn("current_map", dumped)
        self.assertIn("player_state", dumped)
        self.assertIn("nearby_characters", dumped)

    def test_turn_trace_context_builder_filters_for_npc(self):
        trace = TurnTrace(turn_id=1)
        trace.append_step(
            TurnStep(
                step_id="t1-p",
                turn_id=1,
                actor_id="char-player-01",
                phase="player",
                trigger_source="player_input",
                intent=TurnIntent(actor_id="char-player-01"),
                resolution=TurnResolution(actor_id="char-player-01", phase="player"),
            )
        )
        trace.append_step(
            TurnStep(
                step_id="t1-n1",
                turn_id=1,
                actor_id="char-guard-01",
                phase="npc",
                trigger_source="unified",
                intent=TurnIntent(actor_id="char-guard-01"),
                resolution=TurnResolution(actor_id="char-guard-01", phase="npc"),
            )
        )
        trace.append_step(
            TurnStep(
                step_id="t1-n2",
                turn_id=1,
                actor_id="char-butler-01",
                phase="npc",
                trigger_source="unified",
                intent=TurnIntent(actor_id="char-butler-01"),
                resolution=TurnResolution(actor_id="char-butler-01", phase="npc"),
            )
        )

        builder = TurnTraceContextBuilder()
        view = builder.build_for_npc(trace, "char-guard-01")
        actor_ids = [one.actor_id for one in view.steps]
        self.assertIn("char-player-01", actor_ids)
        self.assertIn("char-guard-01", actor_ids)
        self.assertNotIn("char-butler-01", actor_ids)

    def test_narrative_merger_v2_returns_structured_output(self):
        merger = NarrativeMerger(use_llm=False)
        step = TurnStep(
            step_id="turn-1-player-1",
            turn_id=1,
            actor_id="char-player-01",
            phase="player",
            trigger_source="player_input",
            intent=TurnIntent(actor_id="char-player-01", intent_text="玩家检查房间"),
            resolution=TurnResolution(
                actor_id="char-player-01",
                phase="player",
                local_narrative="你在地板上发现了拖拽痕迹。",
            ),
        )

        output = merger.merge_v2([step], turn_truth_anchor={"action_succeeded": True})
        self.assertTrue(output.merged_narrative)
        self.assertTrue(output.turn_summary)
        self.assertIn("char-player-01", output.new_key_facts)

    def test_dialogue_and_narrative_memory_builder_output(self):
        dialogue_builder = DialogueMemoryBuilder()
        narrative_builder = NarrativeMemoryBuilder()

        dialogue = dialogue_builder.build(
            [
                {"speaker": "player", "content": "你好"},
                {"speaker": "dm", "content": "守卫看向你。"},
            ]
        )
        narrative = narrative_builder.build(
            {
                "summary_lines": ["[Turn 1] 你进入大厅"],
                "key_facts": ["map-hall-01", "char-guard-01"],
            }
        )

        self.assertEqual(len(dialogue.recent_dialogues), 2)
        self.assertIn("map-hall-01", narrative.key_facts)


if __name__ == "__main__":
    unittest.main()
