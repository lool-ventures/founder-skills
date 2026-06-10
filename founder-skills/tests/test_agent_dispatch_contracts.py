"""Verify agent dispatch contracts (the JSON shapes the agent is told to
return) match the producer scripts' schemas. This locks in the
'agent-says-X / script-expects-X' contract that Mitigation 1 dispatch
relies on.

DISPATCH_CONTRACTS is loaded from the checked-in fixture file produced
by Phase 0 Task 0c (founder-skills/tests/fixtures/dispatch_contracts.json).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "dispatch_contracts.json"


def _load_dispatch_contracts() -> list[tuple[str, str, str, list[str]]]:
    """Load the per-skill DISPATCH_CONTRACTS from the fixture file.

    Fixture format (per Phase 0 Task 0c):
        {
          "<skill>": {
            "<DISPATCH_TYPE>": {
              "schema": "<schema-filename-or-empty-string>",
              "required_fields_minus_metadata": ["<field>", ...]
            },
            ...
          },
          ...
        }
    Returns a list of (skill, dispatch_type, schema, fields) tuples for
    pytest parameterization.
    """
    if not FIXTURE_PATH.is_file():
        pytest.skip(
            f"DISPATCH_CONTRACTS fixture not found at {FIXTURE_PATH}. Run Phase 0 Task 0c (schema audit) to produce it."
        )
    data = json.loads(FIXTURE_PATH.read_text())
    rows = []
    for skill, dispatches in data.items():
        for dispatch_type, contract in dispatches.items():
            rows.append(
                (
                    skill,
                    dispatch_type,
                    contract.get("schema", ""),
                    contract.get("required_fields_minus_metadata", []),
                )
            )
    return rows


DISPATCH_CONTRACTS = _load_dispatch_contracts()


@pytest.mark.parametrize("skill,dispatch_type,schema_file,expected_fields", DISPATCH_CONTRACTS)
def test_dispatch_contract_matches_schema(
    skill: str,
    dispatch_type: str,
    schema_file: str,
    expected_fields: list[str],
) -> None:
    """Each Context A dispatch type's agent body documentation must list
    the fields the producer script's schema requires (minus metadata)."""
    agent_path = REPO_ROOT / "agents" / f"{skill}.md"
    assert agent_path.is_file(), f"Agent file not found: {agent_path}"
    agent_body = agent_path.read_text()

    # The agent body must mention this dispatch type
    assert dispatch_type in agent_body, f"{skill}.md doesn't document Context A subtype {dispatch_type!r}"

    # And each expected field must appear somewhere in the agent body
    for field in expected_fields:
        assert field in agent_body, f"{skill}.md Context A ({dispatch_type}) doesn't mention field {field!r}"


# Per-skill Context B success-payload shapes.
# These must match the actual field names documented in both the agent body
# (founder-skills/agents/<skill>.md) and the SKILL.md step that reads the
# sub-agent's return value.
COACHING_PAYLOADS: dict[str, list[str]] = {
    "deck-review": [
        "status",
        "review_dir",
        "report_path",
        "score_pct",
        "overall_status",
        "high_severity_warnings",
    ],
    "competitive-positioning": [
        "status",
        "review_dir",
        "report_path",
        "landscape_summary",
        "top_moats",
        "high_severity_warnings",
    ],
    "financial-model-review": [
        "status",
        "review_dir",
        "report_path",
        "runway_months",
        "overall_status",
        "red_flags",
        "high_severity_warnings",
    ],
    "ic-sim": [
        "status",
        "review_dir",
        "report_path",
        "decision",
        "consensus_strength",
        "key_concerns",
        "high_severity_warnings",
    ],
    "market-sizing": [
        "status",
        "review_dir",
        "report_path",
        "tam",
        "sam",
        "som",
        "methodology",
        "confidence",
        "high_severity_warnings",
    ],
}


