"""
skillopt_envs/docdesk/dataloader.py — Data loader for the docdesk coder task.

Each item is a Tunisian accounting document.
Input:  extracted fields + retrieved RAG chunks
Output: account_code + cited_rule
Scorer: coder_score (1.0 iff code matches AND cited_rule in skill/chunks)
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from skillopt.datasets.base import BatchSpec, SplitDataLoader


class DocDeskDataLoader(SplitDataLoader):
    """
    Loads docdesk items from skillopt_data/train.json and skillopt_data/selection.json.
    Each item is a dict with keys: id, company_id, doc_type, text, gold_account_code, etc.
    """

    def __init__(
        self,
        split_dir: str = "skillopt_data",
        data_path: str = "",
        split_mode: str = "split_dir",
        split_ratio: str = "7:2:1",
        split_seed: int = 42,
        split_output_dir: str = "",
        seed: int = 42,
        limit: int = 0,
    ) -> None:
        self.split_dir = Path(split_dir).resolve()
        self.seed = seed
        self.limit = limit
        self._splits: dict[str, list[dict]] = {}

    def setup(self, cfg: dict) -> None:
        """Load split files from disk."""
        for split_name in ("train", "selection", "test"):
            fpath = self.split_dir / f"{split_name}.json"
            if fpath.exists():
                items = json.loads(fpath.read_text(encoding="utf-8"))
                if self.limit > 0:
                    items = items[: self.limit]
                self._splits[split_name] = items

    def load_split_items(self, split: str) -> list[dict]:
        return self._splits.get(split, [])

    def build_train_batch(self, batch_size: int, seed: int, **kwargs) -> BatchSpec:
        items = self._splits.get("train", [])
        rng = random.Random(seed)
        sampled = rng.sample(items, min(batch_size, len(items)))
        return BatchSpec(phase="train", split="train", seed=seed,
                         batch_size=len(sampled), payload=sampled)

    def build_eval_batch(self, env_num: int, split: str, seed: int, **kwargs) -> BatchSpec:
        # The SkillOpt trainer uses benchmark split names (`valid_seen` and
        # `valid_unseen`); this project stores its held-out documents as
        # `selection.json` and `test.json`.
        local_split = {
            "valid_seen": "selection",
            "selection": "selection",
            "val": "selection",
            "valid_unseen": "test",
        }.get(split, split)
        items = self._splits.get(local_split, [])
        return BatchSpec(phase="eval", split=split, seed=seed,
                         batch_size=len(items), payload=items)
