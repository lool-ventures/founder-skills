# Verified Cap Table Reference

## Purpose

This reference pack supports the cap-table skill, covering founder ownership, SAFEs, convertible notes, option pools, anti-dilution, Israeli company issues, Delaware/Israel cross-border structures, flips, and benchmark warnings.

The markdown is intentionally thin. Deterministic formulas, validation checks, date windows, and warning thresholds live in [`cap-table-rules.json`](./cap-table-rules.json), validated by [`cap-table-rules.schema.json`](./cap-table-rules.schema.json). Skill prose should point to rule IDs and call scripts built from the JSON spec rather than restating calculations inline.

## Source Policy

Final references cite original quotable sources only: issuer documents, official agency materials, model legal documents, law-firm publications, and benchmark datasets. Legal and tax rules based on secondary sources are marked for counsel review in the rule spec.

## Counsel Review Semantics

`counsel_review` is a **reliance boundary, not a confidence score.** It tells future scripts what they are and are not allowed to present.

A rule can be well-sourced (high confidence, primary citations) and still require `counsel_review: true` — because application depends on jurisdiction, current law, facts, documents, tax status, or regulatory approval that the script cannot determine from cap-table data alone.

**`counsel_review: false`**
Safe for deterministic script behavior or general modeling, assuming the user provides the relevant document terms. Examples: SAFE ownership math, option-pool algebra, BBWA formula.

**`counsel_review: true`**
The rule may still be useful, but only as:
- a checklist item,
- a warning,
- a prompt for missing facts,
- a "do not conclude automatically" gate, or
- a handoff note for counsel.

Examples:
- `safe.israeli_2025_safe_harbor` — even if source-backed, whether a specific SAFE qualifies is Israeli tax analysis.
- `delaware_cross_border.qsbs_date_sensitive` — scripts can flag issue dates and collect facts, but should not conclude QSBS eligibility.
- `israeli_ltd.iia_royalties_ip` — scripts can warn about IIA-funded IP, but should not calculate definitive transfer obligations without counsel-approved parameters.

**Operational enums** (optional fields in the rule spec): `script_allowed_outputs` and `script_disallowed_outputs` let a rule explicitly declare what scripts may emit. Allowed values:

| Allowed | Disallowed |
| --- | --- |
| `flag_issue` | `legal_conclusion` |
| `ask_for_documents` | `tax_classification` |
| `show_source_note` | `eligibility_determination` |
| `recommend_counsel_review` | `binding_filing_instruction` |
| `compute_numerical_result` | `rate_or_percentage_quotation_without_source_date` |
| `render_warning` | |
| `render_benchmark_comparison` | |

These fields are currently not required on every rule — populate them when adding new rules or when a skill implementation needs the explicit gate. The default reading of `counsel_review: true` without explicit enums is: allow checklist/warning/prompt/handoff outputs only.

## Implementation Contract

Future cap-table scripts should treat `cap-table-rules.json` as the executable reference layer:

| Domain | Use rule IDs for |
| --- | --- |
| `safe` | YC post-money SAFE ownership math, Company Capitalization, stacked SAFEs, MFN, pro rata side letters, liquidity/dissolution branches, Israeli SAFE tax flags. |
| `convertible_notes` | Accrued interest, cap/discount conversion, denominator policies, qualified financing triggers, Israeli CLA tax flags. |
| `option_pool` | Pre-money and post-money pool top-up equations, target denominator prompts, market benchmark ranges. |
| `anti_dilution` | Broad-based weighted-average formula, narrow-based denominator prompts, full-ratchet warnings. |
| `israel_equity_tax` | Section 102 and 3(i) eligibility flags, trustee/holding-period prompts, plan-design risks. |
| `israeli_ltd` | Share register, registrar filing, IIA royalty/IP restrictions, preferred-share governance prompts. |
| `delaware_cross_border` | Delaware parent/Israeli subsidiary flags, Section 102 parent-share issues, IP/transfer-pricing review, QSBS date sensitivity. |
| `delaware_flip` | Share-exchange mapping, Israeli tax ruling path, May 2025 restructuring changes, options/convertibles/IIA review. |
| `founder_benchmarks` | Carta and Israel market benchmarks, severe-dilution warnings, no hard founder-ownership redlines. |

