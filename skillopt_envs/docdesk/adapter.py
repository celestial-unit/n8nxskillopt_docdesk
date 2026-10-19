"""
skillopt_envs/docdesk/adapter.py — SkillOpt adapter for the DocDesk coder task.

Task: Given extracted document fields + RAG chunks, assign the correct account code.
Hard score: 1.0 iff code matches gold AND cited_rule appears in skill or retrieved chunks.
Soft score: 0.5 iff code matches but cited_rule not verified.
"""
from __future__ import annotations

import json
import os

from skillopt.datasets.base import BatchSpec
from skillopt.envs.base import EnvAdapter
from skillopt_envs.docdesk.dataloader import DocDeskDataLoader
from skillopt_envs.docdesk.rollout import run_batch


class DocDeskCoderAdapter(EnvAdapter):
    """SkillOpt adapter for the DocDesk accounting coder benchmark."""

    def __init__(
        self,
        split_dir: str = "skillopt_data",
        data_path: str = "",
        split_mode: str = "split_dir",
        split_ratio: str = "7:2:1",
        split_seed: int = 42,
        split_output_dir: str = "",
        workers: int = 2,
        analyst_workers: int = 2,
        failure_only: bool = False,
        minibatch_size: int = 4,
        edit_budget: int = 4,
        seed: int = 42,
        limit: int = 0,
        max_completion_tokens: int = 300,
    ) -> None:
        self.workers = workers
        self.analyst_workers = analyst_workers
        self.failure_only = failure_only
        self.minibatch_size = minibatch_size
        self.edit_budget = edit_budget
        self.max_completion_tokens = int(max_completion_tokens)
        self.dataloader = DocDeskDataLoader(
            split_dir=split_dir,
            data_path=data_path,
            split_mode=split_mode,
            split_ratio=split_ratio,
            split_seed=split_seed,
            split_output_dir=split_output_dir,
            seed=seed,
            limit=limit,
        )

    # ── Lifecycle ──────────────────────────────────────────────────────

    def setup(self, cfg: dict) -> None:
        super().setup(cfg)
        self.dataloader.setup(cfg)

    def get_dataloader(self):
        return self.dataloader

    # ── Batch building ─────────────────────────────────────────────────

    def build_env_from_batch(self, batch: BatchSpec, **kwargs):
        return list(batch.payload or [])

    def build_train_env(self, batch_size: int, seed: int, **kwargs):
        batch = self.dataloader.build_train_batch(batch_size=batch_size, seed=seed)
        return self.build_env_from_batch(batch)

    def build_eval_env(self, env_num: int, split: str, seed: int, **kwargs):
        batch = self.dataloader.build_eval_batch(env_num=env_num, split=split, seed=seed)
        return self.build_env_from_batch(batch)

    # ── Rollout ────────────────────────────────────────────────────────

    def rollout(
        self,
        env,                # list[dict] items from build_*_env
        skill_doc: str,     # the current skill markdown text
        out_dir: str,       # where to save predictions
        **kwargs,           # includes model_cfg from trainer
    ) -> list[dict]:
        """Run the coder on each item and return scored results."""
        model_cfg = kwargs.get("model_cfg", {})
        results = run_batch(
            items=env,
            skill_text=skill_doc,
            out_dir=out_dir,
            model_cfg=model_cfg,
            workers=self.workers,
        )
        return results

    # ── Task types (for stratified sampling) ──────────────────────────

    def get_task_types(self) -> list[str]:
        return ["invoice", "receipt", "purchase_order"]
