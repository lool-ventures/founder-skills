# Common Mistakes

> **Shared reference.** Extracted from `fin-model-research/best-practices.md` (Post-ZIRP Edition, 2024-2026).
> Consumed by: `financial-model-review`, `metrics-benchmarker`, and other Tier 1+ skills.

---

## Common Mistakes Taxonomy

### Structural / Technical

| Mistake | Impact |
| --- | --- |
| Circular references | Break cash calculations; destabilize model |
| Hardcoded numbers in formulas | Breaks dynamic updating when assumptions change |
| Inconsistent time periods | Monthly/quarterly/annual mixed without reconciliation |
| #REF! / #DIV/0! errors | Broken links from deleted rows or input cells |
| No separation of inputs from calculations | Reviewer can't find or change assumptions |
| Merged cells | Disrupt formula copying and macro execution |
| No versioning | Multiple conflicting copies circulate |

### Logical / Business

| Mistake | Impact |
| --- | --- |
| TAM-based revenue ("1% of $10B market") | No connection to actual acquisition mechanics |
| Zero churn or perfect retention | Impossible; undermines all downstream metrics |
| Linear growth forever (5-10% MoM) | No saturation or channel capacity limits |
| Headcount flat while revenue scales | Ignores largest cost; implies "free growth" |
| Underestimating hiring costs | Missing 25-45% benefits/tax burden |
| Under-budgeting G&A | Legal, compliance, IT, facilities often omitted |
| Ignoring seasonality | Critical for consumer, travel, retail |
| Assuming instant sales ramps | New reps need 60-90 days to quota; ~70% attainment typical |
| Confusing bookings with revenue | Cash bookings != recognized revenue (deferred revenue) |
| Ignoring working capital | Net-60 payment terms create hidden cash flow troughs |
| Mismatch between narrative and model | "PLG motion" in deck but heavy outbound sales spend in model |

### Presentation / Bridge

| Mistake | Impact |
| --- | --- |
| No fundraising story | Model doesn't connect raise -> runway -> milestones -> next round |
| No summary view | Investor can't orient in first 5 minutes |
| Assumptions buried | Key drivers hidden in formula cells instead of assumptions tab |
| No scenarios | Single "best case" only in uncertain environment |
| Stage mismatch | Full 3-statement at pre-seed; napkin-only at Series A |

---

## Red Flags Ranked by Severity

### Critical — Deal-breakers

1. **Model numbers contradict the pitch deck.** Signals lack of control. Explicitly flagged by a16z as a diligence red flag.
2. **Runway math is inconsistent or hides cash reality.** Ignores net cash, working capital, capex, or collection lags. Investors fund survival.
3. **"Perfect world" assumptions.** Zero churn, instant sales ramps, 100% quota attainment, 100% gross margin. Violates reality; KeyBanc shows quota attainment is typically ~70-75%.
4. **Broken cap table.** Founders own <50% pre-Series A, or >10% dead equity from departed founders/inactive advisors.
5. **Negative unit economics at scale with no path to profitability.** LTV/CAC permanently <1.0x.

### High — Requires immediate remediation

6. **No credible raise -> milestones bridge.** Sequoia ties runway explicitly to valuation milestones.
7. **Top-down TAM -> revenue with no unit mechanics.** "1% of $10B" is a hallmark of amateur modeling.
8. **Headcount doesn't scale with execution plan.** Revenue 10x with flat team implies "free growth."
9. **Burn multiple >2.5x at Series A with no downward path.** Post-ZIRP capital efficiency gate.
10. **CAC/LTV presented with fake precision** from immature cohorts and non-fully-loaded CAC. Single unsegmented "3:1" without cohort basis is a warning, not a pass.
11. **Cash balance drops below zero before anticipated close of current round.**
12. **Model shows 18-24 months runway but ignores FX.** For multi-currency startups (e.g., ILS payroll + USD fundraising), a 10-15% currency move can break runway. No FX sensitivity = hidden risk.
13. **No entity-level cash plan despite multi-entity structure.** Israel subsidiary can't make payroll without intercompany transfers, but model only shows consolidated view.

### Medium — Erodes credibility

14. **Multiple spreadsheets with inconsistent metrics.** a16z recommends one linked model.
15. **No downside scenario.** In a risk-off world, scenario planning is expected.
16. **Marketplace modeled as one-sided business.** Missing supply-side CAC and retention.
17. **AI models ignore inference cost and margin degradation.**
18. **Mixing recurring and non-recurring revenue** without clear separation.
19. **Hockey-stick inflection with no operational explanation** (no new channels, pricing changes, or hires).
20. **Ignoring working capital or collection lags** in cash-intensive businesses.
21. **Israel benefits/burdens modeled as a single %** with no policy definition — pension, severance, and KH unclear. Investors can't verify the number.
22. **VAT treated as "non-issue"** without checking whether input VAT timing creates a cash trough (Israel: 18% VAT, refund delays).
23. **IIA grant royalties or IP transfer constraints omitted** from long-term cash flow / exit scenarios. IIA repayment can materially impact acquisition terms.
24. **100% C-suite in Israel at Series A** for a company targeting US enterprise. Investors expect to see US GTM hire timing (CRO/CMO). Model S&M location mismatch -> longer sales cycles and higher CAC.

### Low — Points of friction

25. **Formatting friction.** No tab naming, messy categories, no color coding. Signals lack of investor empathy.
26. **No documentation for key assumptions.** Investor can't understand where numbers come from.
27. **Overly complex model for the stage.** Full 3-statement at pre-seed; 20+ tabs with no clear summary.
28. **No version control or audit trail.**