@pytest.mark.parametrize("skill,fields", COACHING_PAYLOADS.items())
def test_coaching_payload_documented(skill: str, fields: list[str]) -> None:
    """Each agent's Context B success-payload fields must appear in both
    the agent body and the corresponding SKILL.md step (post-compose
    coaching dispatch)."""
    agent_path = REPO_ROOT / "agents" / f"{skill}.md"
    skill_md_path = REPO_ROOT / "skills" / skill / "SKILL.md"

    assert agent_path.is_file(), f"Agent file not found: {agent_path}"
    assert skill_md_path.is_file(), f"SKILL.md not found: {skill_md_path}"

    agent_body = agent_path.read_text()
    skill_md = skill_md_path.read_text()

    for field in fields:
        assert field in agent_body, f"{skill}.md Context B missing payload field {field!r}"
        assert field in skill_md, f"skills/{skill}/SKILL.md doesn't document payload field {field!r}"


# --------------------------------------------------------------------------
# v0.4.2 Mitigation 2 — deck-review Context B (POST_COMPOSE_COACHING)
# --------------------------------------------------------------------------


def _load_deck_review_post_compose_coaching_contract() -> dict[str, object]:
    data = json.loads(FIXTURE_PATH.read_text())
    contract = data["deck-review"].get("POST_COMPOSE_COACHING")
    assert contract is not None, (
        "deck-review fixture is missing the POST_COMPOSE_COACHING entry. v0.4.2 Phase 4 Task 9 added it."
    )
    assert isinstance(contract, dict)
    return contract  # type: ignore[no-any-return]


def test_deck_review_context_b_contract_documented() -> None:
    """Each `required_action` keyword from the POST_COMPOSE_COACHING fixture
    must appear literally in the deck-review agent body's Context B section,
    along with the literal `POST_COMPOSE_COACHING` dispatch_type — which is
    what makes the existing parameterized
    `test_dispatch_contract_matches_schema` pass for this fixture row."""
    contract = _load_deck_review_post_compose_coaching_contract()
    agent_body = (REPO_ROOT / "agents" / "deck-review.md").read_text()

    assert "POST_COMPOSE_COACHING" in agent_body, (
        "deck-review agent body does not include the literal POST_COMPOSE_COACHING dispatch_type"
    )

    required_actions = contract["required_actions"]
    assert isinstance(required_actions, list)
    for action in required_actions:
        assert isinstance(action, str)
        assert action in agent_body, f"deck-review agent body Context B does not document required action {action!r}"

    required_input_keys = contract["required_input_keys"]
    assert isinstance(required_input_keys, list)
    for key in required_input_keys:
        assert isinstance(key, str)
        assert key in agent_body, f"deck-review agent body Context B does not mention required input key {key!r}"


def test_deck_review_context_b_forbidden_actions_documented() -> None:
    """Each `forbidden_action` from the fixture must be mentioned in the
    deck-review agent body's hard-rules section, so authors who try to
    "just Read the report" are warned away by the agent body itself."""
    contract = _load_deck_review_post_compose_coaching_contract()
    agent_body = (REPO_ROOT / "agents" / "deck-review.md").read_text()

    forbidden_actions = contract["forbidden_actions"]
    assert isinstance(forbidden_actions, list)

    # Locate the Hard rules block inside Context B. Anchored on the
    # POST_COMPOSE_COACHING heading so we don't accidentally match Context A's
    # own Hard rules.
    ctx_b_anchor = "Context B — Post-compose coaching dispatch (POST_COMPOSE_COACHING)"
    ctx_b_idx = agent_body.find(ctx_b_anchor)
    assert ctx_b_idx >= 0, f"Could not find Context B anchor in deck-review agent body: {ctx_b_anchor!r}"
    # Section ends at the next top-level "## " heading.
    next_section_idx = agent_body.find("\n## ", ctx_b_idx + 1)
    ctx_b_block = agent_body[ctx_b_idx:next_section_idx] if next_section_idx > 0 else agent_body[ctx_b_idx:]

    hard_rules_idx = ctx_b_block.find("Hard rules")
    assert hard_rules_idx >= 0, "deck-review Context B section is missing a 'Hard rules' block"
    hard_rules_block = ctx_b_block[hard_rules_idx:]

    for action in forbidden_actions:
        assert isinstance(action, str)
        assert action in hard_rules_block, (
            f"deck-review agent body Context B 'Hard rules' block does not document forbidden action {action!r}"
        )


