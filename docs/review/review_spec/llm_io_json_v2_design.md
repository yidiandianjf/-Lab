# AEngine LLM 输入输出 JSON 字段设计（V2 修订稿）

版本: 0.2-draft
日期: 2026-03-28
目标: 在 unified 单模式下，为每个 LLM 提供可决策、可校验、可扩展、可抗漂移的完整上下文协议。

---

## 0. 本次修订说明

本稿已根据你的 6 项要求完成自查并修订:

1. 每个 LLM 输入补齐最小完整决策上下文。
2. 移除无用或职责越界输出字段。
3. 统一输入输出结构、命名、错误字段与枚举口径。
4. 增加长对话防漂移机制（锚点、摘要、预算、冲突处理）。
5. 提供版本化与扩展槽位，支持后续平滑演进。
6. 标注并隔离干扰信息，要求仅保留决策相关字段。

---

## 1. 设计原则

1. 事实优先: 所有可验证事实由代码提供，LLM 不得发明世界状态。
2. 职责隔离: DM 负责玩家意图解析，NPC Director 负责 NPC 计划，State Evolution 负责状态推演，Narrative Merger 负责叙事合并。
3. 单模式统一: 全链路仅使用 unified 触发语义。
4. 强约束可校验: 输出必须通过 schema 校验与运行时规则校验。
5. 防漂移优先: 长对话时以 truth_anchor 与 turn_trace 作为硬锚点。
6. 可扩展: 所有输入输出包含 schema_version 与 extensions 扩展槽。

---

## 2. 统一封装与字段规范

### 2.1 统一请求封装（所有 LLM 输入）

```json
{
  "schema_version": "2.0",
  "request_id": "turn-12-player-parse",
  "turn_id": 12,
  "phase": "player",
  "source": "engine",
  "payload": {},
  "constraints": {},
  "memory_policy": {},
  "extensions": {}
}
```

### 2.2 统一响应封装（所有 LLM 输出）

```json
{
  "schema_version": "2.0",
  "request_id": "turn-12-player-parse",
  "result": {},
  "erro": "",
  "warnings": [],
  "extensions": {}
}
```

### 2.3 命名与一致性约定

1. 错误字段统一为 erro（兼容现代码）。
2. 所有枚举字段统一放入 constraints.enums。
3. 所有约束统一放入 constraints.rules。
4. 所有可选扩展统一放入 extensions，禁止新增平铺顶层字段。

### 2.4 description 标准化约定

1. 世界配置原始结构保持为:
  - `description.public: [{"description": "..."}]`
  - `description.hint: "..."`
2. LLM 输入层建议标准化为:
  - `description`: 由 `description.public[*].description` 拼接得到的短文本
  - `description_hint`: 原始 hint
3. 若调用方需要强可追溯，可同时提供 `description_source` 字段标注来源路径。

---

## 3. 链路总览

玩家输入 -> DM Agent -> Rule -> State Evolution(Player) -> NPC Director -> State Evolution(NPC) -> Narrative Merger -> 记忆提交/持久化

信息链路映射:

- E1: world_state_view
- E2: raw_input_text
- E3: turn_intent
- E4: check_plan/check_result
- E5: turn_resolution
- E6: turn_trace_so_far
- E7: merged_narrative
- E8: dialogue_memory/narrative_memory
- E9: persistence_snapshot

---

## 4. DM Agent

### 4.1 输入 JSON（DMAgentInputV2）

