from __future__ import annotations

import ast
import operator


async def calculator(expression: str) -> dict:
    """Evaluate a mathematical expression safely."""
    allowed = {
        ast.Add: operator.add, ast.Sub: operator.sub,
        ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.USub: operator.neg,
    }

    def _eval(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.BinOp):
            return allowed[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            return allowed[type(node.op)](_eval(node.operand))
        raise ValueError(f"Unsupported: {type(node).__name__}")

    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval(tree.body)
        return {"expression": expression, "result": result}
    except Exception as e:
        return {"expression": expression, "error": str(e)}


async def current_time(timezone_name: str = "UTC") -> dict:
    from datetime import datetime, timedelta, timezone as tz

    offsets = {
        "UTC": 0, "EST": -5, "CST": -6, "MST": -7, "PST": -8,
        "CET": 1, "EET": 2, "IST": 5.5, "JST": 9, "AEST": 10,
    }
    offset = offsets.get(timezone_name.upper(), 0)
    now = datetime.now(tz(timedelta(hours=offset)))
    return {
        "datetime": now.isoformat(),
        "timezone": timezone_name.upper(),
        "offset_hours": offset,
    }


async def read_file(path: str, max_lines: int = 200) -> dict:
    from pathlib import Path

    allowed_dirs = [Path.cwd()]
    p = Path(path).resolve()
    if not any(str(p).startswith(str(d)) for d in allowed_dirs):
        return {"error": f"Access denied: {path}"}

    try:
        content = p.read_text(encoding="utf-8")
        lines = content.splitlines()
        if len(lines) > max_lines:
            lines = lines[:max_lines]
        return {"path": str(p), "lines": lines, "total_lines": len(content.splitlines())}
    except FileNotFoundError:
        return {"path": str(p), "error": "File not found"}
    except Exception as e:
        return {"path": str(p), "error": str(e)}


BUILTIN_TOOLS = [
    {
        "name": "calculator",
        "description": "Evaluate a mathematical expression. Supports +, -, *, /, **, and parentheses.",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Math expression, e.g. '2 + 3 * 4'"}
            },
            "required": ["expression"],
        },
        "fn": calculator,
    },
    {
        "name": "current_time",
        "description": "Get the current date and time for a timezone.",
        "parameters": {
            "type": "object",
            "properties": {
                "timezone_name": {
                    "type": "string",
                    "description": "Timezone abbreviation: UTC, EST, CST, PST, CET, IST, JST, etc.",
                    "default": "UTC",
                }
            },
            "required": [],
        },
        "fn": current_time,
    },
    {
        "name": "read_file",
        "description": "Read content from a local file. Limited to the current working directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative or absolute file path"},
                "max_lines": {"type": "integer", "description": "Maximum lines to read", "default": 200},
            },
            "required": ["path"],
        },
        "fn": read_file,
    },
]
