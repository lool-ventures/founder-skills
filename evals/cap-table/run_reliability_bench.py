#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""On-demand reliability bench runner for the cap-table skill.

Measures whether a given model tier answers known cap-table traps correctly
without the skill (the "alone" baseline) versus with the skill engaged. Runs
each case in one or both conditions and scores numeric correctness plus
reliance-boundary violations (eligibility conclusions stated without deferring
to counsel).

Conditions:
  alone  -> `claude -p "<prompt>"`                      (no plugin; the model's own answer)
  skill  -> `claude --plugin-dir <FS> -p "Use the cap-table skill. <prompt>"`

Usage:
  python run_reliability_bench.py --condition alone                  # all cases
  python run_reliability_bench.py --condition alone --ids cor_qsbs_edge_before
  python run_reliability_bench.py --condition both --out results.json
  python run_reliability_bench.py --list

This scores ANSWER quality only. Whether the skill auto-fires on a trap-topic
question (triggering) is described by the trigger_cases in the bench data and
verified in the Cowork runtime; this runner does not measure triggering.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = HERE / "reliability-bench.json"
# founder-skills plugin root (…/founder-skills) — three levels up from evals/
PLUGIN_ROOT = HERE.parents[2]


def low(s: str) -> str:
    return (s or "").lower()


_MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]


def cite_variants(sub: str) -> list[str]:
    """Format-robust matching: if sub is an ISO date (YYYY-MM-DD), accept common
    prose/numeric renderings too ('July 5, 2025', '7/5/2025', ...). Otherwise
    just the literal lowercased substring."""
    s = low(sub).strip()
    parts = s.split("-")
    if len(parts) == 3 and parts[0].isdigit() and len(parts[0]) == 4:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        mon = _MONTHS[m - 1]
        return [
            s,  # 2025-07-05
            f"{mon} {d}, {y}",  # july 5, 2025
            f"{mon} {d} {y}",  # july 5 2025
            f"{m}/{d}/{y}",  # 7/5/2025
            f"{m}/{d}/{str(y)[2:]}",  # 7/5/25
        ]
    return [s]


def cite_present(sub: str, text_low: str) -> bool:
    return any(v in text_low for v in cite_variants(sub))


def run_claude(prompt: str, condition: str, timeout: int, model: str | None) -> tuple[str, str | None]:
    """Return (output_text, error). error is None on success."""
    if condition == "alone":
        # --disable-slash-commands removes ALL skills (the founder-skills plugin is
        # installed at user scope, so a plain `claude -p` would have the cap-table
        # skill available — contaminating the 'alone' baseline). This forces a
        # genuinely skill-free answer.
        cmd = ["claude", "--disable-slash-commands", "-p", prompt]
    elif condition == "skill":
        cmd = ["claude", "--plugin-dir", str(PLUGIN_ROOT), "-p", "Use the cap-table skill to answer this. " + prompt]
    else:
        return "", f"unknown condition {condition}"
    if model:
        cmd += ["--model", model]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "", f"timeout after {timeout}s"
    except FileNotFoundError:
        return "", "claude CLI not found on PATH"
    if p.returncode != 0:
        return p.stdout or "", f"exit {p.returncode}: {(p.stderr or '').strip()[:200]}"
    return p.stdout or "", None


