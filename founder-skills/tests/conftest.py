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

import os
import tempfile
from collections.abc import Iterator

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
