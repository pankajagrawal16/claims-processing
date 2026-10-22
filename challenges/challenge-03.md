# Challenge 3 - Build the Claims Intelligence Agent

[Home](../README.md)

**Expected Duration:** 30 minutes

## Overview

In this challenge, you will build the Claims Intelligence Agent, the core
decision-making component of the claims processing pipeline.

Like Challenge 2, this component is built in two steps: first you create a Foundry IQ
knowledge base over the policy documents in Blob Storage, then you create one
specialized Foundry agent. The agent receives the knowledge base as an MCP retrieval
tool and handles policy extraction and coverage adjudication in one resource.

Together, the Claims Intake Agent and Claims Intelligence Agent form this flow:

```mermaid
flowchart LR
  A[Claim statement image] --> B[Mistral Document AI OCR]
  B --> C[Claims Intake Agent]
  D[Foundry IQ crash statements] --> C
  C --> E[Intake artifact]
  G[Policy documents in Blob Storage] --> H[Foundry IQ policies knowledge base]
  E --> P[Claims Intelligence Agent]
  H --> P
  P --> I{Coverage decision}
  I --> J[Approve]
  I --> K[Deny]
  I --> L[Escalate]
```

Challenge 2 creates `claims-intake-agent`. This challenge creates
`claims-intelligence-agent`. After completing both challenges, the two Foundry agents
required by Challenge 4 are available.

### From mock policies to real policy documents

Enterprise claims adjudication starts with the model, but it only becomes useful when
the model can read the same policy documents your organization uses. In this challenge,
the Claims Intelligence Agent is the reasoning component, and the Foundry IQ knowledge
base over the Storage account `policies` container is its enterprise grounding layer.

In short: **policy documents → Foundry IQ knowledge base → Claims Intelligence Agent →
coverage decision**. The policy documents remain the source of truth. The agent
retrieves the matching document, structures its policy fields, and adjudicates the
claim in one Foundry resource.

The Claims Intelligence Agent combines Policy Matching and Coverage Validation into a
single orchestrated flow:

1. Retrieve the policy document that matches the claim's policy number through the Foundry IQ knowledge base.
2. Extract structured policy fields (coverage types, limits, deductibles, exclusions) from the grounded document using a dedicated Foundry agent.
3. Run multi-factor coverage analysis using an LLM-backed adjudicator.
4. Apply the compliance rules engine to identify exclusions and limits.
5. Score how consistent the reported crash details are with the policy on a 1-100 scale, driving the approve/deny/escalate outcome.
6. Escalate edge cases with structured reasoning and severity levels.
7. Emit a detailed coverage decision with confidence scores, a consistency score, and a full audit trail.

> [!IMPORTANT]
> The supplied Claims Intelligence implementation is complete. Do not modify the
> Python code in this challenge. Run the commands below and validate each result.

## Prerequisites

* Complete [Challenge 2](./challenge-02.md).
* Keep the `.env` configuration in the repository root.
* Confirm the MicroHack platform or your event coach supplied access to the Foundry
  project and the Azure Storage account.

## Tasks

### Task 1: Create the policies knowledge base

Create a Foundry IQ Blob knowledge source over the Storage account's `policies`
container and a `policies-kb` knowledge base over that source:

From the `docs` directory, run:

```bash
cd docs
python create_knowledge_base.py --policies
```

Foundry IQ creates and runs the ingestion resources asynchronously. The five Markdown
documents already uploaded to the `policies` container become retrievable through the
knowledge base without application code downloading the blobs.

The helper configures this knowledge base with **Minimal** retrieval reasoning and
**Extractive data** output. This works without a separate model deployment on the
knowledge base. The Claims Intelligence Agent still uses its Foundry model to interpret
the extracted policy fields and reason about claim coverage; the knowledge base handles
document retrieval, not adjudication.

If coverage validation reports that a Knowledge Base model must be specified for a reasoning
effort other than **Minimal**, the `policies-kb` knowledge base was created before this
setting was added. Rerun `python create_knowledge_base.py --policies` from the `docs` directory.
The helper updates the existing knowledge base in place, then retry the coverage check.

Expected result:

```text
Knowledge source 'policies-blob-ks' created or updated from Blob container 'policies'.
Knowledge base 'policies-kb' created or updated.
```

Open the Azure AI Search service in the Azure portal. Under **Agentic retrieval**,
confirm that `policies-blob-ks` appears under **Knowledge sources** and `policies-kb`
appears under **Knowledge bases**. Wait for the knowledge source synchronization to
finish before continuing.

