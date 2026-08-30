"""Shared founder-facing renderer for `cap_state` warnings.

Single source of truth for the warning-callout block so the full report (`compose_report`) and the
concise answer (`concise_report`) cannot diverge: a warning family added here renders on both routes.

Bare-code warnings match by equality; the anti-dilution recovery warnings are interpolated SENTENCES
(`W_ANTI_DILUTION_*: …`) so they match by PREFIX — otherwise the recovery detail stays invisible to
the founder.

(Module is named `_warning_callouts`, not `_warnings`: `_warnings` is a CPython builtin backing the
stdlib `warnings` module, so `import _warnings` always resolves to the builtin and a sibling file of
that name is unreachable on `sys.path`.)
"""

from __future__ import annotations


def render_warning_callouts(cap_state_warnings: list[str]) -> list[str]:
    """Render the cap_state warning families as a founder-facing markdown callout block.

    Returns a list of markdown lines (empty list when there are no matching warnings)."""
    out: list[str] = []
    if any(w == "W_AOA_ONLY_NO_INSTRUMENTS" for w in cap_state_warnings):
        out.append("> **AoA-only engagement detected.** No instruments to convert; this report renders the")
        out.append("> Articles-of-Association findings and the current pre-financing cap state. To model")
        out.append("> dilution scenarios, add SAFEs, convertible notes, option grants, or warrants to")
        out.append("> `instruments.json`.")
        out.append("")
    if any(w == "W_CAP_BASE_ASSUMED" for w in cap_state_warnings):
        out.append("> ⚠ **Cap base ASSUMED, not founder-confirmed.** Founder share counts / option pool were")
        out.append("> not confirmed (generic placeholder names or an explicit assumed flag) — ownership")
        out.append("> figures below are DIRECTIONAL. Confirm the cap base before relying on these numbers.")
        out.append("")
    if any(w == "W_FOUNDER_LOOKS_LIKE_INVESTOR" for w in cap_state_warnings):
        out.append("> ⚠ **A listed founder resembles an investment entity** (name contains")
        out.append("> Ventures/Capital/Fund). Confirm it is a founder, not an investor — mis-classifying an")
        out.append("> investor as a founder distorts the ownership table.")
        out.append("")
    if any(w == "W_VISION_EXTRACTION_LOW_CONFIDENCE" for w in cap_state_warnings):
        out.append("> ⚠ **Image-only PDF read by vision (no OCR).** The source PDF had no text layer, so these")
        out.append("> figures were read from page images — dense tables are easily under-read or dropped. Treat")
        out.append("> the cap table as LOW-CONFIDENCE and directional; confirm every holder/class against the")
        out.append("> source before relying on these numbers.")
        out.append("")
    if any(w == "W_REDLINE_DRAFT" for w in cap_state_warnings):
        out.append("> ⚠ **Extracted from a redline / tracked-changes draft (accepted-changes view).** The")
        out.append("> source `.docx` still carries tracked changes — it is an UNSIGNED draft under negotiation,")
        out.append("> not a final executed agreement. The terms reflect the proposed-final (accepted) view;")
        out.append("> confirm them against the signed/clean version before relying on them.")
        out.append("")
    if any(w == "W_CAP_BASE_RECONSTRUCTED" for w in cap_state_warnings):
        out.append("> ⚠ **Cap base was NOT produced by the deterministic spreadsheet mapper.** It was entered")
        out.append("> manually or extracted from a document (PDF / Carta / pasted), so it was not")
        out.append("> mechanically verified against a structured source. Confirm each holder and class against")
        out.append("> whatever these figures came from — the source document if there was one, or your own")
        out.append("> share records if you described the cap table in conversation — before relying on them.")
        out.append("")
    if any(w == "W_PRICING_UNKNOWN" for w in cap_state_warnings):
        out.append("> ⚠ **Preferred pricing unknown for at least one series.** Anti-dilution and")
        out.append("> liquidation preference are not modeled for that series, and the conversion ratio is")
        out.append("> assumed 1:1 (no historical pricing) — a real down-round adjustment would not be")
        out.append("> reflected. Confirm the actual issuance terms with counsel before relying on any")
        out.append("> ownership, dilution, or preference figures involving this series.")
        out.append("")
    if any(w == "W_BASE_VACUOUS" for w in cap_state_warnings):
        out.append("> ⚠ **No real cap-table base — this deliverable is not meaningful yet.** The cap base has")
        out.append("> NO founders, common, or preferred holders — the fully-diluted total is essentially just an")
        out.append("> unallocated option pool. The ownership %s, the fully-diluted figure, and the donut do NOT")
        out.append("> describe a real company until the actual holder base (founders + share counts) is provided.")
        out.append("")
    if any(w == "W_SAFE_PURCHASE_AMOUNT_MISSING" for w in cap_state_warnings):
        out.append("> ⚠ **A SAFE has no purchase amount (blank / template) — kept as terms-only.** Its")
        out.append("> conversion math was skipped, so it contributes NO shares and is excluded from the")
        out.append("> ownership/dilution figures below. Provide the SAFE's purchase amount to model it.")
        out.append("")
    # Each of these names the field that is ACTUALLY missing, and states the DIRECTION of the error.
    # "Contributes no shares" is the mechanism; the consequence is that every remaining stake — the
    # founder's included — is displayed HIGHER than it will really be, and that is the part worth
    # saying out loud, because the error flatters the reader.
    if any(w == "W_NOTE_PRINCIPAL_MISSING" for w in cap_state_warnings):
        out.append("> ⚠ **A convertible note has no principal (blank / template) — kept as terms-only.** Its")
        out.append("> conversion math was skipped, so it mints no shares here. **Every ownership figure")
        out.append("> below is therefore shown HIGHER than it will actually be**, including yours — the")
        out.append("> note still dilutes you, it just cannot be sized yet. The amount may live in a")
        out.append("> Schedule of Lenders. Provide the principal to model the note's conversion.")
        out.append("")
    if any(w == "W_NOTE_ISSUANCE_DATE_MISSING" for w in cap_state_warnings):
        out.append("> ⚠ **A convertible note has no issuance date — kept as terms-only.** Interest accrues")
        out.append("> from issuance, so without that date the note's conversion cannot be computed even")
        out.append("> when its principal is known. It mints no shares here, so **every ownership figure")
        out.append("> below is shown HIGHER than it will actually be**, including yours. Provide the")
        out.append("> note's issuance date to model its conversion.")
        out.append("")
    if any(w == "W_WARRANT_EXERCISE_PRICE_MISSING" for w in cap_state_warnings):
        out.append("> ⚠ **A warrant has no stated exercise price (strike) — its shares ARE still counted.**")
        out.append("> Unlike a terms-only SAFE/note, the warrant's underlying shares REMAIN in the")
        out.append("> fully-diluted total below. Only its exercise / net-share-settlement math was skipped")
        out.append("> pending the strike — supply the exercise price to model exercise.")
        out.append("")
    if any(w == "W_OPTION_GRANT_STRIKE_MISSING" for w in cap_state_warnings):
        out.append("> ⚠ **An option grant has no stated strike price — share counts are unaffected.**")
        out.append("> The pool aggregate drives fully-diluted math, so the totals below are unchanged. Only")
        out.append("> strike-dependent analysis (repricing, 409A / §102 pricing questions) is pending —")
        out.append("> confirm the strike with the founder before relying on any per-grant economics.")
        out.append("")
    fd_rec = [w for w in cap_state_warnings if w.startswith("W_FD_RECONCILE_DELTA")]
    if fd_rec:
        out.append("> ⚠ **Computed total does not match the source-stated total.** The fully-diluted total")
        out.append("> computed from the entered holders/classes diverges from the figure the source document")
        out.append("> itself states — a holder or class may have been dropped or mis-entered. Reconcile before")
        out.append("> relying on ownership math:")
        for w in fd_rec:
            detail = w.split(":", 1)[1].strip() if ":" in w else w
            out.append(f"> - {detail}")
        out.append("")
    stale = [w for w in cap_state_warnings if w.startswith("W_STALE_CCP_SUSPECTED")]
    if stale:
        out.append("> ⚠ **A conversion price looks out of date.** The cap table records an earlier")
        out.append("> anti-dilution adjustment for the series below, yet its conversion price is still the")
        out.append("> original one. Either that adjustment was never applied to your records, or it did not")
        out.append("> happen. Resolve it before relying on any ownership figure — every percentage in this")
        out.append("> report is computed from these prices:")
        for w in stale:
            detail = w.split(":", 1)[1].strip() if ":" in w else w
            out.append(f"> - {detail}")
        out.append("")
    ad = [w for w in cap_state_warnings if w.startswith("W_ANTI_DILUTION")]
    if ad:
        out.append("> ⚠ **Anti-dilution input recovered — confirm with counsel.** The anti-dilution intent")
        out.append("> below was not supplied in the canonical field; it was recovered (or flagged) so it is")
        out.append("> NOT silently dropped. Verify the term before relying on the down-round math:")
        for w in ad:
            detail = w.split(":", 1)[1].strip() if ":" in w else w
            out.append(f"> - {detail}")
        out.append("")
    return out