## Source-Backed Boundaries

SAFE calculations are document-specific. The default implementation should support YC post-money SAFE mechanics, including fixed cap-implied ownership and the YC Company Capitalization definition, through `safe.post_money_cap_conversion`, `safe.company_capitalization_yc_post_money`, and `safe.stacked_post_money_caps` [`YC-PMSAFE-PRIMER`, `YC-SAFE-DOCUMENTS`].

Convertible note calculations must parameterize denominator definitions, eligible accrued interest, qualified financing triggers, and cap/discount mechanics. Use `convertible_notes.accrued_interest`, `convertible_notes.cap_discount_conversion`, and `convertible_notes.note_denominator_template` [`COOLEY-CONVERTIBLE-DEBT`, `NVCA-CONVERTIBLE-NOTE`, `FENWICK-CONVERTIBLE-NOTE`].

Option pool advice should separate economics from labels. A “post-closing target pool” can still shift economics into pre-money pricing if the term sheet defines it that way. Use `option_pool.pre_money_topup`, `option_pool.post_money_topup`, and `option_pool.target_basis` [`COOLEY-OPTION-POOL`, `COOLEY-NOTE-PPS`].

Anti-dilution should be modeled only after identifying the protection type and excluded issuances. Use broad-based weighted-average only when documents support it, and surface full-ratchet protection as a high-impact warning [`COOLEY-ANTI-DILUTION`].

Israel tax and corporate-law items are not calculator conclusions. Section 102 (including current double-trigger treatment under ITA Position Paper 01/2025), Section 3(i), Israeli SAFE guidance, Registrar filings, and IIA-funded IP should be implemented as prompts and counsel-review gates unless counsel-approved facts are provided [`ICNL-ISRAEL-ORDINANCE`, `PEARLCOHEN-102-PITFALLS`, `SHIBOLET-102-DOUBLE-TRIGGER`, `ITA-SAFE-2025-HERZOG`, `PEARLCOHEN-SAFE-2025`, `BARNEA-REGISTRAR-ONLINE`, `IIA-ROYALTIES-IP`]. The ICNL English text is unofficial; the Hebrew official law (Nevo / Knesset Sefer HaChukkim) and current ITA circulars control.

Delaware/Israel cross-border and flip issues should not be inferred from cap-table math alone. Scripts can track holders, instruments, and dates, but structure choice, QSBS, IP, transfer pricing, tax-deferral paths, and IIA exposure require counsel review [`KPMG-RD-CENTER-2025`, `ARNONTL-RESTRUCTURING-2025`, `TAXADVISER-QSBS-OBBBA`, `IIA-ROYALTIES-IP`].

Founder ownership benchmarks should be framed as context, not redlines. Use Carta and Israel market datasets for comparison, not pass/fail scoring [`CARTA-FOUNDER-2026`, `CARTA-FOUNDER-2025`, `F2-ISRAEL-2024`, `FUSION-ISRAEL-PRESEED-2025`].

## Date-Sensitive Checks

The following rule IDs must be evaluated against event dates:

