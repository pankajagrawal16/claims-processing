#!/usr/bin/env python3
"""Claims intake agent that combines Mistral Document AI OCR with Foundry IQ retrieval."""

import argparse
import base64
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPTool, PromptAgentDefinition
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

FOUNDRY_AGENT_NAME = "claims-intake-agent"
CRASH_STATEMENTS_KNOWLEDGE_BASE_NAME = os.environ.get(
    "FOUNDRY_IQ_KNOWLEDGE_BASE_NAME", "crash-statements-kb"
)
CRASH_STATEMENTS_SERVER_LABEL = "crash-statements-knowledge-base"
MCP_API_VERSION = os.environ.get("FOUNDRY_IQ_MCP_API_VERSION", "2026-08-01-preview")
FOUNDRY_AGENT_INSTRUCTIONS = (
    "When the input starts with INDEXED_STATEMENT_TASK, call the "
    f"{CRASH_STATEMENTS_SERVER_LABEL} server's knowledge_base_retrieve tool exactly once "
    "using only the supplied source filename as a quoted phrase query. Do not add generic "
    "words, claimant details, dates, or locations to this query. Summarize only the exact "
    "matching statement. For other inputs, follow the OCR intake instructions below. "
    "You are the Claims Intake Agent. Before answering, you MUST call the "
    f"{CRASH_STATEMENTS_SERVER_LABEL} server's knowledge_base_retrieve tool exactly once "
    "to search the crash statements using key identifying details from the OCR text "
    "(claimant name, date, location). Always perform this search first, even if you believe "
    "you already know the answer. Then, in 2-3 sentences, summarize the claimant, vehicle, "
    "and incident from the new OCR text, and note whether the retrieved match is consistent "
    "with it."
)


class VehicleInfo(BaseModel):
    make: str | None = None
    model: str | None = None
    year: str | None = None
    license_plate: str | None = None
    vin: str | None = None


class Witness(BaseModel):
    name: str | None = None
    phone: str | None = None


class ClaimAnnotation(BaseModel):
    """Document annotation schema: structured claim data extracted from the full accident statement."""

    claimant_name: str = Field(..., description="Full name of the person filing the claim")
    claim_date: str | None = Field(None, description="Date when the claim was filed or incident occurred (MM/DD/YYYY format)")
    policy_number: str | None = Field(None, description="Insurance policy number")
    incident_description: str = Field(..., description="Description of what happened during the incident")
    vehicle_info: VehicleInfo | None = None
    damage_description: str | None = Field(None, description="Description of damage to the vehicle")
    estimated_damage_amount: str | None = Field(None, description="Estimated cost of damages")
    witnesses: list[Witness] = Field(default_factory=list)
    signature_present: bool | None = Field(None, description="Whether a signature is present on the document")
    date_signed: str | None = Field(None, description="Date when the document was signed")


