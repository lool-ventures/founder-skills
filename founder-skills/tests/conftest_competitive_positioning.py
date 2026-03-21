"""Shared fixture data for competitive positioning tests."""

from __future__ import annotations

from typing import Any

VALID_LANDSCAPE: dict[str, Any] = {
    "competitors": [
        {
            "name": "Salt Security",
            "slug": "salt-security",
            "category": "direct",
            "description": "API security platform using AI/ML",
            "key_differentiators": ["API discovery", "Enterprise focus"],
            "research_depth": "full",
            "evidence_source": {"description": "researched"},
            "sourced_fields_count": 5,
        },
        {
            "name": "Noname Security",
            "slug": "noname-security",
            "category": "direct",
            "description": "API security with runtime protection",
            "key_differentiators": ["Runtime protection", "Posture management"],
            "research_depth": "full",
            "evidence_source": {"description": "researched"},
            "sourced_fields_count": 4,
        },
        {
            "name": "Manual API monitoring",
            "slug": "manual-monitoring",
            "category": "do_nothing",
            "description": "Teams manually review API logs",
            "key_differentiators": ["Zero cost", "Full control"],
            "research_depth": "full",
            "evidence_source": {"description": "agent_estimate"},
            "sourced_fields_count": 0,
        },
        {
            "name": "Wallarm",
            "slug": "wallarm",
            "category": "adjacent",
            "description": "API security and WAAP platform",
            "key_differentiators": ["WAAP convergence", "Open-source roots"],
            "research_depth": "partial",
            "evidence_source": {"description": "researched"},
            "sourced_fields_count": 3,
        },
        {
            "name": "Traceable AI",
            "slug": "traceable-ai",
            "category": "emerging",
            "description": "AI-driven API security analytics",
            "key_differentiators": ["AI analytics", "API catalog"],
            "research_depth": "full",
            "evidence_source": {"description": "researched"},
            "sourced_fields_count": 5,
        },
    ],
    "input_mode": "conversation",
    "warnings": [],
    "metadata": {"run_id": "20260319T143045Z"},
}

