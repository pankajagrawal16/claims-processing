---
title: Lab Automation
description: Deployment entry points for the ClaimSight Claims MicroHack
---

## Files

* `deploy-lab.ps1` provisions the lab resources and returns Hackbox credentials.
* `get-keys.sh` (Bash/zsh) and `get-keys.ps1` (PowerShell) create a participant's `.env` in the repository root (the workshop root,
  the folder containing `pyproject.toml`) from the deployed lab. They write the same file.
* `lab-defaults.json` declares the MicroHack deployment defaults.
* `azuredeploy.json` defines the Azure resources provisioned for each lab.

## Infrastructure

The ARM template is stored in [`azuredeploy.json`](./azuredeploy.json) alongside the
other platform-controlled deployment assets.