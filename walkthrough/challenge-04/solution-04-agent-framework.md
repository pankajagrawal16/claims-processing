---
title: "Solution 04: Build the Claims Workflow with Agent Framework"
description: "Solution walkthrough for running the two-agent claims workflow with Agent Framework and deploying it as a hosted agent"
---

[Home](../../README.md) | [Challenge 04](../../challenges/challenge-04-agent-framework.md) | [Next solution](../challenge-05/solution-05.md)

## Outcome

This solution connects the intake and intelligence agents as an Agent Framework graph.
It retrieves an indexed statement, retrieves the selected policy, and evaluates coverage.
Escalated or low-confidence decisions pause for human review until a reviewer answers.
Optionally, it deploys the workflow as a hosted Foundry agent.

## Prerequisites

* Complete Challenges 02 and 03 and confirm that both Foundry agents exist
* Use the same Python environment as the other challenges (`uv sync`)
* Use an interactive terminal in case human review is requested

If you are starting here on a clean machine or after deleting your local setup,
follow [Starting directly at Challenge 4](../../challenges/challenge-04-agent-framework.md#starting-directly-at-challenge-4)
first. It covers the Azure prerequisites from Challenges 1-3, the workshop folder,
dependency installation, environment activation, Azure login, and restoring `.env`.
You do not need the optional hosting environment to run the local solution below.

## Run the solution locally

From the repository root, run the covered
comprehensive policy case:

```bash
cd docs
python claims-framework-workflow.py ../data/claims/crash1/raw/statements/crash1_front.jpeg \
  --policy COMP-AUTO-001
```

Run the default liability-only case:

```bash
python claims-framework-workflow.py ../data/claims/crash1/raw/statements/crash1_front.jpeg
```

Exercise a different policy and claim amount:

```bash
python claims-framework-workflow.py ../data/claims/crash1/raw/statements/crash1_front.jpeg \
  --policy COMM-AUTO-001 --claim-id CLM-2026-007 --amount 28000
```

If the intelligence agent escalates or its confidence is below the threshold, enter
`approve`, `escalate`, or `deny` at the prompt. An optional comment can follow the answer.

## Deploy as a hosted agent (optional)

Return from `docs/` to the **workshop folder**
the repository root with `cd ..`.
Choose **one** package method in
[Challenge 4, Task 5](../../challenges/challenge-04-agent-framework.md#task-5-deploy-the-workflow-as-a-hosted-agent)
and follow only its tab. The tab contains the exact Bash/zsh and PowerShell commands.

=== "Container"

    Keep `azure.yaml` unchanged; ACR remotely builds the supplied Python 3.11 Dockerfile.
    An Azure Container Registry is required (billable).

    * **Foundry Toolkit:** run **Foundry Toolkit: Deploy Hosted Agent**, select your existing
      Foundry project, and choose **Container**. The source directory is `agent-framework/`.
    * **Azure Developer CLI:** select your Foundry project's subscription (`az account set`),
      activate the `agent-framework` environment, then run `azd ext install azure.ai.agents`,
      `azd auth login`, `azd env new claims-framework`, and `python docs/configure_azd_env.py`.
      The helper sets the project ID, subscription, resource group, region, and endpoint in
      `azd`; it does **not** copy secrets from `.env`.
    * Create or select an ACR, set `AZURE_CONTAINER_REGISTRY_ENDPOINT` to its `loginServer`,
      then run `azd deploy claims-workflow-hosted`. If the deploy reports an image
      authentication error, grant the Foundry project's managed identity `AcrPull` on the ACR.
      Use the commands in the
      [Container tab](../../challenges/challenge-04-agent-framework.md#choose-the-package-container-or-code-zip).

=== "Code ZIP"

    Use Task 5's `codeConfiguration` service example and review `agent-framework/.agentignore`.
    Foundry builds the uploaded source using Python 3.13; verify compatibility first.
    No Dockerfile or ACR is needed for this path.

    * **Foundry Toolkit:** run **Foundry Toolkit: Deploy Hosted Agent**, select your existing
      Foundry project, and choose **Code** with **Remote** package mode and Python 3.13.
      The source directory is `agent-framework/`.
    * **Azure Developer CLI:** select your Foundry project's subscription (`az account set`),
      activate the `agent-framework` environment, then run `azd ext install azure.ai.agents`,
      `azd auth login`, `azd env new claims-framework`, `python docs/configure_azd_env.py`, and
      `azd deploy claims-workflow-hosted`. The helper does **not** copy secrets from `.env`.

Wait for the new agent version to become active before invoking it.

If an agent-to-agent call fails with a permissions error, assign **Foundry User**
on the project to the **hosted agent identity**. If the project's managed
identity lacks model inference access, grant it **Foundry User** on the parent
Foundry account. Follow the portal steps or OS-specific commands in
[Give the agent access to your project](../../challenges/challenge-04-agent-framework.md#give-the-agent-access-to-your-project).
An `Agent ... with version ... not found` error is a version mismatch, not
an RBAC failure; redeploy the updated workflow code.

Then call the hosted agent with the same inputs:

```bash
cd docs
python invoke-hosted-claims-workflow.py --agent-name ClaimProcessingWorkflow --indexed-claim crash3 --policy COMP-AUTO-001
```

If the hosted agent was deployed under another name, replace `ClaimProcessingWorkflow`
in `--agent-name` with its exact Foundry agent name (the service's `name:` value,
not the `services:` key).

## Continue to Challenge 5

Continue to the [Challenge 5 observability and evaluation exercises](../../challenges/challenge-05.md).

## Continue to Challenge 6 (FIDES)

After Challenge 5, run the FIDES security exercise with the framework workflow:

```bash
python claims-security-hardening.py ../data/claims/crash1/raw/statements/crash1_front.jpeg \
  --scenario inject-payout --workflow framework
```

## Expected result

The console displays Steps 1 and 2 in order and prints an `APPROVED`, `DENIED`, or
`ESCALATED` result with `policy_info` and `coverage_decision`. Step 3 appears only when
human review is required. The hosted agent returns the same decision, or a pending review
request that the script answers.

## Troubleshooting

* `Foundry hosted requests require a trusted user ID and call ID`: the deployed agent uses
  an old protocol version. Redeploy with `azure.yaml` declaring `responses` `2.0.0`
* `No policy number found`: the statement is not indexed. Complete Challenge 2 or pass
  `--policy`
* A build error about `requirements.txt`: deploy from
  the repository root, with `agent-framework/` as the source directory
* If a human-review prompt fails in automation, rerun in an interactive terminal

## Validation checklist

* [ ] The two agents run in the documented order
* [ ] The workflow reuses the existing Foundry agents and creates none
* [ ] The result includes the requested claim ID, policy, coverage reasoning, approved amount, and final status
* [ ] The liability-only execution is denied
* [ ] A requested review waits for a valid answer and asks again after an invalid one
* [ ] Challenge 6 runs with `--workflow framework`
* [ ] (Optional) The hosted agent returns the same decision

Continue with [Challenge 5](../../challenges/challenge-05.md), then [Challenge 6](../../challenges/challenge-06.md).
