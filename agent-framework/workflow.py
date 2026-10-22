"""Claims workflow built with Agent Framework executors and edges.

    prepare -> claims-intake-agent -> policy_prompt -> claims-intelligence-agent
            -> decision_prompt -> claims-intelligence-agent -> route
            -> human_review (low confidence or escalation) or auto_finish

Input is the same text you would pass to docs/claims-sequential-workflow.py:

    <image path> | --indexed-claim crash3   [--policy COMP-AUTO-001] [--claim-id CLM-2026-007] [--amount 28000]

The result has the same fields as the sequential workflow's final decision.
"""

import argparse
import asyncio
import json
import logging
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Never

from agent_framework import (
    AgentExecutorResponse,
    AgentResponse,
    AgentResponseUpdate,
    Executor,
    Message,
    ResponseStream,
    WorkflowBuilder,
    WorkflowContext,
    handler,
    response_handler,
)
from agent_framework.exceptions import ChatClientException
from agent_framework.foundry import FoundryAgent
from agent_framework.openai import OpenAIChatOptions
from azure.identity.aio import DefaultAzureCredential

INTAKE_AGENT = os.getenv("CLAIMS_INTAKE_AGENT_NAME", "claims-intake-agent")
INTELLIGENCE_AGENT = os.getenv("CLAIMS_INTELLIGENCE_AGENT_NAME", "claims-intelligence-agent")
REVIEW_THRESHOLD = float(os.getenv("HUMAN_REVIEW_CONFIDENCE_THRESHOLD", "0.9"))

REVIEW_ACTIONS = {
    "approve": ("confirmed", None), "a": ("confirmed", None), "yes": ("confirmed", None), "y": ("confirmed", None),
    "escalate": ("escalated", "ESCALATED"), "e": ("escalated", "ESCALATED"),
    "review": ("escalated", "ESCALATED"), "manual": ("escalated", "ESCALATED"),
    "deny": ("overridden", "DENIED"), "d": ("overridden", "DENIED"),
    "reject": ("overridden", "DENIED"), "r": ("overridden", "DENIED"),
}
REVIEW_PROMPT = "Type 'approve' to accept, 'escalate' for manual review, or 'deny' to override."
logger = logging.getLogger(__name__)


@dataclass
class ClaimRequest:
    statement_file: str
    claim_id: str
    amount: float
    policy_number: str | None


class _RequestParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(
            f"{message}. Example: --indexed-claim crash3 --policy COMP-AUTO-001 --claim-id CLM-2026-007 --amount 28000"
        )


def parse_request(text: str) -> ClaimRequest:
    """Read the same inputs as claims-sequential-workflow.py."""
    parser = _RequestParser(prog="claim", add_help=False)
    parser.add_argument("image_path", nargs="?", default="")
    parser.add_argument("--indexed-claim", default="")
    parser.add_argument("--policy", default="")
    parser.add_argument("--claim-id", default="CLM-2026-001")
    parser.add_argument("--amount", type=float, default=15000.0)
    args = parser.parse_args(shlex.split(text))

    if bool(args.image_path) == bool(args.indexed_claim):
        raise ValueError(
            "Provide either an image path or --indexed-claim, but not both. "
            "Example: --indexed-claim crash3 --policy COMP-AUTO-001"
        )

    source = args.image_path or args.indexed_claim
    if args.image_path and Path(source).suffix:
        statement_file = f"{Path(source).stem}.jpeg"  # only the file name is used: the statement is read from the index
    else:
        reference = Path(source).name.removesuffix(".jpeg")
        statement_file = f"{reference if reference.endswith('_front') else reference + '_front'}.jpeg"

    return ClaimRequest(statement_file, args.claim_id, args.amount, args.policy.upper() or None)


class CompletingFoundryAgent(FoundryAgent):
    def run(self, messages=None, *, stream=False, session=None, **kwargs):
        async def complete():
            try:
                async with asyncio.timeout(300):
                    response = await super(CompletingFoundryAgent, self).run(
                        messages, stream=False, session=session, **kwargs
                    )
                    while response.continuation_token is not None:
                        await asyncio.sleep(2)
                        response = await super(CompletingFoundryAgent, self).run(
                            session=session,
                            options=OpenAIChatOptions(continuation_token=response.continuation_token),
                        )
            except TimeoutError:
                logger.error("Foundry agent %s timed out before completing its response.", self.name)
                raise
            except ChatClientException:
                logger.exception("Foundry agent %s failed during execution.", self.name)
                raise
            if not response.text and not response.user_input_requests:
                logger.error("Foundry agent %s completed without a response.", self.name)
                raise RuntimeError(f"Foundry agent {self.name} completed without a response.")
            return response

        if not stream:
            return complete()

        result: AgentResponse | None = None

        async def updates():
            nonlocal result
            result = await complete()
            for message in result.messages:
                yield AgentResponseUpdate(role=message.role, contents=message.contents)

        def finalizer(_updates):
            if result is None:
                raise RuntimeError(f"Foundry agent {self.name} did not finish.")
            return result

        return ResponseStream(updates(), finalizer=finalizer)


