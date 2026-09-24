"""Verbatim vendored subset of cowork-harness 3.7.0's bundled `scripts/scenario.py`.

This module copies exactly the two functions that decide what `cowork-harness critique` puts into a
skill's evidence corpus, plus their full transitive dependency closure:

  - `_resolve_corpus_agents(skill_dir)`             — upstream `scripts/scenario.py:1819`
  - `_resolve_corpus_root_references(skill_dir, agents)` — upstream `scripts/scenario.py:2079`

WHY VENDORED RATHER THAN IMPORTED: importing the installed CLI's copy of `scripts/scenario.py` would
make our corpus-ceiling ratchet (`test_skill_contract.py`'s size guard) CLI-conditional — its result
would depend on which `cowork-harness` version happens to be on PATH (or absent) when the test runs. A
ratchet that silently stops running when the CLI is missing, or silently changes behavior when the CLI
is upgraded out from under it, is worse than no ratchet at all: it would report green while measuring
nothing.

WHY NOT HAND-WRITTEN: upstream cross-language-pins this exact corpus-resolution logic against its own
TypeScript implementation (`src/critique/resolve-agents.ts` and `src/critique/resolve-references.ts`)
using shared fixtures that BOTH sides execute (e.g. `test/fixtures/dispatchable-agents.json`). Copying
the Python body verbatim lets this module inherit that cross-language pinning for free. A hand-rolled
reimplementation of "what does the critique packager include" would drift from the TypeScript side with
no fixture to catch it.

The function bodies below are copied VERBATIM (formatting-only reflow from `ruff format` aside) — do
not "improve", rename, or simplify them. The whole point of a verbatim copy is that drift from upstream
can be detected mechanically (by comparing parsed function bodies), which `tests/test_critique_corpus_sync.py`
does against the installed `cowork-harness` CLI's copy of `scripts/scenario.py`, when that CLI is
available.

HONEST LIMIT, inherited from upstream's own docstring on `_resolve_root_references`: the TypeScript
packager's corpus rule has a clause 3 — files the graded AGENT actually READ during a live run — that
is RUN-DEPENDENT and cannot be mirrored by any static pass with no run to inspect. This module
therefore reproduces clauses 1 and 2 only (a skill's own authored text, and every sub-agent body already
in the corpus). Any total this module produces is consequently a FLOOR on the real critique corpus, not
an exact match — a real run can only ever include MORE files than this counts, never fewer.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any


def _require_yaml() -> Any:
    # Prefer a system PyYAML (uses the faster libyaml build when present); otherwise fall back to the
    # pure-Python copy bundled under _vendor/ so `lint` works on a stock python3 with no pip install
    # (npm consumers / bare CI runners that lack site-packages).
    try:
        import yaml  # type: ignore

        return yaml
    except ImportError:
        vendor = str(Path(__file__).resolve().parent / "_vendor")
        if vendor not in sys.path:
            sys.path.insert(0, vendor)
        try:
            import yaml  # type: ignore

            return yaml
        except ImportError:
            print(
                "scenario.py needs PyYAML and the bundled copy could not be loaded. Install it: pip install pyyaml",
                file=sys.stderr,
            )
            sys.exit(2)


# --------------------------------------------------------------------------- #
# subagent_type static resolution
# --------------------------------------------------------------------------- #
#
# A pinned `subagent_type:` value that doesn't resolve to a real agent fails a definition lookup at
# dispatch time — but that's only discoverable via a live dispatch today. Resolve it statically from
# a plugin's own `.claude-plugin/plugin.json` (or `plugin.json`) + `agents/*.md` frontmatter instead.
#
# HONEST LIMIT: there is no harness registry of built-in agent types (the built-in set is
# agent-binary-version-dependent) — only `general-purpose` is harness-known. So an unresolved bare
# value is surfaced as INFO, never failed as WARN/ERROR; the linter can't disprove it's a real
# built-in. Do NOT add a committed built-in agent-type list here — that would silently go stale and
# either false-warn a real built-in or false-clear a typo.

_SUBAGENT_TYPE_RE = re.compile(r"subagent_type\s*[:=]\s*['\"]?([A-Za-z0-9_.:/-]+)['\"]?")


def _read_plugin_name(plugin_dir: Any) -> Any:
    """Return the `name` field from `<plugin_dir>/.claude-plugin/plugin.json` (fallback
    `<plugin_dir>/plugin.json`), or None if neither file exists or is parsable. Never raises."""
    p = Path(plugin_dir)
    for candidate in (p / ".claude-plugin" / "plugin.json", p / "plugin.json"):
        if candidate.is_file():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                return None
            name = data.get("name") if isinstance(data, dict) else None
            return name if isinstance(name, str) and name.strip() else None
    return None


_AGENT_FRONTMATTER = re.compile(r"^---\s*\n(.*?\n)---\s*(?:\n|$)", re.DOTALL)


def _agent_name_from_frontmatter(md_path: Any, yaml_mod: Any) -> Any:
    """Return a markdown file's `name:` frontmatter value, or None if there's no frontmatter, no
    `name:` field, or it fails to parse. Originally for `agents/*.md` (caller falls back to the
    filename stem there); also reused by the self-heal find-pattern guard for a SKILL.md, whose frontmatter has the same
    `---\\nname: ...\\n---` shape — the parser itself is generic, only the name is agent-specific."""
    try:
        text = Path(md_path).read_text(encoding="utf-8")
    except Exception:
        return None
    m = _AGENT_FRONTMATTER.match(text)
    if not m:
        return None
    try:
        data = yaml_mod.safe_load(m.group(1))
    except Exception:
        return None
    if isinstance(data, dict):
        name = data.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _enumerate_plugin_agents(plugin_dir: Any) -> Any:
    """Every agent markdown under `<plugin_dir>/agents/`, RECURSIVELY, as (declared_name, Path) pairs.

    Recursive on purpose. Claude Code discovers `agents/sub/x.md` (see src/run/analyze-skill.ts:981-983)
    and skill-hash.ts's `agentSkillName` already attributes both the flat and nested shapes, so a nested
    agent is dispatchable, hash-attributed and analyze-scanned. The old non-recursive `glob("*.md")` made
    it invisible to BOTH this linter's subagent_type resolution and the critique corpus.

    This CAN change a severity in both directions, verified, not assumed:
      - a literal naming a nested agent stops being a `subagent-type-not-found-in-plugin` WARN (it really
        is dispatchable, so that WARN was a false positive); and
      - for a plugin whose `agents/` holds ONLY subdirectories, the agent set was previously EMPTY, which
        sent every same-plugin literal down the `plugin_agent_types` falsy branch in
        `_classify_subagent_type` to `subagent-type-unknown` (INFO). The set is now non-empty, so a
        genuinely typo'd literal is reported as the WARN it always was -- a true positive that used to be
        suppressed, but a NEW `--strict` failure on an unchanged tree."""
    agents_dir = Path(plugin_dir) / "agents"
    if not agents_dir.is_dir():
        return []
    yaml = _require_yaml()
    out = []
    for md in sorted(agents_dir.rglob("*.md")):
        if not md.is_file():
            continue
        out.append((_agent_name_from_frontmatter(md, yaml) or md.stem, md))
    return out


def _literal_to_agent_name(value: Any, plugin_name: Any) -> Any:
    """Map a pinned `subagent_type` literal to a declared agent name WITHIN this plugin, or None.

    A colon-bearing literal is namespaced (`<plugin>:<agent>`) and its prefix MUST equal this plugin's
    name, or a cross-plugin `other:market-sizing` would match THIS plugin's `market-sizing`. A bare
    literal matches a declared name directly. MIRRORED in src/critique/resolve-agents.ts; the two are
    pinned by test/fixtures/dispatchable-agents.json, which both sides execute."""
    if ":" not in value:
        return value or None
    if not plugin_name:
        return None
    prefix, _, suffix = value.partition(":")
    return suffix if prefix == plugin_name and suffix else None


def _resolve_corpus_agents(skill_dir: Any) -> Any:
    """Every agent file the critique packager will put in THIS skill's evidence corpus, as a sorted list
    of Paths. Mirrors `resolveDispatchableAgents` in src/critique/resolve-agents.ts -- union of:
      1. `agents/<skillname>.md` by FILENAME (what the packager did through 3.6.0),
      2. every in-plugin agent a pinned `subagent_type` literal in SKILL.md / references/** resolves to,
      3. every agent whose DECLARED name equals the skill name,
    then a transitive closure over the resolved agent bodies (an agent that dispatches another agent).

    The union is the SAFETY property: this can never resolve to less than the single agents/<skill>.md
    the old sizing counted, so a skill's reported corpus never shrinks under this change."""
    skill_dir = Path(skill_dir)
    # Walk UP for the manifest, exactly as the TypeScript side does (`findEnclosingPluginDir`). The
    # old `parent.name == "skills"` LAYOUT rule disagreed with the packager outside the
    # `<root>/skills/<name>` shape: a skill at `<root>/foo/SKILL.md` with a manifest at `<root>` made the
    # packager size a corpus this sized as ZERO, which is the packager-vs-linter divergence 0003e38
    # closed in one shape and left open in another.
    # Nearest MANIFEST first (matching the TypeScript `findEnclosingPluginDir`), falling back to the
    # `<root>/skills/<name>` LAYOUT. Manifest-only diverged from the packager for a manifest-less plugin,
    # where the TS side still enumerates agents because it is handed the root explicitly; layout-only
    # diverged for a skill that is not under `skills/` but does have a manifest above it, which the
    # packager sizes and this sized as ZERO. Neither rule alone matches; the union does.
    plugin_dir = _find_enclosing_plugin_dir(skill_dir / "SKILL.md") or (
        skill_dir.parent.parent if skill_dir.parent.name == "skills" else None
    )
    if plugin_dir is None or not (plugin_dir / "agents").is_dir():
        return []
    all_agents = _enumerate_plugin_agents(plugin_dir)
    if not all_agents:
        return []
    plugin_name = _read_plugin_name(plugin_dir)
    skill_name = skill_dir.name
    picked = {}
    sources = []  # declared before `add`: every picked agent is itself a dispatch SOURCE

    def add(path: Any) -> None:
        """Record an agent AND queue its body as a dispatch source.

        Clauses 1 and 3 used to record without queueing, so a skill's own primary agent -- the most
        likely dispatcher of a second agent -- was never scanned and the transitive closure did not run
        for the dominant real shape. `scanned` below still guarantees termination."""
        if str(path) in picked:
            return
        picked[str(path)] = path
        sources.append(path)

    for name, md in all_agents:
        # clause 1 (filename) and clause 3 (declared name)
        if md == plugin_dir / "agents" / f"{skill_name}.md" or name == skill_name:
            add(md)

    skill_md = skill_dir / "SKILL.md"
    if skill_md.is_file():
        sources.append(skill_md)
    refs = skill_dir / "references"
    if refs.is_dir():
        sources.extend(p for p in sorted(refs.rglob("*")) if p.is_file())
    scanned = set()
    while sources:
        src = sources.pop(0)
        if str(src) in scanned:
            continue
        scanned.add(str(src))
        try:
            text = src.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in _SUBAGENT_TYPE_RE.finditer(text):
            agent_name = _literal_to_agent_name(m.group(1), plugin_name)
            if not agent_name:
                continue
            for name, md in all_agents:
                if name == agent_name:
                    add(md)  # queues the body too -- transitive: this agent may dispatch another
    return [picked[k] for k in sorted(picked)]


# --------------------------------------------------------------------------- #
# plugin-root references/ resolution, for corpus sizing only
#
# Mirrors `resolveRootReferences` in src/critique/resolve-references.ts (clauses 1 + 2 only -- see the
# docstring on `_resolve_corpus_root_references` below for why clause 3 cannot be mirrored here). The TS
# packager now puts a multi-skill plugin's SHARED plugin-root `references/` files into the evaluator
# corpus when the graded skill's own text (or a sub-agent it can dispatch) points at them, so
# `_lint_skill_corpus_size` must size the same files or the ceiling warning under-reports exactly the
# plugins this feature targets.
# --------------------------------------------------------------------------- #

# Trailing punctuation a prose or markdown token picks up, stripped as a RUN and WITHOUT requiring
# balance -- byte-identical rule to TRAILING_PUNCT in resolve-references.ts.
_TRAILING_PUNCT_RE = re.compile(r"""[)\]}>.,;:!?'"]+$""")
_LEADING_QUOTE_RE = re.compile(r"""^["'<([]+""")
_HASH_QUERY_RE = re.compile(r"[#?].*$")
_BACKTICK_SPAN_RE = re.compile(r"`([^`]+)`")
_MD_LINK_TARGET_RE = re.compile(r"\]\(([^)\s]+)")
_HREF_TARGET_RE = re.compile(r"""href=["']([^"']+)["']""")


def _line_tokens(line: Any) -> Any:
    """Candidate tokens on one line: backticked spans, markdown/href link targets, and bare whitespace-
    delimited runs. Only those containing `/` are resolved as paths (`pathish`); the bare ones matter only
    for the ARMED basename pass. Mirrors `lineTokens()` in resolve-references.ts."""
    pathish = []
    bare = []
    raw = (
        _BACKTICK_SPAN_RE.findall(line)
        + _MD_LINK_TARGET_RE.findall(line)
        + _HREF_TARGET_RE.findall(line)
        + line.split()
    )
    for t0 in raw:
        t = _HASH_QUERY_RE.sub("", t0)
        t = _LEADING_QUOTE_RE.sub("", t)
        t = _TRAILING_PUNCT_RE.sub("", t)
        t = t.replace("\\", "/")
        if not t:
            continue
        if "/" in t:
            pathish.append(t)
        else:
            bare.append(t)
    return pathish, bare


def _token_to_abs(token: Any, plugin_root: Any, plugin_name: Any, file_dir: Any) -> Any:
    """Resolve one path-ish token to an absolute (not yet realpath'd) host path. `${CLAUDE_PLUGIN_ROOT}`
    and a leading `<pluginName>/` both mean the plugin root; everything else is relative to the
    directory of the file the token was found in. Mirrors `tokenToAbs()`."""
    if "${CLAUDE_PLUGIN_ROOT}" in token:
        return os.path.normpath(token.replace("${CLAUDE_PLUGIN_ROOT}", plugin_root))
    if plugin_name and token.startswith(plugin_name + "/"):
        return os.path.normpath(os.path.join(plugin_root, token[len(plugin_name) + 1 :]))
    if os.path.isabs(token):
        return os.path.normpath(token)
    return os.path.normpath(os.path.join(file_dir, token))


def _realpath_strict(path: Any) -> Any:
    """Mirrors node's `realpathSync`: resolves symlinks and raises if any path component doesn't exist
    (unlike `os.path.realpath`, which resolves lexically even against a nonexistent path)."""
    return str(Path(path).resolve(strict=True))


def _links_in(text: Any, file_dir: Any, plugin_root: Any, plugin_name: Any, by_basename: Any) -> Any:
    """Every plugin-root reference `text` (from a file at `file_dir`) points at, mapped to the 1-based
    line it was pointed at from. Mirrors `linksIn()` -- including the ARMING rule: a token resolving to
    the plugin-root `references/` DIRECTORY ITSELF arms bare-basename matching for THAT LINE ONLY; it
    never recurses and never carries to the next line."""
    try:
        refs_dir = _realpath_strict(os.path.join(plugin_root, "references"))
    except OSError:
        return {}
    hits = {}
    for i, line in enumerate(text.splitlines()):
        pathish, bare = _line_tokens(line)
        armed = False
        for t in pathish:
            abs_path = _token_to_abs(t, plugin_root, plugin_name, file_dir)
            try:
                rp = _realpath_strict(abs_path)
            except OSError:
                continue  # most prose tokens are not paths at all
            if rp == refs_dir:
                armed = True
                continue
            if rp.startswith(refs_dir + os.sep):
                rel = "references/" + rp[len(refs_dir) + 1 :].replace(os.sep, "/")
                if rel not in hits:
                    hits[rel] = i + 1
        if not armed:
            continue
        for b in bare:
            rel = by_basename.get(b)
            if rel is not None and rel not in hits:
                hits[rel] = i + 1
    return hits


def _is_clean_utf8(path: Any) -> Any:
    """Valid UTF-8, decided by the decoder rather than by scanning the decoded string -- mirrors
    `isCleanUtf8()` (a `TextDecoder("utf-8", { fatal: true })` decode). `bytes.decode("utf-8")` is
    strict by default, so a decode failure (not a scan of the result) is what disqualifies a file."""
    try:
        path.read_bytes().decode("utf-8")
        return True
    except (OSError, UnicodeDecodeError):
        return False


def _resolve_root_references(skill_dir: Any, plugin_dir: Any, agents: Any) -> Any:
    """Low-level worker, taking an explicit `plugin_dir` so the same-directory guard below is directly
    unit-testable regardless of how a caller derives `plugin_dir`. Mirrors `resolveRootReferences()`,
    clauses 1 + 2 only:
      1. the skill's own authored text (SKILL.md + its own `references/**`), and
      2. every sub-agent body already in the corpus (`agents`, from `_resolve_corpus_agents`).

    Clause 3 in the TS packager (files the graded AGENT actually read during a live run) is
    run-dependent -- it needs a recorded turn's access log -- and CANNOT be mirrored by a static lint
    pass with no run to inspect, so it is deliberately NOT reproduced here. This makes this function's
    count a floor, never an exact match, relative to what a real critique run would package; that is the
    same "warn early, the packager's report is the authority" posture the rest of this linter already
    has for the ceiling.

    Two further known, deliberate divergences (not fixed here -- out of scope for this change):
      - byte counting: the packager measures UTF-8-DECODED string length while `_lint_skill_corpus_size`
        (like its pre-existing SKILL.md/references/agents counting) sums `stat().st_size` -- raw bytes
        on disk. These agree for pure single-byte UTF-8 text and diverge slightly otherwise.
      - cleanliness filtering: this module's existing `references/` walks (`rglob("*")`, used here and
        for the skill's own references/** in `_lint_skill_corpus_size`) have no git-tracked-set or
        symlink-containment filter, unlike `listSkillFilesRecursive` in corpus-walk.ts. This function
        reuses that same untared posture for consistency with the rest of this linter, not because it is
        provably safe against a hostile references/ tree."""
    skill_dir = Path(skill_dir)
    plugin_dir = Path(plugin_dir)
    # SKIP (not "dedupe") the standalone-skill shape: those files are already packaged as skill-local,
    # and running this pass too would double-count them under two different display keys.
    try:
        same = skill_dir.resolve(strict=True) == plugin_dir.resolve(strict=True)
    except OSError:
        same = skill_dir.resolve() == plugin_dir.resolve()
    if same:
        return []
    refs_root = plugin_dir / "references"
    if not refs_root.is_dir():
        return []
    all_files = sorted(p for p in refs_root.rglob("*") if p.is_file())
    if not all_files:
        return []
    plugin_name = _read_plugin_name(plugin_dir) or plugin_dir.name
    # Later (sorted) entries win on a real basename collision -- matches the TS `Map` construction,
    # where each duplicate key overwrites the previous.
    by_basename = {}
    for p in all_files:
        rel = "references/" + p.relative_to(refs_root).as_posix()
        by_basename[p.name] = rel

    linked = set()
    sources = [skill_dir / "SKILL.md"]
    local_refs = skill_dir / "references"
    if local_refs.is_dir():
        sources.extend(p for p in sorted(local_refs.rglob("*")) if p.is_file())
    sources.extend(Path(a) for a in agents)
    for src in sources:
        try:
            text = src.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for rel in _links_in(text, str(src.parent), str(plugin_dir), plugin_name, by_basename):
            linked.add(rel)

    packaged = []
    for p in all_files:
        rel = "references/" + p.relative_to(refs_root).as_posix()
        if rel not in linked:
            continue
        if not _is_clean_utf8(p):
            continue
        packaged.append(p)
    return packaged


def _resolve_corpus_root_references(skill_dir: Any, agents: Any) -> Any:
    """Every plugin-root `references/` file the critique packager will put in THIS skill's evidence
    corpus, as a sorted list of Paths. Derives `plugin_dir` the same way `_resolve_corpus_agents` does
    (the `skills/<name>` multi-skill-plugin shape); a standalone skill (no `skills/` parent) has no
    plugin-root references pass and is unaffected."""
    skill_dir = Path(skill_dir)
    # Walk UP for the manifest, exactly as the TypeScript side does (`findEnclosingPluginDir`). The
    # old `parent.name == "skills"` LAYOUT rule disagreed with the packager outside the
    # `<root>/skills/<name>` shape: a skill at `<root>/foo/SKILL.md` with a manifest at `<root>` made the
    # packager size a corpus this sized as ZERO, which is the packager-vs-linter divergence 0003e38
    # closed in one shape and left open in another.
    # Nearest MANIFEST first (matching the TypeScript `findEnclosingPluginDir`), falling back to the
    # `<root>/skills/<name>` LAYOUT. Manifest-only diverged from the packager for a manifest-less plugin,
    # where the TS side still enumerates agents because it is handed the root explicitly; layout-only
    # diverged for a skill that is not under `skills/` but does have a manifest above it, which the
    # packager sizes and this sized as ZERO. Neither rule alone matches; the union does.
    plugin_dir = _find_enclosing_plugin_dir(skill_dir / "SKILL.md") or (
        skill_dir.parent.parent if skill_dir.parent.name == "skills" else None
    )
    if plugin_dir is None:
        return []
    return _resolve_root_references(skill_dir, plugin_dir, agents)


def _find_enclosing_plugin_dir(skill_md_path: Any) -> Any:
    """Resolve the enclosing plugin: walk up from a SKILL.md to the nearest ancestor dir containing
    `.claude-plugin/plugin.json` or `plugin.json` — that's the enclosing plugin. None if no ancestor
    has one (a bare SKILL.md dir with no plugin manifest anywhere above it)."""
    start = Path(skill_md_path).resolve().parent
    for anc in [start, *start.parents]:
        if (anc / ".claude-plugin" / "plugin.json").is_file() or (anc / "plugin.json").is_file():
            return anc
    return None


def resolve_agents(skill_dir: Any) -> Any:
    return _resolve_corpus_agents(skill_dir)


def resolve_root_references(skill_dir: Any, agents: Any) -> Any:
    return _resolve_corpus_root_references(skill_dir, agents)