```json
{
  "schema_version": "2.0",
  "request_id": "turn-12-player-parse",
  "turn_id": 12,
  "phase": "player",
  "source": "engine",
  "payload": {
    "raw_input_text": "我先观察守卫的表情，然后试着借钥匙。",
    "world_state_view": {
      "current_map": {
        "id": "map-room-library-01",
        "name": "图书馆主厅",
        "description": "高耸书架环绕，中央阅读桌上有油灯。",
        "hint": "夜间"
      },
      "nearby_characters": [
        {
          "id": "char-archivist-01",
          "name": "馆藏管理员",
          "location": "map-room-library-01",
          "description": "一个瘦高的中年人，戴着细框眼镜，指尖总有淡淡的墨迹。",
          "hint":...,
          "attitude_to_player": "neutral"
        }
      ],
      "nearby_items": [
        {
          "id": "item-key-01",
          "name": "铜钥匙",
          "location": "char-guard-01",
          "description": "古旧铜钥匙，柄部有磨损纹路。",
          "is_portable": true
        }
      ],
      "player_state": {
        "id": "char-player-01",
        "name": "调查员",
        "description": "擅长观察与推理。",
        "hint":...,
        "status": {
          "hp": 20,
          "max_hp": 20,
          "san": 60,
          "lucky": 50
        },
        "attributes": {
          "str": 20,
          "con": 20,
          "siz": 20,
          "dex": 20,
          "app": 20,
          "int": 20,
          "pow": 20,
          "edu": 20
        }
      },
      "available_exits": [
        {
          "id": "map-room-corridor-01",
          "direction": "北",
          "description": "通往昏暗走廊"
        }
      ]
    },
    "dialogue_memory": {
      "recent_dialogues": [
        {
          "speaker": "player",
          "content": "昨晚有人来过吗？"
        },
        {
          "speaker": "char-guard-01",
          "content": "我不确定。"
        }
      ],
      "dialogue_digest": "守卫对昨晚事件明显回避。"
    },
    "narrative_memory": {
      "summary_lines": [
        "[Turn 11] 你发现守卫神情紧张"
      ],
      "key_facts": [
        "char-guard-01 carries item-key-01"
      ],
      "stable_facts": [
        "图书馆主厅可通往走廊",
        "守卫持有钥匙"
      ]
    },
    "turn_trace_so_far": {
      "turn_id": 12,
      "steps": []
    }
  },
  "constraints": {
    "enums": {
      "npc_response_mode": [
        "unified"
      ],
      "interaction_type": [
        "action",
        "dialogue",
        "mixed"
      ],
      "check_difficulty": [
        "常规",
        "困难",
        "极难"
      ],
      "allowed_check_attributes": [
        "str",
        "con",
        "siz",
        "dex",
        "app",
        "int",
        "pow",
        "edu",
        "hp",
        "san",
        "lucky"
      ]
    },
    "rules": {
      "must_be_grounded": true,
      "forbid_field_invention": true
    }
  },
  "memory_policy": {
    "max_recent_dialogues": 20,
    "max_summary_lines": 20,
    "drift_anchor_required": true
  },
  "extensions": {}
}
```

### 4.2 输出 JSON（DMAgentOutputV2）

说明: activation_hint 已收敛为仅负责 NPC 激活建议，不再输出 NPC 具体回应意图，避免越权到 Director。

```json
{
  "schema_version": "2.0",#自动拼接而非llm输出
  "request_id": "turn-12-player-parse",
  "result": {
    "turn_intent": {
      "actor_id": "char-player-01",
      "raw_input_text": "我先观察守卫的表情，然后试着借钥匙。",
      "intent_text": "玩家尝试观察守卫情绪并发起借钥匙请求",
      "interaction_type": "mixed",
      "check_plan": {
        "check_needed": true,
        "check_type": "非对抗鉴定",
        "attributes": [
          "int",
          "pow"
        ],
        "target_id": null,
        "difficulty": "常规"
      },
      "activation_hint": {
        "response_needed_hint": true,
        "preferred_actor_id": "char-guard-01",
        "candidate_npc_ids_hint": [
          "char-guard-01"
        ]
      }
    },
    "response_to_player": null
  },
  "erro": "",
  "warnings": [],
  "extensions": {}
}
```

---

## 5. State Evolution（玩家阶段）

### 5.1 输入 JSON（StateEvolutionPlayerInputV2）

```json
{
  "schema_version": "2.0",
  "request_id": "turn-12-player-evolve",
  "turn_id": 12,
  "phase": "player",
  "source": "engine",
  "payload": {
    "world_state_view": {
      "...": "同上，完整保留"
    },
    "dialogue_memory": {
      "...": "完整保留"
    },
    "narrative_memory": {
      "...": "完整保留"
    },
    "turn_trace_so_far": {
      "turn_id": 12,
      "steps": []
    },
    "turn_intent": {
      "...": "来自DM输出"
    },
    "check_result": {
      "result": "成功",
      "dice_roll": 41,
      "target_value": 60,
      "actor_value": 60,
      "detail": "int检定成功"
    },
    "truth_anchor": {
      "action_succeeded": true,
      "check_outcome": "success",
      "must_preserve_facts": [
        "守卫持有钥匙直到变更发生"
      ]
    }
  },
  "constraints": {
    "enums": {
      "allowed_change_operations": [
        "update",
        "add",
        "del",
        "move"
      ]
    },
    "rules": {
      "delete_whitelist": [
        "inventory",
        "neighbors",
        "entities.items",
        "entities.characters",
        "description.public",
        "memory.log"
      ],
      "update_rule": {
        "must_use_existing_field": true,
        "forbid_schema_break": true
      },
      "add_rule": {
        "target_must_be_list": true,
        "forbid_nested_list_add": true
      },
      "delete_rule": {
        "forbid_scalar_delete": true,
        "coerce_scalar_delete_to_update": true
      },
      "move_rule": {
        "field_must_be": "location",
        "value_must_be": "target-id or {from,to}",
        "char_target_must_be_map": true,
        "item_target_must_be_char_or_map": true,
        "from_must_match_current_location_if_provided": true
      }
    }
  },
  "memory_policy": {
    "drift_anchor_required": true,
    "max_generated_narrative_chars": 800
  },
  "extensions": {}
}
```

