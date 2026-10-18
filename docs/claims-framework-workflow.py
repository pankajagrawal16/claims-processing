#!/usr/bin/env python3
"""Run the two Foundry agents from Challenges 2 and 3 as an Agent Framework workflow.

Drop-in alternative to claims-sequential-workflow.py: same arguments, same result.
"""

import argparse
import asyncio
import json
import os
import shlex
import sys
from pathlib import Path

from dotenv import load_dotenv
from opentelemetry import trace

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")
sys.path.insert(0, str(REPO_ROOT / "agent-framework"))

FOUNDRY_PROJECT_ENDPOINT = os.environ.get(
    "FOUNDRY_PROJECT_ENDPOINT", os.environ.get("AI_FOUNDRY_PROJECT_ENDPOINT", "")
)
FOUNDRY_MODEL = os.environ.get(
    "FOUNDRY_MODEL", os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-5.4")
)

STEP_MESSAGES = {
    ("executor_invoked", "intake_agent"): "  [Step 1] claims-intake-agent running...",
    ("executor_completed", "intake_agent"): "  [Step 1] Intake complete.",
    ("executor_invoked", "policy_agent"): "  [Step 2] claims-intelligence-agent running...",
    ("executor_completed", "decision_agent"): "  [Step 2] Intelligence complete.",
}


def configure_tracing(*, capture_content: bool = False):
    """Configure CLI tracing only; the hosted server owns its own providers."""
    connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    if not connection_string:
        raise ValueError("--trace requires APPLICATIONINSIGHTS_CONNECTION_STRING in the workshop .env.")

    try:
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Tracing dependencies are missing. From 05_Claims_Processing, run "
            "'uv sync --extra tracing' and activate .venv."
        ) from exc
    from agent_framework.observability import configure_otel_providers

    os.environ.setdefault("OTEL_SERVICE_NAME", "claims-framework-workflow")
    configure_otel_providers(
        enable_sensitive_data=capture_content,
        enable_console_exporters=False,
        exporters=[AzureMonitorTraceExporter(
            connection_string=connection_string,
            disable_offline_storage=True,
        )],
    )
    return trace.get_tracer_provider()


async def _drain(stream) -> object:
    """Print step progress while the workflow runs and return the final response."""
    async for event in stream:
        message = STEP_MESSAGES.get((event.type, getattr(event, "executor_id", None)))
        if message:
            print(message, flush=True)
    return await stream.get_final_response()


async def _run(request_text: str) -> dict:
    from azure.identity.aio import DefaultAzureCredential
    from workflow import build_workflow

    async with DefaultAzureCredential() as credential:
        workflow = build_workflow(credential)
        response = await _drain(workflow.run(request_text, stream=True))

        review_started = False
        while pending := response.get_request_info_events():
            request = pending[0]
            if not review_started:
                review_started = True
                print("  [Step 3] Human review requested...")
                print(
                    f"    Decision status: {request.data['decision_status']} | "
                    f"confidence: {float(request.data['confidence']):.2f} | "
                    f"threshold: {float(request.data['threshold']):.2f}"
                )
                if not sys.stdin.isatty():
                    raise RuntimeError(
                        "Human review is required, but the workflow is running in a non-interactive terminal."
                    )
                print("    Workflow paused. Waiting for human-in-the-loop input.", flush=True)
            reviewer_action = input(f"    {request.data['prompt']} ")
            response = await _drain(
                workflow.run(responses={request.request_id: reviewer_action}, stream=True)
            )

        result = json.loads(response.get_outputs()[-1][0].text)
        if "human_review" in result:
            print("  [Step 3] Human review complete.")
        return result


def run_claims_pipeline(
    image_path: Path | None,
    claim_id: str,
    claim_amount: float,
    policy_number: str | None,
    indexed_claim: str | None = None,
) -> dict:
    """Run the intake and intelligence agents as a workflow and return the claim result."""
    if bool(image_path) == bool(indexed_claim):
        raise ValueError("An image path or indexed claim reference is required.")

    args = [shlex.quote(str(image_path))] if image_path else ["--indexed-claim", shlex.quote(indexed_claim)]
    args += ["--claim-id", shlex.quote(claim_id), "--amount", str(claim_amount)]
    if policy_number:
        args += ["--policy", shlex.quote(policy_number)]
    with trace.get_tracer("claims.workflow").start_as_current_span("claims.process") as span:
        if span.is_recording():
            print(f"  Trace ID : {span.get_span_context().trace_id:032x}", flush=True)
        result = asyncio.run(_run(" ".join(args)))
        span.set_attribute("claims.status", result["status"])
        span.set_attribute("claims.human_review.required", "human_review" in result)
        return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the two-agent claims workflow with Agent Framework"
    )
    parser.add_argument(
        "image_path",
        nargs="?",
        help="Path to the accident statement image used by Challenge 2",
    )
    parser.add_argument(
        "--indexed-claim",
        default="",
        help="Retrieve an existing front statement from Foundry IQ",
    )
    parser.add_argument(
        "--policy", default="",
        help="Optional policy number override; defaults to the intake result",
    )
    parser.add_argument(
        "--claim-id", default="CLM-2026-001",
        help="Claim identifier (default: CLM-2026-001)",
    )
    parser.add_argument(
        "--amount", type=float, default=15000.0,
        help="Claimed amount in USD (default: 15000.0)",
    )
    parser.add_argument(
        "--trace", action="store_true",
        help="Export workflow spans to APPLICATIONINSIGHTS_CONNECTION_STRING (Challenge 5)",
    )
    parser.add_argument(
        "--trace-content", action="store_true",
        help="With --trace, include sensitive prompts and responses; use synthetic lab data only",
    )
    args = parser.parse_args()
    if args.trace_content and not args.trace:
        parser.error("--trace-content requires --trace")

    if not FOUNDRY_PROJECT_ENDPOINT:
        print("FOUNDRY_PROJECT_ENDPOINT is not set. Complete Challenges 2 and 3 first.")
        sys.exit(1)
    if bool(args.image_path) == bool(args.indexed_claim):
        parser.error("provide either image_path or --indexed-claim, but not both")

    image_path = Path(args.image_path).expanduser().resolve() if args.image_path else None
    print("\nClaims Framework Workflow")
    print(f"  Endpoint : {FOUNDRY_PROJECT_ENDPOINT}")
    print(f"  Model    : {FOUNDRY_MODEL}")
    print(f"  Input    : {image_path or f'Foundry IQ claim {args.indexed_claim}'}")
    print(f"  Policy   : {args.policy or 'from intake'}")
    print(f"  Claim ID : {args.claim_id}\n")

    provider = configure_tracing(capture_content=args.trace_content) if args.trace else None
    try:
        output = run_claims_pipeline(
            image_path=image_path,
            claim_id=args.claim_id,
            claim_amount=args.amount,
            policy_number=args.policy or None,
            indexed_claim=args.indexed_claim or None,
        )
    finally:
        if provider is not None:
            if not provider.force_flush(timeout_millis=30000):
                raise RuntimeError("Tracing did not flush within 30 seconds; check exporter diagnostics.")
            provider.shutdown()

    print("\n--- Final Decision ---")
    print(json.dumps(output, indent=2))

    print("\n" + "=" * 60)
    print("CHALLENGE 4 COMPLETE")
    print("=" * 60)
    print("  Step 1 - claims-intake-agent        complete")
    print("  Step 2 - claims-intelligence-agent  complete")
    review_status = "complete" if "human_review" in output else "not required"
    print(f"  Step 3 - human review (conditional) {review_status}")


if __name__ == "__main__":
    main()
