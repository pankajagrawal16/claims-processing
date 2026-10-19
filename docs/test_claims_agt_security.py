# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
"""Offline tests for the Agent Governance Toolkit claims policy.

Run from the docs folder with the toolkit installed:
    python -m pytest test_claims_agt_security.py -v
"""

from agentmesh.governance import GovernanceDenied, govern

from claims_agt_security import POLICY_PATH, call_sink, context_flags, run_scenario


def _status(name: str, labels: set[str], **arguments) -> str:
    return call_sink(name, labels, **arguments)["status"]


PAYOUT = {"claim_id": "CLM-2026-001", "amount": 15000}
NOTICE = {"claim_id": "CLM-2026-001", "message": "Public status update."}


def test_payout_executes_for_trusted_decision_only() -> None:
    assert _status("approve_payout", {"trusted", "public"}, **PAYOUT) == "EXECUTED"


def test_payout_denied_when_claimant_text_is_in_context() -> None:
    assert _status("approve_payout", {"trusted", "public", "untrusted"}, **PAYOUT) == "DENIED"


def test_payout_denied_for_untrusted_only() -> None:
    assert _status("approve_payout", {"untrusted", "public"}, **PAYOUT) == "DENIED"


def test_payout_denied_without_labels() -> None:
    outcome = call_sink("approve_payout", set(), **PAYOUT)
    assert outcome["status"] == "DENIED"
    assert "deny-when-labels-missing" in outcome["reason"]


def test_notice_executes_with_claimant_text_in_context() -> None:
    assert _status("notify_claimant", {"trusted", "public", "untrusted"}, **NOTICE) == "EXECUTED"


def test_notice_denied_when_private_data_is_in_context() -> None:
    assert _status("notify_claimant", {"trusted", "public", "private"}, **NOTICE) == "DENIED"


def test_notice_denied_without_labels() -> None:
    assert _status("notify_claimant", set(), **NOTICE) == "DENIED"


def test_unknown_action_is_denied_by_default() -> None:
    policy = str(POLICY_PATH)

    def delete_records(action=None, claim=None) -> str:
        return "deleted"

    governed = govern(delete_records, policy=policy)
    try:
        governed(action="delete_records", claim=context_flags({"trusted", "public"}))
    except GovernanceDenied:
        return
    raise AssertionError("unknown action was not denied")


def test_clean_scenario_blocks_payout_and_sends_notice() -> None:
    payout, notice = run_scenario("clean")
    assert payout["status"] == "DENIED"
    assert notice["status"] == "EXECUTED"


def test_exfiltration_scenario_blocks_both_sinks() -> None:
    payout, notice = run_scenario("inject-exfiltration")
    assert payout["status"] == "DENIED"
    assert notice["status"] == "DENIED"
    assert "deny-notify-with-private-context" in notice["reason"]
