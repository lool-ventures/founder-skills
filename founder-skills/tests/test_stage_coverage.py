#!/usr/bin/env python3
"""T1: every value the shared stage enum admits must RESOLVE at every site
that keys on stage — directly, through an explicitly declared fallback, or
through an explicitly declared out-of-scope disposition.

The authority is ``founder_context.VALID_STAGES``. Skill scripts are
standalone (PEP 723; no cross-skill imports), so each skill that needs the
ladder mirrors it locally rather than importing the authority — the risk this
file guards against is that local mirror going stale or a hand-written
membership set quietly omitting a stage nobody thought about. A stage that
falls through such a gap gets no founder-visible signal at all: not a wrong
answer, not a disclosed substitution, just silence.

Three dispositions count as compliant for a given site:

1. Resolves directly — the value is a key/member.
2. Declared fallback — resolves to another stage AND the substitution is
   disclosed in the artifact (a stderr-only warning does not count).
3. Declared out-of-scope — the skill deliberately scopes narrower and says so
   through a founder-visible signal (a low/medium-severity warning the
   founder actually reads, not a silent drop).

Each test below states which disposition the site it covers relies on.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import sys
import types
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(SCRIPT_DIR)
SHARED_SCRIPTS_DIR = os.path.join(PLUGIN_ROOT, "scripts")
FMR_DIR = os.path.join(PLUGIN_ROOT, "skills", "financial-model-review", "scripts")
DECK_REVIEW_DIR = os.path.join(PLUGIN_ROOT, "skills", "deck-review", "scripts")
IC_SIM_DIR = os.path.join(PLUGIN_ROOT, "skills", "ic-sim", "scripts")
CP_DIR = os.path.join(PLUGIN_ROOT, "skills", "competitive-positioning", "scripts")

REVIEW_INPUTS_PATH = os.path.join(FMR_DIR, "review_inputs.py")


# ---------------------------------------------------------------------------
# Module loading — these are standalone PEP 723 scripts, not a package, so
# `import` doesn't reach them. Two (stage_profile.py, deck-review's
# compose_report.py) do a bare sibling import of `_artifact_writer` /
# `_schema_validator`, which only resolves if their own directory is already
# on sys.path before exec_module runs.
# ---------------------------------------------------------------------------


def _read_source(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _load_module(path: str, name: str, extra_syspath: str | None = None) -> types.ModuleType:
    if extra_syspath and extra_syspath not in sys.path:
        sys.path.insert(0, extra_syspath)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load spec for {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _require_attr(mod: types.ModuleType, symbol: str, site_id: str) -> Any:
    """Fetch a module attribute, failing loudly rather than silently if it's gone.

    A renamed or deleted symbol must break this suite — a registry entry that
    quietly stops checking anything is exactly the failure mode T1 exists to
    catch, so this raises instead of returning None / skipping.
    """
    if not hasattr(mod, symbol):
        raise AttributeError(
            f"registry entry {site_id!r} names symbol {symbol!r}, which {mod.__file__} no longer defines"
        )
    return getattr(mod, symbol)


FOUNDER_CONTEXT = _load_module(os.path.join(SHARED_SCRIPTS_DIR, "founder_context.py"), "t1_founder_context")
FMR_VALIDATE_INPUTS = _load_module(os.path.join(FMR_DIR, "validate_inputs.py"), "t1_fmr_validate_inputs")
FMR_UNIT_ECONOMICS = _load_module(os.path.join(FMR_DIR, "unit_economics.py"), "t1_fmr_unit_economics")
FMR_VALIDATE_EXTRACTION = _load_module(os.path.join(FMR_DIR, "validate_extraction.py"), "t1_fmr_validate_extraction")
FMR_CHECKLIST = _load_module(os.path.join(FMR_DIR, "checklist.py"), "t1_fmr_checklist")
CP_COMPOSE_REPORT = _load_module(os.path.join(CP_DIR, "compose_report.py"), "t1_cp_compose_report")
DECK_REVIEW_STAGE_PROFILE = _load_module(
    os.path.join(DECK_REVIEW_DIR, "stage_profile.py"), "t1_deckreview_stage_profile", extra_syspath=DECK_REVIEW_DIR
)
DECK_REVIEW_COMPOSE_REPORT = _load_module(
    os.path.join(DECK_REVIEW_DIR, "compose_report.py"), "t1_deckreview_compose_report", extra_syspath=DECK_REVIEW_DIR
)
IC_SIM_COMPOSE_REPORT = _load_module(os.path.join(IC_SIM_DIR, "compose_report.py"), "t1_icsim_compose_report")


# Authority. Never hardcode this set elsewhere in this file — every other
# assertion imports it fresh, so prose/code desync (an unlisted 8th stage)
# surfaces as a test failure here, not a silent gap.
VALID_STAGES: frozenset[str] = frozenset(_require_attr(FOUNDER_CONTEXT, "VALID_STAGES", "founder_context.VALID_STAGES"))
VALID_STAGES_UNDERSCORE: frozenset[str] = frozenset(s.replace("-", "_") for s in VALID_STAGES)


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Site:
    site_id: str
    kind: str  # authority | semantic_gate | lookup_table | ui_enum | display_map
    access: str  # import | ast | text
    resolve: Callable[[], Any]


def _find_enum_fields_stage_value_node(source: str, function_name: str = "_validate_structural") -> ast.expr:
    """``_ENUM_FIELDS`` is local to a function body — invisible to `import`/
    `getattr` and to a naive top-level AST walk. Parse the function, find the
    dict literal, and return the AST node bound to its "stage" key."""
    tree = ast.parse(source)
    func = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == function_name), None)
    if func is None:
        raise LookupError(f"function {function_name!r} not found")
    enum_fields_dict: ast.expr | None = None
    for node in ast.walk(func):
        target_value: tuple[ast.Name, ast.expr] | None = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_value = (node.target, node.value) if node.value is not None else None
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target_value = (node.targets[0], node.value)
        if target_value is not None and target_value[0].id == "_ENUM_FIELDS":
            enum_fields_dict = target_value[1]
            break
    if enum_fields_dict is None or not isinstance(enum_fields_dict, ast.Dict):
        raise LookupError("_ENUM_FIELDS dict literal not found")
    for key, value in zip(enum_fields_dict.keys, enum_fields_dict.values, strict=True):
        if isinstance(key, ast.Constant) and key.value == "stage":
            return value
    raise LookupError('"stage" key not found in _ENUM_FIELDS')


def _extract_js_string_array(source: str, marker: str) -> list[str]:
    """Extract a JS array-of-string-literals immediately following `marker`."""
    idx = source.index(marker)
    start = source.index("[", idx)
    end = source.index("]", start)
    return re.findall(r'"([^"]*)"', source[start + 1 : end])


REGISTRY: list[Site] = [
    Site(
        "founder_context.VALID_STAGES",
        "authority",
        "import",
        lambda: _require_attr(FOUNDER_CONTEXT, "VALID_STAGES", "founder_context.VALID_STAGES"),
    ),
    Site(
        "fmr.validate_inputs._STAGE_LADDER",
        "authority",
        "import",
        lambda: _require_attr(FMR_VALIDATE_INPUTS, "_STAGE_LADDER", "fmr.validate_inputs._STAGE_LADDER"),
    ),
    Site(
        "fmr.validate_inputs._SEED_PLUS",
        "semantic_gate",
        "import",
        lambda: _require_attr(FMR_VALIDATE_INPUTS, "_SEED_PLUS", "fmr.validate_inputs._SEED_PLUS"),
    ),
    Site(
        "fmr.validate_inputs._SERIES_A_PLUS",
        "semantic_gate",
        "import",
        lambda: _require_attr(FMR_VALIDATE_INPUTS, "_SERIES_A_PLUS", "fmr.validate_inputs._SERIES_A_PLUS"),
    ),
    Site(
        "fmr.validate_inputs._ENUM_FIELDS[stage]",
        "ui_enum",
        "ast",
        lambda: _find_enum_fields_stage_value_node(_read_source(os.path.join(FMR_DIR, "validate_inputs.py"))),
    ),
    Site(
        "fmr.unit_economics.STAGE_BENCHMARKS",
        "lookup_table",
        "import",
        lambda: (
            _require_attr(FMR_UNIT_ECONOMICS, "STAGE_BENCHMARKS", "fmr.unit_economics.STAGE_BENCHMARKS"),
            _require_attr(
                FMR_UNIT_ECONOMICS, "_resolve_stage_benchmarks", "fmr.unit_economics._resolve_stage_benchmarks"
            ),
        ),
    ),
    Site(
        "fmr.validate_extraction._STAGE_RANGES",
        "lookup_table",
        "import",
        lambda: (
            _require_attr(FMR_VALIDATE_EXTRACTION, "_STAGE_RANGES", "fmr.validate_extraction._STAGE_RANGES"),
            _require_attr(
                FMR_VALIDATE_EXTRACTION, "_resolve_stage_ranges", "fmr.validate_extraction._resolve_stage_ranges"
            ),
        ),
    ),
    Site(
        "fmr.checklist._SEED_PLUS_STAGES",
        "semantic_gate",
        "import",
        lambda: _require_attr(FMR_CHECKLIST, "_SEED_PLUS_STAGES", "fmr.checklist._SEED_PLUS_STAGES"),
    ),
    Site(
        "fmr.review_inputs company.stage dropdown",
        "ui_enum",
        "text",
        lambda: _extract_js_string_array(_read_source(REVIEW_INPUTS_PATH), 'createDropdown("company.stage"'),
    ),
    Site(
        "competitive_positioning.compose_report._humanize",
        "display_map",
        "import",
        lambda: _require_attr(CP_COMPOSE_REPORT, "_humanize", "competitive_positioning.compose_report._humanize"),
    ),
    Site(
        "deck_review.stage_profile._STAGE_TABLE",
        "ui_enum",
        "import",
        lambda: _require_attr(DECK_REVIEW_STAGE_PROFILE, "_STAGE_TABLE", "deck_review.stage_profile._STAGE_TABLE"),
    ),
    Site(
        "deck_review.compose_report.KNOWN_STAGES",
        "semantic_gate",
        "import",
        lambda: _require_attr(DECK_REVIEW_COMPOSE_REPORT, "KNOWN_STAGES", "deck_review.compose_report.KNOWN_STAGES"),
    ),
    Site(
        "deck_review.compose_report.RECOGNIZED_STAGE_TOKENS",
        "semantic_gate",
        "import",
        lambda: _require_attr(
            DECK_REVIEW_COMPOSE_REPORT, "RECOGNIZED_STAGE_TOKENS", "deck_review.compose_report.RECOGNIZED_STAGE_TOKENS"
        ),
    ),
    Site(
        "ic_sim.compose_report.KNOWN_STAGES",
        "semantic_gate",
        "import",
        lambda: _require_attr(IC_SIM_COMPOSE_REPORT, "KNOWN_STAGES", "ic_sim.compose_report.KNOWN_STAGES"),
    ),
]


def test_every_registered_site_resolves() -> None:
    """Every registry entry must resolve to something without raising. The
    deep per-kind tests below check WHAT it resolves to; this only confirms
    the registry's own bookkeeping (module path, symbol name) is accurate —
    the adversarial control below proves that when it isn't, this fails."""
    for site in REGISTRY:
        site.resolve()


