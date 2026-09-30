"""The one owner of what competitive-positioning tells a founder about its competitor set.

compose_report.py (report.md, report.json) and visualize.py (report.html) both render from this
module, so the two pages cannot say different things about the same set.

Named `_cp_view`, not `_view`: market-sizing owns a `_view` module, and the test suite imports both
skills' scripts into one process, where the first `_view` imported shadows the other. Market-sizing learned this
the expensive way: its visualize carried copies of compose's functions, held equal only by a test,
and two had already drifted by the time `_view.py` replaced them.

Everything here is computed from artifacts a producer wrote. Nothing reads a field whose only
purpose is to steer what the founder sees.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any


def _as_dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _as_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else []


def competitor_names(
    landscape: Mapping[str, Any] | None,
    landscape_draft: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Map competitor slug -> display name.

    The final landscape wins. The draft only fills slugs the final set no longer carries: a
    competitor dropped after the verification challenge is still named in that section, and without
    the draft its only label is the slug.
    """
    out: dict[str, str] = {}
    for source in (landscape_draft, landscape):
        for comp in _as_list(_as_dict(source).get("competitors")):
            comp = _as_dict(comp)
            slug = comp.get("slug")
            name = comp.get("name")
            if isinstance(slug, str) and slug and isinstance(name, str) and name.strip():
                out[slug] = name.strip()
    return out


def md_inline(text: str) -> str:
    """Make a research-written name inert in markdown: "<" and ">" backslash-escaped.

    Names come from web research, and report.md is read both rendered (where a viewer may render
    inline HTML, so "<img …>" in a name would be a tag) and raw. Backslash escapes render as the
    plain characters and read cleanly raw; HTML entities would show literally in a raw read.
    The HTML pages escape separately (`_esc`), so this is for markdown only.
    """
    return text.replace("<", "\\<").replace(">", "\\>")


def md_names(name_by_slug: Mapping[str, str]) -> dict[str, str]:
    """The name map with every name made inert for markdown (see `md_inline`)."""
    return {slug: md_inline(name) for slug, name in name_by_slug.items()}


def display_name(slug: str, name_by_slug: Mapping[str, str] | None) -> str:
    """Render a competitor's display name; fall back to the slug when unknown."""
    if slug == "_startup":
        return "This company"
    if name_by_slug:
        return name_by_slug.get(slug, slug)
    return slug


def row_name(slug: str, name_by_slug: Mapping[str, str] | None, startup_name: str | None) -> str:
    """A table row's company name: the startup by its own name, a competitor by its display name.

    The points and moat tables printed `_startup` and `carbon-robotics` on both baseline runs.
    """
    if slug == "_startup":
        return startup_name.strip() if isinstance(startup_name, str) and startup_name.strip() else "This company"
    return display_name(slug, name_by_slug)


def final_slugs(landscape: Mapping[str, Any] | None) -> set[str]:
    """The slugs in the competitor set the analysis actually scored."""
    out: set[str] = set()
    for comp in _as_list(_as_dict(landscape).get("competitors")):
        slug = _as_dict(comp).get("slug")
        if isinstance(slug, str) and slug:
            out.add(slug)
    return out


def challenge_outcome(
    verdicts: Iterable[tuple[str, str]],
    landscape: Mapping[str, Any] | None,
) -> tuple[list[str], list[str]]:
    """Split the competitors judged `not_a_competitor` into (retained, removed), as slugs.

    Retained means the competitor is still in the scored set, so its rank has to be read with the
    verdict in mind. Removed means it left the set after the challenge. Reporting a removed
    competitor as "retained … scored and ranked" is a false sentence about the founder's own map,
    and it is what the verdicts alone produce: they are written before the founder confirms the set.
    Order follows the verdicts, so both pages list names in the same order.
    """
    scored = final_slugs(landscape)
    retained: list[str] = []
    removed: list[str] = []
    for slug, verdict in verdicts:
        if verdict != "not_a_competitor" or not slug:
            continue
        (retained if slug in scored else removed).append(slug)
    return retained, removed


# Moat status strength, strongest first. `not_applicable` is outside the order: a company the
# dimension does not apply to is not ranked on it.
_MOAT_STRENGTH: dict[str, int] = {"strong": 4, "moderate": 3, "weak": 2, "absent": 1}


def _names_list(slugs: list[str], name_by_slug: Mapping[str, str] | None, limit: int = 3) -> str:
    shown = [display_name(s, name_by_slug) for s in slugs[:limit]]
    rest = len(slugs) - len(shown)
    return ", ".join(shown) + (f" and {rest} more" if rest > 0 else "")


