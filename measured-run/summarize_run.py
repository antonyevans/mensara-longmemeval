"""Summarise a run_dev/run_live output directory: overall, per type, abstention, and the
never-tuned split. Harness errors (no record) and judge failures (correct is null) are
reported separately, never counted as wrong.

  python summarize_run.py <run-dir> [--untuned <json list of question ids>] [--json out.json]
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
from collections import defaultdict


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(100 * (c - h), 1), round(100 * (c + h), 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--untuned")
    ap.add_argument("--json")
    a = ap.parse_args()
    recs = [json.load(open(f, encoding="utf-8")) for f in glob.glob(os.path.join(a.run, "*.json"))
            if os.path.basename(f) not in ("run.json", "summary.json")]
    errors = sorted(os.path.basename(f)[:-10] for f in glob.glob(os.path.join(a.run, "*.error.txt")))
    untuned = set(json.load(open(a.untuned, encoding="utf-8"))) if a.untuned else set()
    groups = defaultdict(lambda: [0, 0])
    unscored = sorted(r["qid"] for r in recs if r.get("correct") is None)
    for r in (r for r in recs if r.get("correct") is not None):
        for g in ("ALL", r["type"], "abstention" if r.get("abstention") else None,
                  ("untuned" if r["qid"] in untuned else "tuned") if untuned else None):
            if g:
                groups[g][0] += bool(r["correct"])
                groups[g][1] += 1
    out = {g: {"correct": k, "n": n, "pct": round(100 * k / n, 1), "wilson95": wilson(k, n)}
           for g, (k, n) in sorted(groups.items())}
    out["_errors"] = errors
    out["_unscored"] = unscored
    out["_no_mind_call"] = sorted(r["qid"] for r in recs if not r.get("mind_calls"))
    for g, v in out.items():
        if not g.startswith("_"):
            print(f"{g:28s} {v['correct']:4d}/{v['n']:<4d} {v['pct']:5.1f}%  95% CI {v['wilson95']}")
    print("harness errors:", len(errors), "| judge unscored:", len(unscored), "| readers with no Mind call:", len(out["_no_mind_call"]))
    if a.json:
        open(a.json, "w", encoding="utf-8").write(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
