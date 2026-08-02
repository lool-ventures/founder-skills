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
    if any(w == "W_NOTE_PRINCIPAL_MISSING" for w in cap_state_warnings):
        out.append("> ⚠ **A convertible note has no principal (blank / template) — kept as terms-only.** Its")
        out.append("> conversion math was skipped, so it contributes NO shares and is excluded from the")
        out.append("> figures below — the amount may live in a Schedule of Lenders. Provide the principal")
        out.append("> to model the note's conversion.")
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