def test_a_stale_registry_entry_fails_loudly_not_silently() -> None:
    """Adversarial control: a deliberately wrong entry (a renamed symbol) must
    raise. This is the failure mode the whole contract exists to prevent — a
    renamed symbol silently disabling a check — so the registry mechanism
    itself must not be able to absorb it quietly."""
    bad_site = Site(
        "adversarial-probe",
        "semantic_gate",
        "import",
        lambda: _require_attr(FMR_VALIDATE_INPUTS, "_SEED_PLUS_RENAMED_TYPO_DOES_NOT_EXIST", "adversarial-probe"),
    )
    with pytest.raises(AttributeError, match="adversarial-probe"):
        bad_site.resolve()


# ---------------------------------------------------------------------------
# Authority
# ---------------------------------------------------------------------------


def test_authority_stages_are_lowercase_hyphenated_strings() -> None:
    assert VALID_STAGES, "authority must not be empty"
    for s in VALID_STAGES:
        assert isinstance(s, str) and s == s.lower() and " " not in s, f"malformed stage token: {s!r}"


def test_fmr_validate_inputs_ladder_mirrors_the_authority() -> None:
    """fmr's local ladder is a hyphenated mirror of founder_context.VALID_STAGES
    — same membership, no duplicates (its order defines every gate derived
    from it below), and this is what ties the standalone-script mirror back to
    the shared authority."""
    ladder = _require_attr(FMR_VALIDATE_INPUTS, "_STAGE_LADDER", "fmr.validate_inputs._STAGE_LADDER")
    assert set(ladder) == VALID_STAGES
    assert len(ladder) == len(set(ladder)), "ladder must have no duplicates for .index() to be unambiguous"