def moat_standing(
    dim_scores: Mapping[str, Any],
    competitor_slugs: list[str],
    name_by_slug: Mapping[str, str] | None,
    humanize: Any = str,
) -> str | None:
    """Where the startup stands on one moat dimension, as the founder reads it; None if unknown.

    Computed from the scored statuses (`comparison.by_dimension[dim]`), not from the producer's
    `startup_rank`, because that rank gives a tie the BETTER place: on a dimension every company
    lacks, the startup read "Rank 1 of 8". Here:
      * an absent moat gets no rank at all -- being first among companies that all lack it is not
        a standing -- and says how many competitors do have it;
      * a tie is stated as a tie, with the range of places and who shares it;
      * every competitor at the top status is a leader, not just the first one listed.
    """
    startup = dim_scores.get("_startup")
    if startup == "not_applicable":
        return "Not applicable to this business model"
    if startup not in _MOAT_STRENGTH:
        return None
    own = _MOAT_STRENGTH[startup]
    rated = [(s, dim_scores.get(s, "absent")) for s in competitor_slugs]
    rated = [(s, st) for s, st in rated if st in _MOAT_STRENGTH]
    top = max((_MOAT_STRENGTH[st] for _, st in rated), default=0)
    leaders = [s for s, st in rated if _MOAT_STRENGTH[st] == top and st != "absent"]
    leader_status = next((st for s, st in rated if s in leaders), None)
    leader_note = f" — leader: {_names_list(leaders, name_by_slug)} ({humanize(leader_status)})" if leaders else ""

    if startup == "absent":
        having = [s for s, st in rated if st != "absent"]
        if not having:
            return "Absent — no competitor assessed has it either"
        return f"Absent — {len(having)} of {len(rated)} competitors have it{leader_note}"

    ahead = sum(1 for _, st in rated if _MOAT_STRENGTH[st] > own)
    tied = [s for s, st in rated if _MOAT_STRENGTH[st] == own]
    total = len(rated) + 1
    best, worst = ahead + 1, ahead + len(tied) + 1
    if not tied:
        place = f"Rank {best} of {total} ranked"
    elif best == 1:
        place = f"Joint leader of {total} ranked, with {_names_list(tied, name_by_slug)}"
    else:
        place = f"Tied {best}–{worst} of {total} ranked, with {_names_list(tied, name_by_slug)}"
    if own == top:
        return place
    return place + leader_note


def axis_place(rank: Any, tied_with: Any, name_by_slug: Mapping[str, str] | None) -> str:
    """The startup's place on one axis: "3", or "3–4 (tied with Aigen)".

    `startup_*_rank` counts only competitors strictly ahead, so a tie reads as the better place. A
    run placed the startup and Aigen at the same cost and reported the startup as 1st on cost.
    """
    if not isinstance(rank, int):
        return "?"
    tied = [str(s) for s in _as_list(tied_with) if s]
    if not tied:
        return str(rank)
    return f"{rank}–{rank + len(tied)} (tied with {_names_list(tied, name_by_slug)})"


# --- founder overrides --------------------------------------------------------------------
# `founder_override` is a model-written stamp. It was measured on a first-pass moat rating, where
# the scoring sub-agent had no founder input, and the report then said the founder had overridden
# it. An override is shown only where the scored value actually differs from the value as first
# scored this run (the producer's `<output>.first.json`, see `_cp_first_copy`). No first copy means
# nothing can be shown as an override.

FIRST_MOAT_SCORES = "moat_scores.json.first.json"
FIRST_LANDSCAPE = "landscape.json.first.json"
# Spelled out, not built with an f-string: the dispatch-drift test finds consumers by literal name.
_SOURCE_FIELD = {"x": "x_evidence_source", "y": "y_evidence_source"}
FIRST_POSITIONING_SCORES = "positioning_scores.json.first.json"


def _moat_statuses(moat_scores: Mapping[str, Any] | None) -> dict[tuple[str, str], Any]:
    out: dict[tuple[str, str], Any] = {}
    for slug, company in _as_dict(_as_dict(moat_scores).get("companies")).items():
        for moat in _as_list(_as_dict(company).get("moats")):
            moat = _as_dict(moat)
            if isinstance(moat.get("id"), str):
                out[(str(slug), moat["id"])] = moat.get("status")
    return out


