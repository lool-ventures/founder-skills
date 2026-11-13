---
paths:
  - ".claude-plugin/**"
  - "founder-skills/.claude-plugin/**"
---
# Installing the Plugin in Claude Cowork

Customize → Plugins → the **+** at the right of the Anthropic/Partners/**Personal** tab row →
**Add marketplace** → **Add from a repository** → pick `lool-ventures/founder-skills` in the **URL**
picker → **Sync** → then **+** on the *Founder skills* card to install.

There is no "Personal Plugins" list and no "Browse Plugins" — that was an older layout. The two `+`
buttons are distinct: tab-row `+` adds a *marketplace*, card `+` installs a *plugin*. Syncing alone
installs nothing. To refresh an installed plugin, use **Check for updates** on the marketplace's `⋯`
menu, which enables the plugin's **Update** button.

(Verified against the live UI 2026-07-29; captures under `docs/internal/cowork-ui-validation-2026-07-28/`.)

A private test build skips the marketplace: Customize → Plugins → Add plugin → Upload plugin.

**Start a new conversation** after installing ("New" on the merged interface; a new Cowork task where the Chat/Cowork choice still exists). Running conversations won't pick up the plugin.

# Local CLI Testing with `--plugin-dir`

For iterating on plugin code in the standalone Claude Code CLI (host CLI, not Cowork), bypass the marketplace machinery entirely. From the repo root:

    claude --plugin-dir "$PWD/founder-skills"

This loads our plugin for the session only:
- No marketplace clone
- No `installed_plugins.json` entry
- No enabled-state in settings
- No interaction with Desktop's "Update available" badge or refresh flow
- Gone the moment the session exits

**Use for:** rapid local iteration on SKILL.md / agents / scripts when you don't want to reinstall after every change.

**Caveats:**
- Host CLI only. Cowork uses a VM-pinned binary at `~/Library/Application Support/Claude/claude-code-vm/<version>/claude` (Linux ARM64 ELF) and has no equivalent flag exposed through Desktop.
- Managed-policy block lists still apply — a blocked plugin name fails to load.
- Repeatable for multi-plugin testing: `--plugin-dir A --plugin-dir B`.

# Updating Plugin Files in Cowork Without Reinstalling

**Local sessions only.** These steps edit host copies; a cloud session reads the plugin synced to the account, so test a build there by uploading it (see "Installing the Plugin in Claude Cowork").

Cowork caches plugin files per-session. To hot-patch files for testing without reinstalling:

1. Find the session cache:
   ```bash
   find ~/Library/Application\ Support/Claude/local-agent-mode-sessions -name "SKILL.md" -path "*ic-sim*" 2>/dev/null
   ```

2. There are typically 4 copies per session — 2 marketplace names × (`cache/` + `marketplaces/`):
   ```
   cowork_plugins/cache/<marketplace>/<plugin>/<version>/
   cowork_plugins/marketplaces/<marketplace>/<plugin-dir>/
   ```

3. Copy modified files into all locations:
   ```bash
   SRC="founderskills"
   COWORK_BASE="$HOME/Library/Application Support/Claude/local-agent-mode-sessions/<org-id>/<session-id>/cowork_plugins"
   TARGETS=(
     "$COWORK_BASE/cache/<marketplace1>/<plugin>/<version>"
     "$COWORK_BASE/cache/<marketplace2>/<plugin>/<version>"
     "$COWORK_BASE/marketplaces/<marketplace1>/<plugin-dir>"
     "$COWORK_BASE/marketplaces/<marketplace2>/<plugin-dir>"
   )
   for target in "${TARGETS[@]}"; do
     cp "$SRC/skills/ic-sim/SKILL.md" "$target/skills/ic-sim/SKILL.md"
     # ... repeat for each modified file
   done
   ```

   If you changed any `.py` file or agent body, first run `python3 founder-skills/scripts/script_hashes.py --write`
   and copy `data/script-hashes.json` into every target too. A copied script the shipped hashes do not list
   makes the dispatch check hold the first paired dispatch once, then hold (never rewrite) a dispatch that
   differs from its printed prompt, so the session would behave unlike any real install.

4. **Start a new conversation** — running conversations have already loaded skill bodies into context.

## Verifying the Marketplace Clone Actually Advanced

Cowork's "Refresh" can succeed without the local clone's git HEAD advancing — `CLAUDE_CODE_PLUGIN_KEEP_MARKETPLACE_ON_FAILURE` and the SSH↔HTTPS fallback both absorb `git pull` failures silently while still bumping `lastUpdated`. The same trap exists for the standalone Claude Code CLI's marketplace cache.

Use [`claude-plugin-doctor`](https://github.com/yaniv-golan/claude-plugin-doctor) (`cpd`) — it diagnoses drift across all six cache layers of the Claude Code / Claude Desktop plugin system, not just the marketplace clone.

```bash
npm install -g claude-plugin-doctor
```

**The full safe dev loop is:**

1. `./scripts/sync-test-repo.sh` — push your changes to the test repo.
2. **In the Cowork UI**, click Refresh on the marketplace.
3. **In your terminal**, run `cpd refresh lool-founder-skills` to confirm the clone advanced and surface any other drift.
4. If the clone is stale, run `cpd refresh lool-founder-skills --force-fetch -y` — bypasses the broken refresh path with a direct `git fetch && git reset --hard`.
5. Click Update on the plugin in Cowork (or use `cpd refresh lool-founder-skills --auto-update`).
6. Open a new Cowork task to pick up the new content.

Run `cpd refresh` after clicking Refresh in step 2 — Cowork's Refresh is async and user-triggered, so it can't be wired into `sync-test-repo.sh` automatically.

**Always run `cpd check founder-skills@lool-founder-skills` before debugging "why isn't my new SKILL.md being picked up"** — it produces a single-plugin drift report across all six cache layers (marketplace clone, install snapshot, enabled state, RPM, session mounts, content-hash sync). Half the time the answer is the clone never moved; the other half it's a different cache layer.

# Removing / Refreshing a Plugin in Claude Code / Cowork

There is no UI to remove a marketplace. Edit config files directly.

## Claude Code (CLI)

- `~/.claude/plugins/known_marketplaces.json` — delete the marketplace entry
- `~/.claude/plugins/installed_plugins.json` — delete any `pluginname@marketplace` entries
- `~/.claude/plugins/cache/<marketplace>/` — delete to reclaim disk space

## Cowork (Desktop App) — stale version troubleshooting

**Local sessions only.** These steps edit host copies; a cloud session reads the plugin synced to the account, so test a build there by uploading it (see "Installing the Plugin in Claude Cowork").

When Cowork won't pick up a new version, nuke all three locations:

```bash
BASE="$HOME/Library/Application Support/Claude/local-agent-mode-sessions/<org-id>/<user-id>/cowork_plugins"
rm -rf "$BASE/cache/<marketplace>"
rm -rf "$BASE/marketplaces/<marketplace>"
rm -f "$BASE/.install-manifests/<plugin>@<marketplace>.json"
```

Then remove the entries from `known_marketplaces.json` and `installed_plugins.json`, restart Cowork, and re-add the marketplace.

**Tip:** `installed_plugins.json` pins a `gitCommitSha` — compare against `git rev-parse HEAD` to check freshness.

**Pitfall:** When deleting an entry from these JSON files, ensure the preceding entry's trailing comma is removed if it becomes the last entry. A trailing comma produces invalid JSON that `JSON.parse()` rejects, causing "Failed to add marketplace" errors in Cowork.