VALID_POSITIONING: dict[str, Any] = {
    "views": [
        {
            "id": "primary",
            "x_axis": {
                "name": "Deployment Complexity",
                "description": "How much infrastructure change required",
                "rationale": "SDK vs proxy is the key differentiator",
            },
            "y_axis": {
                "name": "Detection Accuracy",
                "description": "Ability to detect real API threats",
                "rationale": "Accuracy is table-stakes",
            },
            "points": [
                {
                    "competitor": "_startup",
                    "x": 90,
                    "y": 75,
                    "x_evidence": "SDK-based",
                    "y_evidence": "2B+ calls trained",
                    "x_evidence_source": "founder_override",
                    "y_evidence_source": "researched",
                },
                {
                    "competitor": "salt-security",
                    "x": 30,
                    "y": 85,
                    "x_evidence": "Reverse proxy",
                    "y_evidence": "Industry-leading",
                    "x_evidence_source": "researched",
                    "y_evidence_source": "researched",
                },
                {
                    "competitor": "noname-security",
                    "x": 40,
                    "y": 70,
                    "x_evidence": "Agent-based",
                    "y_evidence": "Good detection",
                    "x_evidence_source": "researched",
                    "y_evidence_source": "researched",
                },
                {
                    "competitor": "manual-monitoring",
                    "x": 95,
                    "y": 15,
                    "x_evidence": "No deployment",
                    "y_evidence": "Manual review",
                    "x_evidence_source": "agent_estimate",
                    "y_evidence_source": "agent_estimate",
                },
                {
                    "competitor": "wallarm",
                    "x": 50,
                    "y": 65,
                    "x_evidence": "Moderate",
                    "y_evidence": "Decent",
                    "x_evidence_source": "researched",
                    "y_evidence_source": "researched",
                },
                {
                    "competitor": "traceable-ai",
                    "x": 45,
                    "y": 60,
                    "x_evidence": "Moderate",
                    "y_evidence": "Growing",
                    "x_evidence_source": "researched",
                    "y_evidence_source": "researched",
                },
            ],
        },
        {
            "id": "secondary",
            "x_axis": {
                "name": "Latency Impact",
                "description": "Performance overhead of the solution",
                "rationale": "Sub-5ms claim needs testing",
            },
            "y_axis": {
                "name": "Protocol Coverage",
                "description": "Breadth of API protocols supported",
                "rationale": "GraphQL support is rare",
            },
            "points": [
                {
                    "competitor": "_startup",
                    "x": 95,
                    "y": 90,
                    "x_evidence": "Sub-5ms",
                    "y_evidence": "REST + GraphQL",
                    "x_evidence_source": "founder_override",
                    "y_evidence_source": "researched",
                },
                {
                    "competitor": "salt-security",
                    "x": 30,
                    "y": 60,
                    "x_evidence": "100-200ms",
                    "y_evidence": "REST only",
                    "x_evidence_source": "researched",
                    "y_evidence_source": "researched",
                },
                {
                    "competitor": "noname-security",
                    "x": 50,
                    "y": 55,
                    "x_evidence": "50-100ms",
                    "y_evidence": "REST + gRPC",
                    "x_evidence_source": "researched",
                    "y_evidence_source": "researched",
                },
            ],
        },
    ],
    "moat_assessments": {
        "_startup": {
            "moats": [
                {
                    "id": "network_effects",
                    "status": "not_applicable",
                    "evidence": "Single-tenant product",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "data_advantages",
                    "status": "moderate",
                    "evidence": "ML model on 2B+ calls, growing",
                    "evidence_source": "researched",
                    "trajectory": "building",
                },
                {
                    "id": "switching_costs",
                    "status": "moderate",
                    "evidence": "SDK integration creates stickiness",
                    "evidence_source": "researched",
                    "trajectory": "building",
                },
                {
                    "id": "regulatory_barriers",
                    "status": "absent",
                    "evidence": "No regulatory moat",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "cost_structure",
                    "status": "weak",
                    "evidence": "Cloud costs similar to competitors",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "brand_reputation",
                    "status": "weak",
                    "evidence": "New entrant, limited brand",
                    "evidence_source": "agent_estimate",
                    "trajectory": "building",
                },
            ]
        },
        "salt-security": {
            "moats": [
                {
                    "id": "network_effects",
                    "status": "not_applicable",
                    "evidence": "Enterprise product",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "data_advantages",
                    "status": "strong",
                    "evidence": "10B+ calls monthly, largest dataset",
                    "evidence_source": "researched",
                    "trajectory": "stable",
                },
                {
                    "id": "switching_costs",
                    "status": "strong",
                    "evidence": "Deep enterprise integration",
                    "evidence_source": "researched",
                    "trajectory": "stable",
                },
                {
                    "id": "regulatory_barriers",
                    "status": "absent",
                    "evidence": "No regulatory moat",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "cost_structure",
                    "status": "moderate",
                    "evidence": "Scale economies from large customer base",
                    "evidence_source": "researched",
                    "trajectory": "stable",
                },
                {
                    "id": "brand_reputation",
                    "status": "strong",
                    "evidence": "Market leader, Gartner recognized",
                    "evidence_source": "researched",
                    "trajectory": "stable",
                },
            ]
        },
        "noname-security": {
            "moats": [
                {
                    "id": "network_effects",
                    "status": "not_applicable",
                    "evidence": "No network effects",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "data_advantages",
                    "status": "moderate",
                    "evidence": "Growing dataset",
                    "evidence_source": "researched",
                    "trajectory": "building",
                },
                {
                    "id": "switching_costs",
                    "status": "moderate",
                    "evidence": "Agent deployment sticky",
                    "evidence_source": "researched",
                    "trajectory": "stable",
                },
                {
                    "id": "regulatory_barriers",
                    "status": "absent",
                    "evidence": "None",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "cost_structure",
                    "status": "weak",
                    "evidence": "Standard cloud costs",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "brand_reputation",
                    "status": "moderate",
                    "evidence": "Growing recognition",
                    "evidence_source": "researched",
                    "trajectory": "building",
                },
            ]
        },
        "manual-monitoring": {
            "moats": [
                {
                    "id": "network_effects",
                    "status": "not_applicable",
                    "evidence": "Not a product",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "data_advantages",
                    "status": "absent",
                    "evidence": "No data advantage",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "switching_costs",
                    "status": "absent",
                    "evidence": "Zero switching cost",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "regulatory_barriers",
                    "status": "absent",
                    "evidence": "None",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "cost_structure",
                    "status": "strong",
                    "evidence": "Zero cost, uses existing infra",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "brand_reputation",
                    "status": "absent",
                    "evidence": "Not a product",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
            ]
        },
        "wallarm": {
            "moats": [
                {
                    "id": "network_effects",
                    "status": "not_applicable",
                    "evidence": "No network effects",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "data_advantages",
                    "status": "weak",
                    "evidence": "Limited data moat",
                    "evidence_source": "researched",
                    "trajectory": "stable",
                },
                {
                    "id": "switching_costs",
                    "status": "moderate",
                    "evidence": "WAAP integration sticky",
                    "evidence_source": "researched",
                    "trajectory": "stable",
                },
                {
                    "id": "regulatory_barriers",
                    "status": "absent",
                    "evidence": "None",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "cost_structure",
                    "status": "weak",
                    "evidence": "Standard",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "brand_reputation",
                    "status": "weak",
                    "evidence": "Niche recognition",
                    "evidence_source": "researched",
                    "trajectory": "stable",
                },
            ]
        },
        "traceable-ai": {
            "moats": [
                {
                    "id": "network_effects",
                    "status": "not_applicable",
                    "evidence": "No network effects",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "data_advantages",
                    "status": "moderate",
                    "evidence": "AI-driven analytics",
                    "evidence_source": "researched",
                    "trajectory": "building",
                },
                {
                    "id": "switching_costs",
                    "status": "weak",
                    "evidence": "Early stage",
                    "evidence_source": "agent_estimate",
                    "trajectory": "building",
                },
                {
                    "id": "regulatory_barriers",
                    "status": "absent",
                    "evidence": "None",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "cost_structure",
                    "status": "weak",
                    "evidence": "Standard",
                    "evidence_source": "agent_estimate",
                    "trajectory": "stable",
                },
                {
                    "id": "brand_reputation",
                    "status": "weak",
                    "evidence": "Emerging",
                    "evidence_source": "researched",
                    "trajectory": "building",
                },
            ]
        },
    },
    "differentiation_claims": [
        {
            "claim": "ML model trained on 2B+ API calls",
            "verifiable": True,
            "evidence": "Founder confirmed; Salt has 10B+",
            "challenge": "How does accuracy compare at this scale?",
            "verdict": "partially_holds",
        },
        {
            "claim": "Sub-5ms latency",
            "verifiable": True,
            "evidence": "Architecturally plausible, no benchmark",
            "challenge": "Share production latency benchmarks",
            "verdict": "holds",
        },
    ],
    "accepted_warnings": [],
    "metadata": {"run_id": "20260319T143045Z"},
}

VALID_POSITIONING_SCORES: dict[str, Any] = {
    "views": [
        {
            "view_id": "primary",
            "x_axis_name": "Deployment Complexity",
            "y_axis_name": "Detection Accuracy",
            "x_axis_rationale": "SDK vs proxy is the key differentiator",
            "y_axis_rationale": "Accuracy is table-stakes",
            "x_axis_vanity_flag": False,
            "y_axis_vanity_flag": False,
            "differentiation_score": 75.0,
            "startup_x_rank": 1,
            "startup_y_rank": 3,
            "competitor_count": 5,
        },
        {
            "view_id": "secondary",
            "x_axis_name": "Latency Impact",
            "y_axis_name": "Protocol Coverage",
            "x_axis_rationale": "Sub-5ms claim needs testing",
            "y_axis_rationale": "GraphQL support is rare",
            "x_axis_vanity_flag": True,
            "y_axis_vanity_flag": False,
            "differentiation_score": 90.0,
            "startup_x_rank": 1,
            "startup_y_rank": 1,
            "competitor_count": 2,
        },
    ],
    "overall_differentiation": 82.5,
    "differentiation_claims": VALID_POSITIONING["differentiation_claims"],
    "warnings": [],
    "metadata": {"run_id": "20260319T143045Z"},
}

VALID_MOAT_SCORES: dict[str, Any] = {
    "companies": {
        "_startup": {
            "moats": VALID_POSITIONING["moat_assessments"]["_startup"]["moats"],
            "moat_count": 2,
            "strongest_moat": "data_advantages",
            "overall_defensibility": "moderate",
        },
        "salt-security": {
            "moats": VALID_POSITIONING["moat_assessments"]["salt-security"]["moats"],
            "moat_count": 3,
            "strongest_moat": "data_advantages",
            "overall_defensibility": "high",
        },
        "noname-security": {
            "moats": VALID_POSITIONING["moat_assessments"]["noname-security"]["moats"],
            "moat_count": 2,
            "strongest_moat": "data_advantages",
            "overall_defensibility": "moderate",
        },
        "manual-monitoring": {
            "moats": VALID_POSITIONING["moat_assessments"]["manual-monitoring"]["moats"],
            "moat_count": 1,
            "strongest_moat": "cost_structure",
            "overall_defensibility": "moderate",
        },
        "wallarm": {
            "moats": VALID_POSITIONING["moat_assessments"]["wallarm"]["moats"],
            "moat_count": 1,
            "strongest_moat": "switching_costs",
            "overall_defensibility": "low",
        },
        "traceable-ai": {
            "moats": VALID_POSITIONING["moat_assessments"]["traceable-ai"]["moats"],
            "moat_count": 1,
            "strongest_moat": "data_advantages",
            "overall_defensibility": "low",
        },
    },
    "comparison": {
        "by_dimension": {
            "data_advantages": {
                "_startup": "moderate",
                "salt-security": "strong",
                "noname-security": "moderate",
                "manual-monitoring": "absent",
                "wallarm": "weak",
                "traceable-ai": "moderate",
            },
            "switching_costs": {
                "_startup": "moderate",
                "salt-security": "strong",
                "noname-security": "moderate",
                "manual-monitoring": "absent",
                "wallarm": "moderate",
                "traceable-ai": "weak",
            },
        },
        "startup_rank": {
            "data_advantages": {"rank": 2, "total": 5},
            "switching_costs": {"rank": 2, "total": 5},
        },
    },
    "warnings": [],
    "metadata": {"run_id": "20260319T143045Z"},
}

VALID_REPORT: dict[str, Any] = {
    "report_markdown": (
        "# Competitive Positioning Analysis: SecureFlow\n\n"
        "## Executive Summary\nSecureFlow differentiates on deployment simplicity."
    ),
    "metadata": {
        "run_id": "20260319T143045Z",
        "company_name": "SecureFlow",
        "analysis_date": "2026-03-19",
        "input_mode": "conversation",
        "competitor_count": 5,
        "research_depth": "full",
        "assessment_mode": "sub-agent",
        "founder_override_count": 2,
    },
    "warnings": [],
    "artifacts_loaded": [
        "product_profile.json",
        "landscape.json",
        "positioning.json",
        "moat_scores.json",
        "positioning_scores.json",
        "checklist.json",
    ],
    "scoring_summary": {
        "checklist_score_pct": 82.6,
        "overall_differentiation": 82.5,
        "startup_defensibility": "moderate",
    },
}
