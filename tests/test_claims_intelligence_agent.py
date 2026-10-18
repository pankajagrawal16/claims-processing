import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"
sys.path.insert(0, str(DOCS_DIR))
MODULE_SPEC = importlib.util.spec_from_file_location(
    "claims_intelligence_agent", DOCS_DIR / "claims-intelligence-agent.py"
)
claims_intelligence_agent = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(claims_intelligence_agent)

from enterprise_models import (
    ClaimProcessingState,
    ClaimStatus,
    PolicyInfo,
    StructuredClaim,
)


@pytest.mark.parametrize(
    ("requires_escalation", "expected_status", "expected_error_count"),
    [
        (False, ClaimStatus.DENIED, 0),
        (True, ClaimStatus.ESCALATED, 1),
    ],
)
def test_validate_coverage_preserves_escalation_in_result(
    monkeypatch, requires_escalation, expected_status, expected_error_count
):
    decision = {
        "is_covered": False,
        "requires_escalation": requires_escalation,
        "escalation_reason": "Manual review requested" if requires_escalation else None,
    }
    responses = SimpleNamespace(
        create=lambda **_: SimpleNamespace(output_text=json.dumps(decision))
    )
    agent = claims_intelligence_agent.ClaimsIntelligenceAgent.__new__(
        claims_intelligence_agent.ClaimsIntelligenceAgent
    )
    agent.model = "test-model"
    agent.client = SimpleNamespace(
        get_openai_client=lambda **_: SimpleNamespace(responses=responses)
    )
    monkeypatch.setattr(agent, "_ensure_claims_intelligence_agent", lambda: None)

    state = ClaimProcessingState(
        claim_id="test-claim",
        structured_claim=StructuredClaim(
            policy_number="LIAB-AUTO-001",
            claim_amount=95000,
            damage_description="Collision damage",
            incident_date="2026-01-01",
            claim_type="collision",
            vehicle_info="2024 Test Sedan",
            extraction_confidence=0.9,
        ),
        policy_info=PolicyInfo(
            policy_id="liab_auto_001",
            policy_number="LIAB-AUTO-001",
            policy_type="Liability Only",
            effective_date="2026-01-01",
            expiry_date="2027-01-01",
        ),
    )

    result = agent.validate_coverage(state)

    assert result.status == expected_status
    assert result.coverage_decision.requires_escalation is requires_escalation
    assert result.coverage_decision.escalation_reason == decision["escalation_reason"]
    assert len(result.errors) == expected_error_count
    result_dict = result.to_result_dict()
    assert (
        result_dict["coverage_decision"]["requires_escalation"]
        is requires_escalation
    )
    assert result_dict["coverage_decision"]["escalation_reason"] == decision[
        "escalation_reason"
    ]
