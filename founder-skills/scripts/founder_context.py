#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Per-company founder context manager.

Manages founder-context-{slug}.json files with init/read/merge/validate/
update-identity subcommands. Each file stores stable identity fields, key
metrics with provenance, fundraising data, and prior skill run history.

Usage:
    python founder_context.py init --company-name "Acme Corp" --stage seed \
        --sector fintech --geography US --artifacts-root ./artifacts

    python founder_context.py read --slug acme-corp --artifacts-root ./artifacts

    python founder_context.py merge --slug acme-corp --source user \
        --data '{"team_size": 12}' --artifacts-root ./artifacts

    python founder_context.py validate --slug acme-corp --artifacts-root ./artifacts

    python founder_context.py update-identity --slug acme-corp --stage series-a \
        --sector "ai-native" --artifacts-root ./artifacts

Exit codes:
    0 = success
    1 = error (missing file, validation failure, protected field violation)
    2 = ambiguous (multiple context files, need --slug)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, NoReturn

# --- Constants ---

STABLE_FIELDS = frozenset({"company_name", "slug", "stage", "sector", "geography"})

PROTECTED_KEY_METRICS = frozenset(
    {
        "runway_months",
        "burn_monthly",
        "arr",
        "mrr",
        "growth_rate_monthly",
        "nrr",
        "ltv",
        "cac",
        "customers",
        "gross_margin",
    }
)

PROTECTED_FUNDRAISING = frozenset({"current_cash"})

VALID_STAGES = {"pre-seed", "seed", "series-a", "series-b", "series-c", "series-d", "later"}


def _normalize_enum_arg(value: str) -> str:
    """Coerce an enum-valued CLI arg to canonical form before choices-validation.

    Callers and sibling scripts mix separators and case for the same token — e.g.
    'Series A' / 'series_a' for the canonical hyphenated 'series-a', or 'AI_Native'
    for 'ai-native'. argparse applies type= BEFORE choices=, so this accepts the
    natural spelling without widening the valid set (the stored value stays canonical).
    """
    return value.strip().lower().replace("_", "-").replace(" ", "-")


CANONICAL_SECTOR_TYPES = frozenset(
    {
        "saas",
        "ai-native",
        "marketplace",
        "hardware",
        "hardware-subscription",
        "consumer-subscription",
        "usage-based",
        "transactional-fintech",
        "retail",
    }
)

_SECTOR_ALIASES: dict[str, str] = {
    "b2b saas": "saas",
    "b2b": "saas",
    "ai native": "ai-native",
    "ai": "ai-native",
    "two-sided marketplace": "marketplace",
    "deep-tech": "hardware",
    "deeptech": "hardware",
    "hardware subscription": "hardware-subscription",
    "consumer": "consumer-subscription",
    "consumer subscription": "consumer-subscription",
    "usage based": "usage-based",
    "consumption": "usage-based",
    "fintech": "saas",
    "proptech": "saas",
    "insurtech": "saas",
    "edtech": "saas",
    "healthtech": "saas",
    "legaltech": "saas",
    "regtech": "saas",
    "cyber": "saas",
    "cybersecurity": "saas",
    "transactional fintech": "transactional-fintech",
    "payment processing": "transactional-fintech",
    "retail": "retail",
    "d2c": "retail",
    "e-commerce": "retail",
    "ecommerce": "retail",
}

# Precedence for substring extraction; most specific first.
# Each entry is (match_token, canonical_value). Match tokens are bare fragments
# that appear in free-form text; canonical values are the output.
#
# POLICY: When multiple tokens match, the FIRST match wins. "AI SaaS" matches
# "ai" before "saas" -> resolves to "ai-native". This is intentional: AI-native
# companies that also use SaaS pricing are better served by AI-specific benchmarks.
# Use --sector-type override for exceptions.
_SECTOR_SUBSTRING_PRECEDENCE: list[tuple[str, str]] = [
    ("hardware subscription", "hardware-subscription"),
    ("hardware-subscription", "hardware-subscription"),
    ("consumer subscription", "consumer-subscription"),
    ("consumer-subscription", "consumer-subscription"),
    ("usage based", "usage-based"),
    ("usage-based", "usage-based"),
    ("marketplace", "marketplace"),
    ("hardware", "hardware"),
    ("retail", "retail"),
    ("d2c", "retail"),
    ("e-commerce", "retail"),
    ("ecommerce", "retail"),
    ("payment processing", "transactional-fintech"),
    ("payments", "transactional-fintech"),
    ("fintech", "saas"),
    ("ai", "ai-native"),
    ("saas", "saas"),
]


# --- Helpers ---


