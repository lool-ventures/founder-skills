#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The plugin's own files, by hash: `data/script-hashes.json`, and the check of a plugin root against it.

WHAT IS LISTED. `files`: every `*.py` under the plugin root, by its plugin-relative POSIX path, except the
top-level `tests/` folder (a `tests/` deeper down is listed), any folder whose name starts with `.` or `__`
(`__pycache__`, `__MACOSX`, a runtime's `.in_use/`) and any file whose name starts with `.` (`._x.py`
AppleDouble entries, `.#x.py` editor locks). A file named `__init__.py` is a module and is listed.
`agent_bodies`: every `agents/*.md`, hashed by the text AFTER its front matter, because an installer
rewrites the front matter (a `description: >` block becomes one quoted line, a `tools: [...]` list a
block list) while the body arrives as written; a file with no front matter is hashed whole. Any `.md`
added here later needs the same rule: installers rewrite SKILL.md front matter too. Each hash is the
sha256 of the bytes with CRLF folded to LF, so a checkout with Windows line endings hashes the same.

THE CHECK. `verify_detail(root)` names every listed file under `root` that differs, is missing or cannot be
read, and every `.py` the same walk finds that the manifest does not list (a new `scripts/json.py` would be
imported by a script in that folder before the standard library's). It never raises. When it cannot judge
the root it returns no list and says why: the manifest is absent or not one this module writes, or more
than `max(5, entries // 10)` LISTED entries differ, which an installer transform or a mixed install produces,
and an improvised edit to one or a few files does not. Unlisted scripts are always named and never count
toward that threshold (a package installed into a scripts folder is an edit, not another install).
Residual: the walk does not follow a symlinked folder inside the plugin (`os.walk`'s default; following one
could loop or leave the plugin), so its listed files read as missing and, past the threshold, the check is
off for that install. No install measured carries one; the plugin ROOT reached through a symlink (the Cowork
host loop's) is walked normally.

USE. `--write` regenerates the manifest of the plugin this file belongs to (run it after editing any plugin
`.py` or agent body); `--check` verifies this plugin (or `--root DIR` against this plugin's manifest) and
exits 1 naming what differs, 0 when clean or when no usable manifest exists (with one line saying so).
Python 3.9, standard library only: the PreToolUse hook loads this module.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from typing import Any

MANIFEST_REL = "data/script-hashes.json"
SCHEMA = 1
ALGORITHM = "sha256"
LINE_ENDINGS = "crlf-as-lf"
PLUGIN_ROOT = os.path.normpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGEN = "python3 founder-skills/scripts/script_hashes.py --write"


def agent_body(data: bytes) -> bytes:
    """The bytes after an agent file's front matter: when the first line is `---`, everything after the
    next line that is exactly `---`; otherwise (or with no closing line) the whole file."""
    lines = data.split(b"\n")
    if not lines or lines[0].rstrip(b"\r") != b"---":
        return data
    for i in range(1, len(lines)):
        if lines[i].rstrip(b"\r") == b"---":
            return b"\n".join(lines[i + 1 :])
    return data


def digest(path: str, body: bool = False) -> str | None:
    """sha256 of the file with CRLF folded to LF (the body only when `body`), or None when it cannot be read."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    data = data.replace(b"\r\n", b"\n")
    if body:
        data = agent_body(data)
    return hashlib.sha256(data).hexdigest()


def _python_files(root: str) -> list[str]:
    """Plugin-relative POSIX paths of every `.py` under `root` the manifest lists (the walk rule above)."""
    out = []
    for folder, dirs, files in os.walk(root):
        rel_folder = os.path.relpath(folder, root)
        dirs[:] = sorted(d for d in dirs if not d.startswith((".", "__")) and not (rel_folder == "." and d == "tests"))
        for name in files:
            if name.endswith(".py") and not name.startswith("."):
                rel = name if rel_folder == "." else os.path.join(rel_folder, name)
                out.append(rel.replace(os.sep, "/"))
    return sorted(out)


def _agent_files(root: str) -> list[str]:
    folder = os.path.join(root, "agents")
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    return sorted(f"agents/{n}" for n in names if n.endswith(".md") and not n.startswith("."))


def build(root: str) -> dict[str, Any]:
    """The manifest for the plugin at `root`."""
    files: dict[str, Any] = {rel: digest(os.path.join(root, rel)) for rel in _python_files(root)}
    bodies: dict[str, Any] = {rel: digest(os.path.join(root, rel), body=True) for rel in _agent_files(root)}
    return {"schema": SCHEMA, "algorithm": ALGORITHM, "line_endings": LINE_ENDINGS, "files": files,
            "agent_bodies": bodies}  # fmt: skip


def manifest_text(root: str) -> str:
    return json.dumps(build(root), indent=2, sort_keys=True) + "\n"


def load_manifest(path: str) -> tuple[dict[str, Any] | None, str]:
    """(manifest, "") when `path` holds a manifest this module writes; (None, why) otherwise."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None, f"no manifest at {path}"
    except (OSError, ValueError) as e:
        return None, f"manifest unreadable: {type(e).__name__}"
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or data.get("algorithm") != ALGORITHM:
        return None, "manifest is not a schema-1 sha256 manifest"
    for key in ("files", "agent_bodies"):
        entries = data.get(key)
        if not isinstance(entries, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in entries.items()
        ):
            return None, f"manifest {key} is not a map of paths to hashes"
    return data, ""


def threshold(entries: int) -> int:
    """How many differing entries still describe an edit rather than another install."""
    return max(5, entries // 10)


def verify_detail(root: str, manifest_path: str | None = None) -> tuple[list[str] | None, str]:
    """(differing plugin-relative paths, "") for `root` against the manifest (this root's own by default),
    or (None, why) when the manifest cannot judge it. Never raises."""
    try:
        path = manifest_path or os.path.join(root, MANIFEST_REL)
        manifest, why = load_manifest(path)
        if manifest is None:
            return None, why
        files: dict[str, str] = manifest["files"]
        bodies: dict[str, str] = manifest["agent_bodies"]
        listed = [rel for rel, want in files.items() if digest(os.path.join(root, rel)) != want]
        listed += [rel for rel, want in bodies.items() if digest(os.path.join(root, rel), body=True) != want]
        entries = len(files) + len(bodies)
        if len(listed) > threshold(entries):
            return None, f"{len(listed)} of {entries} files differ: the manifest does not describe this install"
        # Unlisted scripts never count toward the threshold: a package installed into a scripts folder is an
        # edit to hold on, not an install the manifest fails to describe.
        unlisted = [rel for rel in _python_files(root) if rel not in files]
        return sorted(set(listed + unlisted)), ""
    except Exception as e:  # noqa: BLE001 - the hook's check must never take the whole dispatch check down
        return None, f"{type(e).__name__}: {e}"


def verify(root: str, manifest_path: str | None = None) -> list[str] | None:
    """The differing paths (`verify_detail`), or None when the manifest cannot judge `root`."""
    return verify_detail(root, manifest_path)[0]


def manifest_entry(rel: str, manifest_path: str | None = None) -> str | None:
    """This plugin's manifest hash for one listed file, or None (no usable manifest, or not listed)."""
    manifest, _why = load_manifest(manifest_path or os.path.join(PLUGIN_ROOT, MANIFEST_REL))
    if manifest is None:
        return None
    value = manifest["files"].get(rel)
    return value if isinstance(value, str) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The plugin's script hashes: regenerate or check them.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help=f"rewrite {MANIFEST_REL} for this plugin")
    mode.add_argument("--check", action="store_true", help="check a plugin root against this plugin's manifest")
    parser.add_argument("--root", help="the plugin root to check (default: this plugin)")
    args = parser.parse_args(argv)
    manifest_path = os.path.join(PLUGIN_ROOT, MANIFEST_REL)
    if args.write:
        if args.root:
            parser.error("--root is for --check")
        with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(manifest_text(PLUGIN_ROOT))
        print(f"wrote {manifest_path}", file=sys.stderr)
        return 0
    root = os.path.abspath(args.root) if args.root else PLUGIN_ROOT
    mismatched, why = verify_detail(root, manifest_path)
    if mismatched is None:
        print(f"script_hashes: plugin files not checked ({why})", file=sys.stderr)
        # On this plugin's own tree the manifest must describe it exactly: a stale manifest after a large
        # change is not "another install". The threshold only spares installs this tree did not produce.
        if root == PLUGIN_ROOT and why.endswith("does not describe this install"):
            print(f"after editing the plugin, regenerate it: {REGEN}", file=sys.stderr)
            return 1
        return 0
    if mismatched:
        print(f"script_hashes: {len(mismatched)} plugin file(s) differ from {MANIFEST_REL}:", file=sys.stderr)
        for rel in mismatched:
            print(f"  {rel}", file=sys.stderr)
        print(f"after editing the plugin, regenerate it: {REGEN}", file=sys.stderr)
        return 1
    print(f"script_hashes: {root} matches {MANIFEST_REL}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
