"""Exercise signed real HTTP callbacks and read the resulting task through MCP."""
import asyncio
import hashlib
import json
import os
import time
from uuid import uuid4

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    """Verify reject, dedupe, comment threading, paginated context and task release."""
    payload = {"schema": "2.0", "header": {"app_id": "app-a", "tenant_key": "tenant-a",
        "event_id": str(uuid4()), "event_type": "drive.notice.comment_add_v1",
        "token": os.environ["TEST_CALLBACK_TOKEN"]}, "event": {"is_mentioned": True,
        "comment_id": "commentA", "reply_id": "r1", "notice_meta": {"file_type": "docx",
        "file_token": "docA", "to_user_id": {"open_id": "bot-a"}}}}
    async with httpx.AsyncClient(trust_env=False, timeout=60) as client:
        challenge = await client.post("http://127.0.0.1:8001/events/a", json={"type": "url_verification",
                    "challenge": "synthetic-challenge", "token": os.environ["TEST_CALLBACK_TOKEN"]})
        assert challenge.status_code == 200 and challenge.json()["challenge"] == "synthetic-challenge"
        for index in range(3):
            # Deliver initial event twice, then one follow-up on the same comment.
            if index == 2:
                payload["header"]["event_id"] = str(uuid4())
                payload["event"]["reply_id"] = "r2"
            body = json.dumps(payload).encode()
            timestamp, nonce = str(int(time.time())), str(uuid4())
            signature = hashlib.sha256((timestamp + nonce + os.environ["TEST_CALLBACK_KEY"]).encode() + body).hexdigest()
            headers = {"X-Lark-Request-Timestamp": timestamp, "X-Lark-Request-Nonce": nonce,
                       "X-Lark-Signature": signature, "Content-Type": "application/json"}
            response = await client.post("http://127.0.0.1:8001/events/a", headers=headers, content=body)
            assert response.status_code == 200, response.text
        headers["X-Lark-Signature"] = "invalid"
        assert (await client.post("http://127.0.0.1:8001/events/a", headers=headers, content=body)).status_code != 200
    def factory(**kwargs):
        """Bypass workstation proxies for Docker loopback testing."""
        return httpx.AsyncClient(**kwargs, trust_env=False)
    async with streamablehttp_client("http://127.0.0.1:8000/mcp", headers={
            "Authorization": "Bearer " + os.environ["MCP_EMPLOYEE_ONE"]}, httpx_client_factory=factory) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("list_issues", {})
            tasks = [json.loads(item.text) for item in result.content if item.type == "text"]
            if len(tasks) == 1 and isinstance(tasks[0], list):
                tasks = tasks[0]
            task = next(t for t in tasks if t["document_url"] and t["document_url"].endswith("/docA"))
            result = await session.call_tool("get_issue_context", {"task_code": task["code"]})
            assert not result.isError, result
            context = json.loads(result.content[0].text)
            assert context["document"]["revision_id"] == 7
            assert len(context["document"]["comments"][0]["all_replies"]) == 2
            assert len(context["events"]) >= 2
            assert context["revision"] == len(context["events"])
            assert all("token" not in e["payload"]["header"] for e in context["events"])
    print("Signed callback, forged signature rejection, duplicate suppression, comment threading and document pagination passed")


if __name__ == "__main__":
    asyncio.run(main())
