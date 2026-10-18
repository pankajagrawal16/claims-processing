# Claims Workflow (Agent Framework)

The code behind [Challenge 4: the Agent Framework workflow](../challenges/challenge-04-agent-framework.md): a workflow of nodes and edges over the two existing Foundry agents (`claims-intake-agent`, `claims-intelligence-agent`). The lab instructions are in that page; this file is a quick reference for the code.

Starting with a clean checkout or no local environment? Follow
[Starting directly at Challenge 4](../challenges/challenge-04-agent-framework.md#starting-directly-at-challenge-4)
for the earlier Azure prerequisites and workshop environment setup before using this hosting folder.

**Folder conventions:** the **workshop root** is
the repository root, which contains `azure.yaml`,
`pyproject.toml`, and `docs/`. **This hosting folder** is its
`agent-framework/` subfolder. 

| File | Purpose |
|---|---|
| `workflow.py` | The workflow: nodes, edges, input parsing, result building |
| `main.py` | Hosting entry point: loads the workshop-root `.env` and uses `ResponsesHostServer` to expose the workflow over the Responses API, locally or hosted |
| `tests/` | Offline tests with fake agents |
| `Dockerfile`, `requirements.txt` | Container for the hosted agent |
| `.agentignore` | Excludes secrets, local environments, caches, and tests from code ZIP uploads |
| `../azure.yaml` | Hosted agent definition used by `azd` and the Foundry Toolkit |
| `../docs/claims-framework-workflow.py` | Command-line runner for a claim request and any human-review response |
| `../docs/invoke-hosted-claims-workflow.py` | Calls the hosted (or local) workflow and answers review requests |

## Input

Supply an image path or an indexed statement reference, with optional policy, claim ID,
and claimed amount:

```text
<image path> | --indexed-claim crash3   [--policy COMP-AUTO-001] [--claim-id CLM-2026-007] [--amount 28000]
```

Defaults: `--claim-id CLM-2026-001`, `--amount 15000`. The policy comes from the intake result unless `--policy` is given. Only an image's file name is used, to find its indexed statement.

## Develop and test

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                      # offline
python main.py              # http://localhost:8088/responses (needs az login)
```

`ResponsesHostServer` (from `agent-framework-foundry-hosting`) is the HTTP/protocol
adapter, not the workflow engine. `build_workflow().as_agent(...)` adapts the graph
to an agent interface; the server accepts Responses API requests and returns workflow
outputs, including function-call requests for human review. This lets Agent Inspector
and API clients invoke the graph without importing Python code. The hosted container
runs the same entry point, using the `responses` protocol configured in `azure.yaml`.
Starting it locally does not register or deploy a Foundry agent.

The commented example in [`main.py`](./main.py) shows the corresponding
LangChain/LangGraph hosting adapter for an existing compiled graph. It is illustrative;
no LangChain dependencies or runtime behavior are added to this lab.

For VS Code testing, connect Foundry Toolkit Agent Inspector to the running server.
Without VS Code, open a second terminal at the workshop root and run:

```bash
source agent-framework/.venv/bin/activate
python docs/invoke-hosted-claims-workflow.py --local --indexed-claim crash3 --policy COMP-AUTO-001
```

The script starts a new claim run, prompts for any required human review, and sends
the answer through the Responses API. It does not resume an existing Inspector run.
See [Challenge 4, Task 4](../challenges/challenge-04-agent-framework.md#task-4-test-and-debug-with-the-foundry-toolkit-agent-inspector-optional)
for both local testing paths, PowerShell commands, tracing, and forcing human review.
F5 requires a local VS Code launch configuration; one is not included in this sample.

Environment variables (all optional except the endpoint, which the workshop-root `.env` provides locally and Foundry provides when hosted):

| Variable | Default |
|---|---|
| `FOUNDRY_PROJECT_ENDPOINT` | from `.env` locally, injected when hosted |
| `CLAIMS_INTAKE_AGENT_NAME` | `claims-intake-agent` |
| `CLAIMS_INTELLIGENCE_AGENT_NAME` | `claims-intelligence-agent` |
| `HUMAN_REVIEW_CONFIDENCE_THRESHOLD` | `0.9` |

Set the threshold to `1.01` to force the human-review branch.

## Challenge 5: trace the CLI workflow

From the workshop root, run `uv sync --extra tracing` and activate the workshop `.venv`.
Set `APPLICATIONINSIGHTS_CONNECTION_STRING` in the workshop `.env` to the connected
Application Insights resource's connection string, then run:

```bash
python docs/claims-framework-workflow.py --indexed-claim crash3 --policy COMP-AUTO-001 --trace
```

The CLI prints a trace ID and exports a `claims.process` root with Agent Framework
workflow/executor/agent spans. Message content stays off unless `--trace-content` is
also supplied for synthetic-data debugging. This setup is CLI-only: `ResponsesHostServer`
already owns provider initialization for local/hosted HTTP execution. See
[Challenge 5, Task 1](../challenges/challenge-05.md#task-1-connect-application-insights-and-read-a-trace)
for inspection, privacy, and hosted configuration.

## Container

From this folder:

```bash
docker build --platform linux/amd64 -t claims-workflow .
# Override the Dockerfile's PIP_INDEX_URL build argument if your environment needs a different package index.
```

The container has no `az login`; pass a service principal (`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_SECRET`) and `FOUNDRY_PROJECT_ENDPOINT`, or test with `python main.py`.

## Deploy

Run from the **workshop root**,
the repository root, where `azure.yaml` is.
If you are in `agent-framework/`, run `cd ..` first.

Choose a package method before deploying:

* **Container:** keep `azure.yaml` unchanged. The supplied Dockerfile uses Python 3.11;
  ACR builds it remotely. Provision supporting resources if this environment needs them.
* **Code ZIP:** use the service block in
  [Challenge 4, Task 5](../challenges/challenge-04-agent-framework.md#task-5-deploy-the-workflow-as-a-hosted-agent).
  It sets `language: python` and `codeConfiguration` with `python_3_13`, `main.py`,
  and `remote_build`, instead of a `docker` block. Foundry restores `requirements.txt`;
  no Dockerfile or ACR is needed. Verify Python 3.13 compatibility first; the local
  Python 3.11 environment is not uploaded. Review `.agentignore` before packaging.

After signing in and setting the target environment as described in Task 5:

```bash
azd deploy claims-workflow-hosted
```

For a container environment that needs ACR, run `azd provision` before deployment.
Alternatively, use **Foundry Toolkit: Deploy Hosted Agent** and select **Container** or
**Code / Remote** to match the service configuration. Both methods deploy the same
`main.py` Responses server and workflow, and create a new agent version.

See the [full deployment instructions](../challenges/challenge-04-agent-framework.md#task-5-deploy-the-workflow-as-a-hosted-agent)
for subscription/region settings, prerequisites, and permissions. Provisioning can create
supporting resources such as a container registry; review the target environment first.

The hosted agent's identity may need the **Foundry User** role on the project to call the two prompt agents.

## Human review when hosted

When review is needed, the response contains a `request_info` function call instead of a final decision. Send the reviewer's answer back as a `function_call_output` with the same `call_id` and `previous_response_id`. `docs/invoke-hosted-claims-workflow.py` does this.
