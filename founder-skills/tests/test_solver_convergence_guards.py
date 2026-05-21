"""Sprint 1 convergence-guard tests for priced_round.solve_priced_round.

Per docs/internal/2026-05-21-priced-round-coupled-solver-design.md v3 §7.1,
the convergence guards (sign-flip damping, Aitken Δ² acceleration with
fallback fence, divergence detection) need explicit correctness coverage.
Sprint 1's 15 math goldens implicitly exercise convergence (all converge in
6-12 iters) but don't verify each guard's mechanics in isolation.

Sprint 1 reviewer caught a real Aitken numerator bug (v1 used `(p_n - p_{n-2})²`
instead of the correct `(p_{n-1} - p_{n-2})²`) that the 15 goldens had not
caught — the 20× fallback fence had been silently masking the divergence on
realistic inputs. This suite locks the correct formula.
"""

from __future__ import annotations

import importlib.util
import pathlib

SOLVER_PATH = pathlib.Path(__file__).parent.parent / "skills" / "cap-table" / "scripts" / "priced_round.py"
spec = importlib.util.spec_from_file_location("priced_round", SOLVER_PATH)
assert spec and spec.loader
priced_round = importlib.util.module_from_spec(spec)
spec.loader.exec_module(priced_round)


class TestAitkenProjection:
    """Verify Aitken Δ² produces the correct projected fixed point.

    For a linearly-convergent sequence p_n = L + A × r^n (r ∈ (-1, 1)),
    Aitken's Δ² gives p* = L exactly (within float precision).
    """

    def test_geometric_sequence_converging_from_above(self):
        """p_n = 0.357 + 0.5^n → p* = 0.357 exactly."""
        L = 0.357
        r = 0.5
        seq = [L + r**n for n in range(3)]  # [1.357, 0.857, 0.607]
        projection = priced_round._aitken_projection(seq)
        assert projection is not None
        assert abs(projection - L) < 1e-12

    def test_geometric_sequence_converging_from_below(self):
        """p_n = 1.0 - 0.7^n → p* = 1.0 exactly."""
        L = 1.0
        r = 0.7
        seq = [L - r**n for n in range(3)]  # [0.0, 0.3, 0.51]
        projection = priced_round._aitken_projection(seq)
        assert projection is not None
        assert abs(projection - L) < 1e-12

    def test_alternating_sequence(self):
        """p_n = 0.5 + (-0.4)^n → p* = 0.5 exactly."""
        L = 0.5
        r = -0.4
        seq = [L + r**n for n in range(3)]  # [1.5, 0.1, 0.66]
        projection = priced_round._aitken_projection(seq)
        assert projection is not None
        assert abs(projection - L) < 1e-12

    def test_returns_none_when_history_too_short(self):
        assert priced_round._aitken_projection([0.5]) is None
        assert priced_round._aitken_projection([0.5, 0.4]) is None

    def test_returns_none_on_near_2_cycle(self):
        """When the sequence is converging on a 2-cycle, Δ² → 0 → catastrophic cancellation."""
        # p_0, p_1, p_0 (back to p_0): Δ² = p_0 - 2 p_1 + p_0 = 2(p_0 - p_1) ≠ 0
        # Construct a tighter case where Δ² IS near zero:
        # Need p_n - 2 p_{n-1} + p_{n-2} ≈ 0
        # I.e., p_n + p_{n-2} ≈ 2 p_{n-1}, i.e., p_{n-1} is the midpoint
        seq = [0.5, 0.5 + 1e-16, 0.5 + 2e-16]  # nearly linear, Δ² ≈ 0
        projection = priced_round._aitken_projection(seq)
        assert projection is None


class TestSignFlipDetector:
    """Sign-flip detection triggers under-relaxation."""

    def test_no_flip_on_monotone_sequence(self):
        # Monotone decreasing → no sign flips
        history = [1.0, 0.9, 0.8, 0.7, 0.6]
        assert priced_round._detect_sign_flip(history, window=3) is False

    def test_detects_alternating_signs(self):
        # +, -, +, - (3 alternations in 4 deltas)
        history = [0.5, 0.6, 0.55, 0.62, 0.56]
        assert priced_round._detect_sign_flip(history, window=3) is True

    def test_history_too_short(self):
        assert priced_round._detect_sign_flip([0.5, 0.4], window=3) is False

    def test_zero_delta_breaks_detection(self):
        # A zero delta should not count as a sign flip
        history = [0.5, 0.5, 0.6, 0.55]
        assert priced_round._detect_sign_flip(history, window=3) is False


