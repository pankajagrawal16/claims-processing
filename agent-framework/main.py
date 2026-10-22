"""Host the claims workflow as a Foundry Responses endpoint."""

import os
from pathlib import Path

from agent_framework_foundry_hosting import (
    CheckpointStoreProvider,
    HostedResponseRequest,
    ResponsesHostServer,
    WorkflowTurn,
)
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from workflow import build_workflow  # noqa: E402  (after env is loaded)

credential = DefaultAzureCredential()


def create_workflow(_request: HostedResponseRequest):
    return build_workflow(credential=credential)


def ignore_caller_options(_request: HostedResponseRequest, _options: dict) -> dict:
    # Playgrounds send options such as tools=[]; the hosted agents are configured in Foundry.
    return {}


async def parse_response(request: HostedResponseRequest) -> WorkflowTurn[str]:
    items = await request.get_input_items()
    if any(item.get("type") == "function_call_output" for item in items):
        return WorkflowTurn(responses=await request.get_workflow_responses())
    return WorkflowTurn(input=await request.get_input_text())


if __name__ == "__main__":
    ResponsesHostServer(
        workflow=create_workflow,
        parse_response=parse_response,
        prepare_options=ignore_caller_options,
        checkpoint_store_provider=CheckpointStoreProvider(),
    ).run(port=int(os.getenv("PORT", "8088")))

# LangChain/LangGraph alternative (illustrative; leave commented for this lab).
# Use a separate environment with langchain-azure-ai[hosting]>=1.2.9 and your app's dependencies.
# Replace the active server call above with this pattern, using your existing compiled graph
# (for example, the graph returned by LangChain's create_agent). The import below is a placeholder.
#
# from langchain_azure_ai.agents.hosting import ResponsesHostServer as LangGraphResponsesHostServer
# from your_langgraph_app import graph
#
# LangGraphResponsesHostServer(graph).run(port=int(os.getenv("PORT", "8088")))
#
# Same /responses API pattern, different framework adapter.
# This exposes your LangGraph app, not an automatic conversion of this claims workflow.
# LangGraph interrupt/resume payloads differ from this lab's request_info review flow.
# https://learn.microsoft.com/azure/foundry/how-to/develop/langchain-hosted-agents
