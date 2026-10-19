"""Manage real SkillOpt CLI runs and publish their auditable history."""
from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for import_path in (str(ROOT), str(ROOT / "scripts")):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)
BASE = ROOT / "skillopt_output/company_b_extractor"
RUNS = BASE / "runs"
JOB = BASE / "job.json"
_lock = threading.Lock()
_processes: dict[str, subprocess.Popen] = {}


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _mean_selection_nem(run_dir: Path) -> float | None:
    paths = (run_dir / "selection_eval_baseline" / "predictions").glob("*/conversation.json")
    values = []
    for path in paths:
        record = _read_json(path, {})
        if isinstance(record.get("nem"), (int, float)):
            values.append(float(record["nem"]))
    return sum(values) / len(values) if values else None


def _selection_metrics(
    run_dir: Path,
    directory: str = "selection_eval_baseline",
    fallback_directory: str | None = None,
) -> dict:
    """Return case and per-field metrics from persisted held-out predictions."""
    from skillopt_envs.docdesk.extractor_rollout import _normalize

    records_by_id: dict[str, dict] = {}
    if fallback_directory:
        for path in (run_dir / fallback_directory / "predictions").glob("*/conversation.json"):
            records_by_id[path.parent.name] = _read_json(path, {})
    for path in (run_dir / directory / "predictions").glob("*/conversation.json"):
        records_by_id[path.parent.name] = _read_json(path, {})
    field_hits: dict[str, int] = {}
    field_totals: dict[str, int] = {}
    exact_documents = 0
    parse_ok = 0
    model_responses = 0
    provider_failures = 0
    field_score_total = 0.0
    for record in records_by_id.values():
        gold = record.get("gold_fields", {})
        predicted = record.get("predicted", {})
        has_response = isinstance(record.get("nem"), (int, float))
        model_responses += int(has_response)
        provider_failures += int("Connection error" in str(record.get("error", "")))
        if not has_response:
            continue
        field_score_total += float(record["nem"])
        if predicted:
            parse_ok += 1
        all_match = bool(gold) and bool(predicted)
        for key, expected in gold.items():
            actual = predicted.get(key, "")
            if key == "line_descriptions" and not actual:
                actual = [line.get("description", "") for line in predicted.get("lines", [])
                          if isinstance(line, dict)]
            matched = _normalize(actual) == _normalize(expected)
            field_totals[key] = field_totals.get(key, 0) + 1
            field_hits[key] = field_hits.get(key, 0) + int(matched)
            all_match = all_match and matched
        exact_documents += int(all_match)
    return {
        "documents_scored": len(records_by_id),
        "documents_exact": exact_documents,
        "model_responses": model_responses,
        "provider_failures": provider_failures,
        "model_coverage": model_responses / len(records_by_id) if records_by_id else None,
        "mean_field_exact_match": field_score_total / model_responses if model_responses else None,
        "parse_successes": parse_ok,
        "field_accuracy": {
            key: {"correct": field_hits[key], "total": field_totals[key],
                  "score": field_hits[key] / field_totals[key] if field_totals[key] else None}
            for key in sorted(field_totals)
        },
    }