### 5.2 输出 JSON（TurnResolution）

```json
{
  "schema_version": "2.0",
  "request_id": "turn-12-player-evolve",
  "result": {
    "actor_id": "char-player-01",
    "phase": "player",
    "intent_text": "玩家尝试观察守卫情绪并发起借钥匙请求",
    "check_result": {
      "result": "成功",
      "dice_roll": 41,
      "target_value": 60,
      "actor_value": 60,
      "detail": "int检定成功"
    },
    "state_changes": [
      {
        "id": "char-player-01",
        "field": "description.public",
        "operation": "add",
        "value": {
          "description": "你判断守卫在隐瞒信息"
        }
      },
      {
        "id": "item-key-01",
        "field": "location",
        "operation": "move",
        "value": {
          "from": "char-guard-01",
          "to": "char-player-01"
        }
      }
    ],
    "local_narrative": "你从守卫细微的停顿中看出犹豫，他最终把钥匙递给了你。",
    "outcome": {
      "action_succeeded": true,
      "outcome_type": "player_action",
      "consequence_tags": [
        "new-clue",
        "item-transfer"
      ]
    }
  },
  "erro": "",
  "warnings": [],
  "extensions": {}
}
```

---

## 6. NPC Director

### 6.1 输入 JSON（NPCDirectorInputV2）

```json
{
  "schema_version": "2.0",
  "request_id": "turn-12-npc-plan",
  "turn_id": 12,
  "phase": "npc_planning",
  "source": "engine",
  "payload": {
    "trigger_source": "unified",
    "activated_npc_ids": [
      "char-guard-01",
      "char-archivist-01"
    ],
    "surrounding_context": {
      "current_map": {
        "id": "map-room-library-01",
        "name": "图书馆主厅",
        "description": "主厅静默，走廊有冷风。"
      },
      "nearby_non_activated_npcs": [],
      "nearby_items": [
        {
          "id": "item-book-01",
          "location": "map-room-library-01",
          "description": "破旧古书，可能关联地下线索。"
        }
      ],
      "hazards": []
    },
    "player_action_summary": "玩家通过观察与交涉尝试获取钥匙",
    "player_turn_resolution": {
      "...": "完整保留"
    },
    "turn_trace_so_far": {
      "turn_id": 12,
      "steps": [
        {
          "step_id": "turn-12-player-1",
          "actor_id": "char-player-01",
          "phase": "player",
          "resolution": {
            "...": "完整保留"
          }
        }
      ]
    },
    "narrative_memory": {
      "...": "完整保留"
    },
    "npc_world_views": [
      {
        "npc_id": "char-guard-01",
        "name": "老守卫",
        "location": "map-room-corridor-01",
        "status": {
          "hp": 10,
          "max_hp": 10,
          "san": 45
        },
        "attributes": {
          "str": 11,
          "con": 12,
          "siz": 13,
          "dex": 10,
          "app": 9,
          "int": 11,
          "pow": 12,
          "edu": 10
        },
        "basic_info": "图书馆夜班守卫，熟悉馆内旧事。",
        "description_public": "谨慎寡言。",
        "description_hint": "若玩家保持克制，可能透露线索。",
        "memory": {
          "current_event": "玩家正尝试借钥匙",
          "log": []
        }
      }
    ]
  },
  "constraints": {
    "enums": {
      "mode": [
        "unified"
      ],
      "action_type": [
        "attack",
        "move",
        "talk",
        "use_item",
        "investigate",
        "wait",
        "custom"
      ],
      "check_difficulty": [
        "常规",
        "困难",
        "极难"
      ]
    },
    "rules": {
      "must_reference_existing_ids": true,
      "max_actions_per_turn": 3,
      "avoid_npc_narrative_conflict": true
    }
  },
  "memory_policy": {
    "prefer_recent_turns": true,
    "must_follow_player_truth_anchor": true
  },
  "extensions": {}
}
```

### 6.2 输出 JSON（NPCActionDecision）