def confirmed_moat_overrides(
    moat_scores: Mapping[str, Any] | None, first: Mapping[str, Any] | None
) -> set[tuple[str, str]]:
    """(slug, moat id) stamped `founder_override` whose status changed since the first scoring."""
    if not isinstance(first, Mapping):
        return set()
    before = _moat_statuses(first)
    out: set[tuple[str, str]] = set()
    for slug, company in _as_dict(_as_dict(moat_scores).get("companies")).items():
        for moat in _as_list(_as_dict(company).get("moats")):
            moat = _as_dict(moat)
            key = (str(slug), str(moat.get("id")))
            stamped = moat.get("evidence_source") == "founder_override"
            if stamped and key in before and before[key] != moat.get("status"):
                out.add(key)
    return out


def _points(scores: Mapping[str, Any] | None) -> dict[tuple[str, str, str], Any]:
    out: dict[tuple[str, str, str], Any] = {}
    for view in _as_list(_as_dict(scores).get("views")):
        view = _as_dict(view)
        vid = str(view.get("view_id") or view.get("id") or "")
        for point in _as_list(view.get("points")):
            point = _as_dict(point)
            for axis in ("x", "y"):
                out[(vid, str(point.get("competitor")), axis)] = point.get(axis)
    return out


def confirmed_coordinate_overrides(
    positioning: Mapping[str, Any] | None, first_scores: Mapping[str, Any] | None
) -> set[tuple[str, str, str]]:
    """(view, competitor, axis) stamped `founder_override` whose value changed since first scoring."""
    if not isinstance(first_scores, Mapping):
        return set()
    before = _points(first_scores)
    out: set[tuple[str, str, str]] = set()
    for view in _as_list(_as_dict(positioning).get("views")):
        view = _as_dict(view)
        vid = str(view.get("id") or view.get("view_id") or "")
        for point in _as_list(view.get("points")):
            point = _as_dict(point)
            for axis in ("x", "y"):
                key = (vid, str(point.get("competitor")), axis)
                stamped = point.get(_SOURCE_FIELD[axis]) == "founder_override"
                if stamped and key in before and before[key] != point.get(axis):
                    out.add(key)
    return out


# --- the map in words (D2) ----------------------------------------------------------------
# The differentiation score is not shown to the founder: it reads as a percentage of something
# ("35%"), called a startup that led every competitor on both axes "Moderate … overlap", and gives
# the same number to maps with very different spacing. The view is stated from the scorer's
# geometry instead. Coordinates are coarse ordinal placements (in practice multiples of 5), so
# leads and distances are stated in bands, never digits. The band edges are PROVISIONAL -- set
# before any run was measured against them; recalibrate from critique runs, not by feel.
LEAD_LEVEL = 10.0  # |lead| below this reads "just ahead of" / "just behind" -- "level with" is only a tie
LEAD_WELL = 25.0  # |lead| at or above this reads "well ahead of" / "well behind"
NEAR_NEXT_TO = 15.0  # nearest competitor closer than this: "right next to you"
NEAR_CLEAR = 30.0  # farther than this: "clear space"


def short_axis_name(name: Any) -> str:
    """An axis name without its trailing parenthetical: real runs write "Distribution / go-to-market
    reach (dealer network, existing customer base, service infrastructure)", which repeated in every
    sentence buried the finding. The full name stays on the axis itself."""
    text = str(name or "").strip()
    if text.endswith(")") and " (" in text:
        text = text[: text.rindex(" (")].strip()
    return text


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _place_words(rank: Any, tied_with: Any, total: int | None) -> str | None:
    if not isinstance(rank, int) or total is None:
        return None
    tied = [s for s in _as_list(tied_with) if s]
    if tied:
        return f"tied {_ordinal(rank)}–{_ordinal(rank + len(tied))} of {total}"
    return f"{_ordinal(rank)} of {total}"


def _lead_words(lead: Any, best: Any, name_by_slug: Mapping[str, str] | None, tied_with: Any = None) -> str | None:
    """How far the startup is from the axis's best competitor, in words.

    "level with" only for a competitor the startup is TIED with: a small lead that is not a tie read
    "2nd of 11, level with John Deere" on a live run, with the startup 5 behind and no tie recorded --
    the rank and the words contradicted each other, and the review flagged it."""
    if not isinstance(lead, (int, float)) or isinstance(lead, bool):
        return None
    rivals = [s for s in _as_list(best) if s]
    if not rivals:
        return None
    who = _names_list(rivals, name_by_slug, limit=2)
    tied = [s for s in rivals if s in _as_list(tied_with)]
    size = abs(float(lead))
    if tied or size == 0:
        return f"level with {_names_list(tied or rivals, name_by_slug, limit=2)}"
    if size < LEAD_LEVEL:
        return f"{'just ahead of' if lead > 0 else 'just behind'} {who}"
    if lead > 0:
        return f"{'well ahead of' if size >= LEAD_WELL else 'ahead of'} {who}"
    return f"{'well behind' if size >= LEAD_WELL else 'behind'} {who}"


