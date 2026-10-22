"""Configure azd from the workshop project endpoint and the logged-in Azure CLI."""

import json
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlparse

from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"
AZD_ENVIRONMENT = "claims-framework"
AZD_KEYS = (
    "FOUNDRY_PROJECT_ENDPOINT",
    "AZURE_AI_PROJECT_ID",
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_RESOURCE_GROUP",
    "AZURE_LOCATION",
)
PROJECT_RESOURCE_TYPE = "Microsoft.CognitiveServices/accounts/projects"
FOUNDRY_HOST_SUFFIX = ".services.ai.azure.com"


def azure_json(*args: str):
    try:
        result = subprocess.run(
            ["az", *args, "--output", "json", "--only-show-errors"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Install Azure CLI and sign in with 'az login' before configuring azd.") from exc
    if result.returncode != 0:
        raise RuntimeError(f"Azure CLI lookup failed: {result.stderr.strip() or 'Sign in with az login and try again.'}")
    return json.loads(result.stdout)


def deployment_values(env_file: Path) -> dict[str, str]:
    if not env_file.is_file():
        raise FileNotFoundError(f"Create the workshop-root {env_file.name} before configuring azd.")

    config = dotenv_values(env_file)
    project_endpoint = config.get("FOUNDRY_PROJECT_ENDPOINT") or config.get("AI_FOUNDRY_PROJECT_ENDPOINT")
    alternate = config.get("AI_FOUNDRY_PROJECT_ENDPOINT")
    if alternate and project_endpoint != alternate:
        raise ValueError("FOUNDRY_PROJECT_ENDPOINT and AI_FOUNDRY_PROJECT_ENDPOINT must match in .env.")
    if not isinstance(project_endpoint, str) or not project_endpoint.strip() or "<" in project_endpoint:
        raise ValueError("Set FOUNDRY_PROJECT_ENDPOINT to the existing Foundry project endpoint in .env.")
    project_endpoint = project_endpoint.strip().rstrip("/")
    endpoint = urlparse(project_endpoint)
    path = endpoint.path.split("/")
    if (endpoint.scheme != "https" or not endpoint.hostname
            or not endpoint.hostname.endswith(FOUNDRY_HOST_SUFFIX)
            or endpoint.username or endpoint.password or endpoint.port or endpoint.query or endpoint.fragment
            or len(path) != 4 or path[1:3] != ["api", "projects"] or not path[3]):
        raise ValueError("FOUNDRY_PROJECT_ENDPOINT must be an HTTPS Foundry project endpoint, not a resource endpoint.")

    account_name = endpoint.hostname.removesuffix(FOUNDRY_HOST_SUFFIX)
    project_name = unquote(path[3])
    subscription = azure_json("account", "show", "--query", "{id:id,state:state}")
    if not isinstance(subscription, dict) or not subscription.get("id") or subscription.get("state") != "Enabled":
        raise RuntimeError("Select an enabled subscription for this Foundry project with 'az account set'.")
    subscription_id = subscription["id"]
    resources = azure_json(
        "resource", "list", "--subscription", subscription_id,
        "--resource-type", PROJECT_RESOURCE_TYPE,
        "--query", "[].{id:id,resourceGroup:resourceGroup,location:location}",
    )
    if not isinstance(resources, list):
        raise TypeError("Azure CLI did not return a Foundry project resource list.")
    expected = f"/providers/Microsoft.CognitiveServices/accounts/{account_name}/projects/{project_name}"
    matches = [
        resource for resource in resources
        if isinstance(resource, dict) and isinstance(resource.get("id"), str)
        and resource["id"].casefold().endswith(expected.casefold())
        and resource["id"].casefold().startswith(f"/subscriptions/{subscription_id}/".casefold())
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Found {len(matches)} matching Foundry projects in the selected Azure subscription. "
            "Select the project's subscription with 'az account set' and check project read access."
        )
    resource = matches[0]
    if not resource.get("resourceGroup") or not resource.get("location"):
        raise RuntimeError("The matching Foundry project is missing its resource group or location in Azure.")
    values = {
        "FOUNDRY_PROJECT_ENDPOINT": project_endpoint,
        "AZURE_AI_PROJECT_ID": resource["id"],
        "AZURE_SUBSCRIPTION_ID": subscription_id,
        "AZURE_RESOURCE_GROUP": resource["resourceGroup"],
        "AZURE_LOCATION": resource["location"],
    }
    for key in AZD_KEYS[1:]:
        specified = config.get(key)
        if specified and specified.strip() and specified.strip().casefold() != values[key].casefold():
            raise RuntimeError(f"{key} in .env does not match the Foundry project in the selected Azure subscription.")
    return values


def main() -> None:
    values = deployment_values(ENV_FILE)
    try:
        result = subprocess.run(
            ["azd", "env", "set", *(f"{key}={values[key]}" for key in AZD_KEYS), "--environment", AZD_ENVIRONMENT],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Install Azure Developer CLI (azd) before configuring the environment.") from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"azd env set failed for {AZD_ENVIRONMENT}: {result.stderr.strip() or 'No error details returned.'} "
            f"Create it with 'azd env new {AZD_ENVIRONMENT}' first if needed."
        )
    print(f"Updated {AZD_ENVIRONMENT} from the Foundry project in the selected Azure subscription.")
    print("The workshop .env was not changed; its Search and Storage secrets were not copied to azd.")


if __name__ == "__main__":
    main()
