# Challenge 6 (Alternate) - Govern the Claims Security Agent with the Agent Governance Toolkit

[Home](../index.md) | [Challenge 6 (FIDES)](challenge-06.md)

**Expected Duration:** 45 minutes

## Overview

This alternate path protects the same two downstream actions as [Challenge 6](challenge-06.md):

- `approve_payout` must not run while claimant-written text is in the agent's context.
- `notify_claimant` must not run while private policyholder data is in the agent's context.

Instead of FIDES, the sinks are enforced by the
[Agent Governance Toolkit](https://github.com/microsoft/agent-governance-toolkit). Each sink
is wrapped with `govern()`, which evaluates a YAML policy before the sink body runs. The
sinks are Microsoft Agent Framework tools, so the agent's own tool loop calls them.

The lab's code is in:

- `docs/agt_claims_policy.yaml`: the policy rules
- `docs/claims_agt_security.py`: the governed sinks and the read tools that add labels
- `docs/claims_agt_agent.py`: a real Agent Framework agent that uses those tools
- `docs/test_claims_agt_security.py` and `docs/test_claims_agt_agent.py`: offline tests

> [!NOTE]
> By default the agent's model is a scripted client. It plays back the tool calls a model
> would make, so the example runs offline with no Azure access. The agent loop, the tools,
> and the governance checks are all real. Task 4 runs the same agent against a Foundry model.

> [!NOTE]
> FIDES and the Agent Governance Toolkit are two different ways to govern an agent's tools.
> FIDES tracks how labelled data flows through the agent and enforces that inside the Agent
> Framework middleware. The toolkit wraps each tool in a policy check, and the rules decide
> whether the tool body runs. Both pages use the same two claims actions, so you can compare them.

## Prerequisites

- Python 3.11 on your `PATH`. Check it with `python --version`.
- The repository, opened at the workshop root (the folder containing `pyproject.toml`).

The toolkit and Agent Framework are installed in their own environment. The workshop's
pinned environment is not changed. Tasks 1 to 3 need no Azure access.

## Tasks

### Task 1: Create the environment

Run these commands from the workshop root:

=== "Bash/zsh"

    ```bash
    python3.11 -m venv .venv-agt
    source .venv-agt/bin/activate
    python -m pip install "agent-governance-toolkit[full]" "agent-framework-core==1.13.0" pytest
    ```

=== "PowerShell"

    ```powershell
    py -3.11 -m venv .venv-agt
    .\.venv-agt\Scripts\Activate.ps1
    python -m pip install "agent-governance-toolkit[full]" "agent-framework-core==1.13.0" pytest
    ```

A `DeprecationWarning` about `agentmesh-platform` can appear. It doesn't affect this lab.

### Task 2: Read the policy and the agent

Open `docs/agt_claims_policy.yaml`. The policy denies by default (`default_action: deny`).
It has two allow rules and three deny rules:

| Rule | Action | Condition |
|---|---|---|
| `allow-approve-payout` | allow | the call is `approve_payout` |
| `allow-notify-claimant` | allow | the call is `notify_claimant` |
| `deny-payout-with-untrusted-context` | deny | `approve_payout` while `untrusted_in_context` is true |
| `deny-notify-with-private-context` | deny | `notify_claimant` while `private_in_context` is true |
| `deny-when-labels-missing` | deny | `labels_missing` is true for any call |

`govern()` uses the default `deny_overrides` strategy. A matching deny rule blocks the call
even if an allow rule also matches. The rule language has no negation or list membership, so
the host computes the flags from the labels in `context_flags()`.

Then open `docs/claims_agt_agent.py`. `build_agent()` creates an Agent Framework agent and
gives it the tools from `ClaimRun.build_tools()`. Those tools are the agent's only way to act.

??? tip "💡 Why did I run this step?"

    **Why deny by default.** An agent can call tools you did not anticipate. Starting from deny means a missing
    rule fails safe instead of allowing the action.

    **Why the host computes the flags.** The policy language cannot express "not" or list membership, so the code
    turns the labels into simple true or false flags. The policy then only compares those flags.

    **Why the tools are the only way to act.** If the model can act only through the wrapped tools, the policy
    covers every action it can take. This is the core design choice: govern the action, not the prompt.

    **What to take away.** Write rules about what the agent does, and make the default deny. Then a gap in the rules blocks the action instead of permitting it.

### Task 3: Run the agent through the three scenarios

From the `docs` folder, with `.venv-agt` active:

=== "Bash/zsh"

    ```bash
    cd docs
    python claims_agt_agent.py --scenario clean
    python claims_agt_agent.py --scenario inject-payout
    python claims_agt_agent.py --scenario inject-exfiltration
    ```

=== "PowerShell"

    ```powershell
    Set-Location docs
    python claims_agt_agent.py --scenario clean
    python claims_agt_agent.py --scenario inject-payout
    python claims_agt_agent.py --scenario inject-exfiltration
    ```

Each run prints the labels the agent had read, the outcome of each sink call, and the summary.
Expected outcomes:

| Scenario | `approve_payout` | `notify_claimant` | Why |
|---|---|---|---|
| `clean` | `DENIED` | `EXECUTED` | The claimant follow-up is in context, so the payout is refused. The public notice is allowed. |
| `inject-payout` | `DENIED` | `EXECUTED` | The injected payout request comes from claimant text, so the payout is refused. |
| `inject-exfiltration` | `DENIED` | `DENIED` | The policyholder record is in context, so the notice is refused. The payout is also refused for the claimant text. |

A denied call reports the rule that matched, such as `deny-payout-with-untrusted-context`.

### Task 4: Run the offline tests

From the `docs` folder, with `.venv-agt` active:

```bash
python -m pytest test_claims_agt_security.py test_claims_agt_agent.py -v
```

Eighteen tests should pass. They cover the policy cases, the agent tools, and the agent runs for
the three scenarios, and the labels the agent records.

### Task 5 (optional): Run the agent against a Foundry model

This step replaces the scripted model with a Foundry model. It needs the Foundry project
endpoint in `FOUNDRY_PROJECT_ENDPOINT`, an optional `FOUNDRY_MODEL`, and `az login` with a
lab account that can use the project. It uses your model quota.

```bash
python claims_agt_agent.py --scenario inject-payout --live
```

With a live model, the outcomes come from the model's own tool choices. The governance checks
are the same. If the model does not call the sinks, the sink outcomes list is empty.

### Task 6: Understand who sets the labels

The toolkit does not label data. The host labels every value as it enters the workflow. Each
value carries two labels, one for integrity and one for confidentiality:

| Source | Integrity | Confidentiality | Why |
|---|---|---|---|
| The coverage decision from the intelligence agent | `trusted` | `public` | Produced by the trusted workflow. |
| The claimant's follow-up message | `untrusted` | `public` | Written by the claimant. |
| The policyholder record | `trusted` | `private` | Internal personal data. |

The read tools in `ClaimRun` add these labels when the agent reads each source. A value derived
from several sources carries all of their labels. The payout sink checks only integrity labels.
The notification sink checks only confidentiality labels.

## How this compares with FIDES

| Capability | FIDES (Challenge 6) | Agent Governance Toolkit (this track) |
|---|---|---|
| Enforcement point | Before the tool body, inside Agent Framework middleware | Before the tool body, via `govern()` around the tool function |
| Labelling | Attached by the framework to tool results and messages | Attached by the host in the read tools; the toolkit does not label data |
| Sink declarations | Tool metadata (`accepts_untrusted`, `max_allowed_confidentiality`) | YAML rules over the sink name and the context flags |
| Default behaviour | Blocks the sink when a label conflicts | Denies unless an allow rule matches |
| Audit | FIDES audit log | Toolkit audit, enabled by default in `govern()` |
| Quarantine of untrusted content | Optional auto-hide with a quarantine model | Not included |
| Agent Framework integration | Native middleware | The governed sinks are Agent Framework tools, run by the agent loop |

The toolkit is in public preview, so its API may change before general availability.

## Validation checklist

- [ ] `.venv-agt` exists and `python -c "import agentmesh.governance"` succeeds.
- [ ] The `clean` run shows `approve_payout` as `DENIED` and `notify_claimant` as `EXECUTED`.
- [ ] The `inject-payout` run shows `approve_payout` as `DENIED` with `deny-payout-with-untrusted-context`.
- [ ] Each scenario's outcomes match the Task 3 table.
- [ ] The `inject-exfiltration` run shows `notify_claimant` as `DENIED` with `deny-notify-with-private-context`.
- [ ] All eighteen offline tests pass.
- [ ] You can name the labels on the policyholder record and why the payout sink ignores confidentiality.

## Next step

Return to the [Challenge 6 FIDES path](challenge-06.md) to compare the two enforcement models,
or continue to the [home page](../index.md) for the workshop summary.