def _nearest_words(view: Mapping[str, Any], name_by_slug: Mapping[str, str] | None) -> str | None:
    slug, dist = view.get("nearest_competitor"), view.get("nearest_distance")
    if not isinstance(slug, str) or not isinstance(dist, (int, float)):
        return None
    name = display_name(slug, name_by_slug)
    if dist < NEAR_NEXT_TO:
        return f"Nearest competitor: {name}, right next to you."
    if dist <= NEAR_CLEAR:
        return f"Nearest competitor: {name}, close by."
    return f"Nearest competitor: {name}, with clear space between you."


def view_sentence(
    view: Mapping[str, Any], name_by_slug: Mapping[str, str] | None, label: str | None = None
) -> str | None:
    """One view of the map in words, e.g.

    "Cost per acre: 1st of 11, well ahead of Carbon Robotics; reach: 11th of 11, well behind
    Large equipment makers. No competitor is ahead of you on both axes. Nearest competitor: Aigen,
    right next to you."

    None when the view carries no geometry (an artifact from before the scorer computed it); the
    caller then says nothing rather than falling back to the score.
    """
    if "dominated_by" not in view:
        return None
    count = view.get("competitor_count")
    total = count + 1 if isinstance(count, int) else None
    parts: list[str] = []
    for axis in ("x", "y"):
        name = short_axis_name(view.get(f"{axis}_axis_name")) or axis.upper()
        place = _place_words(view.get(f"startup_{axis}_rank"), view.get(f"startup_{axis}_tied_with"), total)
        lead = _lead_words(
            view.get(f"{axis}_lead_over_best"),
            view.get(f"{axis}_best_competitors"),
            name_by_slug,
            view.get(f"startup_{axis}_tied_with"),
        )
        if place is None:
            continue
        parts.append(f"{name}: {place}" + (f", {lead}" if lead else ""))
    if not parts:
        return None
    dominated = [s for s in _as_list(view.get("dominated_by")) if s]
    planned = view.get("scored_point") == "planned"
    sentence = ("If delivered: " if planned else "") + "; ".join(parts) + ". "
    if dominated:
        sentence += f"Ahead of you on both axes: {_names_list(dominated, name_by_slug)}."
    else:
        sentence += "No competitor is ahead of you on both axes."
    nearest = _nearest_words(view, name_by_slug)
    if nearest:
        sentence += f" {nearest}"
    if planned:
        sentence += " " + _today_words(view, total)
        sentence += " " + ASYMMETRY
    return f"{label}: {sentence}" if label else sentence


# The honest core of scoring a plan: the startup is placed at its plan, competitors at what they ship.
# Carried on every surface that states a planned position, so no reader compares plan with plan.
ASYMMETRY = "You are placed where your plan puts you; competitors are placed at what they ship today."


def _today_words(view: Mapping[str, Any], total: int | None) -> str:
    """Where the startup is today, from the scorer's `today` block only -- never a planned value.

    Unranked when there is nothing to buy: a rank there would score a guess as a measurement. When
    ranked, the plan's movement is stated per axis from the two blocks' ranks.
    """
    today = _as_dict(view.get("today"))
    if not today:
        return ""
    if not today.get("ranked"):
        return "Today: not ranked — there is no product to buy yet."
    parts: list[str] = []
    moves: list[str] = []
    for axis in ("x", "y"):
        name = short_axis_name(view.get(f"{axis}_axis_name")) or axis.upper()
        place = _place_words(today.get(f"startup_{axis}_rank"), today.get(f"startup_{axis}_tied_with"), total)
        if place is None:
            continue
        parts.append(f"{name}: {place}")
        before, after = today.get(f"startup_{axis}_rank"), view.get(f"startup_{axis}_rank")
        if isinstance(before, int) and isinstance(after, int):
            moves.append(
                f"moves you from {_ordinal(before)} to {_ordinal(after)} on {name}"
                if before != after
                else f"does not move you on {name}"
            )
    words = "Today: " + "; ".join(parts) + "." if parts else ""
    if moves:
        words += " The plan " + " and ".join(moves) + "."
    return words


def view_label(view: Mapping[str, Any]) -> str:
    """A view's name for the founder: its label, else "<X axis> vs <Y axis>".

    Never the id: real runs use slug ids ("tco_vs_distribution"), and title-casing one put
    "Tco_Vs_Distribution View" in a delivered report.
    """
    label = str(view.get("label") or "").strip()
    if label:
        return label
    x, y = short_axis_name(view.get("x_axis_name")), short_axis_name(view.get("y_axis_name"))
    if x and y:
        return f"{x} vs {y}"
    return "Positioning map"


