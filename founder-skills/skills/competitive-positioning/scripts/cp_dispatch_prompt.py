#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Print the MOAT_SCORING, POSITIONING_SCORING, CHECKLIST, STARTUP_RESEARCH and RED_TEAM dispatch prompts
from identifiers.

The main thread runs this and sends the printed text as the sub-agent's prompt, unchanged. It used
to copy each template out of SKILL.md and fill it in by hand, and a hand-filled prompt is where
instructions nobody chose get added: a run that applied a review's advice did it by writing new
scoring rules into these prompts. Printing from identifiers alone -- paths, run id, scoring basis,
and the job to be done the verification pass recorded -- leaves nothing to write in. The shared
PreToolUse hook (founder-skills/scripts/dispatch_prompt_check.py) holds a dispatch that differs from
the printed prompt for its OUTPUT_PATH; SKILL.md does not depend on it.

Every prompt ends with the hook's closing line, "Do NOT write any file other than OUTPUT_PATH.",
which is how the hook finds where a printed prompt ends.

Usage:
    python cp_dispatch_prompt.py moat_scoring --run-id R --handoff-agent H --analysis-dir-agent A \
        --plugin-root-agent P
    python cp_dispatch_prompt.py positioning_scoring ... --scoring-basis shipped --analysis-dir D
    python cp_dispatch_prompt.py checklist ...
    python cp_dispatch_prompt.py red_team ... --analysis-dir D --handoff-dir H_SHELL

Exit 2 when a required argument is missing, or (red_team) when the analysis is not finished.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

# The first line of each prompt, as its own literal: the hook and the dispatch-contract test read it.
_MOAT_SCORING_CONTEXT = "CONTEXT: MOAT_SCORING"
_POSITIONING_SCORING_CONTEXT = "CONTEXT: POSITIONING_SCORING"
_CHECKLIST_CONTEXT = "CONTEXT: CHECKLIST"

