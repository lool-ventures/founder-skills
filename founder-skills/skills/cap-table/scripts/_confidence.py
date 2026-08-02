"""Cap-base confidence-tier classifier, shared by visualize.py and explore.py.

Single source of truth for "is this cap base real/verified enough to render with full visual
confidence" — mirrors _warning_callouts.py's role for report.md's text callouts, but for the
HTML/explorer visual-suppression treatment (R-5). Deliberately narrower than the full
_warning_callouts family: only the five warning codes that speak to whether the BASE itself is
real/verified are in scope here (see the plan doc's "Scope boundary" note) — redline-draft,
founder-looks-like-investor, anti-dilution-recovery, and AoA-only stay report.md-only callouts.
"""

from __future__ import annotations

CONFIDENCE_CODES: tuple[str, ...] = (
    "W_BASE_VACUOUS",
    "W_CAP_BASE_ASSUMED",
    "W_CAP_BASE_RECONSTRUCTED",
    "W_VISION_EXTRACTION_LOW_CONFIDENCE",
    "W_FD_RECONCILE_DELTA",  # prefix match: carries an interpolated detail string after ":"
)

TIER_BADGE_TEXT: dict[str, str] = {
    "vacuous": "Not a real cap table yet",
    "unverified": "Base unverified",
}


def _matches(warning: str, code: str) -> bool:
    """True if warning IS code, or carries code as an interpolated-detail prefix (`code:...`)."""
    return warning == code or warning.startswith(code + ":")


def confidence_warnings(all_warnings: list[str]) -> list[str]:
    """The subset of all_warnings that are confidence-tier codes, order preserved."""
    return [w for w in all_warnings if any(_matches(w, code) for code in CONFIDENCE_CODES)]


def confidence_tier(all_warnings: list[str]) -> str:
    """ "vacuous" | "unverified" | "ok". Vacuous dominates when both fire (it is the stronger claim:
    there are no real holders at all, vs. merely-unverified-but-real numbers)."""
    cw = confidence_warnings(all_warnings)
    if any(_matches(w, "W_BASE_VACUOUS") for w in cw):
        return "vacuous"
    if cw:
        return "unverified"
    return "ok"