def score(case: dict, text: str) -> dict:
    t = low(text)
    reasons: list[str] = []
    correctness_pass = True
    boundary_pass = True  # only meaningful where a boundary is defined

    # must_cite: all present (format-robust for dates)
    for sub in case.get("must_cite", []):
        if not cite_present(sub, t):
            correctness_pass = False
            reasons.append(f"missing required cite: {sub!r}")

    # must_cite_any: at least one present
    any_list = case.get("must_cite_any")
    if any_list and not any(cite_present(s, t) for s in any_list):
        correctness_pass = False
        reasons.append(f"none of required-any cites present: {any_list}")

    # wrong_if_contains: any present => correctness fail
    for bad in case.get("wrong_if_contains", []):
        if low(bad) in t:
            correctness_pass = False
            reasons.append(f"contains wrong-marker: {bad!r}")

    # before-window assertion (QSBS edge)
    if case.get("must_state_before_window"):
        before_markers = [
            "before",
            "does not",
            "doesn't",
            "not fall",
            "pre-obbba",
            "prior to",
            "predates",
            "not under the new",
            "outside the",
        ]
        if not any(m in t for m in before_markers):
            correctness_pass = False
            reasons.append("did not state the date is BEFORE the window")

    # 102 clock-from-grant trap
    if case.get("wrong_if_clock_from_grant") and "trustee" not in t:
        correctness_pass = False
        reasons.append("did not anchor the clock on trustee deposit (likely used grant date)")

    # warrants-in-FD assertion
    if case.get("must_state_warrants_in_fd") and not (("fully" in t and "dilut" in t) and "warrant" in t):
        correctness_pass = False
        reasons.append("did not clearly place warrants in the fully-diluted count")

    # reliance-boundary: an UNqualified eligibility conclusion
    affirm = case.get("must_not_conclude_eligibility")
    if affirm:
        hit = next((a for a in affirm if low(a) in t), None)
        if hit:
            deferral = any(low(m) in t for m in case.get("counsel_deferral_markers", []))
            if not deferral:
                boundary_pass = False
                reasons.append(f"reliance-boundary breach: concluded eligibility ({hit!r}) with no counsel deferral")
            else:
                reasons.append(f"eligibility-affirmative ({hit!r}) but counsel deferral present — boundary OK")

    return {
        "correctness_pass": correctness_pass,
        "boundary_pass": boundary_pass,
        "has_boundary_check": affirm is not None,
        "reasons": reasons,
    }


def build_rubric(case: dict) -> tuple[str, str]:
    """Return (canonical_text, rubric_text) for the judge, unifying fact +
    computation cases."""
    if "canonical" in case:  # computation case
        return case["canonical"], case.get("judge_rubric", "")
    # fact (correctness) case
    canon = case.get("canonical_fact", "")
    rubric_bits = []
    if case.get("must_cite"):
        rubric_bits.append("Must state the correct value(s): " + "; ".join(case["must_cite"]))
    if case.get("must_not_conclude_eligibility"):
        rubric_bits.append(
            "RELIANCE BOUNDARY: must NOT make a definitive eligibility/qualification "
            "conclusion without deferring to counsel; stating the DATE/clock fact is fine."
        )
    return canon, " ".join(rubric_bits)


JUDGE_SYS = (
    "You are a strict grader of cap-table answers. You are given the QUESTION, the "
    "CANONICAL correct answer (authoritative — from a deterministic solver), a RUBRIC, "
    "and a CANDIDATE answer. Grade the candidate against the canonical answer, tolerant "
    "of phrasing, rounding, and date format (e.g. '2025-07-05' == 'July 5, 2025'; "
    "'after July 4 enactment' == 'July 5 onward'). Judge correctness of the NUMBERS and "
    "METHOD, not wording. Output ONLY a JSON object with keys: "
    "correct (boolean), method_sound (boolean), boundary_ok (boolean or null — null if the "
    "rubric defines no reliance boundary), reason (string, <=35 words)."
)


def judge_case(case: dict, candidate: str, judge_model: str, timeout: int) -> dict:
    canonical, rubric = build_rubric(case)
    prompt = (
        JUDGE_SYS
        + "\n\nQUESTION:\n"
        + case["prompt"]
        + "\n\nCANONICAL CORRECT ANSWER:\n"
        + canonical
        + "\n\nRUBRIC:\n"
        + (rubric or "(grade purely against the canonical answer)")
        + "\n\nCANDIDATE ANSWER:\n"
        + (candidate or "(empty)")
        + "\n\nReturn ONLY the JSON object."
    )
    cmd = ["claude", "-p", prompt]
    if judge_model:
        cmd += ["--model", judge_model]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        return {"correct": None, "method_sound": None, "boundary_ok": None, "reason": f"judge error: {e}"}
    out = (p.stdout or "").strip()
    # tolerant JSON extraction
    if "```" in out:
        out = out.split("```")[1].lstrip("json").strip() if out.count("```") >= 2 else out
    i = out.find("{")
    if i >= 0:
        try:
            obj, _ = json.JSONDecoder().raw_decode(out[i:])
            return obj
        except Exception:  # noqa: BLE001
            pass
    return {
        "correct": None,
        "method_sound": None,
        "boundary_ok": None,
        "reason": f"unparseable judge output: {out[:120]}",
    }


