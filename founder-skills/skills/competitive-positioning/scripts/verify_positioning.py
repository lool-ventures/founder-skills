#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Delivery gate for competitive positioning.

Validates that the deliverable actually SHOWS what the analysis found, and that no internal
token reached the founder. Exit 0 = publishable, exit 1 = gaps remain.

WHY THIS EXISTS — read before adding or relaxing a check.

Three of the worst defects this skill has shipped were the same shape: analysis that was
computed, paid for, and then never rendered.

  * Axis rationales were written on every run and read from the wrong place, so `report.md`
    showed blank "Rationale:" lines and both HTML surfaces dropped the axis caption — while
    the 25-point review graded POS_05 ("axis rationale explains differentiation value") as a
    PASS on text no founder could see.
  * The explorer embedded the entire scored layer (differentiation score, ranks, vanity flags,
    claim verdicts) and its JavaScript read none of it.
  * The adversarial competitor verdicts reached no renderer, so a competitor judged
    `not_a_competitor` was scored, ranked and tabled indistinguishably from a genuine one.

None of those was caught by a unit test, because each producer was individually correct. They
were caught by reading one live run's artifacts against what actually reached the founder — a
$9-15 instrument, non-deterministic, exercising one path. That does not scale, and it is not
what should stand between a defect and a founder.

So the rule this file enforces is: **a run may not complete while the deliverable is missing
something the artifacts already contain, or while it contains something the founder cannot
use.** Compliance with prose becomes a quality-of-life matter rather than a correctness one,
because a non-compliant run cannot finish.

Modelled deliberately on `financial-model-review/scripts/verify_review.py`, which already had
this shape. Keep the two structurally similar — a reader who knows one should recognise the other.

Usage:
    python verify_positioning.py --dir <artifacts_dir> [--gate {1,2}] [--pretty] [-o <file>]

Gate levels:
    1 = mid-pipeline (artifacts only; report/HTML not expected yet)
    2 = end-of-run, pre-delivery (default) — everything, including the rendered surfaces

Output:
    stdout: JSON with status, artifacts, cross_checks, rendered_checks, summary
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load(dir_path: str, name: str) -> tuple[Any, bool, bool]:
    """Return (data, exists, parse_ok). Never raises."""
    path = os.path.join(dir_path, name)
    if not os.path.exists(path):
        return None, False, False
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), True, True
    except (OSError, json.JSONDecodeError):
        return None, True, False


def _read_text(dir_path: str, name: str) -> str | None:
    path = os.path.join(dir_path, name)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _issue(level: str, message: str) -> dict[str, str]:
    return {"severity": level, "message": message}


def _as_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else []


def _as_dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _is_skipped(data: Any) -> bool:
    return isinstance(data, dict) and data.get("skipped") is True


# ---------------------------------------------------------------------------
# Tier 1 — existence
# ---------------------------------------------------------------------------

_ALWAYS_REQUIRED = [
    "landscape.json",
    "positioning.json",
    "moat_scores.json",
    "positioning_scores.json",
    "checklist.json",
]

# Required only at the end-of-run gate — mid-pipeline these legitimately do not exist yet.
_GATE2_REQUIRED = ["report.json", "report.md"]

_OPTIONAL = ["product_profile.json", "competitor_verification.json", "report.html", "explore.html"]


def _internal_files_in(text: str) -> list[str]:
    """Internal artifact/script filenames present in founder-facing text.

    Returns [] when the shared founder-text policy is unavailable: a missing policy must never fail a
    review that is otherwise complete.
    """
    try:
        shared = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts"))
        if shared not in sys.path:
            sys.path.insert(0, shared)
        import _founder_text  # type: ignore[import-not-found]
    except ImportError:
        return []
    found: list[str] = _founder_text.scan(text)["filenames"]
    return found


