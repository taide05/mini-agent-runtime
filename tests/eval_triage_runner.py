"""客服分流 Agent 评测脚本 (N=100)。

.venv\Scripts\python tests/eval_triage_runner.py
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.business.customer_service.config import TRIAGE_SYSTEM_PROMPT, INTENTS, CONFIDENCE_THRESHOLD
from app.business.customer_service.tools import TRIAGE_TOOLS
from app.core.agent_config import AgentConfig
from app.core.agent_loop import run_agent_loop
from app.core.event_bus import EventBus
from app.core.llm_client import LLMClient
from app.core.tool_registry import ToolDefinition, ToolRegistry
from tests.eval_triage_dataset import TEST_CASES


async def build_triage_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for td in TRIAGE_TOOLS:
        await registry.register(ToolDefinition(
            name=td["name"], description=td["description"],
            parameters=td["parameters"], fn=td["fn"], source="triage",
        ))
    return registry


def extract_classify_result(events: list[dict]) -> dict | None:
    for event in events:
        if event.get("type") == "tool_result" and event.get("tool_name") == "classify_intent":
            result = event.get("result", {})
            if isinstance(result, dict) and "category" in result:
                return result
    return None


async def run_one(query: str, registry: ToolRegistry, llm: LLMClient, config: AgentConfig) -> dict:
    messages = [
        {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ]
    event_bus = EventBus()

    start = time.monotonic()
    try:
        state = await run_agent_loop(
            messages=messages, llm=llm, tools=registry, config=config,
            session_id="eval", node_id="eval", event_bus=event_bus,
        )
    except Exception as exc:
        elapsed = time.monotonic() - start
        return {"query": query, "error": str(exc), "elapsed_seconds": round(elapsed, 2),
                "iterations": 0, "classify_result": None, "tool_calls": 0, "tool_errors": 0,
                "self_corrected": 0, "tool_call_names": [], "final_answer": None}

    elapsed = time.monotonic() - start
    events = event_bus.flush_events()

    tool_call_events = [e for e in events if e.get("type") == "tool_call"]
    tool_result_events = [e for e in events if e.get("type") == "tool_result"]
    error_events = [e for e in tool_result_events if e.get("is_error")]

    self_corrected = 0
    by_name: dict[str, list[dict]] = {}
    for e in tool_result_events:
        by_name.setdefault(e.get("tool_name", ""), []).append(e)
    for name, results in by_name.items():
        if any(r.get("is_error") for r in results) and any(not r.get("is_error") for r in results):
            self_corrected += 1

    classify_result = extract_classify_result(events)

    return {
        "query": query,
        "error": state.error,
        "elapsed_seconds": round(elapsed, 2),
        "iterations": state.iteration,
        "classify_result": classify_result,
        "tool_calls": len(tool_call_events),
        "tool_errors": len(error_events),
        "self_corrected": self_corrected,
        "tool_call_names": [e.get("tool_name") for e in tool_call_events],
        "final_answer": state.final_answer[:200] if state.final_answer else None,
    }


async def main():
    print("=" * 70)
    print("Triage Agent Evaluation (N=%d)" % len(TEST_CASES))
    print("=" * 70)

    registry = await build_triage_registry()
    config = AgentConfig(max_iterations=10, system_prompt=TRIAGE_SYSTEM_PROMPT, model="deepseek-chat")
    llm = LLMClient(model="deepseek-chat")

    print("Model: %s | Confidence threshold: %.1f" % (config.model, CONFIDENCE_THRESHOLD))
    print()

    results = []
    correct = 0
    total_labeled = 0
    total_errors = 0
    latencies = []
    classify_confidences = []

    t_start = time.monotonic()
    for i, case in enumerate(TEST_CASES, 1):
        query = case["query"]
        expected = case["expected_category"]

        result = await run_one(query, registry, llm, config)
        results.append({**case, **result})

        if result["error"]:
            print("[%3d/%d] ERROR: %s" % (i, len(TEST_CASES), result["error"][:60]))
            total_errors += 1
            continue

        latencies.append(result["elapsed_seconds"])

        classify = result["classify_result"]
        if classify:
            classify_confidences.append(classify.get("confidence", 0))
            actual = classify.get("category", "?")
            if expected is not None:
                total_labeled += 1
                if actual == expected:
                    correct += 1
                else:
                    print("[%3d/%d] MISCLASSIFY: %s -> expected=%s got=%s" % (
                        i, len(TEST_CASES), query[:45], expected, actual))
        else:
            print("[%3d/%d] WARN: no classify_intent call for '%s'" % (i, len(TEST_CASES), query[:40]))

        if i % 20 == 0:
            print("  ... %d/%d done (%.0fs elapsed)" % (i, len(TEST_CASES), time.monotonic() - t_start),
                  flush=True)

        await asyncio.sleep(0.3)

    total_time = time.monotonic() - t_start

    # ---- Report ----
    print()
    print("=" * 70)
    print("Evaluation Report")
    print("=" * 70)

    if total_labeled > 0:
        accuracy = correct / total_labeled * 100
        print("\n[1] Intent Classification Accuracy: %d/%d = %.1f%%" % (correct, total_labeled, accuracy))

    if latencies:
        sorted_lat = sorted(latencies)
        n = len(sorted_lat)
        print("\n[2] Processing Latency (seconds)")
        print("    Mean:  %.1fs" % statistics.mean(latencies))
        print("    Median: %.1fs" % statistics.median(latencies))
        print("    Min:   %.1fs" % min(latencies))
        print("    Max:   %.1fs" % max(latencies))
        print("    P50:   %.1fs" % sorted_lat[int(n * 0.50)])
        print("    P90:   %.1fs" % sorted_lat[int(n * 0.90)])
        print("    P95:   %.1fs" % sorted_lat[int(n * 0.95)])
        if n >= 100:
            print("    P99:   %.1fs" % sorted_lat[int(n * 0.99)])

    total_tool_calls = sum(r["tool_calls"] for r in results)
    total_tool_errors = sum(r["tool_errors"] for r in results)
    print("\n[3] Tool Call Statistics")
    print("    Total calls:  %d" % total_tool_calls)
    print("    Total errors: %d" % total_tool_errors)
    if total_tool_calls > 0:
        print("    Success rate: %.1f%%" % ((1 - total_tool_errors / total_tool_calls) * 100))

    total_sc = sum(r["self_corrected"] for r in results)
    print("\n[4] Self-Correction: %d instances" % total_sc)

    print("\n[5] Agent Errors: %d/%d" % (total_errors, len(TEST_CASES)))

    if classify_confidences:
        print("\n[6] Classification Confidence")
        print("    Mean: %.2f" % statistics.mean(classify_confidences))
        below = sum(1 for c in classify_confidences if c < CONFIDENCE_THRESHOLD)
        print("    Below threshold (%.1f): %d/%d" % (CONFIDENCE_THRESHOLD, below, len(classify_confidences)))

    print("\n[7] Per-Category Accuracy:")
    by_cat: dict[str, list] = {}
    for r in results:
        exp = r.get("expected_category")
        cl = r.get("classify_result")
        if exp is None or cl is None:
            continue
        by_cat.setdefault(exp, []).append(cl["category"] == exp)
    for cat, hits in sorted(by_cat.items()):
        acc = sum(hits) / len(hits) * 100 if hits else 0
        print("    %s: %d/%d = %.0f%%" % (cat, sum(hits), len(hits), acc))

    print("\n[8] Total wall-clock time: %.0fs (avg %.1fs per case)" % (total_time, total_time / len(TEST_CASES)))

    # Save JSON
    out_path = Path(__file__).resolve().parent / "eval_triage_results.json"
    serializable = []
    for r in results:
        serializable.append({
            "query": r["query"],
            "expected_category": r.get("expected_category"),
            "actual_category": r["classify_result"]["category"] if r["classify_result"] else None,
            "confidence": r["classify_result"]["confidence"] if r["classify_result"] else None,
            "elapsed_seconds": r["elapsed_seconds"],
            "iterations": r["iterations"],
            "tool_calls": r["tool_calls"],
            "tool_errors": r["tool_errors"],
            "tool_call_names": r.get("tool_call_names", []),
            "self_corrected": r["self_corrected"],
            "error": r["error"],
            "final_answer": r["final_answer"],
        })
    out_path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nDetailed results saved to: %s" % out_path)


if __name__ == "__main__":
    asyncio.run(main())