# ---------------------------------------------------------------------------
# semantic_gate — must be DERIVED from a ladder, not a hand-written literal
# ---------------------------------------------------------------------------


def test_fmr_seed_plus_and_series_a_plus_are_derived_from_the_ladder() -> None:
    """DISPOSITION: resolves directly — membership in a frozenset derived from
    the ladder via _stages_at_or_above. pre-seed's absence from _SEED_PLUS is
    by construction (the floor), not an omission."""
    seed_plus = _require_attr(FMR_VALIDATE_INPUTS, "_SEED_PLUS", "fmr.validate_inputs._SEED_PLUS")
    series_a_plus = _require_attr(FMR_VALIDATE_INPUTS, "_SERIES_A_PLUS", "fmr.validate_inputs._SERIES_A_PLUS")
    ladder = FMR_VALIDATE_INPUTS._STAGE_LADDER

    assert seed_plus == frozenset(ladder[ladder.index("seed") :])
    assert series_a_plus == frozenset(ladder[ladder.index("series-a") :])
    assert seed_plus == VALID_STAGES - {"pre-seed"}
    assert series_a_plus == VALID_STAGES - {"pre-seed", "seed"}
    assert "pre-seed" not in seed_plus
    assert "seed" not in series_a_plus


def test_fmr_stages_at_or_above_is_live_derivation_not_a_baked_in_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anti-vacuity for the derivation claim in the test above: shrink the
    module's ladder and confirm _stages_at_or_above's OUTPUT shrinks with it.
    A hand-written set frozen at import time would not react to this."""
    mod = FMR_VALIDATE_INPUTS
    fake_ladder = ("pre-seed", "seed", "series-a")  # series-b..later removed
    monkeypatch.setattr(mod, "_STAGE_LADDER", fake_ladder)
    result = mod._stages_at_or_above("seed")
    assert result == frozenset({"seed", "series-a"})
    assert "series-b" not in result
    assert "later" not in result


# ---------------------------------------------------------------------------
# ui_enum via ast — _ENUM_FIELDS["stage"] (function-local; not importable)
# ---------------------------------------------------------------------------


def test_fmr_enum_fields_stage_is_derived_from_the_ladder_via_ast() -> None:
    """DISPOSITION: resolves directly — the Layer-1 structural-intake enum for
    company.stage IS the full ladder, expressed as list(_STAGE_LADDER) rather
    than a copied-out literal, so it can't drift from the ladder independently.
    _ENUM_FIELDS is local to _validate_structural, invisible to import/getattr
    and to a naive top-level AST walk, so this reads the function body."""
    path = os.path.join(FMR_DIR, "validate_inputs.py")
    source = _read_source(path)
    value_node = _find_enum_fields_stage_value_node(source)
    assert isinstance(value_node, ast.Tuple) and len(value_node.elts) == 2
    allowed_node = value_node.elts[1]
    assert isinstance(allowed_node, ast.Call), "expected list(_STAGE_LADDER) — a derived call, not a literal list"
    assert isinstance(allowed_node.func, ast.Name) and allowed_node.func.id == "list"
    assert len(allowed_node.args) == 1
    arg = allowed_node.args[0]
    assert isinstance(arg, ast.Name) and arg.id == "_STAGE_LADDER", (
        "the enum's allowed-values expression must reference the module ladder by name, "
        "not restate it as a literal that can silently drift from the ladder"
    )


def test_fmr_enum_fields_ast_check_discriminates_a_hand_written_literal() -> None:
    """Anti-vacuity: run the same reader against a hand-mutated copy where the
    derived list(_STAGE_LADDER) call has been replaced by a hand-written
    literal, and confirm the derivation assertion would have caught it."""
    original = _read_source(os.path.join(FMR_DIR, "validate_inputs.py"))
    needle = '"stage": (("company", "stage"), list(_STAGE_LADDER)),'
    assert needle in original, "fixture assumption stale — source line changed"
    mutated = original.replace(needle, '"stage": (("company", "stage"), ["pre-seed", "seed"]),')
    value_node = _find_enum_fields_stage_value_node(mutated)
    assert isinstance(value_node, ast.Tuple) and len(value_node.elts) == 2
    allowed_node = value_node.elts[1]
    assert not isinstance(allowed_node, ast.Call), (
        "mutation should read as a literal list, proving the check discriminates"
    )
    assert isinstance(allowed_node, ast.List)


# ---------------------------------------------------------------------------
# lookup_table — every ladder value resolves transitively to an existing key,
# with a disclosed substitution when one was needed
# ---------------------------------------------------------------------------


def test_fmr_stage_benchmarks_resolves_every_ladder_stage_with_disclosure() -> None:
    """DISPOSITION: direct for pre-seed/seed/series-a (published benchmarks
    exist); DECLARED FALLBACK to series-a for every stage above it."""
    mod = FMR_UNIT_ECONOMICS
    table = _require_attr(mod, "STAGE_BENCHMARKS", "fmr.unit_economics.STAGE_BENCHMARKS")
    resolve = _require_attr(mod, "_resolve_stage_benchmarks", "fmr.unit_economics._resolve_stage_benchmarks")
    for stage in sorted(VALID_STAGES):
        benchmarks, basis = resolve(stage)
        assert benchmarks in table.values(), (
            f"{stage} resolved to a dict that isn't one of STAGE_BENCHMARKS's own values"
        )
        if stage in table:
            assert basis is None, f"{stage} has its own benchmarks; a substitution basis would misreport it"
        else:
            assert basis is not None, f"{stage} has no published benchmarks and got no disclosure"
            assert basis["resolved_to"] in table
            assert basis["requested"] == stage


def test_fmr_stage_benchmarks_disclosure_reaches_the_artifact() -> None:
    """The substitution basis must be written into the artifact the founder
    reads — a stderr-only warning does not count (per the brief)."""
    source = _read_source(os.path.join(FMR_DIR, "unit_economics.py"))
    assert 'result["benchmark_basis"] = benchmark_basis' in source


def test_fmr_stage_ranges_resolves_every_ladder_stage_downward_with_disclosure() -> None:
    """DISPOSITION: direct for pre-seed/seed/series-a/series-b; DECLARED
    FALLBACK downward along the ladder for series-c/series-d/later (the
    nearest LOWER stage that has ranges — a stricter floor than borrowing
    upward or defaulting flat)."""
    mod = FMR_VALIDATE_EXTRACTION
    table = _require_attr(mod, "_STAGE_RANGES", "fmr.validate_extraction._STAGE_RANGES")
    resolve = _require_attr(mod, "_resolve_stage_ranges", "fmr.validate_extraction._resolve_stage_ranges")
    ladder = _require_attr(mod, "_STAGE_LADDER", "fmr.validate_extraction._STAGE_LADDER")
    for stage in sorted(VALID_STAGES):
        ranges, basis = resolve(stage)
        assert ranges in table.values()
        if stage in table:
            assert basis is None
        else:
            assert basis is not None
            resolved_to = basis["resolved_to"]
            assert resolved_to in table
            assert ladder.index(resolved_to) < ladder.index(stage), "substitution must borrow from a LOWER stage"


def test_fmr_stage_ranges_disclosure_reaches_the_artifact() -> None:
    source = _read_source(os.path.join(FMR_DIR, "validate_extraction.py"))
    assert 'warn_result["stage_basis"] = stage_basis' in source
    assert 'pass_result["stage_basis"] = stage_basis' in source


# ---------------------------------------------------------------------------
# semantic_gate, hand-written by design — checklist's seed+ gate
# ---------------------------------------------------------------------------


def test_fmr_checklist_seed_plus_stages_resolves_every_ladder_stage_in_both_dialects() -> None:
    """DISPOSITION: resolves directly. Hand-written (not ladder-derived) BY
    DESIGN — unlike the semantic_gate sites above, this one must exclude
    pre-seed (it's the gate that turns seed+ criteria OFF for pre-seed
    founders), so a generic ">= floor" helper is the wrong shape here. This
    test does not fix or flag the hand-writing; it confirms the set still
    resolves every ladder stage, in both the hyphen and underscore dialects
    that reach checklist.py."""
    stages = _require_attr(FMR_CHECKLIST, "_SEED_PLUS_STAGES", "fmr.checklist._SEED_PLUS_STAGES")
    for stage in sorted(VALID_STAGES):
        underscore = stage.replace("-", "_")
        is_seed_plus = stage in stages or underscore in stages
        if stage == "pre-seed":
            assert not is_seed_plus, "pre-seed's absence from seed+ is deliberate — do not add it"
        else:
            assert is_seed_plus, f"{stage} (or its underscore form) must gate seed+ criteria on"
    assert len(stages) == 11, "cardinality drifted — re-derive the seed+/dialect/growth accounting above"


# ---------------------------------------------------------------------------
# ui_enum via text — review_inputs.py's JS stage dropdown (not importable)
# ---------------------------------------------------------------------------


def test_fmr_review_inputs_stage_dropdown_offers_the_full_ladder() -> None:
    """DISPOSITION: ui_enum, must resolve directly. The interactive review
    page's Stage <select> must offer every ladder stage — an omitted stage
    can't be selected, and worse, the browser silently pre-selects the FIRST
    listed option for a stored value that isn't among the options, which
    looks like a saved value to the founder and isn't. Not importable (a JS
    literal inside a Python-templated HTML string), so this reads the source
    text directly."""
    source = _read_source(REVIEW_INPUTS_PATH)
    options = _extract_js_string_array(source, 'createDropdown("company.stage"')
    assert set(options) == VALID_STAGES, f"dropdown offers {sorted(options)}, ladder is {sorted(VALID_STAGES)}"


def test_review_inputs_dropdown_extractor_discriminates_a_missing_stage() -> None:
    """Anti-vacuity: feed the extractor a hand-truncated copy (series-d
    removed) and confirm the membership assertion above would have caught it
    — this is exactly the shape of the bug that was live here before the fix."""
    source = _read_source(REVIEW_INPUTS_PATH)
    needle = '"series-d", "later"'
    assert needle in source, "fixture assumption stale — source line changed"
    truncated = source.replace(needle, '"later"')
    options = _extract_js_string_array(truncated, 'createDropdown("company.stage"')
    assert set(options) != VALID_STAGES
    assert "series-d" not in options


# ---------------------------------------------------------------------------
# display_map — competitive-positioning's generic humanizer
# ---------------------------------------------------------------------------


def test_cp_humanize_resolves_every_ladder_stage_in_both_dialects() -> None:
    """DISPOSITION: DECLARED FALLBACK. _LABELS only curates a handful of stage
    tokens; _humanize's `.get(value, <title-cased default>)` covers the rest.
    Confirmed by exercising every ladder stage in both dialects and requiring
    a non-empty, non-sentinel label even for tokens absent from _LABELS
    (e.g. series-c isn't a curated key)."""
    humanize = _require_attr(CP_COMPOSE_REPORT, "_humanize", "competitive_positioning.compose_report._humanize")
    for stage in sorted(VALID_STAGES):
        for token in (stage, stage.replace("-", "_")):
            label = humanize(token)
            assert label and label != "?", f"{token} produced no usable label"


def test_cp_humanize_default_branch_is_reachable_not_dead_code() -> None:
    """Anti-vacuity: prove the fallback branch — not a lucky dict hit — is
    what answers for a value that genuinely isn't a _LABELS key."""
    humanize = CP_COMPOSE_REPORT._humanize
    assert humanize("series-c") == "Series-C"  # title-cased fallback, not a curated label
    assert humanize("") == "?"
    assert humanize(None) == "?"


# ---------------------------------------------------------------------------
# ui_enum — deck-review's deliberately narrower detectable-stage domain
# ---------------------------------------------------------------------------


def test_deck_review_stage_table_matches_the_schema_enum_exactly() -> None:
    """DISPOSITION: DECLARED OUT-OF-SCOPE, not a coverage gap. deck-review's
    detectable-stage domain (pre_seed, seed, series_a get real frameworks;
    series_b/growth are stub entries whose only job is to be catchable as
    STAGE_OUT_OF_SCOPE downstream) is deliberately narrower than the full
    ladder — SKILL.md documents these five as "the complete --rebuild-stage
    enum". What this test guards is drift between the CLI enum and the schema
    enum it must match exactly, not extension to the whole ladder (that's
    covered by KNOWN_STAGES below, which — unlike this site — IS full-ladder,
    via its catch-all complement)."""
    table = _require_attr(DECK_REVIEW_STAGE_PROFILE, "_STAGE_TABLE", "deck_review.stage_profile._STAGE_TABLE")
    schema_path = os.path.join(DECK_REVIEW_DIR, "..", "references", "schemas", "stage_profile.schema.json")
    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)
    assert set(table.keys()) == set(schema["properties"]["detected_stage"]["enum"])