def view_verdict(view: Mapping[str, Any], name_by_slug: Mapping[str, str] | None) -> str | None:
    """The short form for Key Findings: who beats the startup on both axes, and who is nearest."""
    if "dominated_by" not in view:
        return None
    dominated = [s for s in _as_list(view.get("dominated_by")) if s]
    out = (
        f"Ahead of you on both axes: {_names_list(dominated, name_by_slug)}."
        if dominated
        else "No competitor is ahead of you on both axes."
    )
    if view.get("scored_point") == "planned":
        out = "If delivered: " + out
    nearest = _nearest_words(view, name_by_slug)
    return f"{out} {nearest}" if nearest else out


# --- what the coach is given (D5) --------------------------------------------------------
# The coaching sub-agent reads only the payload. It had no map and no stress-test, so on both
# baseline runs it never mentioned that the pitch's headline claim failed, and one run told the
# founder "nothing in this review triggered a serious red flag". It is given the same computed
# sentences the report carries, to quote rather than to derive.

_CLAIM_VERBS = {
    "holds": "holds",
    "partially_holds": "only partly holds",
    "does_not_hold": "does not hold",
    "unproven": "is unproven",
}


def _first_sentence(text: Any, limit: int = 240) -> str:
    body = " ".join(str(text or "").split())
    if not body:
        return ""
    end = body.find(". ")
    sentence = body if end < 0 else body[: end + 1]
    if len(sentence) > limit:
        cut = sentence[:limit].rsplit(" ", 1)[0].rstrip(",;:")
        sentence = cut + "…"
    return sentence


def claim_sentences(positioning_scores: Mapping[str, Any] | None) -> list[str]:
    """One sentence per stress-tested pitch claim: the claim, its verdict, and -- when it does not
    fully hold -- the first sentence of the evidence, so the coach has something to address."""
    out: list[str] = []
    for claim in _as_list(_as_dict(positioning_scores).get("differentiation_claims")):
        claim = _as_dict(claim)
        text = " ".join(str(claim.get("claim") or "").split())
        verb = _CLAIM_VERBS.get(str(claim.get("verdict") or ""))
        if not text or verb is None:
            continue
        sentence = f'Your claim "{text}" {verb}.'
        if claim.get("verdict") != "holds":
            evidence = _first_sentence(claim.get("evidence"))
            if evidence:
                sentence += f" {evidence}"
        out.append(sentence)
    return out


def map_sentences(positioning_scores: Mapping[str, Any] | None, name_by_slug: Mapping[str, str] | None) -> list[str]:
    """One sentence per positioning map, named -- the same sentences the report shows."""
    out: list[str] = []
    for view in _as_list(_as_dict(positioning_scores).get("views")):
        view = _as_dict(view)
        sentence = view_sentence(view, name_by_slug, view_label(view))
        if sentence:
            out.append(sentence)
    return out


# --- a direct competitor displaced at the cap --------------------------------------------
# The set holds at most MAX_COMPETITORS (validate_landscape.py). A baseline-era run left research's
# DIRECT additions out because the set was full, while a competitor the verification pass judged
# `not_a_competitor` kept its slot. The suggestions are read from the run's FIRST landscape as
# well as the final one: the merge before the final pipe is model-written, and dropping a declined
# suggestion there must not be what clears this.
MAX_COMPETITORS = 10


def displaced_direct(
    landscape: Mapping[str, Any] | None,
    first_landscape: Mapping[str, Any] | None,
    verdicts: Iterable[tuple[str, str]],
) -> tuple[list[tuple[str, str]], list[str]]:
    """([(slug, name)] of direct suggestions left out, [slugs] of not-a-competitor entries kept).

    Both lists are empty unless the set is full and both kinds exist.
    """
    scored = final_slugs(landscape)
    if len(scored) < MAX_COMPETITORS:
        return [], []
    kept_non = [slug for slug, verdict in verdicts if verdict == "not_a_competitor" and slug in scored]
    if not kept_non:
        return [], []
    left_out: dict[str, str] = {}
    for source in (first_landscape, landscape):
        for entry in _as_list(_as_dict(source).get("suggested_additions")):
            entry = _as_dict(entry)
            slug, name = str(entry.get("slug") or ""), str(entry.get("name") or "").strip()
            if slug and entry.get("category") == "direct" and slug not in scored:
                left_out.setdefault(slug, name or slug)
    if not left_out:
        return [], []
    return sorted(left_out.items()), kept_non


