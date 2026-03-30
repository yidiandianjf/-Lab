# Debug 系统设计文档

## 1. 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        Game Engine                               │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌────────┐ │
│  │ Input   │  │ State   │  │ NPC     │  │ IO      │  │ Rule   │ │
│  │ System  │  │ Evolution│  │ Director│  │ System  │  │ System │ │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  └───┬────┘ │
│       └─────────────┴─────────────┴─────────────┴─────────┘      │
│                          │                                       │
│                          ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              Debug Logger (统一收集器)                     │   │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐  │   │
│  │  │ Event  │ │ Context│ │ State  │ │ LLM    │ │ Error  │  │   │
│  │  │ Logger │ │ Logger │ │ Logger │ │ Logger │ │ Logger │  │   │
│  │  └───┬────┘ └────┬───┘ └────┬───┘ └────┬───┘ └───┬────┘  │   │
│  └──────┼───────────┼──────────┼──────────┼─────────┼────────┘   │
└─────────┼───────────┼──────────┼──────────┼─────────┼────────────┘
          │           │          │          │         │
          ▼           ▼          ▼          ▼         ▼
┌─────────────────────────────────────────────────────────────────┐
│                      日志存储层                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ 分类日志文件  │  │ 会话总日志    │  │ SQLite (结构化查询)   │   │
│  │ (按类型分割)  │  │ (按对话聚合)  │  │ (可选，用于复杂分析)  │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## 2. 需要监控的关键维度

### 2.1 事件流维度 (Event Flow)
| 监控点 | 内容 | 用途 |
|--------|------|------|
| 玩家输入 | 原始输入、解析后的意图、提取的参数 | 追踪意图识别问题 |
| 指令执行 | 识别到的指令、执行结果、产生的变更 | 追踪指令处理流程 |
| 阶段流转 | Turn 的每个阶段开始/结束、耗时 | 性能分析、流程验证 |
| LLM 调用 | 请求/响应、token 消耗、耗时、重试次数 | LLM 问题排查 |

### 2.2 状态变更维度 (State Changes)
| 监控点 | 内容 | 用途 |
|--------|------|------|
| 变更前快照 | 受影响实体的完整状态 | 对比分析 |
| 变更提案 | LLM 生成的 StateChange 列表 | 验证 LLM 输出 |
| 变更验证 | 每个变更的合法性检查结果 | 追踪被拒绝的变更 |
| 变更应用 | 成功/失败、错误码、级联影响 | 追踪应用问题 |
| 变更后快照 | 受影响实体的完整状态 | 对比验证 |
| 内存 vs IO 一致性 | 内存状态和 IO 层的对比 | 发现同步问题 |

### 2.3 上下文维度 (Context)
| 监控点 | 内容 | 用途 |
|--------|------|------|
| World View | 构建的世界状态视图 | 验证上下文完整性 |
| Dialogue Memory | 对话历史摘要 | 验证记忆系统 |
| Narrative Memory | 叙事上下文 | 验证叙事连贯性 |
| NPC Planning | NPC 的计划和意图 | 验证 NPC 行为逻辑 |
| Prompt 完整内容 | 发送给 LLM 的完整 prompt | 调试 LLM 行为 |

### 2.4 规则系统维度 (Rules)
| 监控点 | 内容 | 用途 |
|--------|------|------|
| 检定触发 | 触发的检定类型、目标值、修正值 | 追踪检定逻辑 |
| 骰子结果 | 原始骰子值、结果判定 | 验证随机性 |
| 规则冲突 | 多个规则同时触发时的优先级决策 | 追踪规则冲突 |
| 条件评估 | 规则条件的评估过程和结果 | 追踪条件判断 |

### 2.5 错误与异常维度 (Errors)
| 监控点 | 内容 | 用途 |
|--------|------|------|
| 异常捕获 | 异常类型、堆栈、上下文变量 | 快速定位问题 |
| LLM 解析失败 | JSON 解析错误、格式错误 | 追踪 LLM 输出问题 |
| 状态不一致 | 检测到的状态冲突 | 发现数据问题 |
| 超时事件 | 操作超时的时间点 | 性能问题分析 |

## 3. 日志分类体系

### 3.1 文件分类

