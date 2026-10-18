"""Host the claims workflow as a Foundry Responses endpoint."""

import os
from pathlib import Path

from agent_framework_foundry_hosting import ResponsesHostServer
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from workflow import build_workflow  # noqa: E402  (after env is loaded)

if __name__ == "__main__":
    ResponsesHostServer(build_workflow().as_agent(name="claims-workflow")).run(port=int(os.getenv("PORT", "8088")))

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
# Same /responses API pattern, different framework adapter; no .as_agent() is needed here.
# This exposes your LangGraph app, not an automatic conversion of this claims workflow.
# LangGraph interrupt/resume payloads differ from this lab's request_info review flow.
# https://learn.microsoft.com/azure/foundry/how-to/develop/langchain-hosted-agents
