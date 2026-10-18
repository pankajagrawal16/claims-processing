---
title: Build and preview the docs
description: Install the documentation dependencies, preview the MkDocs site, and contribute changes.
---

# Preview and update the documentation

The MkDocs site reuses the challenge guides in `challenges/` directly. Edit those
source files when changing lab instructions; don't keep a second copy of a challenge
in the site. Solution walkthroughs are intentionally excluded from this site.

## Preview locally

Install the documentation dependencies in a separate virtual environment so the
workshop's pinned Python environment remains unchanged.

=== "Bash/zsh"

    ```bash
    python -m venv .venv-docs
    source .venv-docs/bin/activate
    python -m ensurepip --upgrade
    python -m pip install -r requirements-docs.txt
    ```

=== "PowerShell"

    ```powershell
    python -m venv .venv-docs
    .\.venv-docs\Scripts\Activate.ps1
    python -m ensurepip --upgrade
    python -m pip install -r requirements-docs.txt
    ```

From the repository root, start the live preview:

=== "Bash/zsh"

    ```bash
    mkdocs serve
    ```

=== "PowerShell"

    ```powershell
    mkdocs serve
    ```

Open the local URL printed by MkDocs, normally `http://127.0.0.1:8000/`. MkDocs
refreshes the preview when a source page changes. Stop the server with `Ctrl+C`.

## Check before contributing

Build all pages and report broken internal links or other documentation warnings:

=== "Bash/zsh"

    ```bash
    mkdocs build --strict
    ```

=== "PowerShell"

    ```powershell
    mkdocs build --strict
    ```

Keep command tabs labeled exactly **Bash/zsh** and **PowerShell** when adding a new
shell-specific example. These shared labels let the Material for MkDocs theme keep
the visitor's shell choice in sync across pages. Keep shell-neutral commands in one
code block instead of repeating them.

## Publish to GitHub Pages

The `Documentation` workflow in `.github/workflows/docs.yml` runs on every pull request
and push to `main`:

- **Pull requests:** build the site with `mkdocs build --strict` and fail on broken links
  or other warnings. Nothing is published.
- **Pushes to `main`** (or a manual run): build the site, then deploy it to GitHub Pages at
  <https://pankaagr.cloud/claims-processing/>.

One-time repository setup: open **Settings > Pages**, and under **Build and deployment**
set **Source** to **GitHub Actions**. The workflow fails to deploy until this is set.