def test_deck_review_context_b_return_payload_keys_match_v0_4_1() -> None:
    """Backward-compat check: the v0.4.2 POST_COMPOSE_COACHING fixture's
    `return_payload_keys` MUST match the deck-review v0.4.1 Context B
    return shape (pinned in COACHING_PAYLOADS)."""
    contract = _load_deck_review_post_compose_coaching_contract()
    fixture_keys = contract["return_payload_keys"]
    expected_v041_keys = COACHING_PAYLOADS["deck-review"]
    assert fixture_keys == expected_v041_keys, (
        "POST_COMPOSE_COACHING return_payload_keys drifted from v0.4.1: "
        f"fixture={fixture_keys!r} v0.4.1={expected_v041_keys!r}"
    )


# --------------------------------------------------------------------------
# v0.4.2 Mitigation 2 — competitive-positioning Context B (POST_COMPOSE_COACHING)
# --------------------------------------------------------------------------


def _load_competitive_positioning_post_compose_coaching_contract() -> dict[str, object]:
    data = json.loads(FIXTURE_PATH.read_text())
    contract = data["competitive-positioning"].get("POST_COMPOSE_COACHING")
    assert contract is not None, (
        "competitive-positioning fixture is missing the POST_COMPOSE_COACHING entry. v0.4.2 Phase 4 Task 10 added it."
    )
    assert isinstance(contract, dict)
    return contract  # type: ignore[no-any-return]


def test_competitive_positioning_context_b_contract_documented() -> None:
    """Each `required_action` keyword from the POST_COMPOSE_COACHING fixture
    must appear literally in the competitive-positioning agent body's Context B
    section, along with the literal `POST_COMPOSE_COACHING` dispatch_type — which
    is what makes the existing parameterized
    `test_dispatch_contract_matches_schema` pass for this fixture row."""
    contract = _load_competitive_positioning_post_compose_coaching_contract()
    agent_body = (REPO_ROOT / "agents" / "competitive-positioning.md").read_text()

    assert "POST_COMPOSE_COACHING" in agent_body, (
        "competitive-positioning agent body does not include the literal POST_COMPOSE_COACHING dispatch_type"
    )

    required_actions = contract["required_actions"]
    assert isinstance(required_actions, list)
    for action in required_actions:
        assert isinstance(action, str)
        assert action in agent_body, (
            f"competitive-positioning agent body Context B does not document required action {action!r}"
        )

    required_input_keys = contract["required_input_keys"]
    assert isinstance(required_input_keys, list)
    for key in required_input_keys:
        assert isinstance(key, str)
        assert key in agent_body, (
            f"competitive-positioning agent body Context B does not mention required input key {key!r}"
        )


def test_competitive_positioning_context_b_forbidden_actions_documented() -> None:
    """Each `forbidden_action` from the fixture must be mentioned in the
    competitive-positioning agent body's hard-rules section, so authors who try
    to 'just Read the report' are warned away by the agent body itself."""
    contract = _load_competitive_positioning_post_compose_coaching_contract()
    agent_body = (REPO_ROOT / "agents" / "competitive-positioning.md").read_text()

    forbidden_actions = contract["forbidden_actions"]
    assert isinstance(forbidden_actions, list)

    # Locate the Hard rules block inside Context B. Anchored on the
    # POST_COMPOSE_COACHING heading so we don't accidentally match Context A's
    # own Hard rules.
    ctx_b_anchor = "Context B — Post-compose coaching dispatch (POST_COMPOSE_COACHING)"
    ctx_b_idx = agent_body.find(ctx_b_anchor)
    assert ctx_b_idx >= 0, f"Could not find Context B anchor in competitive-positioning agent body: {ctx_b_anchor!r}"
    # Section ends at the next top-level "## " heading.
    next_section_idx = agent_body.find("\n## ", ctx_b_idx + 1)
    ctx_b_block = agent_body[ctx_b_idx:next_section_idx] if next_section_idx > 0 else agent_body[ctx_b_idx:]

    hard_rules_idx = ctx_b_block.find("Hard rules")
    assert hard_rules_idx >= 0, "competitive-positioning Context B section is missing a 'Hard rules' block"
    hard_rules_block = ctx_b_block[hard_rules_idx:]

    for action in forbidden_actions:
        assert isinstance(action, str)
        assert action in hard_rules_block, (
            "competitive-positioning agent body Context B 'Hard rules' block does not document "
            f"forbidden action {action!r}"
        )


