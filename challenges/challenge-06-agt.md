# Challenge 6 (Alternate) - Enforce the Claims Security Actions with the Agent Governance Toolkit

[Home](../index.md) | [Challenge 6 (FIDES)](challenge-06.md)

**Expected Duration:** 45 minutes

## Overview

This alternate path protects the same two downstream actions as [Challenge 6](challenge-06.md):

- `approve_payout` must not run while claimant-written text is in the agent's context.
- `notify_claimant` must not run while private policyholder data is in the agent's context.

Instead of FIDES, enforcement uses the
[Agent Governance Toolkit](https://github.com/microsoft/agent-governance-toolkit). Each
sink is wrapped with `govern()` from the toolkit's `agentmesh.governance` package. Before a
sink body runs, the toolkit evaluates a YAML policy and either runs the sink or raises
`GovernanceDenied`.

The lab's code is in:

- `docs/agt_claims_policy.yaml`: the policy rules
- `docs/claims_agt_security.py`: the governed sinks and a scenario runner
- `docs/test_claims_agt_security.py`: offline tests

> [!NOTE]
> The scenario runner replays the action agent's tool calls without a language model. It
> does not call Foundry. Connecting the governed sinks to the Foundry action agent is the
> next step after this challenge.

> [!IMPORTANT]
> This track does not replace Challenge 6. Complete the FIDES path or this alternate path,
> not both, unless your coach asks you to compare them.

## Prerequisites

- Python 3.11 on your `PATH`. Check it with `python --version`.
- The repository, opened at the workshop root (the folder containing `pyproject.toml`).

The toolkit is installed in its own environment. The workshop's pinned environment is not
changed. Running this challenge needs no Azure access.

## Tasks

### Task 1: Create the toolkit environment

Run these commands from the workshop root:

=== "Bash/zsh"

    ```bash
    python3.11 -m venv .venv-agt
    source .venv-agt/bin/activate
    python -m pip install "agent-governance-toolkit[full]" pytest
    ```

=== "PowerShell"

    ```powershell
    py -3.11 -m venv .venv-agt
    .\.venv-agt\Scripts\Activate.ps1
    python -m pip install "agent-governance-toolkit[full]" pytest
    ```

A `DeprecationWarning` about `agentmesh-platform` can appear. It doesn't affect this lab.

### Task 2: Read the policy

Open `docs/agt_claims_policy.yaml`. The policy denies by default (`default_action: deny`).
It has two allow rules and three deny rules:

| Rule | Action | Condition |
|---|---|---|
| `allow-approve-payout` | allow | the call is `approve_payout` |
| `allow-notify-claimant` | allow | the call is `notify_claimant` |
| `deny-payout-with-untrusted-context` | deny | `approve_payout` while `untrusted_in_context` is true |
| `deny-notify-with-private-context` | deny | `notify_claimant` while `private_in_context` is true |
| `deny-when-labels-missing` | deny | `labels_missing` is true for any call |

The `govern()` call uses the default `deny_overrides` strategy. A matching deny rule blocks
the call even if an allow rule also matches. An unknown tool has no allow rule, so the
default deny applies.

The rule language has no negation and no list membership, so the host computes the flags
from the labels in `context_flags()`.

### Task 3: Run the scenarios

Replay the three scenarios from the FIDES challenge:

=== "Bash/zsh"

    ```bash
    cd docs
    python claims_agt_security.py --scenario clean
    python claims_agt_security.py --scenario inject-payout
    python claims_agt_security.py --scenario inject-exfiltration
    ```

=== "PowerShell"

    ```powershell
    Set-Location docs
    python claims_agt_security.py --scenario clean
    python claims_agt_security.py --scenario inject-payout
    python claims_agt_security.py --scenario inject-exfiltration
    ```

Expected results:

| Scenario | `approve_payout` | `notify_claimant` | Why |
|---|---|---|---|
| `clean` | `DENIED` | `EXECUTED` | The claimant follow-up is in context, so the payout is refused. The public notice is allowed. |
| `inject-payout` | `DENIED` | `EXECUTED` | The injected payout request comes from claimant text, so the payout is refused. |
| `inject-exfiltration` | `DENIED` | `DENIED` | The policyholder record is in context, so the notice is refused. The payout is also refused for the claimant text. |

A denied call prints the rule that matched, such as
`deny-payout-with-untrusted-context`.

### Task 4: Run the offline tests

From the `docs` folder, with `.venv-agt` active:

```bash
python -m pytest test_claims_agt_security.py -v
```

The output should list ten tests, and all of them should pass. The tests cover trusted-only
payouts, claimant text in a payout, missing labels, public and private notices, an unknown
tool, and the two full scenarios.

### Task 5: Understand who sets the labels

The toolkit does not label data. The host must label every value as it enters the workflow.
Each value carries two labels, one for integrity and one for confidentiality:

| Source | Integrity | Confidentiality | Why |
|---|---|---|---|
| The coverage decision from the intelligence agent | `trusted` | `public` | Produced by the trusted workflow. |
| The claimant's follow-up message | `untrusted` | `public` | Written by the claimant. |
| The policyholder record | `trusted` | `private` | Internal personal data. |

A value derived from several sources carries all of their labels. The payout sink checks only
integrity labels. The notification sink checks only confidentiality labels.

## How this compares with FIDES

| Capability | FIDES (Challenge 6) | Agent Governance Toolkit (this track) |
|---|---|---|
| Enforcement point | Before the tool body, inside Agent Framework middleware | Before the tool body, via `govern()` around the tool function |
| Labelling | Attached by the framework to tool results and messages | Attached by the host; the toolkit does not label data |
| Sink declarations | Tool metadata (`accepts_untrusted`, `max_allowed_confidentiality`) | YAML rules over the sink name and the context flags |
| Default behaviour | Blocks the sink when a label conflicts | Denies unless an allow rule matches |
| Audit | FIDES audit log | Toolkit audit, enabled by default in `govern()` |
| Quarantine of untrusted content | Optional auto-hide with a quarantine model | Not included |
| Agent Framework integration | Native | Native middleware is listed by the toolkit; this lab wraps the sink functions directly |

The toolkit is in public preview, so the API may change before general availability.

## Validation checklist

- [ ] `.venv-agt` exists and `python -c "import agentmesh.governance"` succeeds.
- [ ] The `clean` scenario shows `approve_payout` as `DENIED` and `notify_claimant` as `EXECUTED`.
- [ ] The `inject-exfiltration` scenario shows `notify_claimant` as `DENIED` with `deny-notify-with-private-context`.
- [ ] All ten offline tests pass.
- [ ] You can name the two labels on the policyholder record and the reason the payout sink ignores confidentiality.

## Next step

Return to the [Challenge 6 FIDES path](challenge-06.md) to compare the two enforcement models,
or continue to the [home page](../index.md) for the workshop summary.
