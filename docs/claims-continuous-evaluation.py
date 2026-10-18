#!/usr/bin/env python3
"""Run evaluators automatically on live traffic to claims-intelligence-agent (continuous evaluation).

    python claims-continuous-evaluation.py --create   # create the evaluation and the rule
    python claims-continuous-evaluation.py --status   # show the rule and recent runs
    python claims-continuous-evaluation.py --delete   # remove the rule and the evaluation
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

FOUNDRY_PROJECT_ENDPOINT = os.environ.get(
    "FOUNDRY_PROJECT_ENDPOINT", os.environ.get("AI_FOUNDRY_PROJECT_ENDPOINT", "")
)
JUDGE_MODEL = os.environ.get("FOUNDRY_MODEL", os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-5.4"))
RULE_ID = "claims-intelligence-continuous"
EVAL_NAME = "claims-continuous-evaluation"
RUBRIC_NAME = "claims-decision-quality"


def find_evaluation(openai_client):
    return next((e for e in openai_client.evals.list(limit=100) if e.name == EVAL_NAME), None)


def create(project, openai_client, agent: str, max_hourly_runs: int) -> None:
    from azure.ai.projects.models import (
        ContinuousEvaluationRuleAction,
        EvaluationRule,
        EvaluationRuleEventType,
        EvaluationRuleFilter,
    )

    evaluation = find_evaluation(openai_client) or openai_client.evals.create(
        name=EVAL_NAME,
        data_source_config={"type": "azure_ai_source", "scenario": "responses"},
        testing_criteria=[
            {
                "type": "azure_ai_evaluator", "name": "Claims Decision Quality", "evaluator_name": RUBRIC_NAME,
                "initialization_parameters": {"deployment_name": JUDGE_MODEL},
            },
            {"type": "azure_ai_evaluator", "name": "Violence", "evaluator_name": "builtin.violence"},
        ],
    )
    rule = project.evaluation_rules.create_or_update(
        id=RULE_ID,
        evaluation_rule=EvaluationRule(
            display_name="Claims intelligence continuous evaluation",
            description="Scores sampled responses from claims-intelligence-agent.",
            action=ContinuousEvaluationRuleAction(eval_id=evaluation.id, max_hourly_runs=max_hourly_runs),
            event_type=EvaluationRuleEventType.RESPONSE_COMPLETED,
            filter=EvaluationRuleFilter(agent_name=agent),
            enabled=True,
        ),
    )
    print(f"Evaluation {evaluation.id}")
    print(f"Rule '{rule.id}' enabled for agent '{agent}' (at most {max_hourly_runs} runs per hour)")


def status(project, openai_client) -> None:
    rules = [r for r in project.evaluation_rules.list() if r.id == RULE_ID]
    print("Rule:", f"{rules[0].id} enabled={rules[0].enabled}" if rules else "not found")
    evaluation = find_evaluation(openai_client)
    if not evaluation:
        print("Evaluation: not found")
        return
    print(f"Evaluation: {evaluation.id}")
    runs = openai_client.evals.runs.list(eval_id=evaluation.id, order="desc", limit=10).data
    print(f"Recent runs: {len(runs)}")
    for run in runs:
        counts = getattr(run, "result_counts", None)
        print(f"  {run.id}  {run.status:10} {counts}  {getattr(run, 'report_url', '') or ''}")


def delete(project, openai_client) -> None:
    if any(rule.id == RULE_ID for rule in project.evaluation_rules.list()):
        project.evaluation_rules.delete(id=RULE_ID)
        print(f"Deleted rule {RULE_ID}")
    else:
        print(f"Rule {RULE_ID} not found")
    evaluation = find_evaluation(openai_client)
    if evaluation:
        openai_client.evals.delete(eval_id=evaluation.id)
        print(f"Deleted evaluation {evaluation.id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Continuous evaluation for the claims intelligence agent")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--create", action="store_true")
    action.add_argument("--status", action="store_true")
    action.add_argument("--delete", action="store_true")
    parser.add_argument("--agent", default="claims-intelligence-agent")
    parser.add_argument("--max-hourly-runs", type=int, default=50, help="Cap on evaluation runs per hour (cost control)")
    args = parser.parse_args()
    if args.max_hourly_runs <= 0:
        parser.error("--max-hourly-runs must be greater than zero")

    if not FOUNDRY_PROJECT_ENDPOINT:
        print("FOUNDRY_PROJECT_ENDPOINT is not set. Complete Challenges 2 and 3 first.")
        sys.exit(1)

    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    with DefaultAzureCredential() as credential, AIProjectClient(
        endpoint=FOUNDRY_PROJECT_ENDPOINT, credential=credential, allow_preview=True
    ) as project, project.get_openai_client() as openai_client:
        if args.create:
            create(project, openai_client, args.agent, args.max_hourly_runs)
        elif args.status:
            status(project, openai_client)
        else:
            delete(project, openai_client)


if __name__ == "__main__":
    main()
