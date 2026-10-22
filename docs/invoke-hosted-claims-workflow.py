#!/usr/bin/env python3
"""Call the Agent Framework claims workflow as a hosted Foundry agent (or a local server).

Takes the same inputs as the other Challenge 4 scripts and answers human-review requests.
"""

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

FOUNDRY_PROJECT_ENDPOINT = os.environ.get(
    "FOUNDRY_PROJECT_ENDPOINT", os.environ.get("AI_FOUNDRY_PROJECT_ENDPOINT", "")
)


def _client(local: bool, agent_name: str):
    if local:
        from openai import OpenAI

        return OpenAI(base_url="http://localhost:8088", api_key="local")

    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    project = AIProjectClient(
        endpoint=FOUNDRY_PROJECT_ENDPOINT,
        credential=DefaultAzureCredential(),
        allow_preview=True,
    )
    return project.get_openai_client(agent_name=agent_name)


def _check_response(response) -> None:
    if response.status == "failed":
        error = response.error
        raise RuntimeError(f"Workflow failed: {error.message if error else 'No server error details were returned.'}")
    if response.status != "completed":
        raise RuntimeError(f"Workflow did not complete (status: {response.status}).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Invoke the hosted claims workflow")
    parser.add_argument("image_path", nargs="?", help="Statement image path (only its file name is used)")
    parser.add_argument("--indexed-claim", default="", help="Indexed claim reference, e.g. crash3")
    parser.add_argument("--policy", default="", help="Optional policy number override")
    parser.add_argument("--claim-id", default="CLM-2026-001", help="Claim identifier")
    parser.add_argument("--amount", type=float, default=15000.0, help="Claimed amount in USD")
    parser.add_argument("--agent-name", default="ClaimProcessingWorkflow", help="Hosted agent name in Foundry")
    parser.add_argument("--local", action="store_true", help="Call a local server on http://localhost:8088")
    args = parser.parse_args()

    if bool(args.image_path) == bool(args.indexed_claim):
        parser.error("provide either image_path or --indexed-claim, but not both")
    if not args.local and not FOUNDRY_PROJECT_ENDPOINT:
        print("FOUNDRY_PROJECT_ENDPOINT is not set. Complete Challenges 2 and 3 first.")
        sys.exit(1)

    request = [shlex.quote(args.image_path)] if args.image_path else ["--indexed-claim", shlex.quote(args.indexed_claim)]
    request += ["--claim-id", shlex.quote(args.claim_id), "--amount", str(args.amount)]
    if args.policy:
        request += ["--policy", shlex.quote(args.policy)]
    text = " ".join(request)

    client = _client(args.local, args.agent_name)
    print(f"\nInvoking {'local server' if args.local else args.agent_name}")
    print(f"  Input : {text}\n")

    response = client.responses.create(input=text)
    while True:
        _check_response(response)
        review = next((item for item in response.output if item.type == "function_call"), None)
        if review is None:
            break
        if not sys.stdin.isatty():
            raise RuntimeError("Human review is required, but this is a non-interactive terminal.")
        if not response.agent_session_id:
            raise RuntimeError("The server did not return an agent session ID to resume human review.")
        arguments = json.loads(review.arguments)
        data = arguments.get("request") or arguments.get("request_event", {}).get("data")
        if not isinstance(data, dict) or "result" not in data:
            raise RuntimeError("The server returned an unrecognized human-review request.")
        decision = data["result"]["coverage_decision"]
        print("  Human review requested...")
        print(
            f"    Decision status: {data['decision_status']} | "
            f"confidence: {float(decision['confidence_score']):.2f} | "
            f"threshold: {float(data['threshold']):.2f}"
        )
        answer = input(f"    {data['prompt']} ")
        response = client.responses.create(
            previous_response_id=response.id,
            extra_body={"agent_session_id": response.agent_session_id},
            input=[{"type": "function_call_output", "call_id": review.call_id, "output": answer}],
        )

    if not response.output_text:
        raise RuntimeError("Workflow completed without a final decision.")
    print("\n--- Final Decision ---")
    print(response.output_text)


if __name__ == "__main__":
    main()