def test_competitive_positioning_context_b_return_payload_keys_match_v0_4_1() -> None:
    """Backward-compat check: the v0.4.2 POST_COMPOSE_COACHING fixture's
    `return_payload_keys` MUST match the competitive-positioning v0.4.1 Context B
    return shape (pinned in COACHING_PAYLOADS)."""
    contract = _load_competitive_positioning_post_compose_coaching_contract()
    fixture_keys = contract["return_payload_keys"]
    expected_v041_keys = COACHING_PAYLOADS["competitive-positioning"]
    assert fixture_keys == expected_v041_keys, (
        "POST_COMPOSE_COACHING return_payload_keys drifted from v0.4.1: "
        f"fixture={fixture_keys!r} v0.4.1={expected_v041_keys!r}"
    )


# --------------------------------------------------------------------------
# v0.4.2 Mitigation 2 — financial-model-review Context B (POST_COMPOSE_COACHING)
# --------------------------------------------------------------------------


def _load_financial_model_review_post_compose_coaching_contract() -> dict[str, object]:
    data = json.loads(FIXTURE_PATH.read_text())
    contract = data["financial-model-review"].get("POST_COMPOSE_COACHING")
    assert contract is not None, (
        "financial-model-review fixture is missing the POST_COMPOSE_COACHING entry. v0.4.2 Phase 4 Task 11 added it."
    )
    assert isinstance(contract, dict)
    return contract  # type: ignore[no-any-return]


def test_financial_model_review_context_b_contract_documented() -> None:
    """Each `required_action` keyword from the POST_COMPOSE_COACHING fixture
    must appear literally in the financial-model-review agent body's Context B
    section, along with the literal `POST_COMPOSE_COACHING` dispatch_type — which
    is what makes the existing parameterized
    `test_dispatch_contract_matches_schema` pass for this fixture row."""
    contract = _load_financial_model_review_post_compose_coaching_contract()
    agent_body = (REPO_ROOT / "agents" / "financial-model-review.md").read_text()

    assert "POST_COMPOSE_COACHING" in agent_body, (
        "financial-model-review agent body does not include the literal POST_COMPOSE_COACHING dispatch_type"
    )

    required_actions = contract["required_actions"]
    assert isinstance(required_actions, list)
    for action in required_actions:
        assert isinstance(action, str)
        assert action in agent_body, (
            f"financial-model-review agent body Context B does not document required action {action!r}"
        )

    required_input_keys = contract["required_input_keys"]
    assert isinstance(required_input_keys, list)
    for key in required_input_keys:
        assert isinstance(key, str)
        assert key in agent_body, (
            f"financial-model-review agent body Context B does not mention required input key {key!r}"
        )


