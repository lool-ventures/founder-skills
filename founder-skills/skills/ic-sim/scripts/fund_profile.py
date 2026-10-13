#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Fund profile validator for IC simulation.

Validates fund profile structure: exactly 3 archetypes, valid check_size_range,
at least 1 thesis area, sources required for fund-specific mode, portfolio
array present with name fields.

Partners are role names only, never real people: an archetype carries only `role` and
`focus_areas`, and the profile's keys, portfolio rows and source URLs are closed sets that leave no
place for a person. A refusal never echoes the value it refused.

Always reads JSON from stdin.

Usage:
    echo '{"fund_name": "...", "mode": "generic", ...}' \
        | python fund_profile.py --pretty

Output: JSON with validated profile including validation.status and validation.errors.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from typing import Any, NoReturn
from urllib.parse import unquote, urlsplit


def _write_output(data: str, output_path: str | None, *, summary: dict[str, Any] | None = None) -> None:
    """Write JSON string to file or stdout."""
    if output_path:
        abs_path = os.path.abspath(output_path)
        parent = os.path.dirname(abs_path)
        if parent == "/":
            print(f"Error: output path resolves to root directory: {output_path}", file=sys.stderr)
            sys.exit(1)
        os.makedirs(parent, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(data)
        receipt: dict[str, Any] = {"ok": True, "path": abs_path, "bytes": len(data.encode("utf-8"))}
        if summary:
            receipt.update(summary)
        sys.stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
    else:
        sys.stdout.write(data)


def _fail_invalid(result: dict[str, Any], output_path: str | None, indent: int | None) -> NoReturn:
    """Emit a validation-error result and exit NON-ZERO, without touching `output_path`.

    The error JSON still goes to STDOUT so the caller can read the diagnostic; only the exit
    code and stderr are new. It is deliberately NOT written to `--output`: that path is the
    canonical fund profile, and overwriting it with a rejected stub would destroy the earlier
    good one and read as truth downstream. Exit 1 makes SKILL.md's "the pipe fails next" branch
    reachable.
    """
    errors = result.get("validation", {}).get("errors") or ["unspecified validation error"]
    if any(str(e).split(":", 1)[0] in PEOPLE_CODES for e in errors):
        # The refused value may be a person: the diagnostic names where it was, never what it was.
        result = dict(result)
        for key in list(result):
            if key in WITHHELD_ON_PEOPLE or key not in FUND_KEYS:
                result[key] = WITHHELD
    sys.stdout.write(json.dumps(result, indent=indent) + "\n")
    print(f"Error: input rejected, no output written: {'; '.join(str(e) for e in errors)}", file=sys.stderr)
    if output_path:
        print(f"Error: {os.path.abspath(output_path)} was left unchanged.", file=sys.stderr)
    sys.exit(1)


VALID_ROLES = {"visionary", "operator", "analyst"}
VALID_MODES = {"generic", "fund_specific"}

# The three partners are always these role names. compose_report.py renders the Fund Profile's partner
# labels from this table (never from the file), and the skill's text uses the same three strings.
ROLE_LABELS = {"visionary": "The Visionary", "operator": "The Operator", "analyst": "The Analyst"}

# Closed key sets. An allowlist is the only deterministic way to keep a person's name or bio out of the
# structured fields; a list of forbidden key names is not. `name` on an archetype is tolerated only as the
# exact role label (an older example carried it) and is never written.
FUND_KEYS = frozenset(
    {
        "fund_name",
        "mode",
        "thesis_areas",
        "check_size_range",
        "stage_focus",
        "archetypes",
        "portfolio",
        "sources",
        "accepted_warnings",
        "metadata",
        "validation",
    }
)
ARCHETYPE_KEYS = frozenset({"role", "focus_areas"})
PORTFOLIO_KEYS = frozenset({"name", "sector", "status"})

PEOPLE_CODES = frozenset(
    {
        "PARTNER_NAME_NOT_ROLE",
        "ARCHETYPE_FIELD_NOT_ALLOWED",
        "FUND_FIELD_NOT_ALLOWED",
        "PORTFOLIO_FIELD_NOT_ALLOWED",
        "SOURCE_IS_A_PERSON",
    }
)
# On a people refusal the diagnostic withholds these and every key outside FUND_KEYS (a refused `team` list).
WITHHELD_ON_PEOPLE = ("archetypes", "portfolio", "sources")
WITHHELD = "<withheld: refused>"

# A URL whose path is a person's page by construction: (host suffix, first path segment). LinkedIn's `/pub/`
# is its older public-profile path (`/pub/dir/...`, a people-search listing, is a person search too), and its
# mobile-lite pages put the same path behind `/mwlite/`.
_PERSON_PAGES = (("linkedin.com", "in"), ("linkedin.com", "pub"), ("crunchbase.com", "person"))
_PATH_PREFIXES = {"linkedin.com": ("mwlite",)}


def _host_matches(host: str, suffix: str) -> bool:
    return host == suffix or host.endswith("." + suffix)


def _is_person_page(url: Any) -> bool:
    """True for a LinkedIn `/in/...` or `/pub/...` URL (also behind `/mwlite/`) or a Crunchbase `/person/...`
    URL, on any subdomain and in any case, with the path percent-decoded and a single-slash scheme
    (`https:/host/...`) read as the host it names."""
    if not isinstance(url, str) or not url.strip():
        return False
    text = url.strip()
    scheme, sep, rest = text.partition(":")
    if sep and scheme.casefold() in ("http", "https") and not rest.startswith("//"):
        text = scheme + "://" + rest.lstrip("/")
    elif "//" not in text:
        text = "//" + text
    try:
        parts = urlsplit(text)
        host = (parts.hostname or "").casefold().rstrip(".")
    except ValueError:
        return False
    segments = [seg for seg in unquote(parts.path).casefold().split("/") if seg]
    for suffix, prefixes in _PATH_PREFIXES.items():
        if _host_matches(host, suffix) and segments and segments[0] in prefixes:
            segments = segments[1:]
    first = segments[0] if segments else ""
    return any(_host_matches(host, suffix) and first == seg for suffix, seg in _PERSON_PAGES)


def _role_text(role: Any) -> str:
    return role if isinstance(role, str) and role in VALID_ROLES else "unknown role"


def people_problems(profile: dict[str, Any]) -> list[str]:
    """Where an already-written fund profile leaves a place for a person, one entry per field, naming where
    and never the value. compose_report.py and visualize.py refuse such a profile: it was written before
    partners became role names, or around this producer. The rules are the producer's own, so a profile it
    wrote can never be listed: a `name` that is not the role label, any other archetype key outside
    `ARCHETYPE_KEYS`, any top-level key outside `FUND_KEYS`, any portfolio key outside `PORTFOLIO_KEYS`, and a
    source that is a person's page. The one exemption: a generic profile's `background`, which an older
    example invented and which names no one (it is never rendered)."""
    problems: list[str] = []
    fund_specific = profile.get("mode") == "fund_specific"
    for key in sorted(str(k) for k in profile if k not in FUND_KEYS):
        problems.append(f'field "{key}"')
    archetypes = profile.get("archetypes")
    for i, arch in enumerate(archetypes if isinstance(archetypes, list) else []):
        if not isinstance(arch, dict):
            continue
        role = arch.get("role")
        label = ROLE_LABELS.get(role) if isinstance(role, str) else None
        if "name" in arch and (label is None or arch.get("name") != label):
            problems.append(f"archetype {i} ({_role_text(role)}): name")
        for key in sorted(str(k) for k in arch if k not in ARCHETYPE_KEYS and k != "name"):
            if key == "background" and not fund_specific:
                continue
            problems.append(f'archetype {i} ({_role_text(role)}): field "{key}"')
    portfolio = profile.get("portfolio")
    for i, entry in enumerate(portfolio if isinstance(portfolio, list) else []):
        if isinstance(entry, dict):
            for key in sorted(str(k) for k in entry if k not in PORTFOLIO_KEYS):
                problems.append(f'portfolio entry {i}: field "{key}"')
    sources = profile.get("sources")
    for i, source in enumerate(sources if isinstance(sources, list) else []):
        if isinstance(source, dict) and _is_person_page(source.get("url")):
            problems.append(f"source {i}: a person's page")
    return problems


NAMES_PEOPLE_FIX = (
    "rebuild the fund profile (Step 4) and run Steps 5-8 again under the same run id, then compose; tell the "
    "founder only that the fund profile is being rebuilt"
)
# The page has no run gate, so it is the one caller that also runs on a finished simulation, which no step can
# rebuild.
FINISHED_FIX = "on a finished simulation this needs a new simulation (Step 0)"


def refuse_profile_naming_people(sim_dir: str, *, by: str) -> None:
    """Exit 1 `FUND_PROFILE_NAMES_PEOPLE`, nothing written, when the dir's fund_profile.json names people
    (`people_problems`). The partner discussion in the dir was written by sub-agents that saw those names, so
    relabelling the Fund Profile section would not reach it. A missing or unreadable profile is left to the
    caller's own handling."""
    try:
        with open(os.path.join(sim_dir, "fund_profile.json"), encoding="utf-8") as f:
            profile = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(profile, dict):
        return
    problems = people_problems(profile)
    if not problems:
        return
    message = (
        f"fund_profile.json has a place for a person, which a profile built by this version never has "
        f"({'; '.join(problems)}); {NAMES_PEOPLE_FIX}"
    )
    if by == "visualize.py":
        message += f"; {FINISHED_FIX}"
    sys.stdout.write(json.dumps({"status": "rejected", "code": "FUND_PROFILE_NAMES_PEOPLE", "message": message}) + "\n")
    print(f"Error: {by}: FUND_PROFILE_NAMES_PEOPLE: {message}; nothing was written", file=sys.stderr)
    sys.exit(1)


# --- what each later artifact was built from -------------------------------------------------------------
# run_id parity cannot see a fund profile rebuilt WITHIN a run (the remedy for FUND_PROFILE_NAMES_PEOPLE is
# exactly that): every file keeps the run's id. So the producers that consume the profile -- detect_conflicts.py,
# compose_discussion.py, score_dimensions.py -- record the fingerprint of the fund_profile.json beside their
# output when they run, and compose compares it with the profile as it stands now (the financial-model-review
# `graded_against` pattern). Comparing the artifacts with each other would not do: they can agree while all
# are stale.

GRADED_AGAINST = "graded_against"
# Not part of what a later step was built from: the run stamp, the producer's own verdict, and the warnings
# the founder accepted at compose time (adding one must not make every earlier step stale).
FINGERPRINT_EXCLUDED = frozenset({"metadata", "validation", "accepted_warnings"})
# The six partner files are written by persist_partner.py (Steps 6 and 6b), the other three by their producers.
PARTNER_FILES = tuple(
    f"partner_{kind}_{archetype}.json"
    for kind in ("assessment", "rebuttal")
    for archetype in ("visionary", "operator", "analyst")
)
PROFILE_DEPENDENTS = (*PARTNER_FILES, "conflict_check.json", "discussion.json", "score_dimensions.json")
STALE_FIX = "run Steps 5-8 again under the same run id, then compose"


def profile_fingerprint(profile: Any) -> str:
    """Order-insensitive sha256 of a fund profile, without the keys in FINGERPRINT_EXCLUDED."""
    material = profile
    if isinstance(profile, dict):
        material = {k: v for k, v in profile.items() if k not in FINGERPRINT_EXCLUDED}
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def profile_fingerprint_in(sim_dir: str) -> str | None:
    """The fingerprint of `<sim_dir>/fund_profile.json` as it is on disk; None when missing or unreadable,
    which no comparison treats as a match."""
    try:
        with open(os.path.join(sim_dir, "fund_profile.json"), encoding="utf-8") as f:
            return profile_fingerprint(json.load(f))
    except (OSError, ValueError):
        return None


def stamp_profile(result: dict[str, Any], output_path: str | None, source_sha256: str | None = None) -> None:
    """Record, on a producer's output, the fingerprint of the fund profile beside where it is written, and (for a
    step fed by a sub-agent's hand-off) the sha256 of the hand-off bytes it consumed. With no `-o` nothing is
    stamped (stdout output is never composed). Overrides any `graded_against` in the input."""
    if not output_path:
        return
    stamp: dict[str, Any] = {"fund_profile": profile_fingerprint_in(os.path.dirname(os.path.abspath(output_path)))}
    if source_sha256 is not None:
        stamp["source_sha256"] = source_sha256
    result[GRADED_AGAINST] = stamp


def bytes_sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def refuse_handoff_not_redispatched(output_path: str | None, source_sha256: str, *, by: str) -> None:
    """Exit 1 `HANDOFF_NOT_REDISPATCHED`, `-o` untouched, when the hand-off about to be persisted is byte for byte
    the one the existing `-o` was built from, and that file was built against an earlier fund profile. Re-piping
    the old hand-off would re-stamp prose a sub-agent wrote against the old profile, which no stamp could then
    tell apart: the remedy is a new dispatch. A repair under the same profile is never refused (its stamp is
    current), and a missing or unreadable `-o`, or one with no recorded hand-off, is never refused either: the
    check must not block a repair. Residuals: a one-byte edit of the old hand-off, or deleting `-o` first, passes;
    both are outside the never-re-type and never-delete rules."""
    if not output_path:
        return
    try:
        with open(os.path.abspath(output_path), encoding="utf-8") as f:
            existing = json.load(f)
    except (OSError, ValueError):
        return
    stamp = existing.get(GRADED_AGAINST) if isinstance(existing, dict) else None
    if not isinstance(stamp, dict) or stamp.get("source_sha256") != source_sha256:
        return
    if stamp.get("fund_profile") == profile_fingerprint_in(os.path.dirname(os.path.abspath(output_path))):
        return
    name = os.path.basename(output_path)
    message = (
        f"{name} was built from this same hand-off against an earlier fund profile; re-dispatch the sub-agent for "
        "this step (a new round under the current profile, not a corrective dispatch), then persist its new hand-off"
    )
    sys.stdout.write(json.dumps({"status": "rejected", "code": "HANDOFF_NOT_REDISPATCHED", "message": message}) + "\n")
    print(
        f"Error: {by}: HANDOFF_NOT_REDISPATCHED: {message}; {os.path.abspath(output_path)} was left unchanged",
        file=sys.stderr,
    )
    sys.exit(1)


def stale_dependents(sim_dir: str, names: tuple[str, ...] = PROFILE_DEPENDENTS) -> list[str]:
    """The artifacts in `names` built from a fund profile other than the current one. A missing
    stamp counts as stale, in every mode: a file written before the stamp existed, or by hand, cannot show what
    it was built from (a pre-stamp run resumed under this version redoes Steps 5-8 once). A missing or
    unreadable fund_profile.json, or a missing dependent, is not judged here: compose reports those as missing
    artifacts."""
    current = profile_fingerprint_in(sim_dir)
    if current is None:
        return []
    stale: list[str] = []
    for name in names:
        try:
            with open(os.path.join(sim_dir, name), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        stamp = data.get(GRADED_AGAINST)
        if not isinstance(stamp, dict) or stamp.get("fund_profile") != current:
            stale.append(name)
    return stale


def refuse_stale_dependents(sim_dir: str, *, by: str, names: tuple[str, ...] = PROFILE_DEPENDENTS) -> None:
    """Exit 1 `PARTNER_ARTIFACTS_STALE`, nothing written, when an artifact the report is built from was made
    against another fund profile than the current one (`stale_dependents`)."""
    stale = stale_dependents(sim_dir, names)
    if not stale:
        return
    message = (
        f"{', '.join(stale)} {'was' if len(stale) == 1 else 'were'} not built from the current fund_profile.json "
        f"(the profile changed after they ran, they ran where no readable profile was, or they carry no record of "
        f"it); {STALE_FIX}"
    )
    sys.stdout.write(json.dumps({"status": "rejected", "code": "PARTNER_ARTIFACTS_STALE", "message": message}) + "\n")
    print(f"Error: {by}: PARTNER_ARTIFACTS_STALE: {message}; nothing was written", file=sys.stderr)
    sys.exit(1)


def validate_fund_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Validate fund profile and return enriched profile with validation results."""
    errors: list[str] = []

    # Required top-level fields. `portfolio` is NOT unconditionally required —
    # see below: it's only required for fund_specific mode.
    for field in ["fund_name", "mode", "thesis_areas", "check_size_range", "stage_focus", "archetypes"]:
        if field not in profile:
            errors.append(f"Missing required field: {field}")

    # Mode validation
    mode = profile.get("mode", "")
    if mode not in VALID_MODES:
        errors.append(f"Invalid mode '{mode}'. Must be one of: {sorted(VALID_MODES)}")

    # Portfolio is required for fund_specific mode (a real fund's actual
    # holdings). It is OPTIONAL in generic mode: a synthesized/illustrative
    # fund has no real holdings, and forcing this field manufactures a
    # fabricated portfolio — and with it, fabricated conflicts that can
    # override the merits-based verdict (see score_dimensions.py's
    # fund-mode-aware dealbreaker handling).
    if mode == "fund_specific" and "portfolio" not in profile:
        errors.append("Missing required field: portfolio (required for fund_specific mode)")

    # Thesis areas: at least 1
    thesis = profile.get("thesis_areas", [])
    if not isinstance(thesis, list):
        errors.append("thesis_areas must be an array")
    elif len(thesis) < 1:
        errors.append("thesis_areas must contain at least 1 area")

    # Stage focus: must be non-empty list
    stage_focus = profile.get("stage_focus", [])
    if not isinstance(stage_focus, list) or len(stage_focus) < 1:
        errors.append("stage_focus must be a non-empty array")

    # Check size range validation
    check_size = profile.get("check_size_range", {})
    if isinstance(check_size, dict):
        min_size = check_size.get("min")
        max_size = check_size.get("max")
        if min_size is not None and max_size is not None:
            try:
                min_val = float(min_size)
                max_val = float(max_size)
                if min_val < 0:
                    errors.append(f"check_size_range.min must be non-negative, got {min_val}")
                if max_val < 0:
                    errors.append(f"check_size_range.max must be non-negative, got {max_val}")
                if min_val > max_val:
                    errors.append(f"check_size_range.min ({min_val}) must be <= max ({max_val})")
            except (TypeError, ValueError):
                errors.append("check_size_range.min and max must be numbers")
        else:
            if min_size is None:
                errors.append("check_size_range missing 'min' field")
            if max_size is None:
                errors.append("check_size_range missing 'max' field")
    else:
        errors.append(f"check_size_range must be an object (got {type(check_size).__name__})")

    # Archetypes: exactly 3, each with valid role
    archetypes = profile.get("archetypes", [])
    if not isinstance(archetypes, list):
        errors.append("archetypes must be an array")
    else:
        if len(archetypes) != 3:
            errors.append(f"Must have exactly 3 archetypes, got {len(archetypes)}")
        roles_seen: set[str] = set()
        for i, arch in enumerate(archetypes):
            if not isinstance(arch, dict):
                errors.append(f"Archetype {i} must be an object")
                continue
            role = arch.get("role", "")
            if role not in VALID_ROLES:
                errors.append(f"Archetype {i}: invalid role '{role}'. Must be one of: {sorted(VALID_ROLES)}")
            elif role in roles_seen:
                errors.append(f"Archetype {i}: duplicate role '{role}'")
            else:
                roles_seen.add(role)
            if "name" in arch:
                label = ROLE_LABELS.get(role) if isinstance(role, str) else None
                if label is None or arch.get("name") != label:
                    errors.append(
                        f"PARTNER_NAME_NOT_ROLE: archetype {i} ({_role_text(role)}): name is not the role label; "
                        'partners are role names only, do not record a person. Remove "name".'
                    )
            for key in sorted(str(k) for k in arch if k not in ARCHETYPE_KEYS and k != "name"):
                errors.append(
                    f'ARCHETYPE_FIELD_NOT_ALLOWED: archetype {i} ({_role_text(role)}): field "{key}" is not '
                    "allowed; an archetype carries only role and focus_areas."
                )
            if not isinstance(arch.get("focus_areas"), list) or not arch.get("focus_areas"):
                errors.append(f"Archetype {i}: 'focus_areas' must be a non-empty array")

    # Portfolio: must be array, each entry must have 'name'
    portfolio = profile.get("portfolio", [])
    if not isinstance(portfolio, list):
        errors.append("portfolio must be an array")
    else:
        for i, entry in enumerate(portfolio):
            if not isinstance(entry, dict):
                errors.append(f"Portfolio entry {i} must be an object")
            else:
                if not entry.get("name"):
                    errors.append(f"Portfolio entry {i}: missing 'name' field")
                for key in sorted(str(k) for k in entry if k not in PORTFOLIO_KEYS):
                    errors.append(
                        f'PORTFOLIO_FIELD_NOT_ALLOWED: portfolio entry {i}: field "{key}" is not allowed; '
                        "a portfolio entry carries only name, sector and status."
                    )

    # Sources required for fund-specific mode
    if mode == "fund_specific":
        sources = profile.get("sources", [])
        if not isinstance(sources, list) or len(sources) == 0:
            errors.append("sources required for fund_specific mode (at least 1)")
        elif isinstance(sources, list):
            for i, source in enumerate(sources):
                if not isinstance(source, dict):
                    errors.append(f"Source {i} must be an object")
                elif not source.get("url") and not source.get("title"):
                    errors.append(f"Source {i} must have at least 'url' or 'title'")

    # Every mode: a source that is a person's page carries that person's name into every sub-agent prompt.
    all_sources = profile.get("sources")
    if isinstance(all_sources, list):
        for i, source in enumerate(all_sources):
            if isinstance(source, dict) and _is_person_page(source.get("url")):
                errors.append(
                    f"SOURCE_IS_A_PERSON: source {i}: the url is a person's profile page; research the fund, "
                    "never its people, and cite the fund's own pages instead."
                )

    # The fund-level keys are a closed set: a `partners` or `team` list has no place in the profile.
    for key in sorted(str(k) for k in profile if k not in FUND_KEYS):
        errors.append(
            f'FUND_FIELD_NOT_ALLOWED: field "{key}" is not allowed in a fund profile; it carries only '
            f"{', '.join(sorted(FUND_KEYS - {'metadata', 'validation'}))}."
        )

    status = "valid" if not errors else "invalid"

    result = dict(profile)
    if "archetypes" in profile and isinstance(archetypes, list):
        # A tolerated role-label `name` is not written. New dicts, so the caller's input is untouched.
        result["archetypes"] = [
            {k: v for k, v in arch.items() if k != "name"} if isinstance(arch, dict) else arch for arch in archetypes
        ]
    result["validation"] = {"status": status, "errors": errors}
    return result


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fund profile validator (reads JSON from stdin)")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    p.add_argument("--run-id", required=True, help="Run identifier injected into metadata.run_id")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    # In a folder that belongs to a run: only that folder's current run (fund_profile opens the run's ledger).
    import _run_ref

    _run_ref.refuse_not_this_runs(
        os.path.dirname(os.path.abspath(args.output)) if args.output else None, args.run_id, noun="simulation dir"
    )

    if sys.stdin.isatty():
        print("Error: pipe JSON input via stdin", file=sys.stderr)
        print(
            'Example: echo \'{"fund_name": "...", ...}\' | python fund_profile.py --pretty',
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, dict):
        print("Error: JSON must be an object", file=sys.stderr)
        sys.exit(1)

    # THE RUN'S GATE LEDGER, when the profile is written into a run's dir: the mode and fund questions are
    # recorded before the profile is built, and the profile is the fund the founder chose. With no
    # `run_ref.json` none of this runs.
    if args.output:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import _ic_gates

        run_dir = os.path.dirname(os.path.abspath(args.output))
        ledger = _ic_gates.require_or_exit(
            run_dir, args.run_id, [_ic_gates.MODE_GATE, _ic_gates.FUND_GATE], by="fund_profile.py"
        )
        if ledger is not None:
            _ic_gates.fund_choice_or_exit(ledger, data.get("mode"))

    result = validate_fund_profile(data)

    # Inject metadata.run_id as the last step before serialization (overrides any stdin metadata).
    result["metadata"] = {"run_id": args.run_id}

    indent = 2 if args.pretty else None
    if result["validation"]["status"] != "valid":
        _fail_invalid(result, args.output, indent)
    out = json.dumps(result, indent=indent) + "\n"
    _write_output(
        out,
        args.output,
        summary={"validation": result["validation"]["status"]},
    )


if __name__ == "__main__":
    main()