def claims_tally(positioning_scores: Mapping[str, Any] | None) -> str | None:
    """ "Differentiation claims: 2 hold, 1 partially holds, 1 does not hold, 1 unproven (of 5 tested)."

    From the scorer's `verdict_counts`, so the parts always sum to the total. None when nothing was
    tested or the artifact predates the tally.
    """
    counts = _as_dict(_as_dict(positioning_scores).get("verdict_counts"))
    total = counts.get("total")
    if not isinstance(total, int) or total <= 0:
        return None
    parts = [
        f"{counts.get('holds', 0)} hold",
        f"{counts.get('partially_holds', 0)} partially hold",
        f"{counts.get('does_not_hold', 0)} do not hold",
    ]
    if counts.get("unproven"):
        parts.append(f"{counts['unproven']} unproven")
    if counts.get("unrecognised"):
        parts.append(f"{counts['unrecognised']} with no recognised verdict")
    return f"Differentiation claims: {', '.join(parts)} (of {total} tested)."


# --- what public records show about the startup (step 5) ----------------------------------
# From startup_research.json (validate_startup_research.py). The status words are the producer's
# COMPUTED status, never text the research pass wrote. The run's FIRST copy is the record shown;
# a later copy that disagrees is listed, not substituted. Every publication carries its source,
# because the record itself came from search results and freezing it does not verify it.

FIRST_STARTUP_RESEARCH = "startup_research.json.first.json"

_STATUS_WORDS = {
    "granted": "granted",
    "published": "published application, no grant found",
    "unknown": "status not established",
}
FAMILY_WORDS = {
    "granted": "at least one patent in the family is granted",
    "published": "published applications only; no grant was found",
    "unknown": "filings found, but their status could not be established",
    "none_found": "no patent filings were found",
}


def publication_rows(research: Mapping[str, Any] | None) -> list[dict[str, str]]:
    """One row per publication: number, office, status words, what was read, source."""
    rows: list[dict[str, str]] = []
    for pub in _as_list(_as_dict(research).get("publications")):
        pub = _as_dict(pub)
        status = _STATUS_WORDS.get(str(pub.get("status")), "status not established")
        if pub.get("grant_event"):
            dates = [str(_as_dict(e).get("date") or "") for e in _as_list(pub.get("events"))]
            when = next((d for d in dates if d), "")
            status += f"; a grant in a national office is recorded{f' ({when})' if when else ''}"
        rows.append(
            {
                "number": str(pub.get("number") or ""),
                "office": str(pub.get("office") or ""),
                "status": status,
                "read": str(pub.get("read") or "none").replace("_", " "),
                "source": str(pub.get("source") or ""),
            }
        )
    return rows


def startup_record_sentences(research: Mapping[str, Any] | None) -> list[str]:
    """The record as sentences, for the coach: quoted, never restated."""
    research = _as_dict(research)
    if not research:
        return []
    out: list[str] = []
    legal = _as_dict(research.get("legal_name"))
    if _as_dict(legal).get("value"):
        out.append(f"Registered legal name: {legal['value']}.")
    family = FAMILY_WORDS.get(str(research.get("family_status")))
    if family:
        out.append(f"Patents: {family}.")
    for row in publication_rows(research):
        out.append(f"{row['number']} ({row['office']}): {row['status']}.")
    return out


def record_disagreements(first: Mapping[str, Any] | None, current: Mapping[str, Any] | None) -> list[str]:
    """Publications whose status in a later record differs from the run's first record."""
    before = {r["number"]: r["status"] for r in publication_rows(first)}
    out: list[str] = []
    for row in publication_rows(current):
        if row["number"] in before and before[row["number"]] != row["status"]:
            out.append(
                f"{row['number']}: first recorded as {before[row['number']]}; a later record says {row['status']}"
            )
        elif row["number"] not in before and before:
            out.append(f"{row['number']}: not in the first record; a later record says {row['status']}")
    return out


# --- what is shown and what is claimed (step 6) --------------------------------------------
# For a planned position: per map and axis, how far each claim behind it has been shown, with the
# analysis's quote, plus the pitch claims that do not fully hold. Proof levels are the analysis's own
# judgement, so this is a disclosure, not a check.

# Spelled out for the dispatch-drift test, which finds consumers by literal name.
_PROOF_QUOTE_FIELD = {"x": "x_proof_quote", "y": "y_proof_quote"}
_PROOF_WORDS = {
    "shipping": "shipping today",
    "customer_validated": "validated by customers",
    "demonstrated": "demonstrated (prototype, pilot or trial)",
    "claimed": "claimed, not yet shown",
}
_AVAILABILITY_WORDS = {
    "concept": "a concept",
    "poc": "a proof of concept",
    "pilot": "in pilots",
    "shipping": "shipping",
}


