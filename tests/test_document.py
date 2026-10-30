"""Verify external document scopes, pagination and media using an isolated HTTP transport."""
import json

import httpx
import pytest

from bot_core.config import settings
from bot_core.feishu import read_document


@pytest.fixture
def configured(tmp_path, monkeypatch):
    """Inject synthetic identity and no real network credentials."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"bots": [{"code": "a", "app_id": "app", "secret_env": "TEST_SECRET",
                    "document_hosts": ["example.feishu.cn"], "allowed_documents": ["docA"]}],
                    "clients": [{"employee_code": "alice", "token_env": "TEST_TOKEN", "bots": ["a"]}]}))
    monkeypatch.setenv("BOT_CONFIG", str(path))
    monkeypatch.setenv("TEST_TOKEN", "x" * 40)
    monkeypatch.setenv("TEST_SECRET", "synthetic")
    settings.cache_clear()
    yield
    settings.cache_clear()


def test_document_media_and_scope(configured, monkeypatch):
    """Only declared document media is downloaded; comment replies are fully paginated."""
    missing_detail = False
    def respond(request):
        """Return two reply pages and one small synthetic image."""
        path = request.url.path
        if path.endswith("/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "synthetic"})
        if path.endswith("/raw_content"):
            data = {"content": "Synthetic document"}
        elif path.endswith("/blocks"):
            data = {"items": [{"block_id": "b1", "image": {"token": "imgA"}}], "has_more": False}
        elif path.endswith("/replies"):
            more = "page_token" not in request.url.params
            data = {"items": [{"reply_id": "r1" if more else "r2"}], "has_more": more, "page_token": "next"}
        elif path.endswith("/commentA"):
            if missing_detail:
                return httpx.Response(404, json={"code": 1069307, "msg": "not exist"})
            data = {"quote": "Original quote"}
        elif path.endswith("/comments"):
            data = {"items": [{"comment_id": "commentA", "quote": "Listed quote"}], "has_more": False}
        elif path.endswith("/download"):
            return httpx.Response(200, content=b"synthetic image", headers={"Content-Type": "image/png"})
        else:
            data = {"document": {"revision_id": 9}}
        return httpx.Response(200, json={"code": 0, "data": data})
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond)))
    value = read_document("a", "https://example.feishu.cn/docx/docA", ["commentA"], True)
    assert value["comments"][0]["quote"] == "Original quote"
    assert len(value["comments"][0]["all_replies"]) == 2
    assert value["images"][0]["mime"] == "image/png"
    missing_detail = True
    assert read_document("a", "https://example.feishu.cn/docx/docA", ["commentA"])["comments"][0]["quote"] == "Listed quote"
    with pytest.raises(ValueError, match="allowlist"):
        read_document("a", "https://example.feishu.cn/docx/other")
    with pytest.raises(ValueError, match="host"):
        read_document("a", "https://localhost/docx/docA")
    settings()["bots"][0]["document_policy"] = "bot_access"
    assert read_document("a", "https://example.feishu.cn/docx/other")["content"] == "Synthetic document"


def test_comment_platform_acl_policy():
    """A valid mention on an unlisted document can enter the queue in platform ACL mode."""
    from unittest.mock import patch
    from event_receiver.main import handle
    bot = {"app_id": "fixture", "tenant_key": "fixture", "open_id": "bot",
           "document_policy": "bot_access", "document_hosts": ["example.feishu.cn"]}
    payload = {"header": {"app_id": "fixture", "tenant_key": "fixture", "event_id": "id",
                          "event_type": "drive.notice.comment_add_v1"},
               "event": {"is_mentioned": True, "comment_id": "c1", "notice_meta": {
                   "file_token": "newDoc", "file_type": "docx", "to_user_id": {"open_id": "bot"}}}}
    with patch("event_receiver.main.bot_config", return_value=bot), patch("event_receiver.main.ingest", return_value=True) as save:
        assert handle("fixture", payload)
        assert save.call_args.args[4] == "https://example.feishu.cn/docx/newDoc"
