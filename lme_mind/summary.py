"""Accuracy with 95% Wilson intervals, overall, per question type and for the abstention set."""

from __future__ import annotations

import json
import math
from pathlib import Path


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if not n:
        return [0.0, 0.0]
    p = k / n
    mid = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(100 * (mid - half), 1), round(100 * (mid + half), 1)]


def cell(records: list[dict]) -> dict:
    k, n = sum(r["correct"] for r in records), len(records)
    return {"correct": k, "n": n, "pct": round(100 * k / n, 1) if n else 0.0, "wilson95": wilson(k, n)}


def summarize(records: list[dict], untuned: set[str] | None = None) -> dict:
    graded = [r for r in records if r.get("correct") is not None]
    out = {"ALL": cell(graded),
           "unscored": sorted(r["question_id"] for r in records if r.get("correct") is None),
           "abstention": cell([r for r in graded if "_abs" in r["question_id"]])}
    for kind in sorted({r["question_type"] for r in graded}):
        out[kind] = cell([r for r in graded if r["question_type"] == kind])
    if untuned:
        out["untuned"] = cell([r for r in graded if r["question_id"] in untuned])
        out["tuned"] = cell([r for r in graded if r["question_id"] not in untuned])
    return out


def harness_errors(run: Path) -> list[str]:
    """Questions with no answer because the harness failed; never counted as right or wrong."""
    return sorted(p.name.removesuffix(".error.txt") for p in run.glob("*.error.txt"))


def load_records(run: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(run.glob("*.json"))
            if p.name != "summary.json"]