def start() -> dict:
    with _lock:
        state = _read_json(JOB, {})
        if state.get("status") == "running" and state.get("pid"):
            state = _finish_if_done(state, {})
            if state.get("status") == "running":
                return {"status": "running", "run_id": state.get("run_id"), "pid": state.get("pid")}

        from prepare_skillopt_company_b import prepare
        dataset_summary = prepare()
        splits = {name: details["documents"] for name, details in dataset_summary.items()}
        BASE.mkdir(parents=True, exist_ok=True)
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = RUNS / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        dataset_dir = run_dir / "dataset"
        dataset_dir.mkdir(parents=True, exist_ok=True)
        dataset_hashes = {}
        for split in ("train", "selection", "test"):
            source = ROOT / f"skillopt_data/company_b_balanced/{split}.json"
            target = dataset_dir / f"{split}.json"
            shutil.copyfile(source, target)
            dataset_hashes[split] = hashlib.sha256(target.read_bytes()).hexdigest()
        log_path = run_dir / "run.log"
        with log_path.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [str(ROOT / ".venv-skillopt/bin/python"), "-u", str(ROOT / "scripts/skillopt_extractor.py"),
                 "--config", str(ROOT / "configs/docdesk/company_b_extractor.yaml"),
                 "--out_root", str(run_dir)],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
                start_new_session=True,
            )
        state = {"status": "running", "run_id": run_id, "pid": proc.pid,
                 "output_root": str(run_dir.relative_to(ROOT)),
                 "started_at": datetime.now(timezone.utc).isoformat(), "splits": splits,
                 "dataset_summary": dataset_summary, "dataset_hashes": dataset_hashes}
        JOB.write_text(json.dumps(state, indent=2), encoding="utf-8")
        (run_dir / "run_state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        _processes[run_id] = proc
        return state


def _finish_if_done(state: dict, summary: dict) -> dict:
    if state.get("status") != "running" or not state.get("pid"):
        return state
    proc = _processes.get(str(state.get("run_id", "")))
    if proc is not None:
        exit_code = proc.poll()
        if exit_code is None:
            return state
    else:
        try:
            os.kill(int(state["pid"]), 0)
            return state
        except (ProcessLookupError, PermissionError, ValueError):
            exit_code = None

    run_dir = ROOT / state.get("output_root", "")
    summary = _read_json(run_dir / "summary.json", summary)
    runtime_state = _read_json(run_dir / "runtime_state.json", {})
    # If FastAPI restarted while the detached trainer was running, its child
    # process handle is gone. A complete SkillOpt summary is then the durable
    # success marker; a live PID is handled above and remains `running`.
    if exit_code in {0, None} and summary and summary.get("total_steps"):
        gate_metric = summary.get("config", {}).get("gate_metric", "hard")
        initial = (_mean_selection_nem(run_dir) if gate_metric == "soft"
                   else summary.get("baseline_selection_hard"))
        best = (runtime_state.get("best_score") if gate_metric == "soft"
                else summary.get("best_selection_hard"))
        accepted = initial is not None and best is not None and float(best) > float(initial)
        promoted = None
        if accepted:
            source = run_dir / "best_skill.md"
            if source.exists():
                skill_dir = ROOT / "skills/company_b/extractor"
                versions = [int(p.stem[1:]) for p in skill_dir.glob("v*.md")
                            if p.stem[1:].isdigit()]
                promoted = f"v{max(versions, default=0) + 1:03d}"
                shutil.copyfile(source, skill_dir / f"{promoted}.md")
        state = {**state, "status": "complete", "exit_code": 0,
                 "baseline_selection_hard": summary.get("baseline_selection_hard"),
                 "best_selection_hard": summary.get("best_selection_hard"),
                 "baseline_selection_score": initial, "best_selection_score": best,
                 "gate_metric": gate_metric,
                 "accepted": accepted, "promoted_version": promoted,
                 "finished_at": datetime.now(timezone.utc).isoformat()}
    else:
        log_path = run_dir / "run.log"
        log_text = log_path.read_text(encoding="utf-8", errors="replace")[-4000:] if log_path.exists() else ""
        state = {**state, "status": "failed", "exit_code": exit_code,
                 "error": "SkillOpt failed or ended without a training summary.",
                 "log_tail": log_text, "finished_at": datetime.now(timezone.utc).isoformat()}
    JOB.write_text(json.dumps(state, indent=2), encoding="utf-8")
    (run_dir / "run_state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def summary() -> dict:
    state = _read_json(JOB, {"status": "not_run"})
    run_dir = ROOT / state.get("output_root", "") if state.get("output_root") else None
    summary_data = _read_json(run_dir / "summary.json", {}) if run_dir else {}
    state = _finish_if_done(state, summary_data)
    summary_data = _read_json((ROOT / state["output_root"] / "summary.json"), {}) if state.get("output_root") else {}
    if run_dir:
        config_data = summary_data.get("config") or _read_json(run_dir / "config.json", {})
        gate_metric = config_data.get("gate_metric", "hard")
        summary_data["gate_metric"] = gate_metric
        baseline_soft = _mean_selection_nem(run_dir)
        baseline_paths = list((run_dir / "selection_eval_baseline" / "predictions").glob("*/conversation.json"))
        expected = _read_json(run_dir / "run_state.json", {}).get("splits", {}).get("selection")
        if expected is None:
            expected = _read_json(JOB, {}).get("splits", {}).get("selection")
        summary_data["baseline_selection_cases"] = {
            "completed": len(baseline_paths), "total": expected,
        }
        summary_data["selection_metrics"] = _selection_metrics(run_dir)
        summary_data["test_initial_metrics"] = _selection_metrics(run_dir, "test_eval_baseline")
        summary_data["test_baseline_metrics"] = _selection_metrics(
            run_dir, "test_eval_baseline_recovery", "test_eval_baseline"
        )
        summary_data["test_best_attempt_metrics"] = _selection_metrics(run_dir, "test_eval")
        summary_data["test_best_metrics"] = _selection_metrics(
            run_dir, "test_eval_best_recovery", "test_eval"
        )
        runtime_state = _read_json(run_dir / "runtime_state.json", {})
        if gate_metric == "soft":
            summary_data["baseline_selection_score"] = baseline_soft
            summary_data["best_selection_score"] = runtime_state.get("best_score")
        else:
            summary_data["baseline_selection_score"] = summary_data.get("baseline_selection_hard")
            summary_data["best_selection_score"] = summary_data.get("best_selection_hard")
    return {"run": state, "summary": summary_data}


def history() -> dict:
    current = summary()
    run_dir = ROOT / current["run"]["output_root"] if current["run"].get("output_root") else None
    step_paths = sorted((run_dir / "steps").glob("step_*/step_record.json")) if run_dir else []
    steps = [_read_json(p, {}) for p in step_paths]
    skills_dir = run_dir / "skills" if run_dir else BASE
    skills = [{"version": p.stem, "text": p.read_text(encoding="utf-8")}
              for p in sorted(skills_dir.glob("skill_*.md"))]
    runtime_dir = ROOT / "skills/company_b/extractor"
    runtime = [{"version": p.stem, "path": str(p.relative_to(ROOT)),
                "text": p.read_text(encoding="utf-8")}
               for p in sorted(runtime_dir.glob("v*.md"))]
    model_usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    if run_dir:
        for path in run_dir.rglob("conversation.json"):
            conversation = _read_json(path, {})
            usage = conversation.get("usage", {})
            if usage:
                model_usage["calls"] += 1
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    model_usage[key] += int(usage.get(key, 0) or 0)
    runs = []
    for folder in sorted(RUNS.glob("*"), reverse=True):
        s = _read_json(folder / "summary.json", {})
        run_state = _read_json(folder / "run_state.json", {})
        if s or run_state:
            runs.append({"run_id": folder.name, "status": run_state.get("status", "complete" if s else "unknown"),
                         "baseline_selection_hard": s.get("baseline_selection_hard", run_state.get("baseline_selection_hard")),
                         "best_selection_hard": s.get("best_selection_hard"),
                         "baseline_selection_score": run_state.get("baseline_selection_score"),
                         "best_selection_score": run_state.get("best_selection_score"),
                         "gate_metric": run_state.get("gate_metric", s.get("config", {}).get("gate_metric", "hard")),
                         "total_steps": s.get("total_steps"), "total_accepts": s.get("total_accepts"),
                         "total_rejects": s.get("total_rejects"), "total_skips": s.get("total_skips")})
    return {"run": current["run"], "summary": current["summary"], "runs": runs,
            "steps": steps, "skillopt_versions": skills, "runtime_versions": runtime,
            "model_usage": model_usage,
            "log": (run_dir / "run.log").read_text(encoding="utf-8", errors="replace")[-12000:]
            if run_dir and (run_dir / "run.log").exists() else ""}