def _check_existence(dir_path: str, gate: int) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    required = list(_ALWAYS_REQUIRED) + (list(_GATE2_REQUIRED) if gate >= 2 else [])
    for name in required + _OPTIONAL:
        is_md = name.endswith(".md")
        is_html = name.endswith(".html")
        if is_md or is_html:
            text = _read_text(dir_path, name)
            entry: dict[str, Any] = {"exists": text is not None, "issues": []}
            entry["_text"] = text
            if text is not None and not text.strip():
                entry["issues"].append(_issue("error", f"{name} exists but is empty"))
        else:
            data, exists, parse_ok = _load(dir_path, name)
            entry = {"exists": exists, "issues": []}
            entry["_data"] = data
            entry["_skipped"] = _is_skipped(data)
            if exists and not parse_ok:
                entry["issues"].append(_issue("error", f"{name} is not valid JSON"))
        if name in required and not entry["exists"]:
            entry["issues"].append(_issue("error", f"required artifact missing: {name}"))
        out[name] = entry
    return out


# ---------------------------------------------------------------------------
# Tier 2 — the rendered-surface checks (the class that motivated this file)
# ---------------------------------------------------------------------------

# Enum values that must never reach a founder verbatim. Each is rendered through
# compose_report.py's _humanize; a raw one in report.md means a render path bypassed it.
_RAW_ENUMS = [
    "partially_holds",
    "does_not_hold",
    "not_a_competitor",
    "not_applicable",
    "agent_estimate",
    "founder_override",
    "founder_provided",
    "do_nothing",
    "reclassify_adjacent",
    "challenge_removal",
]

# Checklist criterion IDs. Meaningless to a founder; measured leaking into the coaching
# commentary on a real run.
_CRITERION_ID_RE = re.compile(r"\b(?:COVER|POS|MOAT|EVID|NARR|MISS)_\d{2}\b")

# Internal field names that have reached report.md before.
_FIELD_NAME_RE = re.compile(
    r"\b(?:recent_developments|out_of_window_developments|moat_count|"
    r"deferred_recall_candidates|key_differentiators|research_depth|"
    r"sourced_fields_count|views_fingerprint|graded_against)\b"
)