_MOAT_SCORING_TEMPLATE = (
    _MOAT_SCORING_CONTEXT + "\n"
    "OUTPUT_PATH: <HANDOFF_AGENT>/moat_scoring_output.json\n"
    "RUN_ID: <RUN_ID>\n"
    "\n"
    "You are the competitive-positioning agent dispatched in Context A (MOAT_SCORING).\n"
    "Read positioning.json at <ANALYSIS_DIR_AGENT>/positioning.json, landscape.json at\n"
    "<ANALYSIS_DIR_AGENT>/landscape.json, and product_profile.json at\n"
    "<ANALYSIS_DIR_AGENT>/product_profile.json. You are scoring _startup among the others, and\n"
    "product_profile.json is the ONLY source for what the startup actually does — positioning.json's\n"
    "pre-dispatch block carries placeholder evidence, so without it you would be scoring the startup\n"
    "from nothing.\n"
    "\n"
    "If a reference path below is refused, read the same file under the plugin folder your own instructions name.\n"
    "Score every slug (including _startup) across the 6 canonical moat dimensions from\n"
    "<PLUGIN_ROOT_AGENT>/skills/competitive-positioning/references/moat-definitions.md:\n"
    "network_effects, data_advantages, switching_costs, regulatory_barriers,\n"
    "cost_structure, brand_reputation.\n"
    "\n"
    "Each moat: status (strong/moderate/weak/absent/not_applicable), evidence (required),\n"
    "evidence_source (researched/agent_estimate/founder_provided), trajectory\n"
    "(building/stable/eroding).\n"
    "\n"
    "Those six are the comparison grid, not the whole vocabulary. You may ALSO add a\n"
    "`custom_{slug}` moat when a real, evidenced form of defensibility does not fit any of them —\n"
    "see the Custom Moat Types table in moat-definitions.md. Distribution is the case that keeps\n"
    "arising: a named partner or reseller covering a large share of the addressable market is\n"
    "defensibility, and it is NOT a network effect. Recording it as `network_effects: absent`\n"
    "because channel leverage does not make the product better with scale is correct reasoning\n"
    "that throws the finding away; use `custom_distribution_channel` instead. A custom moat needs\n"
    "the same evidence quality as a canonical one, and it reaches the founder's report — it does\n"
    "not appear on the six-axis radar, which stays canonical so companies remain comparable.\n"
    "\n"
    "trajectory is a DIFFERENT enum from status — it is one of building/stable/eroding only. Never write\n"
    "a status value (strong/moderate/weak/absent/not_applicable) into trajectory: the producer rejects it\n"
    "and the whole file comes back for repair, costing a round-trip.\n"
    "\n"
    "For trajectory and any moat where landscape.json evidence is thin, use WebSearch\n"
    "to find recent (last 12 months) signals — funding rounds, M&A, hiring, executive\n"
    'changes, patent filings, product launches. Stamp evidence_source: "researched"\n'
    "only when the signal came from a WebSearch result. Whenever you stamp\n"
    'evidence_source: "researched", also add a "source" field on that same moat\n'
    "entry — the URL or the exact search query that produced the signal. The main\n"
    "thread never sees your WebSearch results, only this artifact, so an unsourced\n"
    '"researched" claim (e.g. a dated funding/M&A event) can\'t be spot-checked\n'
    'later. score_moats.py warns (does not fail) on a "researched" moat with no\n'
    '"source".\n'
    "\n"
    "Use your Write tool to write to OUTPUT_PATH — exactly the shape expected by\n"
    "score_moats.py:\n"
    "{\n"
    '  "moat_assessments": {\n'
    '    "_startup": {"moats": [{"id": "...", "status": "...", "evidence": "...",\n'
    '      "evidence_source": "researched", "source": "https://... OR the exact search query used",\n'
    '      "trajectory": "..."}]},\n'
    '    "<slug>": {"moats": [...]},\n'
    "    ...\n"
    "  },\n"
    '  "metadata": {"run_id": "<RUN_ID>"}\n'
    "}\n"
    "Then return ONLY the receipt JSON in your final assistant message:\n"
    '{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}\n'
    "You never write a canonical artifact; anything else you write bypasses schema\n"
    "validation and run_id stamping.\n"
    "Do NOT write any file other than OUTPUT_PATH.\n"
)

