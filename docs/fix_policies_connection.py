"""Repair the Foundry IQ policies RemoteTool connection and refresh its agent."""

from fix_crash_statements_connection import repair_connection

if __name__ == "__main__":
    repair_connection("policies-kb")
