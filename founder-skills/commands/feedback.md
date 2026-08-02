---
description: Send feedback about founder-skills — report a bug, suggest an idea, ask for help, or share a win. Drafts your message and gives you a link to submit; nothing is sent automatically.
argument-hint: "[what you want to say]"
---

# Send founder-skills feedback

Help the user send feedback to the founder-skills maintainers (lool ventures).
**You never transmit anything.** You draft a message and hand the user a link/text;
they submit it themselves via their own browser or mail client.

## Privacy hard-stop (non-negotiable)

- NEVER put session or artifact data in the draft: no company name, cap-table numbers,
  deck content, financials, valuations, or transcript excerpts.
- NEVER include file paths — they leak company slugs (e.g. `artifacts/acme-corp/...`).
- You MAY include, only after showing the user the exact final text: plugin version
  (read `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json`), skill name, platform
  (Claude Code vs Cowork), and error class if it's a bug. Nothing else.
- Show the complete payload and get an explicit "yes, send this" BEFORE producing any link.

## Flow

1. **Classify** with AskUserQuestion (one question, these options):
   Bug · Idea or feedback · Question / help · Share a win
2. **Gather** briefly (1–3 prompts): which skill, what happened / what you'd want.
3. **Draft + scrub** a clean body per the hard-stop above. Show it in full for review/edit.
4. **Offer private delivery:** ask if they'd rather send it privately by email
   instead of posting publicly. If yes, use the mailto route below.
5. **Produce the submit link** (do not open or send it — the user clicks it):

   | Type | Link |
   |---|---|
   | Bug | `https://github.com/lool-ventures/founder-skills/issues/new?template=bug_report.md&title=<enc>&labels=bug` |
   | Idea / feedback | `https://github.com/lool-ventures/founder-skills/discussions/new?category=ideas-feedback` |
   | Question / help | `https://github.com/lool-ventures/founder-skills/discussions/new?category=q-a-help-how-to` |
   | Share a win | `https://github.com/lool-ventures/founder-skills/discussions/new?category=show-and-tell-founder-wins` |
   | Private (any type) | `mailto:founder-skills@lool.vc?subject=<enc>&body=<enc>` |

   - URL-encode `<enc>` values (spaces, newlines, `#`, `&`).
   - Discussions links don't reliably prefill the body — paste the drafted text into the
     thread after it opens. Issue and mailto links do prefill.
   - If a prefilled URL would exceed ~6KB (GitHub) or ~1.5KB (mailto), skip the prefill
     and present the drafted text for the user to paste.
6. **Confirm:** tell them to review on the opened page and submit. Thank them. If they
   shared a win, mention it may help other founders.
