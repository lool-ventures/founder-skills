#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Pipeline-bypass telemetry for cap-table cowork-harness runs.

Measures whether the cap-table skill's deterministic pipeline ACTUALLY RAN in a
given harness run, vs the agent bypassing it (hand-rolling an analysis and
producing no canonical artifacts) — a process/provenance loss, not necessarily
a correctness loss. The point is to turn an anecdotal bypass into a measured
rate per model tier, so a hardening decision rests on data rather than a single
observation.

What it inspects (read-only): a kept harness run dir's
  <run>/<slug>/<session>/work/session/mnt/outputs/
and checks for the canonical cap-table artifacts under artifacts/cap-table-*/.
It deliberately anchors at .../mnt/outputs/ so it never confuses a mounted
plugin source or repo checkout for produced artifacts.

Classification per run:
  pipeline_ran  - the canonical solver/compose artifacts are present
  partial       - a cap-table artifacts dir exists but core artifacts are missing
  bypassed      - no canonical artifacts, but the run produced SOMETHING else
                  (ad-hoc files in outputs/) -> a genuine bypass
  no_output     - nothing produced (likely a crash/abort; inconclusive)
  error         - the run dir couldn't be inspected

bypass_rate = bypassed / (pipeline_ran + partial + bypassed)   # no_output/error excluded

Usage:
  python bypass_telemetry.py <run_dir> [<run_dir> ...]
  python bypass_telemetry.py /tmp/ct-*            # shell-expanded globs
  python bypass_telemetry.py <run_dir> --pretty
  python bypass_telemetry.py <run_dir> -o telemetry.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Canonical artifacts that only the deterministic pipeline produces. The "core"
# set is the strong "the scripts ran" signal (these never come from a hand-roll
# that didn't run run_scenario/compose_report). A flip run emits
# flip_scenario.json in place of a priced scenarios.json, so either satisfies
# the scenario slot.
_CORE_REQUIRED = ["cap_state.json", "rule_audit.json", "report.json"]
_SCENARIO_ANY = ["scenarios.json", "flip_scenario.json"]
_OTHER_CANONICAL = ["inputs.json", "instruments.json", "counsel_packet.json", "report.md"]

_MODEL_RE = re.compile(r"claude-(?:opus|sonnet|haiku)-[0-9][a-z0-9-]*")


def _find_outputs_dirs(run_dir: Path) -> list[Path]:
    """All .../work/session/mnt/outputs dirs under a run dir (usually one)."""
    return [p for p in run_dir.glob("*/*/work/session/mnt/outputs") if p.is_dir()]


def _detect_model(run_dir: Path) -> str | None:
    """Most-frequent claude-* model id seen in any events.jsonl under the run."""
    counts: Counter[str] = Counter()
    for ev in run_dir.glob("*/*/events.jsonl"):
        try:
            text = ev.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        counts.update(_MODEL_RE.findall(text))
    return counts.most_common(1)[0][0] if counts else None


def _cap_table_artifact_dirs(outputs: Path) -> list[Path]:
    base = outputs / "artifacts"
    if not base.is_dir():
        return []
    return [p for p in base.glob("cap-table-*") if p.is_dir()]


