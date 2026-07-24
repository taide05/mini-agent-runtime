"""Mini Agent Runtime Baseline Runner.

Wraps existing eval infrastructure (eval_triage_runner.py, eval_self_correction.py)
in a GSM metrics framework with timestamped baseline recording.

Usage:
    cd D:/mini-agent-runtime
    python -m benchmarks.run_baseline              # run triage + self-correction
    python -m benchmarks.run_baseline --triage-only  # triage only
    python -m benchmarks.run_baseline --report       # show latest benchmark

Requires: PostgreSQL, Redis, DEEPSEEK_API_KEY (for triage eval)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

BENCHMARKS_DIR = Path(__file__).resolve().parent
RUNS_DIR = BENCHMARKS_DIR / "runs"
PROJECT_ROOT = BENCHMARKS_DIR.parent


def run_triage_eval() -> list[dict]:
    """Run triage evaluation and parse results."""
    result_file = PROJECT_ROOT / "tests" / "eval_triage_results.json"

    # Check if we have cached results
    if result_file.exists():
        data = json.loads(result_file.read_text(encoding="utf-8"))
        if isinstance(data, list) and len(data) >= 50:
            print(f"  Using cached triage results: {len(data)} cases")
            return data

    # Run the eval script (requires API key and services)
    print("  Running triage eval (requires DEEPSEEK_API_KEY, PG, Redis)...")
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "tests" / "eval_triage_runner.py")],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=600,
    )
    if result.returncode != 0:
        print(f"  Triage eval failed: {result.stderr[:500]}")
        return []

    if result_file.exists():
        data = json.loads(result_file.read_text(encoding="utf-8"))
        print(f"  Triage eval complete: {len(data)} cases")
        return data
    return []


def run_self_correction_eval() -> list[dict]:
    """Run self-correction evaluation and parse results."""
    result_file = PROJECT_ROOT / "tests" / "eval_self_correction_results.json"

    if result_file.exists():
        data = json.loads(result_file.read_text(encoding="utf-8"))
        if isinstance(data, list) and len(data) >= 50:
            print(f"  Using cached self-correction results: {len(data)} cases")
            return data

    print("  Running self-correction eval (requires DEEPSEEK_API_KEY)...")
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "tests" / "eval_self_correction.py")],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=600,
    )
    if result.returncode != 0:
        print(f"  Self-correction eval failed: {result.stderr[:500]}")
        return []

    if result_file.exists():
        data = json.loads(result_file.read_text(encoding="utf-8"))
        print(f"  Self-correction eval complete: {len(data)} cases")
        return data
    return []


async def run_baseline(triage_only: bool = False):
    """Run full baseline benchmark."""
    from benchmarks.metrics import compute_all_metrics, save_benchmark

    print("=" * 60)
    print("Mini Agent Runtime — Baseline Benchmark")
    print("=" * 60)

    # Phase 1: Triage evaluation
    print("\n[1/2] Triage intent classification evaluation...")
    triage_results = run_triage_eval()

    sc_results = []
    if not triage_only:
        print("\n[2/2] Self-correction evaluation...")
        sc_results = run_self_correction_eval()

    # Phase 2: Compute metrics
    print("\n" + "=" * 60)
    print("Computing GSM Metrics")
    print("=" * 60)

    report = compute_all_metrics(
        triage_results=triage_results,
        self_correction_results=sc_results,
    )

    s = report["summary"]
    print(f"\n  Intent Accuracy:       {s.get('intent_accuracy', 'N/A'):.1%}" if isinstance(s.get('intent_accuracy'), float) else f"\n  Intent Accuracy:       {s.get('intent_accuracy', 'N/A')}")
    if "task_completion_rate" in s:
        print(f"  Task Completion:       {s['task_completion_rate']:.1%}")
    if "self_correction_rate" in s:
        print(f"  Self-Correction Rate:  {s['self_correction_rate']:.1%}")
    if "latency_p50_s" in s:
        print(f"  Latency P50 / P95:     {s['latency_p50_s']}s / {s['latency_p95_s']}s")
    if "avg_iterations" in s:
        print(f"  Avg Iterations:        {s['avg_iterations']}")
    if "escalation_rate" in s:
        print(f"  Escalation Rate:       {s['escalation_rate']:.1%}")

    # Phase 3: Save
    path = save_benchmark(report, RUNS_DIR)
    print(f"\nBenchmark saved to: {path}")

    # Show trend if exists
    from benchmarks.metrics import load_benchmarks
    reports = load_benchmarks(RUNS_DIR)
    if len(reports) >= 2:
        prev = reports[-2]["summary"]
        curr = reports[-1]["summary"]
        print(f"\nTrend vs previous ({reports[-2]['timestamp']}):")
        for key in curr:
            if key in prev and isinstance(curr[key], (int, float)) and isinstance(prev[key], (int, float)):
                delta = curr[key] - prev[key]
                sign = "+" if delta > 0 else ""
                print(f"  {key}: {sign}{delta:.3f}")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mini Agent Runtime Benchmark")
    parser.add_argument("--triage-only", action="store_true",
                        help="Only run triage evaluation (skip self-correction)")
    parser.add_argument("--report", action="store_true",
                        help="Show latest benchmark report")
    args = parser.parse_args()

    if args.report:
        from benchmarks.metrics import load_benchmarks
        reports = load_benchmarks(RUNS_DIR)
        if reports:
            latest = reports[-1]
            print(json.dumps(latest, indent=2, ensure_ascii=False))
        else:
            print("No benchmarks found. Run without --report first.")
    else:
        asyncio.run(run_baseline(triage_only=args.triage_only))
