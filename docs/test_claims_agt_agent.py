# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
"""Offline tests for the Agent Framework examples with the Agent Governance Toolkit.

Run from the docs folder with the toolkit and agent-framework-core installed:
    python -m pytest test_claims_agt_agent.py -v
"""

import asyncio

from claims_agt_agent import run_example


def _statuses(result: dict) -> list[tuple[str, str]]:
    return [(item["tool"], item["status"]) for item in result["sink_outcomes"]]


def test_clean_run_refuses_payout_and_sends_notice() -> None:
    result = asyncio.run(run_example("clean"))
    assert _statuses(result) == [("approve_payout", "DENIED"), ("notify_claimant", "EXECUTED")]


def test_payout_injection_is_refused_by_the_governed_tool() -> None:
    result = asyncio.run(run_example("inject-payout"))
    payout = result["sink_outcomes"][0]
    assert payout["status"] == "DENIED"
    assert "deny-payout-with-untrusted-context" in payout["reason"]


def test_exfiltration_is_refused_at_both_sinks() -> None:
    result = asyncio.run(run_example("inject-exfiltration"))
    assert _statuses(result) == [("approve_payout", "DENIED"), ("notify_claimant", "DENIED")]
    notice = result["sink_outcomes"][1]
    assert "deny-notify-with-private-context" in notice["reason"]


def test_agent_records_the_labels_it_read() -> None:
    result = asyncio.run(run_example("inject-exfiltration"))
    assert result["labels_in_context"] == ["private", "public", "trusted", "untrusted"]


def test_summary_comes_from_the_model() -> None:
    result = asyncio.run(run_example("clean"))
    assert result["summary"] == "Claim actions completed; see the tool results."
