"""Retry provider-failed SkillOpt test cases without overwriting first attempts.

Usage: .venv-skillopt/bin/python eval/skillopt_recover_test.py [run_id]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# Loads the saved project endpoint configuration and registers SkillOpt's
# actual target-model backend. Importing this wrapper does not start training.
import skillopt_extractor  # noqa: F401
from skillopt_envs.docdesk.extractor_rollout import run_batch


def main() -> int:
    job = json.loads((ROOT / "skillopt_output/company_b_extractor/job.json").read_text())
    run_id = sys.argv[1] if len(sys.argv) > 1 else job["run_id"]
    mode = sys.argv[2] if len(sys.argv) > 2 else "baseline_failed"
    run_dir = ROOT / "skillopt_output/company_b_extractor/runs" / run_id
    test_items = json.loads((run_dir / "dataset/test.json").read_text(encoding="utf-8"))
    if mode == "baseline_failed":
        source_dir = run_dir / "test_eval_baseline/predictions"
        recovery_dir = run_dir / "test_eval_baseline_recovery"
        failed_ids = {
            path.parent.name
            for path in source_dir.glob("*/conversation.json")
            if not isinstance(json.loads(path.read_text()).get("nem"), (int, float))
        }
        retry_items = [item for item in test_items if item["id"] in failed_ids]
        skill_path = ROOT / "skills/company_b/extractor/v001.md"
    elif mode == "best_all":
        recovery_dir = run_dir / "test_eval_best_recovery"
        retry_items = test_items
        skill_path = run_dir / "best_skill.md"
    else:
        raise ValueError("mode must be baseline_failed or best_all")
    if not retry_items:
        print(json.dumps({"status": "nothing_to_retry", "documents": len(test_items)}))
        return 0

    skill = skill_path.read_text(encoding="utf-8")
    results = run_batch(
        items=retry_items,
        skill_text=skill,
        out_dir=str(recovery_dir),
        model_cfg={"max_completion_tokens": 4096, "reasoning_effort": "none"},
        workers=1,
    )
    summary = {
        "run_id": run_id,
        "skill": str(skill_path.relative_to(ROOT)) if skill_path.is_relative_to(ROOT) else str(skill_path),
        "evaluation_mode": mode,
        "retry_documents": len(retry_items),
        "results": results,
        "completed": sum(isinstance(result.get("nem"), (int, float)) for result in results),
        "provider_failures": sum("Connection error" in str(result.get("error", "")) for result in results),
        "recovery_attempts": sum(bool(result.get("recovery_attempted")) for result in results),
    }
    (recovery_dir / "recovery_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in summary.items() if key != "results"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