_POSITIONING_SCORING_TEMPLATE = (
    _POSITIONING_SCORING_CONTEXT + "\n"
    "OUTPUT_PATH: <HANDOFF_AGENT>/positioning_scoring_output.json\n"
    "RUN_ID: <RUN_ID>\n"
    "SCORING_BASIS: <SCORING_BASIS>\n"
    "\n"
    "You are the competitive-positioning agent dispatched in Context A (POSITIONING_SCORING).\n"
    "Read positioning.json at <ANALYSIS_DIR_AGENT>/positioning.json and product_profile.json at\n"
    "<ANALYSIS_DIR_AGENT>/product_profile.json (the only source for what the startup actually does —\n"
    "you are placing _startup on the map alongside researched competitors).\n"
    "<JOB_TO_BE_DONE>\n"
    "Set each axis's `polarity` to say which END IS GOOD. Default `higher_is_better`; use\n"
    "`lower_is_better` whenever a LOW number is the desirable one — price, total cost of ownership,\n"
    'friction, latency, time-to-value, switching effort. This is not cosmetic: rank 1 means "best",\n'
    "and it feeds the differentiation score. Get it wrong on a price axis and the founder is told they\n"
    "rank last while being the second-cheapest in the set, with the score rewarding being expensive.\n"
    "If an axis genuinely has no good end, phrase it so it does, or leave the default.\n"
    "\n"
    'Position every competitor and _startup according to SCORING_BASIS: "shipped" means\n'
    'score only what is live and verifiable today, ignoring roadmap claims; "roadmap_12mo"\n'
    'means score the startup\'s stated 12-month roadmap as if already delivered; "mixed"\n'
    "means score today's shipped surface, but call out roadmap-only capabilities\n"
    "separately in the evidence text rather than folding them into the coordinate. A\n"
    'startup that ranks low under "shipped" because its stack is still roadmap is a\n'
    "finding about stage, not a defect — say so in the evidence, don't just place the dot.\n"
    "\n"
    "Where the startup's pitch goes beyond what it ships today, ALSO record where its plan puts it:\n"
    "planned_x / planned_y on the _startup point (0-100, same axes), with planned_x_evidence and\n"
    "planned_y_evidence. x / y stay where it is TODAY -- never put a planned value in them. For each axis\n"
    "give x_proof / y_proof, how far the claim behind the planned position has been shown (shipping,\n"
    "customer_validated, demonstrated or claimed), with x_proof_quote / y_proof_quote quoting the\n"
    'material that shows it. The planned point is the one scored, labelled "if delivered"; competitors\n'
    "stay at what they ship today.\n"
    "\n"
    "For each view in positioning.json, assign coordinates (0-100) for every competitor\n"
    "and _startup on both axes. Every point needs x_evidence, y_evidence, and provenance.\n"
    "Assess differentiation claims: verifiable (boolean), evidence, challenge, verdict\n"
    "(holds/partially_holds/does_not_hold/unproven).\n"
    "\n"
    'The axes themselves drive the search queries — when an axis is "customer support\n'
    'depth" or "pricing transparency," issue WebSearch queries targeting that specific\n'
    "dimension per competitor. Stamp x_evidence_source / y_evidence_source as\n"
    '"researched" only when the coordinate came from a WebSearch result. For each\n'
    "differentiation_claim, use WebSearch to find supporting or contradicting evidence\n"
    "before assigning a verdict.\n"
    "\n"
    "Use your Write tool to write to OUTPUT_PATH — exactly the shape expected by\n"
    "score_positioning.py:\n"
    "{\n"
    '  "scoring_basis": "<echo of SCORING_BASIS>",\n'
    '  "views": [\n'
    "    {\n"
    '      "id": "...", "x_axis": {"name": "...", "rationale": "...", '
    '"polarity": "higher_is_better|lower_is_better"},\n'
    '      "y_axis": {"name": "...", "rationale": "...", "polarity": "higher_is_better|lower_is_better"},\n'
    '      "points": [\n'
    '        {"competitor": "...", "x": 0-100, "y": 0-100,\n'
    '         "x_evidence": "...", "y_evidence": "...",\n'
    '         "x_evidence_source": "researched|agent_estimate",\n'
    '         "y_evidence_source": "researched|agent_estimate",\n'
    '         "planned_x": 0-100, "planned_y": 0-100, "planned_x_evidence": "...", "planned_y_evidence": "...",\n'
    '         "x_proof": "shipping|customer_validated|demonstrated|claimed", "y_proof": "...",\n'
    '         "x_proof_quote": "...", "y_proof_quote": "..."}\n'
    "         (the planned_* and *_proof fields on _startup only, when there is a plan)\n"
    "      ]\n"
    "    }\n"
    "  ],\n"
    '  "differentiation_claims": [...],\n'
    '  "metadata": {"run_id": "<RUN_ID>"}\n'
    "}\n"
    "Then return ONLY the receipt JSON in your final assistant message:\n"
    '{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}\n'
    "You never write a canonical artifact; anything else you write bypasses schema\n"
    "validation and run_id stamping.\n"
    "Do NOT write any file other than OUTPUT_PATH.\n"
)