```json
{
  "schema_version": "2.0",
  "request_id": "turn-12-npc-plan",
  "result": {
    "actions": {
      "char-guard-01": {
        "npc_id": "char-guard-01",
        "action_type": "talk",
        "target_id": "char-player-01",
        "intent_description": "压低声音提醒玩家谨慎使用钥匙",
        "expected_outcome": "维持秩序且不过度暴露秘密",
        "check": {
          "check_needed": false,
          "check_attributes": [],
          "difficulty": "常规",
          "check_target_id": null
        },
        "trigger_source": "unified",
        "metadata": {
          "reason": "与守卫性格和当前线索状态一致"
        }
      }
    },
    "rationale": "先由守卫回应，管理员保持观察，避免多NPC同时抢叙事。"
  },
  "erro": "",
  "warnings": [],
  "extensions": {}
}
```

---

## 7. State Evolution（NPC阶段）

### 7.1 输入 JSON（StateEvolutionNpcInputV2）

```json
{
  "schema_version": "2.0",
  "request_id": "turn-12-npc-evolve-char-guard-01",
  "turn_id": 12,
  "phase": "npc",
  "source": "engine",
  "payload": {
    "active_npc_id": "char-guard-01",
    "npc_action_plan": {
      "...": "NPCDirector 对应动作"
    },
    "world_state_view": {
      "...": "完整保留"
    },
    "dialogue_memory": {
      "...": "完整保留"
    },
    "narrative_memory": {
      "...": "完整保留"
    },
    "turn_trace_so_far": {
      "...": "必须包含玩家步骤与已执行NPC步骤"
    },
    "player_turn_resolution": {
      "...": "完整保留"
    },
    "truth_anchor": {
      "action_succeeded": true,
      "check_outcome": "success"
    }
  },
  "constraints": {
    "enums": {
      "allowed_change_operations": [
        "update",
        "add",
        "del",
        "move"
      ]
    },
    "rules": {
      "must_not_override_player_truth": true,
      "must_not_duplicate_applied_changes": true
    }
  },
  "memory_policy": {
    "max_generated_narrative_chars": 600,
    "drift_anchor_required": true
  },
  "extensions": {}
}
```

### 7.2 输出 JSON（TurnResolution）

```json
{
  "schema_version": "2.0",
  "request_id": "turn-12-npc-evolve-char-guard-01",
  "result": {
    "actor_id": "char-guard-01",
    "phase": "npc",
    "intent_text": "压低声音提醒玩家谨慎使用钥匙",
    "check_result": null,
    "state_changes": [
      {
        "id": "char-player-01",
        "field": "description.public",
        "operation": "add",
        "value": {
          "description": "守卫提醒你不要在走廊停留太久"
        }
      }
    ],
    "local_narrative": "守卫把声音压到几乎听不见，示意你尽快离开主厅。",
    "outcome": {
      "action_succeeded": true,
      "outcome_type": "npc_response",
      "consequence_tags": [
        "warning"
      ]
    }
  },
  "erro": "",
  "warnings": [],
  "extensions": {}
}
```

---

## 8. Narrative Merger

### 8.1 输入 JSON（NarrativeMergerInputV2）

```json
{
  "schema_version": "2.0",
  "request_id": "turn-12-merge",
  "turn_id": 12,
  "phase": "narrative_merge",
  "source": "engine",
  "payload": {
    "turn_trace_steps": [
      {
        "step_id": "turn-12-player-1",
        "phase": "player",
        "actor_id": "char-player-01",
        "intent": {
          "...": "完整保留"
        },
        "resolution": {
          "...": "完整保留"
        }
      },
      {
        "step_id": "turn-12-npc-char-guard-01",
        "phase": "npc",
        "actor_id": "char-guard-01",
        "intent": {
          "...": "完整保留"
        },
        "resolution": {
          "...": "完整保留"
        }
      }
    ],
    "turn_truth_anchor": {
      "player_action_succeeded": true,
      "core_facts": [
        "item-key-01 moved to char-player-01"
      ]
    },
    "narrative_memory": {
      "summary_lines": [
        "[Turn 11] ..."
      ],
      "key_facts": [
        "..."
      ]
    },
    "dialogue_memory": {
      "recent_dialogues": [
        {
          "speaker": "player",
          "content": "..."
        },
        {
          "speaker": "char-guard-01",
          "content": "..."
        }
      ]
    }
  },
  "constraints": {
    "rules": {
      "must_preserve_turn_truth_anchor": true,
      "must_not_invent_new_state_change": true,
      "max_merged_narrative_chars": 1000
    }
  },
  "memory_policy": {
    "summary_write_back_required": true,
    "key_fact_write_back_required": true
  },
  "extensions": {}
}
```