class TestContractionEstimate:
    """Empirical |f'_est| ≈ |Δp_n / Δp_{n-1}|."""

    def test_returns_ratio_of_deltas(self):
        # p_0=1.0, p_1=0.5, p_2=0.3 → Δ_0=−0.5, Δ_1=−0.2 → |f'_est|=0.4
        history = [1.0, 0.5, 0.3]
        f_est = priced_round._estimate_contraction(history)
        assert f_est is not None
        assert abs(f_est - 0.4) < 1e-12

    def test_returns_none_when_prior_step_zero(self):
        # If prior step is zero, ratio is undefined
        history = [0.5, 0.5, 0.6]
        assert priced_round._estimate_contraction(history) is None

    def test_returns_none_on_too_short_history(self):
        assert priced_round._estimate_contraction([0.5]) is None


class TestSolverIntegration:
    """End-to-end: solver should converge well-bounded on realistic goldens."""

    def _build_test_a_cap_state(self):
        return {
            "founders": [{"name": "Founder A", "common_shares": 10_000_000}],
            "preferred_series": [
                {
                    "series_id": "series_seed",
                    "shares": 2_000_000,
                    "original_issue_price": 1.00,
                    "original_conversion_price": 1.00,
                    "current_conversion_price": 1.00,
                    "anti_dilution_protection": "broad_based_weighted_average",
                }
            ],
            "as_converted_totals": {
                "common_shares": 10_000_000,
                "preferred_shares_as_converted": 2_000_000,
                "options_outstanding": 0,
                "options_available": 1_000_000,
                "fully_diluted_shares": 13_000_000,
            },
            "option_pool": {
                "plan_type": "iso",
                "authorized": 1_000_000,
                "issued_and_outstanding": 0,
                "available_for_grant": 1_000_000,
            },
        }

    def test_test_a_converges_within_expected_iterations(self):
        """Test A's contraction is |f'(p*)| ≈ 0.111; should converge in ≤ 15 iters."""
        result = priced_round.solve_priced_round(
            cap_state=self._build_test_a_cap_state(),
            safes=[],
            notes=[],
            pre_money=5_000_000.0,
            new_money=5_000_000.0,
        )
        assert result["converged"] is True
        assert result["iterations"] <= 15

    def test_aitken_not_engaged_in_typical_regime(self):
        """When |f'| < 0.9 (typical), Aitken should NOT engage."""
        result = priced_round.solve_priced_round(
            cap_state=self._build_test_a_cap_state(),
            safes=[],
            notes=[],
            pre_money=5_000_000.0,
            new_money=5_000_000.0,
        )
        # No convergence_diagnostics dict means neither guard engaged
        diag = result.get("convergence_diagnostics", {})
        assert diag.get("aitken_engaged", False) is False
        assert diag.get("damping_engaged", False) is False

    def test_caller_cap_state_not_mutated(self):
        """Verify the deep-copy boundary holds: caller's cap_state untouched."""
        cap_state = self._build_test_a_cap_state()
        # Snapshot the relevant fields
        original_ccp = cap_state["preferred_series"][0]["current_conversion_price"]
        original_preferred_as_converted = cap_state["as_converted_totals"]["preferred_shares_as_converted"]
        original_fd = cap_state["as_converted_totals"]["fully_diluted_shares"]

        priced_round.solve_priced_round(
            cap_state=cap_state,
            safes=[],
            notes=[],
            pre_money=5_000_000.0,
            new_money=5_000_000.0,
        )

        # Caller's cap_state should be unchanged after solver run
        assert cap_state["preferred_series"][0]["current_conversion_price"] == original_ccp
        assert cap_state["as_converted_totals"]["preferred_shares_as_converted"] == original_preferred_as_converted
        assert cap_state["as_converted_totals"]["fully_diluted_shares"] == original_fd

    def test_convergence_history_populated(self):
        """convergence_history should record each iteration's PPS."""
        result = priced_round.solve_priced_round(
            cap_state=self._build_test_a_cap_state(),
            safes=[],
            notes=[],
            pre_money=5_000_000.0,
            new_money=5_000_000.0,
        )
        hist = result["convergence_history"]
        # Initial + one entry per iteration
        assert len(hist) == result["iterations"] + 1
        # First entry is the initial PPS = pre_money / pre_fd = 5M/13M
        assert abs(hist[0] - 5_000_000.0 / 13_000_000.0) < 1e-9
        # Last entry equals the converged PPS
        assert abs(hist[-1] - result["equity_financing_price"]) < 1e-9
