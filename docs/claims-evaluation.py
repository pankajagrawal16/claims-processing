#!/usr/bin/env python3
"""Evaluate claims-intelligence-agent decisions with a rubric, built-in evaluators and ground truth.

    python claims-evaluation.py --create-rubric      # create or update the rubric evaluator
    python claims-evaluation.py --run                # run a batch evaluation and print results
    python claims-evaluation.py --cleanup            # delete what the two commands above created
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

FOUNDRY_PROJECT_ENDPOINT = os.environ.get(
    "FOUNDRY_PROJECT_ENDPOINT", os.environ.get("AI_FOUNDRY_PROJECT_ENDPOINT", "")
)
JUDGE_MODEL = os.environ.get("FOUNDRY_MODEL", os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-5.4"))
EVAL_DIR = REPO_ROOT / "data" / "evaluation"
RUBRIC_NAME = "claims-decision-quality"
TERMINAL = {"completed", "failed", "canceled"}


def as_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None) or getattr(value, "as_dict", None)
    return dump() if dump else dict(value)


def evaluators_client(project):
    """The evaluator operations moved out of `beta` in newer SDK versions."""
    return getattr(project, "evaluators", None) or project.beta.evaluators


def create_rubric(project, rubric_file: Path):
    from azure.ai.projects.models import EvaluatorCategory, EvaluatorDefinitionType

    rubric = json.loads(rubric_file.read_text(encoding="utf-8"))
    evaluator = evaluators_client(project).create_version(
        name=RUBRIC_NAME,
        evaluator_version={
            "name": RUBRIC_NAME,
            "categories": [EvaluatorCategory.QUALITY],
            "display_name": rubric["display_name"],
            "description": rubric["description"],
            "definition": {
                "type": EvaluatorDefinitionType.RUBRIC,
                "dimensions": rubric["dimensions"],
                "pass_threshold": rubric["pass_threshold"],
            },
        },
    )
    print(f"Rubric evaluator '{evaluator.name}' version {evaluator.version} "
          f"({len(rubric['dimensions'])} dimensions, pass threshold {rubric['pass_threshold']})")
    return evaluator


def testing_criteria() -> list[dict]:
    judge = {"deployment_name": JUDGE_MODEL}
    return [
        {
            "type": "azure_ai_evaluator", "name": "Claims Decision Quality", "evaluator_name": RUBRIC_NAME,
            "initialization_parameters": judge,
            "data_mapping": {"query": "{{item.query}}", "response": "{{sample.output_items}}"},
        },
        {
            "type": "azure_ai_evaluator", "name": "Task Adherence", "evaluator_name": "builtin.task_adherence",
            "initialization_parameters": judge,
            "data_mapping": {"query": "{{item.query}}", "response": "{{sample.output_items}}"},
        },
        {
            "type": "azure_ai_evaluator", "name": "Coherence", "evaluator_name": "builtin.coherence",
            "initialization_parameters": judge,
            "data_mapping": {"query": "{{item.query}}", "response": "{{sample.output_text}}"},
        },
        {
            "type": "azure_ai_evaluator", "name": "Violence", "evaluator_name": "builtin.violence",
            "data_mapping": {"query": "{{item.query}}", "response": "{{sample.output_text}}"},
        },
    ]


def response_text(item: dict) -> str:
    source = item.get("datasource_item") or {}
    sample = item.get("sample") or {}
    for text in (source.get("sample.output_text"), sample.get("output_text")):
        if isinstance(text, str) and text:
            return text
    output = sample.get("output") or sample.get("output_items") or []
    parts = []
    for out in output:
        if not isinstance(out, dict):
            continue
        content = out.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(
                part["text"] for part in content
                if isinstance(part, dict) and part.get("type") == "output_text"
                and isinstance(part.get("text"), str)
            )
    return "\n".join(parts)


def decision_status(text: str) -> str:
    try:
        decision = json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())
    except ValueError:
        return "UNPARSEABLE"
    if not isinstance(decision, dict) or not isinstance(decision.get("is_covered"), bool):
        return "UNPARSEABLE"
    if not isinstance(decision.get("requires_escalation", False), bool):
        return "UNPARSEABLE"
    if decision.get("requires_escalation"):
        return "ESCALATED"
    return "APPROVED" if decision.get("is_covered") else "DENIED"


def run_evaluation(project, args) -> None:
    openai_client = project.get_openai_client()
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")

    dataset = project.datasets.upload_file(
        name="claims-decision-eval", version=stamp, file_path=str(args.dataset)
    )
    print(f"Uploaded dataset claims-decision-eval version {stamp}")

    evaluation = openai_client.evals.create(
        name=f"{args.name}",
        data_source_config={
            "type": "custom",
            "item_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            "include_sample_schema": True,
        },
        testing_criteria=testing_criteria(),
    )
    run = openai_client.evals.runs.create(
        eval_id=evaluation.id,
        name=f"{args.name}-{stamp}",
        data_source={
            "type": "azure_ai_target_completions",
            "source": {"type": "file_id", "id": dataset.id},
            "input_messages": {
                "type": "template",
                "template": [{"type": "message", "role": "user", "content": {"type": "input_text", "text": "{{item.query}}"}}],
            },
            "target": {"type": "azure_ai_agent", "name": args.agent},
        },
    )
    print(f"Evaluation {evaluation.id}, run {run.id}. Waiting for results...")

    while run.status not in TERMINAL:
        time.sleep(10)
        run = openai_client.evals.runs.retrieve(run_id=run.id, eval_id=evaluation.id)
    print(f"Run {run.status}. Report: {getattr(run, 'report_url', None)}\n")
    if run.status != "completed":
        sys.exit(1)

    print("Judge results (pass counts per evaluator)")
    for result in as_dict(run).get("per_testing_criteria_results") or []:
        print(f"  {result['testing_criteria']:26} passed {result['passed']}  failed {result['failed']}  errored {result.get('errored', 0)}")

    dataset_rows = {json.loads(line)["query"]: json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines() if line}
    print("\nGround truth (this script) vs rubric judge")
    print(f"  {'case':30} {'category':9} {'status':10} {'ground truth':13} {'rubric':8}")
    correct = {}
    for raw in openai_client.evals.runs.output_items.list(run_id=run.id, eval_id=evaluation.id):
        item = as_dict(raw)
        row = dataset_rows.get((item.get("datasource_item") or {}).get("query", ""), {})
        status = decision_status(response_text(item))
        ok = status in row.get("allowed_statuses", [])
        rubric = next((as_dict(r) for r in item.get("results") or [] if as_dict(r).get("name") == "Claims Decision Quality"), {})
        score = rubric.get("score")
        print(f"  {row.get('case', '?'):30} {row.get('category', '?'):9} {status:10} {'correct' if ok else 'WRONG':13} "
              f"{'n/a' if score is None else f'{score:.2f}'} {'pass' if rubric.get('passed') else 'fail'}")
        correct.setdefault(row.get("category", "?"), []).append(ok)
    print("\nGround-truth accuracy by category")
    for category, results in sorted(correct.items()):
        print(f"  {category:9} {sum(results)}/{len(results)}")


def cleanup(project, openai_client) -> None:
    """Delete the evaluations, dataset versions and rubric versions this script creates."""
    from azure.core.exceptions import ResourceNotFoundError

    for evaluation in list(openai_client.evals.list(limit=100)):
        if evaluation.name.startswith("claims-decision-evaluation"):
            openai_client.evals.delete(eval_id=evaluation.id)
            print(f"Deleted evaluation {evaluation.name}")
    try:
        for version in list(project.datasets.list_versions(name="claims-decision-eval")):
            project.datasets.delete(name="claims-decision-eval", version=version.version)
            print(f"Deleted dataset version {version.version}")
    except ResourceNotFoundError:
        pass
    evaluators = evaluators_client(project)
    try:
        for version in list(evaluators.list_versions(name=RUBRIC_NAME)):
            evaluators.delete_version(name=RUBRIC_NAME, version=version.version)
            print(f"Deleted rubric version {version.version}")
    except ResourceNotFoundError:
        pass  # the service reports a missing evaluator as an error, not an empty list


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate claims decisions with Foundry evaluations")
    parser.add_argument("--create-rubric", action="store_true", help="Create a new version of the rubric evaluator")
    parser.add_argument("--run", action="store_true", help="Run a batch evaluation against the agent")
    parser.add_argument("--cleanup", action="store_true", help="Delete the evaluations, datasets and rubric versions created here")
    parser.add_argument("--agent", default="claims-intelligence-agent", help="Foundry agent to evaluate")
    parser.add_argument("--name", default="claims-decision-evaluation", help="Evaluation name")
    parser.add_argument("--dataset", type=Path, default=EVAL_DIR / "claims-decision-eval.jsonl")
    parser.add_argument("--rubric-file", type=Path, default=EVAL_DIR / "claims-decision-rubric.json")
    args = parser.parse_args()

    if not (args.create_rubric or args.run or args.cleanup):
        parser.error("choose --create-rubric, --run or --cleanup")
    if not FOUNDRY_PROJECT_ENDPOINT:
        print("FOUNDRY_PROJECT_ENDPOINT is not set. Complete Challenges 2 and 3 first.")
        sys.exit(1)

    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    with DefaultAzureCredential() as credential, AIProjectClient(
        endpoint=FOUNDRY_PROJECT_ENDPOINT, credential=credential, allow_preview=True
    ) as project:
        if args.create_rubric:
            create_rubric(project, args.rubric_file)
        if args.run:
            run_evaluation(project, args)
        if args.cleanup:
            with project.get_openai_client() as openai_client:
                cleanup(project, openai_client)


if __name__ == "__main__":
    main()