def _check_rendered(artifacts: dict[str, dict[str, Any]], gate: int) -> list[dict[str, str]]:
    """The deliverable must SHOW what the artifacts contain, and nothing internal."""
    issues: list[dict[str, str]] = []
    if gate < 2:
        return issues

    report_md = artifacts.get("report.md", {}).get("_text")
    if not report_md:
        return issues  # existence check already flagged it

    ps = artifacts.get("positioning_scores.json", {}).get("_data")
    landscape = artifacts.get("landscape.json", {}).get("_data")
    verification = artifacts.get("competitor_verification.json", {}).get("_data")

    # --- 1. axis rationales: present in the scores AND visible in the report -------------
    for view in _as_list(_as_dict(ps).get("views")):
        view = _as_dict(view)
        vid = str(view.get("view_id", "?"))
        for axis in ("x", "y"):
            rationale = view.get(f"{axis}_axis_rationale")
            if not (isinstance(rationale, str) and rationale.strip()):
                issues.append(
                    _issue(
                        "error",
                        f"view '{vid}' has an empty {axis.upper()}-axis rationale — the founder is shown a "
                        f"blank 'Rationale:' line while the checklist may grade POS_05 as a pass",
                    )
                )
                continue
            # A non-empty rationale that never reaches the report is the original defect.
            probe = rationale.strip()[:40]
            if probe and probe not in report_md:
                issues.append(
                    _issue(
                        "error",
                        f"view '{vid}' {axis.upper()}-axis rationale exists in positioning_scores.json but "
                        f"does not appear in report.md — computed and not rendered",
                    )
                )

    # --- 2. no raw enum tokens ------------------------------------------------------------
    for token in _RAW_ENUMS:
        if re.search(rf"\b{re.escape(token)}\b", report_md):
            issues.append(
                _issue("error", f"report.md contains the raw enum token '{token}' — render it through _humanize")
            )

    # --- 3. no internal field names -------------------------------------------------------
    for m in sorted(set(_FIELD_NAME_RE.findall(report_md))):
        issues.append(_issue("error", f"report.md names the internal field '{m}' — a founder cannot use it"))

    # --- 3b. no internal artifact filenames -----------------------------------------------
    # Evidence text from a sub-agent is printed verbatim, and a live run of a sibling skill put
    # `inputs.json` in ten items' evidence. Delegated to the shared policy so "internal" means one thing
    # fleet-wide, and so a founder's OWN uploaded filename is never flagged — naming their file back to
    # them is useful.
    for name in _internal_files_in(report_md):
        issues.append(
            _issue(
                "error",
                f"report.md names the internal file '{name}' — the founder never saw it; say what is "
                f"true of the company or its competitive set instead",
            )
        )

    # --- 4. no criterion IDs ANYWHERE founder-facing --------------------------------------
    # Scoped to the coaching section originally, which measured delivered reports show was too narrow:
    # NARR_01 / COVER_03 / POS_04 appeared elsewhere in the report and this check never looked. The
    # founder-text scan cannot cover it either — its lowercase rule is blind to ALLCAPS, which is why
    # this dedicated regex exists.
    body = report_md.split("## Coaching Commentary", 1)[0]
    for m in sorted(set(_CRITERION_ID_RE.findall(body))):
        issues.append(
            _issue(
                "error",
                f"report.md cites the criterion ID '{m}' — a founder cannot act on it; state the "
                f"finding, or render the criterion's label",
            )
        )

    if "## Coaching Commentary" in report_md:
        commentary = report_md.split("## Coaching Commentary", 1)[1]
        for m in sorted(set(_CRITERION_ID_RE.findall(commentary))):
            issues.append(
                _issue(
                    "error",
                    f"the coaching commentary cites the criterion ID '{m}' — say what the finding IS, "
                    f"not its internal label",
                )
            )

    # --- 5. competitor slugs where a name exists ------------------------------------------
    for comp in _as_list(_as_dict(landscape).get("competitors")):
        comp = _as_dict(comp)
        comp_slug, comp_name = comp.get("slug"), comp.get("name")
        if not (isinstance(comp_slug, str) and comp_slug and isinstance(comp_name, str) and comp_name.strip()):
            continue
        # When the slug and the display name are the same string, the founder is already seeing the
        # name and there is nothing to substitute. Measured as a false positive on a live run: a
        # competitor literally named "n8n" has slug "n8n", and flagging it told the operator to fix
        # Compare with CASE FOLDING ONLY. Stripping punctuation too was the first attempt and it was
        # wrong: "acme-co" and "Acme Co" both reduce to "acmeco", which would have silenced a genuine
        # leak. A test caught it. The rule is literal — if the slug string IS the displayed name there
        # is nothing to substitute; a hyphen where the founder should see a space is still a leak.
        if comp_slug.strip().lower() == comp_name.strip().lower():
            continue
        # A slug is only a leak when it appears OUTSIDE a code span; the evidence tables
        # legitimately key on slug. Restrict to the prose-bearing "leader:" construction and
        # the warnings list, which is where it was measured.
        for line in report_md.splitlines():
            if comp_slug in line and ("leader:" in line or line.lstrip().startswith("- [")):
                issues.append(
                    _issue(
                        "error",
                        f"report.md shows the slug '{comp_slug}' where the name "
                        f"'{comp_name}' belongs: {line.strip()[:90]}",
                    )
                )
                break

    # --- 6. the adversarial verdicts must reach the deliverable --------------------------
    if verification is not None and not _is_skipped(verification):
        verdicts = _as_list(_as_dict(verification).get("verdicts"))
        if verdicts and "Competitor Set Verification" not in report_md:
            issues.append(
                _issue(
                    "error",
                    "competitor_verification.json carries verdicts but report.md has no verification "
                    "section — a challenged competitor is tabled indistinguishably from a genuine one",
                )
            )
        for v in verdicts:
            v = _as_dict(v)
            if str(v.get("verdict")) == "not_a_competitor" and "Retained despite the challenge" not in report_md:
                issues.append(
                    _issue(
                        "error",
                        f"'{v.get('slug')}' was judged not_a_competitor and kept, but report.md does not "
                        f"say so — read its position with the verdict in mind is exactly what the "
                        f"founder cannot do",
                    )
                )
                break

    # --- 7. the explorer must render the scored layer it embeds --------------------------
    explore = artifacts.get("explore.html", {}).get("_text")
    if explore:
        m = re.search(r"const\s+DATA\s*=\s*(\{.*?\});", explore, re.DOTALL)
        if m:
            try:
                payload = json.loads(m.group(1))
            except json.JSONDecodeError:
                payload = {}
            unread = sorted(k for k in payload if f"DATA.{k}" not in explore)
            if unread:
                issues.append(
                    _issue(
                        "error",
                        f"explore.html embeds key(s) its script never reads: {unread} — a founder-facing "
                        f"feature that silently does not exist, still paid for in payload",
                    )
                )

    return issues