```
logs/
├── sessions/                    # 按会话组织的日志
│   └── 20260328_113045_abc123/  # 会话ID = 日期_时间_随机码
│       ├── master.log           # 总日志（按时间线聚合）
│       ├── timeline.json        # 结构化时间线（用于快速分析）
│       ├── turns/               # 每个回合的详细数据
│       │   ├── turn_001/
│       │   │   ├── full_context.json    # 完整上下文快照
│       │   │   ├── state_before.json    # 状态变更前
│       │   │   ├── state_after.json     # 状态变更后
│       │   │   ├── llm_requests/        # LLM 请求记录
│       │   │   └── state_changes.json   # 变更详情
│       │   └── turn_002/
│       └── summary.json         # 会话摘要
│
├── categorized/                 # 按类型分类的日志（便于按类型查看）
│   ├── events.log              # 事件流日志（最近N天）
│   ├── state_changes.log       # 状态变更日志
│   ├── llm_interactions.log    # LLM 交互日志
│   ├── errors.log              # 错误日志
│   └── performance.log         # 性能日志
│
└── archive/                     # 归档日志
    └── 2026-03/                # 按月归档
```

### 3.2 日志级别定义

```python
class LogLevel:
    DEBUG = "debug"      # 详细调试信息
    INFO = "info"        # 一般信息
    NOTICE = "notice"    # 重要但不紧急（如状态变更）
    WARNING = "warning"  # 警告
    ERROR = "error"      # 错误
    CRITICAL = "critical" # 严重错误
```

### 3.3 事件类型定义

```python
class EventType:
    # 输入相关
    PLAYER_INPUT = "player_input"
    COMMAND_PARSED = "command_parsed"
    
    # Turn 流程
    TURN_START = "turn_start"
    TURN_PHASE_START = "turn_phase_start"
    TURN_PHASE_END = "turn_phase_end"
    TURN_END = "turn_end"
    
    # LLM 交互
    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"
    LLM_RETRY = "llm_retry"
    LLM_ERROR = "llm_error"
    
    # 状态变更
    STATE_CHANGE_PROPOSED = "state_change_proposed"
    STATE_CHANGE_VALIDATED = "state_change_validated"
    STATE_CHANGE_APPLIED = "state_change_applied"
    STATE_CHANGE_FAILED = "state_change_failed"
    STATE_SNAPSHOT = "state_snapshot"
    
    # 检定
    CHECK_TRIGGERED = "check_triggered"
    CHECK_RESOLVED = "check_resolved"
    
    # NPC
    NPC_PLAN_GENERATED = "npc_plan_generated"
    NPC_ACTION_EXECUTED = "npc_action_executed"
    
    # 系统
    ERROR_OCCURRED = "error_occurred"
    WARNING_ISSUED = "warning_issued"
    PERFORMANCE_METRIC = "performance_metric"
```

## 4. 总日志（Master Log）结构

### 4.1 格式设计

采用**可读性与结构化兼顾**的格式：

