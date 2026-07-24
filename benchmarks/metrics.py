"""Mini Agent Runtime Benchmark Metrics Calculator.

GSM Framework: Goals -> Signals -> Metrics

Goal 1: Agent correctly completes tasks
  Signal 1a: Triage correctly classifies intents → Intent Accuracy
  Signal 1b: Agent produces useful answers → Task Completion Rate

Goal 2: Agent recovers from tool errors
  Signal 2a: Tool errors detected and retried → Self-Correction Rate
  Signal 2b: Recovery produces correct results → Recovery Success Rate

Goal 3: System is performant
  Signal 3a: Responses are fast → Latency P50/P95
  Signal 3b: Agent doesn't loop excessively → Avg Iterations

Goal 4: Business safety compliance
  Signal 4a: High-risk cases escalated → High-Risk Escalation Rate
  Signal 4b: Safety rules followed → Safety Compliance Rate
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Quality Metric 1: Intent Classification Accuracy
# ---------------------------------------------------------------------------

def compute_intent_accuracy(results: list[dict]) -> dict[str, Any]:
    """Compute triage intent classification accuracy.

    Args:
        results: List of {expected_category, actual_category, ...} from eval runs.

    Returns:
        Dict with overall accuracy and per-category breakdown.
    """
    total = len(results)
    if total == 0:
        return {"metric": "intent_accuracy", "value": 0.0, "total": 0, "correct": 0}

    correct = sum(1 for r in results if r.get("expected_category") == r.get("actual_category"))
    accuracy = correct / total

    # Per-category breakdown
    categories: dict[str, dict] = {}
    for r in results:
        cat = str(r.get("expected_category") or "unknown")
        if cat not in categories:
            categories[cat] = {"total": 0, "correct": 0}
        categories[cat]["total"] += 1
        if r.get("expected_category") == r.get("actual_category"):
            categories[cat]["correct"] += 1

    per_category = {
        str(cat): {
            "accuracy": round(d["correct"] / d["total"], 3) if d["total"] else 0,
            "total": d["total"],
            "correct": d["correct"],
        }
        for cat, d in sorted(categories.items(), key=lambda x: str(x[0]))
    }

    return {
        "metric": "intent_accuracy",
        "value": round(accuracy, 3),
        "total": total,
        "correct": correct,
        "per_category": per_category,
    }


# ---------------------------------------------------------------------------
# Quality Metric 2: Task Completion Rate
# ---------------------------------------------------------------------------

def compute_task_completion_rate(results: list[dict]) -> dict[str, Any]:
    """Compute task completion rate (agent reached finish, not error/max_iter).

    Args:
        results: List of {stop_reason, error, ...} from eval runs.

    Returns:
        Dict with completion rate and stop reason distribution.
    """
    total = len(results)
    if total == 0:
        return {"metric": "task_completion_rate", "value": 0.0, "total": 0}

    finished = sum(1 for r in results if r.get("stop_reason", "") == "finish" and not r.get("error"))
    rate = finished / total

    reasons: dict[str, int] = {}
    for r in results:
        reason = r.get("stop_reason", "unknown")
        reasons[reason] = reasons.get(reason, 0) + 1

    return {
        "metric": "task_completion_rate",
        "value": round(rate, 3),
        "total": total,
        "finished": finished,
        "stop_reasons": reasons,
    }


# ---------------------------------------------------------------------------
# Reliability Metric 3: Self-Correction Rate
# ---------------------------------------------------------------------------

def compute_self_correction_rate(results: list[dict]) -> dict[str, Any]:
    """Compute agent self-correction rate from tool error scenarios.

    Args:
        results: List of {tool_errors, self_corrected, ...} from eval runs.

    Returns:
        Dict with correction rate and per-category breakdown.
    """
    total_with_errors = sum(1 for r in results if r.get("tool_errors", 0) > 0)
    if total_with_errors == 0:
        return {"metric": "self_correction_rate", "value": 1.0,
                "total_with_errors": 0, "corrected": 0,
                "note": "No tool errors encountered"}

    corrected = sum(1 for r in results
                    if r.get("tool_errors", 0) > 0 and r.get("self_corrected", False))
    rate = corrected / total_with_errors

    return {
        "metric": "self_correction_rate",
        "value": round(rate, 3),
        "total_with_errors": total_with_errors,
        "corrected": corrected,
    }


# ---------------------------------------------------------------------------
# Efficiency Metric 4: Latency
# ---------------------------------------------------------------------------

def compute_latency_stats(elapsed_s_list: list[float]) -> dict[str, Any]:
    """Compute P50, P95, mean latency from elapsed seconds list."""
    if not elapsed_s_list:
        return {"metric": "latency", "p50": 0, "p95": 0, "mean": 0, "count": 0}

    sorted_l = sorted(elapsed_s_list)
    n = len(sorted_l)

    def percentile(p: float) -> float:
        k = (p / 100) * (n - 1)
        f = int(k)
        c = k - f
        if f + 1 < n:
            return sorted_l[f] + c * (sorted_l[f + 1] - sorted_l[f])
        return sorted_l[f]

    return {
        "metric": "latency",
        "p50": round(percentile(50), 2),
        "p95": round(percentile(95), 2),
        "mean": round(statistics.mean(sorted_l), 2),
        "min": round(sorted_l[0], 2),
        "max": round(sorted_l[-1], 2),
        "count": n,
    }


# ---------------------------------------------------------------------------
# Efficiency Metric 5: Iteration Efficiency
# ---------------------------------------------------------------------------

def compute_iteration_efficiency(results: list[dict]) -> dict[str, Any]:
    """Compute average iterations per task and distribution."""
    iterations = [r.get("iterations", 0) for r in results if "iterations" in r]
    if not iterations:
        return {"metric": "iteration_efficiency", "avg": 0, "count": 0}

    return {
        "metric": "iteration_efficiency",
        "avg": round(statistics.mean(iterations), 1),
        "median": round(statistics.median(iterations), 1),
        "min": min(iterations),
        "max": max(iterations),
        "count": len(iterations),
    }


# ---------------------------------------------------------------------------
# Quality Metric 6: High-Risk Escalation Rate (Business Safety)
# ---------------------------------------------------------------------------

HIGH_RISK_INTENTS = {"refund_complaint", "account_recovery"}

def compute_escalation_rate(results: list[dict]) -> dict[str, Any]:
    """Check if high-risk intents are properly escalated.

    Args:
        results: List of {expected_category, escalated, ...}

    Returns:
        Dict with escalation rate for high-risk categories.
    """
    high_risk = [r for r in results
                 if str(r.get("expected_category") or "").lower() in HIGH_RISK_INTENTS]
    if not high_risk:
        return {"metric": "escalation_rate", "value": 1.0, "total_high_risk": 0}

    escalated = sum(1 for r in high_risk if r.get("escalated", False))
    rate = escalated / len(high_risk)

    return {
        "metric": "escalation_rate",
        "value": round(rate, 3),
        "total_high_risk": len(high_risk),
        "escalated": escalated,
    }


# ---------------------------------------------------------------------------
# Aggregate Report
# ---------------------------------------------------------------------------

def compute_all_metrics(
    triage_results: list[dict] | None = None,
    self_correction_results: list[dict] | None = None,
) -> dict[str, Any]:
    """Compute all metrics and return aggregate report."""
    triage_results = triage_results or []
    sc_results = self_correction_results or []

    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {},
        "quality": {},
        "efficiency": {},
        "reliability": {},
        "safety": {},
    }

    # From triage results
    if triage_results:
        report["quality"]["intent_accuracy"] = compute_intent_accuracy(triage_results)
        report["quality"]["task_completion"] = compute_task_completion_rate(triage_results)
        latencies = [r.get("elapsed_seconds", 0) for r in triage_results]
        report["efficiency"]["latency"] = compute_latency_stats(latencies)
        report["efficiency"]["iteration_efficiency"] = compute_iteration_efficiency(triage_results)
        report["safety"]["escalation_rate"] = compute_escalation_rate(triage_results)

    # From self-correction results
    if sc_results:
        report["reliability"]["self_correction"] = compute_self_correction_rate(sc_results)

    # Summary rollup
    s: dict[str, Any] = {}
    q = report["quality"]
    e = report["efficiency"]
    r = report["reliability"]
    sf = report["safety"]

    if "intent_accuracy" in q:
        s["intent_accuracy"] = q["intent_accuracy"]["value"]
    if "task_completion" in q:
        s["task_completion_rate"] = q["task_completion"]["value"]
    if "self_correction" in r:
        s["self_correction_rate"] = r["self_correction"]["value"]
    if "latency" in e:
        s["latency_p50_s"] = e["latency"]["p50"]
        s["latency_p95_s"] = e["latency"]["p95"]
    if "iteration_efficiency" in e:
        s["avg_iterations"] = e["iteration_efficiency"]["avg"]
    if "escalation_rate" in sf:
        s["escalation_rate"] = sf["escalation_rate"]["value"]

    report["summary"] = s
    return report


def save_benchmark(report: dict[str, Any], runs_dir: Path, label: str = "") -> Path:
    """Save benchmark report to timestamped JSON."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = runs_dir / f"benchmark{label}-{ts}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_benchmarks(runs_dir: Path) -> list[dict[str, Any]]:
    """Load all benchmark reports sorted by time."""
    reports = []
    for f in sorted(runs_dir.glob("benchmark*.json")):
        try:
            reports.append(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return reports
