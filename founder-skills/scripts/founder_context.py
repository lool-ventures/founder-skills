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
from typing import Any

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

VALID_STAGES = {"pre-seed", "seed", "series-a", "series-b", "later"}

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
    valid_list = sorted(CANONICAL_SECTOR_TYPES)
    print(
        f"Warning: could not derive sector_type from '{sector}'; "
        f"valid sector_type values: {valid_list}. "
        f"Set explicitly with --sector-type.",
        file=sys.stderr,
    )
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


def cmd_init(args: argparse.Namespace) -> None:
    """Create a new founder context file."""
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
            valid_list = sorted(CANONICAL_SECTOR_TYPES)
            context.setdefault("warnings", []).append(
                {
                    "code": "W_SECTOR_TYPE_UNKNOWN",
                    "message": (
                        f"could not derive sector_type from '{args.sector}'. "
                        f"Valid sector_type values: {valid_list}. "
                        f"Re-run with --sector-type to set explicitly."
                    ),
                }
            )

    path = _context_path(artifacts_root, slug)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(context, f, indent=2)

    output = _format_json(context, args.pretty)
    _write_output(output, args.output)


def cmd_read(args: argparse.Namespace) -> None:
    """Read and output an existing founder context file."""
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
        context = json.load(f)

    output = _format_json(context, args.pretty)
    _write_output(output, args.output)


def cmd_merge(args: argparse.Namespace) -> None:
    """Merge data into an existing founder context file."""
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
                valid_list = sorted(CANONICAL_SECTOR_TYPES)
                # Replace any prior sector_type warning
                context["warnings"] = [
                    w for w in context.get("warnings", []) if w.get("code") != "W_SECTOR_TYPE_UNKNOWN"
                ]
                context["warnings"].append(
                    {
                        "code": "W_SECTOR_TYPE_UNKNOWN",
                        "message": (
                            f"could not derive sector_type from '{args.sector}'. "
                            f"Valid sector_type values: {valid_list}. "
                            f"Re-run with --sector-type to set explicitly."
                        ),
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


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description="Per-company founder context manager")
    sub = p.add_subparsers(dest="command", required=True)

    # Common arguments added to relevant subcommands
    def _add_common(sp: argparse.ArgumentParser, with_output: bool = True) -> None:
        sp.add_argument(
            "--artifacts-root",
            default=os.path.join(os.getcwd(), "artifacts"),
            help="Override artifacts directory (default: ./artifacts)",
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
        choices=sorted(VALID_STAGES),
        help="Funding stage",
    )
    sp_init.add_argument("--sector", required=True, help="Industry sector")
    sp_init.add_argument("--geography", required=True, help="Geographic region")
    sp_init.add_argument(
        "--sector-type",
        choices=sorted(CANONICAL_SECTOR_TYPES),
        help="Override auto-derived sector type",
    )
    sp_init.add_argument(
        "--run-id",
        help="Override generated run_id (default: ISO timestamp)",
    )
    _add_common(sp_init)

    # read
    sp_read = sub.add_parser("read", help="Read existing founder context")
    sp_read.add_argument("--slug", help="Company slug (auto-detects if single file)")
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
        choices=sorted(VALID_STAGES),
        help="New funding stage",
    )
    sp_update.add_argument("--geography", help="New geographic region")
    sp_update.add_argument(
        "--sector-type",
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
