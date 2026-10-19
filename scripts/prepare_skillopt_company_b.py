"""Create reproducible, balanced Company B SkillOpt splits."""
import json
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skillopt_data"
DEST = SOURCE / "company_b_balanced"
SIZES = {"train": 12, "selection": 20}


def _balanced_sample(items: list[dict], size: int, seed: int) -> list[dict]:
    """Greedily balance supplier and document type with deterministic ties."""
    rng = random.Random(seed)
    remaining = list(items)
    rng.shuffle(remaining)
    chosen: list[dict] = []
    suppliers: Counter = Counter()
    types: Counter = Counter()
    while remaining and len(chosen) < size:
        item = min(
            remaining,
            key=lambda x: (
                suppliers[x.get("gold_fields", {}).get("supplier", "unknown")],
                types[x.get("doc_type", "unknown")],
                rng.random(),
            ),
        )
        remaining.remove(item)
        chosen.append(item)
        suppliers[item.get("gold_fields", {}).get("supplier", "unknown")] += 1
        types[item.get("doc_type", "unknown")] += 1
    return chosen


def prepare() -> dict:
    DEST.mkdir(parents=True, exist_ok=True)
    train_source = json.loads((SOURCE / "train.json").read_text(encoding="utf-8"))
    company_b_train = [x for x in train_source if x.get("company_id") == "company_b"]
    train = _balanced_sample(company_b_train, SIZES["train"], seed=420)
    (DEST / "train.json").write_text(json.dumps(train, ensure_ascii=False, indent=2), encoding="utf-8")

    # The source selection split has 30 Company B examples. Reserve 20 for
    # SkillOpt's gate and keep the remaining 10 unseen until final evaluation.
    selection_source = json.loads((SOURCE / "selection.json").read_text(encoding="utf-8"))
    company_b_selection = [x for x in selection_source if x.get("company_id") == "company_b"]
    by_type = {
        "invoice": 8,
        "purchase_order": 8,
        "receipt": 4,
    }
    selection = []
    for index, (doc_type, size) in enumerate(by_type.items()):
        candidates = [x for x in company_b_selection if x.get("doc_type") == doc_type]
        selection.extend(_balanced_sample(candidates, size, seed=421 + index))
    selected_ids = {x["id"] for x in selection}
    test = [x for x in company_b_selection if x["id"] not in selected_ids]
    if len(train) != 12 or len(selection) != 20 or len(test) != 10:
        raise RuntimeError(f"Unexpected split sizes: train={len(train)}, selection={len(selection)}, test={len(test)}")

    counts = {}
    for split, records in (("train", train), ("selection", selection), ("test", test)):
        (DEST / f"{split}.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        counts[split] = {
            "documents": len(records),
            "suppliers": len({x.get("gold_fields", {}).get("supplier") for x in records}),
            "doc_types": dict(Counter(x.get("doc_type", "unknown") for x in records)),
        }
    return counts


if __name__ == "__main__":
    print(json.dumps(prepare(), ensure_ascii=False))
