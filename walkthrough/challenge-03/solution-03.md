---
title: "Solution 03: Build the Claims Intelligence Agent"
description: "Solution walkthrough for grounding claim decisions in policy documents"
---

[Home](../../README.md) | [Challenge 03](../../challenges/challenge-03.md) | [Previous solution](../challenge-02/solution-02.md) | [Next solution](../challenge-04/solution-04-agent-framework.md)

## Outcome

This solution creates a Foundry IQ knowledge base over the five policy documents in
Blob Storage, connects it to `claims-intelligence-agent`, and produces a grounded
coverage decision for the Challenge 02 intake artifact.

The knowledge base uses Minimal retrieval reasoning with Extractive data output so
it does not require a separate knowledge-base model deployment. The agent's Foundry
model performs the coverage reasoning.

## Prerequisites

* Complete Challenge 02
* Configure `AZURE_STORAGE_CONNECTION_STRING` and
  `AZURE_POLICIES_CONTAINER_NAME`
* Keep the generated intake artifact under the claim's `derived/statements/`
  folder

## Run the solution

From the repository root, create the policy knowledge
base, create the Foundry agent, and verify the policies:

```bash
cd docs
python create_knowledge_base.py --policies
python claims-intelligence-agent.py --setup-agent
python claims-intelligence-agent.py --verify-policies
```

Run the default liability-only decision:

```bash
python claims-intelligence-agent.py ../data/claims/crash1/derived/statements/crash1_front.intake.json
```

Exercise the comprehensive coverage path:

```bash
python claims-intelligence-agent.py ../data/claims/crash1/derived/statements/crash1_front.intake.json \
  --policy-number COMP-AUTO-001
```

## Expected result

Policy verification lists five policy codes. The default liability-only case is
`DENIED`, approves no payout, and identifies collision or own-vehicle damage as
an exclusion. The comprehensive policy run exercises the covered collision
path and applies its deductible.

## Troubleshooting

* If no policies are found, redeploy or upload `data/policies/*.md` to the
  configured policies container
* If storage configuration is missing, restore the deployment-provided
  connection string in the environment
* If a policy is unknown, use one of the codes printed by `--verify-policies`
* If MCP verification reports an unsupported API version, confirm the
  `FOUNDRY_IQ_MCP_API_VERSION` value and ensure both Foundry project connection
  targets use the same version before rerunning `--setup-agent`

## Validation checklist

* [ ] The `claims-intelligence-agent` exists with its policy knowledge-base tool
* [ ] Five policy documents are retrieved through Foundry IQ
* [ ] The default liability-only claim is denied for the expected exclusion
* [ ] The audit trail includes policy retrieval and coverage validation
* [ ] The consistency score is between 1 and 100
* [ ] If the decision escalates, `coverage_decision.requires_escalation` and
  `coverage_decision.escalation_reason` agree with the `ESCALATED` status and
  `ESCALATION_REQUIRED` warning

Continue with [Challenge 04: Agent Framework workflow (default path)](../../challenges/challenge-04-agent-framework.md)
and its [solution](../challenge-04/solution-04-agent-framework.md).
The [manual sequential workflow](../../challenges/challenge-04.md) is an alternative.