```
═══════════════════════════════════════════════════════════════════
🎮 SESSION START: 2026-03-28 11:30:45 | SessionID: abc123def
World: mysterious_library | Player: char-player-01
═══════════════════════════════════════════════════════════════════

───────────────────────────────────────────────────────────────────
📝 TURN 001 | 11:30:46 | Input: "撒谎欺骗管理员让其前往走廊"
───────────────────────────────────────────────────────────────────
  [11:30:46.123] ▶️ PHASE: parse_input
  [11:30:46.145] ✅ Command parsed: {type: "action", action: "deceive", target: "char-archivist-01"}
  
  [11:30:46.200] ▶️ PHASE: dm_processing
  [11:30:46.250] 📤 LLM REQUEST [dm_agent]
                  Prompt: 4862 tokens | Model: qwen-max
  [11:30:48.890] 📥 LLM RESPONSE [dm_agent]
                  Duration: 2640ms | Tokens: 523
                  Summary: 玩家尝试欺骗管理员，需要进行APP+POW检定
  
  [11:30:48.900] 🎲 CHECK TRIGGERED
                  Type: deceive | Attribute: app+pow
                  Target: 50 | Roll: 32 | Result: SUCCESS
  
  [11:30:49.100] ▶️ PHASE: state_evolution
  [11:30:49.150] 📤 LLM REQUEST [state_evolution]
  [11:30:52.340] 📥 LLM RESPONSE [state_evolution]
                  Changes proposed: 2
                  ├─ item-book-01.location: "map-room-library-01" → "char-player-01"
                  └─ item-note-01.location: "map-room-library-01" → "char-player-01"
  
  [11:30:52.350] 📝 STATE CHANGES VALIDATED
                  All 2 changes passed validation
  
  [11:30:52.400] 📝 STATE CHANGES APPLIED
                  ├─ item-book-01.location ✓
                  └─ item-note-01.location ✓
                  ⚠️  Cascading updates detected in IO layer:
                      └─ char-player-01.inventory updated (item-book-01, item-note-01 added)
  
  [11:30:52.500] ▶️ PHASE: npc_response
  [11:30:52.550] 🤖 NPC [char-archivist-01] PLAN
                  Intent: investigate_corridor
                  Action: move_to "map-room-corridor-01"
  
  [11:30:53.000] ✅ TURN 001 COMPLETE
                  Duration: 6877ms | Narrative: 156 chars
───────────────────────────────────────────────────────────────────

🎒 PLAYER INVENTORY CHECK | 11:30:55
   Requested via: \\inventory
   Memory state: []
   IO state: ["item-book-01", "item-note-01"]
   ⚠️  INCONSISTENCY DETECTED: Memory and IO state differ!
   
═══════════════════════════════════════════════════════════════════
🔚 SESSION END: 2026-03-28 11:35:22 | Duration: 4m 37s
Total Turns: 12 | LLM Calls: 34 | Errors: 1
═══════════════════════════════════════════════════════════════════
```

### 4.2 结构化时间线 (timeline.json)

```json
{
  "session_id": "abc123def",
  "start_time": "2026-03-28T11:30:45",
  "end_time": "2026-03-28T11:35:22",
  "world": "mysterious_library",
  "player_id": "char-player-01",
  "summary": {
    "total_turns": 12,
    "total_llm_calls": 34,
    "total_errors": 1,
    "total_warnings": 3
  },
  "turns": [
    {
      "turn_number": 1,
      "timestamp": "2026-03-28T11:30:46",
      "input": "撒谎欺骗管理员让其前往走廊",
      "phases": [
        {
          "name": "parse_input",
          "start": "11:30:46.123",
          "end": "11:30:46.145",
          "duration_ms": 22
        },
        {
          "name": "dm_processing",
          "start": "11:30:46.200",
          "end": "11:30:48.900",
          "duration_ms": 2700,
          "llm_calls": [
            {
              "agent": "dm_agent",
              "request_tokens": 4862,
              "response_tokens": 523,
              "duration_ms": 2640
            }
          ]
        },
        {
          "name": "state_evolution",
          "start": "11:30:49.100",
          "end": "11:30:52.400",
          "duration_ms": 3300,
          "state_changes": [
            {
              "id": "item-book-01",
              "field": "location",
              "old_value": "map-room-library-01",
              "new_value": "char-player-01"
            },
            {
              "id": "item-note-01",
              "field": "location",
              "old_value": "map-room-library-01",
              "new_value": "char-player-01"
            }
          ],
          "cascading_updates": [
            {
              "entity": "char-player-01",
              "field": "inventory",
              "added": ["item-book-01", "item-note-01"]
            }
          ]
        }
      ],
      "issues": []
    }
  ],
  "issues": [
    {
      "turn": 1,
      "type": "state_inconsistency",
      "severity": "warning",
      "description": "Memory and IO state differ for player inventory",
      "detected_at": "11:30:55.000"
    }
  ]
}
```

## 5. 核心组件设计

### 5.1 DebugLogger 类

