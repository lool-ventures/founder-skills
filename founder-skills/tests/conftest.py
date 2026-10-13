"""Session-wide fixtures.

ONE FIX FOR TWENTY LEAKS. Twenty test modules build fixtures with a bare `tempfile.mkdtemp()` and
never remove them (`test_market_sizing.py:567` alone left 19,790 `test-compose-*` dirs under $TMPDIR
on one machine; the fleet total was ~62,000 dirs). Rewriting every site to `tmp_path` is a large
diff with no behavioural change; pointing `tempfile`'s default directory at pytest's own basetemp
is one line, covers every site including future ones, and pytest prunes basetemps to the last three
runs on its own. Scoped to the session and restored afterwards, so a test that inspects
`tempfile.gettempdir()` sees the redirected value only while the suite runs.
"""

from __future__ import annotations

import importlib.util
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True, scope="session")
def _tempfiles_under_pytest_basetemp(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    base = tmp_path_factory.getbasetemp() / "mkdtemp"
    base.mkdir(exist_ok=True)
    before = tempfile.tempdir
    tempfile.tempdir = str(base)
    # Subprocesses (every `run_script` call) inherit the same choice through the env.
    env_before = os.environ.get("TMPDIR")
    os.environ["TMPDIR"] = str(base)
    try:
        yield
    finally:
        tempfile.tempdir = before
        if env_before is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = env_before


@pytest.fixture(scope="session")
def plugin_hashes_current() -> None:
    """For the modules that run the dispatch-prompt hook against this checkout: the hook holds a paired
    dispatch while a plugin file differs from `data/script-hashes.json`, so an edited `.py` with the
    manifest not regenerated would read as dozens of hook failures. Fail once, naming the command.
    Requested per module (never autouse, never at session start): the mutation lane runs a child pytest in
    a mutated copy of the tree and must not trip it."""
    path = Path(__file__).resolve().parents[1] / "scripts" / "script_hashes.py"
    spec = importlib.util.spec_from_file_location("script_hashes_conftest", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mismatched, why = mod.verify_detail(str(path.parents[1]))
    if mismatched is None or mismatched:
        pytest.fail(
            f"plugin files differ from data/script-hashes.json ({', '.join(mismatched or []) or why}): run "
            "`python3 founder-skills/scripts/script_hashes.py --write`",
            pytrace=False,
        )
