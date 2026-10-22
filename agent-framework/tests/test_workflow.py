"""Offline tests: the two Foundry agents are replaced by scripted fakes."""

import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from agent_framework import (
    AgentResponse,
    Message,
    RawAgent,
    ResponseStream,
    WorkflowRunState,
)
from agent_framework.foundry import FoundryAgent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import main as hosting  # noqa: E402
import workflow  # noqa: E402

POLICY = {
    "policy_type": "Comprehensive Auto",
    "coverage_types": ["collision"],
    "limits": {"collision": 50000},
    "deductibles": {"collision": 500},
    "exclusions": ["racing"],
}


class FakeAgent(RawAgent):
    """Replies by task keyword and records every prompt it receives."""

    def __init__(self, name: str, replies: dict[str, str], prompts: list[tuple[str, str]]) -> None:
        super().__init__(client=SimpleNamespace(STORES_BY_DEFAULT=True), name=name, default_options={"store": False})
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


@pytest.mark.asyncio
async def test_foundry_agent_waits_for_background_completion(monkeypatch):
    calls = []
    pending = AgentResponse(continuation_token={"response_id": "pending-response"})
    completed = AgentResponse(messages=[Message("assistant", ["Complete decision"])])

    def scripted_run(self, messages=None, *, stream=False, session=None, options=None, **kwargs):
        calls.append((messages, stream, session, options))

        async def respond():
            return pending if len(calls) == 1 else completed

        return respond()

    async def no_delay(_seconds):
        pass

    monkeypatch.setattr(FoundryAgent, "run", scripted_run)
    monkeypatch.setattr(workflow.asyncio, "sleep", no_delay)
    agent = object.__new__(workflow.CompletingFoundryAgent)
    session = object()
    stream = agent.run([Message("user", ["Claim"])], stream=True, session=session)
    updates = [update async for update in stream]

    assert [update.text for update in updates] == ["Complete decision"]
    assert (await stream.get_final_response()).text == "Complete decision"
    assert len(calls) == 2
    assert calls[1][0] is None and calls[1][2] is session
    assert calls[1][3]["continuation_token"] == pending.continuation_token


@pytest.mark.asyncio
async def test_foundry_agent_rejects_empty_completed_response(monkeypatch):
    def empty_run(self, messages=None, *, stream=False, **kwargs):
        async def respond():
            return AgentResponse()

        return respond()

    monkeypatch.setattr(FoundryAgent, "run", empty_run)
    agent = object.__new__(workflow.CompletingFoundryAgent)
    agent.name = "intake_agent"
    with pytest.raises(RuntimeError, match="completed without a response"):
        await agent.run([Message("user", ["Claim"])])


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
async def test_hosted_review_and_new_claim_have_separate_state(build, monkeypatch):
    build(0.5)
    monkeypatch.setattr(hosting, "build_workflow", lambda credential: workflow.build_workflow(credential=credential))
    host = hosting.ResponsesHostServer(
        workflow=hosting.create_workflow,
        parse_response=hosting.parse_response,
        checkpoint_store_provider=hosting.CheckpointStoreProvider(),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=host), base_url="http://testserver") as client:
        first = (await client.post("/responses", json={"input": "--indexed-claim crash3"})).json()
        assert first["status"] == "completed", first.get("error")
        call = next(item for item in first["output"] if item["type"] == "function_call")
        assert json.loads(call["arguments"])["request"]["result"]["status"] == "PENDING_HUMAN_REVIEW"

        second = (await client.post("/responses", json={"input": "--indexed-claim crash4"})).json()
        assert second["status"] == "completed", second.get("error")
        assert any(item["type"] == "function_call" for item in second["output"])

        continued = (await client.post("/responses", json={
            "previous_response_id": first["id"],
            "agent_session_id": first["agent_session_id"],
            "input": [{"type": "function_call_output", "call_id": call["call_id"], "output": "approve"}],
        })).json()
        assert continued["status"] == "completed", continued.get("error")
        text = "".join(part["text"] for item in continued["output"] if item["type"] == "message"
                       for part in item["content"] if part["type"] == "output_text")
        assert json.loads(text)["human_review"]["status"] == "confirmed"


def test_terminal_client_reports_failed_or_empty_responses(monkeypatch, capsys):
    client_script = runpy.run_path(str(Path(__file__).resolve().parents[2] / "docs/invoke-hosted-claims-workflow.py"))
    monkeypatch.setitem(client_script["main"].__globals__, "_client", lambda *_: SimpleNamespace(
        responses=SimpleNamespace(create=lambda **_: SimpleNamespace(
            status="failed", error=SimpleNamespace(message="Workflow state error"), output=[], output_text=""
        ))
    ))
    monkeypatch.setattr(sys, "argv", ["invoke-hosted-claims-workflow.py", "--local", "--indexed-claim", "crash3"])
    with pytest.raises(RuntimeError, match="Workflow state error"):
        client_script["main"]()
    assert "--- Final Decision ---" not in capsys.readouterr().out

    monkeypatch.setitem(client_script["main"].__globals__, "_client", lambda *_: SimpleNamespace(
        responses=SimpleNamespace(create=lambda **_: SimpleNamespace(
            status="completed", error=None, output=[], output_text=""
        ))
    ))
    with pytest.raises(RuntimeError, match="without a final decision"):
        client_script["main"]()


def test_terminal_client_resumes_review_in_original_session(monkeypatch, capsys):
    client_script = runpy.run_path(str(Path(__file__).resolve().parents[2] / "docs/invoke-hosted-claims-workflow.py"))
    pending = SimpleNamespace(
        status="completed", error=None, id="response-1", agent_session_id="session-1", output_text="",
        output=[SimpleNamespace(
            type="function_call", call_id="call-1",
            arguments=json.dumps({"request": {
                "result": {"coverage_decision": {"confidence_score": 0.5}},
                "decision_status": "APPROVED", "threshold": 0.9, "prompt": "Approve?",
            }}),
        )],
    )
    done = SimpleNamespace(
        status="completed", error=None, id="response-2", agent_session_id="session-1",
        output=[], output_text='{"status": "APPROVED"}',
    )
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        return pending if len(requests) == 1 else done

    monkeypatch.setitem(client_script["main"].__globals__, "_client",
                        lambda *_: SimpleNamespace(responses=SimpleNamespace(create=create)))
    monkeypatch.setattr(sys, "argv", ["invoke-hosted-claims-workflow.py", "--local", "--indexed-claim", "crash3"])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda _: "approve")
    client_script["main"]()
    assert requests[1] == {
        "previous_response_id": "response-1", "extra_body": {"agent_session_id": "session-1"},
        "input": [{"type": "function_call_output", "call_id": "call-1", "output": "approve"}],
    }
    assert '{"status": "APPROVED"}' in capsys.readouterr().out


def test_openai_client_sends_session_id_in_continuation_body():
    from openai import OpenAI

    bodies = []

    def handle(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "response-2", "object": "response", "status": "completed",
            "output": [], "agent_session_id": "session-1",
        })

    with httpx.Client(transport=httpx.MockTransport(handle)) as transport:
        client = OpenAI(base_url="http://localhost:8088", api_key="local", http_client=transport)
        response = client.responses.create(
            previous_response_id="response-1",
            extra_body={"agent_session_id": "session-1"},
            input=[{"type": "function_call_output", "call_id": "call-1", "output": "approve"}],
        )
    assert bodies[0]["agent_session_id"] == response.agent_session_id == "session-1"


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
