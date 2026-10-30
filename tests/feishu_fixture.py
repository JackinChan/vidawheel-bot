"""Synthetic Feishu endpoints for local Docker acceptance; never route production traffic here."""
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route


async def respond(request):
    """Serve deterministic document, block, quote and multi-page reply payloads."""
    path = request.url.path
    if path.endswith("/tenant_access_token/internal"):
        return JSONResponse({"code": 0, "tenant_access_token": "synthetic-fixture-token"})
    if request.headers.get("authorization") != "Bearer synthetic-fixture-token":
        return JSONResponse({"code": 999, "msg": "authentication required"}, status_code=403)
    if path.endswith("/raw_content"):
        data = {"content": "Synthetic Chat interface: stars must remain at three after completion."}
    elif path.endswith("/blocks"):
        data = {"items": [{"block_id": "b1", "block_type": 2, "text": {"elements": [{"text_run": {"content": "Fixture paragraph"}}]}}], "has_more": False}
    elif path.endswith("/replies"):
        more = not bool(request.query_params.get("page_token"))
        data = {"items": [{"reply_id": "r1" if more else "r2", "content": {"elements": [
            {"type": "text_run", "text_run": {"text": "Investigate star reset" if more else "Additional reproduction step"}}]}}],
            "has_more": more, "page_token": "next" if more else ""}
    elif "/comments/" in path:
        data = {"comment_id": "commentA", "quote": "Topic star count", "is_whole": False}
    else:
        data = {"document": {"document_id": "docA", "revision_id": 7}}
    return JSONResponse({"code": 0, "data": data})


app = Starlette(routes=[Route("/{path:path}", respond, methods=["GET", "POST"])])
