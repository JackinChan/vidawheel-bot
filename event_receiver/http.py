"""Authenticated Feishu HTTP callback alternative, using the official SDK verifier."""
import asyncio
import json
import os
import time

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from starlette.routing import Route

from bot_core.config import bot_config
from event_receiver.main import handle


def dispatch(code: str, body: bytes, headers: dict):
    """Verify signature/token before dispatching an event and durably acknowledging it."""
    import json
    import lark_oapi as lark
    from lark_oapi.core.model import RawRequest
    bot = bot_config(code)
    key = os.environ[bot["encrypt_key_env"]]
    verification = os.environ[bot["verification_token_env"]]
    if not key or not verification:
        raise ValueError("Callback authentication is not configured")

    def receive(event):
        """Forward verified SDK envelopes into the shared dispatcher."""
        handle(code, json.loads(lark.JSON.marshal(event)))

    handler = (lark.EventDispatcherHandler.builder(key, verification)
               .register_p2_im_message_receive_v1(receive)
               .register_p2_drive_notice_comment_add_v1(receive).build())
    raw = RawRequest()
    raw.uri = "/events/" + code
    raw.headers = headers
    raw.body = body
    return handler.do(raw)


async def callback(request: Request):
    """Bound request size and freshness; reject unauthenticated or malformed callbacks."""
    try:
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1024 * 1024:
                return JSONResponse({"error": "event too large"}, status_code=413)
        timestamp = request.headers.get("x-lark-request-timestamp", "")
        challenge = json.loads(body).get("type") == "url_verification"
        # The initial URL challenge is authenticated by the SDK's verification token;
        # business callbacks additionally require a fresh signed timestamp.
        if not challenge and abs(time.time() - int(timestamp)) > 300:
            return JSONResponse({"error": "stale request"}, status_code=401)
        # SDK uses canonical Feishu header names, while ASGI headers are lowercase.
        headers = {"X-Lark-Request-Timestamp": timestamp,
                   "X-Lark-Request-Nonce": request.headers.get("x-lark-request-nonce", ""),
                   "X-Lark-Signature": request.headers.get("x-lark-signature", "")}
        result = await asyncio.to_thread(dispatch, request.path_params["bot"], bytes(body), headers)
        return Response(result.content, status_code=result.status_code, media_type="application/json")
    except (ValueError, KeyError, StopIteration):
        return JSONResponse({"error": "invalid event"}, status_code=400)


async def health(request):
    """Expose process readiness without credentials or company data."""
    return JSONResponse({"status": "ok"})


app = Starlette(routes=[Route("/events/{bot}", callback, methods=["POST"]), Route("/health", health)])
