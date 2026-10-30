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
            data = {"quote": "Original quote"}
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
    with pytest.raises(ValueError, match="allowlist"):
        read_document("a", "https://example.feishu.cn/docx/other")
    with pytest.raises(ValueError, match="host"):
        read_document("a", "https://localhost/docx/docA")