_CHECKLIST_TEMPLATE = (
    _CHECKLIST_CONTEXT + "\n"
    "OUTPUT_PATH: <HANDOFF_AGENT>/checklist_output.json\n"
    "RUN_ID: <RUN_ID>\n"
    "\n"
    "You are the competitive-positioning agent dispatched in Context A (CHECKLIST).\n"
    "If a reference path below is refused, read the same file under the plugin folder your own instructions name.\n"
    "Read landscape.json, positioning.json, moat_scores.json, positioning_scores.json,\n"
    "product_profile.json, and landscape_draft.json from <ANALYSIS_DIR_AGENT>. Also read\n"
    "<PLUGIN_ROOT_AGENT>/skills/competitive-positioning/references/checklist-criteria.md.\n"
    "product_profile.json's deck_competition_slide field (deck mode) and\n"
    "landscape_draft.json's deck_competitors_excluded field are what the\n"
    "competition-slide cross-check item (NARR_03) needs — without them it has\n"
    "nothing to grade. When deck_competition_slide.present is false (the deck had\n"
    "no competition slide at all), that IS a concrete answer — grade NARR_03 **warn**,\n"
    "never not_applicable, using the stated reason as your evidence and saying plainly\n"
    "that the deck names no competitor. not_applicable would drop the item out of the\n"
    "score denominator, inflating the score while hiding the finding, and a deck that\n"
    "never engages competition is one of the strongest findings this review returns.\n"
    'Do not treat the field\'s absence as "nothing to grade" once a present:false\n'
    "record with a reason exists. references/checklist-criteria.md's NARR_03 bands are\n"
    "the authority.\n"
    "\n"
    "Assess all 25 checklist items (COVER_01..05, POS_01..05, MOAT_01..04,\n"
    "EVID_01..04, NARR_01..04, MISS_01..03). Mode-based gating applies: when\n"
    "input_mode is conversation, research-dependent items auto-gate to not_applicable.\n"
    "\n"
    "Evidence is MANDATORY for every item: every fail and warn MUST have a non-empty\n"
    "evidence string citing specific findings. Every pass MUST have evidence noting\n"
    "what was checked.\n"
    "\n"
    "Evidence prints VERBATIM in the founder's report, so name the source the way the\n"
    "founder knows it — never by our filename. They never saw `landscape.json` or\n"
    "`moat_scores.json`; they saw their deck and the competitors in it.\n"
    '  Instead of: "landscape.json reports input_mode: deck"\n'
    '  Write:      "the deck names three competitors and no others"\n'
    '  Instead of: "moat_scores.json shows switching_costs weak"\n'
    '  Write:      "switching costs are weak — customers can leave in a day"\n'
    "State what is true of the COMPANY or its competitive set. The delivery gate\n"
    "flags an internal filename in evidence, so this is checked.\n"
    "\n"
    "**Copy each criterion's label verbatim into `criterion`.** It is a cross-check, not decoration:\n"
    "the label you are shown and the evidence you write are joined by `id` downstream, so if the id\n"
    "and the criterion you actually graded drift apart, a founder reads a real criterion above a\n"
    'justification for a different one — measured on real runs, e.g. "Do-nothing / status quo\n'
    'included" carrying evidence about how many direct competitors were named. Echoing the label is\n'
    "what makes that detectable. Grade the criterion you name.\n"
    "\n"
    "Use your Write tool to write to OUTPUT_PATH — the items array without a\n"
    "summary (the producer script computes the summary):\n"
    '{"items": [{"id": "COVER_01", "criterion": "<the criterion label, copied verbatim>", '
    '"status": "pass", "evidence": "...", "notes": "..."}, ...all 25 items...]}\n'
    "Then return ONLY the receipt JSON in your final assistant message:\n"
    '{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}\n'
    "You never write a canonical artifact; anything else you write bypasses schema\n"
    "validation and run_id stamping.\n"
    "Do NOT write any file other than OUTPUT_PATH.\n"
)