# ---------------------------------------------------------------------------
# Tier 3 — cross-artifact consistency
# ---------------------------------------------------------------------------


def _check_cross(artifacts: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    landscape = _as_dict(artifacts.get("landscape.json", {}).get("_data"))
    ps = _as_dict(artifacts.get("positioning_scores.json", {}).get("_data"))
    moats = _as_dict(artifacts.get("moat_scores.json", {}).get("_data"))
    checklist = _as_dict(artifacts.get("checklist.json", {}).get("_data"))
    verification = artifacts.get("competitor_verification.json", {}).get("_data")

    # Checklist EVIDENCE, at the artifact level — not only what compose happened to render.
    #
    # A live run produced 11 items citing `landscape.json` / `positioning.json` in evidence while
    # report.md scanned clean, because this skill renders checklist evidence nowhere. Checking only
    # the rendered report therefore reports a compliance that does not exist, and it ships the moment
    # an item's evidence does get rendered or reaches the founder through the coaching payload.
    #
    # Warning, not error: not founder-facing today, so it must not block a hand-over. The report.md
    # check stays at error severity, where it IS founder-facing.
    for _item in _as_list(checklist.get("items")):
        _item = _as_dict(_item)
        _ev = _item.get("evidence")
        if not isinstance(_ev, str):
            continue
        for _name in _internal_files_in(_ev):
            issues.append(
                _issue(
                    "warning",
                    f"checklist item {_item.get('id', '?')} cites the internal file '{_name}' in its "
                    f"evidence — the founder never saw it; say what is true of the company instead",
                )
            )

    slugs = {
        str(c.get("slug"))
        for c in _as_list(landscape.get("competitors"))
        if isinstance(c, dict) and isinstance(c.get("slug"), str) and c.get("slug")
    }

    # --- the checklist must have graded the CURRENT map ---------------------------------
    current_fp = ps.get("views_fingerprint")
    graded_fp = _as_dict(checklist.get("graded_against")).get("views_fingerprint")
    if (
        isinstance(current_fp, str)
        and current_fp
        and isinstance(graded_fp, str)
        and graded_fp
        and current_fp != graded_fp
    ):
        issues.append(
            _issue(
                "error",
                "checklist.json was graded against a different positioning map than the current "
                "positioning_scores.json — re-run the checklist. run_id parity cannot detect this, "
                "because a re-score does not change the run_id",
            )
        )

    # --- every competitor must be scored on both instruments ----------------------------
    scored = set(_as_dict(moats.get("companies")).keys()) - {"_startup"}
    for missing in sorted(slugs - scored):
        issues.append(_issue("error", f"competitor '{missing}' is in the landscape but absent from moat_scores"))

    for view in _as_list(ps.get("views")):
        view = _as_dict(view)
        plotted = {
            str(_as_dict(p).get("competitor"))
            for p in _as_list(view.get("points"))
            if isinstance(_as_dict(p).get("competitor"), str)
        } - {"_startup"}
        for missing in sorted(slugs - plotted):
            issues.append(
                _issue(
                    "error",
                    f"competitor '{missing}' is in the landscape but not plotted on view "
                    f"'{view.get('view_id', '?')}' — the map is incomplete",
                )
            )

    # --- rank sanity: rank may reach competitor_count + 1, never beyond -----------------
    for view in _as_list(ps.get("views")):
        view = _as_dict(view)
        n = view.get("competitor_count")
        if not isinstance(n, int):
            continue
        for axis in ("x", "y"):
            rank = view.get(f"startup_{axis}_rank")
            if isinstance(rank, int) and rank > n + 1:
                issues.append(
                    _issue(
                        "error",
                        f"view '{view.get('view_id', '?')}' {axis.upper()} rank {rank} exceeds the "
                        f"{n + 1} entities ranked",
                    )
                )

    # --- declined recall candidates must be accounted for -------------------------------
    # Set comparison, not an emptiness check: a deferred list holding one of four candidates
    # would otherwise suppress the warning while three were silently lost.
    if verification is not None and not _is_skipped(verification):
        unmatched = _as_list(_as_dict(_as_dict(verification).get("recall_gaps")).get("unmatched"))
        deferred = landscape.get("deferred_recall_candidates")
        if isinstance(deferred, list):  # absent => pre-gate artifact, stay silent
            actual = {str(_as_dict(d).get("slug")) for d in deferred if isinstance(_as_dict(d).get("slug"), str)}
            expected = {
                str(_as_dict(u).get("slug"))
                for u in unmatched
                if isinstance(_as_dict(u).get("slug"), str)
                and _as_dict(u).get("slug")
                and str(_as_dict(u).get("slug")) not in slugs
            }
            for lost in sorted(expected - actual):
                issues.append(
                    _issue(
                        "warning",
                        f"recall candidate '{lost}' was neither adopted into the competitor set nor "
                        f"retained as a declined candidate — it can no longer be re-offered",
                    )
                )

    return issues


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def verify(dir_path: str, gate: int = 2) -> dict[str, Any]:
    artifacts = _check_existence(dir_path, gate)
    rendered = _check_rendered(artifacts, gate)
    cross = _check_cross(artifacts)

    errors: list[str] = []
    warnings: list[str] = []
    for name, entry in artifacts.items():
        for iss in entry["issues"]:
            (errors if iss["severity"] == "error" else warnings).append(f"{name}: {iss['message']}")
    for iss in rendered + cross:
        (errors if iss["severity"] == "error" else warnings).append(iss["message"])

    public = {name: {"exists": e["exists"], "issues": e["issues"]} for name, e in artifacts.items()}
    return {
        "status": "publishable" if not errors else "gaps",
        "gate": gate,
        "artifacts": public,
        "rendered_checks": rendered,
        "cross_checks": cross,
        "summary": {
            "error_count": len(errors),
            "warning_count": len(warnings),
            "errors": errors,
            "warnings": warnings,
        },
        "_produced_by": "verify_positioning",
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Delivery gate for competitive positioning")
    p.add_argument("--dir", required=True, help="Artifacts directory")
    p.add_argument(
        "--gate",
        type=int,
        default=2,
        choices=[1, 2],
        help="1 = mid-pipeline (artifacts only); 2 = end-of-run, pre-delivery (default)",
    )
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if not os.path.isdir(args.dir):
        print(f"Error: not a directory: {args.dir}", file=sys.stderr)
        sys.exit(1)

    result = verify(args.dir, gate=args.gate)
    out = json.dumps(result, indent=2 if args.pretty else None) + "\n"

    if args.output:
        abs_path = os.path.abspath(args.output)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(out)
        receipt = {
            "ok": result["status"] == "publishable",
            "path": abs_path,
            "status": result["status"],
            "error_count": result["summary"]["error_count"],
            "warning_count": result["summary"]["warning_count"],
        }
        sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
    else:
        sys.stdout.write(out)

    for msg in result["summary"]["errors"]:
        print(f"Gap: {msg}", file=sys.stderr)
    for msg in result["summary"]["warnings"]:
        print(f"Note: {msg}", file=sys.stderr)

    sys.exit(0 if result["status"] == "publishable" else 1)


if __name__ == "__main__":
    main()