| Rule ID | Date field | Reason |
| --- | --- | --- |
| `safe.israeli_2025_safe_harbor` | `safe_investment_date` | Reported ITA temporary SAFE guidance applies during 2025-2026. |
| `safe.israeli_safe_facts_circumstances` | `safe_investment_date` | Non-qualifying Israeli SAFEs need tax review under current guidance. |
| `convertible_notes.qualified_financing_threshold` | `benchmark_reference_date` | WSGR FY2025 benchmark figures reflect 2025 deals; refresh annually. |
| `israel_equity_tax.section_102_capital_gains` | `grant_date` | Trustee deposit, plan, and holding-period checks depend on grant and sale timing. |
| `israel_equity_tax.section_102_double_trigger` | `transaction_event_date` | ITA Position Paper 01/2025 is the current reported position; verify against current ITA materials at deal time. |
| `israeli_ltd.registrar_online_reporting` | `filing_date` | Online-only filing workflow is reported from June 27, 2024. |
| `delaware_cross_border.transfer_pricing_ip` | `tax_position_date` | Israeli R&D center and IP valuation guidance is recent and date-sensitive (KPMG-RD-CENTER-2025 reports the November 2025 final guidance). |
| `delaware_cross_border.qsbs_date_sensitive` | `stock_issue_date` | QSBS changes are reported for stock issued after July 4, 2025. |
| `delaware_flip.part_e2_repeal` | `restructuring_effective_date` | May 1, 2025 Israeli restructuring amendments repealed the prior 25%-for-2-years Part E2 holding-period requirement. |
| `delaware_flip.options_convertibles` | `flip_closing_date` | Options, SAFEs, notes, trustee approvals, and consents must be current at closing. |

## Bibliography

`ARNONTL-RESTRUCTURING-2025` - Arnon, Tadmor-Levy, “Significant Tax Reliefs in Corporate Restructuring,” https://arnontl.com/news/significant-tax-reliefs-in-corporate-restructuring-amendment-to-the-israeli-income-tax-ordinance/

`BARNEA-REGISTRAR-ONLINE` - Barnea Jaffa Lande, “Compulsory Online Reporting to the Israeli Registrar of Companies,” https://barlaw.co.il/practice_areas/corporate/client_updates/compulsory-online-reporting-to-the-israeli-registrar-of-companies/

`CARTA-FOUNDER-2025` - Carta, “How much ownership do founders have at startup IPO?” https://carta.com/data/founder-ownership/

`CARTA-FOUNDER-2026` - Carta, “How much ownership do founders have at startup IPO?” https://carta.com/uk/en/data/founder-ownership-2026/

`CLERKY-INCORPORATION` - Clerky, “Certificate of Incorporation Contents,” https://handbooks.clerky.com/startup-incorporation/certificate-of-incorporation-contents

`COOLEY-ANTI-DILUTION` - Cooley GO, “Broad-Based Weighted Average Anti-Dilution Protection,” https://www.cooleygo.com/glossary/broad-based-weighted-average-anti-dilution-protection/

`COOLEY-CONVERTIBLE-DEBT` - Cooley GO, “Convertible Debt,” https://www.cooleygo.com/convertible-debt/

`COOLEY-DOWN-ROUND` - Cooley GO, “What You Need to Know About Down Round Financings,” https://www.cooleygo.com/down-round-financings/

`COOLEY-NOTE-PPS` - Cooley GO, “Calculating Share Price With Outstanding Convertible Notes or Safes,” https://www.cooleygo.com/calculating-share-price-outstanding-convertible-notes-or-safes/

`COOLEY-OPTION-POOL` - Cooley GO, “Negotiating the Option Pool,” https://www.cooleygo.com/negotiating-option-pool/

`F2-ISRAEL-2024` - F2 Venture Capital, “Israel's early-stage investors on 2024 takeaways and expectations for 2025,” https://www.f2vc.com/insights/israels-early-stage-investors-on-2024-takeaways-expectations-for-2025

`FENWICK-CONVERTIBLE-NOTE` - Fenwick, “Convertible Note Seed-Stage Startup Template,” https://assets.fenwick.com/legacy/FenwickDocuments/Convertible-Note-Seed-Stage-Startup.pdf

`FUSION-ISRAEL-PRESEED-2025` - Fusion VC, “Fusion Pre-Seed Report 2025,” https://blog.fusion-vc.com/p/fusion-pre-seed-report-2025