def classify_run(run_dir: str) -> dict[str, Any]:
    """Classify one harness run dir as pipeline_ran / partial / bypassed /
    no_output / error. Read-only."""
    rd = Path(run_dir)
    result: dict[str, Any] = {
        "run_dir": str(rd),
        "model": None,
        "classification": "error",
        "canonical_present": [],
        "canonical_missing": [],
        "adhoc_outputs": [],
        "artifacts_dir": None,
        "reason": "",
    }
    if not rd.is_dir():
        result["reason"] = "run dir does not exist"
        return result

    result["model"] = _detect_model(rd)
    outputs_dirs = _find_outputs_dirs(rd)
    if not outputs_dirs:
        result["classification"] = "no_output"
        result["reason"] = "no .../mnt/outputs dir found"
        return result

    outputs = outputs_dirs[0]
    art_dirs = _cap_table_artifact_dirs(outputs)

    # Ad-hoc outputs = files the agent wrote directly into outputs/ (not under
    # artifacts/), e.g. a hand-rolled <Company>_Analysis.md. Strong bypass tell.
    adhoc = sorted(p.name for p in outputs.iterdir() if p.is_file())
    result["adhoc_outputs"] = adhoc

    if not art_dirs:
        if adhoc:
            result["classification"] = "bypassed"
            result["reason"] = "no cap-table artifacts dir; agent produced ad-hoc output(s) instead"
        else:
            result["classification"] = "no_output"
            result["reason"] = "outputs dir present but empty (no artifacts, no ad-hoc files)"
        return result

    adir = art_dirs[0]
    result["artifacts_dir"] = str(adir)
    present = {p.name for p in adir.iterdir() if p.is_file()}

    required = list(_CORE_REQUIRED) + list(_OTHER_CANONICAL)
    missing = [a for a in required if a not in present]
    if not any(s in present for s in _SCENARIO_ANY):
        missing.append("scenarios.json|flip_scenario.json")
    result["canonical_present"] = sorted(a for a in present if a in set(required) | set(_SCENARIO_ANY))
    result["canonical_missing"] = missing

    core_ok = all(a in present for a in _CORE_REQUIRED) and any(s in present for s in _SCENARIO_ANY)
    if core_ok:
        result["classification"] = "pipeline_ran"
        result["reason"] = "all core canonical artifacts present"
    else:
        result["classification"] = "partial"
        result["reason"] = "cap-table artifacts dir present but missing core canonical artifact(s)"
    return result


def aggregate(classifications: list[dict[str, Any]]) -> dict[str, Any]:
    """Group classifications by model and compute bypass_rate.
    bypass_rate = bypassed / (pipeline_ran + partial + bypassed); no_output and
    error are excluded from the denominator as inconclusive."""
    buckets: dict[str, dict[str, int]] = {}

    def _empty() -> dict[str, int]:
        return {
            "total": 0,
            "pipeline_ran": 0,
            "partial": 0,
            "bypassed": 0,
            "no_output": 0,
            "error": 0,
        }

    for c in classifications:
        model = c.get("model") or "unknown"
        b = buckets.setdefault(model, _empty())
        b["total"] += 1
        cls = c.get("classification", "error")
        b[cls] = b.get(cls, 0) + 1

    def _finish(b: dict[str, int]) -> dict[str, Any]:
        denom = b["pipeline_ran"] + b["partial"] + b["bypassed"]
        rate = round(b["bypassed"] / denom, 4) if denom else None
        return {**b, "bypass_rate": rate, "conclusive_runs": denom}

    by_model = {m: _finish(b) for m, b in buckets.items()}

    overall = _empty()
    for b in buckets.values():
        for k in overall:
            overall[k] += b[k]
    overall_out = _finish(overall)

    return {"by_model": by_model, "overall": overall_out}


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Pipeline-bypass telemetry for cap-table harness runs.")
    ap.add_argument("run_dirs", nargs="+", help="One or more kept harness run dirs (globs ok via shell).")
    ap.add_argument("--pretty", action="store_true", help="Human-readable output.")
    ap.add_argument("-o", "--out", help="Write JSON result to this file.")
    args = ap.parse_args(argv)

    classifications = [classify_run(d) for d in args.run_dirs]
    agg = aggregate(classifications)
    payload = {"runs": classifications, "aggregate": agg}

    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(json.dumps({"ok": True, "wrote": args.out, "runs": len(classifications)}))
        return 0

    if args.pretty:
        for c in classifications:
            print(f"[{c['classification']:<12}] {c.get('model') or '?':<20} {c['run_dir']}")
            if c["classification"] in ("bypassed", "partial"):
                print(f"               reason: {c['reason']}")
                if c["adhoc_outputs"]:
                    print(f"               ad-hoc: {', '.join(c['adhoc_outputs'][:5])}")
        print("\n--- bypass rate by model (bypassed / conclusive runs) ---")
        for m, b in sorted(agg["by_model"].items()):
            rate = "n/a" if b["bypass_rate"] is None else f"{b['bypass_rate'] * 100:.1f}%"
            print(
                f"  {m:<22} bypass={rate:<7} "
                f"(ran={b['pipeline_ran']} partial={b['partial']} bypassed={b['bypassed']} "
                f"no_output={b['no_output']} of {b['total']})"
            )
        ov = agg["overall"]
        ov_rate = "n/a" if ov["bypass_rate"] is None else f"{ov['bypass_rate'] * 100:.1f}%"
        print(f"  {'OVERALL':<22} bypass={ov_rate} (conclusive={ov['conclusive_runs']}/{ov['total']})")
    else:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