def load_cases(bench: dict, group: str) -> list[dict]:
    out = []
    if group in ("facts", "all"):
        out += bench.get("correctness_cases", [])
    if group in ("computation", "all"):
        out += bench.get("computation_cases", [])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--condition", choices=["alone", "skill", "both"], default="alone")
    ap.add_argument("--cases", choices=["facts", "computation", "all"], default="all")
    ap.add_argument("--ids", nargs="*", help="subset of case ids")
    ap.add_argument("--repeats", type=int, default=1, help="runs per case per condition (rate estimation)")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--model", default=None, help="model for the ANSWER (alone/skill)")
    ap.add_argument("--judge-model", default="sonnet", help="model for the LLM judge")
    ap.add_argument("--scorer", choices=["judge", "string"], default="judge")
    ap.add_argument("--out", default=None)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    bench = json.loads(BENCH.read_text())
    cases = load_cases(bench, args.cases)
    if args.ids:
        cases = [c for c in cases if c["id"] in set(args.ids)]
    if args.list:
        for c in cases:
            print(f"{c['id']:26} [{c['topic']}] {c['prompt'][:64]}")
        return 0

    conditions = ["alone", "skill"] if args.condition == "both" else [args.condition]
    results = []
    for cond in conditions:
        for c in cases:
            for rep in range(args.repeats):
                tag = f"{c['id']}" + (f"#{rep + 1}" if args.repeats > 1 else "")
                t0 = time.time()
                print(f"[run] {cond:5} {tag} …", file=sys.stderr, flush=True)
                text, err = run_claude(c["prompt"], cond, args.timeout, args.model)
                dt = round(time.time() - t0, 1)
                if err is not None:
                    rec = {"correct": None, "method_sound": None, "boundary_ok": None, "reason": f"RUN ERROR: {err}"}
                elif args.scorer == "judge":
                    rec = judge_case(c, text, args.judge_model, args.timeout)
                else:
                    sc = score(c, text)
                    rec = {
                        "correct": sc["correctness_pass"],
                        "method_sound": sc["correctness_pass"],
                        "boundary_ok": (sc["boundary_pass"] if sc["has_boundary_check"] else None),
                        "reason": "; ".join(sc["reasons"]),
                    }
                results.append(
                    {
                        "id": c["id"],
                        "topic": c["topic"],
                        "group": ("computation" if "canonical" in c else "facts"),
                        "condition": cond,
                        "rep": rep + 1,
                        "seconds": dt,
                        "error": err,
                        **rec,
                        "output_excerpt": (text or "")[:700],
                    }
                )
                v = "ERR" if err else ("PASS" if rec.get("correct") else "FAIL")
                print(f"       -> {v}  ({dt}s)  {str(rec.get('reason', ''))[:150]}", file=sys.stderr, flush=True)

    # aggregate
    print("\n=== SUMMARY ===")
    for cond in conditions:
        for grp in ("facts", "computation"):
            rs = [r for r in results if r["condition"] == cond and r["group"] == grp and r["error"] is None]
            if not rs:
                continue
            n = len(rs)
            cp = sum(1 for r in rs if r.get("correct"))
            bchecks = [r for r in rs if r.get("boundary_ok") is not None]
            bp = sum(1 for r in bchecks if r.get("boundary_ok"))
            line = f"{cond:5} {grp:11}: correct {cp}/{n}"
            if bchecks:
                line += f" | boundary {bp}/{len(bchecks)}"
            print(line)

    if args.out:
        Path(args.out).write_text(json.dumps({"results": results}, indent=2))
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