# ---------------------------------------------------------------------------
# semantic_gate with a founder-visible catch-all disclosure — deck-review and
# ic-sim's STAGE_OUT_OF_SCOPE mechanism. Exercised end-to-end through the real
# validate_artifacts, not by re-deriving the membership logic in this file.
# ---------------------------------------------------------------------------


def _dr_detected_stage_signal(detected: str) -> set[str]:
    mod = DECK_REVIEW_COMPOSE_REPORT
    artifacts: dict[str, Any] = {
        "deck_inventory.json": {"metadata": {"run_id": "r1"}},
        "stage_profile.json": {"metadata": {"run_id": "r1"}, "detected_stage": detected},
        "slide_reviews.json": {"metadata": {"run_id": "r1"}},
        "checklist.json": {"metadata": {"run_id": "r1"}},
    }
    warnings = mod.validate_artifacts(artifacts)
    return {w["code"] for w in warnings if "STAGE" in w["code"]}


def _dr_claimed_stage_signal(claimed: str) -> set[str]:
    """Isolate the claimed-stage cross-check by omitting stage_profile.json
    entirely (both the STAGE_MISMATCH block and the detected-side half of
    STAGE_OUT_OF_SCOPE require a usable profile; leaving it unusable strips
    both, leaving only the claimed-side branch active)."""
    mod = DECK_REVIEW_COMPOSE_REPORT
    artifacts: dict[str, Any] = {
        "deck_inventory.json": {"metadata": {"run_id": "r1"}, "claimed_stage": claimed},
        "stage_profile.json": None,
        "slide_reviews.json": {"metadata": {"run_id": "r1"}},
        "checklist.json": {"metadata": {"run_id": "r1"}},
    }
    warnings = mod.validate_artifacts(artifacts)
    return {w["code"] for w in warnings if "STAGE" in w["code"]}


