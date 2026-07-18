# Mini Agent Runtime

[![test](https://github.com/taide05/mini-agent-runtime/actions/workflows/test.yml/badge.svg)](https://github.com/taide05/mini-agent-runtime/actions/workflows/test.yml)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A minimal agent runtime built from scratch — ReAct loop, pluggable tools, tree-based sessions, typed SSE events. Inspired by [Pi](https://github.com/earendil-works/pi).

**No LangChain. No LangGraph.** Every line of the agent loop is explicit.

## Architecture

```
POST /sessions/{id}/run  →  AgentLoop.run()
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
                 LLM call    Tool exec    Stop check
                    │            │            │
                    ▼            ▼            ▼
              ┌──────────────────────────────────┐
              │           EventBus               │
              │   PostgreSQL  │  Queue  │  Redis │
              └──────────────────────────────────┘
                                 │
Client  ◀── SSE /stream/{id}  ──┘
```

## Quick Start

```bash
# 1. Set your API key
cp .env.example .env
# Edit .env → DEEPSEEK_API_KEY=sk-...

# 2. Start infrastructure
docker compose up -d postgres redis

# 3. Install and run
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python -m uvicorn app.main:app --reload

# 4. Open http://localhost:8000/docs
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/sessions` | Create a session |
| GET | `/sessions` | List sessions |
| GET | `/sessions/{id}` | Session detail |
| DELETE | `/sessions/{id}` | Delete session |
| GET | `/sessions/{id}/tree` | Full session tree |
| POST | `/sessions/{id}/run` | Trigger agent run |
| GET | `/sessions/{id}/stream` | SSE event stream |
| POST | `/sessions/{id}/branch` | Branch from any node |
| GET | `/nodes/{id}` | Node detail |
| GET | `/nodes/{id}/events` | Node events (paginated) |
| GET | `/tools` | List tools |
| POST | `/tools` | Register tool at runtime |
| DELETE | `/tools/{name}` | Unregister tool |
| GET | `/health` | PostgreSQL + Redis check |

## Key Design Decisions

**ReAct from scratch, not LangGraph.**
The loop is ~120 lines. function calling mode (not text parsing) for tool invocation. Tool errors fed back to LLM for self-correction. Max-iteration fallback asks LLM to summarize rather than returning empty.

**Sessions are trees, not linear logs.**
Each node has a `parent_id`. Branch from any point to explore alternative reasoning paths — zero cost over linear storage.

**Typed SSE events, not free-form strings.**
Every event has a fixed schema: `thinking` | `text` | `tool_call` | `tool_result` | `error` | `status`. Enables type-safe UI rendering and structured audit queries.

**Runtime-pluggable tools.**
`POST /tools` registers a new tool without restart. `DELETE /tools/{name}` removes it. 3 built-in: calculator, current_time, read_file.

**4 tools. That's enough.**
Pi ships with 4 tools and has 70K+ stars. Tool count doesn't make a better agent — loop quality does.

## Tech Stack

FastAPI · PostgreSQL · Redis · DeepSeek API · Docker Compose · Nginx · SSE

## Tests

```bash
.venv\Scripts\python -m pytest tests/unit/ -v   # 11 tests (no DB needed)
.venv\Scripts\python tests/manual_smoke_test.py   # 3 real-LLM tests
```
