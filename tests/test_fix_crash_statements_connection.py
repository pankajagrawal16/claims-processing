import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "docs" / "fix_crash_statements_connection.py"
SPEC = importlib.util.spec_from_file_location("fix_crash_statements_connection", SCRIPT)
repair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair)

SEARCH_URL = "https://example.search.windows.net"
EXPECTED_URL = f"{SEARCH_URL}/knowledgebases/crash-statements-kb/mcp?api-version=2026-08-01-preview"
STALE_URL = EXPECTED_URL.replace("2026-08-01-preview", "2026-04-01")
CONNECTION_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.CognitiveServices/"
    "accounts/account/projects/project/connections/account-crash-statements-kb"
)


class Context:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, *_):
        return False


def _connection(target=STALE_URL):
    return SimpleNamespace(
        type="RemoteTool",
        target=target,
        name="account-crash-statements-kb",
        id=CONNECTION_ID,
    )


def test_expected_url_requires_supported_version_and_search_endpoint(monkeypatch):
    monkeypatch.setenv("FOUNDRY_IQ_SEARCH_ENDPOINT", SEARCH_URL)
    monkeypatch.delenv("FOUNDRY_IQ_MCP_API_VERSION", raising=False)
    assert repair._expected_url() == EXPECTED_URL
    assert repair._expected_url("policies-kb") == EXPECTED_URL.replace("crash-statements-kb", "policies-kb")

    monkeypatch.setenv("FOUNDRY_IQ_MCP_API_VERSION", "2026-04-01")
    with pytest.raises(RuntimeError, match="remove the override"):
        repair._expected_url()


def test_find_connection_rejects_other_search_services_and_ambiguity(monkeypatch):
    monkeypatch.delenv("FOUNDRY_IQ_CRASH_STATEMENTS_CONNECTION_NAME", raising=False)
    client = SimpleNamespace(connections=SimpleNamespace(list=lambda: [_connection()]))
    assert repair._find_connection(client, EXPECTED_URL).id == CONNECTION_ID
    client.connections.list = lambda: [_connection(STALE_URL.replace("example", "other"))]
    with pytest.raises(RuntimeError, match="different Search service"):
        repair._find_connection(client, EXPECTED_URL)
    client.connections.list = lambda: [_connection(), _connection()]
    with pytest.raises(RuntimeError, match="found 2"):
        repair._find_connection(client, EXPECTED_URL)
    client.connections.list = list
    with pytest.raises(RuntimeError, match="found 0"):
        repair._find_connection(client, EXPECTED_URL)


@pytest.mark.parametrize(
    ("target", "auth_type", "patch_count"),
    [(STALE_URL, "ProjectManagedIdentity", 1), (EXPECTED_URL, "ProjectManagedIdentity", 0), (STALE_URL, "ApiKey", 0)],
)
def test_repair_only_updates_stale_managed_identity_connection(
    monkeypatch, target, auth_type, patch_count
):
    monkeypatch.setenv("AI_FOUNDRY_PROJECT_ENDPOINT", "https://account.services.ai.azure.com/api/projects/project")
    monkeypatch.setenv("FOUNDRY_IQ_SEARCH_ENDPOINT", SEARCH_URL)
    monkeypatch.delenv("FOUNDRY_IQ_MCP_API_VERSION", raising=False)
    monkeypatch.delenv("FOUNDRY_IQ_CRASH_STATEMENTS_CONNECTION_NAME", raising=False)
    connection = _connection(target)
    project = SimpleNamespace(connections=SimpleNamespace(list=lambda: [connection]))
    credential = SimpleNamespace(get_token=lambda _: SimpleNamespace(token="test-token"))
    monkeypatch.setattr(repair, "DefaultAzureCredential", lambda **_: Context(credential))
    monkeypatch.setattr(repair, "AIProjectClient", lambda **_: Context(project))

    requests = []

    def respond(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "etag": "etag-1",
                    "properties": {
                        "target": target,
                        "authType": auth_type,
                        "category": "RemoteTool",
                        "audience": "https://search.azure.com/",
                    },
                },
            )
        return httpx.Response(
            200,
            json={"properties": {"target": EXPECTED_URL, "authType": "ProjectManagedIdentity"}},
        )

    httpx_client = httpx.Client
    monkeypatch.setattr(
        repair.httpx,
        "Client",
        lambda **kwargs: httpx_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    if auth_type == "ApiKey":
        with pytest.raises(RuntimeError, match="project managed identity"):
            repair.repair_connection()
    else:
        repair.repair_connection()
    patches = [request for request in requests if request.method == "PATCH"]
    assert len(patches) == patch_count
    if patches:
        assert patches[0].headers["if-match"] == "etag-1"
        assert patches[0].headers["authorization"] == "Bearer test-token"
        assert patches[0].read().decode().count(EXPECTED_URL) == 1


def test_policies_connection_refreshes_older_agent_binding(monkeypatch):
    monkeypatch.setenv("AI_FOUNDRY_PROJECT_ENDPOINT", "https://account.services.ai.azure.com/api/projects/project")
    monkeypatch.setenv("FOUNDRY_IQ_SEARCH_ENDPOINT", SEARCH_URL)
    monkeypatch.delenv("FOUNDRY_IQ_MCP_API_VERSION", raising=False)
    monkeypatch.delenv("FOUNDRY_IQ_POLICIES_CONNECTION_NAME", raising=False)
    policy_url = EXPECTED_URL.replace("crash-statements-kb", "policies-kb")
    connection = _connection(policy_url)
    connection.name = "account-policies-kb"
    connection.id = CONNECTION_ID.replace("crash-statements-kb", "policies-kb")
    versions_created = []
    latest = SimpleNamespace(
        version="1",
        created_at=datetime(2026, 10, 22, 9, 30, tzinfo=UTC),
        definition=SimpleNamespace(
            tools=[
                SimpleNamespace(
                    server_label="policies-knowledge-base",
                    server_url=policy_url,
                    project_connection_id=connection.id,
                )
            ]
        ),
    )
    project = SimpleNamespace(
        connections=SimpleNamespace(list=lambda: [connection]),
        agents=SimpleNamespace(
            list_versions=lambda _: [latest],
            create_version=lambda **kwargs: versions_created.append(kwargs) or SimpleNamespace(version="2"),
        ),
    )
    credential = SimpleNamespace(get_token=lambda _: SimpleNamespace(token="test-token"))
    monkeypatch.setattr(repair, "DefaultAzureCredential", lambda **_: Context(credential))
    monkeypatch.setattr(repair, "AIProjectClient", lambda **_: Context(project))

    def respond(request):
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "properties": {
                    "target": policy_url,
                    "authType": "ProjectManagedIdentity",
                    "category": "RemoteTool",
                    "audience": "https://search.azure.com/",
                },
                "systemData": {"lastModifiedAt": "2026-10-22T09:35:00Z"},
            },
        )

    httpx_client = httpx.Client
    monkeypatch.setattr(
        repair.httpx,
        "Client",
        lambda **kwargs: httpx_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    repair.repair_connection("policies-kb")
    assert len(versions_created) == 1
    assert versions_created[0]["definition"] is latest.definition

    latest.created_at = datetime(2026, 10, 22, 9, 40, tzinfo=UTC)
    repair.repair_connection("policies-kb")
    assert len(versions_created) == 1