def connect(agent_name: str, step_id: str, credential) -> FoundryAgent:
    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT") or os.environ["AI_FOUNDRY_PROJECT_ENDPOINT"]
    return CompletingFoundryAgent(
        project_endpoint=endpoint,
        agent_name=agent_name,
        agent_version="",  # Ignore the hosted workflow's FOUNDRY_AGENT_VERSION.
        allow_preview=True,
        credential=credential,
        name=step_id,  # the intelligence agent appears twice and step names must be unique
        default_options={"store": False},
    )


def user(text: str) -> list[Message]:
    return [Message("user", [text])]


def as_json(text: str) -> dict:
    return json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip()))


class Prepare(Executor):
    """Reads the request and asks the intake agent for the indexed statement."""

    def __init__(self) -> None:
        super().__init__(id="prepare")

    @handler
    async def run(self, request: str | list[Message], ctx: WorkflowContext[list[Message]]) -> None:
        claim = parse_request(request if isinstance(request, str) else request[-1].text)
        ctx.set_state("claim_id", claim.claim_id)
        ctx.set_state("filename", claim.statement_file)
        ctx.set_state("amount", claim.amount)
        ctx.set_state("policy_number", claim.policy_number)
        await ctx.send_message(
            user(
                f'INDEXED_STATEMENT_TASK\nSearch for the exact quoted source filename "{claim.statement_file}" '
                "without adding other terms. Summarize the matching statement and include the policy number."
            )
        )


class PolicyPrompt(Executor):
    def __init__(self) -> None:
        super().__init__(id="policy_prompt")

    @handler
    async def run(self, reply: AgentExecutorResponse, ctx: WorkflowContext[list[Message]]) -> None:
        statement = reply.agent_response.text
        found = re.search(r"\b[A-Z]+(?:-[A-Z]+)*-\d+\b", statement)
        policy_number = ctx.get_state("policy_number") or (found[0] if found else None)
        if not policy_number:
            raise ValueError(
                f"No policy number found for {ctx.get_state('filename')}. "
                "Check that the statement is indexed (Challenge 2) or pass --policy."
            )
        ctx.set_state("statement", statement)
        ctx.set_state("policy_number", policy_number)
        await ctx.send_message(
            user(
                f"POLICY_EXTRACTION_TASK\nRetrieve the policy with exact Policy Code {policy_number} "
                "and extract its coverage fields."
            )
        )


class DecisionPrompt(Executor):
    def __init__(self) -> None:
        super().__init__(id="decision_prompt")

    @handler
    async def run(self, reply: AgentExecutorResponse, ctx: WorkflowContext[list[Message]]) -> None:
        policy_number = ctx.get_state("policy_number")
        extracted = as_json(reply.agent_response.text)
        if extracted.get("policy_type") == "NOT_FOUND":
            raise LookupError(f"Policy {policy_number} not found")
        policy = {
            "policy_id": policy_number.lower().replace("-", "_"),
            "policy_number": policy_number,
            "policy_type": extracted.get("policy_type", "Unknown"),
            "coverage_types": extracted.get("coverage_types", []),
            "limits": extracted.get("limits", {}),
            "deductibles": extracted.get("deductibles", {}),
            "exclusions": extracted.get("exclusions", []),
        }
        ctx.set_state("policy", policy)
        await ctx.send_message(
            user(
                "COVERAGE_DECISION_TASK\n"
                f"**CLAIM INFORMATION:**\n- Policy Number: {policy_number}\n"
                f"- Claim Amount: ${ctx.get_state('amount'):,.2f}\n- Claim Type: collision\n"
                f"- Statement: {ctx.get_state('statement')}\n\n"
                f"**POLICY INFORMATION:**\n- Policy Type: {policy['policy_type']}\n"
                f"- Coverage Types: {', '.join(policy['coverage_types'])}\n"
                f"- Limits: {json.dumps(policy['limits'])}\n- Deductibles: {json.dumps(policy['deductibles'])}\n"
                f"- Exclusions: {', '.join(policy['exclusions']) or 'None'}\n\n"
                "Determine if this claim is covered under the policy and calculate the approved payment "
                "amount. Consider the claim type against policy coverage types, check limits, apply "
                "deductible, and identify any exclusions."
            )
        )