def test_deck_review_detected_stage_out_of_scope_covers_the_full_ladder_complement() -> None:
    """DISPOSITION: direct for pre_seed/seed/series_a; DECLARED OUT-OF-SCOPE
    (a founder-visible STAGE_OUT_OF_SCOPE warning) for every other ladder
    stage — proven by actually calling validate_artifacts, not by
    re-implementing the `not in KNOWN_STAGES` check here."""
    mod = DECK_REVIEW_COMPOSE_REPORT
    known = _require_attr(mod, "KNOWN_STAGES", "deck_review.compose_report.KNOWN_STAGES")
    assert "STAGE_OUT_OF_SCOPE" in mod.WARNING_SEVERITY
    assert "STAGE_OUT_OF_SCOPE" in mod.WARNING_LABELS
    for stage in sorted(VALID_STAGES_UNDERSCORE):
        codes = _dr_detected_stage_signal(stage)
        if stage in known:
            assert "STAGE_OUT_OF_SCOPE" not in codes, f"{stage} is in scope; should not be flagged"
        else:
            assert "STAGE_OUT_OF_SCOPE" in codes, f"{stage} fell through detected_stage with no founder-visible signal"


def test_deck_review_claimed_stage_cross_check_covers_the_full_ladder() -> None:
    """DISPOSITION (post-fix): every ladder stage a deck itself claims now
    resolves — direct for pre_seed/seed/series_a, DECLARED OUT-OF-SCOPE for
    the rest. Before this file's fix, RECOGNIZED_STAGE_TOKENS was missing
    series_d and later: a deck claiming either got neither STAGE_MISMATCH nor
    STAGE_OUT_OF_SCOPE — silently treated as "not a stage assertion" with no
    founder-visible signal at all. Proven end-to-end through validate_artifacts."""
    mod = DECK_REVIEW_COMPOSE_REPORT
    known = _require_attr(mod, "KNOWN_STAGES", "deck_review.compose_report.KNOWN_STAGES")
    recognized = _require_attr(mod, "RECOGNIZED_STAGE_TOKENS", "deck_review.compose_report.RECOGNIZED_STAGE_TOKENS")
    assert recognized >= VALID_STAGES_UNDERSCORE, (
        f"missing from RECOGNIZED_STAGE_TOKENS: {sorted(VALID_STAGES_UNDERSCORE - recognized)}"
    )
    for stage in sorted(VALID_STAGES_UNDERSCORE):
        codes = _dr_claimed_stage_signal(stage)
        if stage in known:
            assert codes == set(), f"{stage} is in scope; the claimed-side check alone should not flag it"
        else:
            assert "STAGE_OUT_OF_SCOPE" in codes, f"a deck claiming '{stage}' got no founder-visible stage signal"


