"""Derive each skill's `coaching_payload` top-level keys FROM THE EMITTER, statically.

WHY THIS EXISTS. Every skill's contract test pinned a HAND-TYPED set of payload key names. In one
evening six defects passed through it: two keys emitted and named by no prompt at all
(`market_size_approach`, `consensus_strength`), and four prompts describing a shape the producer
had stopped emitting. The hand-typed set was the defect; the instances were symptoms.

WHY STATIC, NOT A COMPOSE RUN. financial-model-review emits `base_runway_note` conditionally
(`**({...} if base_is_default_alive else {})`). A set derived by composing a fixture contains it
only if that fixture happens to be default-alive -- the committed one is not. Reading the source
sees the key regardless of the data, which is the property that matters for a contract.

WHAT IT DELIBERATELY DOES NOT DO. It is a LOWER BOUND on what the prompts must name, in the
ADDITION direction only: a derived set shrinks automatically when an emission line is deleted, so
it can never catch a key that stopped being emitted while the prompts still name it. That
direction stays with `test_compose_invariants.py::_COACHING_COVERAGE_KEYS`, which pins named keys
at the EMISSION site precisely because deleting three emission lines once left the whole suite
green. Derivation does not replace that constant and must not be read as making it redundant.

It is also blind to SHAPE: it sees `high_severity_warnings` as a name, not as
`{code, label, message}`. Four of the six defects were shape drift inside a key that was present.
`test_coaching_payload_key_shape` covers that axis separately.

FAILURE POSTURE. Every unresolvable construct RAISES. A derivation that silently returns a short
set is worse than the hand list it replaces: the hand list at least fails loudly when a human
reads it, where a quiet degradation looks exactly like a clean pass.
"""

from __future__ import annotations

import ast
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / "founder-skills" / "skills"

EMITTERS: dict[str, str] = {
    "deck-review": "_emit_coaching_payload",
    "cap-table": "build_coaching_payload",
    "market-sizing": "_emit_coaching_payload",
    "ic-sim": "_emit_coaching_payload",
    "financial-model-review": "_emit_coaching_payload",
    "competitive-positioning": "_emit_coaching_payload",
}


class UnresolvedPayloadKey(RuntimeError):
    """The emitter uses a construct this derivation cannot read. Fix the derivation, never
    downgrade it to a silent skip."""


def _literal_keys(node: ast.Dict, where: str) -> set[str]:
    keys: set[str] = set()
    for k, v in zip(node.keys, node.values, strict=False):
        if k is None:
            keys |= _unpacked_keys(v, where)
            continue
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            keys.add(k.value)
        else:
            raise UnresolvedPayloadKey(f"{where}: non-literal dict key {ast.dump(k)[:80]}")
    return keys


def _unpacked_keys(value: ast.expr, where: str) -> set[str]:
    """`**{...}` and `**({...} if cond else {})` -- both branches count, since either may ship."""
    if isinstance(value, ast.Dict):
        return _literal_keys(value, where)
    if isinstance(value, ast.IfExp):
        out: set[str] = set()
        for branch in (value.body, value.orelse):
            if isinstance(branch, ast.Dict):
                out |= _literal_keys(branch, where)
            else:
                raise UnresolvedPayloadKey(f"{where}: ** conditional branch is not a dict literal")
        return out
    raise UnresolvedPayloadKey(f"{where}: ** unpacking of {ast.dump(value)[:80]}")


def _returned_dict(fn: ast.FunctionDef, where: str) -> tuple[ast.Dict, str | None]:
    """The dict the function returns, plus the name it was bound to (if any)."""
    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None]
    if len(returns) != 1:
        # Two return paths could ship different key sets; picking one silently is how a
        # derivation reports a confident wrong answer.
        raise UnresolvedPayloadKey(f"{where}: expected exactly 1 return, found {len(returns)}")
    value = returns[0].value
    assert value is not None  # filtered above, but mypy cannot see it
    if isinstance(value, ast.Dict):
        return value, None
    if isinstance(value, ast.Name):
        for node in ast.walk(fn):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            else:
                continue
            if any(isinstance(t, ast.Name) and t.id == value.id for t in targets):
                if isinstance(node.value, ast.Dict):
                    return node.value, value.id
                raise UnresolvedPayloadKey(f"{where}: `{value.id}` is not bound to a dict literal")
    raise UnresolvedPayloadKey(f"{where}: return is {ast.dump(value)[:80]}")


def _subscript_keys(fn: ast.FunctionDef, name: str, where: str) -> set[str]:
    """`payload["x"] = ...` after construction. cap-table adds `flip_specifics` this way."""
    keys: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            if not (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id == name):
                continue
            if isinstance(t.slice, ast.Constant) and isinstance(t.slice.value, str):
                keys.add(t.slice.value)
            else:
                raise UnresolvedPayloadKey(f"{where}: computed subscript on `{name}`")
    return keys


def emitted_top_level_keys(skill: str) -> set[str]:
    """Top-level keys of `skill`'s coaching_payload, read from its compose script."""
    fn_name = EMITTERS[skill]
    path = SKILLS_ROOT / skill / "scripts" / "compose_report.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fn_name),
        None,
    )
    if fn is None:
        raise UnresolvedPayloadKey(f"{skill}: no function {fn_name}")
    where = f"{skill}.{fn_name}"
    node, bound_name = _returned_dict(fn, where)
    keys = _literal_keys(node, where)
    if bound_name:
        keys |= _subscript_keys(fn, bound_name, where)
    return keys
