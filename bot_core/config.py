"""Load explicit server-side app and employee mappings from a mounted file."""
import json
import os
from functools import lru_cache


@lru_cache
def settings() -> dict:
    """Return validated settings; secrets are environment references, never logged."""
    with open(os.environ.get("BOT_CONFIG", "/run/config/bots.json"), encoding="utf-8") as file:
        value = json.load(file)
    if not value.get("bots") or not value.get("clients"):
        raise ValueError("bots and clients must be configured")
    ids = [bot["code"] for bot in value["bots"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate bot code")
    for bot in value["bots"]:
        if bot.get("document_policy", "allowlist") not in ("allowlist", "bot_access"):
            raise ValueError("Unknown document policy")
    employees = [client["employee_code"] for client in value["clients"]]
    if len(employees) != len(set(employees)):
        raise ValueError("Duplicate employee code")
    credentials = [os.environ[client["token_env"]] for client in value["clients"]]
    if len(credentials) != len(set(credentials)):
        raise ValueError("Employee credentials must be unique")
    for client in value["clients"]:
        if not set(client["bots"]).issubset(ids):
            raise ValueError("Unknown bot in client access mapping")
        if len(os.environ[client["token_env"]]) < 32:
            raise ValueError("Client credential must have at least 32 characters")
    return value


def bot_config(code: str) -> dict:
    """Resolve a bot by trusted internal code, never by a client supplied app secret."""
    return next(bot for bot in settings()["bots"] if bot["code"] == code)


def document_allowed(bot: dict, token: str) -> bool:
    """Use platform bot ACLs when selected, otherwise require the explicitly configured token list."""
    return bot.get("document_policy", "allowlist") == "bot_access" or token in bot.get("allowed_documents", [])
