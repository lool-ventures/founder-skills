# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.8.0] - 2026-08-15 — Checking the arithmetic, and saying what was not checked

### Highlights

Six themes.

**Your own figure now reads the same in both documents.** When a figure you stated is in a
different currency from the analysis, market sizing converts it before comparing. The written
report compared the converted figure while the visual report showed the unconverted one — so the
two documents you receive disagreed about your own number by exactly the exchange rate, and the
visual report labelled a foreign figure with the analysis currency. Both now show the same
converted figure, and so do the surrounding notes and warnings. When the comparison cannot be made
at all, because no currency was stated for your figure, neither report prints a percentage
difference any more: that number measured the exchange rate rather than any disagreement. Your
figure still appears, beside a dash and the reason the two could not be lined up.

**A competitive positioning rank now accounts for which end of an axis is good.** On an axis
running price low to high, a startup sitting second-cheapest of nine was told it "ranks last of
eight companies on both price and analytical depth. That is the headline finding to address." The
axis direction is now stated and carried through both halves of the differentiation score, and an
unrecognised value is refused rather than silently read as its opposite.

**Deck review now does the deck's arithmetic.** "The numbers are internally consistent" has been one
of the 35 criteria since it shipped, assessed by reading rather than by calculation. It now reads
every figure off your slides at full scale, has a second, independent reading of the same
slides confirm them, works out which figures should relate to each other, and computes the result.
Figures that disagree with each other are shown, along with readings the numbers imply. Figures the
second reading could not confirm are dropped rather than guessed at, and a separate pass reviews
each disagreement before you see it — it can withdraw one whose comparison does not really hold,
and never the other way. The section says how many figures were read, how many were confirmed and
how many comparisons were run, and says plainly that a short list means those particular
comparisons held, not that a careful reader would find nothing more.

**PowerPoint decks are now read as slides.** deck-review accepted `.pptx` and scored all five
Design & Readability criteria for one, without the slides having been rendered first. PowerPoint is
now converted and rendered. When it cannot be converted, the slide text, table cells, speaker notes and
chart data are recovered instead, the design criteria are excluded rather than guessed at, and the
report says in its summary that the design was never reviewed — and what would get it reviewed,
which depends on why: a deck described in conversation needs a file, a deck whose slides are
images needs exporting from the original rather than scanning, and a deck read only in part needs
re-sending in full. The same gate now covers markdown decks, and decks that arrived unreadable or
only partly readable. Where the design criteria were excluded, the charts leave the category out
altogether instead of scoring it over whichever criterion survived — it was being drawn at 100%
and listed among your strengths — and the visual report now carries the same explanation the
written one does, rather than simply dropping the number. The category charts also stop showing a
category that does not apply to you at all as **0%**: the four AI-company criteria on a company
that is not an AI company had an empty denominator and were plotted at the centre, which reads as
total failure rather than "not applicable".

**Scores and sections say what they mean.** A deck-review `warn` earns half credit — every one of
the 35 criteria defines warn as partial satisfaction, and it used to count for nothing. The score
is labelled deck-craft conformance and is explicitly not a prediction of investability; the verdict
wording no longer promises "investor-ready". The coaching commentary — the only part of the report
written by something that read your deck rather than scored it — moved from the very bottom to
directly beneath the summary, and opens with a verdict. The fixes section now lists changes to
make: the field it draws from had no stated contract, so on real decks it came back describing what
had been *checked* rather than what to change.

**Reports now name what they did not cover.** A gap the report did not mention was easy to read as
a gap that was not there. Deck review states that its 35 criteria do not assess your market, technology, or sector regulatory
and compliance questions. Competitive positioning names competitors that were never put through
its adversarial verification. Financial model review names the checks that dropped out of the score
— whether because the assessment excluded them or because your geography or sector could not be
matched — and it no longer states the wrong reason for the second case. A company in Israel whose
geography was written "Israel/US" was told, on four Israel-specific checks, that they applied to a
different geography; the checks had in fact never been assessed, and leaving them out of the total
moved the score from solid to strong on the spelling alone. The report now says the field could not
be matched, everywhere it says anything: in the written report, in the visual one, in the explorer,
and in the count shown beside the score. And market sizing stops presenting agreement as evidence:
two methods landing close together is not cross-validation, and reproducing the figure in your own
deck is not a strength.

### Added

- **deck-review:** a numeric consistency chain — figures are recorded at full scale with the
  verbatim text they were read from, transcribed again by a second, independent reading of the
  figure-bearing slides, related to each other, and checked by arithmetic that applies scale,
  currency and period rules. Two things reach you: figures that disagree with a figure your deck
  itself states, and up to three readings the numbers imply, labelled as judgement. Confirmations,
  restatements and unconfirmable figures are not shown. Where this arithmetic and the criteria
  review disagree about your numbers, the report says both rather than quietly picking one.
- **deck-review:** PowerPoint (`.pptx`) is converted and read. Without a converter, a fallback
  reader recovers slide text, table cells, speaker notes and native chart series, records that the
  deck arrived as text, and reports how many images it could not read.
- **deck-review:** a coverage line stating how many figures were read, how many a second reading
  confirmed, and how many comparisons were run — rendered even when nothing was found, so a
  thin check is distinguishable from a clean one.
- **deck-review:** an explicit statement of what the review does not cover.
- **competitive-positioning:** a Funding column in the competitor tables of both the report and the
  visual report. The research was already being done, and whether a rival has raised an order of
  magnitude more money often decides how the rest of the analysis should be read — but it reached
  you only when the write-up happened to mention it in prose.
- **competitive-positioning:** the moat step is now told about the custom-moat path and given
  distribution/channel defensibility as the case that keeps arising. A named partner reaching most
  of your buyers previously had nowhere to go and was recorded as an absent network effect.
- **competitive-positioning:** competitors added after the verification pass had already run are
  named as not independently challenged, rather than presented alongside verified ones.
- **financial-model-review:** checks that came back not-applicable although your profile says they
  apply, and checks excluded because your geography or sector could not be matched, are now named
  beside the score they qualify.
- **market-sizing:** a warning when the serviceable market equals the total market — a serviceable
  market that applies no narrowing carries no filtering work.

### Changed

- **deck-review:** a `warn` now earns half credit toward the score. The band thresholds are
  deliberately unchanged: four decks measured span ten points while the same deck moved up to seven
  between two runs that changed no scoring code, so a new boundary would flip bands on re-runs of
  an unchanged deck.
- **deck-review:** the score is presented as "deck-craft score" with its formula stated, and the
  verdict wording describes craft rather than investability. The footnote projecting a score "if
  all fixable items were resolved" is gone: with all 35 criteria mandatory, that figure works out to
  100% for any deck, so it carried no information.
- **deck-review:** the fixes section is renamed "Up to 5 Fixes to Make", states that it is not
  ranked, leads with a critical missing slide, and skips any item whose text is not a change you
  can make — at every place that text is rendered, including the coaching hand-off. A separate
  warning records how many were skipped.
- **deck-review:** the slide-count criterion is no longer excluded for text decks. Counting slides
  is arithmetic, not a visual judgement, and the model was making the criticism in prose anyway —
  unscored and without evidence.
- **deck-review:** contradictions are ordered most-wrong-first by relative gap, so a figure that is
  525% off reaches you before one that is 4% off. Previously the order was whatever the analysis
  happened to propose.
- **deck-review:** a review now takes noticeably longer, because reading the figures and
  transcribing the slides a second time both look at the slide images. Only the figure-bearing
  slides are read the second time, which is what keeps the difference bounded.
- **market-sizing:** "cross-validation" is retired as a label — the pipeline cannot tell whether
  the two builds rest on the same underlying figures, so their agreement is not confirmation. The
  self-check no longer passes on the two answers being within 30% of each other; what earns the
  point is explaining the gap, in either direction. The methodology line said it too, and was the
  last place it survived.
- **market-sizing:** a figure you stated in another currency is now shown converted in every place
  it appears — the comparison table, the note above it, the warning below it, and the visual
  report. Four places, and they did not agree: one printed the converted figure, the others the
  raw one, and one labelled a foreign figure with the analysis currency and put a dollar sign on an
  analysis that was not in dollars.
- **market-sizing:** a comparison that cannot be made no longer produces a percentage. Where your
  figure's currency is unstated, the difference shown was the exchange rate rather than a
  disagreement — a report could say a figure "could not be cross-checked" and print a difference
  for it in the same breath. The row stays, so your figure is still there to see, with a dash and
  an explanation in place of the number.
- **market-sizing:** the coaching commentary is told when a cross-check was refused. It was given
  your stated figures and told the deck had been reviewed, with nothing to say the comparison never
  ran, so it could write as though your number had been checked against ours.
- **market-sizing:** the "most sensitive parameter" is now the widest-stressed parameter, and every
  parameter tied at the top is named. The ranking follows how wide a stress band each input was
  given, not how much the answer depends on it, and the top spot was a tie on 11 of 14 runs
  measured — broken by nothing more than list order.
- **market-sizing:** a figure landing within 25% of one stated in your materials is annotated with
  what that does and does not mean, and the "within 20% of deck claim" line has been removed from
  the strengths list.
- **competitive-positioning:** one score now yields one verdict. The differentiation score was
  banded by three separate chains and the analysis-quality score by two, so a single report could
  call the same figure "strong" in one line and "moderate" two lines below.
- **financial-model-review:** which criteria count toward your score is now decided from the review
  inputs on disk rather than from a profile re-typed by the grading step; where the two disagree,
  each differing field is reported rather than absorbed.
- **financial-model-review:** a check skipped because your geography or revenue model could not be
  matched no longer reads as a statement about your company. It said "applies to a different
  geography" — the same words used when a check genuinely does not apply to you — so a company in
  Israel entered as "Israel/US" was told four Israel-specific checks were for somewhere else. They
  had never been assessed, and dropping them from the total moved the score from solid to strong.
  It now says the field could not be matched, and quotes back what you wrote.
- **financial-model-review:** the score says when it was computed over fewer checks than your
  company warrants. The written report had named the missing checks for a while; the visual report
  and the explorer showed the percentage alone, so a partial review looked like a complete one. The
  coaching commentary is told as well, and told not to lead with the headline status when it is.
- **financial-model-review:** every list in the report names checks in words rather than by
  internal identifiers. The failed and warned items led with the identifier and put the readable
  name in brackets after it — a delivered review carried thirty of them — and the two warnings
  about dropped checks did the same.
- **financial-model-review:** the runway criterion's pass and warn bands did not cover their own
  axis for seed and Series A — 18-24 months fell in neither. A 22-month runway was graded a pass on
  evidence that described a warn.

### Fixed

Fleet-wide:

- Rewriting internal names into plain English also rewrote them inside links, so a citation
  containing an underscore was handed to you broken. The check that should have caught it ran after
  the damage and reported clean, because a corrupted link no longer carries the token it was
  looking for. Links are now left byte-exact while prose around them is still translated, and
  somebody else's URL slug is no longer reported as our internal token.

**deck-review** — the numeric checks, all found by running real decks:

- A correct deck was told it contradicted itself: `$493k ÷ $94k = 5.24x — but the deck states 425%`.
  425% growth *is* 5.25x. The rule that recognises this convention was using a tolerance calibrated
  for the opposite job, so it could only ever fail to suppress.
- A range split across two rows was compared endpoint by endpoint as though each were a point, so a
  computed figure sitting comfortably inside the range your deck states was reported as a
  disagreement. On one live deck this accounted for seven of nine reported contradictions.
- A figure recorded with a lost decimal produced a 0.006% "disagreement" on a table denominated in
  thousands. The check that exists to catch precision loss had a floor that swallowed it.
- Readings that restated the deck rather than testing it: a figure compared with itself across two slides
  (`150+ ÷ 150+ = 100.0%`, `$12.5 trillion − $12.5 trillion = 0`), including the case where the same
  quantity is stated in different units on different slides (9 million per month against 108 million
  per year).
- The figures a comparison was built from were checked against the second reading, but the figure it
  was compared *against* was not — so a disagreement could rest on a number the second reading never
  found. Both sides now clear the same gate, which is what the section's opening sentence describes.
- Subtracting an open-ended figure ("Over 30%") reported an exact answer where only a ceiling is
  honest, and a bound stated inside the figure's own text was not detected at all.
- A percentage reduction was compared against a percentage share as though they were the same
  quantity — they are complements. The comparison is now refused rather than converted, since
  guessing the direction would manufacture a contradiction.
- "Targets" and "projections" were treated as approximate and given up to 14% tolerance. A target is
  a specific number and a projection is stated exactly, so widening there only made disagreements
  less likely to surface. Genuine rounding markers still widen.
- "200-400m" tower heights were rejected with advice that would have recorded them as 200 million
  metres. Whether a trailing letter is a unit or a multiplier is settled on the slide, not in the
  text, so the step now asks for it to be spelled out instead of resolving it either way.
- The warning that the disagreements you are reading were never reviewed could be waived away. It
  can no longer be.

**deck-review** — everything else:

- A deck whose comparisons all held produced no numbers section at all — on one real deck, 113
  figures read, 101 confirmed and 20 comparisons run, with none of it reported. The coverage line now
  renders whenever the checks ran, findings or not.
- PowerPoint conversion, when it was first exercised for real, could not start at all and reported
  the wrong reason — a converter that existed and failed looked identical to no converter. The three
  outcomes are now distinct and the actual error is reported.
- One run replied "I don't see a pitch deck attached" and stopped, with the deck sitting in place.
  The review now locates the file first and asks only after a listing genuinely comes back empty.
- Markdown decks were scored on "24pt+ body text" and "readable on mobile without zoom" — criteria
  that cannot be evidenced for a deck with no rendered page.
- When the design criteria were correctly excluded, the only disclosure was an annotation inside a
  35-row table.
- Reported unresolvable sector wording implied the industry list was incomplete. Sector type is a
  revenue model, not an industry; the message now says so and states that the only consequence is
  skipped sector gating.

**competitive-positioning:**

- Rank did not know which end of an axis was good. On a price axis running low to high, a startup
  sitting second-cheapest of nine was told it "ranks last of eight companies on both price and
  analytical depth. That is the headline finding to address." Both halves of the differentiation
  score were affected, not just the rank. Axis polarity is now stated, an unrecognised value is
  rejected rather than silently read as its opposite, and it forms part of the map's identity so a
  quality check graded before a flip is no longer reported as current.
- The positioning map's axis explanations were read from the pre-scoring draft, so founders were
  shown "Placeholder — replaced by POSITIONING_SCORING dispatch" in visible prose beneath the map,
  in both the visual report and the explorer.
- A moat dimension that does not apply rendered as "Rank -1 of 0 ranked" and was still offered a
  leader — a comparison on a dimension where no comparison was possible. On the moat radar, "does
  not apply" and "assessed, and there is nothing here" were plotted at the same point; the chart now
  names the non-applicable dimensions and states they are not scored as a weakness.
- A quality check recorded against the wrong criterion — real evidence filed under someone else's
  label — could not be detected, so a reader asking "why did this pass?" was shown the justification
  for a different check. The grading step now echoes the criterion it believes it graded, and a
  disagreement is reported.

**financial-model-review:**

- Criteria the profile says apply could be excluded during assessment and drop out of the score
  unrecorded. Two delivered reviews excluded criteria by applying a rule backwards, and one was scored on
  very nearly the complement of the right set — the percentage looks ordinary while covering fewer
  checks than the company warrants.
- The same company graded twice, differing only in how its geography was spelled, assessed 38
  criteria one time and 34 the other, silently dropping the statutory, grant and VAT checks — with
  the same score reported both times.
- The runway table printed `None` for a company that never runs out of cash, where the adjacent
  column already rendered "not applicable" properly.
- The new exclusion lines named internal criterion ids; they now name the checks.

**market-sizing:**

- An unsourced exchange rate was recorded and read by nothing — the warning existed, was written to
  the artifact, and reached neither the report nor you. A blank date or source now counts as absent
  rather than passing as provenance, so a converted figure can no longer look sourced while showing
  a blank where the date belongs.
- The report and the visual report disagreed about when a divergence from your own stated figure is
  worth flagging (25% in one, 50% in the other), so a deck sitting at -43% was called out in one and
  passed over in the other.