`ICNL-ISRAEL-ORDINANCE` - ICNL library copy, “Income Tax Ordinance, New Version, 1961,” https://www.icnl.org/wp-content/uploads/Israel_Ordinance.pdf

`IIA-ROYALTIES-IP` - Israel Innovation Authority, “Royalties and Intellectual Property,” https://innovationisrael.org.il/en/royalties-intellectual-property/

`ISRAEL-COMPANIES-LAW` - ICNL library copy, “Companies Law, 5759-1999,” https://www.icnl.org/wp-content/uploads/Israel_CompaniesLaw.pdf

`ITA-SAFE-2025-HERZOG` - Herzog Fox & Neeman, “The ITA Publishes an Updated Version of its Guidance and Safe Harbor for SAFEs,” https://herzoglaw.co.il/en/news-and-insights/the-ita-publishes-an-updated-version-of-its-guidance-and-safe-harbor-for-safes/ (states the guidance applies to SAFEs signed Jan 1 2025–Dec 31 2026, unless revised earlier; corroborated by Arnon Tadmor-Levy, https://arnontl.com/news/updated-guidelines-israel-tax-authority-regarding-safe-transactions/). Replaces a former Maslaw summary whose URL now redirects to a spam domain.

`KPMG-RD-CENTER-2025` - KPMG, “Israel: Final guidance for local R&D centers related to IP valuations,” https://kpmg.com/us/en/taxnewsflash/news/2025/11/israel-final-guidance-local-r-and-d-centers-ip-valuations.html

`NVCA-CERT-OF-INC` - National Venture Capital Association, “Model Certificate of Incorporation,” https://nvca.org/wp-content/uploads/2019/06/NVCA-Model-Document-Certificate-of-Incorporation.docx

`NVCA-CONVERTIBLE-NOTE` - NVCA, “Note Purchase Agreement and Convertible Note,” https://nvca.org/wp-content/uploads/2024/02/Note-Purchase-Agreement-and-Convertible-Note.pdf

`PEARLCOHEN-102-PITFALLS` - Pearl Cohen, “Section 102 Options: The Unwritten Rules and Pitfalls to Look For,” https://www.pearlcohen.com/section-102-options-the-unwritten-rules-and-pitfalls-to-look-for/

`PEARLCOHEN-SAFE-2025` - Pearl Cohen, “SAFE 2025: Summary of Key Changes from SAFE 2023,” https://www.pearlcohen.com/key-tax-updates-safe-2025-summary-key-changes-from-safe-2023/

`SHIBOLET-102-DOUBLE-TRIGGER` - Shibolet, “Double Trigger Acceleration Upon Exit or IPO,” https://www.shibolet.com/en/double-trigger-acceleration-upon-exit-or-ipo/

`STRIPE-ATLAS-EQUITY` - Stripe Atlas, “Startup equity guide,” https://stripe.com/guides/atlas/equity

`TAXADVISER-QSBS-OBBBA` - The Tax Adviser, “Revisiting Sec. 1202: Strategic planning after the 2025 OBBBA expansion,” https://www.thetaxadviser.com/issues/2025/dec/revisiting-sec-1202-strategic-planning-after-the-2025-obbba-expansion/

`WSGR-ER-FY2025` - Wilson Sonsini, “The Entrepreneurs Report: Full Year 2025,” https://www.wsgr.com/en/insights/the-entrepreneurs-report-full-year-2025.html

`YC-PMSAFE-PRIMER` - Y Combinator, “Primer for post-money safe v1.1,” https://www.ycombinator.com/assets/ycdc/Primer%20for%20post-money%20safe%20v1.1-2af8129e12effd9638eeab383b7309142c8f415e5cdb0bc210d573f779177a1c.pdf

`YC-SAFE-DOCUMENTS` - Y Combinator, “SAFE Financing Documents,” https://www.ycombinator.com/documents

`YC-STANDARD-DEAL` - Y Combinator, “Y Combinator Standard Deal,” https://www.ycombinator.com/deal