def _document_annotation_format() -> dict[str, Any]:
    """Build the document_annotation_format payload requesting structured claim extraction."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "ClaimAnnotation",
            "schema": ClaimAnnotation.model_json_schema(),
            "strict": True,
        },
    }


def _encode_image_as_data_url(image_path: Path) -> tuple[str, str]:
    suffix = image_path.suffix.lower()
    mime_type = "image/jpeg"
    url_type = "image_url"

    if suffix == ".png":
        mime_type = "image/png"
    elif suffix == ".pdf":
        mime_type = "application/pdf"
        url_type = "document_url"

    encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}", url_type


def run_mistral_ocr(image_path: Path) -> dict[str, Any]:
    endpoint = os.getenv("MISTRAL_DOCUMENT_AI_ENDPOINT", "").rstrip("/")
    api_key = os.getenv("MISTRAL_DOCUMENT_AI_KEY", "")
    model = os.getenv("MISTRAL_DOCUMENT_AI_DEPLOYMENT_NAME", "mistral-document-ai-2512")

    if not endpoint or not api_key:
        raise RuntimeError("Missing Mistral Document AI configuration in .env")

    data_url, url_type = _encode_image_as_data_url(image_path)

    payload = {
        "model": model,
        "document": {
            "type": url_type,
            url_type: data_url,
        },
        "document_annotation_format": _document_annotation_format(),
    }

    api_version = os.getenv("MISTRAL_DOCUMENT_AI_API_VERSION", "2024-05-01-preview")
    ocr_endpoint = f"{endpoint}/providers/mistral/azure/ocr?api-version={api_version}"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    with httpx.Client(timeout=300.0) as client:
        response = client.post(ocr_endpoint, headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()

    pages = body.get("pages", [])
    if pages:
        text = "\n\n".join(page.get("markdown", "") for page in pages if isinstance(page, dict))
    else:
        text = body.get("content") or body.get("text") or ""

    document_annotation_raw = body.get("document_annotation")
    document_annotation: dict[str, Any] | None = None
    if isinstance(document_annotation_raw, str):
        try:
            document_annotation = json.loads(document_annotation_raw)
        except json.JSONDecodeError:
            document_annotation = None
    elif isinstance(document_annotation_raw, dict):
        document_annotation = document_annotation_raw

    return {
        "model": model,
        "text": text,
        "character_count": len(text),
        "pages_processed": len(pages) if pages else 1,
        "document_annotation": document_annotation,
    }


def _get_knowledge_connection_id(
    client: AIProjectClient, knowledge_base_name: str, expected_url: str
) -> str:
    """Find the RemoteTool connection that targets the Foundry IQ knowledge base."""
    expected_name = os.environ.get("FOUNDRY_IQ_CRASH_STATEMENTS_CONNECTION_NAME", "")
    connections = [
        connection
        for connection in client.connections.list()
        if getattr(connection.type, "value", connection.type) in {"RemoteTool", "RemoteTool_Preview"}
    ]
    if expected_name:
        connection = next(
            (item for item in connections if item.name == expected_name or item.id == expected_name),
            None,
        )
    else:
        connection = next(
            (item for item in connections if knowledge_base_name in (getattr(item, "target", "") or "")),
            None,
        )

    if connection is None:
        raise RuntimeError(
            f"No Foundry RemoteTool connection targets '{knowledge_base_name}'. "
            "Redeploy labautomation/azuredeploy.json, then rerun the intake agent."
        )
    if connection.target != expected_url:
        raise RuntimeError(
            f"Foundry RemoteTool connection '{connection.name}' targets {connection.target}, "
            f"but the agent expects {expected_url}. Update the Foundry project's RemoteTool "
            "connection target by running 'python fix_crash_statements_connection.py' "
            "from the docs directory, then rerun the intake agent."
        )
    return connection.id


def _build_crash_statements_knowledge_tool(client: AIProjectClient) -> MCPTool:
    """Build the MCP tool that retrieves indexed crash statements through Foundry IQ."""
    search_endpoint = (
        os.environ.get("FOUNDRY_IQ_SEARCH_ENDPOINT")
        or os.environ.get("SEARCH_SERVICE_ENDPOINT", "")
    ).rstrip("/")
    if not search_endpoint:
        raise RuntimeError("FOUNDRY_IQ_SEARCH_ENDPOINT is not set. Complete Task 1 first.")

    server_url = (
        f"{search_endpoint}/knowledgebases/{CRASH_STATEMENTS_KNOWLEDGE_BASE_NAME}"
        f"/mcp?api-version={MCP_API_VERSION}"
    )
    return MCPTool(
        server_label=CRASH_STATEMENTS_SERVER_LABEL,
        server_url=server_url,
        require_approval="never",
        allowed_tools=["knowledge_base_retrieve"],
        project_connection_id=_get_knowledge_connection_id(
            client, CRASH_STATEMENTS_KNOWLEDGE_BASE_NAME, server_url
        ),
    )


def _ensure_foundry_agent(client: AIProjectClient, model_deployment: str) -> None:
    """Register the Claims Intake Agent or update it when its model, instructions, or tool change."""
    expected_tool = _build_crash_statements_knowledge_tool(client)
    try:
        client.agents.get(FOUNDRY_AGENT_NAME)
        versions = list(client.agents.list_versions(FOUNDRY_AGENT_NAME))
        latest_version = max(versions, key=lambda version: int(version.version))
        latest_tools = getattr(latest_version.definition, "tools", None) or []
        latest_tool_matches = any(
            getattr(tool, "type", None) == "mcp"
            and getattr(tool, "server_label", None) == CRASH_STATEMENTS_SERVER_LABEL
            and getattr(tool, "server_url", None) == expected_tool.server_url
            and getattr(tool, "project_connection_id", None) == expected_tool.project_connection_id
            for tool in latest_tools
        )
        if (
            latest_version.definition.model == model_deployment
            and latest_version.definition.instructions == FOUNDRY_AGENT_INSTRUCTIONS
            and latest_tool_matches
        ):
            return
    except ResourceNotFoundError:
        pass

    definition = PromptAgentDefinition(
        model=model_deployment,
        instructions=FOUNDRY_AGENT_INSTRUCTIONS,
        tools=[expected_tool],
    )
    client.agents.create_version(agent_name=FOUNDRY_AGENT_NAME, definition=definition)


def _extract_foundry_iq_matches(response: Any, index_name: str) -> dict[str, Any]:
    """Pull the Foundry IQ knowledge base references out of the agent response."""
    matches: list[dict[str, Any]] = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) != "mcp_call":
            continue
        if getattr(item, "name", None) != "knowledge_base_retrieve":
            continue
        try:
            payload = json.loads(item.output)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        for reference in payload.get("references", []):
            if reference.get("type") != "searchIndex":
                continue
            source = reference.get("sourceData") or {}
            matches.append(
                {
                    "id": reference.get("docKey") or source.get("id", "unknown"),
                    "content": source.get("content", ""),
                }
            )

    return {"index_name": index_name, "match_count": len(matches), "matches": matches}


def _extract_indexed_claim(content: str) -> dict[str, Any]:
    """Convert an indexed accident statement into the intake annotation shape."""
    def field(label: str) -> str | None:
        match = re.search(rf"^{re.escape(label)}:\s*(.+)$", content, re.MULTILINE)
        return match.group(1).strip() if match else None

    incident_match = re.search(
        r"## Description of Incident\s*\n+(.*?)(?=\n(?:## |[^\n]+\.jpeg\s*$)|\Z)",
        content,
        re.DOTALL | re.MULTILINE,
    )
    incident_description = (
        incident_match.group(1).strip() if incident_match else content.strip()
    )
    vehicle_parts = (field("Year/Make/Model") or "").split(maxsplit=2)

    return {
        "claimant_name": field("Name") or "Unknown",
        "claim_date": field("Date of Incident"),
        "policy_number": field("Policy Number"),
        "incident_description": incident_description,
        "vehicle_info": {
            "year": vehicle_parts[0] if vehicle_parts else None,
            "make": vehicle_parts[1] if len(vehicle_parts) > 1 else None,
            "model": vehicle_parts[2] if len(vehicle_parts) > 2 else None,
            "license_plate": field("License Plate"),
            "vin": field("VIN"),
        },
        "damage_description": incident_description,
        "estimated_damage_amount": None,
        "witnesses": [],
        "signature_present": None,
        "date_signed": None,
    }


def run_indexed_claim_intake(claim_reference: str) -> dict[str, Any]:
    """Retrieve an existing front statement from Foundry IQ without rerunning OCR."""
    project_endpoint = os.getenv("AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
    if not project_endpoint:
        raise RuntimeError("AI_FOUNDRY_PROJECT_ENDPOINT is not set. Complete Task 1 first.")

    normalized_reference = claim_reference.removesuffix(".jpeg")
    statement_id = (
        normalized_reference
        if normalized_reference.endswith("_front")
        else f"{normalized_reference}_front"
    )
    source_file = f"{statement_id}.jpeg"
    index_name = os.getenv("FOUNDRY_IQ_SEARCH_INDEX_NAME", "crash-statements")
    model_deployment = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-5.4")
    client = AIProjectClient(
        endpoint=project_endpoint,
        credential=DefaultAzureCredential(process_timeout=30),
        allow_preview=True,
    )
    _ensure_foundry_agent(client, model_deployment)

    response = client.get_openai_client(agent_name=FOUNDRY_AGENT_NAME).responses.create(
        model=model_deployment,
        input=(
            "INDEXED_STATEMENT_TASK\nSearch for the exact quoted source filename "
            f'"{source_file}" without adding other terms. Summarize the matching statement.'
        ),
    )
    foundry_iq = _extract_foundry_iq_matches(response, index_name)
    exact_match = next(
        (match for match in foundry_iq["matches"] if match["id"] == statement_id),
        None,
    )
    if exact_match is None:
        raise RuntimeError(
            f"Foundry IQ did not return indexed statement '{statement_id}'."
        )

    return {
        "status": "success",
        "input_mode": "foundry_iq",
        "claim_reference": claim_reference,
        "processed_at_utc": datetime.now(timezone.utc).isoformat(),
        "ocr": None,
        "extracted_data": _extract_indexed_claim(exact_match["content"]),
        "foundry_iq": foundry_iq,
        "foundry_agent": {"name": FOUNDRY_AGENT_NAME},
        "agent_summary": response.output_text,
    }


def run_claims_intake(image_path: Path) -> dict[str, Any]:
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    ocr = run_mistral_ocr(image_path)

    project_endpoint = os.getenv("AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
    if not project_endpoint:
        raise RuntimeError("AI_FOUNDRY_PROJECT_ENDPOINT is not set. Complete Task 1 first.")

    index_name = os.getenv("FOUNDRY_IQ_SEARCH_INDEX_NAME", "crash-statements")
    model_deployment = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-5.4")

    client = AIProjectClient(
        endpoint=project_endpoint,
        credential=DefaultAzureCredential(process_timeout=30),
        allow_preview=True,
    )
    _ensure_foundry_agent(client, model_deployment)

    openai_client = client.get_openai_client(agent_name=FOUNDRY_AGENT_NAME)
    response = openai_client.responses.create(
        model=model_deployment,
        input=f"New OCR statement:\n{ocr.get('text', '')}",
    )

    return {
        "status": "success",
        "image_path": str(image_path),
        "processed_at_utc": datetime.now(timezone.utc).isoformat(),
        "ocr": ocr,
        "extracted_data": ocr.get("document_annotation"),
        "foundry_iq": _extract_foundry_iq_matches(response, index_name),
        "foundry_agent": {"name": FOUNDRY_AGENT_NAME},
        "agent_summary": response.output_text,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run claims intake OCR + Foundry IQ retrieval")
    parser.add_argument("image_path", help="Path to the claim image or PDF")
    parser.add_argument(
        "--output",
        default="",
        help="Optional output JSON path. Defaults to next to input file with .intake.json suffix",
    )
    args = parser.parse_args()

    image_path = Path(args.image_path).expanduser().resolve()
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else image_path.with_suffix(".intake.json")
    )

    result = run_claims_intake(image_path)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(json.dumps(result, indent=2))
    print(f"\nSaved intake output to: {output_path}")


if __name__ == "__main__":
    main()