def _write_output(data: str, output_path: str | None) -> None:
    """Write JSON string to file or stdout."""
    if output_path:
        abs_path = os.path.abspath(output_path)
        parent = os.path.dirname(abs_path)
        if parent == "/":
            print(
                f"Error: output path resolves to root directory: {output_path}",
                file=sys.stderr,
            )
            sys.exit(1)
        os.makedirs(parent, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(data)
    else:
        sys.stdout.write(data)


def _slugify(name: str) -> str:
    """Convert company name to slug: lowercase, hyphens, strip special chars."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug


def sector_type_unknown_message(sector: str) -> str:
    """Why a free-form sector did not resolve, phrased so it does not invite a wrong fix.

    `sector_type` is a REVENUE MODEL, not an industry. The distinction is invisible from the
    field name and the old message hid it: told 'Consumer social / audio' was unresolvable and
    handed a list reading saas / marketplace / usage-based, a reader reasonably concludes the
    taxonomy is missing industries and starts adding them. It is not. An industry does not
    determine a revenue model -- a consumer audio app may be subscription, marketplace or
    ad-supported -- so refusing to guess is the correct behaviour here, not a gap.

    Deliberately NOT offering an "ad-supported" value: no ad-supported benchmarks exist in
    this repo, so the enum entry would gate checklist criteria against nothing and read as
    supported when it is not.
    """
    valid = ", ".join(sorted(CANONICAL_SECTOR_TYPES))
    return (
        f"sector_type not set: '{sector}' names an industry, and sector_type is a revenue "
        f"model (it selects unit-economics benchmarks). An industry does not imply one -- "
        f"the same product can be subscription, marketplace or ad-supported. Leaving it unset "
        f"is correct when the model is genuinely unknown; the only effect is that "
        f"sector-specific checklist gating is skipped. Set it with --sector-type when you do "
        f"know: {valid}."
    )


def _derive_sector_type(sector: str) -> str | None:
    """Derive canonical sector_type from free-form sector string.

    Resolution order: exact match -> alias lookup -> word-boundary substring -> None.
    """
    raw = sector.strip().lower()
    if not raw:
        return None

    # 1. Exact canonical match
    if raw in CANONICAL_SECTOR_TYPES:
        return raw

    # 2. Alias lookup
    if raw in _SECTOR_ALIASES:
        return _SECTOR_ALIASES[raw]

    # 3. Word-boundary substring extraction with precedence
    for token, canonical in _SECTOR_SUBSTRING_PRECEDENCE:
        if re.search(rf"\b{re.escape(token)}\b", raw):
            return canonical

    # 4. No match
    print(sector_type_unknown_message(sector), file=sys.stderr)
    return None


def _context_path(artifacts_root: str, slug: str) -> str:
    """Return the path for a founder context file."""
    return os.path.join(artifacts_root, f"founder-context-{slug}.json")


def _now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _find_context_files(artifacts_root: str) -> list[str]:
    """Find all founder-context-*.json files in artifacts root."""
    if not os.path.isdir(artifacts_root):
        return []
    results: list[str] = []
    for entry in os.listdir(artifacts_root):
        if entry.startswith("founder-context-") and entry.endswith(".json"):
            full_path = os.path.join(artifacts_root, entry)
            if os.path.isfile(full_path):
                results.append(full_path)
    return sorted(results)


def _slug_from_filename(filename: str) -> str:
    """Extract slug from founder-context-{slug}.json filename."""
    base = os.path.basename(filename)
    # Remove prefix and suffix
    return base[len("founder-context-") : -len(".json")]


def _resolve_slug(artifacts_root: str, slug: str | None) -> tuple[int, str]:
    """Resolve slug, auto-detecting if not provided.

    Returns (exit_code, resolved_slug). exit_code 0 means success.
    """
    if slug:
        return 0, slug

    # Auto-detect
    files = _find_context_files(artifacts_root)
    if len(files) == 0:
        return 1, "No founder context files found"
    if len(files) == 1:
        return 0, _slug_from_filename(files[0])
    # Multiple files
    slugs = [_slug_from_filename(f) for f in files]
    print(
        f"Ambiguous: found {len(files)} founder context files. Use --slug to disambiguate: {', '.join(slugs)}",
        file=sys.stderr,
    )
    return 2, ""


def _format_json(data: dict[str, Any], pretty: bool) -> str:
    """Format dict as JSON string."""
    if pretty:
        return json.dumps(data, indent=2, sort_keys=False) + "\n"
    return json.dumps(data, sort_keys=False) + "\n"


def _check_protected_fields(merge_data: dict[str, Any], source: str, force: bool) -> bool:
    """Check if merge data touches protected fields when source is not 'user'.

    Returns True if merge should proceed, False if it should be rejected.
    Prints error/warning to stderr as appropriate.
    """
    if source == "user":
        return True

    violations: list[str] = []

    # Check key_metrics protected fields
    km = merge_data.get("key_metrics", {})
    if isinstance(km, dict):
        for field in PROTECTED_KEY_METRICS:
            if field in km:
                violations.append(f"key_metrics.{field}")

    # Check fundraising protected fields
    fr = merge_data.get("fundraising", {})
    if isinstance(fr, dict):
        for field in PROTECTED_FUNDRAISING:
            if field in fr:
                violations.append(f"fundraising.{field}")

    if not violations:
        return True

    if force:
        for v in violations:
            print(
                f"WARNING: --force used to override protection for {v} from source '{source}'",
                file=sys.stderr,
            )
        return True

    for v in violations:
        print(
            f"ERROR: refusing to merge derived value for {v} from "
            f"source '{source}' \u2014 roadmap requires user confirmation. "
            f"Use --source user if the founder confirmed this value, "
            f"or --force to override.",
            file=sys.stderr,
        )
    return False


def _deep_merge(target: dict[str, Any], updates: dict[str, Any]) -> None:
    """Recursively merge ``updates`` into ``target`` in place.

    For keys present in both whose values are dicts, recurse so nested
    sub-dicts are merged rather than clobbered. Otherwise overwrite.
    """
    for key, val in updates.items():
        if key in target and isinstance(target[key], dict) and isinstance(val, dict):
            _deep_merge(target[key], val)
        else:
            target[key] = val


def _stamp_key_metrics_source(km: dict[str, Any], source: str) -> dict[str, Any]:
    """Add source provenance to each key_metrics entry."""
    stamped: dict[str, Any] = {}
    for key, val in km.items():
        if isinstance(val, dict):
            stamped[key] = {**val, "source": source}
        else:
            stamped[key] = val
    return stamped


# --- Subcommands ---


# The stage a `ctx_basics.stage` record names, as the context file spells it. `series_b_plus` takes its
# specific stage from `ctx_stage_detail`.
_RECORDED_STAGE = {"pre_seed": "pre-seed", "seed": "seed", "series_a": "series-a"}
_RECORDED_STAGE_DETAIL = {"series_b": "series-b", "series_c": "series-c", "series_d": "series-d", "later": "later"}
_CTX_FIELDS = ("company_name", "stage", "sector", "geography")


def _init_refusal(code: int, payload: dict[str, Any], line: str) -> NoReturn:
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    print(line, file=sys.stderr)
    sys.exit(code)


def _check_gate_records(args: argparse.Namespace) -> Any:
    """With a gate ledger for this run, `init` writes a context only from recorded answers.

    Keyed on the ledger existing, never on `--run-id` alone: skills pass `--run-id` today with no ledger,
    and must behave exactly as before. Each Step-1 field needs a record (exit 10 opens the missing ones
    and prints what to ask; under FS_HOST_NO_ASK exit 12, nothing to ask), and every typed value must be the one
    recorded (exit 1 otherwise). Returns (the registry module, the run's paths) with a ledger, else None.
    """
    run_id = args.run_id
    root = os.path.abspath(args.artifacts_root)
    if not run_id or not os.path.isfile(os.path.join(root, "runs", str(run_id), "gates.json")):
        return None
    try:
        import _gates
        import _run_status
    except Exception as e:  # the registry fails closed
        _init_refusal(
            2,
            {"status": "error", "code": "REGISTRY_UNREACHABLE", "message": str(e)},
            f"Error: the plugin's gate registry is not reachable: {e}",
        )
    if args.skill is None:
        _init_refusal(
            2,
            {"status": "error", "code": "USAGE", "message": "this run has a gate ledger, so init needs --skill"},
            f"Error: run {run_id} has a gate ledger; pass --skill so init can check the run is this skill's",
        )
    paths = _run_status.run_paths(root, run_id)
    status = _run_status.load_status(paths) or {}
    if status.get("status") in _run_status.FINAL_STATUSES or status.get("skill") != args.skill:
        _init_refusal(
            1,
            {
                "status": "rejected",
                "code": "GATE_RECORD_MISMATCH",
                "run_id": run_id,
                "run_status": status.get("status"),
            },
            f"Rejected: run {run_id} is {status.get('status')} for {status.get('skill')}; no context was written",
        )

    def fn(ctx: Any, ledger: dict[str, Any], st: dict[str, Any]) -> dict[str, Any]:
        keys = [f"ctx_basics.{f}" for f in _CTX_FIELDS]
        results = {k: _gates.require_terminal(ctx, ledger, k, by="founder_context.py") for k in keys}
        stage = (ledger["gates"].get("ctx_basics.stage") or {}).get("current") or {}
        if results["ctx_basics.stage"] == "ok" and stage.get("answer_id") == "series_b_plus":
            results["ctx_stage_detail"] = _gates.require_terminal(
                ctx, ledger, "ctx_stage_detail", by="founder_context.py"
            )
        waiting = [k for k, v in results.items() if v == "waiting"]
        quiet = _gates.no_ask(ledger)
        return {
            "waiting": waiting,
            "needs_input": [] if quiet else [_gates.needs_input(ctx, ledger, k) for k in waiting],
            "stop": _gates.no_ask_payload(ctx, ledger, waiting) if quiet else None,
            "records": {k: (ledger["gates"].get(k) or {}).get("current") for k in results},
        }

    try:
        out = _gates.transact(paths, fn)
    except _gates.Declined as e:
        _init_refusal(1, e.payload(), f"Refused ({e.code}): {e}; stop here and produce nothing")
    except _gates.GateRejection as e:
        _init_refusal(1, e.payload(), f"Rejected ({e.code}): {e}; no context was written")
    except (_run_status.RunStatusError, _gates.Unimplemented) as e:
        _init_refusal(
            2, {"status": "error", "code": getattr(e, "code", "GATE_NOT_WIRED"), "message": str(e)}, f"Error: {e}"
        )
    if out["waiting"] and out.get("stop"):
        _init_refusal(
            _gates.NO_ASK_EXIT,
            {**out["stop"], "blocked_by_gate": out["waiting"][0]},
            f"Waiting (the request said not to ask): {', '.join(out['waiting'])}. {_gates.NO_ASK_STOP}",
        )
    if out["waiting"]:
        _init_refusal(
            _gates.EXIT_CODES["waiting"],
            {"status": "waiting", "blocked_by_gate": out["waiting"][0], "needs_input": out["needs_input"]},
            f"Waiting: {', '.join(out['waiting'])} not yet answered; ask, record the answers, then run init again",
        )
    mismatches = _typed_mismatches(args, out["records"])
    if mismatches:
        _init_refusal(
            1,
            {"status": "rejected", "code": "GATE_RECORD_MISMATCH", "run_id": run_id, "mismatches": mismatches},
            f"Rejected: {mismatches[0]['field']} was typed {mismatches[0]['typed']!r} but recorded "
            f"{mismatches[0]['recorded']!r}; no context was written",
        )
    return _gates, paths


def _typed_mismatches(args: argparse.Namespace, records: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for field in _CTX_FIELDS:
        cur = records.get(f"ctx_basics.{field}") or {}
        if cur.get("resolution") == "not_applicable":
            continue
        typed = getattr(args, field)
        answer_id = cur.get("answer_id")
        if field == "stage":
            recorded = _RECORDED_STAGE.get(str(answer_id))
            if answer_id == "series_b_plus":
                detail = (records.get("ctx_stage_detail") or {}).get("answer_id")
                recorded = _RECORDED_STAGE_DETAIL.get(str(detail))
        elif answer_id == "not_sure":
            recorded = ""
            # "Not sure" is recorded as an empty value; the option's label or id typed for it means the same.
            if str(typed or "").strip().casefold().replace("_", " ") in ("", "not sure"):
                setattr(args, field, "")
                continue
        elif cur.get("value") is not None:
            recorded = cur["value"]
        else:
            continue  # a working title or the model file's name: the typed value is what was chosen
        if typed != recorded:
            out.append({"field": field, "typed": typed, "recorded": recorded})
    return out


def cmd_init(args: argparse.Namespace) -> None:
    """Create a new founder context file."""
    checked = _check_gate_records(args)
    slug = args.slug if args.slug else _slugify(args.company_name)
    artifacts_root: str = args.artifacts_root
    os.makedirs(artifacts_root, exist_ok=True)

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    now = _now_iso()

    context: dict[str, Any] = {
        "metadata": {
            "run_id": run_id,
            "review_date": now[:10],  # YYYY-MM-DD
            "last_updated": now,
        },
        "company_name": args.company_name,
        "slug": slug,
        "stage": args.stage,
        "sector": args.sector,
        "geography": args.geography,
    }

    if hasattr(args, "sector_type") and args.sector_type:
        context["sector_type"] = args.sector_type
    else:
        derived = _derive_sector_type(args.sector)
        context["sector_type"] = derived
        if derived is None:
            context.setdefault("warnings", []).append(
                {
                    "code": "W_SECTOR_TYPE_UNKNOWN",
                    "message": sector_type_unknown_message(args.sector),
                }
            )

    path = _context_path(artifacts_root, slug)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(context, f, indent=2)
    if checked is not None:
        # From here a company basic taken from the materials stands for the run: the file above is not rewritten.
        gates_mod, run_paths = checked
        gates_mod.mark_context_written(run_paths)

    output = _format_json(context, args.pretty)
    _write_output(output, args.output)


def _read_with_ledger(args: argparse.Namespace) -> str | None:
    """With a gate ledger for this run, `read` settles the Step-1 gates a read decides.

    Keyed on the ledger existing, as `init` is: with no `--run-id`, or no `runs/<id>/gates.json`, this
    returns None and `read` is exactly what it always was. Otherwise:

      * a run already bound to a company reads that company's context (a resume never re-asks which);
      * several contexts make `ctx_select_company` owed: with no record the read stops at exit 10 and
        prints the question; a recorded company is read; `different_company` reads as "not found" (exit
        1, so the skill creates a new context); a `--slug` other than the record is refused;
      * a context that is read records the Step-1 basics as not applicable ("context existed"), once, and
        a request line for one of them is listed in the run's notices as not used.

    Returns the slug to read, or None when nothing here applies."""
    run_id = getattr(args, "run_id", None)
    root = os.path.abspath(args.artifacts_root)
    if not run_id or not os.path.isfile(os.path.join(root, "runs", str(run_id), "gates.json")):
        return None
    try:
        import _gates
        import _run_status
    except Exception as e:  # the registry fails closed
        _init_refusal(
            2,
            {"status": "error", "code": "REGISTRY_UNREACHABLE", "message": str(e)},
            f"Error: the plugin's gate registry is not reachable: {e}",
        )
    if args.skill is None:
        _init_refusal(
            2,
            {"status": "error", "code": "USAGE", "message": "this run has a gate ledger, so read needs --skill"},
            f"Error: run {run_id} has a gate ledger; pass --skill so read can check the run is this skill's",
        )
    paths = _run_status.run_paths(root, run_id)
    status = _run_status.load_status(paths) or {}
    if status.get("status") in _run_status.FINAL_STATUSES or status.get("skill") != args.skill:
        _init_refusal(
            1,
            {
                "status": "rejected",
                "code": "GATE_RECORD_MISMATCH",
                "run_id": run_id,
                "run_status": status.get("status"),
            },
            f"Rejected: run {run_id} is {status.get('status')} for {status.get('skill')}; nothing was read",
        )
    files = _find_context_files(root)
    bound = status.get("slug") if isinstance(status.get("slug"), str) else None
    if bound and not os.path.isfile(_context_path(root, bound)):
        bound = None

    def fn(ctx: Any, ledger: dict[str, Any], st: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {"slug": args.slug}
        gates = ledger.get("gates") or {}
        if bound:
            if args.slug and args.slug != bound:
                return {"mismatch": bound}
            out["slug"] = bound
            entry = gates.get("ctx_select_company") or {}
            owed = _gates.owed(ctx, _gates.GATES["ctx_select_company"], None)
            if owed and entry.get("state") not in ("answered", "not_owed"):
                _gates.record(
                    ctx,
                    ledger,
                    "ctx_select_company",
                    resolution="not_applicable",
                    basis="script",
                    note="the run is bound to its company",
                    by="founder_context.py",
                )
        elif len(files) >= 2:
            got = _gates.require_terminal(ctx, ledger, "ctx_select_company", by="founder_context.py")
            if got == "waiting":
                if _gates.no_ask(ledger):
                    return {"waiting": True, "stop": _gates.no_ask_payload(ctx, ledger, ["ctx_select_company"])}
                return {"waiting": True, "needs_input": _gates.needs_input(ctx, ledger, "ctx_select_company")}
            picked = ((ledger["gates"].get("ctx_select_company") or {}).get("current") or {}).get("answer_id")
            if picked == "different_company":
                return {"not_found": True}
            if args.slug and args.slug != picked:
                return {"mismatch": picked}
            out["slug"] = picked
        elif not files:
            return {"not_found": True}
        for key in [f"ctx_basics.{f}" for f in _CTX_FIELDS] + ["ctx_stage_detail"]:
            entry = (ledger.get("gates") or {}).get(key) or {}
            if entry.get("state") in ("answered", "not_owed"):
                continue
            pending = _gates.pending_pre_answer(ledger, key)
            _gates.record(
                ctx,
                ledger,
                key,
                resolution="not_applicable",
                basis="script",
                note="context existed",
                by="founder_context.py",
            )
            if pending is not None:
                ledger.setdefault("notices", []).append(
                    {"code": "PRE_ANSWER_IGNORED", "gate": key, "lines": pending["raw"], "reason": "not_owed"}
                )
        return out

    try:
        out = _gates.transact(paths, fn)
    except _gates.Declined as e:
        _init_refusal(1, e.payload(), f"Refused ({e.code}): {e}; stop here and produce nothing")
    except _gates.GateRejection as e:
        _init_refusal(1, e.payload(), f"Rejected ({e.code}): {e}; nothing was read")
    except (_run_status.RunStatusError, _gates.Unimplemented) as e:
        _init_refusal(
            2, {"status": "error", "code": getattr(e, "code", "GATE_NOT_WIRED"), "message": str(e)}, f"Error: {e}"
        )
    if out.get("waiting") and out.get("stop"):
        _init_refusal(
            _gates.NO_ASK_EXIT,
            {**out["stop"], "blocked_by_gate": "ctx_select_company"},
            f"Waiting (the request said not to ask): ctx_select_company. {_gates.NO_ASK_STOP}",
        )
    if out.get("waiting"):
        _init_refusal(
            _gates.EXIT_CODES["waiting"],
            {"status": "waiting", "blocked_by_gate": "ctx_select_company", "needs_input": [out["needs_input"]]},
            "Waiting: several companies have a context; ask which one, record it, then read again",
        )
    if out.get("not_found"):
        # Its own code, so a caller can tell "create the context" from a refusal (GATE_RECORD_MISMATCH and the
        # other rejections are exit 1 too).
        _init_refusal(
            1,
            {"status": "not_found", "code": "CONTEXT_NOT_FOUND", "run_id": run_id},
            "No founder context for this company",
        )
    if "mismatch" in out:
        _init_refusal(
            1,
            {"status": "rejected", "code": "GATE_RECORD_MISMATCH", "run_id": run_id, "recorded": out["mismatch"]},
            f"Rejected: --slug {args.slug!r} is not the company recorded for this run ({out['mismatch']!r})",
        )
    slug = out.get("slug")
    return slug if isinstance(slug, str) and slug else None


def cmd_read(args: argparse.Namespace) -> None:
    """Read and output an existing founder context file."""
    artifacts_root: str = args.artifacts_root
    rc, slug = _resolve_slug(artifacts_root, _read_with_ledger(args) or args.slug)
    if rc != 0:
        if slug:
            print(slug, file=sys.stderr)
        sys.exit(rc)

    path = _context_path(artifacts_root, slug)
    if not os.path.isfile(path):
        print(f"Founder context not found: {path}", file=sys.stderr)
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        context = json.load(f)

    output = _format_json(context, args.pretty)
    _write_output(output, args.output)


def cmd_merge(args: argparse.Namespace) -> None:
    """Merge data into an existing founder context file.

    NOT currently invoked by any skill workflow — skills only ``init`` the context
    once (from the deck basics) and ``read``/import it. ``merge`` is the retained,
    provenance-gated write-back primitive for updating a shared per-company context
    (e.g. a later skill persisting a refined metric); protected metrics require
    ``--source user`` or ``--force``. Cross-skill data currently flows via artifact
    import, not through here. Keep it: it is the write path a deterministic
    cross-artifact consistency check would build on. Do not treat it as dead code.
    """
    artifacts_root: str = args.artifacts_root
    rc, slug = _resolve_slug(artifacts_root, args.slug)
    if rc != 0:
        if slug:
            print(slug, file=sys.stderr)
        sys.exit(rc)

    path = _context_path(artifacts_root, slug)
    if not os.path.isfile(path):
        print(f"Founder context not found: {path}", file=sys.stderr)
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        context: dict[str, Any] = json.load(f)

    try:
        merge_data: dict[str, Any] = json.loads(args.data)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in --data: {e}", file=sys.stderr)
        sys.exit(1)

    source: str = args.source

    # Check protected fields
    if not _check_protected_fields(merge_data, source, args.force):
        sys.exit(1)

    # Remove stable fields from merge data (they cannot be overwritten)
    for field in STABLE_FIELDS:
        merge_data.pop(field, None)

    # Stamp source on key_metrics entries
    if "key_metrics" in merge_data and isinstance(merge_data["key_metrics"], dict):
        merge_data["key_metrics"] = _stamp_key_metrics_source(merge_data["key_metrics"], source)

    # Deep merge: for dict values, merge recursively; otherwise overwrite.
    # Protected fields are gated by _check_protected_fields above, so recursion
    # here only touches user-confirmed or non-protected nested data.
    _deep_merge(context, merge_data)

    # Handle --add-skill-run
    if args.add_skill_run:
        runs: list[str] = context.get("prior_skill_runs", [])
        if args.add_skill_run not in runs:
            runs.append(args.add_skill_run)
        context["prior_skill_runs"] = runs

    # Always update timestamp
    meta = context.setdefault("metadata", {})
    meta["last_updated"] = _now_iso()

    with open(path, "w", encoding="utf-8") as f:
        json.dump(context, f, indent=2)

    output = _format_json(context, args.pretty)
    _write_output(output, args.output)


def cmd_validate(args: argparse.Namespace) -> None:
    """Validate a founder context file."""
    artifacts_root: str = args.artifacts_root
    rc, slug = _resolve_slug(artifacts_root, args.slug)
    if rc != 0:
        if slug:
            print(slug, file=sys.stderr)
        sys.exit(rc)

    path = _context_path(artifacts_root, slug)
    if not os.path.isfile(path):
        print(f"Founder context not found: {path}", file=sys.stderr)
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        context: dict[str, Any] = json.load(f)

    errors: list[str] = []

    # Check required stable identity fields
    for field in ("company_name", "slug", "stage", "sector", "geography"):
        if field not in context or not context[field]:
            errors.append(f"Missing required field: {field}")

    # Validate stage enum
    if "stage" in context and context["stage"] not in VALID_STAGES:
        errors.append(f"Invalid stage '{context['stage']}': must be one of {', '.join(sorted(VALID_STAGES))}")

    # Validate sector and geography are non-empty strings
    if "sector" in context and (not isinstance(context["sector"], str) or not context["sector"].strip()):
        errors.append("sector must be a non-empty string")
    if "geography" in context and (not isinstance(context["geography"], str) or not context["geography"].strip()):
        errors.append("geography must be a non-empty string")

    # Validate key_metrics provenance structure
    km = context.get("key_metrics", {})
    if isinstance(km, dict):
        for metric_name, metric_val in km.items():
            if isinstance(metric_val, dict):
                for req in ("value", "as_of", "source"):
                    if req not in metric_val:
                        errors.append(f"key_metrics.{metric_name} missing '{req}' in provenance structure")

    if errors:
        for e in errors:
            print(f"Validation error: {e}", file=sys.stderr)
        sys.exit(1)

    # Valid — this is a gate (no -o/--pretty); report status to stderr, no stdout.
    print("Valid", file=sys.stderr)


def cmd_update_identity(args: argparse.Namespace) -> None:
    """Update stable identity fields (sector, stage, geography)."""
    artifacts_root: str = args.artifacts_root
    rc, slug = _resolve_slug(artifacts_root, args.slug)
    if rc != 0:
        if slug:
            print(slug, file=sys.stderr)
        sys.exit(rc)

    path = _context_path(artifacts_root, slug)
    if not os.path.isfile(path):
        print(f"Founder context not found: {path}", file=sys.stderr)
        sys.exit(1)

    # Require at least one field
    has_update = any([args.sector, args.stage, args.geography])
    if not has_update:
        print("Error: at least one of --sector, --stage, --geography is required", file=sys.stderr)
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        context: dict[str, Any] = json.load(f)

    if args.sector:
        context["sector"] = args.sector
        # Re-derive sector_type
        if hasattr(args, "sector_type") and args.sector_type:
            context["sector_type"] = args.sector_type
            # Clear any prior sector_type warning now that it's resolved
            context["warnings"] = [w for w in context.get("warnings", []) if w.get("code") != "W_SECTOR_TYPE_UNKNOWN"]
        else:
            derived = _derive_sector_type(args.sector)
            context["sector_type"] = derived
            if derived is None:
                # Replace any prior sector_type warning
                context["warnings"] = [
                    w for w in context.get("warnings", []) if w.get("code") != "W_SECTOR_TYPE_UNKNOWN"
                ]
                context["warnings"].append(
                    {
                        "code": "W_SECTOR_TYPE_UNKNOWN",
                        "message": sector_type_unknown_message(args.sector),
                    }
                )
            else:
                # Resolved — clear prior warning if present
                context["warnings"] = [
                    w for w in context.get("warnings", []) if w.get("code") != "W_SECTOR_TYPE_UNKNOWN"
                ]

    if args.stage:
        context["stage"] = args.stage

    if args.geography:
        context["geography"] = args.geography

    meta = context.setdefault("metadata", {})
    meta["last_updated"] = _now_iso()

    with open(path, "w", encoding="utf-8") as f:
        json.dump(context, f, indent=2)

    output = _format_json(context, args.pretty)
    _write_output(output, args.output)


# --- CLI ---


def _default_artifacts_root() -> str:
    """The artifacts root to use when --artifacts-root is not passed.

    NOT `os.getcwd()/artifacts`. On a Cowork session tree the workspace shell's cwd is the BARE
    SESSION ROOT (cowork-harness >=2.4.0, measured against production 2026-08-27), so that guess
    resolves to `/sessions/<id>/artifacts` -- OUTSIDE `mnt/`, where a write is never delivered and
    nothing reports it. Every SKILL.md passes the flag explicitly, but "the flag is always passed"
    is a property of PROSE the agent paraphrases, which is the whole reason the resolver exists.

    Falls back to the old guess if the sibling import fails, so this stays a standalone script:
    a wrong default is strictly better than an unrunnable one, and on the plain CLI the two agree.
    """
    try:
        shared = os.path.dirname(os.path.abspath(__file__))
        if shared not in sys.path:
            sys.path.insert(0, shared)
        import resolve_artifacts_root  # type: ignore[import-not-found]

        return str(resolve_artifacts_root.resolve_artifacts_root(os.getcwd(), dict(os.environ)))
    except ImportError:
        # NARROW, and LOUD. A bare `except Exception` here swallowed any failure and returned the
        # very path this function exists to avoid -- on a session tree that is
        # `/sessions/<id>/artifacts`, outside `mnt/`, undelivered and unreported. The fallback keeps
        # the script standalone, but it must never be silent.
        sys.stderr.write(
            "warning: could not import resolve_artifacts_root; falling back to $PWD/artifacts. "
            "On a Cowork session tree that is OUTSIDE the outputs mount and nothing written there "
            "is delivered. Pass --artifacts-root explicitly.\n"
        )
        return os.path.join(os.getcwd(), "artifacts")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description="Per-company founder context manager")
    sub = p.add_subparsers(dest="command", required=True)

    # Common arguments added to relevant subcommands
    def _add_common(sp: argparse.ArgumentParser, with_output: bool = True) -> None:
        sp.add_argument(
            "--artifacts-root",
            default=_default_artifacts_root(),
            help="Override artifacts directory (default: the resolved canonical root)",
        )
        if with_output:
            sp.add_argument(
                "--pretty",
                action="store_true",
                help="Pretty-print JSON output",
            )
            sp.add_argument(
                "-o",
                "--output",
                help="Write output to file instead of stdout",
            )

    # init
    sp_init = sub.add_parser("init", help="Create a new founder context")
    sp_init.add_argument("--company-name", required=True, help="Company name")
    sp_init.add_argument("--slug", help="Company slug (auto-generated from name if omitted)")
    sp_init.add_argument(
        "--stage",
        required=True,
        type=_normalize_enum_arg,
        choices=sorted(VALID_STAGES),
        help="Funding stage",
    )
    sp_init.add_argument("--sector", required=True, help="Industry sector")
    sp_init.add_argument("--geography", required=True, help="Geographic region")
    sp_init.add_argument(
        "--sector-type",
        type=_normalize_enum_arg,
        choices=sorted(CANONICAL_SECTOR_TYPES),
        help="Override auto-derived sector type",
    )
    sp_init.add_argument(
        "--run-id",
        help="Override generated run_id (default: ISO timestamp)",
    )
    sp_init.add_argument(
        "--skill",
        default=None,
        help="Required when --run-id has a gate ledger: the skill whose run this is (refused if it is another's)",
    )
    _add_common(sp_init)

    # read
    sp_read = sub.add_parser("read", help="Read existing founder context")
    sp_read.add_argument("--slug", help="Company slug (auto-detects if single file)")
    sp_read.add_argument(
        "--run-id",
        default=None,
        help="With a gate ledger for this run, the read records the Step-1 questions it settles",
    )
    sp_read.add_argument("--skill", default=None, help="Required when --run-id has a gate ledger")
    _add_common(sp_read)

    # merge
    sp_merge = sub.add_parser("merge", help="Merge data into existing founder context")
    sp_merge.add_argument("--slug", help="Company slug (auto-detects if single file)")
    sp_merge.add_argument("--data", required=True, help="JSON string to merge")
    sp_merge.add_argument(
        "--source",
        required=True,
        help="Provenance source (user or skill-name)",
    )
    sp_merge.add_argument(
        "--add-skill-run",
        help="Append skill name to prior_skill_runs list",
    )
    sp_merge.add_argument(
        "--force",
        action="store_true",
        help="Override protected field guards",
    )
    _add_common(sp_merge)

    # validate
    sp_validate = sub.add_parser("validate", help="Validate founder context schema")
    sp_validate.add_argument("--slug", help="Company slug (auto-detects if single file)")
    _add_common(sp_validate, with_output=False)

    # update-identity
    sp_update = sub.add_parser("update-identity", help="Update stable identity fields")
    sp_update.add_argument("--slug", help="Company slug (auto-detects if single file)")
    sp_update.add_argument("--sector", help="New sector value")
    sp_update.add_argument(
        "--stage",
        type=_normalize_enum_arg,
        choices=sorted(VALID_STAGES),
        help="New funding stage",
    )
    sp_update.add_argument("--geography", help="New geographic region")
    sp_update.add_argument(
        "--sector-type",
        type=_normalize_enum_arg,
        choices=sorted(CANONICAL_SECTOR_TYPES),
        help="Override auto-derived sector type",
    )
    _add_common(sp_update)

    return p.parse_args()


def main() -> None:
    """Entry point."""
    args = parse_args()
    if args.command == "init":
        cmd_init(args)
    elif args.command == "read":
        cmd_read(args)
    elif args.command == "merge":
        cmd_merge(args)
    elif args.command == "validate":
        cmd_validate(args)
    elif args.command == "update-identity":
        cmd_update_identity(args)


if __name__ == "__main__":
    main()
