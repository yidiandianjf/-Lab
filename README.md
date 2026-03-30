# COC 文字冒险游戏引擎

基于 LLM 驱动的克苏鲁的呼唤（Call of Cthulhu）文字冒险游戏框架。

## 特性

- **LLM 驱动叙事**：使用大语言模型生成动态叙事和NPC响应
- **双轨数据流**：自然语言与结构化数据双向转换
- **完整COC规则**：支持技能检定、SAN值、HP等核心机制
- **NPC系统**：智能NPC导演系统，支持队列和响应式两种模式
- **存档系统**：支持游戏进度保存和读取

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 LLM

复制示例配置文件并填入你的 API Key：

```bash
cp config/llm.json.example config/llm.json
```

编辑 `config/llm.json`：

```json
{
  "api_key": "your-api-key-here",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4",
  "temperature": 0.0,
  "max_tokens": 4096,
  "timeout": 100.0,
  "enable_thinking": false,
  "structured_output": true
}
```

支持的环境变量（优先级高于配置文件）：

- `LLM_API_KEY` - API 密钥
- `LLM_BASE_URL` - API 基础地址
- `LLM_MODEL` - 模型名称

### 3. 启动游戏

```bash
# 启动新游戏
python src/main.py

# 指定玩家名称
python src/main.py --name "调查员名称"

# 加载存档
python src/main.py --load save_name
```

## 游戏命令

在游戏中可以使用以下命令：

- `\status` - 查看角色状态
- `\inventory` 或 `\i` - 查看背包
- `\look` 或 `\l` - 查看当前场景
- `\move to <地图ID>` - 移动到相邻场景
- `\save [存档名]` - 保存游戏
- `\load <存档名>` - 加载存档
- `\help` - 显示帮助

## 项目结构

```
.
├── config/                 # 配置文件
│   ├── llm.json           # LLM配置（需自行创建）
│   ├── llm.json.example   # LLM配置示例
│   └── world/             # 世界配置
│       └── mysterious_library/  # 示例世界
├── src/                    # 源代码
│   ├── agent/             # AI代理
│   │   ├── dm_agent.py    # DM代理
│   │   ├── state_evolution.py  # 状态推演
│   │   └── npc/           # NPC系统
│   ├── engine/            # 游戏引擎
│   │   └── game_engine.py # 主引擎
│   ├── data/              # 数据模型和IO
│   │   ├── models.py      # 数据模型
│   │   └── io_system.py   # IO系统
│   └── main.py            # 入口文件
├── tests/                  # 测试
├── docs/                   # 文档
└── data/saves/            # 存档目录
```

## 运行测试

```bash
# 运行所有测试
python -m unittest discover tests

# 运行回归测试
python -m unittest tests.test_regression_flow
```

## 配置说明

### 世界配置

世界配置位于 `config/world/<world_name>/`，包含：

- `world.json` - 世界清单（玩家ID、起始地图、回合顺序）
- `characters/*.json` - 角色定义
- `items/*.json` - 物品定义
- `maps/*.json` - 地图/房间定义
- `endings/*.json` - 结局条件

### NPC响应模式

支持两种NPC响应模式：

1. **queue模式(未完成不要选) :**玩家输入前先处理NPC回合
2. **reactive模式（默认）**：由DM Agent决定是否触发NPC响应

在 `config/llm.json` 中设置：

```json
{
  "npc_response_mode": "queue"  // 或 "reactive"
}
```

## 技术架构

```
玩家输入 → DM Agent → 规则系统 → 状态推演 → IO系统 → 游戏状态更新
              ↓
         NPC导演系统（可选）
```

- **DM Agent**：解析玩家意图，决定是否需要检定
- **规则系统**：执行COC技能检定
- **状态推演**：根据检定结果推演世界变化
- **NPC导演**：决定NPC行为意图
- **IO系统**：持久化游戏状态

## 许可证

MIT License

## 致谢

- 克苏鲁的呼唤（Call of Cthulhu）是混沌元素（Chaosium）的注册商标
- 本项目仅用于学习和研究目的