# ---------------------------------------------------------------------------------------------
# SOLVER warnings.
#
# A DIFFERENT CHANNEL from everything above, and it was reaching the founder through none of them.
# `render_warning_callouts` takes `cap_state["warnings"]`, a list of STRINGS. The priced-round solver
# emits its warnings as DICTS onto `scenarios.json`'s `computed_outputs.warnings`, and the composer
# read that list in exactly two places, both testing for one unrelated code -- so every solver warning
# was computed, serialised, and then dropped before the report.
#
# That silence had a contract violation inside it: `agents/cap-table.md` states that when the solver
# emits W_MFN_NOT_MOST_FAVORABLE "the report should label it as such, not as the holder's actual
# entitlement." Nothing labelled it, so a counterfactual MFN election was presented to the founder as
# their entitlement.
#
# UNKNOWN CODES ARE RENDERED, NOT SKIPPED. A warning the solver thought worth emitting is worth
# showing even if this renderer has no bespoke prose for it; the alternative reintroduces exactly the
# silent-drop defect this function exists to fix. New solver warnings therefore surface by default and
# get better wording later, rather than being invisible until someone remembers to add a branch.
# ---------------------------------------------------------------------------------------------

# Founder-facing prose per solver warning code. `{}` placeholders are filled from the warning payload
# by _solver_subject() -- deliberately not %-formatted against the raw dict, so a missing key degrades
# to a slightly vaguer sentence instead of raising mid-report.
_SOLVER_WARNING_PROSE: dict[str, str] = {
    "W_MFN_NOT_MOST_FAVORABLE": (
        "**This MFN election is a counterfactual, not your entitlement.** The most-favoured-nation "
        "SAFE below was modelled against the terms it named, but a better set of sibling terms "
        "exists. A real YC MFN takes the MOST favourable terms available, so the true conversion is "
        "at least as good as what is shown here — do not read this line as the holder's actual "
        "entitlement."
    ),
    "W_MFN_ELECTION_OVERRIDES_INSTRUMENT": (
        "**A scenario setting overrode terms recorded on the instrument.** The most-favoured-nation "
        "election used here came from the scenario, not from the SAFE itself. Confirm the election "
        "matches the executed document before relying on the conversion."
    ),
    "W_CP2_FLOOR_APPLIED": (
        "**Your charter's price floor limited the anti-dilution adjustment.** The down-round "
        "adjustment would have reduced the conversion price further, but the floor in your charter "
        "stopped it. Confirm the floor value against the charter — it changes how much protection "
        "the holder actually receives."
    ),
    "W_STALE_CCP_SUSPECTED": (
        "**A prior down-round adjustment may not be reflected in the starting price.** This series "
        "has an earlier anti-dilution event on record, yet its current conversion price still equals "
        "the original. If the earlier adjustment was never applied, this round's protection is "
        "computed from the wrong starting point."
    ),
    "W_SOLVER_AITKEN_FALLBACK": (
        "**The round math needed a fallback to settle.** The interlocking SAFE / note / pool "
        "calculation was hard to converge and an acceleration step had to be reverted. The result "
        "below is the settled one, but it is worth a second look."
    ),
}