```python
class DebugLogger:
    """统一调试日志记录器"""
    
    def __init__(self, session_id: str, log_dir: str = "logs"):
        self.session_id = session_id
        self.start_time = datetime.now()
        
        # 创建目录结构
        self.session_dir = Path(log_dir) / "sessions" / session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        (self.session_dir / "turns").mkdir(exist_ok=True)
        
        # 初始化各类日志处理器
        self._init_handlers()
        
        # 当前 turn 上下文
        self._current_turn = 0
        self._current_phase = None
        
    def _init_handlers(self):
        """初始化日志处理器"""
        # 主日志（人类可读）
        self.master_handler = MasterLogHandler(self.session_dir / "master.log")
        
        # 结构化时间线
        self.timeline = TimelineRecorder(self.session_dir / "timeline.json")
        
        # 分类日志（同时写入公共文件）
        self.event_handler = CategorizedHandler("logs/categorized/events.log")
        self.state_handler = CategorizedHandler("logs/categorized/state_changes.log")
        self.llm_handler = CategorizedHandler("logs/categorized/llm_interactions.log")
        self.error_handler = CategorizedHandler("logs/categorized/errors.log")
        
    def start_turn(self, player_input: str):
        """开始新回合"""
        self._current_turn += 1
        self._turn_dir = self.session_dir / "turns" / f"turn_{self._current_turn:03d}"
        self._turn_dir.mkdir(exist_ok=True)
        
        event = {
            "type": EventType.TURN_START,
            "turn": self._current_turn,
            "timestamp": datetime.now().isoformat(),
            "player_input": player_input
        }
        self._log_event(event)
        
    def start_phase(self, phase_name: str):
        """开始阶段"""
        self._current_phase = phase_name
        self._phase_start_time = datetime.now()
        
        self._log_event({
            "type": EventType.TURN_PHASE_START,
            "turn": self._current_turn,
            "phase": phase_name,
            "timestamp": self._phase_start_time.isoformat()
        })
        
    def end_phase(self, result: Dict = None):
        """结束阶段"""
        duration = (datetime.now() - self._phase_start_time).total_seconds() * 1000
        
        self._log_event({
            "type": EventType.TURN_PHASE_END,
            "turn": self._current_turn,
            "phase": self._current_phase,
            "duration_ms": duration,
            "result": result
        })
        
    def log_llm_request(self, agent: str, prompt: str, model: str, tokens: int):
        """记录 LLM 请求"""
        # 保存完整 prompt 到文件
        prompt_file = self._turn_dir / f"llm_{agent}_request.txt"
        prompt_file.write_text(prompt, encoding="utf-8")
        
        self._log_event({
            "type": EventType.LLM_REQUEST,
            "agent": agent,
            "model": model,
            "tokens": tokens,
            "prompt_file": str(prompt_file),
            "timestamp": datetime.now().isoformat()
        }, handler=self.llm_handler)
        
    def log_llm_response(self, agent: str, response: str, duration_ms: int):
        """记录 LLM 响应"""
        response_file = self._turn_dir / f"llm_{agent}_response.txt"
        response_file.write_text(response, encoding="utf-8")
        
        self._log_event({
            "type": EventType.LLM_RESPONSE,
            "agent": agent,
            "duration_ms": duration_ms,
            "response_file": str(response_file),
            "timestamp": datetime.now().isoformat()
        }, handler=self.llm_handler)
        
    def log_state_snapshot(self, game_state: GameState, label: str):
        """记录状态快照"""
        snapshot_file = self._turn_dir / f"state_{label}.json"
        snapshot = self._serialize_game_state(game_state)
        snapshot_file.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
        
        self._log_event({
            "type": EventType.STATE_SNAPSHOT,
            "label": label,
            "file": str(snapshot_file),
            "timestamp": datetime.now().isoformat()
        }, handler=self.state_handler)
        
    def log_state_changes(self, changes: List[StateChange], validation_result: ValidationResult = None):
        """记录状态变更"""
        event = {
            "type": EventType.STATE_CHANGE_PROPOSED,
            "turn": self._current_turn,
            "changes": [self._serialize_change(c) for c in changes],
            "timestamp": datetime.now().isoformat()
        }
        
        if validation_result:
            event["validation"] = {
                "passed": validation_result.is_valid,
                "errors": validation_result.errors
            }
            event["type"] = EventType.STATE_CHANGE_VALIDATED if validation_result.is_valid else EventType.STATE_CHANGE_FAILED
            
        self._log_event(event, handler=self.state_handler)
        
    def log_state_change_applied(self, change: StateChange, error_code: int, cascading_effects: List[Dict] = None):
        """记录变更应用结果"""
        self._log_event({
            "type": EventType.STATE_CHANGE_APPLIED if error_code == 0 else EventType.STATE_CHANGE_FAILED,
            "change": self._serialize_change(change),
            "error_code": error_code,
            "cascading_effects": cascading_effects or [],
            "timestamp": datetime.now().isoformat()
        }, handler=self.state_handler)
        
    def check_consistency(self, memory_state: GameState, io_state: GameState):
        """检查内存与 IO 层一致性"""
        differences = self._compare_states(memory_state, io_state)
        
        if differences:
            self._log_event({
                "type": "state_inconsistency",
                "severity": "warning",
                "turn": self._current_turn,
                "differences": differences,
                "timestamp": datetime.now().isoformat()
            }, level=LogLevel.WARNING, handler=self.error_handler)
            
    def end_turn(self, narrative_output: str):
        """结束回合"""
        self._log_event({
            "type": EventType.TURN_END,
            "turn": self._current_turn,
            "narrative": narrative_output,
            "timestamp": datetime.now().isoformat()
        })
        
    def end_session(self, game_state: GameState = None):
        """结束会话"""
        duration = (datetime.now() - self.start_time).total_seconds()
        
        summary = {
            "session_id": self.session_id,
            "duration_seconds": duration,
            "total_turns": self._current_turn,
            "end_time": datetime.now().isoformat()
        }
        
        if game_state:
            self.log_state_snapshot(game_state, "final")
            
        self.timeline.finalize(summary)
        self.master_handler.finalize(summary)
```

