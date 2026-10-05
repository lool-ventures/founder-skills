"""The adversarial review's skill-neutral half, in ONE place: which findings may reach a founder, and
which review is shown.

Two skills dispatch a reviewer against their own finished analysis. The rules here were each learned
on a live run, and a rule with two copies drifts, so both skills load this file by path (plugin-root
`scripts/` is not a package). What stays with each skill is what differs between them: the quote
matcher and the wording of the review's prose (passed in to `validate_findings`), the parameter
names a finding may name, and what a review is taken against (`write_copy`'s `reviewed_state`).

Standard library only: a skill's producer must be able to load this from nothing but its path.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterable
from typing import Any

# --- Which findings reach a founder -----------------------------------------------------------

SEVERITIES = ("high", "medium", "low")

# The ONE non-web provenance a finding may claim: the sentence is from this run's own output.
#
# It exists because a real run produced exactly that shape -- the red team quoted the analysis'
# own comparison note back at it -- and, with only http(s) accepted, hung an unrelated external
# URL on it to get through. A link that does not contain the quote quietly breaks this step's
# whole promise, which is that every finding carries the sentence it relies on.
#
# A CLOSED single value, for the same reason the skip reason is closed: an open one lets a
# finding claim a provenance nobody can check. Exact match, case-sensitive -- "internal",
# "internal:whatever" and "INTERNAL:ANALYSIS" are all refused.
INTERNAL_PROVENANCE = "internal:analysis"

# Every field a finding must carry to reach a founder. `source_url` is the load-bearing one and
# the requirement is POSITIVE on purpose.
#
# An earlier design tried to catch the failure from the other side, with a regex refusing any
# finding that "proposes a number". Measured against real findings it failed BOTH ways: it
# accepted "closer to $X than $Y" and "N billed months rather than 12", and it REFUSED
# "the recurring rate is actually $Y on n=M" -- a correct finding quoting its source to
# correct a misread, which is the single most valuable shape this step produces. A negative
# rule over prose cannot separate those, because the difference is not in the grammar.
#
# What does separate them is whether the claim is anchored: a finding that names where its
# sentence came from can be checked by the founder, and one that cannot is an opinion no matter
# how it is phrased.
REQUIRED_FIELDS = ("claim_attacked", "what_is_true", "evidence_quote", "source_url", "source_title")

# The THIRD provenance: the founder's own page. `document:<filename>#page=<n>`, where the file
# is one the founder supplied. It exists because, with only a web address and `internal:analysis`
# accepted, a finding whose evidence is the deck itself -- "slide 8 says n=M, the analysis says
# n=N" -- had no legal source and was dropped as unsourced. The step that should catch a misread
# of a page was forbidden from citing the page. Measured on a live run: the misread was repeated.
#
# A document citation is CHECKED where it can be: against the page's text layer, else against the
# OCR sidecar a skill wrote, else it is `quote_verified: null` -- shown, and marked as not
# machine-checked. It is never rejected for being unverifiable; it IS rejected for naming a file
# the founder did not supply, or for quoting a token rather than a sentence (a three-character
# "quote" always matches something).
DOCUMENT_PREFIX = "document:"
# `#page=<n>` is REQUIRED for a paginated file and OPTIONAL otherwise: a live red team cited a
# markdown file -- which has no pages -- and the first rule, which demanded a page on every
# citation, set a real finding aside.
DOC_RE = re.compile(r"^document:([^#/\\]+)(?:#page=([1-9]\d*))?$")
PAGINATED_SUFFIXES = (".pdf", ".pptx", ".docx")
MIN_DOC_QUOTE_WORDS = 6
# Copied into each skill's dispatch-prompt generator (skill scripts cannot import this without the
# plugin); keep in step.
DOCUMENT_SUFFIXES = (".pdf", ".md", ".txt", ".docx", ".pptx", ".xlsx", ".csv")
# An `internal:analysis` quote is shown to the founder as a quotation of this analysis. A live red
# team quoted raw JSON (`"existing_claims": {"tam": 12000000000}`) -- a founder cannot read that, and
# the report must not reword a quote to make it readable. So it is set aside, per finding, with its
# reason: the sentence form exists in the analysis for anything worth quoting.
JSON_QUOTE_RE = re.compile(r'^\s*[\[{]\s*["\[{\d]|"\w+"\s*:\s*(?:[{\["\d-]|true\b|false\b|null\b)')
# The probe's per-page floor: under this, a text layer is treated as absent and the sidecar is used.
TEXT_LAYER_FLOOR = 100


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


def page_text(uploads_dir: str | None, ocr_dir: str | None, filename: str, page: int) -> str | None:
    """Text of one page: the text layer if it has one, else the OCR sidecar, else None."""
    if not uploads_dir:
        return None
    path = os.path.join(uploads_dir, filename)
    if filename.lower().endswith((".md", ".txt")):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return None
    try:
        import pdfplumber  # optional at runtime; absent means "no text layer here"

        with pdfplumber.open(path) as pdf:
            if 1 <= page <= len(pdf.pages):
                text = pdf.pages[page - 1].extract_text() or ""
                if len(text.strip()) >= TEXT_LAYER_FLOOR:
                    return text
    except Exception:  # noqa: BLE001 -- any failure here means "no text layer", never a crash
        pass
    if ocr_dir:
        sidecar = os.path.join(ocr_dir, f"{filename}.p{page}.txt")
        if os.path.isfile(sidecar):
            try:
                with open(sidecar, encoding="utf-8", errors="replace") as fh:
                    return fh.read()
            except OSError:
                return None
    return None


def reject_reason(finding: Any, documents: list[str] | None = None) -> str | None:
    """Why this ONE finding cannot be shown to a founder, or None if it can.

    Per-finding, never whole-payload. An earlier design discarded the entire hand-off when any
    finding named something absent from the artifacts -- measured against a real run, the
    "known" set is exactly the twelve parameter names the sizing math uses, and EVERY finding
    about something the analysis OMITTED is by construction outside it. That gate would have
    thrown away the most valuable findings and raised a high-severity warning while doing it.

    `claim_attacked` is therefore free text and is never checked against a vocabulary.
    """
    if not isinstance(finding, dict):
        return "not an object"
    missing = [f for f in REQUIRED_FIELDS if not str(finding.get(f) or "").strip()]
    if missing:
        return f"missing or empty: {', '.join(missing)}"
    url = str(finding["source_url"]).strip()
    doc = DOC_RE.match(url)
    if doc:
        if doc.group(1) not in (documents or []):
            return f"source_url names a document that was not supplied: {doc.group(1)}"
        if doc.group(2) is None and doc.group(1).lower().endswith(PAGINATED_SUFFIXES):
            return "a citation to a PDF must name the page: document:<filename>#page=<n>"
        if len(str(finding["evidence_quote"]).split()) < MIN_DOC_QUOTE_WORDS:
            return f"quote the sentence, not a token ({MIN_DOC_QUOTE_WORDS} words minimum for a document citation)"
    elif url.startswith(DOCUMENT_PREFIX):
        return "source_url for a document must be exactly document:<filename>#page=<n>"
    elif url == INTERNAL_PROVENANCE and JSON_QUOTE_RE.search(str(finding["evidence_quote"])):
        return "quote this analysis in its own words, as a sentence -- not as JSON from its files"
    elif url != INTERNAL_PROVENANCE and not url.lower().startswith(("http://", "https://")):
        return f"source_url must be a web address, a document citation, or exactly {INTERNAL_PROVENANCE!r}"
    severity = finding.get("severity")
    if severity not in SEVERITIES:
        return f"severity must be one of {', '.join(SEVERITIES)}"
    return None


def validate_findings(
    data: dict[str, Any],
    uploads_dir: str | None,
    ocr_dir: str | None,
    *,
    page_text: Callable[[str | None, str | None, str, int], str | None],
    quote_in_doc: Callable[[str, str], Any],
    humanize: Callable[[str, list[str]], tuple[str, int]],
    substitute: Callable[[str], str],
    prose_fields: tuple[str, ...],
    parameter_names: frozenset[str],
) -> dict[str, Any]:
    """Split the sub-agent's findings into accepted and rejected, keeping both.

    `page_text(uploads_dir, ocr_dir, filename, page)` reads the cited page -- this module's `page_text`,
    or a skill's own copy when its report checks quotes with that copy and the two must agree.
    `humanize` then `substitute` word each prose field for the founder (the skill's own wording, then
    the fleet's shared founder-text policy); `quote_in_doc(quote, text)` checks a document citation;
    a finding may name one of `parameter_names`, and any other name is dropped from it.
    """
    documents = list_documents(uploads_dir)
    humanized = 0
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for finding in data.get("findings") or []:
        reason = reject_reason(finding, documents)
        if reason is None:
            url = str(finding["source_url"]).strip()
            quote = str(finding["evidence_quote"]).strip()
            # One shape for every provenance: web and internal findings are `null` (nothing on disk
            # to check them against); a document citation is true/false when the page has text.
            quote_verified: bool | None = None
            doc = DOC_RE.match(url)
            if doc:
                text = page_text(uploads_dir, ocr_dir, doc.group(1), int(doc.group(2) or 1))
                if text is not None:
                    quote_verified = bool(quote_in_doc(quote, text)[0])
            kept: dict[str, Any] = {
                "claim_attacked": str(finding["claim_attacked"]).strip(),
                "what_is_true": str(finding["what_is_true"]).strip(),
                "evidence_quote": quote,
                "source_url": url,
                "source_title": str(finding["source_title"]).strip(),
                "severity": finding["severity"],
                "quote_verified": quote_verified,
            }
            for field in prose_fields:
                worded, n = humanize(kept[field], documents)
                humanized += n
                kept[field] = substitute(worded)
            parameter = finding.get("parameter")
            if isinstance(parameter, str) and parameter.strip() in parameter_names:
                kept["parameter"] = parameter.strip()
            accepted.append(kept)
        else:
            # Keep enough to identify it without echoing a field we just called unusable.
            label = ""
            if isinstance(finding, dict):
                label = str(finding.get("claim_attacked") or "").strip()
            rejected.append({"claim_attacked": label or "(unnamed)", "reason": reason})

    # Printed to the founder under "Not checked", so worded exactly like the prose fields.
    could_not_check = []
    for c in data.get("could_not_check") or []:
        if str(c).strip():
            worded, n = humanize(str(c).strip(), documents)
            humanized += n
            could_not_check.append(substitute(worded))

    # What the red team OPENED, against what the founder SUPPLIED. Self-reported -- the only
    # evidence it is honest is the tool stream a harness records, which an e2e lane reads -- but a
    # red team that lists nothing when documents exist is caught here, and that is the live case:
    # told the artifacts were "a faithful transcription", it opened three files, none of them the
    # deck. A file opened but unreadable belongs in BOTH sources_read and could_not_check.
    # The prompt lists documents by agent-namespace PATH and their OCR sidecars beside them; an
    # honest red team echoes those. Normalise to the document's basename: strip directories, and
    # map a `<name>.p<N>.txt` sidecar to `<name>` -- reading the machine-read text of a page IS
    # reading that document. (Measured: an exact-basename match read a correct transcription of
    # the prompt as "unread", which would have put a high warning on the honest behaviour.)
    read_names: set[str] = set()
    for raw in data.get("sources_read") or []:
        base = os.path.basename(str(raw).strip())
        m = re.match(r"^(.+)\.p\d+\.txt$", base)
        read_names.add(m.group(1) if m else base)
    # A CITATION IS EVIDENCE OF READING, and it is evidence we already hold. `sources_read` is
    # self-reported, and on a live run the review quoted page 2 of the founder's deck in two
    # accepted findings while declaring it read nowhere -- so the report told the founder, four
    # times and once at high severity, that the review never opened a document it had just quoted
    # back to them. The verdict paragraph carried both sentences. Validation above already refuses
    # a `document:` citation naming a file that was not supplied, so an ACCEPTED finding citing
    # `document:<name>#page=<n>` is a checked claim to have opened <name>; rejected findings are
    # not, and do not count. Deliberately not gated on `quote_verified`: a quote that fails to
    # verify is a fabrication signal with its own handling, and "we could not confirm your quote"
    # and "we never opened your file" are different statements -- saying the second because of the
    # first is how the contradiction got in front of a founder in the first place.
    cited_docs = {m.group(1) for f in accepted if (m := DOC_RE.match(str(f.get("source_url", "")).strip()))}
    reconciled = sorted(n for n in documents if n in cited_docs and n not in read_names)
    read_names |= cited_docs
    sources_read = [n for n in documents if n in read_names]
    sources_unread = [n for n in documents if n not in read_names]

    by_severity = {s: sum(1 for f in accepted if f["severity"] == s) for s in SEVERITIES}
    return {
        "findings": accepted,
        "rejected": rejected,
        "could_not_check": could_not_check,
        "sources_read": sources_read,
        "sources_unread": sources_unread,
        "summary": {
            "accepted": len(accepted),
            "rejected": len(rejected),
            "unchecked": len(could_not_check),
            "sources_unread": len(sources_unread),
            "by_severity": by_severity,
            "humanized": humanized,
            "sources_read_from_citation": reconciled,
        },
    }


# --- Which review is shown: append-only copies, one per round -----------------------------------
#
# The analysis's main thread can change the review after it is written -- measured with `python3 -c`
# and with a plain write over `redteam.json`, each time with a SKILL.md rule against it in context.
# So the founder-facing output does not depend on `redteam.json` staying untouched.
#
# The producer writes, beside `redteam.json`, a copy per round into this run's hand-off dir,
# `handoff/<run_id>/redteam.r<N>.json`, created once and never rewritten by a later round.
# Renderers show the review from the copy. An edit to `redteam.json` changes nothing the founder
# reads, and it is reported (`REDTEAM_ALTERED`).
#
# The copies also count rounds, and they decide which review is shown -- from what each copy records
# it reviewed (`inputs_reviewed`, the skill's `reviewed_state`), never from anything the model writes.
# The review shown is the EARLIEST one of the analysis as delivered, so re-running the review of an
# unchanged analysis cannot make it softer; every later review of the same analysis is listed beneath
# it, so re-running cannot hide a harsher one either. A model-written approval flag used to make this
# choice: on a live run it was set from an answer to a different question, and the page told the
# founder they had approved a revision that changed nothing.
#
# Detection, not prevention: the main thread owns the filesystem, and a deliberate overwrite of both
# the review and its copy defeats this. That is a different act from the two observed, and the
# plan names it as a residual.
#
# Rounds are counted by the hand-off each copy was produced from. Re-piping the SAME hand-off (for
# instance with a corrected documents dir) replaces that round's copy instead of adding a round.

COPY_KEY = "_review_copy"
COPY_RE = re.compile(r"^redteam\.r(\d+)\.json$")
# The key, inside the review itself, that records what the review was taken against. It is written
# INTO the review, not into the copy's own bookkeeping, so an edit of it is an edit of the review and
# is reported as one.
REVIEWED_KEY = "inputs_reviewed"


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def copies_dir(analysis_dir: str, run_id: str) -> str:
    return os.path.join(analysis_dir, "handoff", run_id)


def strip(doc: dict[str, Any]) -> dict[str, Any]:
    """The review as `redteam.json` holds it: the copy minus its own bookkeeping."""
    return {k: v for k, v in doc.items() if k != COPY_KEY}


def list_copies(analysis_dir: str, run_id: str) -> list[tuple[int, dict[str, Any] | None]]:
    """Every copy for this run, by round. An unreadable copy is kept as None: it still counts."""
    d = copies_dir(analysis_dir, run_id)
    try:
        names = os.listdir(d)
    except OSError:
        return []
    out: list[tuple[int, dict[str, Any] | None]] = []
    for name in names:
        m = COPY_RE.match(name)
        if not m:
            continue
        doc: dict[str, Any] | None
        try:
            with open(os.path.join(d, name), encoding="utf-8") as fh:
                loaded = json.load(fh)
            doc = loaded if isinstance(loaded, dict) else None
        except (OSError, ValueError):
            doc = None
        out.append((int(m.group(1)), doc))
    return sorted(out, key=lambda x: x[0])


def write_copy(
    analysis_dir: str,
    run_id: str,
    result: dict[str, Any],
    handoff_sha256: str,
    *,
    reviewed_state: Callable[[], Any],
    block_extra: Callable[[], dict[str, Any]],
) -> int:
    """Write this round's copy and return its round number. Raises OSError on failure.

    Sets `result[REVIEWED_KEY]` to `reviewed_state()` in place, so `redteam.json` and the copy carry
    the same one. `block_extra()` adds skill-specific baselines to the copy's own bookkeeping.
    """
    d = copies_dir(analysis_dir, run_id)
    os.makedirs(d, exist_ok=True)
    existing = list_copies(analysis_dir, run_id)
    block = {"handoff_sha256": handoff_sha256, **block_extra()}
    for n, doc in existing:
        if isinstance(doc, dict) and as_dict(doc.get(COPY_KEY)).get("handoff_sha256") == handoff_sha256:
            # The same hand-off re-piped: the same round, not a new one. Its content may refresh; its
            # baselines may not. Rebuilding either here would re-read the analysis as it now stands,
            # so a figure edited after the review would become the round's own baseline and the
            # change would go unreported.
            if REVIEWED_KEY in doc:
                result[REVIEWED_KEY] = doc[REVIEWED_KEY]
            else:
                result.pop(REVIEWED_KEY, None)
            kept = {**as_dict(doc.get(COPY_KEY)), "round": n}
            with open(os.path.join(d, f"redteam.r{n}.json"), "w", encoding="utf-8") as fh:
                json.dump({**result, COPY_KEY: kept}, fh, indent=2)
            return n
    result[REVIEWED_KEY] = reviewed_state()
    n = max([0, *(r for r, _ in existing)]) + 1
    while True:
        path = os.path.join(d, f"redteam.r{n}.json")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            n += 1
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({**result, COPY_KEY: {**block, "round": n}}, fh, indent=2)
        return n


def primary_run_id(docs: Iterable[Any], produced: Iterable[float | None] | None = None) -> str | None:
    """This run's id, from the required artifacts -- never from the review itself.

    THE ID MOST OF THEM CARRY. An analysis dir is per company, so a re-run writes over an earlier run's
    files, and one the re-run did not regenerate keeps the earlier id. The rule this replaces took the
    FIRST artifact's id, so a leftover in the first slot (competitive-positioning lists `landscape.json`
    first, market-sizing `inputs.json`) made the earlier run "this run": its review was accepted as this
    run's, and this run's own skip record was refused. A majority cannot be moved by one leftover file in
    a set of three or more, and a consistent set (one id) gets exactly the id it always got.

    A TIE (an even split) goes to the id whose newest artifact was produced last. `produced` runs parallel
    to `docs` and gives each artifact's production time (its file's mtime: no producer stamps a time in
    the artifact itself); a re-run's files are newer than the ones it left behind. Not the greatest id
    string: a run id is whatever the caller passes, and a host-supplied id need not sort by time. Not the
    last-listed artifact: one leftover in the last slot (a checklist not regenerated) would decide it.
    With no production times (or equal ones), the tied id met first in `docs` wins, so callers pass the
    required artifacts in a fixed order.

    A stub (`"skipped": true`, a step deliberately not run, the fleet's one stub shape) is no analysis,
    so its id does not vote; nor does a missing, empty or non-string id. None when no artifact carries one.
    STALE_ARTIFACT names every artifact off this id; this decides whose review the report is resolved for.
    """
    times = list(produced) if produced is not None else None
    counts: dict[str, int] = {}
    newest: dict[str, float] = {}
    order: dict[str, int] = {}
    for i, doc in enumerate(docs):
        d = as_dict(doc)
        if d.get("skipped") is True:
            continue
        rid = as_dict(d.get("metadata")).get("run_id")
        if not (isinstance(rid, str) and rid):
            continue
        counts[rid] = counts.get(rid, 0) + 1
        order.setdefault(rid, i)
        t = times[i] if times is not None and i < len(times) else None
        if isinstance(t, (int, float)):
            newest[rid] = max(newest.get(rid, float("-inf")), float(t))
    if not counts:
        return None
    return max(counts, key=lambda rid: (counts[rid], newest.get(rid, float("-inf")), -order[rid]))


def produced_at(dir_path: str, names: Iterable[str]) -> list[float | None]:
    """Each named artifact's production time (file mtime), None when it cannot be read."""
    out: list[float | None] = []
    for name in names:
        try:
            out.append(os.path.getmtime(os.path.join(dir_path, name)))
        except OSError:
            out.append(None)
    return out


def primary_run_id_in(dir_path: str, artifacts: Any, names: Iterable[str]) -> str | None:
    """`primary_run_id` over the named artifacts as loaded, with their files' production times."""
    names = list(names)
    loaded = as_dict(artifacts)
    return primary_run_id([loaded.get(n) for n in names], produced_at(dir_path, names))


# Each message carries its own remedy. It is printed at the moment of action, which a rule
# further down a SKILL.md is not.
_DELIVER = "Re-running or editing cannot fix this; deliver the report as it is."
MESSAGES = {
    "REDTEAM_ALTERED": (
        "The outside review was changed or removed after it was written. This report shows it as it "
        "was written. " + _DELIVER
    ),
    "REVIEW_COPY_MISSING": (
        "The outside review carries no record of how it was written, so nothing can show it is "
        "unchanged. Re-run the review step's producer command exactly as the skill gives it; never "
        "edit the review."
    ),
    "RED_TEAM_SKIP_CONTRADICTED": (
        "The analysis records that no outside review ran, but one did; this report shows it. " + _DELIVER
    ),
}


_EARLIER_WINDOW_S = 24 * 3600


def earlier_reviews(analysis_dir: str, run_id: str, now: float | None = None) -> list[str]:
    """Other run ids in this analysis dir with a review copy written in the last 24 hours."""
    import time

    now = time.time() if now is None else now
    root = os.path.join(analysis_dir, "handoff")
    try:
        runs = sorted(os.listdir(root))
    except OSError:
        return []
    found: list[str] = []
    for other in runs:
        if other == run_id:
            continue
        d = os.path.join(root, other)
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for name in names:
            if COPY_RE.match(name):
                try:
                    if now - os.path.getmtime(os.path.join(d, name)) <= _EARLIER_WINDOW_S:
                        found.append(other)
                        break
                except OSError:
                    continue
    return found


def resolve(
    analysis_dir: str,
    run_id: str | None,
    redteam: Any,
    *,
    skipped: bool,
    same_as_now: Callable[[Any], bool],
) -> tuple[dict[str, Any] | None, list[tuple[str, str]], dict[str, Any]]:
    """(the review to show, [(code, message)], facts) for this run.

    `same_as_now(reviewed)` says whether a copy was taken of the analysis as it now stands; the caller
    computes it. Required, so two renderers cannot pick different rounds by one of them forgetting it.
    `skipped` is whether the analysis records that no review ran.

    With no copies, the review is `redteam` unchanged and nothing is checked -- a run made before
    copies existed, or a fixture. `facts` carries `rounds` (the highest round number), `round_shown`,
    `later` ([(round, review)] of the same analysis after the one shown), `matched` (some copy is of the
    analysis as delivered), `all_match`, the first and shown copies' `reviewed_first` /
    `reviewed_shown`, and their bookkeeping blocks as `first_block` / `shown_block`.
    """
    shown: dict[str, Any] | None = redteam if isinstance(redteam, dict) else None
    facts: dict[str, Any] = {"rounds": 0, "round_shown": None, "later": [], "matched": False, "all_match": False}
    if not run_id:
        return shown, [], facts
    earlier = earlier_reviews(analysis_dir, run_id)
    earlier_codes: list[tuple[str, str]] = []
    if earlier:
        earlier_codes.append(
            (
                "EARLIER_REVIEW_THIS_ANALYSIS",
                f"An earlier run today also had this analysis reviewed ({', '.join(earlier)}); this report "
                "shows only this run's review. If the analysis was restarted to get a different review, "
                "say so to the founder; otherwise accept this with the reason.",
            )
        )
    copies = list_copies(analysis_dir, run_id)
    if not copies:
        codes: list[tuple[str, str]] = []
        rid = as_dict(as_dict(shown).get("metadata")).get("run_id")
        if shown is not None and rid == run_id and os.path.isdir(copies_dir(analysis_dir, run_id)):
            codes.append(("REVIEW_COPY_MISSING", MESSAGES["REVIEW_COPY_MISSING"]))
        return shown, earlier_codes + codes, facts

    codes = list(earlier_codes)
    usable = [(n, d) for n, d in copies if isinstance(d, dict)]
    # Counted by the highest round, not by how many copies exist: deleting round 1 used to leave a
    # lone round 2 that read as the only review.
    rounds = max(n for n, _ in copies)
    facts["rounds"] = rounds
    gap = rounds != len(copies) or len(usable) != len(copies)
    if usable:
        facts["first_block"] = as_dict(usable[0][1].get(COPY_KEY))
        facts["reviewed_first"] = usable[0][1].get(REVIEWED_KEY)

    # A re-pipe of the same hand-off replaces its round (write_copy), so a genuine round 2 was built
    # from a different hand-off and says something round 1 did not. One carrying round 1's hash, or
    # round 1's findings word for word, is round 1 copied: the review shown is round 1's. The findings
    # are compared, not only the hash, because the hash sits in the same file a copier is editing.
    def _findings(doc: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in strip(doc).items() if k != REVIEWED_KEY}

    copied = (
        rounds == 2
        and len(usable) == 2
        and (
            as_dict(usable[0][1].get(COPY_KEY)).get("handoff_sha256")
            == as_dict(usable[1][1].get(COPY_KEY)).get("handoff_sha256")
            or _findings(usable[0][1]) == _findings(usable[1][1])
        )
    )
    matching = [(n, d) for n, d in usable if same_as_now(d.get(REVIEWED_KEY))]
    facts["matched"] = bool(matching)
    facts["all_match"] = bool(matching) and len(matching) == rounds
    pick: tuple[int, dict[str, Any]] | None
    if copied or gap:
        pick = usable[0] if usable else None
        codes.append(("REDTEAM_ALTERED", MESSAGES["REDTEAM_ALTERED"]))
    elif matching:
        pick = matching[0]
        facts["later"] = [(n, strip(d)) for n, d in matching[1:]]
    else:
        # No review is of the analysis as delivered: the latest is shown, and the skill says what
        # changed after it.
        pick = usable[-1] if usable else None
    if pick is not None:
        facts["round_shown"] = pick[0]
        facts["reviewed_shown"] = pick[1].get(REVIEWED_KEY)
        facts["shown_block"] = as_dict(pick[1].get(COPY_KEY))
        chosen: dict[str, Any] | None = strip(pick[1])
    else:
        chosen = shown
    latest = strip(usable[-1][1]) if usable else None
    if (latest is None or shown != latest) and not copied and not gap:
        codes.append(("REDTEAM_ALTERED", MESSAGES["REDTEAM_ALTERED"]))
    if skipped:
        codes.append(("RED_TEAM_SKIP_CONTRADICTED", MESSAGES["RED_TEAM_SKIP_CONTRADICTED"]))
    return chosen, codes, facts
