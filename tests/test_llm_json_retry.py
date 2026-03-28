import unittest

from src.agent.dm_agent import DMAgent
from src.agent.state_evolution import StateEvolution
from src.agent.llm_service import LLMService
from src.data.models import GameState, Character


class LLMJsonRetryTests(unittest.TestCase):
    def test_call_llm_json_retries_with_error_hint(self):
        service = object.__new__(LLMService)
        calls = []

        def fake_call_llm(prompt, response_format=None, max_retries=3, **kwargs):
            calls.append(prompt)
            # 第一次给坏JSON，第二次给正确JSON
            if len(calls) == 1:
                return {
                    "success": True,
                    "content": "{bad json}",
                    "model": "fake-model",
                    "usage": None,
                    "error": None,
                }
            return {
                "success": True,
                "content": '{"ok": true}',
                "model": "fake-model",
                "usage": None,
                "error": None,
            }

        service.call_llm = fake_call_llm  # type: ignore[attr-defined]

        result = LLMService.call_llm_json(
            service,
            prompt="测试",
            schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
            max_retries=3,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"], {"ok": True})
        self.assertGreaterEqual(len(calls), 2)
        self.assertIn("上一次输出存在错误", calls[1])

    def test_dm_agent_does_not_override_temperature(self):
        captured_kwargs = {}

        class FakeLLM:
            def call_llm_json(self, prompt, schema, **kwargs):
                captured_kwargs.update(kwargs)
                return {
                    "success": True,
                    "data": {
                        "schema_version": "2.0",
                        "request_id": "turn-0-player-parse",
                        "result": {
                            "turn_intent": {
                                "actor_id": "char-player-01",
                                "raw_input_text": "测试输入",
                                "intent_text": "测试",
                                "interaction_type": "action",
                                "check_plan": {
                                    "check_needed": False,
                                    "check_type": None,
                                    "attributes": [],
                                    "target_id": None,
                                    "difficulty": None
                                },
                                "activation_hint": {
                                    "response_needed_hint": False,
                                    "preferred_actor_id": None,
                                    "candidate_npc_ids_hint": []
                                }
                            },
                            "response_to_player": None
                        },
                        "erro": "",
                        "warnings": [],
                        "extensions": {}
                    },
                    "content": "",
                    "model": "fake",
                    "error": None,
                }

        agent = DMAgent(llm_service=FakeLLM(), system_prompt="test")
        output = agent.parse_intent("测试输入", game_state=None)
        self.assertFalse(output.needs_check)
        self.assertNotIn("temperature", captured_kwargs)

    def test_state_evolution_does_not_override_temperature(self):
        captured_kwargs = {}

        class FakeLLM:
            def call_llm_json(self, prompt, schema, **kwargs):
                captured_kwargs.update(kwargs)
                return {
                    "success": True,
                    "data": {
                        "schema_version": "2.0",
                        "request_id": "turn-0-player-evolve",
                        "result": {
                            "actor_id": "char-player-01",
                            "phase": "player",
                            "intent_text": "观察",
                            "check_result": None,
                            "state_changes": [],
                            "local_narrative": "测试叙事",
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

        game_state = GameState(
            characters={"char-player-01": Character(id="char-player-01", name="测试者", is_player=True)},
            player_id="char-player-01",
        )
        agent = StateEvolution(llm_service=FakeLLM(), system_prompt="test")
        output = agent.evolve_player_action(check_result=None, action_description="观察", game_state=game_state)
        self.assertEqual(output.narrative, "测试叙事")
        self.assertNotIn("temperature", captured_kwargs)


if __name__ == "__main__":
    unittest.main()