- With a currency conversion in play, one report could read "+11.1%" in the comparison table and
  "differs from deck claim by -72.2%" in the warnings, about a single figure — the table compared
  the raw claim while the warning compared the converted one.

## [0.7.1] - 2026-08-07 — Two ways a report could be wrong without saying so

### Highlights

A small corrective release. Two faults that produced a finished-looking report from work that had
not actually been done.

**A value that is not a number no longer becomes one.** Market sizing accepted a few inputs that look
numeric but are not — a true/false answer where an amount belonged, or the words "nan" and "infinity"
— and computed a market size from them anyway. A true/false value was read as 1, so a 1% capture rate
could appear where you had given nothing meaningful, and the resulting figure was labelled valid.
Those inputs are now refused, and the run stops and names the field it could not read.

**A deck review now tells you which slides it did not review.** If a slide was missing from the
slide-by-slide analysis, the review still scored and read as complete — you could receive a review of
twelve slides for a fifteen-slide deck with nothing to indicate the gap. The report now names the
slides that were not covered and flags it prominently. A slide analysed twice is flagged too, since it
overstates how much of your deck was actually looked at.

### Fixed

- **market-sizing:** true/false values, and the words "nan" and "infinity", were accepted where an
  amount was expected and silently produced a figure that the report then described as valid. They are
  now refused with a message naming the field. Such a report could also contain values that some tools
  cannot open at all; that can no longer happen.
- **deck-review:** slides absent from the slide-by-slide analysis are now flagged prominently, with the
  slide numbers named, rather than producing a review that reads as complete. Slides analysed more than
  once are flagged separately.

## [0.7.0] - 2026-08-06 — Everything it found, in your words

### Highlights

Three themes.

**The reports are written in your language.** Across all six skills, the internal names our own code
uses — status values, field names, checklist item ids, warning codes — no longer appear in what you
read. They are rendered as English, from one shared policy, in the report, the visual report and the
coaching commentary alike. The exceptions are deliberate: an identifier you can match against your own
paperwork, like a SAFE's id or a scenario's name, is left exactly as it is.

**Analysis you already paid for now reaches the page.** A recurring fault across competitive
positioning, financial model review and cap-table was work that was computed, carried as far as the
interactive explorer, and then rendered nowhere — positioning-map axis rationales, claim verdicts,
competitor-set verdicts, investor talking points, the review's own score. Those now appear. Competitive
positioning also gained a check that runs before hand-over: if the report does not show what the
analysis found, the run does not hand over.

**Fewer silent guesses.** Geography is asked for when your materials do not state it, instead of being
read off a currency symbol or off where the founders used to work — it decides which regulatory and
benchmark guidance the whole review is graded against. A market figure in another currency now needs an
exchange rate you supply, recorded with its date and source, or the run stops rather than converting
from memory. And a step that rejects its input says so and stops, instead of overwriting its own
finished work with a blank and reporting success.

Finished documents are also handed over properly now: each one named for what it is and linked
individually, rather than arriving as an unlabelled row of files.

### Added

- **competitive-positioning:** the positioning reality-check triggers are now evaluated from the
  scored map itself rather than worked out afresh each run, and "not evaluated" (too few competitors
  for a quartile to mean anything) is reported distinctly from "did not fire".
- **competitive-positioning:** a pre-delivery check that the report actually shows what the analysis
  found — axis rationales, claim verdicts, the competitor-set verdicts, the explorer's scored layer —
  that nothing internal reached you, and that the artifacts agree with each other. A run with gaps
  does not hand over.

### Changed

- All six skills render internal enum and field names as English ("switching costs evidence source"
  rather than `switching_costs evidence_source`), from one shared policy. Stable identifiers a founder
  can cross-reference against their own documents — a SAFE's id, a scenario's name — and diagnostic
  codes are deliberately left unchanged. cap-table's own label map remains the authority for its
  vocabulary.
- Reports are checked for internal tokens as they are composed, and the coaching commentary is checked
  as it is inserted; findings are reported without blocking a run.
- **competitive-positioning:** warning text now names competitors by display name rather than internal
  slug.
- **competitive-positioning:** the trade-off trigger for the positioning reality check now fires on a
  strong-on-one-axis position (top third) rather than only a top-2 one, so it catches the shape it was
  added for.
- All six skills locate their own installation once per run, deterministically, instead of searching
  for it again at every step — so a machine carrying more than one copy can no longer mix versions
  mid-run. Duplicates are named when found.

### Fixed

Fleet-wide:

- Three skills told an analysis step to hand its whole result back in a message as well as writing it
  to disk. Restating a long analysis is where truncation and drift come from; each now returns only a
  confirmation that the file was written.
- Finished documents were sent without being introduced, so a founder could receive a row of files
  with nothing saying which was the report and which the interactive version. Every skill now names
  each deliverable and links it individually.
- **deck-review, market-sizing:** a company's geography could be recorded from a currency symbol or
  from where the founders previously worked, rather than asked for. Geography selects which
  regulatory and benchmark guidance the review is graded against. Both now ask when the materials do
  not state it, and deriving some of the opening basics no longer skips the question for the rest.
- Internal tokens reached founder-facing report text in every skill: private enums, field names and,
  in one case, a shell command the founder had no shell to run.
- Some tokens were then kept verbatim by mistake — a field name reached through an `id` field
  (`gross_margin`) stayed raw and suppressed its own warning. Identifier preservation is now scoped to
  cap-table, where ids are handles a founder matches against their own documents.
- A founder's own uploaded filename was reported as an internal file reference.
- Internal tokens written in capitals — checklist item ids, dispatch labels, warning codes, an
  importance flag — reached founders in every skill's reports and were invisible to the check meant to
  catch them, which only looked at lowercase. deck-review no longer prints `[NICE_TO_HAVE]`, the
  coaching hand-off now carries readable warning names rather than codes, and
  competitive-positioning's gate checks the whole report rather than only the coaching section.
- Sub-agents are now told, on the surface that measurably changes their behaviour, not to name our
  files or internal labels in the evidence a founder reads, and not to write item ids, status values or
  warning codes into coaching commentary. Every skill also states what to do with a warning it does not
  recognise, rather than leaving it undefined. Our own working files are now recognised by kind rather
  than by a hand-kept list that had fallen well behind, and a web address in a citation is no longer
  mistaken for one.
- **financial-model-review:** unit economics and runway fingerprinted their inputs AFTER computing, and
  the unit-economics computation modifies what it was given — so the recorded fingerprint described a
  document that never existed on disk and the verifier reported staleness on a current artifact.
- **financial-model-review:** the staleness check could be cleared by deleting the record it compares —
  cheaper than forging it, and silent. An absent record is now an error, its remedy is stated per
  artifact (the checklist must be re-judged, not re-piped), and it names the report re-run that a stale
  producer artifact also invalidates.
- **financial-model-review:** correcting a figure marked the review stale even when none of its numbers
  would change — a false alarm with no remedy. The check now rebuilds from your corrected inputs and
  reports it only if the result actually differs.
- Sub-agent evidence cited our artifact filenames ("inputs.json reports actuals separated: false") and
  that text prints verbatim in the report. Evidence now states what is true of the company or model;
  financial-model-review and competitive-positioning check it at their delivery gate.
- A step that rejected its input said so nowhere: it overwrote its own finished work with an empty
  placeholder and still reported success, so a section of the report came back blank and the only
  warning pointed at a symptom rather than the cause. Across four skills, each such step now leaves
  existing work untouched, reports the problem and stops — and the report refuses to present an
  analysis one of its steps never produced.

**cap-table:**

- Guidance said a missing cap base produced silent zeros in artifacts that "look right". It stops the
  run instead, and saying otherwise invited invented founders and share counts. Two places also
  claimed the extraction step produces the cap-state snapshot; it does not.
- Field names printed as raw tokens (`safe_price`).
- The explorer embedded three values its script never read.
- The report identified a SAFE only by our internal id (`safe_foobar`) when the investor's name was
  available; it now leads with the name and keeps the id in small print.
- The counsel packet's summary line printed a raw rule-domain token and an `item(s)` placeholder.

**competitive-positioning:**

- A deck with no competition slide was graded as "not applicable" rather than flagged, which dropped
  the item out of the score — so a deck that never engaged competition scored *higher* than one that
  engaged it poorly. It is now a warning, as the criteria always said.
- The positioning reality-check described one of its own triggers with an out-of-date threshold, so
  the explanation and the check disagreed about when it fires. The explanation no longer restates the
  numbers, and a trigger calibrated on limited evidence is now presented to you as a soft signal
  rather than a settled finding.
- Positioning-map axis rationales were blank in `report.md` and absent from the visual report and
  explorer; the checklist could grade POS_05 as a pass on unrendered text.
- The explorer embedded differentiation scores, per-axis ranks, vanity-axis flags and claim verdicts,
  and rendered none of them.
- Adversarial competitor-set verdicts did not reach the report — a competitor judged not-a-competitor
  was scored, ranked and tabled like a genuine one.
- A competitor's researched pricing model was never shown, and the competitor-set verdicts showed
  neither which dimensions overlapped nor the verdict's confidence.
- Startup rank could print as "11 of 10 competitors". Ranks now read "N of M ranked", with the same
  wording in the moat section.
- Differentiation verdicts and moat statuses printed as raw enum tokens; competitors were named by
  internal slug.
- A competitor development older than the 18-month window failed the whole landscape step.
  Out-of-window moves are retained and reported instead; the checks against invented events are
  unchanged and still stop the run.
- The blind-recall duplicate check compared slugs literally, so a competitor already in the set could
  reappear as a gap and a company named inside a cohort entry read as missing.
- Recall candidates declined at the first gate were dropped instead of re-offered at the later gate.
- Re-scoring the map without re-running the checklist left the review describing a map that no longer
  existed. The checklist records which map it graded and compose flags a mismatch.
- The delivery gate checked only the rendered report for internal filenames, so evidence citing them
  passed unnoticed — this skill renders checklist evidence nowhere. The gate now checks the artifact.

**deck-review:**

- Slide types printed as raw tokens (`purpose_traction`, `business_model`).

**financial-model-review:**

- Two runway figures the report relies on were missing from the documented artifact, including the one
  to lead with when a company is projected default-alive — where a blank runway is a result, not a gap.
- The explorer embedded the review checklist score but did not render it.
- The coaching template asks for investor talking points; they were embedded in the explorer and
  rendered nowhere.
- The report ended with a command line for the founder to run (`explore.py --dir … -o …`), which they
  have no shell for. It now asks for the explorer in words.
- Warnings about missing optional data named the internal file rather than the data.
- A skipped checklist item explained itself by naming the internal gate field
  (`Auto-gated: geography_gate '[...]'`); it now states the reason.
- An output computed before the founder's corrections were applied could not be distinguished from one
  computed after. Each output now records a fingerprint of the inputs it used, and the completeness
  check compares it against the inputs as they stand.
- Checklist scoring recorded no fingerprint of the inputs it graded, so staleness was undetectable for
  it; the producer pipe now passes the inputs it was scored against.

**ic-sim:**

- The evaluation reference omitted the "to confirm" status entirely and gave a scoring formula that
  counted it against you. Undisclosed dimensions are excluded from the score, and past six of them the
  verdict is held at more-diligence in both directions — you cannot be declined for what you weren't
  asked. The reference also claimed a generic run invents a fund thesis; it never does.
- Partner and consensus verdicts printed as raw tokens (`more_diligence`, `hard_pass`), including in
  the report's headline verdict lines.

**market-sizing:**

- A market figure sourced in another currency was converted by an agent that had no exchange rate
  and no way to look one up, so the rate came from memory — undated, unsourced, and impossible to
  check. Conversion now happens in the sizing step, using a rate that must be supplied; it is
  recorded and shown to you in both the report and the visual report, with its date and source. A
  figure in another currency with no rate stops the run instead of being guessed at.
- A converted figure could no longer be checked against the number you stated, or against your
  deck's TAM/SAM/SOM — the comparison would have differed by exactly the exchange rate and flagged a
  correct analysis as a mismatch. Stating which currency your own figures are in restores the check;
  without it the report says it could not verify, rather than reporting a mismatch that isn't one.
- Sensitivity ranges could skip their widening floor, producing a stress test that stressed nothing.
- Support strength, estimate provenance and driver names printed as raw tokens
  (`partially_supported`, `agent_estimate`, `customer_count`); the checklist listed internal filenames.
- Each source's quality tier and segment match, and each assumption's source attribution, were
  collected and never shown — leaving no way to weigh a figure being defended.

## [0.6.0] - 2026-08-02 — Fits more companies, reports more honestly


### Highlights

Three themes.

**The skills now fit companies they previously mis-handled.** In **financial model review** and
**market sizing**, figures denominated in a currency other than USD are labelled and reported in that
currency end to end, and are no longer judged against USD-denominated bars. (No FX conversion is
performed anywhere — the currency is a label on the numbers you supply, and the reports say so. The
other four skills have no currency dimension.) Gross margin is benchmarked against your sector — hardware, consumer
subscription and retail get their own bands, and marketplace, transactional-fintech,
hardware-subscription and usage-based models are rated *contextual* rather than failed against a SaaS
bar. Retail/D2C is a first-class revenue model, Series C and Series D are accepted stages, and more
geographies are recognised by name. In cap-table, a lone SAFE, note, term sheet or option plan with no
surrounding cap table now produces an instrument-terms report instead of a dead end, and messy
real-world spreadsheets — holder × share-class matrices, angel and ex-employee common holders, printed
Total rows, right-to-left Hebrew PDF exports — are read rather than refused or silently misread.

**Reports say what they mean, and say what they don't know.** An IC simulation's "pass" now reads as
**Decline** everywhere a founder sees it — a bare "Pass" reads as approval and means the opposite. A
dimension your materials simply don't disclose is scored *to confirm* and excluded from the conviction
denominator, so honest non-disclosure no longer drags a verdict down. Past six undisclosed dimensions
the verdict is held at More Diligence in **both** directions, with the reason stated: a thin deck can no
longer produce a confident "Invest", and — new in this release — it can no longer produce a Decline
either. You cannot be declined on the grounds that you weren't asked. (A weakness the materials *do*
disclose is a concern, not a non-disclosure, and that still counts against you.) Instruments with blank fields are kept as partials with a plain-language note
about what was skipped, never filled in with invented numbers. Figures computed outside the validated
engine carry a disclosure banner, and computed round terms that diverge from your source document lead
the report with a warning.

**Runs are more reliable and quieter.** Deliverables land in the run's own folder rather than
occasionally inside a project folder you happened to connect. Sub-agent results move over files instead
of the message channel, and the coaching section can no longer be half-written, duplicated, or corrupted
by its own punctuation. The skills stop asking for company name, stage, sector and geography they can
already read off your deck, and internal plumbing — script names, flags, exit codes, warning codes,
step labels — no longer leaks into what you read.

*Version 0.5.1 was documented but never distributed — it was neither tagged nor published, so no user
received it. Upgrading from 0.5.0 delivers both 0.5.1's changes and this release's.*

### Fixed — a coaching step that could land its file where the review could not find it

- A sub-agent's hand-off path is no longer inferred from the wrong process. The resolver was deriving
  where a *sub-agent* writes from where the *main thread's shell* happened to be sitting; on Cowork those
  are different processes in different namespaces, so a coaching file could land under a duplicated path
  segment. The review still finished, but the coaching step had to be recovered by hand, and the recovery
  narration leaked internals into what you read. The path is now derived from the one fact that is
  actually true of the sub-agent, and every skill resolves it through the script rather than assembling it
  from strings.
- When a hand-off file genuinely is missing, the review now distinguishes "the sub-agent never wrote it"
  from "it wrote it somewhere unexpected" and reports the second as its own condition, so a compliant
  step is no longer described as a failed one.
- A required read that fails now stops and says so, instead of continuing without the input. This is the
  more important half: a step that improvises produces a complete-looking assessment of data it never
  read, which nothing downstream can detect.

### Fixed — financial-model-review: a validator that could only be satisfied by inventing data