??? tip "💡 Why did I run this step?"

    **Why a Blob knowledge source instead of downloading the files.** Foundry IQ indexes the `policies`
    container directly. Your code never downloads or parses the policy files, and a resync picks up any changed document.

    **Why Minimal reasoning and extractive output.** This knowledge base only retrieves documents. The
    Claims Intelligence Agent does the reasoning about coverage. Keeping retrieval simple means it needs no separate model.

    **Why wait for the sync.** Until the first indexing run finishes, the knowledge base is empty. A query made
    during the sync returns nothing, which looks like a missing policy when it is really a timing issue.

    **What to take away.** Keep retrieval and decision-making separate. You can then check each part on its own.

### Task 2: Prepare the Claims Intelligence Agent

Create or update `claims-intelligence-agent`. It retrieves policy documents through
the `policies-kb` MCP tool, converts them into structured policy information, and
compares that policy with the structured claim to produce a coverage decision.

```bash
python claims-intelligence-agent.py --setup-agent
```

Expected result:

```text
Foundry agent 'claims-intelligence-agent' is ready.
```

Open your Foundry project and confirm that `claims-intelligence-agent` appears under
**Agents** with `policies-knowledge-base` and `crash-statements-knowledge-base` MCP
tools. It calls `knowledge_base_retrieve` against the policies tool when extracting
coverage types, limits, deductibles, and exclusions. The crash-statements tool lets the
same agent inspect indexed accident evidence when requested.

Verify the crash-statements connection with a known indexed statement:

```bash
python claims-intelligence-agent.py --verify-crash-statement crash1_front
```

The Foundry IQ MCP endpoint uses the Search API version from
`FOUNDRY_IQ_MCP_API_VERSION`; the default for this lab is `2026-08-01-preview`.
The agent's MCP URL and the Foundry project's `policies-kb` connection target must
match. Changing `.env` or rerunning `--setup-agent` does not update a stale project
connection.

??? question "🛠️ If the agent reports 'api-version ... does not exist'"

    Foundry uses the **project connection's** target URL to reach the knowledge base.
    A stale `policies-kb` connection (for example, `api-version=2026-04-01`) can cause
    this error even when the agent uses the default `2026-08-01-preview`.

    1. No API-version setting is required: the code defaults to `2026-08-01-preview`.
       If you previously set `FOUNDRY_IQ_MCP_API_VERSION` in `.env` or your shell,
       remove any older override before repairing the connection.
    2. From the `docs` directory, sign in with `az login` if needed and run:

       ```text
       python fix_policies_connection.py
       ```

       The helper reads the repository-root `.env`, updates **only** a stale
       `policies-kb` RemoteTool target, and refreshes `claims-intelligence-agent` if
       it still has an older connection binding. It uses your Azure sign-in, not a
       Search API key, and stops if the connection is missing or is not using the
       project's managed identity.
    3. Rerun `python claims-intelligence-agent.py --verify-policies`. If
       `--verify-crash-statement` instead reports this error for `crash-statements-kb`,
       use `python fix_crash_statements_connection.py` as described in
       [Challenge 2](./challenge-02.md), then rerun the verification.

At this point, your project contains the two Foundry agents used in Challenge 4:
`claims-intake-agent` from Challenge 2 and `claims-intelligence-agent` from this
challenge.

### Task 3: Verify the enterprise policy documents

Run the policy verification command from the `docs` directory:

```bash
python claims-intelligence-agent.py --verify-policies
```

The command asks `claims-intelligence-agent` to retrieve each lab policy through Foundry
IQ. It does not download policy files from Blob Storage in application code.

Expected result:

```text
Found 5 policy document(s) through Foundry IQ:
  - COMM-AUTO-001
  - COMP-AUTO-001
  - HV-AUTO-001
  - LIAB-AUTO-001
  - MOTO-001
```

This confirms that the Claims Intelligence Agent can retrieve the real policy documents
uploaded from `data/policies/` through the knowledge base.

If the command reports that no policy documents were found, ask your coach to
verify the lab deployment and policy upload, then run the verification command
again.

??? tip "💡 Why did I run this step?"

    **Why verify before the full run.** If Task 4 gives a wrong coverage decision, you need to know whether
    retrieval or reasoning failed. This check runs retrieval alone. If all five policies come back, the problem is in the reasoning.

    **Why these five IDs.** Each policy ID is what the decision output cites. For example, `LIAB-AUTO-001` is
    the liability-only policy used in the exclusion path in Task 4.

    **Why it uses the agent's own route.** The check goes through the same Foundry IQ tool the agent uses,
    so it tests the path that matters for the decision.

    **What to take away.** Test your data source separately from your logic. Then a failure points to one place.

### Task 4: Run the Claims Intelligence Agent

