"""`scripts/_redteam_core.py`: the adversarial review's shared rules, loaded by path by each skill.

Market-sizing's behaviour is pinned by its own suites, run unmodified against the shared module. What
is pinned here is the module's own contract: it loads from nothing but its path, the rules have one
home, and the copies that must stay identical to it do.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "scripts" / "_redteam_core.py"
MS = ROOT / "skills" / "market-sizing" / "scripts"
CP = ROOT / "skills" / "competitive-positioning" / "scripts"


def _function(path: Path, name: str, rename: dict[str, str] | None = None) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    node.name = "f"
    body = node.body
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
        node.body = body[1:]  # docstrings may differ; the code may not
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and rename and sub.id in rename:
            sub.id = rename[sub.id]
    return ast.unparse(node)


def test_the_core_loads_from_its_path_alone() -> None:
    """A skill's producer loads it with nothing but the file: no package, no sibling module."""
    code = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('_redteam_core', {str(CORE)!r})\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "print(m.INTERNAL_PROVENANCE, m.COPY_KEY)\n"
    )
    r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd="/")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["internal:analysis", "_review_copy"]


def test_market_sizing_keeps_no_copy_of_the_rules() -> None:
    """The rules have one home. A definition reappearing in red_team.py is a second copy to drift."""
    tree = ast.parse((MS / "red_team.py").read_text(encoding="utf-8"))
    defined = {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    defined |= {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    for name in ("_REQUIRED_FIELDS", "INTERNAL_PROVENANCE", "_DOC_RE", "_JSON_QUOTE_RE", "_reject_reason"):
        assert name not in defined, f"red_team.py defines {name} again; it lives in scripts/_redteam_core.py"
    assert "_PARAMETER_NAMES" in defined  # what IS a sizing's own stays with the sizing


def test_the_page_reader_matches_market_sizings() -> None:
    """market-sizing's review keeps its own reader (its report checks a founder's quote with a pinned
    copy of it); the shared one, which other skills use, must read a page the same way."""
    assert _function(CORE, "page_text", {"TEXT_LAYER_FLOOR": "_F"}) == _function(
        MS / "red_team.py", "_page_text", {"_TEXT_LAYER_FLOOR": "_F"}
    )


def test_the_document_list_matches_the_prompt_generators() -> None:
    """A document the prompt lists must be one a citation may name."""
    assert _function(CORE, "list_documents") == _function(MS / "dispatch_prompt.py", "list_documents")
    assert _function(CORE, "list_documents") == _function(CP / "cp_dispatch_prompt.py", "list_documents")


def test_a_missing_core_is_refused_loudly_even_when_the_text_policy_is_present(tmp_path: Path) -> None:
    """A mixed install: the shared dir carries the founder-text policy but not this module. The
    producer must refuse, leave -o untouched, and say which file is missing -- not fail on first use
    with a traceback after the text policy check has already passed."""
    import json
    import shutil

    lone = tmp_path / "plugin" / "skills" / "market-sizing" / "scripts"
    lone.mkdir(parents=True)
    for name in ("red_team.py", "_redteam_text.py", "_redteam_copy.py", "_quote_match.py"):
        shutil.copy(MS / name, lone / name)
    shared = tmp_path / "plugin" / "scripts"
    shared.mkdir()
    shutil.copy(ROOT / "scripts" / "_founder_text.py", shared / "_founder_text.py")
    out = tmp_path / "redteam.json"
    out.write_text('{"sentinel": true}')
    finding = {
        "claim_attacked": "x",
        "what_is_true": "y",
        "evidence_quote": "a sentence long enough to count as a quote here",
        "source_url": "https://example.com",
        "source_title": "t",
        "severity": "low",
    }
    proc = subprocess.run(
        [sys.executable, str(lone / "red_team.py"), "--run-id", "R1", "-o", str(out)],
        input=json.dumps({"findings": [finding]}),
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert json.loads(out.read_text()) == {"sentinel": True}, "-o must be left untouched"
    assert "shared scripts" in proc.stdout and "_redteam_core.py" in proc.stdout, proc.stdout