def _icsim_stage_signal(stage: str) -> set[str]:
    mod = IC_SIM_COMPOSE_REPORT
    artifacts: dict[str, Any] = {name: {"metadata": {"run_id": "r1"}} for name in mod.REQUIRED_ARTIFACTS}
    artifacts["startup_profile.json"]["stage"] = stage
    warnings = mod.validate_artifacts(artifacts)
    return {w["code"] for w in warnings if "STAGE" in w["code"]}


def test_icsim_stage_out_of_scope_covers_the_full_ladder_complement() -> None:
    """DISPOSITION: direct for pre_seed/seed/series_a; DECLARED OUT-OF-SCOPE
    for every other ladder stage. ic-sim has a single startup.stage field (no
    claimed/detected split) and checks KNOWN_STAGES directly with a
    fail-closed `not in` — no allowlist prefilter — which is exactly why this
    site never needed the fix deck-review's RECOGNIZED_STAGE_TOKENS did."""
    mod = IC_SIM_COMPOSE_REPORT
    known = _require_attr(mod, "KNOWN_STAGES", "ic_sim.compose_report.KNOWN_STAGES")
    assert "STAGE_OUT_OF_SCOPE" in mod.WARNING_SEVERITY
    for stage in sorted(VALID_STAGES):
        underscore = stage.replace("-", "_")
        codes = _icsim_stage_signal(stage)
        if underscore in known:
            assert codes == set(), f"{stage} is in scope; should not be flagged"
        else:
            assert "STAGE_OUT_OF_SCOPE" in codes, f"{stage} fell through with no founder-visible signal"


def test_icsim_stage_out_of_scope_also_catches_a_token_off_the_ladder_entirely() -> None:
    """The catch-all is fail-closed for garbage input too, not just for the
    other 6 real ladder stages — a stray typo doesn't get a free pass."""
    codes = _icsim_stage_signal("not-a-real-stage")
    assert "STAGE_OUT_OF_SCOPE" in codes
