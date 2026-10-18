---
title: Choose your shell
description: Switch command examples between Bash or zsh and PowerShell and learn about shell-specific setup.
---

# Choose the shell you use

The command examples use matching tabs throughout the site:

- **Bash/zsh** for macOS, Linux, and the Codespace terminal.
- **PowerShell** for Windows PowerShell 7+ or PowerShell in VS Code.

Select your shell on any paired command. The same choice is carried across the
other shell tabs on the site. Commands such as `python` and `az` use the same syntax
in both shells, so they may appear as a single code block instead of duplicated tabs.

## Pick your shell

=== "Bash/zsh"

    ```bash
    python --version
    az --version
    ```

=== "PowerShell"

    ```powershell
    python --version
    az --version
    ```

## Know which directory the command uses

The **workshop root** is the project folder containing `pyproject.toml`, `azure.yaml`,
and the `docs/` directory. Instructions may ask you to change into `docs/` or
`agent-framework/` for a particular task. If a command fails with “file not found,”
check your current directory before changing the command.

## Bash-only helper scripts

The lab configuration helper `labautomation/get-keys.sh` requires **Bash 4 or later**
(`mapfile` is not available in macOS's built-in Bash 3.2). On macOS, install a newer
Bash or use the workshop Codespace. On Windows, run the helper from WSL or an
installed Bash such as Git Bash; PowerShell's `bash` command can invoke it when that
Bash executable is available on `PATH`.

For uploading missing sample assets, the repository also supplies
`labautomation/upload-assets.ps1`. PowerShell users can use that script instead of
`upload-assets.sh` after installing the **Az.Accounts**, **Az.Resources**, and
**Az.Storage** PowerShell modules and signing in with `Connect-AzAccount`.

Azure CLI commands such as `az login` are not Bash-only. Use them from PowerShell
without changing their syntax.

## Activate the Python environment

Python environment activation is shell-specific. Activate the workshop environment
from the workshop root:

=== "Bash/zsh"

    ```bash
    source .venv/bin/activate
    ```

=== "PowerShell"

    ```powershell
    .\.venv\Scripts\Activate.ps1
    ```

If PowerShell blocks activation because of its execution policy, see Microsoft's
[PowerShell execution policy documentation](https://learn.microsoft.com/powershell/module/microsoft.powershell.core/about/about_execution_policies).
You can also run the environment's Python directly, for example
`.venv\Scripts\python.exe docs\claims-intake-agent.py --help`, without activating it.

## Keep credentials private

The setup scripts write secrets to the ignored `.env` file. Do not paste its values
into a terminal command, issue, chat, screenshot, or commit. Verify configuration by
checking variable **names** or using the documented command, not by printing the
file. Prefer interactive Azure sign-in over putting credentials on a command line.
