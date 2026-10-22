"""Repair a Foundry IQ RemoteTool connection's MCP URL."""

import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from azure.ai.projects import AIProjectClient
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

CRASH_STATEMENTS_KNOWLEDGE_BASE_NAME = "crash-statements-kb"
POLICIES_KNOWLEDGE_BASE_NAME = "policies-kb"
CONNECTION_NAME_ENV = {
    CRASH_STATEMENTS_KNOWLEDGE_BASE_NAME: "FOUNDRY_IQ_CRASH_STATEMENTS_CONNECTION_NAME",
    POLICIES_KNOWLEDGE_BASE_NAME: "FOUNDRY_IQ_POLICIES_CONNECTION_NAME",
}
MCP_API_VERSION = "2026-08-01-preview"
ARM_API_VERSION = "2025-10-01-preview"
CONNECTION_ID_PATTERN = re.compile(
    r"/subscriptions/[^/]+/resourceGroups/[^/]+/providers/"
    r"Microsoft\.CognitiveServices/accounts/[^/]+/projects/[^/]+/connections/[^/]+",
    re.IGNORECASE,
)


def _expected_url(knowledge_base_name: str = CRASH_STATEMENTS_KNOWLEDGE_BASE_NAME) -> str:
    if knowledge_base_name not in CONNECTION_NAME_ENV:
        raise ValueError(f"Unsupported knowledge base: {knowledge_base_name}")
    version = os.getenv("FOUNDRY_IQ_MCP_API_VERSION", MCP_API_VERSION)
    if version != MCP_API_VERSION:
        raise RuntimeError(
            f"FOUNDRY_IQ_MCP_API_VERSION is '{version}'. Set it to {MCP_API_VERSION} "
            "or remove the override before repairing this lab's connection."
        )
    endpoint = os.getenv("FOUNDRY_IQ_SEARCH_ENDPOINT") or os.getenv("SEARCH_SERVICE_ENDPOINT", "")
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path not in {"", "/"}:
        raise RuntimeError("Set FOUNDRY_IQ_SEARCH_ENDPOINT to the HTTPS Search service URL in .env.")
    return (
        f"{endpoint.rstrip('/')}/knowledgebases/{knowledge_base_name}"
        f"/mcp?api-version={MCP_API_VERSION}"
    )


def _find_connection(
    client: AIProjectClient,
    expected_url: str,
    knowledge_base_name: str = CRASH_STATEMENTS_KNOWLEDGE_BASE_NAME,
):
    expected_name = os.getenv(CONNECTION_NAME_ENV[knowledge_base_name], "")
    expected_path = urlparse(expected_url).path
    connections = [
        connection
        for connection in client.connections.list()
        if getattr(connection.type, "value", connection.type) in {"RemoteTool", "RemoteTool_Preview"}
        and (
            connection.name == expected_name
            if expected_name
            else urlparse(connection.target or "").path == expected_path
        )
    ]
    if len(connections) != 1:
        raise RuntimeError(
            f"Expected one Foundry RemoteTool connection for {knowledge_base_name}; "
            f"found {len(connections)}. Check the project's Connected resources."
        )
    connection = connections[0]
    if urlparse(connection.target).hostname != urlparse(expected_url).hostname:
        raise RuntimeError("The connection targets a different Search service. No changes made.")
    if not CONNECTION_ID_PATTERN.fullmatch(connection.id) or connection.id.rsplit("/", 1)[-1] != connection.name:
        raise RuntimeError("The connection does not have an expected Foundry project ARM resource ID.")
    return connection


def _refresh_policies_agent(
    client: AIProjectClient,
    expected_url: str,
    connection_id: str,
    connection_modified_at: str | None,
    changed: bool,
) -> None:
    try:
        versions = list(client.agents.list_versions("claims-intelligence-agent"))
    except ResourceNotFoundError:
        return
    if not versions:
        return
    latest = max(versions, key=lambda version: int(version.version))
    policy_tool = next(
        (tool for tool in latest.definition.tools if getattr(tool, "server_label", None) == "policies-knowledge-base"),
        None,
    )
    if (
        policy_tool is None
        or policy_tool.server_url != expected_url
        or policy_tool.project_connection_id != connection_id
    ):
        print("Run python claims-intelligence-agent.py --setup-agent to update the agent's MCP tool.")
        return
    modified_at = datetime.fromisoformat(connection_modified_at) if connection_modified_at else None
    if changed or (modified_at is not None and latest.created_at < modified_at):
        version = client.agents.create_version(
            agent_name="claims-intelligence-agent", definition=latest.definition
        )
        print(f"Refreshed claims-intelligence-agent version {version.version} to use the updated connection.")


def repair_connection(knowledge_base_name: str = CRASH_STATEMENTS_KNOWLEDGE_BASE_NAME) -> None:
    project_endpoint = os.getenv("AI_FOUNDRY_PROJECT_ENDPOINT", "")
    if not project_endpoint:
        raise RuntimeError("Set AI_FOUNDRY_PROJECT_ENDPOINT in the repository-root .env.")
    expected_url = _expected_url(knowledge_base_name)

    with DefaultAzureCredential(process_timeout=30) as credential:
        with AIProjectClient(endpoint=project_endpoint, credential=credential, allow_preview=True) as client:
            connection = _find_connection(client, expected_url, knowledge_base_name)

        arm_url = f"https://management.azure.com{connection.id}?api-version={ARM_API_VERSION}"
        token = credential.get_token("https://management.azure.com/.default")
        changed = False
        with httpx.Client(headers={"Authorization": f"Bearer {token.token}"}, timeout=30) as http:
            response = http.get(arm_url)
            response.raise_for_status()
            resource = response.json()
            properties = resource["properties"]
            if properties["target"] != connection.target:
                raise RuntimeError("The connection changed since it was listed. Retry without modifying it.")
            if (
                properties["authType"] != "ProjectManagedIdentity"
                or properties["category"] != "RemoteTool"
                or properties.get("audience") != "https://search.azure.com/"
            ):
                raise RuntimeError("The connection is not a Search RemoteTool using project managed identity.")
            if properties["target"] != expected_url:
                headers = {"If-Match": resource["etag"]} if resource.get("etag") else {}
                response = http.patch(
                    arm_url,
                    headers=headers,
                    json={
                        "properties": {
                            "authType": properties["authType"],
                            "category": properties["category"],
                            "audience": properties["audience"],
                            "target": expected_url,
                        }
                    },
                )
                response.raise_for_status()
                updated = response.json()
                if (
                    updated["properties"]["target"] != expected_url
                    or updated["properties"]["authType"] != "ProjectManagedIdentity"
                ):
                    raise RuntimeError("Connection update did not return the expected target and authentication.")
                changed = True
                print(f"Updated {connection.name} to {expected_url}.")
                resource = updated
            else:
                print(f"Connection already targets {expected_url}; no changes made.")

        if knowledge_base_name == POLICIES_KNOWLEDGE_BASE_NAME:
            with AIProjectClient(endpoint=project_endpoint, credential=credential, allow_preview=True) as client:
                _refresh_policies_agent(
                    client,
                    expected_url,
                    connection.id,
                    resource.get("systemData", {}).get("lastModifiedAt"),
                    changed,
                )
        print("Rerun the agent to verify retrieval.")


if __name__ == "__main__":
    repair_connection()