class Route(Executor):
    """Builds the claim result and sends it to review or straight to the final answer."""

    def __init__(self) -> None:
        super().__init__(id="route")

    @handler
    async def run(self, reply: AgentExecutorResponse, ctx: WorkflowContext[dict]) -> None:
        raw = as_json(reply.agent_response.text)
        decision = {
            "is_covered": raw.get("is_covered", False),
            "coverage_percentage": raw.get("coverage_percentage", 0),
            "applicable_deductible": float(raw.get("applicable_deductible", 0)),
            "approved_amount": float(raw.get("approved_amount", 0)),
            "exclusions_matched": raw.get("exclusions_matched", []),
            "reasoning": raw.get("reasoning", ""),
            "risk_flags": raw.get("risk_flags", []),
            "confidence_score": raw.get("confidence_score", 0.85),
            "consistency_score": int(raw.get("consistency_score", 0)),
            "requires_escalation": bool(raw.get("requires_escalation", False)),
            "escalation_reason": raw.get("escalation_reason"),
        }
        status = "ESCALATED" if decision["requires_escalation"] else ("APPROVED" if decision["is_covered"] else "DENIED")
        errors = []
        if decision["requires_escalation"]:
            errors.append(
                {
                    "error_code": "ESCALATION_REQUIRED",
                    "error_message": decision["escalation_reason"] or "Manual review needed",
                    "severity": "WARN",
                    "recommendation": "Escalate to claims adjuster for manual review",
                    "agent_name": INTELLIGENCE_AGENT,
                }
            )
        result = {
            "claim_id": ctx.get_state("claim_id"),
            "status": status,
            "policy_info": ctx.get_state("policy"),
            "coverage_decision": decision,
            "errors": errors,
        }
        confidence = float(decision["confidence_score"] or 0)
        await ctx.send_message(
            {"needs_review": status == "ESCALATED" or confidence < REVIEW_THRESHOLD, "result": result}
        )


class AutoFinish(Executor):
    def __init__(self) -> None:
        super().__init__(id="auto_finish")

    @handler
    async def run(self, routed: dict, ctx: WorkflowContext[Never, list[Message]]) -> None:
        await ctx.yield_output([Message("assistant", [json.dumps(routed["result"], indent=2)])])


class HumanReview(Executor):
    """Pauses until a reviewer answers approve, escalate or deny."""

    def __init__(self) -> None:
        super().__init__(id="human_review")

    @staticmethod
    def _request(result: dict, note: str = "") -> dict:
        decision = result["coverage_decision"]
        return {
            "message": "Human review requested. " + note + REVIEW_PROMPT,
            "prompt": note + REVIEW_PROMPT,
            "decision_status": result["human_review"]["agent_status"],
            "confidence": decision["confidence_score"],
            "threshold": REVIEW_THRESHOLD,
            "result": result,
        }

    @handler
    async def run(self, routed: dict, ctx: WorkflowContext[Never, list[Message]]) -> None:
        result = routed["result"]
        result["human_review"] = {
            "required": True,
            "status": "pending",
            "agent_status": result["status"],
            "confidence_threshold": REVIEW_THRESHOLD,
        }
        result["status"] = "PENDING_HUMAN_REVIEW"
        await ctx.request_info(self._request(result), str)

    @response_handler
    async def on_review(self, original_request: dict, response: str, ctx: WorkflowContext[Never, list[Message]]) -> None:
        result = original_request["result"]
        words = response.strip().strip('"').split(maxsplit=1)
        action = words[0].lower() if words else ""
        if action not in REVIEW_ACTIONS:
            await ctx.request_info(self._request(result, "Invalid response. Enter approve, escalate, or deny. "), str)
            return

        review_status, override = REVIEW_ACTIONS[action]
        final_status = override or result["human_review"]["agent_status"]
        result["status"] = final_status
        result["human_review"].update(
            {"status": review_status, "reviewer_action": action, "final_status": final_status}
        )
        if len(words) > 1:
            result["human_review"]["comment"] = words[1]
        await ctx.yield_output([Message("assistant", [json.dumps(result, indent=2)])])


def build_workflow(credential=None):
    credential = credential or DefaultAzureCredential()
    prepare, policy_prompt, decision_prompt = Prepare(), PolicyPrompt(), DecisionPrompt()
    intake = connect(INTAKE_AGENT, "intake_agent", credential)
    policy_agent = connect(INTELLIGENCE_AGENT, "policy_agent", credential)
    decision_agent = connect(INTELLIGENCE_AGENT, "decision_agent", credential)
    route, auto_finish, human_review = Route(), AutoFinish(), HumanReview()

    return (
        WorkflowBuilder(name="claims_workflow", start_executor=prepare)
        .add_edge(prepare, intake)
        .add_edge(intake, policy_prompt)
        .add_edge(policy_prompt, policy_agent)
        .add_edge(policy_agent, decision_prompt)
        .add_edge(decision_prompt, decision_agent)
        .add_edge(decision_agent, route)
        .add_edge(route, human_review, condition=lambda r: r["needs_review"])
        .add_edge(route, auto_finish, condition=lambda r: not r["needs_review"])
        .build()
    )
