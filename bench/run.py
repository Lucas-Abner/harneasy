"""Run the benchmark: each task, N times, in a fresh temporary folder.

    uv run python bench/run.py                       # all tasks, once
    uv run python bench/run.py --runs 3 --only criar_arquivo
    uv run python bench/run.py --model granite4.1:3b

Results go to bench/results/<model>-<date>.json; the agent output of each
run goes next to it, in a .log file.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from tasks import TASKS

BENCH_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BENCH_DIR / "results"


def run_task(task: dict, model: str, timeout: int, log_path: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"bench-{task['name']}-") as folder:
        workspace = Path(folder)
        for relative, content in task["files"].items():
            path = workspace / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        env = {**os.environ, "OPENAI_MODEL": model, "HARNEASY_PROJECT_ROOT": str(workspace)}
        command = [sys.executable, "-m", "agent_harness.agent", "-p", task["prompt"], "--yes"]
        started = time.monotonic()
        try:
            agent = subprocess.run(command, cwd=workspace, env=env, capture_output=True, text=True, timeout=timeout)
            agent_output, exit_code = agent.stdout + agent.stderr, agent.returncode
        except subprocess.TimeoutExpired as error:
            agent_output, exit_code = f"{error.stdout or ''}\n[TIMEOUT após {timeout}s]", "timeout"
        seconds = round(time.monotonic() - started, 1)

        # The check is written only now, so the agent could not read it.
        check_file = workspace / "_bench_check.py"
        check_file.write_text(task["check"], encoding="utf-8")
        check = subprocess.run([sys.executable, check_file.name], cwd=workspace, capture_output=True, text=True, timeout=60)
        log_path.write_text(
            f"$ {' '.join(command)}\n\n{agent_output}\n\n--- check (exit {check.returncode}) ---\n{check.stdout}{check.stderr}",
            encoding="utf-8",
        )
        return {
            "task": task["name"],
            "passed": check.returncode == 0,
            "agent_exit": exit_code,
            "seconds": seconds,
            "check_error": (check.stderr.strip().splitlines() or [""])[-1],
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "ornith-1.5:9b"))
    parser.add_argument("--runs", type=int, default=1, help="repetições por tarefa")
    parser.add_argument("--only", nargs="*", help="nomes das tarefas a executar")
    parser.add_argument("--timeout", type=int, default=600, help="segundos por execução")
    args = parser.parse_args()

    tasks = [t for t in TASKS if not args.only or t["name"] in args.only]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = RESULTS_DIR / f"{args.model.replace(':', '_').replace('/', '_')}-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for task in tasks:
        for attempt in range(1, args.runs + 1):
            result = run_task(task, args.model, args.timeout, run_dir / f"{task['name']}-{attempt}.log")
            results.append(result)
            mark = "PASS" if result["passed"] else "FAIL"
            print(f"{mark}  {task['name']:<32} run {attempt}  {result['seconds']:>6}s  {result['check_error']}", flush=True)

    passed = sum(r["passed"] for r in results)
    print(f"\n{args.model}: {passed}/{len(results)} ({100 * passed / max(1, len(results)):.0f}%)")
    print(f"Logs: {run_dir}")
    (run_dir / "results.json").write_text(
        json.dumps({"model": args.model, "runs": args.runs, "results": results}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