def _solver_subject(w: dict) -> str:
    """The 'which one' half of a solver callout: the instrument or series the warning is about."""
    for key in ("instance_id", "series_id", "safe_id", "note_id"):
        val = w.get(key)
        if val:
            return str(val)
    return ""


def solver_callouts_plaintext(scenarios: list[dict]) -> list[str]:
    """Solver callouts as PLAIN PROSE, for the HTML renderers.

    Deliberately not `visualize._strip_md_markers`, which does `.replace("_", "")` -- it deletes
    every underscore, so `safe_003_mfn` reaches the founder as `safe003mfn`, a name matching nothing
    in their cap table. Solver callouts always name an instrument by its snake_case id, so that
    helper is exactly wrong for this channel even though it is right for the one beside it.

    Strips the blockquote marker, bold markers and code backticks; leaves the text otherwise intact.
    Callers still HTML-escape.
    """
    out: list[str] = []
    lines = render_solver_warning_callouts(collect_solver_warnings(scenarios))
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith(">"):
            s = s[1:].strip()
        s = s.replace("**", "").replace("`", "")
        out.append(s)
    return out


def collect_solver_warnings(scenarios: list[dict]) -> list[dict]:
    """Walk scenarios -> `computed_outputs.warnings` and return the solver's warning dicts.

    Shared because it must be: this walk lived inline in `compose_report`, which is precisely why
    the other five founder-facing surfaces did not do it. Each of them renders `cap_state`'s warning
    STRINGS and stops, so every one of them read as "warnings are handled here" while the solver's
    channel -- including the MFN counterfactual -- reached only `report.md`.

    Tolerant of a scenario with no `computed_outputs` and of a null `warnings`: this is read back off
    a JSON artifact, and one malformed scenario must not cost the founder the warnings beside it.
    """
    collected: list[dict] = []
    for s in scenarios or []:
        if not isinstance(s, dict):
            continue
        co = s.get("computed_outputs") or {}
        if isinstance(co, dict):
            collected.extend(co.get("warnings") or [])
    return collected


