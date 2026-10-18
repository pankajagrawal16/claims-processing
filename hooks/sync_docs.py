from pathlib import Path
import shutil


IGNORED_ENTRIES = shutil.ignore_patterns(
    ".deployment.json",
    ".DS_Store",
    ".env",
    ".env.*",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".venv-*",
    "__pycache__",
    "*.log",
    "*.pyc",
    "*.tmp",
    "local.settings.json",
    "node_modules",
)


def on_pre_build(config):
    repository = Path(config.config_file_path).parent
    docs = Path(config.docs_dir)

    for stale in (docs / "README.md", docs / "walkthrough"):
        if stale.is_dir():
            shutil.rmtree(stale)
        elif stale.exists():
            stale.unlink()

    for directory in ("agent-framework", "challenges", "data", "labautomation"):
        source = repository / directory
        target = docs / directory
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target, ignore=IGNORED_ENTRIES)

    for filename in (".env.example", "LICENSE", "azure.yaml", "pyproject.toml", "uv.lock"):
        shutil.copy2(repository / filename, docs / filename)

    scripts = docs / "docs"
    if scripts.exists():
        shutil.rmtree(scripts)
    scripts.mkdir()
    for script in (repository / "docs").glob("*.py"):
        shutil.copy2(script, scripts / script.name)

    example = repository / ".foundry" / ".deployment.example.json"
    if example.exists():
        foundry = docs / ".foundry"
        foundry.mkdir(exist_ok=True)
        shutil.copy2(example, foundry / example.name)
        shutil.copy2(example, docs / "foundry-deployment.example.json")

    for page in (docs / "challenges").rglob("*.md"):
        text = page.read_text().replace("../README.md", "../index.md")
        text = text.replace("../.foundry/.deployment.example.json", "../foundry-deployment.example.json")
        text = text.replace("../agent-framework/.agentignore", "../agent-framework/agentignore-example.txt")
        page.write_text(text)

    shutil.copy2(
        repository / "agent-framework" / ".agentignore",
        docs / "agent-framework" / "agentignore-example.txt",
    )