def proof_gap(positioning_scores: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Rows for the proof-gap section, or None when no map scores a plan."""
    scores = _as_dict(positioning_scores)
    rows: list[dict[str, str]] = []
    for view in _as_list(scores.get("views")):
        view = _as_dict(view)
        if view.get("scored_point") != "planned":
            continue
        startup = next(
            (_as_dict(p) for p in _as_list(view.get("points")) if _as_dict(p).get("competitor") == "_startup"), {}
        )
        for axis in ("x", "y"):
            level = startup.get(f"{axis}_proof")
            rows.append(
                {
                    "map": view_label(view),
                    "axis": short_axis_name(view.get(f"{axis}_axis_name")) or axis.upper(),
                    "proof": _PROOF_WORDS.get(str(level), "not stated"),
                    "quote": str(startup.get(_PROOF_QUOTE_FIELD[axis]) or ""),
                }
            )
    if not rows:
        return None
    availability = scores.get("product_availability")
    return {
        "availability": _AVAILABILITY_WORDS.get(str(availability)) if availability else None,
        "availability_quote": str(scores.get("availability_quote") or ""),
        "rows": rows,
        "open_claims": [s for s in claim_sentences(scores) if " holds." not in s or "partly" in s],
    }


# --- the verdict: the report's own summary, for the hand-over (step 7) --------------------------
# The paragraph the closing message carries, so the model has nothing to summarise in chat. Built
# only from computed facts: each map's sentence, the pitch-claim tally and the claims that do not
# hold, defensibility, and the patent record. The asymmetry is stated once, however many maps.


def verdict(
    positioning_scores: Mapping[str, Any] | None,
    moat_scores: Mapping[str, Any] | None,
    startup_research: Mapping[str, Any] | None,
    name_by_slug: Mapping[str, str] | None,
    redteam: Mapping[str, Any] | None = None,
    skip_reason: str | None = None,
) -> str | None:
    """The report's verdict paragraph, or None when there is no scored map to state. It ends with the
    outside review's sentence when the review raised a serious challenge or did not run."""
    maps = [s.replace(" " + ASYMMETRY, "") for s in map_sentences(positioning_scores, name_by_slug)]
    if not maps:
        return None
    parts = list(maps)
    if any(_as_dict(v).get("scored_point") == "planned" for v in _as_list(_as_dict(positioning_scores).get("views"))):
        parts.append(ASYMMETRY)
    tally = claims_tally(positioning_scores)
    if tally:
        parts.append(tally)
    parts.extend(s for s in claim_sentences(positioning_scores) if " does not hold." in s)
    startup = _as_dict(_as_dict(_as_dict(moat_scores).get("companies")).get("_startup"))
    defensibility = startup.get("overall_defensibility")
    if isinstance(defensibility, str) and defensibility:
        parts.append(f"Overall defensibility: {defensibility.replace('_', ' ')}.")
    family = FAMILY_WORDS.get(str(_as_dict(startup_research).get("family_status")))
    if family:
        parts.append(f"Public patent records: {family}.")
    review = review_for_verdict(redteam, skip_reason)
    if review:
        parts.append(review)
    return " ".join(parts)


def report_verdict(report: Mapping[str, Any] | None, *sources: Mapping[str, Any] | None) -> str | None:
    """The verdict compose wrote into report.json, for a page to open with. The pages print this string
    rather than building their own, so report.md, both pages and the hand-over carry the same words. None
    when the report belongs to another run than any of `sources` (the artifacts the verdict is built
    from): a report left by an earlier run must not lead this run's pages."""
    rep = _as_dict(report)
    verdict_text = rep.get("verdict")
    run_id = _as_dict(rep.get("metadata")).get("run_id")
    if not isinstance(verdict_text, str) or not verdict_text.strip() or not isinstance(run_id, str) or not run_id:
        return None
    for src in sources:
        rid = _as_dict(_as_dict(src).get("metadata")).get("run_id")
        if isinstance(rid, str) and rid and rid != run_id:
            return None
    return verdict_text.strip()


# --- The outside review (RED_TEAM) ------------------------------------------------------------------
#
# What the report, the page, the verdict and the coach say about the review is decided here, once. The
# review passed in is always the one `_cp_redteam_copy.resolve` chose -- its append-only copy, never
# `redteam.json` as it now stands.

# The recorded reason, never a generic absence: "you asked us not to" and "we tried and could not" are
# different disclosures. Keys are `_cp_redteam_copy.SKIP_REASONS`.
SKIP_SENTENCES: dict[str, str] = {
    "founder_declined": (
        "No outside review ran, because you asked us not to run one. Nothing in this report has been "
        "checked by a reviewer trying to contradict it."
    ),
    "dispatch_failed": (
        "An outside review was attempted and did not complete, so nothing in this report has been checked "
        "by a reviewer trying to contradict it. This is a gap in the process, not a finding about your "
        "position; it is worth re-running."
    ),
    "no_network_available": (
        "No outside review ran, because this run had no access to outside sources. Nothing here has been "
        "checked against published material that might contradict it."
    ),
    "no_subagent_dispatch": (
        "No outside review ran, because this environment runs the whole analysis as a single agent and "
        "cannot dispatch a separate reviewer. Nothing here has been checked by a reviewer trying to "
        "contradict it."
    ),
}
_INTERNAL_PROVENANCE = "internal:analysis"
SEVERITY_WORDS = {"high": "Serious", "medium": "Moderate", "low": "Minor"}
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def review_findings(redteam: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """The review's accepted findings, most serious first."""
    found = [f for f in _as_list(_as_dict(redteam).get("findings")) if isinstance(f, dict)]
    return sorted(found, key=lambda f: _SEVERITY_ORDER.get(str(f.get("severity")), 3))


def review_outcome(redteam: Mapping[str, Any] | None, skip_reason: str | None) -> str | None:
    """The ONE sentence for what the outside review found, said the same way everywhere it appears.

    None only when there is nothing to say: no review for this run and no recorded reason (a run from
    before the step existed)."""
    if redteam is None:
        return SKIP_SENTENCES.get(skip_reason or "")
    findings = review_findings(redteam)
    rejected = int(_as_dict(redteam.get("summary")).get("rejected") or 0)
    if not findings:
        if rejected:
            noun = "challenge" if rejected == 1 else "challenges"
            return f"An outside review raised {rejected} {noun} against this analysis but could evidence none of them."
        return "An outside review ran against this analysis and found nothing it could evidence."
    n = len(findings)
    serious = sum(1 for f in findings if f.get("severity") == "high")
    noun = "challenge" if n == 1 else "challenges"
    tail = f", {serious} of them serious" if serious and n > 1 else (", a serious one" if serious else "")
    return f"An outside review raised {n} {noun} to this analysis that it could evidence{tail}."


def review_for_verdict(redteam: Mapping[str, Any] | None, skip_reason: str | None) -> str | None:
    """The review's sentence for the verdict paragraph: when it raised a serious challenge, or when none
    ran. A review that found only minor points is in the report, not the headline."""
    if redteam is None:
        return SKIP_SENTENCES.get(skip_reason or "")
    if any(f.get("severity") == "high" for f in review_findings(redteam)):
        outcome = review_outcome(redteam, None)
        return f"{outcome} Read them before relying on the positions above." if outcome else None
    return None


def review_source(finding: Mapping[str, Any]) -> dict[str, str]:
    """Where a finding's sentence came from, for a renderer: `kind` is `link`, `document` or `internal`.

    An internal finding is labelled, never linked: an outside source contradicting a placement and the
    analysis contradicting itself are both worth knowing and are not interchangeable. The founder's own
    page is named, never linked, with whether the quoted sentence was found on it.
    """
    url = str(finding.get("source_url") or "").strip()
    title = str(finding.get("source_title") or "").strip()
    if url == _INTERNAL_PROVENANCE:
        return {"kind": "internal", "text": "from this analysis's own output, not an outside source", "url": ""}
    if url.startswith("document:"):
        m = re.match(r"^document:([^#]+)(?:#page=(\d+))?$", url)
        where = (f"{m.group(1)}, page {m.group(2)}" if m.group(2) else m.group(1)) if m else url[len("document:") :]
        verified = finding.get("quote_verified")
        note = (
            ""
            if verified is True
            else " (this sentence was not found on that page)"
            if verified is False
            else " (quoted from a page that could not be machine-read)"
        )
        return {"kind": "document", "text": f"your document {where}{note}", "url": ""}
    return {"kind": "link", "text": title or url, "url": url}


def review_sentences(redteam: Mapping[str, Any] | None, skip_reason: str | None) -> list[str]:
    """For the coach: the outcome, then one sentence per finding, most serious first. The same words the
    report shows, so the coach quotes the review instead of characterising it."""
    outcome = review_outcome(redteam, skip_reason)
    out = [outcome] if outcome else []
    for f in review_findings(redteam):
        sev = SEVERITY_WORDS.get(str(f.get("severity")), "")
        claim = str(f.get("claim_attacked") or "").strip()
        truth = str(f.get("what_is_true") or "").strip()
        out.append(f"{sev}: {claim}. {truth}".strip())
    return out
