"""Extend only synthetic local configuration with generated callback credentials."""
import json
import secrets
from pathlib import Path


def main():
    """Refuse real app configurations and leave generated credentials in ignored files."""
    root = Path(__file__).resolve().parents[1]
    path = root / "config.local.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    if config["bots"][0]["app_id"] != "app-a":
        raise SystemExit("Only synthetic configuration can be extended")
    config["bots"][0].update({"allowed_documents": ["docA"], "allowed_chats": ["chat-a"],
                             "encrypt_key_env": "TEST_CALLBACK_KEY", "verification_token_env": "TEST_CALLBACK_TOKEN"})
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    with (root / ".env").open("a", encoding="utf-8") as file:
        file.write("\nTEST_CALLBACK_KEY=" + secrets.token_urlsafe(32))
        file.write("\nTEST_CALLBACK_TOKEN=" + secrets.token_urlsafe(32))
        file.write("\nFEISHU_MOXON_SECRET=" + secrets.token_urlsafe(32) + "\n")
    print("Prepared synthetic callback configuration")


if __name__ == "__main__":
    main()
