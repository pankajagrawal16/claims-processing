---
title: ClaimSight Claims MicroHack
description: A guided, hands-on workshop for building a grounded, observable, and secure claims-processing workflow.
---

# Build a claims-processing workflow, one challenge at a time

Welcome to the ClaimSight Claims MicroHack. You'll build and explore a claims
workflow that reads accident statements, retrieves policy evidence, coordinates
specialist agents, routes uncertain decisions to human review, and protects sensitive
actions.

The workshop is designed to be completed in order. You can choose **Bash/zsh** or
**PowerShell** in the command tabs; choosing a tab updates matching command tabs
throughout the site.

## Your path through the workshop

1. **Get your environment ready.** Confirm the lab accounts and Azure resources, open
   the Codespace, and configure your local environment in
   [Challenge 1: Prepare the Environment](challenges/challenge-01.md).
2. **Build the claims workflow.** Work through Challenges 2–4 to extract claim
   details, retrieve policy evidence, and compose the agents into a workflow.
3. **Make it observable and secure.** Trace and evaluate decisions in
   [Challenge 5](challenges/challenge-05.md), then test deterministic security
   controls in [Challenge 6](challenges/challenge-06.md).
4. **Understand the design.** Review the architecture diagram below before you start.

!!! important "Before you begin"

    This is a hands-on lab. You need the assigned lab account, a provisioned Azure
    environment, and the repository's **Claims Hack** development container. Start
    with Challenge 1; it explains the prerequisites and setup.

## Choose your first challenge

| Challenge | What you'll do | Time |
| --- | --- | ---: |
| [1. Prepare the environment](challenges/challenge-01.md) | Verify your lab access, start the Codespace, and configure your tools. | 30 min |
| [2. Build the Claims Intake Agent](challenges/challenge-02.md) | Extract accident statements and find related evidence. | 45 min |
| [3. Build the Claims Intelligence Agent](challenges/challenge-03.md) | Ground coverage decisions in retrieved insurance policies. | 30 min |
| [4. Build the Agent Framework workflow](challenges/challenge-04-agent-framework.md) | Compose the agents and support conditional human review. | 45 min |
| [5. Observe and evaluate](challenges/challenge-05.md) | Trace runs, score decisions, and measure guardrails. | 90 min |
| [6. Harden the claims pipeline](challenges/challenge-06.md) | Defend sensitive actions against prompt injection. | 60 min |

Challenge 4's Agent Framework workflow is the recommended path. The
[sequential workflow](challenges/challenge-04.md) remains available as an
alternative. Challenge 5's optional hosted-agent exercises require a deployment and
may incur Azure charges.

## Where to run commands

Unless a challenge says otherwise, run commands from the **workshop root**: the folder
containing `pyproject.toml`, `azure.yaml`, `docs/`, `challenges/`, and
`agent-framework/`. Some tasks explicitly ask you to change into `docs/` or
`agent-framework/`; follow the directory shown above each command.

Use the [shell selection guide](shells.md) to switch between Bash/zsh and
PowerShell, understand which scripts need Bash, and keep secrets out of command
output and source control.

## Architecture at a glance { #architecture }

The workshop combines specialized Foundry agents with grounded retrieval and
deterministic security controls:

```mermaid
flowchart LR
    CLAIM[Accident statement] --> INTAKE[Claims Intake Agent]
    INTAKE --> DECISION[Claims Intelligence Agent]
    DECISION --> REVIEW{Human review needed?}
    REVIEW -- Yes --> HUMAN[Claims reviewer]
    REVIEW -- No --> SECURE[Claims Security Action Agent]
    HUMAN --> SECURE
    SECURE --> ACTIONS[Protected downstream actions]
    SEARCH[Foundry IQ evidence] --> INTAKE
    POLICY[Foundry IQ policies] --> DECISION
    FIDES[FIDES enforcement] --> SECURE
```

The workshop instructions are built directly from the challenge files in the
repository, so each guide has a single source of truth. Solution walkthroughs remain
available in the repository but are intentionally not included in this site.
