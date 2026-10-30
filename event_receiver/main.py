"""Run one official Feishu WebSocket client per configured application."""
import json
import logging
import multiprocessing
import os
import re

from bot_core.config import settings, bot_config
from bot_core.store import ingest

log = logging.getLogger(__name__)


class SDKLogFilter(logging.Filter):
    """Remove temporary connection credentials from SDK-generated log messages."""

    def filter(self, record):
        """Keep operational failures while redacting signed WebSocket query parameters."""
        record.msg = re.sub(r"wss://\S+", "wss://<redacted>", record.getMessage())
        record.args = ()
        return True


def handle(code: str, payload: dict) -> bool:
    """Filter scoped mentions and persist before acknowledging the platform event."""
    payload = json.loads(json.dumps(payload))
    # Callback verification material is not business context and must never be persisted.
    payload.pop("token", None)
    payload.get("header", {}).pop("token", None)
    bot = bot_config(code)
    header, event = payload.get("header", {}), payload.get("event", {})
    if header.get("app_id") != bot["app_id"] or header.get("tenant_key") != bot["tenant_key"]:
        raise ValueError("Event application or tenant mismatch")
    event_id = header.get("event_id")
    if not event_id:
        raise ValueError("Missing event identity")
    kind = header.get("event_type")
    if kind == "im.message.receive_v1":
        message = event.get("message", {})
        if message.get("chat_id") not in bot.get("allowed_chats", []):
            return False
        if message.get("message_type") != "text":
            return False
        mentioned = any(m.get("id", {}).get("open_id") == bot["open_id"]
                        for m in message.get("mentions", []))
        if not mentioned:
            return False
        content = json.loads(message.get("content", "{}"))
        question = content.get("text", "")
        urls = re.findall(r"https://[^\s<>\"\u3002]+", question)
        document_url = next((url for url in urls if "/wiki/" in url or "/docx/" in url), None)
        thread_key = "im:" + str(message.get("root_id") or message.get("message_id") or event_id)
    elif kind == "drive.notice.comment_add_v1":
        notice = event.get("notice_meta", {})
        if not event.get("is_mentioned") or notice.get("to_user_id", {}).get("open_id") != bot["open_id"]:
            return False
        token = notice.get("file_token", "")
        if notice.get("file_type") != "docx" or not token.isalnum():
            return False
        if token not in bot.get("allowed_documents", []):
            return False
        comment = event.get("comment_id", "")
        if not comment.isalnum():
            raise ValueError("Invalid comment identity")
        document_url = "https://" + bot["document_hosts"][0] + "/docx/" + token
        question = "Document comment mention: " + comment + "; reply: " + str(event.get("reply_id", ""))
        thread_key = "comment:" + token + ":" + comment
    else:
        # Unregistered event types must not create tasks.
        return False
    if not question.strip():
        return False
    created = ingest(code, event_id, payload, question, document_url, thread_key)
    log.info("Event committed bot=%s event=%s task_created=%s", code, event_id, created)
    return created


def run_bot(code: str):
    """Block on the SDK client; exceptions exit the worker for supervisor recovery."""
    import lark_oapi as lark

    bot = bot_config(code)
    logging.getLogger("Lark").addFilter(SDKLogFilter())

    def receive(data):
        """Convert the SDK event to a plain envelope without logging its content."""
        handle(code, json.loads(lark.JSON.marshal(data)))

    dispatcher = (lark.EventDispatcherHandler.builder("", "")
                  .register_p2_im_message_receive_v1(receive)
                  .register_p2_drive_notice_comment_add_v1(receive).build())
    client = lark.ws.Client(bot["app_id"], os.environ[bot["secret_env"]], event_handler=dispatcher,
                            log_level=lark.LogLevel.WARNING)
    client.start()


def main():
    """Supervise all app connections; fail the container if any connection worker exits."""
    logging.basicConfig(level=logging.INFO)
    processes = [multiprocessing.Process(target=run_bot, args=(bot["code"],)) for bot in settings()["bots"]]
    try:
        for process in processes:
            process.start()
        while True:
            for process in processes:
                process.join(timeout=1)
                if not process.is_alive():
                    raise RuntimeError("Feishu worker stopped")
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
        for process in processes:
            if process.pid:
                process.join(timeout=10)


if __name__ == "__main__":
    main()
