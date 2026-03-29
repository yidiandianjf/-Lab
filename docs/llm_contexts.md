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
  
  // 记忆策略 - 控制记忆的使用方式
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
    
    // 回合意图 - DMAgent解析后的结构化意图
    "turn_intent": {
      "actor_id": "char-player-01",           // 行动者ID
      "raw_input_text": "我想撬开保险箱",     // 原始输入
      "intent_text": "使用撬锁工具打开保险箱", // 解析后的意图
      "interaction_type": "action",            // 交互类型
      
      // 检定计划
      "check_plan": {
        "check_needed": true,                  // 是否需要检定
        "check_type": "非对抗鉴定",            // 检定类型
        "attributes": ["dex"],                 // 相关属性（敏捷）
        "target_id": "item-safe-01",          // 目标ID
        "difficulty": "困难"                   // 难度
      },
      
      // 激活提示 - 是否需要NPC响应
      "activation_hint": {
        "response_needed_hint": true,          // 需要NPC响应
        "preferred_actor_id": "char-guard-01", // 优先响应的NPC
        "candidate_npc_ids_hint": []           // 候选NPC列表
      }
    },
    
    // 检定结果 - CheckSystem的输出
    "check_result": {
      "result": "success",           // 结果：success/failure
      "dice_roll": 45,               // 骰子点数
      "target_value": 60,            // 目标值（属性值）
      "actor_value": 60,             // 行动者属性值
      "detail": "检定成功，骰子45 <= 目标60" // 详细说明
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
        "description.public",  // 公开描述列表
        "memory.log"           // 记忆日志
      ],
      
      // 更新规则
      "update_rule": {
        "must_use_existing_field": true,  // 必须更新已存在的字段
        "forbid_schema_break": true       // 禁止破坏数据结构
      },
      
      // 添加规则
      "add_rule": {
        "target_must_be_list": true,      // 只能向列表类型字段添加
        "forbid_nested_list_add": true    // 禁止嵌套列表添加
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
      }
    }
  },
  
  "memory_policy": {
    "drift_anchor_required": true,           // 必须遵守事实锚点
    "max_generated_narrative_chars": 800     // 生成叙事的最大字符数
  },
  
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