def test_financial_model_review_context_b_forbidden_actions_documented() -> None:
    """Each `forbidden_action` from the fixture must be mentioned in the
    financial-model-review agent body's hard-rules section, so authors who try
    to 'just Read the report' are warned away by the agent body itself."""
    contract = _load_financial_model_review_post_compose_coaching_contract()
    agent_body = (REPO_ROOT / "agents" / "financial-model-review.md").read_text()

    forbidden_actions = contract["forbidden_actions"]
    assert isinstance(forbidden_actions, list)

    # Locate the Hard rules block inside Context B. Anchored on the
    # POST_COMPOSE_COACHING heading so we don't accidentally match Context A's
    # own Hard rules.
    ctx_b_anchor = "Context B — Post-compose coaching dispatch (POST_COMPOSE_COACHING)"
    ctx_b_idx = agent_body.find(ctx_b_anchor)
    assert ctx_b_idx >= 0, f"Could not find Context B anchor in financial-model-review agent body: {ctx_b_anchor!r}"
    # Section ends at the next top-level "## " heading.
    next_section_idx = agent_body.find("\n## ", ctx_b_idx + 1)
    ctx_b_block = agent_body[ctx_b_idx:next_section_idx] if next_section_idx > 0 else agent_body[ctx_b_idx:]

    hard_rules_idx = ctx_b_block.find("Hard rules")
    assert hard_rules_idx >= 0, "financial-model-review Context B section is missing a 'Hard rules' block"
    hard_rules_block = ctx_b_block[hard_rules_idx:]

    for action in forbidden_actions:
        assert isinstance(action, str)
        assert action in hard_rules_block, (
            "financial-model-review agent body Context B 'Hard rules' block does not document "
            f"forbidden action {action!r}"
        )


def test_financial_model_review_context_b_return_payload_keys_match_v0_4_1() -> None:
    """Backward-compat check: the v0.4.2 POST_COMPOSE_COACHING fixture's
    `return_payload_keys` MUST match the financial-model-review v0.4.1 Context B
    return shape (pinned in COACHING_PAYLOADS)."""
    contract = _load_financial_model_review_post_compose_coaching_contract()
    fixture_keys = contract["return_payload_keys"]
    expected_v041_keys = COACHING_PAYLOADS["financial-model-review"]
    assert fixture_keys == expected_v041_keys, (
        "POST_COMPOSE_COACHING return_payload_keys drifted from v0.4.1: "
        f"fixture={fixture_keys!r} v0.4.1={expected_v041_keys!r}"
    )


# --------------------------------------------------------------------------
# v0.4.2 Mitigation 2 — ic-sim Context B (POST_COMPOSE_COACHING)
# --------------------------------------------------------------------------


def _load_ic_sim_post_compose_coaching_contract() -> dict[str, object]:
    data = json.loads(FIXTURE_PATH.read_text())
    contract = data["ic-sim"].get("POST_COMPOSE_COACHING")
    assert contract is not None, (
        "ic-sim fixture is missing the POST_COMPOSE_COACHING entry. v0.4.2 Phase 4 Task 12 added it."
    )
    assert isinstance(contract, dict)
    return contract  # type: ignore[no-any-return]


def test_ic_sim_context_b_contract_documented() -> None:
    """Each `required_action` keyword from the POST_COMPOSE_COACHING fixture
    must appear literally in the ic-sim agent body's Context B section,
    along with the literal `POST_COMPOSE_COACHING` dispatch_type — which is
    what makes the existing parameterized
    `test_dispatch_contract_matches_schema` pass for this fixture row."""
    contract = _load_ic_sim_post_compose_coaching_contract()
    agent_body = (REPO_ROOT / "agents" / "ic-sim.md").read_text()

    assert "POST_COMPOSE_COACHING" in agent_body, (
        "ic-sim agent body does not include the literal POST_COMPOSE_COACHING dispatch_type"
    )

    required_actions = contract["required_actions"]
    assert isinstance(required_actions, list)
    for action in required_actions:
        assert isinstance(action, str)
        assert action in agent_body, f"ic-sim agent body Context B does not document required action {action!r}"

    required_input_keys = contract["required_input_keys"]
    assert isinstance(required_input_keys, list)
    for key in required_input_keys:
        assert isinstance(key, str)
        assert key in agent_body, f"ic-sim agent body Context B does not mention required input key {key!r}"


