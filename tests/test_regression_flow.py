import unittest
import os
import tempfile
import json
from pathlib import Path

from src.data.io_system import (
    ERROR_SUCCESS,
    ERROR_ID_NOT_FOUND,
    ERROR_OPERATION_INVALID,
    ERROR_OTHER,
    IOSystem,
)
from src.data.init.world_loader import load_initial_world_bundle
from src.data.models import (
    DMAgentOutput,
    StateEvolutionOutput,
    GameState,
    StateChange,
    ChangeOperation,
    Character,
    Item,
    MapNeighbor,
    Map,
)
from src.agent.input_system import InputSystem, InputType
from src.agent.state_evolution import StateEvolution
from src.cli.game_cli import DisplayManager
from src.engine.game_engine import GameEngine
from src.utils.consistency_checker import ConsistencyChecker


class FakeIO:
    """Minimal IO stub that avoids database-backed I/O in tests."""

    def save_character(self, _):
        return ERROR_SUCCESS

    def save_item(self, _):
        return ERROR_SUCCESS

    def save_map(self, _):
        return ERROR_SUCCESS

    def clear_current_events(self):
        return ERROR_SUCCESS

    def apply_state_change(self, _):
        return ERROR_SUCCESS


class FailingIO(FakeIO):
    def __init__(self, fail_on_entity_id=None, fail_on_field=None, fail_code=ERROR_ID_NOT_FOUND):
        self.fail_on_entity_id = fail_on_entity_id
        self.fail_on_field = fail_on_field
        self.fail_code = fail_code

    def apply_state_change(self, change):
        if (
            self.fail_on_entity_id is not None
            and change.id == self.fail_on_entity_id
            and (self.fail_on_field is None or change.field == self.fail_on_field)
        ):
            return self.fail_code
        return ERROR_SUCCESS


class TransactionalFailingIO(IOSystem):
    def __init__(self, db_path):
        super().__init__(db_path=db_path, mode="sqlite")

    def apply_state_change(self, change):
        if change.id == "bad-entity":
            return ERROR_ID_NOT_FOUND
        return super().apply_state_change(change)


class SaveFailingIO(IOSystem):
    def __init__(self, db_path, fail_map_id):
        super().__init__(db_path=db_path, mode="sqlite")
        self.fail_map_id = fail_map_id

    def save_map(self, map_obj):
        if map_obj.id == self.fail_map_id:
            return ERROR_OTHER
        return super().save_map(map_obj)


class DummyRuleSystem:
    def __init__(self):
        self.calls = 0

    def execute_check(self, check_input, game_state):
        self.calls += 1
        from src.data.models import CheckOutput, CheckResult
        return CheckOutput(
            result=CheckResult.SUCCESS,
            dice_roll=30,
            target_value=50,
            actor_value=50,
            detail="NPC妫€瀹氭垚鍔" ,
        )


class DummyDMAgent:
    def parse_intent(self, player_input: str, game_state: GameState, additional_context=None):
        return DMAgentOutput(
            is_dialogue=False,
            response_to_player="",
            needs_check=False,
            check_type=None,
            check_attributes=[],
            check_target=None,
            difficulty="甯歌",
            action_description=player_input,
        )


class DummyStateAgent:
    def __init__(self):
        self.end_condition = ""

    def evolve_player_action(self, check_result, action_description, game_state, additional_context=None):
        return StateEvolutionOutput(
            narrative="浣犺皟鏁翠簡鍛煎惛锛岀煭鏆傝瀵熷洓鍛ㄣ€" ,
            changes=[],
            resolved=True,
            next_action_hint=None,
            is_end=False,
            end_narrative="",
        )

    def check_end_condition(self, game_state):
        return None


class AliasIdStateAgent:
    def __init__(self):
        self.end_condition = ""

    def evolve_player_action(self, check_result, action_description, game_state, additional_context=None):
        return StateEvolutionOutput(
            narrative="浣犳嬁璧蜂簡鐓ゆ补鐏€" ,
            changes=[
                StateChange(
                    id="player_001",
                    field="inventory",
                    operation=ChangeOperation.UPDATE,
                    value=["item-lantern-01"],
                )
            ],
            resolved=True,
            next_action_hint=None,
            is_end=False,
            end_narrative="",
        )

    def check_end_condition(self, game_state):
        return None


class AiEndReviewStateAgent(DummyStateAgent):
    def check_end_condition(self, game_state):
        return StateEvolutionOutput(
            narrative="",
            changes=[],
            resolved=True,
            next_action_hint=None,
            is_end=True,
            end_narrative="浣犵殑瑙嗛噹琚棤灏介粦鏆楀悶娌★紝鏁呬簨鍒版缁撴潫銆" ,
        )