- The expense-coverage check treated a conversational model — total burn plus headcount, no line-item
  opex — as a blocking extraction failure. Because the only way to clear a block is to supply the missing
  expenses, and a conversational model has none to supply, the check could be satisfied by inventing a
  reconciling opex figure. It is now advisory for conversational and partial models, states plainly that
  the remainder is unitemized, and says not to invent one. Spreadsheet and deck models — which do carry a
  breakdown — still block, because there the gap really does mean something was missed.
- Non-USD figures in that warning no longer carry a dollar sign.

### Fixed — financial-model-review: runway that reads as safer than it is

- Every runway scenario now reports **runway at today's burn** alongside the projection. The projection
  holds spending flat while revenue grows, so a company with about seven months of cash could be
  described as "low risk" — true only if you never hire through that growth. The verdict now states the
  assumption it depends on, and a company that merely doesn't run out of cash is no longer described the
  same way as one that reaches profitability.
- A projected-default-alive company reports "no cash-out date" as a result rather than as a missing
  number.

### Fixed — financial-model-review: non-USD reviews that graded almost nothing

- Suppressing USD-denominated bars for a non-USD model was individually correct but collectively left
  burn multiple and Rule of 40 with no assessment at all. Both now carry the grade they would have
  received against the stage benchmark, labelled as a reference with its source and date rather than as a
  verdict. No exchange rate is used or assumed: these benchmarks are ratios, so the comparison is exact.
- An implausibly high burn multiple in a non-USD model no longer says "check input consistency" when the
  real cause is a small revenue base that the USD-denominated materiality floor could not be applied to.

### Also in 0.6.0 — landed after the release commit, before the tag

**Numbers the founder gave must survive the pipeline.**