def test_ic_sim_context_b_forbidden_actions_documented() -> None:
    """Each `forbidden_action` from the fixture must be mentioned in the
    ic-sim agent body's hard-rules section, so authors who try to
    'just Read the report' are warned away by the agent body itself."""
    contract = _load_ic_sim_post_compose_coaching_contract()
    agent_body = (REPO_ROOT / "agents" / "ic-sim.md").read_text()

    forbidden_actions = contract["forbidden_actions"]
    assert isinstance(forbidden_actions, list)

    # Locate the Hard rules block inside Context B. Anchored on the
    # POST_COMPOSE_COACHING heading so we don't accidentally match Context A's
    # own Hard rules.
    ctx_b_anchor = "Context B — Post-compose coaching dispatch (POST_COMPOSE_COACHING)"
    ctx_b_idx = agent_body.find(ctx_b_anchor)
    assert ctx_b_idx >= 0, f"Could not find Context B anchor in ic-sim agent body: {ctx_b_anchor!r}"
    # Section ends at the next top-level "## " heading.
    next_section_idx = agent_body.find("\n## ", ctx_b_idx + 1)
    ctx_b_block = agent_body[ctx_b_idx:next_section_idx] if next_section_idx > 0 else agent_body[ctx_b_idx:]

    hard_rules_idx = ctx_b_block.find("Hard rules")
    assert hard_rules_idx >= 0, "ic-sim Context B section is missing a 'Hard rules' block"
    hard_rules_block = ctx_b_block[hard_rules_idx:]

    for action in forbidden_actions:
        assert isinstance(action, str)
        assert action in hard_rules_block, (
            f"ic-sim agent body Context B 'Hard rules' block does not document forbidden action {action!r}"
        )


def test_ic_sim_context_b_return_payload_keys_match_v0_4_1() -> None:
    """Backward-compat check: the v0.4.2 POST_COMPOSE_COACHING fixture's
    `return_payload_keys` MUST match the ic-sim v0.4.1 Context B
    return shape (pinned in COACHING_PAYLOADS)."""
    contract = _load_ic_sim_post_compose_coaching_contract()
    fixture_keys = contract["return_payload_keys"]
    expected_v041_keys = COACHING_PAYLOADS["ic-sim"]
    assert fixture_keys == expected_v041_keys, (
        "POST_COMPOSE_COACHING return_payload_keys drifted from v0.4.1: "
        f"fixture={fixture_keys!r} v0.4.1={expected_v041_keys!r}"
    )


# --------------------------------------------------------------------------
# v0.4.2 Mitigation 2 — market-sizing Context B (POST_COMPOSE_COACHING)
# --------------------------------------------------------------------------


def _load_market_sizing_post_compose_coaching_contract() -> dict[str, object]:
    data = json.loads(FIXTURE_PATH.read_text())
    contract = data["market-sizing"].get("POST_COMPOSE_COACHING")
    assert contract is not None, (
        "market-sizing fixture is missing the POST_COMPOSE_COACHING entry. v0.4.2 Phase 4 Task 13 added it."
    )
    assert isinstance(contract, dict)
    return contract  # type: ignore[no-any-return]


def test_market_sizing_context_b_contract_documented() -> None:
    """Each `required_action` keyword from the POST_COMPOSE_COACHING fixture
    must appear literally in the market-sizing agent body's Context B section,
    along with the literal `POST_COMPOSE_COACHING` dispatch_type — which is
    what makes the existing parameterized
    `test_dispatch_contract_matches_schema` pass for this fixture row."""
    contract = _load_market_sizing_post_compose_coaching_contract()
    agent_body = (REPO_ROOT / "agents" / "market-sizing.md").read_text()

    assert "POST_COMPOSE_COACHING" in agent_body, (
        "market-sizing agent body does not include the literal POST_COMPOSE_COACHING dispatch_type"
    )

    required_actions = contract["required_actions"]
    assert isinstance(required_actions, list)
    for action in required_actions:
        assert isinstance(action, str)
        assert action in agent_body, f"market-sizing agent body Context B does not document required action {action!r}"

    required_input_keys = contract["required_input_keys"]
    assert isinstance(required_input_keys, list)
    for key in required_input_keys:
        assert isinstance(key, str)
        assert key in agent_body, f"market-sizing agent body Context B does not mention required input key {key!r}"


