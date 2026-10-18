"""Offline regression checks for the Challenge 5 result reporting."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def load_script(name):
    path = Path(__file__).resolve().parents[2] / "docs" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evaluation = load_script("claims-evaluation")
guardrails = load_script("claims-guardrail-test")
framework = load_script("claims-framework-workflow")


def test_cli_tracing_requires_connection_string(monkeypatch):
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    with pytest.raises(ValueError, match="APPLICATIONINSIGHTS_CONNECTION_STRING"):
        framework.configure_tracing()


@pytest.mark.parametrize("capture_content", [False, True])
def test_cli_tracing_configures_exporter_and_explicit_content_policy(monkeypatch, capture_content):
    import azure.monitor.opentelemetry.exporter as exporters
    from agent_framework import observability

    calls = {}
    exporter = object()
    provider = object()

    def make_exporter(**kwargs):
        calls["exporter"] = kwargs
        return exporter

    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "test-connection")
    monkeypatch.setenv("ENABLE_SENSITIVE_DATA", "true")
    monkeypatch.setattr(exporters, "AzureMonitorTraceExporter", make_exporter)
    monkeypatch.setattr(observability, "configure_otel_providers", lambda **kw: calls.update(kw))
    monkeypatch.setattr(framework.trace, "get_tracer_provider", lambda: provider)

    assert framework.configure_tracing(capture_content=capture_content) is provider
    assert calls["enable_sensitive_data"] is capture_content
    assert calls["enable_console_exporters"] is False
    assert calls["exporters"] == [exporter]
    assert calls["exporter"] == {
        "connection_string": "test-connection", "disable_offline_storage": True,
    }


def test_cli_rejects_content_capture_without_tracing(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["claims-framework-workflow.py", "--trace-content"])
    with pytest.raises(SystemExit) as exc:
        framework.main()
    assert exc.value.code == 2
    assert "--trace-content requires --trace" in capsys.readouterr().err


@pytest.mark.parametrize("trace_enabled, fail", [(False, False), (True, False), (True, True)])
def test_cli_tracing_is_opt_in_and_flushes_on_success_or_failure(monkeypatch, trace_enabled, fail):
    calls = []
    provider = SimpleNamespace(
        force_flush=lambda **kwargs: calls.append("flush") or True,
        shutdown=lambda: calls.append("shutdown"),
    )
    monkeypatch.setattr("sys.argv", [
        "claims-framework-workflow.py", "--indexed-claim", "crash3",
        *(["--trace"] if trace_enabled else []),
    ])
    monkeypatch.setattr(framework, "FOUNDRY_PROJECT_ENDPOINT", "https://example.test")
    monkeypatch.setattr(framework, "configure_tracing", lambda **kwargs: calls.append("configure") or provider)

    def run(**kwargs):
        calls.append("run")
        if fail:
            raise ValueError("bad policy")
        return {"status": "APPROVED"}

    monkeypatch.setattr(framework, "run_claims_pipeline", run)
    if fail:
        with pytest.raises(ValueError, match="bad policy"):
            framework.main()
    else:
        framework.main()
    assert calls == (["configure", "run", "flush", "shutdown"] if trace_enabled else ["run"])


@pytest.mark.parametrize(
    "item",
    [
        {"datasource_item": {"sample.output_text": '{"is_covered": true}'}},
        {"sample": {"output_text": '{"is_covered": true}'}},
        {"sample": {"output": [{"content": '{"is_covered": true}'}]}},
        {"sample": {"output": [
            {"type": "mcp_call", "output": "tool result"},
            {"content": [{"type": "output_text", "text": '{"is_covered": true}'}]},
        ]}},
        {"sample": {"output_items": [
            {"content": [{"type": "output_text", "text": '{"is_covered": true}'}]},
        ]}},
    ],
)
def test_response_text_handles_text_and_structured_outputs(item):
    assert evaluation.decision_status(evaluation.response_text(item)) == "APPROVED"


@pytest.mark.parametrize("text", ["[]", "null", "{}", '{"is_covered": "false"}', "not JSON"])
def test_malformed_decisions_do_not_count_as_denials(text):
    assert evaluation.decision_status(text) == "UNPARSEABLE"


def test_escalation_takes_priority_over_coverage():
    text = json.dumps({"is_covered": True, "requires_escalation": True})
    assert evaluation.decision_status(text) == "ESCALATED"


@pytest.mark.parametrize(
    "status,error,expected",
    [
        ("completed", None, "allowed"),
        ("failed", SimpleNamespace(code="content_filter"), "blocked"),
        ("failed", SimpleNamespace(code="server_error"), "error"),
        ("incomplete", None, "error"),
    ],
)
def test_guardrails_do_not_report_failed_requests_as_allowed(status, error, expected):
    response = SimpleNamespace(
        status=status, error=error, output_text="decision", incomplete_details=None,
    )
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: response))
    assert guardrails.classify(client, "claim")[0] == expected