### 5.2 自动一致性检查

```python
class ConsistencyChecker:
    """自动状态一致性检查器"""
    
    def __init__(self, logger: DebugLogger, io_system: IOSystem):
        self.logger = logger
        self.io = io_system
        
    def verify_after_change(self, entity_id: str, field: str, game_state: GameState):
        """在变更应用后验证一致性"""
        # 从 IO 层重新加载实体
        if entity_id.startswith("char-"):
            io_entity = self.io.get_character(entity_id)
            memory_entity = game_state.characters.get(entity_id)
        elif entity_id.startswith("item-"):
            io_entity = self.io.get_item(entity_id)
            memory_entity = game_state.items.get(entity_id)
        else:
            return
            
        # 对比关键字段
        differences = []
        
        if field == "location" and hasattr(memory_entity, 'location'):
            if memory_entity.location != io_entity.location:
                differences.append({
                    "field": "location",
                    "memory": memory_entity.location,
                    "io": io_entity.location
                })
                
        # 对于物品，检查 inventory 同步
        if entity_id.startswith("item-") and field == "location":
            # 检查持有者 inventory
            if io_entity.location and io_entity.location.startswith("char-"):
                holder_io = self.io.get_character(io_entity.location)
                holder_memory = game_state.characters.get(io_entity.location)
                
                if holder_io and holder_memory:
                    io_inv = set(holder_io.inventory)
                    mem_inv = set(holder_memory.inventory)
                    
                    if io_inv != mem_inv:
                        differences.append({
                            "entity": holder_memory.id,
                            "field": "inventory",
                            "memory": list(mem_inv),
                            "io": list(io_inv),
                            "added_in_io": list(io_inv - mem_inv),
                            "missing_in_memory": list(mem_inv - io_inv)
                        })
                        
        if differences:
            self.logger.log_inconsistency(
                trigger_change=f"{entity_id}.{field}",
                differences=differences
            )
```

### 5.3 使用示例

