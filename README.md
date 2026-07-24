# Mini Agent Runtime

[![test](https://github.com/taide05/mini-agent-runtime/actions/workflows/test.yml/badge.svg)](https://github.com/taide05/mini-agent-runtime/actions/workflows/test.yml)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

一个从零手写的 Agent 运行时——ReAct 主循环、事件驱动通信、树形会话、可插拔工具系统全部自己实现，不依赖 LangChain/LangGraph。设计理念受 [Pi](https://github.com/earendil-works/pi) 启发。

## 为什么值得关注

大多数 Agent 项目是对 LangChain/LangGraph 的封装——调几个 API、配几个 node 就完事了。这没问题，但面试官想看的是你**理解 Agent 循环里每一行在干什么**。

这个项目把 ReAct 循环拆到了最底层：LLM 怎么调用、工具结果怎么喂回去、max_iteration 兜底策略怎么写、事件怎么广播给 SSE 客户端、会话树怎么用 parent_id 实现零成本分叉。120 行主循环代码，没有黑盒。

## 核心特性

- **手写 ReAct 循环（~120 行）**：function calling 模式而非文本解析，工具错误反馈给 LLM 自纠正，max_iteration 兜底让 LLM 总结而非返回空
- **事件驱动架构**：6 种类型化 SSE 事件（thinking / text / tool_call / tool_result / error / status），EventBus 解耦循环与客户端，事件扁平化到顶层方便前端消费
- **树形会话模型**：每个 node 有 parent_id，从任意节点分叉探索替代推理路径。`assemble_messages_from_chain()` 沿 parent 链回溯组装完整上下文
- **运行时热插拔工具**：`POST /tools` 注册新工具无需重启，`DELETE /tools/{name}` 即删。3 个内置工具（calculator / current_time / read_file），工具注册表用 `asyncio.Lock` 保证并发安全
- **两套业务包装**：客服分流 Triage Agent（5 种意图分类 + 风险等级路由 + 6 个领域工具 + 331 条 eval 用例）和自纠正能力评测（10 种错误类型 100 个场景），展示 Runtime 不是玩具

## 快速开始

```bash
# 1. 配置
cp .env.example .env
# .env 中设置 DEEPSEEK_API_KEY=sk-xxx

# 2. 启动基础设施
docker compose up -d postgres redis

# 3. 安装 + 启动
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python -m uvicorn app.main:app --reload

# 4. 打开 http://localhost:8000/docs
```

## 架构概览

```
HTTP 请求
    │
    ▼
┌─────────────┐     ┌─────────────────────────────────┐
│   Router     │ ──► │         AgentService             │
│  5 路由模块   │     │  组装消息链 → 创建节点 → 调循环   │
└─────────────┘     └────────────┬────────────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
      ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
      │  LLMClient   │  │ ToolRegistry │  │  AgentLoop   │
      │ DeepSeek API │  │  可插拔工具   │  │  ReAct 主循环  │
      │ 3 次重试+退避 │  │ async.Lock   │  │  ~120 行     │
      └──────────────┘  └──────────────┘  └──────┬───────┘
                                                  │
                                          ┌───────┴───────┐
                                          │   EventBus     │
                                          │ 内存发布/订阅    │
                                          │ 按 session 隔离  │
                                          └───────┬───────┘
                                                  │
                    ┌─────────────────────────────┼─────────────────┐
                    ▼                             ▼                 ▼
            ┌──────────────┐            ┌──────────────┐  ┌──────────────┐
            │  SSE Stream  │            │  AgentEvent  │  │   ToolCall   │
            │ 实时推送客户端 │            │  批量写 PostgreSQL│  │  审计追踪    │
            └──────────────┘            └──────────────┘  └──────────────┘
```

### ReAct 循环细节

```
iteration 1..max_iterations:
  ① LLM.chat(messages, tools)
  ② 有 thinking → 发 THINKING 事件
  ③ 有 content → 发 TEXT 事件
  ④ 无 tool_calls → 结束，返回 final_answer
  ⑤ 有 tool_calls → 逐个执行：
      发 TOOL_CALL 事件 → 执行工具 → 发 TOOL_RESULT 事件（含耗时/错误）
      工具报错不炸循环，错误信息作为 tool_result 喂回 LLM 让它重试
  ⑥ 回到 ①

for...else（跑满迭代未结束）:
  发 STATUS 事件（stop_reason=max_iterations）
  最后一次 LLM 调用不含 tools，让 LLM 基于已有信息给最佳总结
```

### 会话树模型

```
Session
  └── Node A (user, root, parent_id=null)
        └── Node B (assistant, depth=1, parent=A)
              ├── Node C (user, depth=2, parent=B)     ← 主干
              │     └── Node D (assistant, depth=3)
              └── Node E (user, depth=2, parent=B)     ← 分叉（从 B 节点分支）
                    └── ...
```

分叉只需要创建新的 user node 并设 parent_id 指向 B，零额外存储成本。`assemble_messages_from_chain()` 沿 parent 链回溯到 root，再反转得到时间序上下文。

## 关键技术决策

**手写循环而非 LangGraph**。LangGraph 的 `StateGraph` 为复杂多 Agent 编排提供了 value，但单 Agent ReAct 场景下它隐藏了控制流。这个项目的 120 行显式循环让面试官看到你理解：消息怎么积累、工具调用怎么喂回、异常怎么兜底。面试时讨论这个比讨论"我配了几个 LangGraph node"有深度得多。

**事件扁平化到顶层而非嵌套 payload**。`TOOL_RESULT` 事件是 `{"tool_name": "calc", "result": 4}` 而非 `{"type": "tool_result", "payload": {...}}`。前端 SSE 消费者可以直接解构字段而不用多一层嵌套访问。类型安全通过 6 种固定 EventType 保证，不会出现 free-form string。

## 量化指标

| 指标 | 值 | 说明 |
|------|-----|------|
| 主循环行数 | 120 | ReAct 核心逻辑，不含注释空行 |
| 内置工具数 | 3 | calculator / current_time / read_file |
| API 端点 | 13 | 覆盖 session/node/tool/agent/stream/branch/triage |
| SSE 事件类型 | 6 | thinking / text / tool_call / tool_result / error / status |
| Triage eval 用例 | 331 | 100 标注 + 231 边界，覆盖 5 种意图类别 |
| 自纠正 eval 用例 | 100 | 10 种错误类型，测试 LLM 读错误信息重试的能力 |
| 单元测试 | 33 | 覆盖 agent_loop / event_bus / tool_registry / session_tree / triage_tools |

## 技术栈

FastAPI · PostgreSQL（SQLAlchemy 2.0 + session tree） · Redis（async） · DeepSeek API · SSE（sse-starlette） · Docker Compose · Nginx · Pydantic v2 · pytest-asyncio

## API 端点

| Method | Path | 说明 |
|--------|------|------|
| POST | `/sessions` | 创建会话 |
| GET | `/sessions` | 会话列表（最近 50） |
| GET | `/sessions/{id}` | 会话详情 + 节点数 |
| DELETE | `/sessions/{id}` | 删除会话（级联） |
| GET | `/sessions/{id}/tree` | 完整会话树（nodes + edges） |
| POST | `/sessions/{id}/run` | 触发 Agent 运行 |
| GET | `/sessions/{id}/stream` | SSE 事件流（实时推送） |
| POST | `/sessions/{id}/branch` | 从任意节点分叉 |
| GET | `/nodes/{id}` | 节点详情 + 子节点 |
| GET | `/nodes/{id}/events` | 节点事件列表（按 seq 排序） |
| GET | `/tools` | 已注册工具列表 |
| POST | `/tools` | 运行时注册工具 |
| DELETE | `/tools/{name}` | 卸载工具 |
| GET | `/health` | PostgreSQL + Redis 连通检查 |

## 项目结构

```
app/
├── core/              # Agent 运行时核心（框架无关）
│   ├── agent_loop.py     # ReAct 主循环（120 行）
│   ├── event_bus.py      # 内存发布/订阅事件系统
│   ├── tool_registry.py  # 可插拔工具注册表
│   ├── llm_client.py     # DeepSeek API 封装（3 次重试）
│   ├── event_types.py    # EventType + StopReason 枚举
│   └── agent_config.py   # Agent 运行参数
├── routers/           # FastAPI 路由层
├── services/          # 业务编排层（session/agent/tool/event）
├── tools/             # 内置工具实现
├── business/          # 业务包装（客服分流 Triage Agent）
├── models.py          # SQLAlchemy ORM（session/node/event/tool_call）
├── schemas.py         # Pydantic 请求/响应模型
├── config.py          # pydantic-settings 配置
├── database.py        # PostgreSQL 连接
└── redis.py           # Redis 连接（懒初始化单例）
```

## License

MIT