def test_market_sizing_context_b_forbidden_actions_documented() -> None:
    """Each `forbidden_action` from the fixture must be mentioned in the
    market-sizing agent body's hard-rules section, so authors who try to
    'just Read the report' are warned away by the agent body itself."""
    contract = _load_market_sizing_post_compose_coaching_contract()
    agent_body = (REPO_ROOT / "agents" / "market-sizing.md").read_text()

    forbidden_actions = contract["forbidden_actions"]
    assert isinstance(forbidden_actions, list)

    # Locate the Hard rules block inside Context B. Anchored on the
    # POST_COMPOSE_COACHING heading so we don't accidentally match Context A's
    # own Hard rules.
    ctx_b_anchor = "Context B — Post-compose coaching dispatch (POST_COMPOSE_COACHING)"
    ctx_b_idx = agent_body.find(ctx_b_anchor)
    assert ctx_b_idx >= 0, f"Could not find Context B anchor in market-sizing agent body: {ctx_b_anchor!r}"
    # Section ends at the next top-level "## " heading.
    next_section_idx = agent_body.find("\n## ", ctx_b_idx + 1)
    ctx_b_block = agent_body[ctx_b_idx:next_section_idx] if next_section_idx > 0 else agent_body[ctx_b_idx:]

    hard_rules_idx = ctx_b_block.find("Hard rules")
    assert hard_rules_idx >= 0, "market-sizing Context B section is missing a 'Hard rules' block"
    hard_rules_block = ctx_b_block[hard_rules_idx:]

    for action in forbidden_actions:
        assert isinstance(action, str)
        assert action in hard_rules_block, (
            f"market-sizing agent body Context B 'Hard rules' block does not document forbidden action {action!r}"
        )


def test_market_sizing_context_b_return_payload_keys_match_v0_4_1() -> None:
    """Backward-compat check: the v0.4.2 POST_COMPOSE_COACHING fixture's
    `return_payload_keys` MUST match the market-sizing v0.4.1 Context B
    return shape (pinned in COACHING_PAYLOADS)."""
    contract = _load_market_sizing_post_compose_coaching_contract()
    fixture_keys = contract["return_payload_keys"]
    expected_v041_keys = COACHING_PAYLOADS["market-sizing"]
    assert fixture_keys == expected_v041_keys, (
        "POST_COMPOSE_COACHING return_payload_keys drifted from v0.4.1: "
        f"fixture={fixture_keys!r} v0.4.1={expected_v041_keys!r}"
    )


def test_all_skills_have_disable_flag_removed() -> None:
    """Sanity check that the v0.4.1 inline-skill pivot landed in every
    SKILL.md frontmatter (disable-model-invocation: true must be absent).
    Currently 6 skills (deck-review, market-sizing, ic-sim,
    financial-model-review, competitive-positioning, cap-table)."""
    skills_dir = REPO_ROOT / "skills"
    checked = 0
    for skill_dir in sorted(skills_dir.iterdir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        body = skill_md.read_text()
        # Frontmatter is between the first two `---` lines
        parts = body.split("---")
        assert len(parts) >= 3, f"{skill_md} doesn't look like a valid SKILL.md (no frontmatter delimiters)"
        frontmatter = parts[1]
        assert "disable-model-invocation: true" not in frontmatter, (
            f"{skill_md} still has disable-model-invocation: true in frontmatter "
            f"(must be removed for inline-skill pivot)"
        )
        checked += 1

    assert checked == 6, (
        f"Expected 6 SKILL.md files (deck-review, market-sizing, ic-sim, "
        f"financial-model-review, competitive-positioning, cap-table); found "
        f"{checked}. Add the missing skill or update this assertion."
    )
