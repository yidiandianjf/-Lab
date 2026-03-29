# 系统中所有LLM接收到的上下文汇总

> 本文档详细描述了A Engine中所有LLM Agent接收到的上下文信息结构
> 
> 生成时间: 2026-03-29
> 版本: 1.0

---

## 目录

1. [概述](#概述)
2. [DMAgent（玩家意图解析）](#1-dmagent玩家意图解析)
3. [StateEvolution（状态推演系统）](#2-stateevolution状态推演系统)
4. [NPCDirector（NPC导演）](#3-npcdirectornpc导演)
5. [NarrativeMerger（叙事合并器）](#4-narrativemerger叙事合并器)
6. [通用上下文组件](#通用上下文组件)
7. [上下文对比表](#上下文对比表)

---

## 概述

本系统采用多Agent架构，每个LLM Agent负责不同的游戏逻辑处理。所有Agent通过统一的 `LLMRequestEnvelopeV2` 协议接收上下文信息。

### 信息链路位置（九要素模型）

```
E1(世界事实) → E2(输入信号) → E3(意图解释) → E4(规则结算) → E5(步骤结算) → E6(回合因果链) → E7(叙事投影) → E8(长期记忆) → E9(持久化投影)
```

各Agent在链路中的位置：
- **DMAgent**: E2 → E3（输入信号到意图解释）
- **StateEvolution**: E4 → E5（规则结算到步骤结算）
- **NPCDirector**: E6 上游规划（回合因果链规划）
- **NarrativeMerger**: E6 → E7（回合因果链到叙事投影）

---

## 1. DMAgent（玩家意图解析）

### 1.1 职责说明
解析玩家输入，判断是行动还是对话，确定是否需要检定，识别NPC响应需求。

### 1.2 接收的完整上下文

```json
{
  // 请求信封 - 标识本次请求的基本信息
  "request_id": "turn-{turn_id}-player-parse",  // 唯一请求ID，格式：turn-{回合数}-player-parse
  "turn_id": 12,                                   // 当前回合ID
  "phase": "player",                               // 阶段标识：player表示玩家阶段
  
  // Payload - 核心上下文数据
  "payload": {
    // 玩家原始输入文本
    "raw_input_text": "我想检查这个保险箱",
    
    // 世界状态视图 - 当前游戏世界的快照
    "world_state_view": {
      // 当前地图信息
      "current_map": {
        "id": "map-corridor-01",                   // 地图唯一标识
        "name": "走廊",                             // 地图显示名称
        "description": "一条昏暗的走廊..."          // 地图公开描述
      },
      
      // 附近角色列表 - 当前场景中的NPC和玩家
      "nearby_characters": [
        {
          "id": "char-guard-01",                   // 角色ID
          "name": "守卫",                           // 角色名称
          "is_player": false,                      // 是否为玩家角色
          "basic_info": "夜班守卫",                // 角色基本信息
          "description_public": "一个穿着制服的人", // 公开描述（玩家可见）
          "description_hint": "性格谨慎，忠于职守"   // 内部提示（LLM决策参考）
        }
      ],
      
      // 附近物品列表 - 当前场景中的可交互物品
      "nearby_items": [
        {
          "id": "item-safe-01",                    // 物品ID
          "name": "保险箱",                         // 物品名称
          "description_public": "一个金属保险箱",   // 公开描述
          "description_hint": "需要钥匙或撬锁工具", // 内部提示
          "is_portable": false                     // 是否可携带
        }
      ],
      
      // 玩家状态 - 当前行动角色的详细信息
      "player_state": {
        "id": "char-player-01",
        "name": "调查员",
        "status": {
          "hp": 12,        // 当前生命值
          "max_hp": 12,    // 最大生命值
          "san": 60        // 理智值
        },
        "attributes": {
          "str": 60,       // 力量
          "con": 60,       // 体质
          "dex": 60,       // 敏捷
          "int": 70,       // 智力
          "pow": 60,       // 意志
          "edu": 70        // 教育
        }
      },
      
      // 可用出口 - 当前地图的相邻连接
      "available_exits": []
    },
    
    // 对话记忆 - 最近的对话历史
    "dialogue_memory": {
      "recent_dialogues": [
        {
          "speaker": "history",      // 发言者标识
          "content": "之前的对话内容" // 对话内容
        }
      ]
    },
    
    // 叙事记忆 - 游戏进程中的关键信息
    "narrative_memory": {
      "summary_lines": ["事件摘要1", "事件摘要2"],  // 近期事件摘要
      "key_facts": ["关键事实1"],                    // 关键事实
      "stable_facts": ["稳定事实1"]                  // 稳定事实（不会改变）
    },
    
    // 回合追踪 - 本回合已执行的步骤
    "turn_trace_so_far": {
      "turn_id": 12,
      "steps": []  // 本回合已执行的步骤列表
    }
  },
  
  // 约束规则 - 定义LLM输出的限制条件
  "constraints": {
    "enums": {
      // NPC响应模式枚举
      "npc_response_mode": ["unified"],  // unified: 统一响应模式
      
      // 交互类型枚举
      "interaction_type": ["action", "dialogue", "mixed"],
      // action: 纯行动（如开锁、攻击）
      // dialogue: 纯对话（如问候、询问）
      // mixed: 混合（如边开锁边说话）
      
      // 检定难度枚举（COC规则）
      "check_difficulty": ["常规", "困难", "极难"],
      
      // 允许检定的属性列表
      "allowed_check_attributes": [
        "str", "con", "siz", "dex", "app",  // 物理属性
        "int", "pow", "edu",                 // 精神属性
        "hp", "san", "lucky"                 // 状态属性
      ]
    },
    "rules": {
      "must_be_grounded": true,        // 必须基于现有世界事实，不能虚构
      "forbid_field_invention": true,  // 禁止发明不存在的字段
      "actor_id": "char-player-01"     // 当前行动者ID
    }
  },
  
  // 记忆策略 - 控制记忆的使用方式  #有无代码显式控制,不应该是让llm决定保留哪几条对话啊,如果有就删除这个字段,如果没有就增加一个配置项到config.json中,并让代码控制记忆策略的使用
  "memory_policy": {
    "max_recent_dialogues": 20,      // 最多保留20条近期对话
    "max_summary_lines": 20,         // 最多保留20条摘要
    "drift_anchor_required": true    // 必须遵守事实锚点，防止幻觉
  },
  
  // 扩展信息 - 额外的配置参数  
  "extensions": {
    "npc_response_policy": "",       // NPC响应策略
    "npc_prelude": ""                // NPC前置剧情
  }
}
```

### 1.3 输出字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `is_dialogue` | boolean | 是否为对话类型 |
| `needs_check` | boolean | 是否需要检定 |
| `check_attributes` | string[] | 需要检定的属性 |
| `target_id` | string | 目标实体ID |
| `action_description` | string | 行动描述 |
| `npc_response_needed` | boolean | 是否需要NPC响应 |
| `npc_actor_id` | string | 优先响应的NPC |

---

## 2. StateEvolution（状态推演系统）

### 2.1 职责说明
根据检定结果推演世界变化，生成叙事描述和状态变更列表。这是AI权力最大的模块，负责将数值结果转化为世界变化。

### 2.2 玩家行动推演上下文

```json
{
  "request_id": "turn-{turn_id}-player-evolve",
  "turn_id": 12,
  "phase": "player",
  "payload": {
    // 世界状态视图（同DMAgent）
    "world_state_view": { ... },
    
    // 对话记忆
    "dialogue_memory": { ... },
    
    // 叙事记忆
    "narrative_memory": { ... },
    
    // 回合追踪
    "turn_trace_so_far": { ... },
    
    // 回合意图 - DMAgent解析后的结构化意图（已简化）
    "turn_intent": {
      "actor_id": "char-player-01",           // 行动者ID
      "raw_input_text": "我想撬开保险箱",     // 原始输入
      "intent_text": "使用撬锁工具打开保险箱", // 解析后的意图
      "interaction_type": "action"             // 交互类型
      // 注意：check_plan和activation_hint已移除，StateEvolution不需要这些信息
    },
    
    // 检定结果 - CheckSystem的输出（已简化，只保留核心字段）
    "check_result": {
      "result": "success"           // 结果：success/failure（已移除dice_roll/target_value/actor_value/detail）
    },
    
    // 事实锚点 - 玩家阶段已确定的事实
    "truth_anchor": {
      "action_succeeded": true       // 玩家行动是否成功
    }
  },
  
  // 约束规则 - 状态变更的操作限制
  "constraints": {
    "enums": {
      // 允许的状态变更操作
      "allowed_change_operations": [
        "update",  // 更新字段值
        "add",     // 向列表添加元素
        "del",     // 从列表删除元素
        "move"     // 移动位置（专用于location）
      ]
    },
    "rules": {
      // 删除操作白名单 - 只允许删除这些列表字段的元素
      "delete_whitelist": [
        "inventory",           // 角色背包
        "neighbors",           // 地图邻居连接
        "entities.items",      // 地图上的物品
        "entities.characters", // 地图上的角色
        "description.add"      // 新增描述（只能通过add操作添加）
        // 注意：description.public和memory.log已从白名单移除
      ],
      
      // 更新规则
      "update_rule": {
        "must_use_existing_field": true,   // 必须更新已存在的字段
        "forbid_schema_break": true,       // 禁止破坏数据结构
        "forbidden_fields": ["is_player", "is_portable", "id", "name", "basic_info", "description.public", "description.hint", "memory.log", "memory.current_event"]
      },
      
      // 添加规则
      "add_rule": {
        "target_must_be_list": true,       // 只能向列表类型字段添加
        "forbid_nested_list_add": true,    // 禁止嵌套列表添加
        "allowed_fields": ["inventory", "neighbors", "entities.items", "entities.characters", "description.add"]
      },
      
      // 删除规则
      "delete_rule": {
        "forbid_scalar_delete": true,           // 禁止删除标量字段
        "coerce_scalar_delete_to_update": true  // 标量删除转为更新默认值
      },
      
      // 移动规则 - 专用于location字段
      "move_rule": {
        "field_must_be": "location",                    // 只能操作location字段
        "value_must_be": "target-id or {from,to}",      // 值格式
        "char_target_must_be_map": true,                // 角色目标必须是地图
        "item_target_must_be_char_or_map": true,        // 物品目标可以是角色或地图
        "from_must_match_current_location_if_provided": true  // from必须匹配当前位置
      },
      
      // 全局禁止编辑的字段
      "forbidden_fields": [
        "is_player", "is_portable", "id",
        "name", "basic_info",
        "description.public", "description.hint",
        "memory.log", "memory.current_event"
      ],
      
      // description字段特殊规则
      "description_rule": {
        "can_only_add_to_add_field": true,  // 只能向description.add添加
        "cannot_edit_public": true,         // 不能编辑description.public
        "cannot_edit_hint": true            // 不能编辑description.hint
      }
    }
  },
  
  "memory_policy": {
    // 注意：drift_anchor_required已移除，由代码层控制记忆策略
    "max_generated_narrative_chars": 800     // 生成叙事的最大字符数
  }
  
  "extensions": {
    "end_condition": "玩家找到出口或死亡"     // 结局条件描述
  }
}
```

### 2.3 NPC行动推演上下文

```json
{
  "request_id": "turn-{turn_id}-npc-evolve-{npc_id}",
  "turn_id": 12,
  "phase": "npc",                              // NPC阶段
  "payload": {
    "active_npc_id": "char-guard-01",         // 当前行动的NPC
    
    // NPC行动计划 - NPCDirector生成的计划
    "npc_action_plan": {
      "npc_id": "char-guard-01",
      "action_type": "talk",                   // 动作类型
      "target_id": "char-player-01",          // 目标
      "intent_description": "警告玩家不要撬锁", // 意图描述
      "check": {
        "check_needed": false                  // 不需要检定
      }
    },
    
    "world_state_view": { ... },
    "dialogue_memory": { ... },
    "narrative_memory": { ... },
    "turn_trace_so_far": { ... },
    // 注意：player_turn_resolution已移除，相关信息应从turn_trace_so_far中获取
    
    "truth_anchor": { ... },
    "npc_intent": "警告玩家停止撬锁行为",       // NPC意图
    "check_result": null                        // NPC检定结果（可选，已简化）
  },
  "constraints": {
    "rules": {
      "must_not_override_player_truth": true,   // 不能覆盖玩家事实
      "must_not_duplicate_applied_changes": true, // 不能重复已应用的变更
      "forbidden_fields": ["is_player", "is_portable", "id", "name", "basic_info", "description.public", "description.hint", "memory.log", "memory.current_event"],
      "description_rule": {
        "can_only_add_to_add_field": true,
        "cannot_edit_public": true,
        "cannot_edit_hint": true
      }
    }
  },
  "memory_policy": {
    "max_generated_narrative_chars": 600        // NPC叙事更短
  },
  "extensions": { "end_condition": "" }
}
```

### 2.4 结局判定上下文

```json
{
  "request_id": "turn-{turn_id}-end-check",
  "turn_id": 12,
  "phase": "end_check",                        // 结局检查阶段
  "payload": {
    "world_state_view": { ... },
    "dialogue_memory": { ... },
    "narrative_memory": { ... },
    "turn_trace_so_far": { ... },
    
    // 结局判定的特殊意图（已简化）
    "turn_intent": {
      "actor_id": "char-player-01",
      "raw_input_text": "结局判定",
      "intent_text": "检查当前状态是否触发结局",
      "interaction_type": "action"
      // 注意：check_plan和activation_hint已移除
    },
    "check_result": null,
    "truth_anchor": {}
  },
  "constraints": {
    "rules": {
      "must_only_decide_ending": true,           // 只能决定结局
      "must_not_invent_new_state_change": true,  // 不能发明新状态变更
      "forbidden_fields": ["is_player", "is_portable", "id", "name", "basic_info", "description.public", "description.hint", "memory.log", "memory.current_event"],
      "description_rule": {
        "can_only_add_to_add_field": true,
        "cannot_edit_public": true,
        "cannot_edit_hint": true
      }
    }
  },
  "memory_policy": {
    "max_generated_narrative_chars": 400        // 结局叙事更短
  },
  "extensions": {
    "end_condition": "结局条件",
    "end_check_only": true
  }
}
```

### 2.5 StateEvolution输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `narrative` | string | 生成的叙事描述 |
| `changes` | StateChange[] | 状态变更列表 |
| `resolved` | boolean | 是否已解决 |
| `is_end` | boolean | 是否触发结局 |
| `end_narrative` | string | 结局叙事 |

---

## 3. NPCDirector（NPC导演）

### 3.1 职责说明
在同一回合为已激活的NPC生成结构化行动计划，协调多NPC之间的行动，避免叙事冲突。

### 3.2 接收的完整上下文

```json
{
  "request_id": "turn-{turn_id}-npc-plan",
  "turn_id": 12,
  "phase": "npc_planning",
  "payload": {
    // 触发来源
    "trigger_source": "unified",  // unified: 统一响应模式
    
    // 激活的NPC列表 - 本轮需要规划的NPC
    "activated_npc_ids": [
      "char-guard-01",      // 守卫
      "char-archivist-01"   // 馆藏管理员
    ],
    
    // 场景上下文
    "surrounding_context": {
      "current_map": {
        "id": "map-corridor-01",
        "name": "走廊",
        "description": "一条昏暗的走廊，尽头有一扇门"
      },
      
      // 附近未激活的NPC（用于了解完整场景）
      "nearby_non_activated_npcs": [],
      
      // 附近物品
      "nearby_items": []
      // 注意：hazards字段已移除，不在NPCDirector中使用
    },
    
    // 玩家行动摘要
    "player_action_summary": "玩家通过观察与交涉尝试获取钥匙",
    
    // 玩家阶段结算结果 - NPC必须遵守的事实锚点
    // 注意：此字段将在后续版本中从payload移除，相关信息应从turn_trace_so_far获取
    "player_turn_resolution": {
      "actor_id": "char-player-01",
      "phase": "player",
      "state_changes": [
        {
          "id": "char-player-01",
          "field": "inventory",
          "operation": "add",
          "value": "item-key-01"
        }
      ],
      "local_narrative": "玩家成功说服守卫借出钥匙",
      "outcome": {
        "action_succeeded": true,        // 重要：NPC不能逆转这个结果
        "outcome_type": "success",
        "consequence_tags": ["persuasion", "trust"]
      }
    },
    
    // 回合追踪
    "turn_trace_so_far": {
      "turn_id": 12,
      "steps": [
        {
          "step_id": "step-1",
          "actor_id": "char-player-01",
          "phase": "player",
          "resolution": { ... }
        }
      ]
    },
    
    // 叙事记忆
    "narrative_memory": {
      "summary_lines": ["玩家进入走廊", "玩家与守卫交谈"],
      "key_facts": ["守卫持有钥匙", "玩家需要进入档案室"],
      "stable_facts": ["档案室在走廊尽头"]
    },
    
    // NPC世界观 - 每个激活NPC的详细状态
    "npc_world_views": [
      {
        "npc_id": "char-guard-01",
        "name": "守卫",
        "location": "map-corridor-01",    // 当前位置
        
        // 状态
        "status": {
          "hp": 10,        // 生命值
          "max_hp": 10,    // 最大生命值
          "san": 45        // 理智值
        },
        
        // 属性（COC七版规则）
        "attributes": {
          "str": 60,       // 力量
          "con": 60,       // 体质
          "siz": 65,       // 体型
          "dex": 50,       // 敏捷
          "app": 55,       // 外貌
          "int": 50,       // 智力
          "pow": 50,       // 意志
          "edu": 45        // 教育
        },
        
        "basic_info": "夜班守卫，工作5年",
        "description_public": "一个穿着制服的中年男子",
        "description_hint": "性格谨慎，但容易被说服，对玩家有轻微好感",
        
        // 记忆
        "memory": {
          "current_event": "玩家请求借用钥匙",
          "log": ["玩家进入走廊", "玩家主动搭话"]
        }
      },
      {
        "npc_id": "char-archivist-01",
        "name": "馆藏管理员",
        "location": "map-corridor-01",
        "status": { "hp": 8, "max_hp": 8, "san": 55 },
        "attributes": { ... },
        "basic_info": "档案室管理员，学者气质",
        "description_public": "戴着眼镜的老者",
        "description_hint": "不轻易介入冲突，保持中立",
        "memory": {
          "current_event": "",
          "log": []
        }
      }
    ]
  },
  
  // 约束规则
  "constraints": {
    "enums": {
      // 响应模式
      "mode": ["unified"],  // 统一响应模式
      
      // 动作类型枚举
      "action_type": [
        "attack",      // 攻击
        "move",        // 移动
        "talk",        // 对话
        "use_item",    // 使用物品
        "investigate", // 调查
        "wait",        // 等待
        "custom"       // 自定义
      ],
      
      // 检定难度
      "check_difficulty": ["常规", "困难", "极难"]
    },
    "rules": {
      "must_reference_existing_ids": true,      // 引用的ID必须存在
      "max_actions_per_turn": 3,                // 每回合最多动作数
      "avoid_npc_narrative_conflict": true      // 避免NPC间叙事冲突
    }
  },
  
  // 记忆策略
  "memory_policy": {
    "prefer_recent_turns": true,               // 优先参考近期回合
    "must_follow_player_truth_anchor": true    // 必须遵守玩家事实锚点
  },
  
  // 扩展信息
  "extensions": {
    "recent_events": [                         // 最近事件（最多10条）
      {"event": "玩家进入走廊", "timestamp": "..."}
    ],
    "narrative_context": "当前场景为走廊，守卫正在值班"  // 叙事上下文
  }
}
```

### 3.3 NPCDirector输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `actions` | object | NPC动作计划集合，键为NPC ID |
| `rationale` | string | 本轮整体协调说明 |

每个动作的字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `npc_id` | string | NPC的ID |
| `action_type` | string | 动作类型枚举值 |
| `target_id` | string/null | 目标ID |
| `intent_description` | string | 动作意图描述 |
| `expected_outcome` | string | 期望结果 |
| `check` | object | 检定信息 `{check_needed, check_attributes, difficulty}` |
| `trigger_source` | string | 触发来源（固定为"unified"） |
| `metadata` | object | 元数据 `{reason}` |

---

## 4. NarrativeMerger（叙事合并器）

### 4.1 职责说明
将多个叙事片段（玩家行动、多个NPC行动）合并为连贯的回合级叙事，生成回合摘要和新的关键事实。

### 4.2 V2 API 上下文

```json
{
  "request_id": "turn-{turn_id}-merge",
  "turn_id": 12,
  "phase": "narrative_merge",
  "payload": {
    // 回合追踪步骤 - 本回合所有已执行的步骤
    "turn_trace_steps": [
      {
        "step_id": "step-player-1",
        "turn_id": 12,
        "actor_id": "char-player-01",
        "phase": "player",
        "trigger_source": "player_input",
        
        // 意图
        "intent": {
          "actor_id": "char-player-01",
          "raw_input_text": "我想撬开保险箱",
          "intent_text": "使用撬锁工具打开保险箱",
          "interaction_type": "action",
          "check_plan": { ... }
        },
        
        // 结算结果
        "resolution": {
          "actor_id": "char-player-01",
          "phase": "player",
          "intent_text": "使用撬锁工具打开保险箱",
          "check_result": { ... },
          "state_changes": [...],
          "local_narrative": "你小心翼翼地拨动锁芯，随着一声轻响，保险箱打开了。",
          "outcome": {
            "action_succeeded": true,
            "outcome_type": "success",
            "consequence_tags": ["noise"]
          }
        }
      },
      {
        "step_id": "step-npc-1",
        "turn_id": 12,
        "actor_id": "char-guard-01",
        "phase": "npc",
        "trigger_source": "unified",
        "intent": { ... },
        "resolution": {
          "actor_id": "char-guard-01",
          "phase": "npc",
          "local_narrative": "守卫听到声音，警觉地看向你的方向。"
        }
      }
    ],
    
    // 回合事实锚点 - 本回合的确定事实
    "turn_truth_anchor": {
      "action_succeeded": true,
      "state_changes_applied": [...]
    },
    
    // 叙事记忆
    "narrative_memory": {
      "summary_lines": ["玩家进入走廊", "玩家尝试撬开保险箱"],
      "key_facts": ["保险箱在走廊尽头", "守卫在值班"],
      "stable_facts": ["档案室存放着重要文件"]
    },
    
    // 对话记忆
    "dialogue_memory": {
      "recent_dialogues": []
    }
  },
  
  // 约束规则
  "constraints": {
    "rules": {
      "must_preserve_turn_truth_anchor": true,    // 必须保留回合事实锚点
      "must_not_invent_new_state_change": true,   // 不能发明新状态变更
      "max_merged_narrative_chars": 1000          // 合并后叙事最大长度
    }
  },
  
  // 记忆策略
  "memory_policy": {
    "summary_write_back_required": true,    // 需要写回摘要
    "key_fact_write_back_required": true    // 需要写回关键事实
  }
}
```

### 4.3 NarrativeMerger输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `merged_narrative` | string | 合并后的完整叙事 |
| `turn_summary` | string | 回合摘要（用于记忆） |
| `new_key_facts` | string[] | 新发现的关键事实 |
| `dialogue_updates` | object[] | 对话更新列表 |

---

## 通用上下文组件

所有LLM Agent共享以下通用上下文组件：

### WorldStateView（世界状态视图）

```json
{
  "current_map": {
    "id": "地图ID",
    "name": "地图名称",
    "description": {              // 描述系统（新增add字段）
      "public": [...],            // 公开描述列表（只读，由系统维护）
      "hint": "内部提示",        // 内部提示（只读）
      "add": []                   // 新增描述（StateEvolution可添加）
    }
  },
  "nearby_characters": [...],   // 附近角色
  "nearby_items": [...],        // 附近物品
  "player_state": {...},        // 玩家状态
  "available_exits": [...]      // 可用出口
}
```

**Description系统说明：**
- `public`: 公开描述列表，只读，由系统维护
- `hint`: 内部提示，只读，仅AI可见
- `add`: 新增描述，StateEvolution只能通过ADD操作向此字段添加内容
- 系统会在回合结束时自动将`add`的内容合并到`public`

### DialogueMemory（对话记忆）

```json
{
  "recent_dialogues": [
    {
      "speaker": "发言者ID或名称",
      "content": "对话内容"
    }
  ]
}
```

### NarrativeMemory（叙事记忆）

```json
{
  "summary_lines": ["事件摘要1", "事件摘要2"],  // 近期事件摘要（短期记忆）
  "key_facts": ["关键事实1"],                    // 关键事实（中期记忆）
  "stable_facts": ["稳定事实1"]                  // 稳定事实（长期记忆，不会改变）
}
```

### TurnTrace（回合追踪）

```json
{
  "turn_id": 12,
  "steps": [
    {
      "step_id": "步骤ID",
      "actor_id": "行动者ID",
      "phase": "player/npc",
      "resolution": {
        "local_narrative": "局部叙事",
        "state_changes": [...]
      }
    }
  ]
}
```

---

## 上下文对比表

| 上下文组件 | DMAgent | StateEvolution | NPCDirector | NarrativeMerger |
|-----------|:-------:|:--------------:|:-----------:|:---------------:|
| request_id | ✅ | ✅ | ✅ | ✅ |
| turn_id | ✅ | ✅ | ✅ | ✅ |
| phase | ✅ | ✅ | ✅ | ✅ |
| world_state_view | ✅ | ✅ | ✅ | ❌ |
| dialogue_memory | ✅ | ✅ | ❌ | ✅ |
| narrative_memory | ✅ | ✅ | ✅ | ✅ |
| turn_trace_so_far | ✅ | ✅ | ✅ | ✅ (as steps) |
| turn_intent | ❌ | ✅ | ❌ | ✅ (in steps) |
| check_result | ❌ | ✅ | ❌ | ❌ |
| truth_anchor | ❌ | ✅ | ❌ | ✅ |
| activated_npc_ids | ❌ | ❌ | ✅ | ❌ |
| npc_world_views | ❌ | ❌ | ✅ | ❌ |
| player_turn_resolution | ❌ | ✅ (NPC) | ✅ | ❌ |
| player_action_summary | ❌ | ❌ | ✅ | ❌ |
| surrounding_context | ❌ | ❌ | ✅ | ❌ |
| constraints | ✅ | ✅ | ✅ | ✅ |
| memory_policy | ✅ | ✅ | ✅ | ✅ |
| extensions | ✅ | ✅ | ✅ | ❌ |

### 图例说明

- ✅ 包含该上下文
- ❌ 不包含该上下文
- ✅ (NPC) 仅在NPC阶段包含
- ✅ (as steps) 以steps形式包含
- ✅ (in steps) 包含在steps中

---

## 附录：数据流图

```
┌─────────────────────────────────────────────────────────────────┐
│                         玩家输入                                 │
└──────────────────────┬──────────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────────────┐
│  DMAgent (意图解析)                                              │
│  - 接收: world_state_view, dialogue_memory, narrative_memory    │
│  - 输出: TurnIntent (意图解释)                                  │
└──────────────────────┬──────────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────────────┐
│  CheckSystem (规则结算)                                          │
│  - 接收: TurnIntent                                              │
│  - 输出: CheckResult (鉴定结果)                                 │
└──────────────────────┬──────────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────────────┐
│  StateEvolution (状态推演) - 玩家阶段                            │
│  - 接收: TurnIntent, CheckResult, truth_anchor                  │
│  - 输出: StateChanges, LocalNarrative                           │
└──────────────────────┬──────────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────────────┐
│  NPCDirector (NPC规划)                                           │
│  - 接收: activated_npcs, npc_world_views, player_resolution     │
│  - 输出: NPCActionPlans                                          │
└──────────────────────┬──────────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────────────┐
│  StateEvolution (状态推演) - NPC阶段                             │
│  - 接收: NPCActionPlan, player_resolution                       │
│  - 输出: StateChanges, LocalNarrative                           │
└──────────────────────┬──────────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────────────┐
│  NarrativeMerger (叙事合并)                                      │
│  - 接收: TurnTraceSteps, narrative_memory                       │
│  - 输出: MergedNarrative, TurnSummary, KeyFacts                 │
└─────────────────────────────────────────────────────────────────┘
```

---

*文档结束*