```python
class GameEngine:
    def __init__(self):
        # ... 其他初始化 ...
        self.debug_logger = DebugLogger(
            session_id=self._generate_session_id(),
            log_dir="logs"
        )
        self.consistency_checker = ConsistencyChecker(
            self.debug_logger, self.io
        )
        
    def process_turn(self, player_input: str):
        # 开始回合
        self.debug_logger.start_turn(player_input)
        
        # 记录初始状态
        self.debug_logger.log_state_snapshot(self.game_state, "before")
        
        # 阶段 1: 输入解析
        self.debug_logger.start_phase("parse_input")
        parsed = self.input_system.parse(player_input)
        self.debug_logger.end_phase({"parsed_command": parsed})
        
        # 阶段 2: DM 处理
        self.debug_logger.start_phase("dm_processing")
        self.debug_logger.log_llm_request(
            agent="dm_agent",
            prompt=dm_prompt,
            model="qwen-max",
            tokens=len(dm_prompt)
        )
        dm_output = self.dm_agent.process(...)
        self.debug_logger.log_llm_response(
            agent="dm_agent",
            response=dm_output.raw_response,
            duration_ms=dm_output.duration_ms
        )
        self.debug_logger.end_phase({"dm_output": dm_output.summary()})
        
        # 阶段 3: 状态推演
        self.debug_logger.start_phase("state_evolution")
        self.debug_logger.log_llm_request(
            agent="state_evolution",
            prompt=se_prompt,
            model="qwen-max",
            tokens=len(se_prompt)
        )
        evolution_result = self.state_agent.evolve(...)
        self.debug_logger.log_llm_response(
            agent="state_evolution",
            response=evolution_result.raw_response,
            duration_ms=evolution_result.duration_ms
        )
        
        # 记录变更
        self.debug_logger.log_state_changes(
            changes=evolution_result.changes,
            validation_result=evolution_result.validation
        )
        self.debug_logger.end_phase({"change_count": len(evolution_result.changes)})
        
        # 阶段 4: 应用变更
        self.debug_logger.start_phase("apply_changes")
        for change in evolution_result.changes:
            error_code = self.io.apply_state_change(change)
            
            # 检测级联更新
            cascading = self._detect_cascading_effects(change)
            
            self.debug_logger.log_state_change_applied(
                change=change,
                error_code=error_code,
                cascading_effects=cascading
            )
            
            if error_code == 0:
                self._sync_state_change(change)
                
        # 一致性检查！
        io_state = self._reload_state_from_io()
        self.consistency_checker.verify_after_all_changes(
            self.game_state, io_state
        )
        
        self.debug_logger.end_phase({"applied": len(evolution_result.changes)})
        
        # 记录最终状态
        self.debug_logger.log_state_snapshot(self.game_state, "after")
        
        # 结束回合
        self.debug_logger.end_turn(narrative_output)
        
        return narrative_output
```

## 6. 日志查看工具

### 6.1 命令行工具

```bash
# 查看最新会话的主日志
python -m debug_tools.view logs/sessions/latest/master.log

# 按类型过滤
python -m debug_tools.view logs/sessions/latest/master.log --filter "STATE_CHANGE"

# 查看结构化时间线
python -m debug_tools.timeline logs/sessions/latest/timeline.json

# 对比两个状态快照
python -m debug_tools.diff logs/sessions/latest/turns/turn_001/state_before.json \
                            logs/sessions/latest/turns/turn_001/state_after.json

# 分析性能
python -m debug_tools.analyze logs/sessions/latest/timeline.json --metric performance

# 查找不一致问题
python -m debug_tools.analyze logs/sessions/latest/timeline.json --metric consistency
```

### 6.2 Web 界面（可选）

```python
# 简单的 Flask/FastAPI 应用，提供：
# - 会话列表浏览
# - Turn 时间线可视化
# - 状态变更对比
# - LLM Prompt/Response 查看
# - 性能图表
```

## 7. 配置建议

```python
# debug_config.yaml
debug:
  enabled: true
  log_level: "debug"  # debug, info, notice, warning, error
  
  # 输出控制
  outputs:
    master_log: true      # 总日志（必须）
    timeline_json: true   # 结构化时间线
    categorized: true     # 分类日志
    snapshots: true       # 状态快照
    llm_prompts: true     # LLM prompt 完整保存
    
  # 性能相关
  performance:
    track_llm_latency: true
    track_phase_duration: true
    track_memory_usage: false  # 可选
    
  # 一致性检查
  consistency:
    check_after_each_change: true
    check_after_turn: true
    warn_on_inconsistency: true
    
  # 保留策略
  retention:
    keep_sessions: 30      # 保留30个会话
    archive_after_days: 7  # 7天后归档
```

## 8. 关键收益

1. **问题快速定位**：通过总日志的时间线，一眼看出哪个阶段出问题
2. **状态变更可追溯**：每个变更都有 before/after 对比，易于发现同步问题
3. **LLM 行为可分析**：完整的 prompt/response 保存，便于调优
4. **自动化检测**：一致性检查主动发现问题，而不是等用户报告
5. **性能可监控**：各阶段耗时清晰可见，便于优化
