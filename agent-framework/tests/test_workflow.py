"""Offline tests: the two Foundry agents are replaced by scripted fakes."""

import json
import sys
from pathlib import Path

import pytest
from agent_framework import (
    AgentResponse,
    BaseAgent,
    Message,
    ResponseStream,
    WorkflowRunState,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import workflow  # noqa: E402

POLICY = {
    "policy_type": "Comprehensive Auto",
    "coverage_types": ["collision"],
    "limits": {"collision": 50000},
    "deductibles": {"collision": 500},
    "exclusions": ["racing"],
}


class FakeAgent(BaseAgent):
    """Replies by task keyword and records every prompt it receives."""

    def __init__(self, name: str, replies: dict[str, str], prompts: list[tuple[str, str]]) -> None:
        super().__init__(name=name)
        self.replies, self.prompts = replies, prompts

    def run(self, messages=None, *, stream=False, session=None, **kwargs):
        text = messages[-1].text if isinstance(messages, list) else str(messages)
        self.prompts.append((self.name, text))
        reply = next(v for k, v in self.replies.items() if text.startswith(k))

        async def respond():
            return AgentResponse(messages=[Message("assistant", [reply])])

        if stream:
            async def updates():
                for update in ():
                    yield update

            return ResponseStream(updates(), finalizer=lambda _: AgentResponse(messages=[Message("assistant", [reply])]))
        return respond()


def decision(confidence: float, escalate: bool = False, covered: bool = True) -> str:
    return json.dumps(
        {"is_covered": covered, "approved_amount": 14500.0, "confidence_score": confidence,
         "requires_escalation": escalate, "escalation_reason": "needs adjuster" if escalate else None}
    )


@pytest.fixture
def build(monkeypatch):
    def _build(confidence: float, escalate: bool = False, covered: bool = True, policy: dict = POLICY):
        prompts: list[tuple[str, str]] = []

        def fake_connect(agent_name, step_id, credential):
            replies = (
                {"INDEXED_STATEMENT_TASK": "Statement for crash3, policy number COMP-AUTO-001."}
                if agent_name == workflow.INTAKE_AGENT
                else {"POLICY_EXTRACTION_TASK": json.dumps(policy),
                      "COVERAGE_DECISION_TASK": decision(confidence, escalate, covered)}
            )
            return FakeAgent(step_id, replies, prompts)

        monkeypatch.setattr(workflow, "connect", fake_connect)
        monkeypatch.setattr(workflow, "REVIEW_THRESHOLD", 0.9)
        return workflow.build_workflow(credential=object()), prompts

    return _build


def final(result) -> dict:
    return json.loads(result.get_outputs()[-1][0].text)


# --- the same inputs as claims-sequential-workflow.py -------------------------------------------

@pytest.mark.parametrize(
    "text, file, claim_id, amount, policy",
    [
        ("--indexed-claim crash3", "crash3_front.jpeg", "CLM-2026-001", 15000.0, None),
        ("--indexed-claim crash3_front.jpeg --policy comp-auto-001", "crash3_front.jpeg", "CLM-2026-001", 15000.0, "COMP-AUTO-001"),
        ("../data/claims/crash1/raw/statements/crash1_front.jpeg --policy COMM-AUTO-001 --claim-id CLM-2026-007 --amount 28000",
         "crash1_front.jpeg", "CLM-2026-007", 28000.0, "COMM-AUTO-001"),
        ("crash2", "crash2_front.jpeg", "CLM-2026-001", 15000.0, None),
        ("'/my files/crash4_front.jpeg'", "crash4_front.jpeg", "CLM-2026-001", 15000.0, None),
    ],
)
def test_parse_request_matches_the_sequential_workflow_inputs(text, file, claim_id, amount, policy):
    claim = workflow.parse_request(text)
    assert (claim.statement_file, claim.claim_id, claim.amount, claim.policy_number) == (file, claim_id, amount, policy)


@pytest.mark.parametrize("text", ["", "--policy COMP-AUTO-001", "crash3 --indexed-claim crash4", "--indexed-claim crash3 --amount lots"])
def test_parse_request_rejects_bad_input_with_an_example(text):
    with pytest.raises(ValueError, match="crash3"):
        workflow.parse_request(text)


# --- workflow behaviour -------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agents_run_in_order_and_policy_comes_from_intake(build):
    wf, prompts = build(0.97)
    await wf.run("--indexed-claim crash3 --amount 15000")

    assert [name for name, _ in prompts] == ["intake_agent", "policy_agent", "decision_agent"]
    assert '"crash3_front.jpeg"' in prompts[0][1]
    assert "COMP-AUTO-001" in prompts[1][1]
    assert "Claim Amount: $15,000.00" in prompts[2][1]
    assert "Coverage Types: collision" in prompts[2][1]


@pytest.mark.asyncio
async def test_policy_override_is_used_instead_of_the_intake_policy(build):
    wf, prompts = build(0.97)
    await wf.run("--indexed-claim crash3 --policy liab-auto-001")

    assert "LIAB-AUTO-001" in prompts[1][1]


@pytest.mark.asyncio
async def test_result_has_the_sequential_workflow_fields(build):
    wf, _ = build(0.97)
    result = final(await wf.run("--indexed-claim crash3 --claim-id CLM-9"))

    assert result["claim_id"] == "CLM-9"
    assert result["status"] == "APPROVED"
    assert result["policy_info"]["policy_number"] == "COMP-AUTO-001"
    assert result["policy_info"]["deductibles"] == {"collision": 500}
    assert result["coverage_decision"]["approved_amount"] == 14500.0
    assert result["errors"] == []
    assert "human_review" not in result


@pytest.mark.asyncio
async def test_not_covered_decision_is_denied(build):
    wf, _ = build(0.97, covered=False)
    assert final(await wf.run("--indexed-claim crash3"))["status"] == "DENIED"


@pytest.mark.asyncio
@pytest.mark.parametrize("confidence, escalate", [(0.5, False), (0.99, True)])
async def test_low_confidence_or_escalation_pauses_in_pending_review(build, confidence, escalate):
    wf, _ = build(confidence, escalate)
    paused = await wf.run("--indexed-claim crash3")

    assert paused.get_final_state() == WorkflowRunState.IDLE_WITH_PENDING_REQUESTS
    (request,) = paused.get_request_info_events()
    assert request.data["result"]["status"] == "PENDING_HUMAN_REVIEW"
    assert request.data["decision_status"] == ("ESCALATED" if escalate else "APPROVED")
    assert request.data["threshold"] == 0.9
    assert "approve" in request.data["prompt"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply, status, review_status",
    [("approve", "APPROVED", "confirmed"), ("escalate", "ESCALATED", "escalated"), ('"deny not covered"', "DENIED", "overridden")],
)
async def test_reviewer_action_sets_the_final_status(build, reply, status, review_status):
    wf, _ = build(0.5)
    (request,) = (await wf.run("--indexed-claim crash3")).get_request_info_events()
    result = final(await wf.run(responses={request.request_id: reply}))

    assert result["status"] == status
    assert result["human_review"]["status"] == review_status
    assert result["human_review"]["agent_status"] == "APPROVED"


@pytest.mark.asyncio
async def test_invalid_review_answer_asks_again(build):
    wf, _ = build(0.5)
    (request,) = (await wf.run("--indexed-claim crash3")).get_request_info_events()
    again = await wf.run(responses={request.request_id: "maybe"})

    assert again.get_final_state() == WorkflowRunState.IDLE_WITH_PENDING_REQUESTS
    (second,) = again.get_request_info_events()
    assert "Invalid response" in second.data["prompt"]

    assert final(await wf.run(responses={second.request_id: "approve"}))["status"] == "APPROVED"


@pytest.mark.asyncio
async def test_unknown_policy_stops_the_workflow(build):
    wf, _ = build(0.97, policy={"policy_type": "NOT_FOUND"})
    with pytest.raises(LookupError, match="COMP-AUTO-001 not found"):
        await wf.run("--indexed-claim crash3")


@pytest.mark.asyncio
async def test_bad_request_fails_before_calling_any_agent(build):
    wf, prompts = build(0.97)
    with pytest.raises(ValueError, match="Example"):
        await wf.run("hello --amount")

    assert prompts == []


@pytest.mark.parametrize("review, fail", [(False, False), (True, False), (False, True)])
def test_cli_exports_one_trace_with_workflow_children_and_review(build, monkeypatch, review, fail):
    import importlib.util
    from types import SimpleNamespace

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: provider)
    graph, _ = build(
        0.5 if review else 0.97,
        policy={"policy_type": "NOT_FOUND"} if fail else POLICY,
    )
    exporter.clear()
    monkeypatch.setattr(workflow, "build_workflow", lambda credential: graph)
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda prompt: "approve")
    path = Path(__file__).resolve().parents[2] / "docs" / "claims-framework-workflow.py"
    spec = importlib.util.spec_from_file_location("traced_cli", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    if fail:
        with pytest.raises(LookupError, match="not found"):
            cli.run_claims_pipeline(None, "CLM-TEST", 15000, "COMP-AUTO-001", "crash3")
    else:
        result = cli.run_claims_pipeline(None, "CLM-TEST", 15000, "COMP-AUTO-001", "crash3")
    spans = exporter.get_finished_spans()
    root = next(span for span in spans if span.name == "claims.process")
    assert root.parent is None
    if fail:
        assert root.status.status_code is trace.StatusCode.ERROR
        assert any(event.name == "exception" for event in root.events)
    else:
        assert root.attributes["claims.status"] == result["status"] == "APPROVED"
        assert root.attributes["claims.human_review.required"] is review
    assert len(spans) > 5
    assert {span.context.trace_id for span in spans} == {root.context.trace_id}
    assert any(span.parent and span.parent.span_id == root.context.span_id for span in spans)
    provider.shutdown()
