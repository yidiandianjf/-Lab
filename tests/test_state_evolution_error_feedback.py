import unittest

from src.agent.state_evolution import StateEvolution
from src.data.models import GameState, Character, CharacterStatus, CharacterAttributes, StateChange, ChangeOperation


class FakeLLMService:
    def __init__(self):
        self.prompts = []
        self.calls = 0

    def call_llm_json(self, prompt, schema, temperature=0.7):
        self.calls += 1
        self.prompts.append(prompt)

        if self.calls == 1:
            return {
                "success": True,
                "data": {
                    "schema_version": "2.0",
                    "request_id": "turn-0-player-evolve",
                    "result": {
                        "actor_id": "char-player-01",
                        "phase": "player",
                        "intent_text": "尝试包扎伤口",
                        "check_result": None,
                        "state_changes": [
                            {
                                "id": "bad-id",
                                "field": "status.hp",
                                "operation": "update",
                                "value": 8,
                            }
                        ],
                        "local_narrative": "第一次输出，包含错误ID。",
                        "outcome": {
                            "action_succeeded": True,
                            "outcome_type": "player_action",
                            "consequence_tags": []
                        }
                    },
                    "erro": "实体ID不存在",
                    "warnings": [],
                    "extensions": {}
                },
                "content": "",
                "model": "fake",
                "error": None,
            }

        return {
            "success": True,
            "data": {
                "schema_version": "2.0",
                "request_id": "turn-0-player-evolve",
                "result": {
                    "actor_id": "char-player-01",
                    "phase": "player",
                    "intent_text": "尝试包扎伤口",
                    "check_result": None,
                    "state_changes": [
                        {
                            "id": "char-player-01",
                            "field": "status.hp",
                            "operation": "update",
                            "value": 8,
                        }
                    ],
                    "local_narrative": "第二次输出，已修正。",
                    "outcome": {
                        "action_succeeded": True,
                        "outcome_type": "player_action",
                        "consequence_tags": []
                    }
                },
                "erro": "",
                "warnings": [],
                "extensions": {}
            },
            "content": "",
            "model": "fake",
            "error": None,
        }


class StateEvolutionErroFeedbackTests(unittest.TestCase):
    def test_error_feedback_retries_and_corrects_changes(self):
        fake_llm = FakeLLMService()
        agent = StateEvolution(llm_service=fake_llm, system_prompt="test prompt")

        game_state = GameState(
            characters={
                "char-player-01": Character(
                    id="char-player-01",
                    name="调查员",
                    status=CharacterStatus(hp=10, max_hp=12, san=60, lucky=50),
                    attributes=CharacterAttributes(dex=12),
                    is_player=True,
                )
            },
            player_id="char-player-01",
        )

        result = agent.evolve_player_action(
            check_result=None,
            action_description="尝试包扎伤口",
            game_state=game_state,
        )

        self.assertEqual(fake_llm.calls, 2)
        self.assertIn("系统错误反馈（erro）", fake_llm.prompts[1])
        self.assertEqual(result.narrative, "第二次输出，已修正。")
        self.assertEqual(len(result.changes), 1)
        self.assertEqual(result.changes[0].id, "char-player-01")

    def test_validate_changes_rejects_delete_on_non_list_field(self):
        agent = StateEvolution(llm_service=FakeLLMService(), system_prompt="test prompt")

        game_state = GameState(
            characters={
                "char-player-01": Character(
                    id="char-player-01",
                    name="调查员",
                    status=CharacterStatus(hp=10, max_hp=12, san=60, lucky=50),
                    attributes=CharacterAttributes(dex=12),
                    is_player=True,
                )
            },
            player_id="char-player-01",
        )

        errors = agent.validate_changes(
            [
                StateChange(
                    id="char-player-01",
                    field="status.hp",
                    operation=ChangeOperation.DELETE,
                    value=1,
                )
            ],
            game_state,
        )

        self.assertEqual(len(errors), 1)
        self.assertIn("DELETE仅允许作用于白名单列表字段", errors[0])


if __name__ == "__main__":
    unittest.main()