- Market sizing no longer silently substitutes a better-sourced researched figure for one you stated. A
  researched figure that disagrees is reported as a cross-check with both numbers named, so you can
  decide — it never quietly replaces your input. (In testing, a founder-stated 18,000 pharmacies was
  swapped for a researched 16,601 and the report's headline TAM came from a number they never gave.)
- Market sizing figures carry the analysis currency rather than assuming dollars, and the report
  discloses that no FX conversion happens anywhere — industry totals are usually quoted in USD, so a
  mixed-currency input needs converting before you rely on the total.
- A financial model review no longer contradicts itself on a headline ratio. Where the burn multiple in
  the metrics table and the burn multiple in the checklist evidence disagreed, the report now flags it
  instead of leaving you two numbers to choose between.
- `growth_rate_monthly` is defined as net of churn where it is consumed, so two parts of the review can
  no longer derive different burn multiples from the same inputs.

**Reports say more where they used to say nothing.**

- A non-USD financial model now shows what each ratio *would* score against the stage benchmark, marked
  as a reference rather than a verdict. Previously a non-USD review could return a page of numbers with
  no assessment at all, because every ratio landed "contextual" at once.
- Competitive positioning's coaching section is written from the actual moat scores. It was being asked
  for a defensibility roadmap without being given the moat data — so its advice could disagree with the
  scored table on the same page.
- Moat count and defensibility grade are explained as independent: two weak moats correctly give a count
  of 2 with a low grade, which previously read as a scoring bug.

**Runs are harder to get wrong.**

- A cap-table quick answer lands in its own folder instead of overwriting where a full review belongs.
- Sub-agent hand-offs report a path-namespace mismatch distinctly from a missing file — the two look
  identical from the outside and need opposite responses.
- The conversational path (numbers typed in chat, or read off a deck) is now documented end to end: it
  no longer tries to review an extraction file that was never created, and confirming your numbers before
  the math runs is a stop point there too, exactly as it is for an uploaded model.

**Answers now come from the calculator, not from arithmetic in the chat.**

- Ask a cap-table question in passing — *"if I raise 2M on an 8M pre with a 10% pool, how much do I still
  own?"* — and the answer now comes from the solver. It used to be worked out in the reply, and **it was
  wrong**: 70% where the real figure is 72%, because a pre-money 10% pool dilutes to 8% of post. Two points
  of a company, on a question you ask before signing.
- Every skill now states plainly that a figure reaching you must come out of the tools, never from mental
  arithmetic, a remembered benchmark, or a "rough estimate" offered with the real analysis as a follow-up.
  That last pattern was the most common: you cannot tell that what you just read was not the analysis, so
  you never ask for it.
- A follow-up "what if it were X instead?" re-runs the numbers rather than adjusting them in prose. So does
  splitting a total — per-founder ownership comes from the model, never from arithmetic in the chat.
- **Cap-table now answers "what does this round do to *me*?"** A priced round reports each founder's
  post-round stake by name — *Alex Stone 33.8%, Sam Lee 29.6%* — alongside the founders' combined
  figure. Before, only the combined number existed, and the honest response to the most common
  question a co-founded company asks was to decline it. The per-founder figures are computed by the
  same solver as everything else, not divided out afterwards, and the report says plainly that shares
  held through an employee pool are counted in the totals but not broken out per person.

**Nothing is filled in on your behalf without saying so.**

- A financial model review records which values it supplied versus which you stated. It had been writing a
  24-month runway target for founders who never mentioned one — harmless as a number, misleading as a
  record, because your own inputs file could not tell you which figures were yours.
- Cap-table will not invent a date it was not given. It had been filling in a plausible SAFE issuance date
  that then appeared in your date-sensitive watchlist, indistinguishable from one you supplied — and a
  wrong QSBS clock is worse than a missing one.

**The IC simulation stops overstating what it knows.**

- A verdict reached on almost no disclosed information now says so, in every direction. Previously a
  scorecard with 23 of 28 dimensions undisclosed could return *"More Diligence — promising but needs more
  evidence"* with no caveat at all. It now reads *"too little disclosed to reach a verdict (this is NOT a
  negative signal)"* and shows the denominator: *"Scored on 3 of 28 dimensions."*
- A conviction percentage computed from a handful of dimensions is labelled as such rather than presented
  with the precision of a full assessment.

**Reports say less that is irrelevant to you.**

- A US-only company no longer sees Israeli tax and registrar obligations in its watchlist. The rules were
  correctly filtered; the filter was being dropped between the calculation and the report.
- Progress updates describe what is happening to your work rather than to our machinery — "checking your
  numbers against the 46-point review" instead of internal step names.

**Fewer questions you have already answered.**

- Deck review stops re-asking your company's stage when you gave it a minute earlier, and says it is
  reusing your answer rather than skipping the step silently.
- Runs fail less often on their own bookkeeping: a checklist no longer rejects a whole batch over evidence
  for items it was about to mark not-applicable.

**The IC simulation now holds a real debate.**

- The three partner archetypes used to be consulted in parallel, with no sight of each other — so no
  debate happened. The write-up of "the discussion" was then composed rather than recorded, and it was
  binding: a concern narrated as a dealbreaker forced the score to follow. Two runs on the same inputs
  could reach different headline verdicts depending on how dramatically that exchange got written.
  Partners now actually respond to each other, and the record is produced from what they said.
- The report distinguishes a dealbreaker the partners **argued** from one the scoring pass raised
  alone. Both are worth reading; only the first has been tested by disagreement.

**Competitive positioning asks who is missing, not just who is wrong.**

- The adversarial check that challenges competitors who do not genuinely compete only ever tested the
  list you already had. A separate pass now asks what is *absent* — the blind spot you came to this
  skill unable to see — before you validate the set rather than after.
- Recent competitor developments are dated and sourced, so a rival who moved last quarter is not
  described as though nothing changed.

**Your work is handed to you, not left at an address.**

- Every skill now sends its finished documents to you as files. They used to be written to a folder
  and described by path — and on Cowork's cloud lane, which is the default for a new task, that
  workspace is reclaimed when the task ends. A path could name something already gone.
- Cap-table hands over **all four** documents it produces. A live run delivered three and silently
  dropped the visual report; the closing summary had only ever named three of them.
- The quick routes deliver too. Fast-assess, concise and instrument-only reviews each produce one
  document, and each now has a named place to hand it over — the instrument-only route previously had
  no delivery step at all.

**Numbers that were quietly not being checked.**

- A Series C or D financial model was rejected outright by one validator and, at seven other gates,
  matched no stage at all and was held to no burn threshold. Both now derive from one ordered ladder,
  so a stage nobody thought about cannot silently fall through.
- Plausibility bounds above Series B had been borrowing Seed's floor. Because only the low end is
  compared, that made the check *more* permissive the later the company: $600K of cash at Series C
  read as plausible against a $50K floor. It is now checked against Series B's $1M.
- An implausible figure no longer rates as a strength. A 780% gross margin or a 500% NRR — far more
  likely a mis-scaled input than an elite company — used to sail through as a positive, precisely
  where a second look was most warranted.
- A deck you pasted as text is no longer scored `fail` on five criteria for visual design it was never
  possible to assess from text.

**Questions render properly, and answer the right thing.**

- Every founder question now specifies its own options. Sixteen gates had none, which left the wording
  improvised — one gate measured four different option sets across four runs.
- Two gates offered five choices to a control that renders four, so an option simply could not be
  picked. One offered a choice that would have failed validation if taken.
- Cap-table will not carry an example date into your file. It had been copying the incorporation date
  out of its own template — the same class of invention already fixed for SAFE issuance dates — and
  that date drives QSBS holding-period timing.

**Warnings are written to you.**

- Report warnings used to be phrased for the machine: internal file names, raw status codes, and in one
  case an instruction addressed to the assistant *about* you ("rather than leaving the founder two
  numbers to choose between"). They now state what it means for your report. The diagnostic detail is
  still recorded for the assistant, just not shown to you as though it were advice.
- A cap-table run that models a SAFE snapshot without a priced round no longer reports that as
  "pending input", which reads as an unfinished analysis rather than the answer you asked for.

### Known limitation — a skill may not run unless you name it

- Asked to review a financial model, the assistant may agree your request matched and still answer from
  its own knowledge instead — substituting recalled benchmarks for the source-cited ones, and only
  mentioning the choice if you ask. Each skill's description now states plainly what is lost by answering
  from memory, but **that does not reliably change the decision**: in testing the assistant declined,
  then acknowledged the miss when challenged.
- **If you want a specific skill, name it.** Either a slash command (`/financial-model-review`,
  `/cap-table`, `/deck-review`, `/ic-sim`, `/market-sizing`, `/competitive-positioning`) or plain prose:
  *"Use the financial-model-review skill on our model."* Both route reliably — every example prompt in
  the README now does this.
- Being honest about the shape of it: on a handful of pasted figures, answering directly is not
  unreasonable — the deeper scoring needs more of your model (CAC, churn, headcount, expense breakdown).
  The real problem is being given an unbenchmarked answer with no signal that a rigorous path existed.
  Naming the skill removes the ambiguity entirely.
- **What changed this release — and how to reach it.** The quick-check path below lives *inside* each
  skill, so **it only helps once the skill is running.** In testing, a short conversational question with
  no skill named triggered the skill in only one of three tries; the other two were answered directly,
  without it. **So name the skill even for a quick question** — *"use market-sizing: roughly how big is
  this market?"* — or you will get an answer with no analysis behind it and no way to tell.
- Market sizing, financial model review and competitive positioning now
  have a real **quick-check** path: a short directional answer that still runs the actual calculator on
  the inputs you gave, writes an artifact, and tells you which checks were skipped and what they would
  have added. The numbers match the full run's — only the production weight is dropped. IC simulation and
  deck review have no quick path, because no honest subset of a verdict or a 35-criterion score exists;
  they now tell you what the full run costs before starting it instead. All five also carry a checkpoint
  that forbids answering from arithmetic done in conversation. **The checkpoint is guidance, not a
  mechanism** — it makes the honest path available and obvious, and we have not yet demonstrated it
  changes the decision every time. Naming the skill is still the reliable route.

### Added — financial-model-review: models in any currency

- Set your model's currency (ISO 4217) and the review stays in it end to end. Every figure in the
  report, the HTML artifact, the explorer, and the unit-economics and runway evidence is tagged with
  the native code rather than shown with a bare `$`.
- Extraction now preserves the model's native currency and never applies an FX rate it finds in the
  sheet. Previously the same non-USD model could come out two orders of magnitude apart between runs
  depending on whether that run converted.
- Non-USD models are no longer judged against USD bars or given bogus scale warnings. Burn multiple
  and Rule of 40 are still computed (they are ratios) but reported as *contextual* with a note that
  the stage benchmark could not be verified; the ARR materiality floors and the fixed USD
  cash-sensitivity grid are skipped with an explanation; and the extraction plausibility check drops
  its USD-absolute floors, so a healthy non-USD model can't trip a false "values may still be in
  thousands" flag or a wrong auto-correction.

### Added — financial-model-review: gross margin benchmarked against your sector

- Hardware, consumer-subscription and retail models are scored against their own thresholds instead of
  the SaaS survey table, where a healthy hardware margin previously rated a warning or a fail.
- Marketplace, transactional-fintech, hardware-subscription and usage-based models are rated
  **contextual** with the reason (net take-rate vs gross volume basis; a blend needing its
  hardware/service split; passthrough-heavy vs software-margin spans) rather than graded against a bar
  that doesn't apply.
- New `gross_margin_basis` input: declaring `store_contribution`, `net_revenue`, `gross_revenue` or
  `blended` rates the margin contextual and redirects the review to store contribution, buildout
  payback and same-store trends. A restaurant's store-level margin and its product margin are
  different metrics and neither should be judged on the other's bar.
- When the SaaS bar *is* applied by default, the report now says so — an unrecognised model type is
  labelled "SaaS benchmark assumed", and a sector-table model with no declared basis is labelled as
  assuming product/merchandise margin.
- The AI gross-margin allowance is no longer granted on a trait alone: an `ai-powered` model qualifies
  only if AI costs actually appear in COGS. `ai-native` models and AI sectors still qualify outright.

### Added — cap-table: review a standalone SAFE, note, term sheet, or option plan

- A document with no surrounding cap table used to fail. You are now asked how to proceed — supply the
  cap base for a full review, or take instrument terms only — and the terms-only path produces a new
  `report_extraction_only.md`: an instrument-terms table (cap, discount, MFN, pro-rata, maturity,
  governing law, issuance date) with an explicit "what this does NOT cover" section.
- Term sheets and option plans render a terms table with a per-term confidence column, and an
  amendment that restates one clause of an existing instrument is classified as an amendment rather
  than forced through the convertible-note path as an all-null note.
- Fields the document genuinely doesn't state read as "not stated in document; confirm" — never a
  fabricated value, and never "uncapped" for a cap-implying form whose cap is simply absent.

### Added — cap-table: acquisition modeling

- Model an acquisition alongside a priced round: negotiated consideration percentage, consideration
  form, timing, and which entity is acquired, with the pre-money and pool bases selectable. Option-pool
  top-ups size correctly against the combined post-closing fully-diluted base, and the report states
  the sizing basis so a negotiated headline target isn't confused with the realised percentage.
- A flip can now be chained into a priced round, so the round is modeled against the post-flip cap
  state rather than the pre-flip one.
- Deals past the feasibility fold return a typed, remedy-bearing refusal rather than a wrong number,
  and an over- or double-specified deal is named as such. Every acquisition rule is flagged for counsel
  review.

### Added — cap-table: coverage check and disclosure before the math

- Each deal is checked against a registry of what the validated engine actually covers. An uncovered
  structure is disclosed rather than quietly approximated: the report carries a "computed outside the
  validated cap-table engine" banner and a `coverage_disclosure.json` artifact. (For a deal carrying
  SAFEs, notes, an acquisition or a flip the scenario plan is auto-populated; a plain priced round or
  pool-only change still has its scenarios authored by hand.)
- When computed price-per-share or fully-diluted diverges from a figure stated in your source document
  by more than 0.1%, the report now *leads* with a warning naming the divergence, and records it in
  `report.json`. (The reconciliation table itself shipped in an earlier release; this is the banner.)
- A preferred series whose original issue price you can't confirm can be declared unknown instead of
  given a placeholder. The report then states that anti-dilution and liquidation preference are not
  modeled for that series and the conversion ratio is assumed 1:1, and the skill refuses to run
  anti-dilution math against the placeholder.

### Added — cap-table: messy real-world spreadsheets

- Holder × share-class matrices (one column per class) are decomposed per class, reading class identity
  from the column header.
- Non-founder ordinary shareholders — angels, ex-employees, nominee trusts — get their own category
  instead of being mis-filed as founders, and real shareholder names now appear in the ownership and
  voting tables instead of "Batch b1".
- A labelled Total / Subtotal / Grand total / Sum row is detected and skipped with a warning naming the
  excluded row (whole-cell matching, so a fund actually named "Total Ventures Fund I" is never
  dropped), and the summed shares are cross-footed against the sheet's own printed total — blocking
  with a named reason rather than emitting a silently doubled figure.
- Hebrew and other right-to-left PDF exports often store their text layer in visual (reversed) order,
  which a naive read silently garbles. This is now detected and flagged before the numbers are trusted.
- A cap table made only of preferred series and/or angel common holders is accepted; the no-equity-base
  stop previously fired unless founders or an option pool were present.

### Added — cap-table: blank and partial instruments are kept, not invented

- A SAFE with no purchase amount, a note whose principal lives in a schedule, a warrant or option grant
  with no stated strike, a missing maturity date or an unnamed investor: each is kept as a partial with
  a per-field "not stated; confirm" note and a plain-language callout of what was skipped.
- The callouts distinguish what actually matters to your ownership numbers: a terms-only SAFE or note
  contributes no shares and is excluded; a strike-less warrant's shares still count in fully-diluted
  (only the exercise math is deferred); a strike-less option grant changes no totals at all.
- Re-submitting a corrected extraction of the same instrument used to append a second copy and inflate
  the table; a likely duplicate is now flagged with instructions to reuse the id.
- A note with neither a cap nor a discount now gets a specific answer — no conversion price exists for
  the round, confirm one from the note or counsel — instead of a generic "no conversion path".
- On a jurisdiction flip, per-grant option tax-route detail is requested up front, and a pool with
  issued options but no per-grant data raises an explicit "§102 exposure unconfirmed" counsel item
  instead of reporting zero §102 grants.

### Added — ic-sim: "to confirm" for what your materials don't disclose

- A dimension your deck simply doesn't address is scored `to_confirm` — undisclosed, needs
  confirmation — and excluded from the conviction denominator, instead of being forced into "concern"
  (a negative judgment) or "N/A". It appears as its own column in the scorecard and the HTML category
  bars. Absence that *is* the finding — no traction behind a large ask, no unit economics at Series A —
  still scores as a concern.
- Past six undisclosed dimensions the verdict is capped at **More Diligence**, with the conviction
  score left untouched and the report explaining that the cap comes from missing data rather than from
  the merits.

### Added — competitive-positioning: adversarial competitor-set verification

- Before the landscape locks in, every candidate competitor is independently re-researched from scratch
  — deliberately ignoring your draft's own description — and given a genuine / adjacent /
  not-a-competitor verdict. A "not a real competitor" flag must carry its own reasoning plus an
  independent characterisation of that company's buyer and job, so it can't be a rubber stamp.
- Flagged names are shown to you in the chat *and* named in the confirmation question, and are **never
  auto-removed** — you decide. Competitors you decline stay recorded, so later coaching can refer to the
  decision.
- Newly discovered competitors are an explicit include/skip decision rather than a silent addition.
- Researched claims must cite the URL or the exact search query behind them; a researched claim with no
  source raises a "Researched Without Source" warning so an unverifiable funding, M&A or pricing claim
  is visible rather than invisible.
- Materials more than roughly a year old are flagged up front, since competitor pricing and positioning
  from an old deck may already be wrong.
- Decks beyond ~10 pages are read in page-range chunks, so competitive claims on later slides actually
  reach the analysis.
- A moat rating you supplied yourself is accepted instead of erroring out the scoring step.
- The positioning map now plots the researched coordinates; previously the map and report could render
  draft coordinates while the evidence-grounded ones sat unused.

### Added — market-sizing: catches the errors that silently shrink a market

- A percentage written as a fraction (`0.35` where `35` was meant) produced a market ~100× too small.
  It is now caught and surfaced as a high-severity warning in the report's Warnings section, not left
  on a stream no founder sees. The prompts also spell out that these values are percentage *points*,
  and which one narrows TAM→SAM versus SAM→SOM so the two can't be swapped.
- SAM and SOM convergence are now checked, not just TAM. A converging TAM previously hid an
  order-of-magnitude SAM or SOM gap presented as equally defensible.
- The "competitive landscape acknowledged" criterion is scored from what your deck actually says, via a
  new notes field — previously it was scored without ever seeing the deck.
- Validation verdicts are constrained to four honest states (validated / partially supported /
  unsupported / refuted), so an invented in-between label can't misrepresent how well a figure is
  sourced.
- A dollar amount like `$8M` written into a shell heredoc could be expanded away before it reached the
  artifact; quoting is now required throughout.
- The report's self-check now reads as a score with pass/fail/not-applicable counts.

### Added — later stages, more sectors, more geographies (all skills)

- Series C and Series D are accepted stages; the list previously ended at Series B, so a later-stage
  company had to mislabel itself. Three financial-model-review criteria that were auto-marked N/A at
  those stages (LTV/CAC shown, burn multiple tracked, dilution/ownership shown) are now scored.
- **Retail / physical-store and D2C** is a recognised revenue model with its own per-stage checks —
  store-level contribution, buildout capex per location, store payback, same-store versus new-store
  split, inventory as a runway risk, cohort maturation, shrinkage and returns.
- Gross-margin guidance covers hardware, consumer subscription and retail, and explicitly marks
  marketplace, transactional-fintech, hardware-subscription and usage-based models as contextual.
- India, Germany, France, Canada, Singapore and Australia are recognised by name and gate the same way
  as any other non-Israel geography.

### Changed — verdicts and wording you actually read

- **IC simulation reports a decline as "Decline".** The internal `pass` / `hard_pass` values rendered
  as a bare "Pass" in the headline verdict, the conviction gauge, the per-partner chips, the summary
  bar, the coaching commentary and the chat narration — which a founder can read as approval when it
  means the opposite. All of them now read "Decline" / "Decline — Hard Pass", and the report carries a
  legend for all four outcomes.
- **Internal plumbing no longer leaks into cap-table narration** — script and file names, `--flags`,
  exit codes, `W_`/`E_` warning codes, JSON, and step labels like "Lane 3" or "Context A". The
  first-run company-context lookup previously surfaced a "not found" exit status as though something
  had gone wrong.
- **The skills stop asking for what your materials already state.** Company name, stage, sector and
  geography are derived field by field from the deck or description, remaining fields are inferred from
  clear signals (currency, phone country code, address, a named round or round size, product category),
  and only genuinely unknown fields are asked about — with the derived values shown so you confirm
  rather than re-supply. Applies to deck-review, competitive-positioning, market-sizing and unattended
  ic-sim runs.
- **A generic ("illustrative") IC simulation stops inventing a fund.** It no longer fabricates
  portfolio holdings, skips portfolio-conflict analysis rather than checking you against made-up
  companies, and a fund-fit dealbreaker derived from the synthetic persona no longer forces a hard
  pass. The report states plainly that the thesis, partners, portfolio and any conflicts are fictional
  constructs. Startup-side dealbreakers still force a decline in every mode.
- **Where a debate and a score disagree, the divergence is reported** rather than reconciled away: the
  mechanical verdict is the headline, the mismatch stays as a caveat, and nothing is re-run to force
  agreement.

### Changed — where your deliverables land, and how results are handed off

- Deliverables now land in this run's own folder under `outputs/`, derived from the session identity.
  The old logic probed the filesystem, so a connected folder containing its own `outputs/` could
  receive the run's files, and a shell sitting above several sessions picked the alphabetically first
  one — meaning files could land in a different task's folder.
- Sub-agent results are handed off through per-run files instead of the message channel, with a
  permanent audit trail per run. If the hand-off file isn't visible to the orchestrator after one
  corrective attempt, the run degrades to the message channel rather than dying mid-pipeline.
- The coaching section can no longer be half-written, duplicated, or corrupted by its own punctuation.
  Insertion is done by a script rather than by the model editing your report: the commentary is carried
  as plain markdown so quotes and line breaks can't break transport, the result is self-checked in
  memory before anything is written, a re-run finds the section present and no-ops instead of adding a
  second one, and a run whose artifacts disagree on identity is blocked *before* the report is touched
  — with a named reason instead of a silently missing section.
- Cowork parity: bundled reference files, prior-step artifacts and uploads are located and passed
  correctly under Cowork's host-loop runtime, and writes that Cowork's `outputs/` mount refuses to
  delete are copied rather than moved.

### Changed — install and docs

- **The install instructions were wrong at almost every step, and are rewritten from a verified
  walkthrough.** Most consequentially: *syncing the marketplace does not install the plugin* — you still
  have to click the `+` on the plugin card. Every previous version of the instructions stopped before
  that, so anyone following them would sync and then find nothing installed. The Cowork path now leads
  (it is where these skills are actually used), the duplicate "Claude Desktop" section is merged into it,
  and "Sync automatically" is called out because it is what prevents the stale-plugin problem.
- **The `npx skills add` path is documented as not working — for every host, not just Claude Code.** The
  old text promised it "works with Claude Code, Cursor, Copilot, Windsurf" while the caveat below
  contradicted it, and that caveat addressed only Claude Code users. Skills resolve their scripts through
  the plugin root, which that layout does not create, so they fail on the first step anywhere.
- **Python prerequisites are stated where they apply.** Claude Code runs the scripts on your own machine
  and needs Python 3.10+ (plus `openpyxl` for Excel, `pdfplumber` for PDFs). Cowork's sandbox already has
  everything, so Cowork users install nothing.
- **New: what to expect on a first run** — that an analysis takes minutes rather than seconds, and where
  the reports appear (the task's Working folder under `outputs/artifacts/…` in Cowork; `artifacts/` in
  Claude Code). Neither was documented anywhere.
- **Troubleshooting is split by app.** Both remedies were previously Claude Code CLI commands under a
  heading about Claude Desktop, including a cache path Cowork does not use — so a Cowork user following
  them changed nothing.
- **New: a plain "not legal, tax or investment advice" line** on the cap-table skill, which advertises
  SAFE conversion math and a counsel-handoff packet.
- The cap-table deliverables list is no longer unconditional: the quick-answer path writes no artifacts,
  a lone instrument with no cap table returns an instrument-terms report, and the pre-money slider is
  priced-rounds-only.
- Skills are called "skills" throughout, matching what you see in Claude, rather than alternating between
  "skill" and "agent"; the "What it does" lists drop internal vocabulary for what the skill actually does
  for you. Old deep links to the per-skill sections still work.
- README gained a table of contents (now including the install paths); the per-skill "full workflow
  details" links are relabelled as the technical spec for the agent runtime rather than user reading; and
  the cap-table description drops internal vocabulary in favour of "every calculation traceable to a
  cited source", spelling out broad-based weighted-average (BBWA).
- CONTRIBUTING documents the pre-commit hook and the DCO sign-off gate, points at the security policy for
  vulnerability reporting, adds a Releasing section, states that participating means agreeing to the Code
  of Conduct, and adds a section on running the Cowork-runtime test gates locally.
- The bundled Sora typeface now ships its SIL Open Font License and copyright notice, as the license
  requires of any redistribution, with a third-party notices pointer under README's License section.

### Changed — privacy disclosure is now complete

- The README claimed the plugin "runs entirely inside your local Claude session". That was not true of
  three skills, and the gap is now stated plainly: **market sizing, IC simulation and competitive
  positioning search the web** as part of their work, so search queries derived from your materials pass
  through Claude to a search provider. Cap-table, deck review and financial model review never touch the
  network.
- A second egress was undisclosed entirely: **the competitive-positioning explorer's optional 3D view
  loads a charting library from a public CDN** the first time you open that tab. Every other generated
  file is self-contained and works offline.
- What was already true is unchanged and stays: no data is collected, transmitted or shared with lool
  ventures, and feedback remains opt-in and user-initiated.

### Changed — a coherent, theme-aware banner set

- Every skill now has a banner, including cap-table, which never had one — and each comes in a light and
  a dark version, so **GitHub dark mode no longer shows a glaring white slab**. The old banners baked an
  opaque near-white gradient across their right ~57%: designed for light mode only, and more than half of
  each image carried no information.
- The set now reads as one system: uniform line weight throughout (the IC simulation banner was filled
  artwork while every other was outline), strokes heavy enough to survive being scaled into GitHub's
  column, and the same survey motifs threading through all six.
- Banner alt text was repeating the heading immediately below it, so screen readers announced every skill
  twice. The banners are decorative and are now marked as such.
- Despite seven more images, `assets/` shrank from 6.09 MB to 2.67 MB — the header alone was 4.7 MB of
  resolution and an unused transparency channel that nothing could see.

### Fixed — financial-model-review

- The static review page no longer attempts a dead server round-trip. In Cowork the page is served from
  an ordinary origin, so its guard didn't hold and **Submit Corrections** fired a request to a server
  that isn't there — and if the origin answered `200`, the founder was told their corrections had been
  saved when nothing had been. It now skips the round-trip entirely and goes straight to the download,
  and the overlay says the file was *downloaded* (pending upload) rather than *saved*.
- A data-sparse model now reaches a finished report instead of stalling on a gate: when too few metrics
  are computable the producer declares the shortfall, the completeness gate passes with a partial-data
  warning, and the documented rule is to record the warning and proceed — never to fabricate a value to
  clear the gate.
- The missing-critical-data path now applies to spreadsheets, not just decks and conversational input,
  so a spreadsheet that verifiably lacks the fields no longer falls through it.
- Very large or oddly formatted Excel files no longer blow up extraction: a sheet whose declared range
  is ballooned by stray formatting is trimmed to its populated region, a pathological sheet gets a
  bounded read with the caps disclosed, and extraction warnings now surface in the output and the
  on-screen receipt.
- Cell references cited as provenance are correct when a sheet repeats a column header; two columns
  sharing a header previously collided, attributing a value to the wrong cell.
- The report's "Corrections Applied" table no longer shows `?` for every value, adds a reason column
  when reasons exist, shows a field the source didn't contain as "not in source", and summarises a
  replaced series as a row count.
- A review no longer crashes when an optional input block is present but explicitly empty.
- The final completeness check warns about unexpected files in the review folder, catching an artifact
  written outside the sanctioned pipeline.
- Passing checklist rows are one-line notes rather than full evidence paragraphs, so the criteria table
  is tighter and passing items never pad the coaching section.

### Fixed — deck-review

- Slide-count scoring had dead bands: a 7-slide deck and a 16–18-slide deck fell between the pass and
  fail rules and produced neither. Fail is now 6 or fewer / 19 or more, warn is 7–9 / 13–18.
- The "inconsistent company name" flag stops crying wolf. Your brand inside an email address, URL or
  domain, in ordinary lowercase prose, or as a plural or shared-root form no longer counts as name
  drift — only genuinely cased variants do.
- A deck that never states its stage no longer triggers a bogus stage warning. An absent stage is
  recorded honestly as "not stated" instead of being filled with a placeholder that then produced a
  "stage mismatch" or "out of scope" warning.
- Duplicate or non-sequential slide numbers in the source deck are surfaced as a warning instead of
  being silently absorbed, and downstream slide references are disambiguated.
- The review can no longer make a bad score disappear: pipeline problems are fixed and re-run, but
  content findings — critical checklist failures, extreme slide count, stage mismatch — are the honest
  verdict and are reported as-is, never re-scored or suppressed.
- A claim that your deck has no charts, photos, diagrams or logos must now be checked against the
  recorded per-slide visuals, citing the slides checked, before it can be made.

### Fixed — ic-sim

- Portfolio-conflict scoring uses the actual conflict findings, instead of defaulting to "not
  applicable" whenever that data wasn't in front of the scoring step.
- Two spurious "Schema Drift" notes no longer appear in every report: the per-run stamp carried by every
  artifact, and the portfolio field that is legitimately optional in generic mode.

### Fixed — cap-table

- A dollar figure printed with cents verified correctly instead of false-failing on the fractional
  part; conversely, a yes/no term the extraction asserts without a supporting quote in the document is
  now flagged as unverified rather than passing silently.
- Pointing the extractor at a source path that doesn't exist now fails loudly instead of degrading to a
  clean-looking "unverified" pass.
- Answering a freeform blocker with a mistyped field name now warns and names the valid fields, instead
  of accepting the answer and ignoring it.
- An option-pool target outside 0–100% is rejected with a named error rather than producing nonsense.

### Fixed — competitive-positioning

- Long labels on the defensibility-timeline chart are no longer clipped.

### Development

Contributor-facing only; nothing here changes what a founder installs or runs.

Regression coverage for Cowork-runtime behaviour now runs on every PR, via
[`cowork-harness`](https://github.com/yaniv-golan/cowork-harness) — a Cowork-runtime emulator used as a
dev-time CLI, not a runtime dependency and not part of the distributed plugin. Two token-free jobs:
static analysis over every skill body, agent, reference and command, and deterministic replay of
recorded Cowork runs. Recording itself remains local and paid, so replay verifies against recordings
that can lag the current skills — the gate is "no new regressions against the recorded baseline", not
"verified against live Cowork". Several of the founder-facing fixes in this release came out of that
lane rather than from unit tests, because they only reproduce inside Cowork's runtime: an HTML artifact
whose Submit button silently failed under Cowork's own serving origin, script paths that resolve in the
CLI but not in the VM, and an `outputs/` mount that refuses deletes.

The privacy guard gained a path-name layer — a denylisted name in a filename now trips it even when the
contents are clean — plus a denylist refresher. `CONTRIBUTING.md` documents how to run both Cowork
gates locally; `CLAUDE.md` and `cowork-tests/README.md` carry the details.

## [0.5.1] - 2026-06-18 — Fleet-wide hardening: audit remediation, brand theme, self-sufficient reports

### Highlights

A broad correctness, observability, and presentation pass across all six skills following 0.5.0's
cap-table introduction. The headline work: a full-repo audit remediation hardening every skill and
the shared scripts; the lool brand theme applied to every generated HTML artifact; self-sufficient
reports that read standalone without the chat context; a founder feedback channel; deterministic
`run_id` stamping, artifacts-root resolution, and fleet-wide outputs-tree safety; and a large
cap-table extraction- and math-correctness pass. New drift-contract and renderer-key-coverage test
suites lock each skill's prose to its producers, and a fleet-wide cowork-harness replay gate
exercises every skill under Cowork's runtime token-free on each PR — so these fixes can't silently
regress.

### Added — feedback channel

- `/founder-skills:feedback` command — drafts a bug report, idea, help request, or "founder win"
  and hands the user a prefilled GitHub Issue / Discussion link (or a private `mailto:` to
  founder-skills@lool.vc) to submit themselves. The plugin transmits nothing automatically; a
  privacy hard-stop keeps company names, numbers, file paths, and transcript data out of the draft.
- Every generated report (Markdown + HTML) now carries a "Share feedback" link in its footer,
  routing to the Ideas & Feedback discussion category.
- Skills surface `/founder-skills:feedback` on a blocked/failed run and on unsolicited sentiment
  (once per session, never routine).
- cap-table report footer harmonized with the other five skills (now links back to the repo and
  lool ventures; drops the internal rule-pack version line).

### Added — self-sufficient reports

- Every skill's report (Markdown + HTML) now stands alone — it carries the context, definitions, and
  provenance needed to be read and shared without the originating chat session. Rolled out across
  all six skills (deck-review, market-sizing, ic-sim, competitive-positioning,
  financial-model-review, cap-table).

### Added — lool brand theme

- The lool visual identity is applied to every generated HTML artifact across all six skills:
  design-token CSS plus the Sora variable font (OFL) embedded base64-inline so artifacts stay
  self-contained, with a footer credit. A theme-sync contract test keeps each skill's `_theme.py`
  copy identical.

### Added — cowork-harness replay gate

- A token-free **replay** PR gate (`.github/workflows/cowork-replay.yml`) exercises the skills under
  Claude Cowork's runtime via `cowork-harness` (≥ 0.7.1). Recording is live (staged agent + Docker);
  replay/verify run token- and agent-free in stock CI. **11 committed cassettes:** six cap-table
  scenarios (Lane 1/2/4 extraction, anti-hallucination, priced-round + BBWA anti-dilution,
  fast-assess routing) plus a per-skill fleet-parity smoke for market-sizing, ic-sim,
  competitive-positioning, deck-review, and financial-model-review — each proving the artifacts-root
  resolver lands deliverables at `outputs/artifacts/<skill>-<slug>/` with no host-path leak and no
  `outputs/` delete.
- The suite lives at the repo root (`cowork-tests/`), **outside** the hashed plugin mount, so editing
  a scenario or fixture no longer churns the cassette staleness fingerprint. Staleness is further
  **scoped per skill** — each scenario declares the skill it exercises, and
  `founder-skills/.cowork-hashignore` drops `tests/` (pytest is not skill runtime) — so editing one
  skill re-stales only its own cassette.
- The CI gate is split: **privacy is hard-fail** (class-scoped `--allow-domain` / `--allow-email`
  allowlists; only synthetic email domains permitted) and **staleness is warn-only** (the whole-plugin
  mount otherwise re-stales every cassette on any skill edit). An **email canary** must trip under the
  same allowlist, so the job fails if the email tripwire is ever silently disabled. All fixtures are
  synthetic.

### Added — other

- **cap-table:** Articles-of-Association extraction dispatch template (Lane 1); `--mode=grid` dumps
  the Lane-3 cell grid deterministically; vision fallback for image-only documents in the evidence
  verifier.
- **cap-table — deterministic Lane-3 (freeform spreadsheet) mapping.** Replaces the agent-authored
  heredoc that wrote Lane-3 artifacts with a pure, unit-tested mapper (`freeform_mapper.py`, behind
  `extract_cap_table.py --mode=freeform-emit`). A closed agent↔producer contract
  (`references/schemas/freeform-role-map.json`) pins block types + column-role values to schema
  fields, so the structure-detection sub-agent and the producer can't drift. Off-contract roles and
  fields freeform can't supply (a note's `interest_rate_type`, a preferred series' issue price, an
  enum `plan_type`) become founder-confirmation **blockers** (a human-in-the-loop gate; answers
  return via `--answer BLOCK.FIELD=VALUE`) rather than fabrications. Per-target-array stable instrument
  ids, merged-cell/sheet-qualified-range handling, and a `cap_state.py` `E_NO_EQUITY_BASE` guard that
  turns the old silent all-zero-snapshot (founders + option_pool both absent while instruments are
  present) into a loud error.
- **deck-review:** resume now preserves same-run pipeline artifacts across the stage-gate
  round-trip.

### Changed — determinism & observability

- **Unified `run_id` stamping.** All producers now inject `metadata.run_id` via a required
  `--run-id` CLI flag, so every artifact in a run shares one identifier and compose can enforce
  parity. Applied across ic-sim, market-sizing, competitive-positioning, deck-review,
  financial-model-review, and cap-table; a static orchestration guard asserts CLI-stamping producer
  pipes carry `--run-id`.
- **Deterministic artifacts-root resolution.** The inline `ARTIFACTS_ROOT` path computation in each
  SKILL.md Step 0 block was guidance the agent paraphrased, not code it ran verbatim — it kept the
  intent ("under `outputs/`") but dropped the detection, landing `outputs/` in one run and
  `outputs/artifacts/` in another, desyncing cross-skill `find_artifact.py` resolution and
  path-based assertions. All six skills now invoke a shared `scripts/resolve_artifacts_root.py`
  (fixed resolution order, deterministic, creates the dir) as one opaque command.
- **Outputs-tree safety (fleet-wide).** In Cowork the per-run work dir is the promoted, user-visible
  `outputs/` tree, where staging scratch or deleting artifacts is unsafe — Cowork can deny the delete
  and the parity gate flags it. All six skills now stage sub-agent JSON in a `/tmp` mktemp dir and
  overwrite each artifact in place every run instead of a fresh-start `rm`; a fresh per-run `run_id`
  plus compose's `STALE_ARTIFACT` parity check backstop any skipped-step leftover. deck-review keeps
  its `setup_run.py` resume lifecycle, with its `--clean` delete now tolerant of a Cowork-denied
  delete. A `test_skill_orchestration` guard flags any `outputs/`-tree `.staging` path or `rm`.
- **CI version-bump filter** now requires in-plugin Markdown bumps, matching the documented
  versioning policy.

### Fixed — fleet-wide audit remediation

A full-repo audit hardened all six skills and the shared scripts. By area:

- **cap-table:** math correctness (conversion-cap-price fallback, anti-dilution baseline, donut
  palette, summary counts); extraction correctness (AoA merge, Carta fabrication guard, share-suffix
  parsing); pre-money SAFE now honors the document's two conversion branches and a pool-inclusive
  denominator; warrants join the broad-based anti-dilution base and the rule text matches the NVCA
  charter it cites; the solver flags economically impossible rounds instead of returning garbage;
  note conversion surfaces as a dilution driver; anti-dilution meta keys excluded from the explorer
  donut/legend; `pdfplumber` declared so a missing parser blocks the hallucination gate rather than
  silently degrading; rule-pack version single-sourced and bound into every producer; the dead
  ITA-SAFE citation replaced with live gov.il primary sources and honest Carta provenance.
- **financial-model-review:** burn multiple was divided by net-new ARR instead of monthly ΔMRR (a
  12× overstatement) — fixed, plus three more 12× period-mismatch bugs and a GRR sanity guard;
  partial models now evaluate all 46 checklist items and data rows survive header detection; the
  extracted-values review is a hard stop gate rather than a drive-by; stops overstating a
  default-alive company as "on track to profitability"; magic number uses the full S&M base and
  Rule of 40 uses realized YoY with honest benchmark labels (dead Mosaic citations retired); the
  checklist sub-agent no longer self-gates (gating belongs to the producer); MARKER_COLLISION
  pre-scan before status render; present-but-null numeric fields guarded in math and validators.
- **market-sizing:** unit-aware sensitivity parameter values — the Value column holds the input
  parameter (currency / count / percent), so the old USD-for-low/high, raw-number-for-base rendering
  printed percentages and counts as dollars; a new `_fmt_param_value` formats each cell by parameter
  name. Also: tolerates non-numeric deck claims and null notes; compose reordered so
  MARKER_COLLISION reflects in both status and the Warnings section.
- **deck-review:** 3-value `ai_company_status` with producer-applied AI-criteria gating and verbatim
  pass-through; canonical scoring IDs enumerated in dispatch templates; `checklist.py` omits null
  evidence/notes, requires `--run-id`, and fails closed on `-o` validation errors; `gate_state`
  answer handling survives corrupt files; resume detection moved into `setup_run.py`; visualize
  legend color and gauge fixes.
- **ic-sim:** derives `consensus_strength`, fixes warnings ordering, guards renderers against
  malformed artifacts; resolves cross-owned straggler findings shared with market-sizing.
- **competitive-positioning:** `EVID_02` mode-gating prose corrected; scripts hardened against
  malformed artifacts; `checklist.py` gains `--input-mode`/`--run-id` flags; all three
  artifact-integrity warning codes named in SKILL.md.
- **shared scripts:** `find_artifact.py` conformed to the `--pretty` / `-o` / JSON-stdout script
  convention; `founder_context.py` now performs a real recursive deep merge; `marketplace.json`
  drops the top-level `description` to match the documented format.

### Tests

- **Drift-contract suites** pin each skill's SKILL.md prose to its script source across all six
  skills, and surfaced/fixed several dead `coaching_payload` shell-variable captures and an
  input-mode attribution bug.
- **Renderer key-coverage** tests across all six skills assert every produced key is either rendered
  or explicitly excluded.
- Regression suites added for the cap-table extraction and math fixes.

### Docs

- README adds the cap-table skill section and documents six agents and Python 3.10+; CONTRIBUTING and
  SECURITY include cap-table; VERSIONING clarifies that tags gate releases and reconciles the
  no-bump cases; CLAUDE.md sync-test-repo framing and e2e figures corrected.

## [0.5.0] - 2026-06-10 — New skill: cap-table; financial-model-review hardening

### Highlights

This release ships the cap-table skill for the first time and completes a pre-distribution hardening
pass on financial-model-review. Users upgrading from 0.4.7 get both skills in their first-ever
stable form — neither was available in any prior distributed release.

*Versions 0.4.8–0.4.11 were internal development versions and were never distributed; all of their
changes ship in 0.5.0.*

### Added — new skill: cap-table

The cap-table skill extracts structured terms from SAFEs, convertible notes, term sheets, articles
of association, and Carta XLSX exports, then runs a layered math pipeline to produce a
counsel-handoff packet and founder-readable report.

#### Extraction

Four lanes share a common anti-hallucination validator:

- **Lane 1 — unstructured instruments (PDF/DOCX).** A sub-agent extracts; the validator enforces
  form-dependent required-field gates, normalizes the discount-rate multiplier-vs-rate trap, and
  routes warrants and non-instruments to clean classification. Accepted instrument types include
  all five YC SAFE forms (post-money cap, uncapped MFN, cap-and-discount, pre-money legacy cap,
  pre-money legacy cap-and-discount), convertible notes, convertible loan agreements (Israeli
  CLA/CIA), YC convertible securities, term sheets, option plans, and warrants.
- **Lane 2 — Carta XLSX exports.** Verified sheet-name fingerprint, Convertible Ledger parsing,
  discount normalization, and cancelled-record skipping. `--mode=pulley` routes to freeform with a
  structured blocker until a verified Pulley workbook fingerprint is available.
- **Lane 3 — freeform spreadsheets.** Sub-agent identifies cell semantics; validator gates per-field
  confidence.
- **Lane 4 — structured JSON paste / conversational.** Pre-built JSON or chat-described cap tables
  still flow through `--mode=validate` for schema enforcement.

A four-layer verification stack runs by default on every Lane-1 extraction:

- **Forward verification** — three-layer check catches hallucinated values not present in the source
  document. Calibrated at 3.6% FPR / 100% TPR on verifiable docs; handles 8 PDF
  extraction-artifact patterns (CID-encoded fonts, image-only PDFs, DocuSign overlays, etc.).
- **Invariant checking** — per-field real-world bounds and cross-field math invariants. 0% FPR /
  63% TPR on ×1000 unit-error perturbations. Hard math impossibilities block; soft bounds warn-only.
- **Deterministic backstop extractors** — regex-based span-preserving extractors for SAFEs
  (`purchase_amount`, `discount_multiplier`, `valuation_cap`, `issuance_date`, `investor_name`).
- **Cross-check** — demote-only confidence modulator when sub-agent and backstop disagree.
  Agreement never bumps; informational only.

An optional fifth layer (backward verification via fresh-sub-agent re-extraction) catches
semantic-confusion errors and is dispatched when the `attention_needed_fields[]` receipt signals
high-stakes ambiguity.

#### Math pipeline

Cap state → SAFE/note conversion → option-pool top-up → coupled priced-round solver with
anti-dilution → flip scenarios → report assembly.

- **SAFE conversion** — all five YC forms including the pre-money (legacy) family. Post-money forms
  lock `purchase/cap` of Company Capitalization measured immediately prior to the equity financing
  (= existing shares + pre-existing unissued pool + all converting securities), then are diluted by
  the new-money round like all other holders — per the YC post-money SAFE definition and rule
  `safe.company_capitalization_yc_post_money`; pre-money forms use the pre-financing FD as
  denominator — the two families produce materially different cap tables.
  MFN auto-bind: when an uncapped MFN SAFE has `mfn_provision.elected_against_safe_id` pointing to
  a resolved sibling, the election is pre-resolved before iteration. Transitive MFN chains resolve
  to a fixed point (bounded by `len(safes)` iterations). Genuinely uncapped MFNs still hit the
  cycle guard.
- **Note conversion** — seven-branch enum (`cap_conversion` / `discount_only` /
  `maturity_floor_conversion` / `maturity_discount_only` / `maturity_outstanding` /
  `maturity_forgiven` / `threshold_not_met`) plus override branch. Accepted subtypes: standard
  convertible note, Israeli CLA, YC convertible security.
- **Option-pool top-up** — four `target_basis` modes. When `pre_money` basis produces a zero top-up
  because the existing pool already meets target, the skill issues a clarifying question so the
  founder confirms pre-money vs post-close-unallocated intent.
- **Coupled priced-round solver** — fixed-point iteration couples SAFE conversion, note conversion,
  pool top-up, new-money issuance, and anti-dilution (BBWA and full ratchet) in a single Banach
  loop. Per-series knobs: `ad_trigger_basis`, `ad_a_denominator_basis`, `ad_cp2_floor`,
  `ad_carve_outs`. Convergence guards: sign-flip damping (α=0.5), Aitken Δ² acceleration,
  fallback fence, 200-iteration hard cap. When anti-dilution fires, the report renders a three-way
  founder-ownership narrative: pre-AD baseline / coupled post-AD headline / delta in pp.
- **Warrants as first-class instruments.** Vested outstanding warrants are included in
  `fully_diluted_shares`; unvested are surfaced separately and excluded per the YC primer narrow
  `company_capitalization` convention. A deterministic pre-round pump applies cash-exercise or
  net-share settlement for warrants whose exercise date precedes the transaction date. Preferred-stock
  warrants route into the matching series. Three settlement variants are explicitly rejected with
  structured errors: debt cancellation, share-for-share exchange, VWAP-cashless.
- **Dual-class / super-voting.** When any holder carries `voting_rights_multiple != 1.0`, the report
  adds a voting-pct column to the cap-table summary.
- **AoA-only engagements.** The skill accepts an Articles of Association with no
  SAFEs/notes/grants. The AoA extractor populates `preferred_series[]` and `aoa_findings` (9
  findings: drag-along threshold, Section 102 plan, liquidation preference above 1×, participation,
  dividend provisions, protective provisions, bring-along threshold, pay-to-play detection, full
  ratchet presence). The report renders an AoA-summary view.
- **Fast-assess mode.** A 1-page founder-facing markdown report in under 60 seconds for
  conversational queries that don't need the full pipeline. Step 0 routes between fast-assess and
  full pipeline based on whether a document is attached.
- **Israeli ↔ Delaware flip analysis.** `flip_scenario.py` models the 1:1 share-for-share flip.
  QSBS eligibility gates against the post-flip Delaware C-corp issuance date (`flip_closing_date`),
  not the pre-flip Israeli date.
- **Counsel-handoff packet.** Standalone JSON + Markdown deliverable (`counsel_packet.py`).

#### Rule pack and counsel items

~75 rules across 10 domains, citing NVCA Model COI §4.4.4/§4.4.5, YC SAFE primer, Cooley GO
down-round article, and ITA §102. The `counsel_review` flag is a reliance boundary — a rule can be
`confidence: high` and `counsel_review: true` simultaneously. The rule-audit pipeline runs in two
phases: `--phase=pre_math` writes a gating block before math runs; `--phase=post_math` composes
watchlist and counsel items after. The founder-facing report splits the watchlist into "Active"
(applies to this engagement) and "For-Reference Annotations" (tracked but not currently applicable).
Per-scenario completeness lines expand the bare enum value into plain language so founders know
whether legal/tax math ran.

#### Scope and explicitly rejected inputs

The following are rejected with structured errors or surfaced as counsel items rather than silently
mis-modeled: RSU grants (`E_RSU_NOT_MODELED`), cumulative-preferred dividend math
(`E_DIVIDEND_FIELDS_REMOVED` — dividend provisions surface in `aoa_findings` for counsel-handoff),
warrant repricing under issuer AD clauses, three exotic warrant settlement variants (debt
cancellation / share-for-share exchange / VWAP-cashless), non-1:1 flip ratios, non-unity preferred
voting (surfaces `W_PREFERRED_VOTING_NON_UNITY_NOT_MODELED`), Pulley XLSX (structured blocker routes
to freeform), LLC structures and profits-interests, SPAC/de-SPAC mechanics, multi-class liquidation
waterfalls at exit, 409A valuations, pro-rata side-letter exercise, cumulative preferred dividends,
83(b) elections.

#### Engineering reliability

Every consumer reads artifacts through a typed loader (`_artifact_io.py`) that validates
`schema_version` stamps and re-runs 14 semantic invariants at the load boundary, including FD-sum
equality, CCP ≤ OCP ratchet-down, warrant vested_flag / exercise_event_date parity, and
mirrored-field drift detection. Solver convergence guards (damping, Aitken acceleration, fallback
fence) ensure deterministic outputs. 1,588 non-e2e tests pass. The property-based solver
convergence harness and fresh-AI replay tests are scheduled as a v0.5.1 follow-up.

### Fixed — all skills

- **Claude Cowork in-VM script discovery.** `${CLAUDE_PLUGIN_ROOT}` substitutes to a host-side
  path that does not exist inside the Cowork session VM — non-empty but invalid — so the documented
  Glob fallback never fired and agents hit "No such file" with no cue to fall back. The fallback
  condition in all six SKILL.md files now also fires when the resolved path does not exist.
  (Developed internally as v0.4.11; first ships here — satisfies downstream skills declaring
  `requires founder-skills ≥ v0.4.11`.)
- **Version-ref policy (fleet-wide).** Removed internal release markers, sprint labels, and
  audit-cycle references from SKILL.md files, agent bodies, schema descriptions, rule pack fields,
  and inline comments across all skills. A new contract test
  (`test_no_internal_version_refs_in_user_facing_files`) enforces this policy on every PR.

### financial-model-review: pre-ship hardening

A focused pre-distribution hardening pass carried in this release. All changes are in `founder-skills/skills/financial-model-review/` and its tests.

#### Orchestration contract fixes

- **CHECKLIST dispatch shape corrected.** The sub-agent return shape now includes `company` (copied verbatim from `inputs.json`) and `metadata: {"run_id": "<RUN_ID>"}` alongside `items`. This ensures `checklist.py` can apply profile-based auto-gating (stage/geography/sector/model_format) and that `checklist.json` carries a `run_id` consistent with the other three producer artifacts. Context B coaching dispatch was structurally blocked on every run due to the missing `run_id`; that is now fixed.
- **Checklist ID enumeration corrected (`BRIDGE_36..38`).** SKILL.md and the agent body both previously referenced non-existent `SCENARIO_36..38` IDs while double-booking positions 36–38. The canonical set from `checklist.py` is `METRIC_33..35, BRIDGE_36..38, SECTOR_39..44, OVERALL_45..46`. Sub-agents following the corrected prompt will no longer emit unknown IDs that `checklist.py` rejects.
- **`commentary.json` authoring step added.** `verify_review.py --gate 2` requires `commentary.json` for quantitative reviews, but no workflow step produced it. Added an explicit agent-authored heredoc step (after Step 7, before Step 8b) with schema reference. Cleanup list extended to cover this and other previously missing artifacts (`extraction_validation.json`, `corrected_inputs.json`, `extraction_corrections.json`, `corrections_from_agent.json`, `commentary.json`, `explore.html`, `review.html`).
- **`coaching_payload` now printed, not captured.** The `COACHING_PAYLOAD="$( ... )"` assignment wrapped the extraction in command substitution, sending output to a shell variable that neither persisted between Bash calls nor reached the tool result. Changed to a bare `python3 -c '...'` invocation so the payload prints directly to stdout.
- **UE and runway dispatches replaced with direct pipes.** `UNIT_ECONOMICS` and `RUNWAY_SCENARIOS` sub-agent dispatches were pure pass-through round-trips (read `inputs.json`, return `inputs.json`), exposing multi-KB financial figures to LLM transcription errors. Both steps now use `cat "$REVIEW_DIR/inputs.json" | python3 "$SCRIPTS/<producer>.py" ...` directly from the main thread.
- **INPUTS_REVIEW dispatch uses deterministic corrected-payload path.** Sub-agent return shape now explicitly excludes `changes` and `base_hash` keys, routing through the deterministic `corrected`-shaped path in `apply_corrections.py`. The broken `base_hash`-verification patch path (which always errored because the sub-agent has no Bash) is avoided.
- **`dispatch_contracts.json` fixtures updated.** Synced with the direct-pipe UE/runway change and the `overall_status` field rename.

#### `verify_review.py` fix — default-alive companies

Gate 2 no longer blocks publication for profitable or default-alive companies. Previously any review where no scenario had `runway_months` (correct for a company that never runs out of cash) caused exit 1. Fixed to: only error if no runway **and** no scenario is default-alive.

#### `coaching_payload` field fixes

- **`runway_months` added.** `_emit_coaching_payload` in `compose_report.py` now extracts the base-scenario `runway_months` (may be `null` for default-alive companies) and includes it in the payload.
- **`overall_status` rename.** The agent success payload field was renamed from `unit_economics_status` to `overall_status`, correctly mapped to `coaching_payload.summary.overall_status` (the checklist overall status). Dispatch-contract fixtures updated to match.

#### HTML self-containment and escaping

- **Chart.js vendored into `explore.py`.** The explorer previously loaded Chart.js from a CDN. The Cowork iframe sandbox blocks external fetches; offline `file://` viewing also broke. Copied the vendored `chart.min.js` (already used by `competitive-positioning/scripts/explore.py`) into `financial-model-review/scripts/vendor/` and switched to inline embedding.
- **`</script>` injection hardening.** Founder-document-derived data (company names, LLM-extracted strings) embedded as JSON in `<script>` blocks now has `<` escaped to `\u003c` at every embed site in both `explore.py` and `review_inputs.py`.
- **HTML escaping for warning/commentary fields.** Extraction-warning `candidates` and `untraceable[*].role` strings in `review_inputs.py` are now wrapped with `html.escape()`. Commentary fields (`callout`, `highlight`, `watch_out`) in `explore.py` are assigned via `textContent`/`createTextNode` instead of HTML string concatenation.
- **Scenario labels and banner title escaped** via the shared `_esc()` helper throughout the explorer.

#### `review_inputs.py` hardening

- **Kill-port guard targets only own instances.** `_kill_port` previously sent SIGTERM to whatever process owned the port; now checks the process command line contains `review_inputs.py` before signalling.
- **`GET /api/feedback` returns 405.** The handler previously returned the stored corrections payload to any local caller; changed to an explicit 405.
- **Static-mode receipt carries `ok` and `bytes` keys**, aligned with the receipt shape used by `visualize.py` and `explore.py`.

#### Input-pipeline robustness

- **Structured `READ_ERROR` on corrupt corrections upload.** `apply_corrections.py` previously produced a raw Python traceback when the uploaded corrections file was corrupt; now emits `{"status": "error", "errors": [{"code": "READ_ERROR", ...}]}` consistent with every other error path.
- **BOM-tolerant CSV reading.** `extract_model.py` now opens CSV files with `encoding="utf-8-sig"`, so Windows Excel exports parse correctly instead of producing a `"﻿Month"` header that silently fails column matching.
- **Root-dir write guard in `validate_extraction.py`.** Added the same output-path root-directory guard that every sibling script already has.

#### Heuristic guards

- **Scale-fix requires ≥ 2 corroborating fields.** `validate_extraction.py --fix` previously applied a ×1000 scale correction if any scale indicator was present and values appeared implausible, even when only one monetary field was populated (insufficient evidence for majority vote). Now requires at least 2 monetary fields.
- **Post-fix plausibility check.** After applying a scale correction, `validate_extraction.py --fix` verifies the corrected values are plausible before writing; skips and warns if the corrected values are still implausible.
- **Mixed/unknown periodicity uses multi-multiplier scan.** Traceability checks on models where `periodicity_summary` is `"mixed"` or `"unknown"` previously scaled as monthly (×1), producing spurious `REVENUE_TRACEABILITY` warnings on quarterly or annual models. Now tries ×3 and ×12 for `"mixed"`, and skips periodicity-aware scaling for `"unknown"`.

#### Analysis fixes

- **`monthly_total` fallback in expense-coverage check.** `validate_inputs.py` `EXPENSE_COVERAGE_SUSPECT` now reads `revenue.monthly_total` when `revenue.mrr.value` is absent, avoiding false-positive critical warnings for companies that express revenue via monthly total rather than MRR.
- **Sub-score `None` semantics for inapplicable categories.** `checklist.py` `business_quality_pct` previously returned `0.0` when zero business items were applicable; now mirrors the `None` pattern used by `model_maturity_pct` so downstream display code treats it as "not computed" rather than "zero quality."
- **Near-zero cash warning guard.** `compose_report.py` `RUNWAY_INCONSISTENCY` check now requires `abs(inputs_cash) >= 1000` before computing a delta percentage, avoiding false positives near zero.
- **Breakeven note.** `runway.py` now emits a human-readable note when `monthly_net_burn = 0` (breakeven), instead of "Infinite" for every row of the burn-sensitivity table.
- **Negative USD formatting.** `visualize.py` `_fmt_usd` now handles negative values with `"-" + _fmt_usd(-value)`, producing `"-$200K"` instead of `"$-200,000.00"` (which overflowed SVG label slots on the runway chart's Y-axis).
- **`bench` initialized to `None`.** `unit_economics.py` declared `bench` as annotation-only; initialized to prevent potential `UnboundLocalError` on refactoring paths.

#### Version-ref policy cleanup (fleet-wide)

A new contract test (`test_no_internal_version_refs_in_user_facing_files`) now enforces the version-ref policy fleet-wide on every PR. As part of this pass: removed internal version markers from the financial-model-review SKILL.md and agent body; converted the agent-body changelog section into present-tense instructions; cleaned up garbled arithmetic in the agent body; applied the same removal to `agents/deck-review.md` (had one stale reference).

#### Schema-doc drift fixes

- `references/schema-inputs.md`: `company.stage` enum now lists all five values; both `revenue_model_type` enum tables now list all 10 canonical values; `model_format` pipeline-effects subsection moved below the `company` field table; `--strict` semantics note corrected (blocks on high-severity warnings only).
- SKILL.md: `--sector-type` valid-values list extended to include `transactional-fintech`; stale Context B preamble replaced with accurate description; `metadata.run_id` requirement scoped to the four producer artifacts.

#### CI registry wiring

- `financial-model-review` added to `compose_invocations.py` registry (`_COMPOSE_FLAGS` and `_RUN_ID_MUTATION_TARGET`).
- `financial-model-review` added to `COACHING_SKILLS` in `test_compose_invariants.py`.
- Fixture directory `tests/fixtures/financial-model-review/` populated with `inputs.json`, `checklist.json`, `unit_economics.json`, `runway.json` — the shared `coaching_payload` + `STALE_ARTIFACT` invariant suite now exercises this skill.
- New `test_fmr_skill_contract.py`: CHECKLIST ID enumeration, SKILL.md/agent body ID consistency, fleet-wide internal-version-ref policy enforcement.

### Out of scope for v0.5.0

Surfaces-based counsel-packet rendering and tag backfill across the existing ~70 rules, property-based solver convergence harness, fresh-AI replay tests. All three are scheduled for v0.5.1 follow-ups; the internal contract spec lays out the design.

## [0.4.7] - 2026-05-19

### Highlights

Gives `competitive-positioning`'s research sub-agent the `WebSearch` tool it was always dispatched to use, so competitor research and moat-trajectory evidence are honest rather than guessed from training data.

### Fixed

- **`competitive-positioning`: sub-agent had no network tools but was dispatched to research competitors.** SKILL.md Steps 4 (LANDSCAPE_RESEARCH), 5a (MOAT_SCORING), and 5b (POSITIONING_SCORING) dispatch the sub-agent with prompts asking for `evidence_source: researched | agent_estimate` (and Step 5a's `trajectory: building/stable/eroding`, which is inherently research-dependent). The agent's `tools:` allowlist was `["Read", "Edit", "Glob", "Grep"]` — no network access — and Step 4 explicitly forbade the main thread from doing the research either. Net effect since the skill shipped: every `evidence_source: "researched"` stamp was a training-cutoff guess wearing a research label. CHECKLIST (Step 6) is unaffected (artifact grading only, no research).

### Changed

- **`competitive-positioning` agent now declares `WebSearch`** in its `tools:` allowlist. Cowork's named-sub-agent dispatch is strict allowlist mode — empirically verified via a probe (a sub-agent declared with `tools: [Read, Edit, Glob, Grep]` receives exactly those four names; no MCP leakage, no default-toolset injection). With `WebSearch` declared, Phase A enrichment, moat trajectory scoring, and positioning-axis evidence become honest.
- **`competitive-positioning` SKILL.md dispatch prompts** (Steps 4, 5a, 5b) now reference `WebSearch` explicitly. The "Do not do the landscape research yourself in the main thread" instruction in Step 4 is retained — research now runs in the sub-agent's isolated context, where it belongs. Phase B (gap detection) is also instructed to use `WebSearch` for discovering missing competitor categories.
- **Producer-script JSON schemas unchanged.** The dishonesty was upstream of `validate_landscape.py` / `score_moats.py` / `score_positioning.py`; the schemas themselves were always correct.

### Added

- **`tests/test_cowork_invariants.py::test_research_agents_declare_websearch`** — new regression detector. Agents in `_AGENTS_REQUIRING_WEBSEARCH` (currently `{"competitive-positioning"}`) must declare `WebSearch`. Future refactors that strip it from the allowlist will fail CI. The docstring of `test_agent_declares_no_dangerous_tools` is updated to reflect that the "all agents declare exactly Read/Edit/Glob/Grep" property no longer holds — WebSearch is an intentional addition.

### Notes

- The fix corrects a real defect but the diff is small (one `tools:` addition + four dispatch-prompt clarifications). The original v0.4.7 plan considered the "main-thread does research, sub-agent structures the data" pattern used by `market-sizing` and `ic-sim`, but a sub-agent probe in Cowork (`/tmp/cowork-tool-probe/` locally) settled that `WebSearch` *is* available to sub-agents — only `WebFetch` (the plain name; `mcp__workspace__web_fetch` IS available) and `Bash` (replaced by `mcp__workspace__bash` in the default sub-agent toolset, not via deferred MCP tier as the allowlist file's comment suggested) follow the documented exclusion model. A separate follow-up will correct the false-premise comments in `cowork_async_subagent_filter.py` and the sibling skill docs.
- **No artifact schema bump.** `schema_version` strings for competitive-positioning artifacts are unchanged — consumer plugins downstream of this skill will not see a version-pin break.

## [0.4.6] - 2026-05-13

### Highlights

Fixes a `market-sizing` gap where deck TAM/SAM/SOM figures stated under non-canonical keys silently bypassed deck-vs-computed reconciliation, and adds a narrative escape hatch for deck claims that don't fit the canonical shape.

### Fixed

- **`market-sizing`: non-canonical `existing_claims` keys silently bypassed deck-vs-computed reconciliation.** When a deck stated TAM/SAM/SOM figures under non-canonical keys (e.g., `SAM_Israel_only`, `TAM_global`), both the `DECK_CLAIM_MISMATCH` warning and the report's provenance section's `deck_claim` / `delta_vs_deck_pct` columns silently returned `None` — `compose_report.py` and `visualize.py` look up `tam`/`sam`/`som` by exact lowercase name via `dict.get()`. The skill produced a complete report with no signal that comparison had been short-circuited, allowing downstream framing to treat a missing deck figure as a wrong deck figure.

### Added

- **`EXISTING_CLAIMS_SHAPE` warning** (medium severity, code #17 in `compose_report.py validate_artifacts()`) surfaces non-canonical keys or non-dict types in `inputs.existing_claims`. Acceptable via `accepted_warnings`; does not block the report.
- **`existing_claims_detail` field** in `inputs.json` — escape hatch for deck claims that don't fit the canonical `{tam, sam, som}` flat shape (regional sub-SAMs, time-anchored figures, alternative TAM frames). Documented in `artifact-schemas.md`; rendered as a new "Deck Claims (Narrative)" sub-section in the report (between sizing-table and assumptions). Does NOT participate in reconciliation.
- **`deck_coverage` field** in `coaching_payload` — nullable structured signal indicating which canonical figures the deck stated vs left null. Shape: `null` when no canonical figure was stated, otherwise `{"deck_reviewed": true, "stated": [...], "missing": [...]}`. Additive in `v0.4.2-market-sizing` (schema_version unchanged — three literal pins would break for zero consumer benefit).
- **Coaching framing guidance** in `agents/market-sizing.md` and `SKILL.md`: when `deck_coverage.missing` is non-empty, frame as "deck should also show {missing}" — explicitly NOT "understatement." When `EXISTING_CLAIMS_SHAPE` is present, do not trust `deck_coverage = null` as "deck wasn't reviewed"; branch coaching around the warning and the new narrative section instead.
- 21 new regression tests in `tests/test_market_sizing.py`: 10 `EXISTING_CLAIMS_SHAPE` cases (incl. non-dict types, uppercase canonical, canonical-null happy path), 2 `_compute_provenance` lock-in tests with tripwire docstrings documenting the contracted division of labor (warning = shape signal; provenance = numerical signal, stays neutral on shape errors), 3 narrative renderer cases, 6 `deck_coverage` cases.

### Changed

- `SKILL.md` heredoc template for `inputs.json` writes `"existing_claims": {"tam": null, "sam": null, "som": null}` + `"existing_claims_detail": null` (was `"existing_claims": {}`). Backward-compatible: empty-dict legacy templates continue to pass without warning.
- `WARNING_SEVERITY` totality test updated 19 → 20 codes.

## [0.4.5] - 2026-05-10

### Highlights

Adds a skill-quality CI pipeline — contract tests, compose invariants, and a deck-review end-to-end smoke — that runs on every PR and gates releases on tag-push.

### Added

- **Skill-quality CI** — new GitHub Actions workflow `.github/workflows/skill-quality.yml` runs three layers, ordered by speed:
  1. **Contract tests** (per-PR): SKILL.md frontmatter invariants enforced via YAML parse (`user-invocable: true` present, `disable-model-invocation` absent, braced `${CLAUDE_PLUGIN_ROOT}`); per-agent persistence-tool-name compatibility against Cowork's sub-agent tool registry; sub-agent-cue-followed-by-bash-block regression detector; SKILL.md does-not-depend-on-SessionStart-hook invariant (Cowork plugin hooks don't fire).
  2. **Compose invariants** (per-PR): every skill's `compose_report.py` emits a structured `coaching_payload` block; `STALE_ARTIFACT` warning surfaces on mismatched `metadata.run_id` across artifacts. Compose invocations are dispatched via a registry (`compose_invocations.py`) so per-skill CLI variation doesn't leak into test bodies.
  3. **End-to-end smoke** (`deck-review-e2e-smoke`): `deck-review` runs against a synthetic seed-stage fixture deck via `claude-agent-sdk`. Asserts artifact existence, schema validity, score in expected range, `run_id` parity, `coaching_payload` shape. Triggered on `push: tags: ['v*']` and `workflow_dispatch`; not on `pull_request`. See "Release Process" in CLAUDE.md for the opt-in dispatch list and the required tag → wait-for-green → sync ordering.
- `founder-skills/tests/cowork_async_subagent_filter.py` — tool-name compatibility check against Cowork's sub-agent tool registry. The desktop-side scope exclusion removes 5 tool names (`Bash`, `NotebookEdit`, `REPL`, `JavaScript`, `WebFetch`) from the registry before the CLI's filter runs; `Bash` is replaced by `mcp__workspace__bash`. Names that DO resolve in sub-agent contexts (`Read`, `Edit`, `Glob`, `Grep`, `WebSearch`, etc.) are listed in `COWORK_ASYNC_SUBAGENT_ALLOWLIST`.
- Synthetic deck fixture and golden expected-output under `founder-skills/tests/fixtures/` for the deck-review e2e smoke and compose-invariant tests.
- `claude-agent-sdk==0.1.80` pinned in dev dependencies (pre-1.0 SDK with API churn).
- `pythonpath = ["founder-skills/tests"]` added to `[tool.pytest.ini_options]` so test files can import sibling helper modules by bare name.

### Changed

- `pyproject.toml` `version` aligned with `plugin.json` (earlier drift between the two is fixed).
- `ci.yml` test job scoped to `-m "not e2e"` to prevent the deck-review e2e smoke from running twice per PR.
- `deck-review`, `financial-model-review`, `ic-sim`, and `competitive-positioning` SKILL.md files: added `<!-- skill-quality-ci: bash-after-subagent-ok -->` suppression markers above the legitimate coaching-payload extraction blocks so the regression detector doesn't false-positive on them.
- **`deck-review-e2e-smoke` moved from per-PR push to tag-push + workflow_dispatch.** Runs on every release tag and is opt-in via manual dispatch for architectural-surface PRs. Tag-time preflight verifies the tag matches both `pyproject.toml` and `founder-skills/.claude-plugin/plugin.json` (fails in <5 sec). See CLAUDE.md "Release Process" for the required tag → wait-for-green → `sync-test-repo.sh` ordering and the opt-in dispatch trigger list.

### Notes

- **e2e wall time:** 5-20 min per run depending on LLM dispatch decisions.
- **e2e auth: three paths supported.** The smoke test accepts any of:
  1. `ANTHROPIC_API_KEY` env var
  2. `CLAUDE_CODE_OAUTH_TOKEN` env var (subscription via long-lived token from `claude setup-token`; set as `CLAUDE_CODE_OAUTH_TOKEN_CI` repo secret if you choose this path)
  3. Local subscription auth: macOS Keychain entry `Claude Code-credentials` (after `claude /login`) or `~/.claude/.credentials.json` on Linux/Windows — for local dev only; not applicable in CI.
  The workflow env-injects both `ANTHROPIC_API_KEY_CI` and `CLAUDE_CODE_OAUTH_TOKEN_CI` if set; whichever is present is used. Configure exactly one in repo secrets.

## [0.4.4] - 2026-05-09

### Highlights

Retires the single-purpose `verify-cowork-clone.sh` in favor of `claude-plugin-doctor`, which diagnoses drift across all cache layers rather than just the marketplace clone HEAD.

### Removed

- `scripts/verify-cowork-clone.sh` — superseded by [`claude-plugin-doctor`](https://github.com/yaniv-golan/claude-plugin-doctor) (`cpd`), which diagnoses drift across all six cache layers instead of just the marketplace clone HEAD. Install with `npm install -g claude-plugin-doctor`.

## [0.4.3] - 2026-05-09

### Highlights

Skill, plugin, and dev-workflow alignment with the documented Claude Code v2.1.131 + Desktop v1.6259.1 contracts. Fixes a fragile env-var pattern in 3 skills, migrates inert custom frontmatter into body documentation, and adds CI-level manifest validation plus a script that catches Cowork's silent-marketplace-refresh trap.

### Fixed

- Bare `$CLAUDE_PLUGIN_ROOT` (no braces) in fenced bash blocks across `deck-review`, `ic-sim`, and `market-sizing` SKILL.md files — these resolved only at Bash subprocess time and depended on `CLAUDE_ENV_FILE` being sourced into the shell, which Claude Code does not document as a guarantee for skill subprocesses. Switched all 10 occurrences (deck-review×3, ic-sim×3, market-sizing×4) to `${CLAUDE_PLUGIN_ROOT}` (braced form), which the plugin content expander substitutes at skill load time. `session-setup.sh` stays as defense-in-depth.
- `competitive-positioning/scripts/` was silently missing from CI's typecheck matrix despite having Python files alongside the other four skills.

### Added

- `claude plugin validate` runs in CI on every PR, catching plugin and marketplace manifest drift before users hit it. CLI pinned to exact v2.1.138.
- `founder-skills/tests/test_skill_contract.py` — regression tests enforcing: only `${CLAUDE_PLUGIN_ROOT}` (braced) in skill bodies; only documented frontmatter keys; `when_to_use` declared on every skill; description+when_to_use within both per-skill (1,536-char) and total (6,000-char) listing budgets.
- `scripts/verify-cowork-clone.sh` — verifies the Cowork marketplace clone advanced to upstream HEAD after a Refresh. Cowork's marketplace refresh can return success and bump `known_marketplaces.json#lastUpdated` without the local git clone actually advancing — silent `git pull` failures are absorbed when `CLAUDE_CODE_PLUGIN_KEEP_MARKETPLACE_ON_FAILURE` is set or by the SSH↔HTTPS transport fallback. bash 3.2-compatible, macOS-only, cross-checks `installed_plugins.json` `gitCommitSha` against clone HEAD.
- Explicit `user-invocable: true` on all 5 SKILL.md frontmatters — Desktop's regex scanner reads this key (it doesn't read `disable-model-invocation`), so making the user-invocable intent legible to the scanner is one line of insurance.
- `homepage`, `repository`, `license: Apache-2.0`, `keywords`, and `author.url` in `founder-skills/.claude-plugin/plugin.json` — discoverability metadata surfaced in the Settings UI.
- CLAUDE.md sections covering: SKILL.md conventions (env-vars, frontmatter, the two-parsers / two-discovery-outcomes asymmetry between CLI runtime and Desktop's regex scanner), the marketplace-refresh-verification workflow, and `--plugin-dir` for fast local CLI iteration without going through the marketplace.

### Changed

- Removed inert custom frontmatter (`compatibility`, `metadata`, `imports`, `exports`) from all 5 SKILL.md files. These were silently dropped by the parser and posed a regex-parser fragility risk in Desktop's skill scanner. Migrated to a clearly-labeled `## Skill Metadata` section in each skill body. Plugin version stays in `plugin.json` (single source of truth) — `metadata.version` removed.
- `dev` extras in `pyproject.toml` add `pyyaml` and `types-PyYAML` (for the new SKILL.md frontmatter regression test).

## [0.4.2] - 2026-05-04

### Highlights

Coaching commentary now reasons from a structured `coaching_payload` block in `report.json` instead of re-reading the full report, saving tokens and aligning producer schemas across skills.

### Changed

- **Coaching commentary now reads structured data instead of the full report.** Each skill's `compose_report.py` emits a structured `coaching_payload` block in `report.json` (per-skill schema, with summary stats and failed/warned items). The post-compose coaching sub-agent reasons from this payload directly and inserts `## Coaching Commentary` at a per-run marker (`<!-- COACHING_INSERTION_POINT_<8-hex> -->`) via `Edit`, instead of re-reading `report.md`. Empirical: ~9K tokens saved per coaching run on `deck-review`; larger savings expected on `financial-model-review` (its `report.md` is typically ~3× larger).
- **Producer schema parity across the four checklist-based skills.** `competitive-positioning`'s `checklist.py` now emits a `summary` block with `failed_items`/`warned_items` arrays alongside its existing flat top-level fields (additive — backward-compat preserved). `financial-model-review`'s `failed_items` and `warned_items` entries gain a per-item `severity` (high/medium/low), used to truncate large coaching payloads to the top 15 high + top 15 medium when items exceed 30. `market-sizing` keeps its pass/fail/not-applicable model (no `warn` status). `ic-sim`'s coaching payload uses a distinct dimension-based shape (dealbreakers + concerns) instead of the checklist shape.
- **Tighter coaching-agent integrity checks.** The coaching agent runs an idempotency check before editing — re-running the dispatch against the same review now returns success without duplicating the section. After editing, it verifies all canonical artifacts share the same `metadata.run_id` (using grep-based extraction so the check is robust to where `metadata` sits in each file). The agent matches the *exact* per-run insertion marker — never the prefix substring — so deck content that legitimately contains `<!-- COACHING_INSERTION_POINT_` can't cause a false block.
- **`ic-sim` compose simplification.** Removed the static `## Founder Coaching` section that compose previously generated; the (richer) coaching commentary covers the same ground.
- **Staging files moved to a per-review subdirectory.** Skills that buffer large sub-agent JSON to disk before piping it to a producer script now do so in `$REVIEW_DIR/.staging/` (or the skill-specific equivalent), created at setup.

### Added

- `founder-skills/references/skill-execution-model.md` — committed reference doc explaining how skills run inline in the main thread, when sub-agents are dispatched, the producer-script contract, per-skill payload schemas, and runtime constraints to be aware of. Cross-referenced from each `SKILL.md`.
- Tests covering coaching payload shapes, marker placement and collision handling, severity-sorted truncation, idempotency, and cross-skill dispatch contracts.

## [0.4.1] - 2026-05-03

### Highlights

Skills now run inline in the main thread so they work end-to-end on Cowork, with heavy analytical steps dispatched to sub-agents and coaching commentary appended via a post-compose dispatch.

### Changed

- **Skills run inline in the main thread.** All five skills (`deck-review`, `competitive-positioning`, `financial-model-review`, `ic-sim`, `market-sizing`) drop `disable-model-invocation: true` from their frontmatter. Invoke via the `Skill` tool or the `/<skill-name>` slash command. Heavy analytical steps within each skill dispatch sub-agents (with `Read`/`Edit`/`Glob`/`Grep`) for context isolation; the main thread continues to run the producer scripts that validate and persist canonical artifacts. **BREAKING** for any caller that depended on directly invoking the skill's companion agent — companion agents are now used only as dispatched sub-agents within a skill run.
- **Coaching commentary moves to a post-compose dispatch.** `compose_report.py` now writes `report.md` directly (via `--write-md`); the coaching commentary is then appended by a dispatched sub-agent that reads the report, edits in the commentary, verifies all canonical artifacts on disk, and returns a structured success payload. Replaces the prior pattern of the agent receiving `report_markdown` as JSON and hand-writing the file.
- **Tolerant JSON extraction from sub-agent replies.** Sub-agents may wrap JSON in markdown fences or include prose preambles/footers; the calling skill now robustly extracts the first valid JSON object from the reply.
- **Compose scripts verify outputs after writing.** `compose_report.py` exits non-zero if any declared output file is missing or empty after the run.
- **`deck-review` companion agent split into two dispatch contexts.** Per-step analytical dispatches return JSON matching the producer schemas; the post-compose coaching dispatch returns a structured `{status, review_dir, report_path, score_pct, overall_status, high_severity_warnings}` payload. Tool surface narrowed to `Read`/`Edit`/`Glob`/`Grep`.

### Fixed

- Skills can now run end-to-end on Cowork. Earlier versions broke because Cowork strips `Bash` from sub-agent dispatches at runtime; v0.4.1 inverts the model so orchestration runs in the main thread (where `Bash` is available) and sub-agents handle only work that fits within their (`Bash`-stripped) tool surface.

### Added

- `founder-skills/tests/fixtures/dispatch_contracts.json` and `tests/test_agent_dispatch_contracts.py` — track which sub-agent dispatches each skill makes and what shape each is expected to return; flag drift between agent body documentation and producer-script schemas.
- Per-skill regression tests for compose-script output verification and tolerant JSON extraction.

## [0.4.0] - 2026-05-03

### Highlights

Replaces `deck-review`'s heredoc-written JSON with validating Python producer scripts that schema-check every artifact, and moves the stage gate to a checkpoint-and-resume flow.

### Changed

- **`deck-review` artifacts are now produced by validating Python scripts.** New scripts (`deck_inventory.py`, `stage_profile.py`, `slide_reviews.py`, `gate_state.py`, `setup_run.py`) replace heredoc-written JSON. `compose_report.py` schema-validates every input and refuses to compose if any required artifact lacks `metadata.run_id`. JSON schemas live in `references/schemas/*.schema.json`. **BREAKING** for any caller writing artifacts directly — they must go through the producer scripts.
- **`deck-review` stage gate uses checkpoint-and-resume.** Instead of `AskUserQuestion` (parent-only) inside a sub-agent dispatch, the sub-agent returns `{needs_input: ...}`; the parent asks the user, writes the answer back via `gate_state.py`, then re-invokes the sub-agent. The sub-agent rehydrates `RUN_ID` from `gate_state.json` so artifacts produced before and after the gate share one run identity.
- **`deck-review` sub-agent return contract.** Coaching dispatch now returns a structured `{status, review_dir, report_path, html_path, score_pct, overall_status, high_severity_warnings}` payload — no inline `report_markdown` in the assistant message.
- **`compose_report.py --write-md`** writes `report.md` directly to disk, eliminating prior fragility where the agent had to extract `report_markdown` from JSON and hand-write the file.
- **`setup_run.py`** replaces ad-hoc bash setup. Resolves the review directory, generates `RUN_ID`, and on `--clean` removes stale artifacts (preserving `gate_state.json` across re-invocation).
- **New compose warnings**: `SCHEMA_VIOLATION` (artifact violates JSON schema), `MISSING_METADATA` (artifact lacks `metadata.run_id`), `NAME_DRIFT` (case variants and near-miss spellings of the canonical company name detected in slide content).
- **`founder_context.py init` writes a `metadata` block** with `run_id`, `review_date`, `last_updated`. Existing context files without `metadata` remain readable; the block is added on first touch.

### Fixed

Hardens `deck-review` against several issues surfaced in real Cowork runs:

- `checklist.py` is no longer bypassed via heredoc-written `checklist.json` — `compose_report.py` validates checklist shape before composing.
- `report.json` is now always valid JSON.
- `stage_profile.json` schema is enforced (no more stage-prefixed keys or missing `reference_file_read`).
- The review-directory resolution works across both host and Cowork mount layouts.
- Sub-agents can resume after the stage gate (previously `AskUserQuestion` was parent-only and blocked the dispatch).
- Schema definitions are machine-readable JSON Schema files (previously embedded in markdown).
- The "Different stage" path no longer asks the agent to mutate the artifact directly — `stage_profile.py --rebuild-stage` does it.

## [0.3.1] - 2026-04-29

### Highlights

Gives every founder-skills sub-agent a persistence path (`Write`/`Edit`) that survives Cowork's `Bash` filtering, so sub-agents write their JSON/HTML artifacts instead of degrading to prose narration.

### Fixed

- Sub-agents in Cowork could not persist artifacts because the async dispatch path filters `Bash` out of every sub-agent's tool set, regardless of what the agent's `tools:` frontmatter declares. Result: founder-skills sub-agents collapsed to `{Read, Glob, Grep}` and silently degraded to prose narration instead of writing the JSON/HTML artifacts each skill produces. Adding `Write` and `Edit` to the `tools:` declaration of every founder-skills agent (`competitive-positioning`, `deck-review`, `financial-model-review`, `ic-sim`, `market-sizing`) gives sub-agents a persistence path that survives the filter. `Bash` and `Task` are kept in the declaration so they remain available in non-Cowork environments where they aren't filtered.

## [0.3.0] - 2026-04-21

### Highlights

New Competitive Positioning Agent — maps a startup's competitive landscape, scores differentiation
and moat strength, and stress-tests positioning claims to produce investor-ready competitive analysis.
Also adds resilience improvements across all scoring scripts so common LLM output shape variations
are accepted and normalized rather than rejected.

### Added

- Competitive Positioning Agent with 7 scripts: `validate_landscape.py` (competitor list validation with slug uniqueness and provenance), `score_moats.py` (6 moat dimensions per company with aggregates and cross-company comparison), `score_positioning.py` (pair-centric positioning views with rank-based differentiation and vanity axis detection), `checklist.py` (25-item quality checklist across 6 categories with mode-based gating), `compose_report.py` (report assembly with cross-artifact validation and accepted warnings), `visualize.py` (self-contained HTML with SVG positioning map, moat radar, and competitor table), and `explore.py` (interactive HTML explorer with Chart.js scatter plot, view switching, bubble encoding controls, and company detail panels).
- SKILL.md for competitive positioning (`/founder-skills:competitive-positioning` slash command).
- Deck review now imports competitive positioning landscape for cross-validation.
- IC simulation now imports competitive positioning report.
- Hard validation gates with script provenance stamps and self-grading detection.
- Axis rationale captions and label readability improvements in visualizations.

### Changed

- Market Sizing, Deck Review, and IC Simulation now track `RUN_ID` across all artifacts — `compose_report.py` flags a `STALE_ARTIFACT` high-severity warning if artifacts from different runs are mixed, blocking delivery under `--strict`. Each skill's path setup now includes `rm -f` cleanup of stale artifacts from prior runs before starting. Cowork permission guidance included.
- Deck Review expanded with: 5-item ingestion pitfalls guide (image-only PDFs, PPTX speaker notes, multi-file submissions, partial decks, wrong file types); explicit AI company detection signals for `is_ai_company`; full evidence quality rules for checklist scoring (fail/warn/pass/not_applicable each have specific requirements); Gotchas section covering polished-deck bias, AI-generated copy, benchmarks as medians, text-only input, and cross-skill context. Stale step numbers in `artifact-schemas.md` fixed to match current pipeline table. "2026" removed from description and body (kept in reference files where it is factual).
- Market Sizing and IC Simulation now include explicit sub-agent failure recovery guidance — after each sub-agent dispatch point, the agent verifies expected artifacts exist in the working directory and re-runs the failed sub-agent before proceeding if any are missing.
- Market Sizing, Deck Review, and IC Simulation now integrate `founder_context.py` as a first step — each skill reads (or creates) a persistent founder identity before starting analysis, matching the pattern already in Financial Model Review and Competitive Positioning. The company slug from founder context drives the skill-specific working directory name (`market-sizing-${SLUG}`, etc.), so artifact directories align across skills automatically. Path setup is now a two-phase process: base paths are set immediately, while the skill directory and `RUN_ID` are deferred until the slug is known. `SHARED_SCRIPTS` added to path setup and Glob fallbacks in all three skills.
- Deck Review now inserts a mandatory founder confirmation gate (two-step: chat summary then `AskUserQuestion`) between stage detection and slide review — agent presents detected stage, confidence, evidence, and expected framework before evaluating slides against stage-specific criteria. Out-of-scope stages (`series_b`/`growth`) surface a distinct gate with stop/proceed options.
- Market Sizing now inserts a mandatory founder confirmation gate between input extraction / methodology selection and external validation research — agent presents methodology, key inputs table, and missing fields before spawning research sub-agents. Founder can approve, switch methodology, or correct/add data; gate repeats until confirmed.
- `score_moats.py`, `score_positioning.py`: accept and normalize common LLM output shape mismatches — array-of-objects normalized to dict-keyed format for moat assessments; bare strings wrapped as `{name, description, rationale}` objects for axes; `slug` accepted as alias for `competitor` in positioning points.
- Financial Model Review extraction pitfalls (8 items) moved from inline SKILL.md to `extraction-pitfalls.md` reference file — reduces SKILL.md by ~22 lines while keeping the guidance available via `$REFS` pointer. Added to Available References list.
- Competitive Positioning `explore.py` now embeds Chart.js 4.4.9 from a vendored local file instead of loading via CDN — generated HTML is fully self-contained (no network required). Plotly 3D remains CDN-loaded (lazy, larger).
- Validation error messages now include expected shape hints.
- stderr summary lines added to scoring scripts for batch visibility.
- Tightened skill descriptions across all 5 skills (competitive-positioning, deck-review, financial-model-review, ic-sim, market-sizing) — dropped trigger-phrase litanies and `Do NOT use` clauses that were dead weight under `disable-model-invocation: true`. Cuts ~70% of description length each.
- Tightened agent descriptions across all 5 companion agents — dropped weakest example per agent, removed redundant `<commentary>` blocks, and rewrote openers as concise "what + when" statements. Preserves 2 distinct-capability examples per agent for reliable triggering; cuts ~45% of description length on average.

## [0.2.0] - 2026-03-18

### Highlights

New Financial Model Review agent — reviews startup financial models for investor readiness,
validating structure, unit economics, runway, and metrics against stage-appropriate standards.
Supports Excel, CSV, pitch decks, and conversational input with automatic profile-based gating
by stage, geography, and sector.

### Added

- Financial Model Review Agent with 10 scripts: `extract_model.py` (Excel/CSV parser with cell coordinate provenance and `pre_header_rows`), `validate_extraction.py` (anti-hallucination gate — 5 cross-reference checks with `--fix` for auto-correcting scale denomination), `validate_inputs.py` (4-layer structural/consistency/sanity/completeness validation), `review_inputs.py` (dual-mode review viewer with extraction warning banners and comma-formatted inputs), `apply_corrections.py` (patch-based corrections with SHA256 base_hash staleness detection), `checklist.py` (46-criteria scoring across 7 categories with profile-based auto-gating), `unit_economics.py` (11 benchmarked metrics), `runway.py` (multi-scenario stress-test with decision points and default-alive analysis), `compose_report.py` (report assembly with cross-artifact validation), `visualize.py` (self-contained HTML with SVG charts and label collision avoidance), and `explore.py` (interactive HTML explorer with editable slider values and unit labels).
- SKILL.md for financial model review (`/founder-skills:financial-model-review` slash command).
- Agent definition with skill preloading (`skills:` frontmatter).
- Profile-based auto-gating: checklist items gate by stage (`seed+`), geography (Israel, multi-currency, multi-entity), sector (AI-native, marketplace, usage-based, hardware, consumer, annual-contracts), and model format (spreadsheet vs. deck/conversational).
- `ai-powered` trait for AI-hybrid products: triggers AI cost scrutiny (SECTOR_40) regardless of revenue model type.
- Data sufficiency gate with qualitative fallback path for deck/conversational inputs.
- `data_confidence` qualifier (`exact`/`estimated`/`mixed`) propagated through unit economics and runway outputs.
- Cross-agent integration: financial model review exports `report.json`, `unit_economics.json`, and `runway.json` for downstream IC simulation and fundraise-readiness skills.
- 746 regression tests across all four skills.

### Changed

- Sub-agents for Market Sizing skill: extraction sub-agent for Steps 1-2 (file reading + methodology), parallel top-down/bottom-up research sub-agents for Step 3, and parallel sensitivity + checklist sub-agents for Steps 5-6 — all with constrained return contracts and graceful degradation.
- Sub-agents for Financial Model Review skill: extraction sub-agent for Steps 2-3 (with two-pass resume flow for documents), and parallel checklist + metrics/runway sub-agents for Steps 4-6.
- Output size contracts for IC Simulation partner sub-agents — return only verdict and one-sentence rationale instead of full assessments.
- Context reduction (~87 KB): slimmed agent definitions, condensed SKILL.md files, split FMR schemas into separate reference files.
- JSON receipt emitted to stdout when scripts write to file via `-o`, enabling programmatic artifact tracking.

## [0.1.0] - 2026-02-22

### Highlights

First release of founder-skills — a Claude Cowork plugin with three AI coaching agents
for startup founders. Market Sizing builds defensible TAM/SAM/SOM analysis with external
validation and sensitivity testing. Deck Review scores pitch decks against 35 best-practice
criteria calibrated by fundraising stage. IC Simulation recreates a VC Investment Committee
discussion with three partner archetypes debating the startup across 28 scored dimensions.

### Added

- Market Sizing Agent with 4 scripts: `market_sizing.py` (TAM/SAM/SOM calculator), `sensitivity.py` (assumption stress-testing with confidence-based auto-widening), `checklist.py` (22-item self-check), and `compose_report.py` (report assembly with cross-artifact validation).
- Deck Review Agent with 2 scripts: `checklist.py` (35-criteria scoring across 7 categories) and `compose_report.py` (report assembly with cross-artifact validation).
- IC Simulation Agent with 4 scripts: `fund_profile.py` (fund profile validation), `detect_conflicts.py` (portfolio conflict validation), `score_dimensions.py` (28-dimension conviction scoring across 7 categories), and `compose_report.py` (report assembly with 13 cross-artifact validation checks).
- Three partner archetypes (Visionary, Operator, Analyst) with independent sub-agent assessments and orchestrated debate.
- Fund-specific mode with WebSearch-backed fund research and real partner mapping.
- Cross-agent integration: IC simulation imports prior market-sizing and deck-review artifacts with staleness detection.
- SKILL.md files for all three skills (`/founder-skills:market-sizing`, `/founder-skills:deck-review`, `/founder-skills:ic-sim` slash commands).
- Agent skill preloading (`skills:` frontmatter) for all three agents.
- SessionStart hook for environment setup (`CLAUDE_PLUGIN_ROOT` persistence).
- Dev tooling: ruff (lint + format), mypy (type checking), pytest (testing), GitHub Actions CI, pre-commit hooks.
- 123 regression tests across all three skills.