Feed the intake artifact produced by the Claims Intake Agent in [Challenge 2](./challenge-02.md) straight into the Intelligence Agent:

```bash
cd docs
python claims-intelligence-agent.py ../data/claims/crash1/derived/statements/crash1_front.intake.json
```

The command prints the coverage decision to the terminal. It does not save another
local JSON file.

The intake artifact's `policy_number` is `LIAB-AUTO-001` (Liability Only), so this run exercises the exclusion path: a liability-only policy denying a collision claim, with `own_vehicle_damage` or `collision` listed in `exclusions_matched`.

Optional: override the policy number to test the approval path:

```bash
python claims-intelligence-agent.py ../data/claims/crash1/derived/statements/crash1_front.intake.json --policy-number COMP-AUTO-001
```

Optional: try a high claim amount with the liability-only policy:

```bash
python claims-intelligence-agent.py ../data/claims/crash1/derived/statements/crash1_front.intake.json --policy-number LIAB-AUTO-001 --claim-amount 95000
```

The high-amount example is a **what-if test**, not a guaranteed way to trigger escalation.

??? tip "💡 Why did I run this step?"

    **Why try different policies?** The same crash can have a different outcome under
    different coverage. Compare the liability-only policy, which excludes damage to
    your own car, with the comprehensive policy. Check `exclusions_matched` to see
    *why* a claim was denied, rather than judging by the result alone.

    **Why try a high amount?** A larger claim does not automatically go to a person
    for review: there is no fixed dollar threshold in this example. The agent
    decides whether manual review is needed based on the claim and the policy.

    **What should I check?** Look at `status` and `coverage_decision.requires_escalation`
    in the printed JSON. If review is needed, `status` is `ESCALATED`,
    `coverage_decision.escalation_reason` explains why, and `errors` contains an
    `ESCALATION_REQUIRED` warning. If review is not needed, `DENIED` with no warning
    can be the right result: liability-only insurance does not cover this collision
    damage to the claimant's own car.

## Expected output

### What the agent does

1. Retrieves the exact policy number from the `policies-kb` Foundry IQ knowledge base.
2. Parses the retrieved policy into a structured `PolicyInfo` object and caches it for the current process.
3. Builds a contextualized decision prompt combining claim details and policy fields.
4. Submits the prompt to the LLM adjudicator, which evaluates type match, limits, deductibles, exclusions, and crash-to-policy consistency simultaneously.
5. Parses the structured JSON response into a typed `CoverageDecision` object:
   - Approved amount after deductible
   - Matched exclusions
   - Risk flags and confidence score
   - `consistency_score`: a 1-100 rating of how well the crash details line up with what the policy should cover, and therefore whether the claim should be approved
   - `requires_escalation` and `escalation_reason`: the adjudicator's explicit manual-review signal and explanation
6. Escalates to `ESCALATED` status and records a `WARN`-severity error when the adjudicator signals manual review is needed.
7. Appends a complete audit trail entry for every significant action, including agent name, action type, outcome, and structured metadata (including the consistency score).


## Validation checklist

- [ ] `policies-blob-ks` and `policies-kb` appear under **Agentic retrieval**, and the knowledge source has finished synchronizing.
- [ ] `--verify-policies` lists all five policies: `COMM-AUTO-001`, `COMP-AUTO-001`, `HV-AUTO-001`, `LIAB-AUTO-001`, and `MOTO-001`.
- [ ] `--verify-crash-statement crash1_front` returns the indexed statement.
- [ ] Policy retrieval succeeds through the `policies-kb` Foundry IQ knowledge base and the cache is populated on the first call.
- [ ] The `claims-intelligence-agent` appears under your Foundry project's agents with its MCP retrieval tool.
- [ ] The LLM adjudicator returns a valid JSON decision with all required fields.
- [ ] `approved_amount` reflects the claim amount minus the applicable deductible, capped at the policy limit.
- [ ] The audit trail contains at least two entries: `retrieve_policy` and `validate_coverage`.
- [ ] Escalation path sets `status` to `ESCALATED` and populates `errors`.
- [ ] A liability-only policy correctly denies a collision claim and lists `own_vehicle_damage` or `collision` in `exclusions_matched`.
- [ ] `consistency_score` is an integer between 1 and 100 that agrees with the decision: scores below 30 do not coincide with `is_covered: true`, and scores of 90+ do not require escalation unless a hard policy limit is exceeded.

## Next step

Continue with [Challenge 4: Agent Framework workflow (default path)](./challenge-04-agent-framework.md)
to orchestrate the two Foundry agents from Challenges 2 and 3 as a graph with conditional
human review and optional hosted-agent deployment.
The [manual sequential workflow](./challenge-04.md) remains available as an alternative.