_STARTUP_RESEARCH_CONTEXT = "CONTEXT: STARTUP_RESEARCH"
# The startup's own public record. A real run called a granted patent family "pending" because
# nothing looked it up. The sub-agent records what it found and where; validate_startup_research.py
# computes every status, so none is asked for here.
_STARTUP_RESEARCH_TEMPLATE = (
    _STARTUP_RESEARCH_CONTEXT + "\n"
    "OUTPUT_PATH: <HANDOFF_AGENT>/startup_research_output.json\n"
    "RUN_ID: <RUN_ID>\n"
    "\n"
    "You are the competitive-positioning agent dispatched in Context A (STARTUP_RESEARCH).\n"
    "Read product_profile.json at <ANALYSIS_DIR_AGENT>/product_profile.json for the company name, its\n"
    "founders and its claims. Research the STARTUP's own public record with WebSearch -- not competitors.\n"
    "\n"
    "Search, and record every search you run, including the ones that find nothing:\n"
    "1. A company registry for the startup's registered legal name (kind: registry).\n"
    "2. Each named founder as a patent inventor (kind: inventor).\n"
    "3. The legal name, and the trading name, as a patent applicant (kind: applicant).\n"
    "4. Each publication number you find, to reach the rest of its family (kind: publication).\n"
    "5. Each publication's legal status or legal events (kind: status).\n"
    "\n"
    "Record facts, not conclusions. For each publication give its number, office and kind code exactly\n"
    "as the source shows them, the legal events the source lists (code and date), what you actually read\n"
    "(none / abstract / claims / full_text), and the source: the URL, or the exact query that surfaced it.\n"
    "Do not write a status such as granted or pending: the producer computes it from the kind code and\n"
    "events. Do not include a publication you did not see in a result; a missing record is reported as a\n"
    "search with found: false, never guessed.\n"
    "\n"
    "Use your Write tool to write to OUTPUT_PATH -- exactly this shape:\n"
    "{\n"
    '  "legal_name": {"value": "<registered name, or null if not found>", "source": "<URL or query>"},\n'
    '  "searches": [{"query": "...", "kind": "registry|inventor|applicant|publication|status|other",\n'
    '                "found": true}],\n'
    '  "publications": [{"number": "...", "office": "...", "kind": "...", "title": "...",\n'
    '                    "events": [{"code": "...", "date": "YYYY-MM-DD"}],\n'
    '                    "read": "none|abstract|claims|full_text", "source": "<URL or query>"}],\n'
    '  "metadata": {"run_id": "<RUN_ID>"}\n'
    "}\n"
    "Then return ONLY the receipt JSON in your final assistant message:\n"
    '{"status": "complete", "output_path": "<echo of OUTPUT_PATH>"}\n'
    "You never write a canonical artifact; anything else you write bypasses schema\n"
    "validation and run_id stamping.\n"
    "Do NOT write any file other than OUTPUT_PATH.\n"
)

# A corrective redo re-sends the same prompt with one line added. The lines are a closed set, printed
# here, so a redo is also a printed prompt and nothing is typed into it. (A repair dispatch -- a bad file,
# a wrong path, a producer rejection -- is a different prompt that does not open with a context line, and
# is not generated.) The line is placed before the closing line, which must stay last.
CORRECTIONS = {
    "missing-file": (
        "Your previous receipt claimed a file at OUTPUT_PATH but none exists; use Write to create exactly that path."
    ),
    "receipt-only": "Return ONLY the receipt JSON -- no fences, no prose.",
}

_TEMPLATES = {
    "moat_scoring": _MOAT_SCORING_TEMPLATE,
    "positioning_scoring": _POSITIONING_SCORING_TEMPLATE,
    "checklist": _CHECKLIST_TEMPLATE,
    "startup_research": _STARTUP_RESEARCH_TEMPLATE,
}
SCORING_BASES = ("shipped", "roadmap_12mo", "mixed")
# The hook's closing line (founder-skills/scripts/dispatch_prompt_check.py END); it ends every prompt.
_END = "Do NOT write any file other than OUTPUT_PATH.\n"
for _name, _text in _TEMPLATES.items():
    assert _text.endswith(_END), f"{_name} must end with the hook's closing line"