class NpcCapableStateAgent(DummyStateAgent):
    def __init__(self):
        super().__init__()
        self.npc_calls = 0

    def evolve_npc_action(self, npc_id, game_state, check_result=None, npc_intent=None, additional_context=None):
        self.npc_calls += 1
        self.last_check_result = check_result
        return StateEvolutionOutput(
            narrative="瀹堝崼浣庡０鎻愰啋浣犱繚鎸佸畨闈欍€" ,
            changes=[
                StateChange(
                    id="char-player-01",
                    field="status.san",
                    operation=ChangeOperation.UPDATE,
                    value=59,
                )
            ],
            resolved=True,
            next_action_hint=None,
            is_end=False,
            end_narrative="",
        )


class ReactiveDMAgent(DummyDMAgent):
    def parse_intent(self, player_input: str, game_state: GameState, additional_context=None):
        return DMAgentOutput(
            is_dialogue=False,
            response_to_player="",
            needs_check=False,
            check_type=None,
            check_attributes=[],
            check_target=None,
            difficulty="甯歌",
            action_description=player_input,
            npc_response_needed=True,
            npc_actor_id="char-guard-01",
            npc_intent="瀵圭帺瀹跺垰鎵嶇殑琛屽姩鍋氬嚭璀﹀憡",
        )


class ReactiveNoNpcDMAgent(DummyDMAgent):
    def parse_intent(self, player_input: str, game_state: GameState, additional_context=None):
        return DMAgentOutput(
            is_dialogue=False,
            response_to_player="",
            needs_check=False,
            check_type=None,
            check_attributes=[],
            check_target=None,
            difficulty="甯歌",
            action_description=player_input,
            npc_response_needed=False,
            npc_actor_id=None,
            npc_intent=None,
        )


class DialogueDMAgent(DummyDMAgent):
    def __init__(self, npc_response_needed: bool):
        self._npc_response_needed = npc_response_needed

    def parse_intent(self, player_input: str, game_state: GameState, additional_context=None):
        return DMAgentOutput(
            is_dialogue=True,
            response_to_player="瀹堝崼浣庡０鍥炲簲浜嗕綘銆" ,
            needs_check=False,
            check_type=None,
            check_attributes=[],
            check_target=None,
            difficulty="甯歌",
            action_description=player_input,
            npc_response_needed=self._npc_response_needed,
            npc_actor_id="char-guard-01" if self._npc_response_needed else None,
            npc_intent="瀹堝崼鍥炲簲鐜╁鐨勫璇" if self._npc_response_needed else None,
        )


class TriggerAwareStateAgent(DummyStateAgent):
    def __init__(self):
        super().__init__()
        self.npc_calls = 0
        self.triggers = []

    def evolve_npc_action(self, npc_id, game_state, check_result=None, npc_intent=None, additional_context=None):
        self.npc_calls += 1
        trigger = None
        if additional_context:
            trigger = additional_context.get("trigger")
        self.triggers.append(trigger)
        return StateEvolutionOutput(
            narrative="瀹堝崼瑙傚療鐫€浣犵殑涓惧姩銆" ,
            changes=[],
            resolved=True,
            next_action_hint=None,
            is_end=False,
            end_narrative="",
        )


class AddDescriptionStateAgent(DummyStateAgent):
    def evolve_player_action(self, check_result, action_description, game_state, additional_context=None):
        return StateEvolutionOutput(
            narrative="浣犲湪澧欎笂鍙戠幇浜嗘柊鐨勫埢鐥曘€" ,
            changes=[
                StateChange(
                    id="map-room-library-01",
                    field="description.public",
                    operation=ChangeOperation.ADD,
                    value={"description": "澧欓潰涓婂浜嗕竴琛屾疆婀跨殑鍒掔棔"},
                )
            ],
            resolved=True,
            next_action_hint=None,
            is_end=False,
            end_narrative="",
        )


class FailingChangeStateAgent(DummyStateAgent):
    def evolve_player_action(self, check_result, action_description, game_state, additional_context=None):
        return StateEvolutionOutput(
            narrative="浣犺瘯鍥捐皟鏁存埧闂撮噷鐨勯檲璁俱€" ,
            changes=[
                StateChange(
                    id="char-player-01",
                    field="status.san",
                    operation=ChangeOperation.UPDATE,
                    value=58,
                ),
                StateChange(
                    id="bad-entity",
                    field="status.hp",
                    operation=ChangeOperation.UPDATE,
                    value=5,
                ),
            ],
            resolved=True,
            next_action_hint=None,
            is_end=False,
            end_narrative="",
        )