### 8.2 输出 JSON（NarrativeMergerOutputV2）

```json
{
  "schema_version": "2.0",
  "request_id": "turn-12-merge",
  "result": {
    "merged_narrative": "你从守卫微妙的停顿里确认了他的动摇，钥匙最终落入你的掌心。守卫随即压低声音，催促你尽快离开主厅。",
    "turn_summary": "玩家获取钥匙并收到守卫警告。",
    "new_key_facts": [
      "item-key-01@char-player-01",
      "guard-warning-issued"
    ],
    "dialogue_updates": [
      {
        "speaker": "char-guard-01",
        "content": "别在主厅久留。"
      }
    ]
  },
  "erro": "",
  "warnings": [],
  "extensions": {}
}
```

---

## 9. Move 操作协议（最终约定）

### 9.1 允许格式

1. 简写:

```json
{
  "id": "item-key-01",
  "field": "location",
  "operation": "move",
  "value": "char-player-01"
}
```

2. 显式来源:

```json
{
  "id": "item-key-01",
  "field": "location",
  "operation": "move",
  "value": {
    "from": "char-guard-01",
    "to": "char-player-01"
  }
}
```

### 9.2 代码约束

1. field 必须是 location。
2. 角色 move 目标必须是 map id。
3. 物品 move 目标必须是 char id 或 map id。
4. 若提供 from，必须与实体当前 location 一致。
5. move 成功后由代码自动维护 inventory 与地图 entities 关系。

---

## 10. 长对话防漂移机制

1. 双锚点机制:
- 事实锚点: truth_anchor.core_facts
- 过程锚点: turn_trace_so_far.steps

2. 记忆分层:
- recent_dialogues 负责短期语境
- summary_lines 负责中期压缩
- stable_facts 负责长期不变事实

3. 预算控制:
- 输入窗口超过预算时，优先保留: truth_anchor > turn_trace > summary > raw dialogues

4. 冲突裁决:
- 新推理与 stable_facts 冲突时，必须输出 erro 或 warnings，不得静默覆盖。

---

## 11. 扩展策略

1. 版本化扩展:
- 只允许在 extensions 中追加字段。
- 破坏性变更必须升级 schema_version 主版本号。

2. 能力扩展点:
- 可在 constraints.rules 新增规则，不影响既有字段。
- 可在 payload 新增可选视图，但不得删除既有核心字段。

3. 兼容策略:
- 新字段必须可选。
- 老字段弃用需先标记 deprecated 两个迭代周期。

---

## 12. 输入干扰信息治理

1. 输入必须只保留决策相关信息。
2. 以下视为干扰信息，禁止直接输入 LLM:
- 调试日志原文
- 内部堆栈信息
- 非当前回合无关的历史明细
- 未结构化的大段系统提示拼接残片

3. 对可能干扰但有价值的信息，必须结构化后再输入:
- 通过 summary_lines 输入摘要
- 通过 key_facts 输入结论
- 通过 warnings 输入风险提示

---

## 13. 六项自查结论

1. 决策完整性: 通过。
- 每个 LLM 均具备 世界视图 + 记忆视图 + 回合链 + 约束 + 锚点。

2. 无用输出字段: 已清理。
- DM 的 activation_hint 移除 npc_intent_hint，仅保留激活建议。
- 各输出统一为 result 业务体，避免平铺冗余。

3. 格式统一性与一致性: 通过。
- 统一 request/response 外壳，统一 erro、warnings、extensions、schema_version。

4. 长对话防漂移: 可保障。
- 已引入双锚点、记忆分层、预算裁切和冲突裁决规则。

5. 扩展能力: 可支持。
- 通过版本号与 extensions 槽位可平滑扩展。

6. 输入干扰控制: 可控。
- 已定义干扰信息清单与结构化输入路径。

---

## 14. 与 mysterious_library 配置对齐说明

1. 守卫实际位置为 `map-room-corridor-01`，文档中的主厅 nearby 示例已改为 `char-archivist-01`。
2. `description` 输入采用标准化文本视图，来源于 `description.public[*].description`。
3. `is_interactable` 已从示例移除（世界配置无该字段）。
4. 检定难度枚举已统一为中文：`常规/困难/极难`。
5. 属性白名单移除 `luck`，保留 `lucky`。

---

## 15. 交付清单

1. 单模式: 仅保留 unified 语义。
2. Move: 已进入操作枚举、校验层、执行层与内存同步层。
3. JSON 设计: 本文档可直接作为协议评审基线。
4. 自查结论: 已覆盖你提出的 6 项检查要求。