def job_to_be_done(analysis_dir: str | None) -> str | None:
    """The startup's job to be done as the verification pass characterised it, if it ran."""
    if not analysis_dir:
        return None
    try:
        with open(os.path.join(analysis_dir, "competitor_verification.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    chars = data.get("startup_characterization") if isinstance(data, dict) else None
    job = chars.get("job_to_be_done") if isinstance(chars, dict) else None
    return " ".join(job.split()) if isinstance(job, str) and job.strip() else None


def render(
    context: str,
    *,
    run_id: str,
    handoff_agent: str,
    analysis_dir_agent: str,
    plugin_root_agent: str,
    scoring_basis: str = "shipped",
    job: str | None = None,
    correction: str | None = None,
) -> str:
    """The prompt for `context`, placeholders filled. No free text reaches it but the recorded job."""
    text = _TEMPLATES[context]
    # The job is placed where the scorer decides how well each competitor serves the startup's buyer:
    # a run credited unrelated shipping products on readiness because scoring never saw the job.
    job_line = (
        f"The startup's job to be done, as the verification pass characterised it: {job} "
        "Place each competitor by how well it serves THIS job, not by how good its own product is.\n"
        if job
        else ""
    )
    if correction is not None:
        text = text.replace(_END, f"{CORRECTIONS[correction]}\n{_END}")
    return (
        text.replace("<HANDOFF_AGENT>", handoff_agent.rstrip("/"))
        .replace("<ANALYSIS_DIR_AGENT>", analysis_dir_agent.rstrip("/"))
        .replace("<PLUGIN_ROOT_AGENT>", plugin_root_agent.rstrip("/"))
        .replace("<SCORING_BASIS>", scoring_basis)
        .replace("<JOB_TO_BE_DONE>", job_line)
        .replace("<RUN_ID>", run_id)
    )


# --- RED_TEAM ------------------------------------------------------------------------------------------
#
# The adversarial review of the finished analysis, dispatched to its own agent
# (competitive-positioning-redteam), whose body carries none of the scoring rubric: the review exists to
# look at the analysis without its constructor's framing. For the same reason the founder's documents
# are listed FIRST, before any of the analysis's files -- a reader who opens the analysis's reading of
# the deck before the deck inherits that reading. Unlike the other contexts this prompt is not a fixed
# template: it lists the documents actually on disk, so it needs the hand-off dir in this shell's
# namespace as well as the agent's.

_RED_TEAM_CONTEXT = "CONTEXT: RED_TEAM"
# What the review attacks. The checklist is left out on purpose: it is the analysis grading itself.
RED_TEAM_ARTIFACTS = ("product_profile.json", "landscape.json", "positioning_scores.json", "moat_scores.json")
RED_TEAM_OPTIONAL = ("startup_research.json",)
# Copy of _redteam_core.DOCUMENT_SUFFIXES and list_documents (a generator runs without the plugin's
# shared scripts on its path); tests/test_redteam_core.py pins the copy.
DOCUMENT_SUFFIXES = (".pdf", ".md", ".txt", ".docx", ".pptx", ".xlsx", ".csv")
_TEXT_LAYER_FLOOR = 100


def list_documents(uploads_dir: str | None) -> list[str]:
    """Regular files with a document suffix, sorted; dotfiles and AppleDouble `._*` excluded."""
    if not uploads_dir or not os.path.isdir(uploads_dir):
        return []
    out: list[str] = []
    for name in sorted(os.listdir(uploads_dir)):
        if name.startswith(".") or not name.lower().endswith(DOCUMENT_SUFFIXES):
            continue
        if os.path.isfile(os.path.join(uploads_dir, name)):
            out.append(name)
    return out


def _text_layer_note(path: str) -> str:
    """A note for a PDF whose pages carry no text: what the reviewer opens there is a vision read, which
    drops dense content without saying so. No machine-read copy is made for this skill, so the reviewer
    is told, and a check it could not make is reported rather than filed as "nothing found"."""
    try:
        import pdfplumber  # optional at runtime; absent means the note cannot be computed
    except ImportError:
        return "  (could not probe for a text layer)"
    try:
        with pdfplumber.open(path) as pdf:
            pages = len(pdf.pages)
            texted = sum(1 for pg in pdf.pages if len((pg.extract_text() or "").strip()) >= _TEXT_LAYER_FLOOR)
    except Exception:  # noqa: BLE001 -- an unreadable PDF is reported as unprobed, never guessed
        return "  (could not probe for a text layer)"
    if pages and texted == 0:
        return f"  (NO TEXT LAYER, {pages} pages: a vision read drops dense content silently)"
    return ""


def _where_you_stand(analysis_dir: str) -> list[str]:
    """The report's own "Where you stand" sentences (`_cp_view.map_sentences`), or [] when the map is not
    scored. A reviewer reading the raw scores alone read a planned view's today point as "the plotted
    point" and filed a false serious finding that the report's own "If delivered" line answers."""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import _cp_view

    def _load(name: str) -> dict[str, Any] | None:
        try:
            with open(os.path.join(analysis_dir, name), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    scores = _load("positioning_scores.json")
    if scores is None:
        return []
    names = _cp_view.competitor_names(_load("landscape.json"), _load("landscape_draft.json"))
    sentences: list[str] = _cp_view.map_sentences(scores, names)
    return sentences


def red_team(
    *,
    run_id: str,
    analysis_dir: str,
    handoff_dir: str,
    handoff_agent: str,
    analysis_dir_agent: str,
    correction: str | None = None,
) -> str:
    """The RED_TEAM prompt. Raises FileNotFoundError naming any required artifact that is missing."""
    missing = [f for f in RED_TEAM_ARTIFACTS if not os.path.isfile(os.path.join(analysis_dir, f))]
    if missing:
        raise FileNotFoundError(", ".join(missing))
    analysis_agent = analysis_dir_agent.rstrip("/")
    agent_root = handoff_agent.rstrip("/")
    docs_dir = os.path.join(handoff_dir, "docs")
    lines = [
        _RED_TEAM_CONTEXT,
        f"OUTPUT_PATH: {agent_root}/redteam_output.json",
        f"RUN_ID: {run_id}",
        "",
    ]
    docs = list_documents(docs_dir)
    if docs:
        lines += [
            "The founder's documents. Open every one of them, and for each claim the analysis relies on",
            "write down what the page actually says, before you open any of the analysis's files:",
        ]
        for name in docs:
            note = _text_layer_note(os.path.join(docs_dir, name)) if name.lower().endswith(".pdf") else ""
            lines.append(f"  {agent_root}/docs/{name}{note}")
        lines += [
            "",
            "Record every file you opened in sources_read. A page you could not read reliably goes in",
            "could_not_check by file and page, never reported as 'nothing found'. A claim the analysis",
            "took from a page that the page does not say is a finding whose source is that page:",
            'source_url "document:<filename>#page=<n>".',
            "",
        ]
    else:
        lines += [
            "The founder supplied no documents. Say so in could_not_check and work from the analysis's",
            "files and the web.",
            "",
        ]
    lines += ["Then read the analysis's files and attack the analysis they describe:"]
    lines += [f"  {analysis_agent}/{f}" for f in RED_TEAM_ARTIFACTS]
    lines += [f"  {analysis_agent}/{f}" for f in RED_TEAM_OPTIONAL if os.path.isfile(os.path.join(analysis_dir, f))]
    positions = _where_you_stand(analysis_dir)
    if positions:
        lines += [
            "",
            "What the report tells the founder about where they stand, computed from those files. These are",
            "the statements the founder will repeat to investors; where one is wrong, it is the one to attack:",
        ]
        lines += [f"  - {p}" for p in positions]
    lines += [
        "",
        "You are not told what to attack. The analysis is not a reliable guide to its own weaknesses,",
        "and its evidence fields are its reading of the sources, not the sources.",
        "",
        "Write your findings to OUTPUT_PATH in the shape your agent body specifies, then return ONLY",
        "the receipt JSON in your final assistant message:",
        '{"status": "complete", "output_path": "<echo of OUTPUT_PATH>", "findings": <count>}',
        _END.rstrip("\n"),
    ]
    text = "\n".join(lines) + "\n"
    if correction is not None:
        text = text.replace(_END, f"{CORRECTIONS[correction]}\n{_END}")
    return text


def _plugin_root_refusal(root: str) -> str | None:
    """Why a sub-agent could not read references under `root`, or None when it can.

    A literal `${CLAUDE_PLUGIN_ROOT}` (skill text that arrived unfilled) or an empty or relative value
    names nothing a file tool can open, and a root whose plugin.json names another plugin is a
    different plugin's folder. Only a manifest this shell can see is checked: on a host-loop session
    the root is a host path the shell cannot reach, and that is correct.
    """
    if not root.strip() or "$" in root:
        return "is empty or an unfilled placeholder"
    if not os.path.isabs(root):
        return "is not an absolute path"
    manifest = os.path.join(root, ".claude-plugin", "plugin.json")
    try:
        with open(manifest, encoding="utf-8") as fh:
            name = json.load(fh).get("name")
    except (OSError, ValueError, AttributeError):
        return None
    if name != "founder-skills":
        return f"is the folder of another plugin ({name!r})"
    return None


def main() -> None:
    p = argparse.ArgumentParser(description="Print a competitive-positioning dispatch prompt")
    p.add_argument("context", choices=sorted([*_TEMPLATES, "red_team"]))
    p.add_argument("--run-id", required=True)
    p.add_argument("--handoff-agent", required=True, help="the hand-off dir as the sub-agent addresses it")
    p.add_argument("--analysis-dir-agent", required=True, help="the artifacts dir as the sub-agent addresses it")
    p.add_argument("--plugin-root-agent", required=True, help="the plugin root as the sub-agent addresses it")
    p.add_argument("--scoring-basis", choices=SCORING_BASES, default="shipped")
    p.add_argument("--correction", choices=sorted(CORRECTIONS), help="a corrective redo's one added line")
    p.add_argument(
        "--analysis-dir",
        help="the artifacts dir in THIS shell's namespace (positioning_scoring reads the job; red_team checks it)",
    )
    p.add_argument("--handoff-dir", help="the hand-off dir in THIS shell's namespace (red_team lists its docs/)")
    a = p.parse_args()
    if a.plugin_root_agent is not None:
        why = _plugin_root_refusal(a.plugin_root_agent)
        if why:
            print(
                f"Error: --plugin-root-agent {a.plugin_root_agent!r} {why}; pass the plugin folder this skill "
                "shows, or the READ_ROOT= value Step 0 printed",
                file=sys.stderr,
            )
            sys.exit(2)
    if a.context == "positioning_scoring" and not a.analysis_dir:
        print("Error: positioning_scoring needs --analysis-dir to read the job to be done", file=sys.stderr)
        sys.exit(2)
    if a.context == "red_team":
        if not a.analysis_dir or not a.handoff_dir:
            print("Error: red_team needs --analysis-dir and --handoff-dir", file=sys.stderr)
            sys.exit(2)
        try:
            text = red_team(
                run_id=a.run_id,
                analysis_dir=a.analysis_dir,
                handoff_dir=a.handoff_dir,
                handoff_agent=a.handoff_agent,
                analysis_dir_agent=a.analysis_dir_agent,
                correction=a.correction,
            )
        except FileNotFoundError as exc:
            print(f"Error: the analysis is not finished -- missing {exc}", file=sys.stderr)
            sys.exit(2)
        sys.stdout.write(text)
        return
    sys.stdout.write(
        render(
            a.context,
            run_id=a.run_id,
            handoff_agent=a.handoff_agent,
            analysis_dir_agent=a.analysis_dir_agent,
            plugin_root_agent=a.plugin_root_agent,
            scoring_basis=a.scoring_basis,
            job=job_to_be_done(a.analysis_dir) if a.context == "positioning_scoring" else None,
            correction=a.correction,
        )
    )


if __name__ == "__main__":
    main()
