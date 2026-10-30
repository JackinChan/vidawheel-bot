"""Generate ignored local smoke-test configuration; never prints credential values."""
import json
import secrets
import subprocess
from pathlib import Path


def main():
    """Reuse the disposable DB container password and generate a test-only employee credential."""
    root = Path(__file__).resolve().parents[1]
    target = root / ".env"
    if target.exists() or (root / "config.local.json").exists():
        raise SystemExit("Refusing to overwrite local configuration")
    info = json.loads(subprocess.check_output(["docker", "inspect", "vidawheel-bot-db-1"]))[0]
    env = dict(item.split("=", 1) for item in info["Config"]["Env"])
    password = env["POSTGRES_PASSWORD"]
    lines = ["# Generated disposable local test configuration; do not commit.",
             "DB_PASSWORD=" + password,
             "DATABASE_URL=postgresql://bot:" + password + "@db:5432/vidawheel_bot",
             "MCP_PUBLIC_URL=http://localhost:8000/mcp",
             "MCP_EMPLOYEE_ONE=" + secrets.token_urlsafe(40)]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    config = json.loads((root / "config.example.json").read_text(encoding="utf-8"))
    config["bots"][0].update({"code": "a", "app_id": "app-a", "tenant_key": "tenant-a", "open_id": "bot-a"})
    config["clients"][0]["bots"] = ["a"]
    (root / "config.local.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    print("Generated ignored local test settings")


if __name__ == "__main__":
    main()