class RegressionFlowTests(unittest.TestCase):
    def test_world_bundle_loader_with_split_files(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")
        world_manifest_path = Path("config/world/mysterious_library/world.json")
        with open(world_manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        self.assertEqual(bundle.world_name, "mysterious_library")
        self.assertTrue(bundle.end_condition)
        self.assertEqual(bundle.npc_response_mode, manifest.get("npc_response_mode", "queue"))
        self.assertEqual(bundle.npc_director_use_llm, manifest.get("npc_director_use_llm", True))
        self.assertEqual(bundle.narrative_merge_use_llm, manifest.get("narrative_merge_use_llm", True))
        self.assertIn("char-player-01", bundle.game_state.characters)
        self.assertIn("map-room-library-01", bundle.game_state.maps)

    def test_apply_world_settings_can_override_npc_mode(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")

        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=DummyDMAgent(),
            state_agent=DummyStateAgent(),
            npc_response_mode="queue",
        )

        engine.apply_world_settings(
            world_name=bundle.world_name,
            end_condition=bundle.end_condition,
            npc_response_mode="reactive",
        )
        self.assertEqual(engine._npc_response_mode, "reactive")

    def test_apply_world_settings_can_override_llm_switches(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")

        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=DummyDMAgent(),
            state_agent=DummyStateAgent(),
        )

        engine.apply_world_settings(
            world_name=bundle.world_name,
            end_condition=bundle.end_condition,
            npc_director_use_llm=False,
            narrative_merge_use_llm=False,
        )

        self.assertFalse(engine._npc_director_use_llm)
        self.assertFalse(engine._narrative_merge_use_llm)

    def test_plan_npc_actions_passes_narrative_context(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")
        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=DummyDMAgent(),
            state_agent=DummyStateAgent(),
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(bundle.world_name, bundle.end_condition)

        class _CaptureDirector:
            def __init__(self):
                self.last_context = None

            def decide_actions(self, npc_ids, game_state, player_intent=None, trigger_source="unified", recent_events=None, narrative_context=""):
                from src.data.npc_planning_models import NPCActionDecision, NPCActionForm, NPCActionType
                self.last_context = narrative_context
                return NPCActionDecision(
                    actions={
                        npc_ids[0]: NPCActionForm(
                            npc_id=npc_ids[0],
                            action_type=NPCActionType.WAIT,
                            intent_description="绛夊緟",
                            trigger_source=trigger_source,
                        )
                    },
                    rationale="capture",
                )

        capture = _CaptureDirector()
        engine.npc_director = capture

        plans = engine._plan_npc_actions(trigger="unified", candidate_npc_ids=["char-guard-01"])
        self.assertIn("char-guard-01", plans)
        self.assertIsNotNone(capture.last_context)

    def test_plan_npc_actions_passes_player_resolution_anchor(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")
        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=DummyDMAgent(),
            state_agent=DummyStateAgent(),
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(bundle.world_name, bundle.end_condition)

        class _CaptureDirector:
            def __init__(self):
                self.last_context = None

            def decide_actions(self, npc_ids, game_state, player_intent=None, trigger_source="unified", recent_events=None, narrative_context=""):
                from src.data.npc_planning_models import NPCActionDecision, NPCActionForm, NPCActionType
                self.last_context = narrative_context
                return NPCActionDecision(
                    actions={
                        npc_ids[0]: NPCActionForm(
                            npc_id=npc_ids[0],
                            action_type=NPCActionType.WAIT,
                            intent_description="绛夊緟",
                            trigger_source=trigger_source,
                        )
                    },
                    rationale="capture",
                )

        capture = _CaptureDirector()
        engine.npc_director = capture

        plans = engine._plan_npc_actions(
            trigger="unified",
            candidate_npc_ids=["char-guard-01"],
            player_resolution_anchor={"action_succeeded": True, "check_outcome": "鎴愬姛"},
        )

        self.assertIn("char-guard-01", plans)
        self.assertIn("PlayerResolutionAnchor", capture.last_context or "")

    def test_add_entities_items_with_list_value_is_flattened(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")
        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=DummyDMAgent(),
            state_agent=DummyStateAgent(),
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(bundle.world_name, bundle.end_condition)

        engine._apply_changes(
            [
                StateChange(
                    id="map-room-library-01",
                    field="entities.items",
                    operation=ChangeOperation.ADD,
                    value=["item-book-01", "item-lantern-01"],
                )
            ]
        )

        current_map = engine.game_state.maps["map-room-library-01"]
        self.assertTrue(all(isinstance(x, str) for x in current_map.entities.items))

        # 浠ュ墠浼氬洜宓屽list瀵艰嚧 unhashable type: 'list'
        context = engine._build_game_context()
        self.assertIn("nearby_items", context)

    def test_config_ending_is_evaluated(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")

        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=DummyDMAgent(),
            state_agent=DummyStateAgent(),
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(bundle.world_name, bundle.end_condition)

        # 寮哄埗瑙﹀彂 death ending
        player = engine.game_state.get_player()
        self.assertIsNotNone(player)
        player.status.hp = 0

        result = engine.process_input("鎴戜粈涔堜篃涓嶅仛")
        self.assertTrue(result["game_over"])
        self.assertIn("图书馆重新归于沉寂", result.get("narrative") or "")

    def test_alias_player_id_change_is_normalized(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")

        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=DummyDMAgent(),
            state_agent=AliasIdStateAgent(),
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(bundle.world_name, bundle.end_condition)

        result = engine.process_input("鎷胯捣鐓ゆ补鐏?")
        self.assertTrue(result["success"])

        player = engine.game_state.get_player()
        self.assertIsNotNone(player)
        self.assertIn("item-lantern-01", player.inventory)

    def test_slash_help_is_treated_as_command(self):
        parser = InputSystem(FakeIO())
        parsed = parser.parse_input("/help")
        self.assertEqual(parsed.input_type, InputType.BASIC_COMMAND)
        self.assertEqual(parsed.command, "help")

    def test_ai_end_review_is_used_before_code_fallback(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")

        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=DummyDMAgent(),
            state_agent=AiEndReviewStateAgent(),
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(bundle.world_name, bundle.end_condition)

        result = engine.process_input("鎴戝仠涓嬭剼姝?")
        self.assertTrue(result["game_over"])
        self.assertIn("鏁呬簨鍒版缁撴潫", result.get("narrative") or "")

    def test_dynamic_action_queue_removes_unavailable_actor(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")

        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=DummyDMAgent(),
            state_agent=DummyStateAgent(),
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(bundle.world_name, bundle.end_condition)

        guard = engine.game_state.characters.get("char-guard-01")
        self.assertIsNotNone(guard)
        guard.status.hp = 0

        player = engine.game_state.get_player()
        self.assertIsNotNone(player)
        player.status.hp = 10

        queue = engine._build_dynamic_action_queue()
        self.assertNotIn("char-guard-01", queue)
        self.assertIn("char-player-01", queue)

    def test_npc_participates_and_applies_changes_before_player_turn(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")

        state_agent = NpcCapableStateAgent()
        rule_system = DummyRuleSystem()
        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=DummyDMAgent(),
            state_agent=state_agent,
            rule_system=rule_system,
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(bundle.world_name, bundle.end_condition)

        engine._action_queue = ["char-guard-01", "char-player-01"]
        result = engine.process_input("缁х画鍓嶈繘")

        self.assertTrue(result["success"])
        self.assertGreaterEqual(state_agent.npc_calls, 1)
        self.assertIsNotNone(state_agent.last_check_result)
        self.assertEqual(rule_system.calls, 1)
        self.assertTrue((result.get("narrative") or "").strip())

        player = engine.game_state.get_player()
        self.assertIsNotNone(player)
        self.assertEqual(player.status.san, 59)

    def test_add_operation_keeps_description_public_as_list(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")

        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=DummyDMAgent(),
            state_agent=AddDescriptionStateAgent(),
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(bundle.world_name, bundle.end_condition)

        result = engine.process_input("瑙傚療澧欓潰")
        self.assertTrue(result["success"])

        current_map = engine.game_state.get_current_map()
        self.assertIsNotNone(current_map)
        self.assertIsInstance(current_map.description.public, list)
        self.assertTrue(current_map.description.get_public_text())

    def test_dirty_snapshot_restore_coerces_description_and_entity_lists(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")

        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=DummyDMAgent(),
            state_agent=DummyStateAgent(),
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(bundle.world_name, bundle.end_condition)

        snapshot = {"game_state": bundle.game_state.model_dump()}
        snapshot["game_state"]["characters"]["char-guard-01"]["description"]["public"] = {
            "description": "脏快照公开描述"
        }
        snapshot["game_state"]["maps"]["map-room-library-01"]["entities"]["characters"] = [
            "char-guard-01",
            ["char-player-01"],
        ]

        engine._restore_transaction_snapshot(snapshot)

        guard = engine.game_state.characters["char-guard-01"]
        self.assertIsInstance(guard.description.public, list)
        self.assertEqual(guard.description.get_public_text(), "脏快照公开描述")

        current_map = engine.game_state.maps["map-room-library-01"]
        self.assertEqual(current_map.entities.characters, ["char-guard-01", "char-player-01"])

    def test_state_evolution_rejects_unknown_field_path(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")
        evolution = StateEvolution(llm_service=object(), system_prompt="test", end_condition="")

        errors = evolution.validate_changes(
            [
                StateChange(
                    id="map-room-library-01",
                    field="environment.hazard",
                    operation=ChangeOperation.UPDATE,
                    value="heavy_fog",
                )
            ],
            bundle.game_state,
        )

        self.assertTrue(any("字段路径不存在" in error for error in errors))

    def test_cli_print_scene_handles_legacy_dict_neighbors(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")
        display = DisplayManager()
        game_state = bundle.game_state
        current_map = game_state.get_current_map()
        self.assertIsNotNone(current_map)

        current_map.__dict__["neighbors"] = [
            {"id": "map-room-corridor-01", "direction": "北", "description": "通往走廊的木门"}
        ]

        from io import StringIO
        import contextlib

        buffer = StringIO()
        with contextlib.redirect_stdout(buffer):
            display.print_scene(game_state)

        output = buffer.getvalue()
        self.assertIn("可通往", output)
        self.assertIn("北", output)
        self.assertIn("通往走廊的木门", output)

    def test_sync_state_change_normalizes_neighbor_dicts(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")
        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=DummyDMAgent(),
            state_agent=DummyStateAgent(),
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(bundle.world_name, bundle.end_condition)

        engine._sync_state_change(
            StateChange(
                id="map-room-library-01",
                field="neighbors",
                operation=ChangeOperation.ADD,
                value={"id": "map-room-secret-01", "direction": "西", "description": "通往密室"},
            )
        )

        current_map = engine.game_state.maps["map-room-library-01"]
        self.assertTrue(all(isinstance(neighbor, MapNeighbor) for neighbor in current_map.neighbors))
        self.assertTrue(any(neighbor.direction == "西" for neighbor in current_map.neighbors))

    def test_io_state_change_normalizes_neighbor_dicts(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            io = IOSystem(db_path=tmp_dir, mode="json")
            map_obj = Map(id="map-01", name="测试地图")
            self.assertEqual(io.save_map(map_obj), ERROR_SUCCESS)

            change = StateChange(
                id="map-01",
                field="neighbors",
                operation=ChangeOperation.ADD,
                value={"id": "map-02", "direction": "北", "description": "通往北侧"},
            )
            self.assertEqual(io.apply_state_change(change), ERROR_SUCCESS)

            reloaded = io.get_map("map-01")
            self.assertIsNotNone(reloaded)
            self.assertTrue(all(isinstance(neighbor, MapNeighbor) for neighbor in reloaded.neighbors))
            self.assertEqual(reloaded.neighbors[0].direction, "北")

    def test_help_command_should_not_trigger_npc_prelude(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")

        state_agent = NpcCapableStateAgent()
        rule_system = DummyRuleSystem()
        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=DummyDMAgent(),
            state_agent=state_agent,
            rule_system=rule_system,
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(bundle.world_name, bundle.end_condition)

        engine._action_queue = ["char-guard-01", "char-player-01"]
        result = engine.process_input("\\help")

        self.assertTrue(result["success"])
        self.assertIn("基础指令列表", result.get("response") or "")
        self.assertEqual(state_agent.npc_calls, 0)
        self.assertEqual(rule_system.calls, 0)

    def test_move_command_updates_player_location(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")

        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=DummyDMAgent(),
            state_agent=DummyStateAgent(),
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(bundle.world_name, bundle.end_condition)

        current_map = engine.game_state.get_current_map()
        self.assertIsNotNone(current_map)
        self.assertTrue(current_map.neighbors)
        target_map_id = current_map.neighbors[0].id

        result = engine.process_input(f"\\move to {target_map_id}")
        self.assertTrue(result["success"])
        self.assertIn("你移动到了", result.get("response") or "")

        player = engine.game_state.get_player()
        self.assertIsNotNone(player)
        self.assertEqual(player.location, target_map_id)
        self.assertEqual(engine.game_state.current_scene_id, target_map_id)

    def test_move_command_supports_to_equals_map_id(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")

        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=DummyDMAgent(),
            state_agent=DummyStateAgent(),
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(bundle.world_name, bundle.end_condition)

        current_map = engine.game_state.get_current_map()
        self.assertIsNotNone(current_map)
        self.assertTrue(current_map.neighbors)
        target_map_id = current_map.neighbors[0].id

        result = engine.process_input(f"\\move to={target_map_id}")
        self.assertTrue(result["success"])

        player = engine.game_state.get_player()
        self.assertIsNotNone(player)
        self.assertEqual(player.location, target_map_id)

    def test_io_rejects_invalid_inventory_item_id(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            io = IOSystem(db_path=tmp_dir, mode="json")

            player = Character(id="char-player-01", name="娴嬭瘯鑰" , is_player=True)
            valid_item = Item(id="item-key-01", name="閽ュ寵")
            self.assertEqual(io.save_character(player), ERROR_SUCCESS)
            self.assertEqual(io.save_item(valid_item), ERROR_SUCCESS)

            ok_change = StateChange(
                id="char-player-01",
                field="inventory",
                operation=ChangeOperation.ADD,
                value="item-key-01",
            )
            self.assertEqual(io.apply_state_change(ok_change), ERROR_SUCCESS)

            bad_change = StateChange(
                id="char-player-01",
                field="inventory",
                operation=ChangeOperation.ADD,
                value="item-not-exist-01",
            )
            self.assertEqual(io.apply_state_change(bad_change), ERROR_ID_NOT_FOUND)

            reloaded_player = io.get_character("char-player-01")
            self.assertIsNotNone(reloaded_player)
            self.assertEqual(reloaded_player.inventory, ["item-key-01"])

    def test_item_location_update_syncs_inventory_and_map(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            io = IOSystem(db_path=tmp_dir, mode="json")

            player = Character(id="char-player-01", name="娴嬭瘯鑰" , is_player=True)
            room = Map(id="map-room-01", name="鎴块棿")
            item = Item(id="item-key-01", name="閽ュ寵", location="map-room-01")
            room.entities.items.append("item-key-01")

            self.assertEqual(io.save_character(player), ERROR_SUCCESS)
            self.assertEqual(io.save_map(room), ERROR_SUCCESS)
            self.assertEqual(io.save_item(item), ERROR_SUCCESS)

            change = StateChange(
                id="item-key-01",
                field="location",
                operation=ChangeOperation.UPDATE,
                value="char-player-01",
            )
            self.assertEqual(io.apply_state_change(change), ERROR_SUCCESS)

            reloaded_player = io.get_character("char-player-01")
            reloaded_item = io.get_item("item-key-01")
            reloaded_room = io.get_map("map-room-01")
            self.assertIsNotNone(reloaded_player)
            self.assertIsNotNone(reloaded_item)
            self.assertIsNotNone(reloaded_room)
            self.assertEqual(reloaded_item.location, "char-player-01")
            self.assertIn("item-key-01", reloaded_player.inventory)
            self.assertNotIn("item-key-01", reloaded_room.entities.items)

            checker = ConsistencyChecker()
            issues = checker.check_item_relationships(reloaded_item, [reloaded_player], [reloaded_room])
            self.assertEqual(issues, [])

    def test_inventory_update_syncs_item_location(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            io = IOSystem(db_path=tmp_dir, mode="json")

            player = Character(id="char-player-01", name="娴嬭瘯鑰" , is_player=True, inventory=["item-key-01"])
            room = Map(id="map-room-01", name="鎴块棿")
            item = Item(id="item-key-01", name="閽ュ寵", location="char-player-01")

            self.assertEqual(io.save_character(player), ERROR_SUCCESS)
            self.assertEqual(io.save_map(room), ERROR_SUCCESS)
            self.assertEqual(io.save_item(item), ERROR_SUCCESS)

            change = StateChange(
                id="char-player-01",
                field="inventory",
                operation=ChangeOperation.UPDATE,
                value=[],
            )
            self.assertEqual(io.apply_state_change(change), ERROR_SUCCESS)

            reloaded_player = io.get_character("char-player-01")
            reloaded_item = io.get_item("item-key-01")
            self.assertIsNotNone(reloaded_player)
            self.assertIsNotNone(reloaded_item)
            self.assertEqual(reloaded_player.inventory, [])
            self.assertEqual(reloaded_item.location, "")

    def test_save_and_load_restore_world_metadata(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")
        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=DummyDMAgent(),
            state_agent=DummyStateAgent(),
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(
            world_name=bundle.world_name,
            end_condition=bundle.end_condition,
            npc_response_mode="reactive",
            narrative_window=3,
            npc_director_use_llm=False,
            narrative_merge_use_llm=False,
        )
        engine._record_dm_dialogue("test", "dialogue")
        engine._append_narrative_event(
            actor_id="char-player-01",
            actor_name="娴嬭瘯鑰" ,
            text="鏃ц蹇" ,
            source="test",
        )

        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                os.chdir(tmp_dir)
                self.assertTrue(engine.save_game("metadata_roundtrip"))

                engine.world_name = "wrong_world"
                engine.end_condition = "wrong_condition"
                engine.set_npc_response_mode("queue")
                engine._set_narrative_window(1)
                engine._npc_director_use_llm = True
                engine._narrative_merge_use_llm = True

                self.assertTrue(engine.load_game("metadata_roundtrip"))

                self.assertEqual(engine.world_name, bundle.world_name)
                self.assertEqual(engine.end_condition, bundle.end_condition)
                self.assertEqual(engine._npc_response_mode, "reactive")
                self.assertEqual(getattr(engine.narrative_context, "window_size", None), 3)
                self.assertFalse(engine._npc_director_use_llm)
                self.assertFalse(engine._narrative_merge_use_llm)
                self.assertTrue(engine.dm_dialogue_log)
            finally:
                os.chdir(original_cwd)

    def test_move_command_rejects_non_neighbor(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")

        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=DummyDMAgent(),
            state_agent=DummyStateAgent(),
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(bundle.world_name, bundle.end_condition)

        result = engine.process_input("\\move to map-room-secret-01")
        self.assertTrue(result["success"])
        self.assertIn("无法移动到目标", result.get("response") or "")

    def test_reactive_mode_triggers_dm_driven_npc_response(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")

        state_agent = NpcCapableStateAgent()
        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=ReactiveDMAgent(),
            state_agent=state_agent,
            npc_response_mode="reactive",
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(bundle.world_name, bundle.end_condition)

        result = engine.process_input("鎴戦潬杩戝畧鍗?")
        self.assertTrue(result["success"])
        self.assertTrue((result.get("narrative") or "").strip())
        self.assertGreaterEqual(state_agent.npc_calls, 1)

    def test_reactive_mode_skips_queue_prelude_when_npc_first(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")

        state_agent = TriggerAwareStateAgent()
        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=ReactiveNoNpcDMAgent(),
            state_agent=state_agent,
            npc_response_mode="reactive",
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(bundle.world_name, bundle.end_condition)

        engine._action_queue = ["char-guard-01", "char-player-01"]
        result = engine.process_input("鎴戞鏌ラ棬閿?")

        self.assertTrue(result["success"])
        self.assertEqual(state_agent.npc_calls, 0)

    def test_queue_mode_marks_npc_trigger_as_queue(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")

        state_agent = TriggerAwareStateAgent()
        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=DummyDMAgent(),
            state_agent=state_agent,
            npc_response_mode="queue",
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(bundle.world_name, bundle.end_condition)

        engine._action_queue = ["char-guard-01", "char-player-01"]
        result = engine.process_input("鎴戣瀵熷畧鍗?")

        self.assertTrue(result["success"])
        self.assertGreaterEqual(state_agent.npc_calls, 1)
        self.assertIn("queue", state_agent.triggers)

    def test_reactive_mode_marks_npc_trigger_as_reactive(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")

        state_agent = TriggerAwareStateAgent()
        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=ReactiveDMAgent(),
            state_agent=state_agent,
            npc_response_mode="reactive",
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(bundle.world_name, bundle.end_condition)

        result = engine.process_input("鎴戦潬杩戝畧鍗?")

        self.assertTrue(result["success"])
        self.assertGreaterEqual(state_agent.npc_calls, 1)
        self.assertIn("reactive", state_agent.triggers)

    def test_dialogue_can_still_trigger_npc_response(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")

        state_agent = NpcCapableStateAgent()
        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=DialogueDMAgent(npc_response_needed=True),
            state_agent=state_agent,
            npc_response_mode="reactive",
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(bundle.world_name, bundle.end_condition)

        start_turn = engine.game_state.turn_count
        result = engine.process_input("鍜屽畧鍗璇?")

        self.assertTrue(result["success"])
        self.assertEqual(result.get("response"), "瀹堝崼浣庡０鍥炲簲浜嗕綘銆")
        self.assertGreaterEqual(state_agent.npc_calls, 1)
        self.assertGreater(engine.game_state.turn_count, start_turn)
        self.assertTrue((result.get("narrative") or "").strip())

    def test_dialogue_without_npc_response_still_returns_early(self):
        bundle = load_initial_world_bundle(FakeIO(), player_name="娴嬭瘯鑰?", world_name="mysterious_library")

        state_agent = NpcCapableStateAgent()
        engine = GameEngine(
            io_system=FakeIO(),
            dm_agent=DialogueDMAgent(npc_response_needed=False),
            state_agent=state_agent,
            npc_response_mode="reactive",
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(bundle.world_name, bundle.end_condition)

        start_turn = engine.game_state.turn_count
        result = engine.process_input("鍜屽畧鍗棽鑱?")

        self.assertTrue(result["success"])
        self.assertEqual(result.get("response"), "瀹堝崼浣庡０鍥炲簲浜嗕綘銆")
        self.assertEqual(state_agent.npc_calls, 0)
        self.assertEqual(engine.game_state.turn_count, start_turn)

    def test_change_failure_aborts_turn_and_reports_error(self):
        bundle = load_initial_world_bundle(FailingIO(fail_on_entity_id="bad-entity"), player_name="娴嬭瘯鑰?", world_name="mysterious_library")

        engine = GameEngine(
            io_system=FailingIO(fail_on_entity_id="bad-entity"),
            dm_agent=DummyDMAgent(),
            state_agent=FailingChangeStateAgent(),
        )
        engine.game_state = bundle.game_state
        engine.apply_world_settings(bundle.world_name, bundle.end_condition)

        start_turn = engine.game_state.turn_count
        result = engine.process_input("鏌ョ湅鎴块棿")

        self.assertFalse(result["success"])
        self.assertIn("状态变更失败", result.get("response") or "")
        self.assertEqual(engine.game_state.turn_count, start_turn)



    def test_change_failure_rolls_back_memory_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            io = TransactionalFailingIO(db_path=str(Path(tmpdir) / "game.db"))
            bundle = load_initial_world_bundle(io, player_name="娴嬭瘯鑰?", world_name="mysterious_library")

            engine = GameEngine(
                io_system=io,
                dm_agent=DummyDMAgent(),
                state_agent=FailingChangeStateAgent(),
            )
            engine.game_state = bundle.game_state
            engine.apply_world_settings(bundle.world_name, bundle.end_condition)

            player_id = engine.game_state.player_id
            self.assertIsNotNone(player_id)
            original_player = io.get_character(player_id)
            self.assertIsNotNone(original_player)
            original_hp = original_player.status.hp

            result = engine.process_input("鏌ョ湅鎴块棿")

            self.assertFalse(result["success"])
            self.assertEqual(engine.game_state.get_player().status.hp, original_hp)

            persisted_player = io.get_character(player_id)
            self.assertIsNotNone(persisted_player)
            self.assertEqual(persisted_player.status.hp, original_hp)
            self.assertEqual(engine.game_state.turn_count, bundle.game_state.turn_count)
            if hasattr(io, "_session") and io._session is not None:
                io._session.close()
            if hasattr(io, "engine"):
                io.engine.dispose()

    def test_save_game_state_returns_failure_when_entity_save_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            seed_io = IOSystem(db_path=str(Path(tmpdir) / "seed.db"), mode="sqlite")
            bundle = load_initial_world_bundle(seed_io, player_name="测试者", world_name="mysterious_library")

            fail_map_id = next(iter(bundle.game_state.maps.keys()))
            io = SaveFailingIO(db_path=str(Path(tmpdir) / "save_fail.db"), fail_map_id=fail_map_id)
            result = io.save_game_state(bundle.game_state)

            self.assertEqual(result, ERROR_OTHER)

            if hasattr(seed_io, "_session") and seed_io._session is not None:
                seed_io._session.close()
            if hasattr(seed_io, "engine"):
                seed_io.engine.dispose()
            if hasattr(io, "_session") and io._session is not None:
                io._session.close()
            if hasattr(io, "engine"):
                io.engine.dispose()

    def test_clear_runtime_store_removes_loaded_world_entities(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            io = IOSystem(db_path=str(Path(tmpdir) / "game.db"), mode="sqlite")
            bundle = load_initial_world_bundle(io, player_name="测试者", world_name="mysterious_library")

            player_id = bundle.game_state.player_id
            self.assertIsNotNone(io.get_character(player_id))
            self.assertGreater(len(bundle.game_state.items), 0)
            sample_item_id = next(iter(bundle.game_state.items.keys()))
            self.assertIsNotNone(io.get_item(sample_item_id))

            result = io.clear_runtime_store()
            self.assertEqual(result, ERROR_SUCCESS)
            self.assertIsNone(io.get_character(player_id))
            self.assertIsNone(io.get_item(sample_item_id))
            self.assertIsNone(io.load_game_state())

            if hasattr(io, "_session") and io._session is not None:
                io._session.close()
            if hasattr(io, "engine"):
                io.engine.dispose()

    def test_delete_scalar_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            io = IOSystem(db_path=str(Path(tmpdir) / "game.db"), mode="sqlite")
            bundle = load_initial_world_bundle(io, player_name="测试者", world_name="mysterious_library")
            player_id = bundle.game_state.player_id

            result = io.apply_state_change(
                StateChange(
                    id=player_id,
                    field="status.hp",
                    operation=ChangeOperation.DELETE,
                    value=1,
                )
            )

            self.assertEqual(result, ERROR_OPERATION_INVALID)

            if hasattr(io, "_session") and io._session is not None:
                io._session.close()
            if hasattr(io, "engine"):
                io.engine.dispose()

if __name__ == "__main__":
    unittest.main()
