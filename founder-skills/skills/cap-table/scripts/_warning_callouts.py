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
    if any(w == "W_CAP_BASE_RECONSTRUCTED" for w in cap_state_warnings):
        out.append("> ⚠ **Cap base was NOT produced by the deterministic spreadsheet mapper.** It was entered")
        out.append("> manually or extracted from a document (PDF / Carta / pasted), so it was not")
        out.append("> mechanically verified against a structured source. Confirm each holder/class against the")
        out.append("> source before relying on these numbers.")
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