def render_solver_warning_callouts(solver_warnings: list[dict]) -> list[str]:
    """Render `computed_outputs.warnings` (solver dicts) as founder-facing callouts.

    Returns markdown lines, empty when there is nothing to say. Non-dict entries are tolerated and
    skipped: this list is read back off a JSON artifact that a prior step may have written loosely,
    and a malformed entry must not cost the founder the well-formed ones beside it.
    """
    out: list[str] = []
    seen: set[tuple[str, str]] = set()
    for w in solver_warnings or []:
        if not isinstance(w, dict):
            continue
        code = str(w.get("code") or "").strip()
        if not code or not code.startswith("W_"):
            continue
        subject = _solver_subject(w)
        # The solver runs per scenario and the composer may pass several scenarios' lists; the same
        # warning about the same instrument is one fact, not three.
        if (code, subject) in seen:
            continue
        seen.add((code, subject))

        prose = _SOLVER_WARNING_PROSE.get(code)
        if prose is None:
            # No bespoke wording yet. Say the honest generic thing rather than dropping it. The code
            # itself is withheld: it is our vocabulary, not the founder's.
            prose = (
                "**The round math flagged something worth checking.** Confirm this scenario's "
                "assumptions before relying on the figures below."
            )
        head = f"> ⚠ {prose}" if not subject else f"> ⚠ {prose} (affects `{subject}`)"
        # Wrap to the same visual shape as the cap_state callouts above.
        out.append(head)
        detail = str(w.get("detail") or "").strip()
        if detail and code not in _SOLVER_WARNING_PROSE:
            out.append(f"> - {detail}")
        out.append("")
    return out
