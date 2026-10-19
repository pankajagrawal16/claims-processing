# Instruction Feedback

> [!NOTE]
> This review uses [`main`](https://github.com/pankajagrawal16/MicroHack/tree/main/03-Azure/01-04-AI/05_Claims_Processing)
> as the baseline. Each item records a discrepancy between the instructions and behavior
> in that baseline; proposed corrections and workshop updates are on the
> [`improvements` branch](https://github.com/pankajagrawal16/MicroHack/tree/improvements/03-Azure/01-04-AI/05_Claims_Processing).
> Compare the [main-to-improvements changes](https://github.com/pankajagrawal16/MicroHack/compare/main...improvements)
> before proposing or porting a fix. This feedback file is published separately on
> the `instruction-discrepancies` branch, based on `main`, without the implementation changes.
> The reviewed baseline is main commit
> [`85f29203`](https://github.com/pankajagrawal16/MicroHack/commit/85f292033be1a27fd8be2084684da1b5478ed002).
> Historical verification notes below describe the earlier test project, not a fresh
> validation of another participant's deployment. Resolution notes identify which
> Challenges 2-3 discrepancies are addressed by the current working changes; the main
> baseline and its historical observations remain unchanged.

## Challenge 2 - Foundry IQ vs. Direct Search

- **Main instructions:** [Task 4](https://github.com/pankajagrawal16/MicroHack/blob/main/03-Azure/01-04-AI/05_Claims_Processing/challenges/challenge-02.md#task-4-understand-how-foundry-iq-grounding-is-added-through-a-knowledge-base-no-action-required) describes knowledge-base retrieval through `MCPTool`.
- **Code:** [`_build_crash_statements_knowledge_tool`](../docs/claims-intake-agent.py) originally used `AzureAISearchTool` to query the index directly, bypassing the knowledge base. The code now uses an `MCPTool` that calls the `crash-statements-kb` knowledge base MCP endpoint, as in the intelligence agent.
- **Suggested improvement:** Align the instructions with direct index retrieval, or implement the documented MCP knowledge-base path. The [improvements branch](https://github.com/pankajagrawal16/MicroHack/tree/improvements/03-Azure/01-04-AI/05_Claims_Processing) is the proposal workspace; this discrepancy is not resolved merely by adding a workflow.
- **Resolution in current changes:** The intake agent now uses the `crash-statements-kb` knowledge base through an `MCPTool`, the same pattern as the intelligence agent. `_ensure_foundry_agent()` updates an existing agent when its MCP tool changes. Task 4 and the solution walkthrough describe that path. The live agent has not been updated by this change; run `python docs/claims-intake-agent.py --indexed-claim crash1` after `labautomation/get-keys.sh` writes the project endpoint to `.env`.

## Challenge 3 - Verification Fails on MCP API Version

- **Main instructions:** Run `python claims-intelligence-agent.py --verify-crash-statement crash1_front` to verify crash evidence ([challenge step](https://github.com/pankajagrawal16/MicroHack/blob/main/03-Azure/01-04-AI/05_Claims_Processing/challenges/challenge-03.md)).
- **Original code:** Both knowledge-base MCP tool URLs used `api-version=2026-04-01` ([tool configuration](../docs/claims-intelligence-agent.py)).
- **Observed:** The command fails with HTTP 400 while enumerating tools at `policies-kb`: "The version indicated by the api-version query string parameter does not exist." Crash-statement verification is blocked.
- **Fix:** Default MCP endpoints to `2026-08-01-preview` (verified on this Search service), align project connection URLs, and refresh the agent when tool URLs or connections change. `FOUNDRY_IQ_MCP_API_VERSION` can override the script default. Run `python claims-intelligence-agent.py --setup-agent`, then retry the verification command.
- **Suggested improvement:** The [improvements branch](https://github.com/pankajagrawal16/MicroHack/compare/main...improvements) contains the updated API version and setup guidance.
- **Verified:** Updated both live project connections and the agent version. `--verify-crash-statement crash1_front` now returns John Peterson's `crash1_front.jpeg` statement with a source citation.
- **Resolution in current changes:** The current code defaults the MCP endpoints in [`claims-intelligence-agent.py`](../docs/claims-intelligence-agent.py), [`claims-intake-agent.py`](../docs/claims-intake-agent.py), and [`create_knowledge_base.py`](../docs/create_knowledge_base.py) to `2026-08-01-preview`, and the lab deployment's RemoteTool connections use the same version. Challenge 3 documents the default, the `FOUNDRY_IQ_MCP_API_VERSION` override, and the requirement to keep both project connection targets aligned with the MCP tool URLs before refreshing the agent.

## Challenge 3 - Policy Retrieval Requires a Knowledge-Base Model

- **Observed:** Coverage validation fails with "A Knowledge Base model must be specified to use any reasoning effort other than 'Minimal'". The policies knowledge base has no model and its setup omitted reasoning defaults.
- **Fix:** Explicitly set `retrievalReasoningEffort` to `minimal` and `outputMode` to `extractiveData`, using the verified API version. Updated the setup helper and the live `policies-kb`; the agent still performs coverage reasoning.
- **Verified:** Full coverage validation for the crash1 intake completes with no errors. It returns `DENIED` because the liability-only policy excludes own-vehicle damage.
- **Suggested improvement:** Review the [knowledge-base setup changes on `improvements`](https://github.com/pankajagrawal16/MicroHack/blob/improvements/03-Azure/01-04-AI/05_Claims_Processing/docs/create_knowledge_base.py).
- **Resolution in current changes:** `ensure_knowledge_base` in [`create_knowledge_base.py`](../docs/create_knowledge_base.py) sets `outputMode` to `extractiveData` and `retrievalReasoningEffort` to `minimal`, and uses the `2026-08-01-preview` MCP endpoint. Running `python create_knowledge_base.py --policies` creates or updates `policies-kb` in place, so existing workshop environments can be fixed by rerunning it. Challenge 3 explains the settings and the rerun step for the reasoning error.
- **Resolution in current changes:** Challenge 3 and its solution walkthrough now explain the helper's Minimal reasoning and Extractive data settings and distinguish knowledge-base retrieval from the agent model's coverage reasoning.

## Challenge 3 - Escalation Example and Output Do Not Align

- **Main instructions:** [Task 4](https://github.com/pankajagrawal16/MicroHack/blob/main/03-Azure/01-04-AI/05_Claims_Processing/challenges/challenge-03.md) suggests `--policy-number LIAB-AUTO-001 --claim-amount 95000` to test escalation and an `ESCALATION_REQUIRED` warning.
- **Code:** Escalation depends on the LLM's response; there is no deterministic amount threshold. A liability-only policy can deny excluded own-vehicle damage without escalating, so an empty `errors` list is not itself a failure.
- **Output mismatch:** [Decision construction](../docs/claims-intelligence-agent.py#L391) omits `requires_escalation` and `escalation_reason`. Their [model defaults](../docs/enterprise_models.py#L69) remain `false` and `null` in the printed decision even when the raw LLM response triggers `ESCALATED` status and an `ESCALATION_REQUIRED` warning.
- **Verified:** The documented LIAB/$95,000 command returned `DENIED`, `requires_escalation: false`, and `errors: []`. A mocked LLM response with escalation set to `true` produced `ESCALATED` and the expected `WARN`, but the printed decision still reported `false`.
- **Suggested improvement:** Review the [decision output changes on `improvements`](https://github.com/pankajagrawal16/MicroHack/blob/improvements/03-Azure/01-04-AI/05_Claims_Processing/docs/claims-intelligence-agent.py). The escalation example also needs qualification: a larger claim alone does not guarantee escalation.
- **Resolution in current changes:** The decision builder now copies both escalation fields from the model response, and a regression test checks that result JSON, status, and warning stay aligned for escalated and non-escalated decisions. Challenge 3 now presents the $95,000 input as a non-deterministic example rather than a guaranteed escalation trigger.

## Challenge 4 - Indexed Crash Retrieval Misses the Requested Statement

- **Main behavior:** The current [Challenge 4 instructions on `main`](https://github.com/pankajagrawal16/MicroHack/blob/main/03-Azure/01-04-AI/05_Claims_Processing/challenges/challenge-04.md) exercise indexed crash retrieval.
- **Observed:** The sequential workflow fails with "Foundry IQ did not return indexed statement 'crash3_front'", although the document exists. OCR-oriented instructions add generic terms to the filename query, so other crashes occupy the top three search results.
- **Fix:** Add an indexed-statement mode that searches only the quoted source filename, and refresh the intake agent when its instructions change.
- **Verified:** The updated live agent queried `"crash3_front.jpeg"` and returned the exact `crash3_front` document successfully.
- **Suggested improvement:** See the [indexed-crash workflow changes on `improvements`](https://github.com/pankajagrawal16/MicroHack/compare/main...improvements).

## Challenge 4 - Workflow Is Not Built With the Framework's Workflow Support

- **Main instructions:** [Challenge 4 on `main`](https://github.com/pankajagrawal16/MicroHack/blob/main/03-Azure/01-04-AI/05_Claims_Processing/challenges/challenge-04.md) presents `claims-sequential-workflow.py` as the claims workflow.
- **Code:** The workflow is imperative Python calling the intake and intelligence scripts in order, with a terminal prompt for human review. It does not use Agent Framework's native workflow support (executors and edges) or provide framework-managed pause/resume and hosted-agent integration.
- **Verified:** A graph workflow directly over the two existing Foundry agents (`agent-framework/`) runs locally and returns the human-review request as a resumable `request_info` call.
- **Suggested improvement:** [Challenge 4's Agent Framework workflow on `improvements`](https://github.com/pankajagrawal16/MicroHack/blob/improvements/03-Azure/01-04-AI/05_Claims_Processing/challenges/challenge-04-agent-framework.md) is the default continuation from Challenge 3 and continues into Challenge 5. The manual sequential workflow remains an alternative. Local pause/resume does not by itself guarantee recovery after a process restart; durable state depends on the hosting/storage configuration.

## Challenge 5 on Main - FIDES Is Still Experimental

- **Main instructions:** [Challenge 5 prerequisites on `main`](https://github.com/pankajagrawal16/MicroHack/blob/main/03-Azure/01-04-AI/05_Claims_Processing/challenges/challenge-05.md#prerequisites) mention in one bullet that FIDES is "currently marked experimental". Make this caveat prominent when presenting the security controls.
- **Observed:** The APIs carry an experimental warning in the pinned `agent-framework-core==1.13.0` (for example, `ContentVariableStore` emits an `ExperimentalWarning`: "may change or be removed in future versions without notice"). Behavior and names can change on upgrade, and this was only checked against the pinned version, not the newer core used by the Challenge 4 hosted workflow.
- **Suggested improvement:** FIDES moves to [Challenge 6 on `improvements`](https://github.com/pankajagrawal16/MicroHack/blob/improvements/03-Azure/01-04-AI/05_Claims_Processing/challenges/challenge-06.md). Keep the experimental status prominent and re-check it when dependency versions change. This numbering change is a proposal, not the numbering on `main`.
