"""Exercise actual remote MCP HTTP transport against a running local container."""
import asyncio
import os

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    """Check anonymous rejection and authenticated tools over the same public MCP route."""
    url = os.environ.get("SMOKE_MCP_URL", "http://127.0.0.1:8000/mcp")
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert response.status_code == 401, response.status_code
        response = await client.post(url, headers={"Authorization": "Bearer invalid-credential"},
                                     json={"jsonrpc": "2.0", "id": 2, "method": "initialize"})
        assert response.status_code == 401, response.status_code
    headers = {"Authorization": "Bearer " + os.environ["MCP_EMPLOYEE_ONE"]}
    def local_client(**kwargs):
        """Avoid workstation proxy settings for loopback acceptance requests."""
        return httpx.AsyncClient(**kwargs, trust_env=False)

    async with streamablehttp_client(url, headers=headers, httpx_client_factory=local_client) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert len(tools.tools) == 8
            listing = await session.call_tool("list_issues", {})
            assert not listing.isError
            claim = await session.call_tool("claim_issue", {})
            assert not claim.isError
            import json
            result = json.loads(claim.content[0].text)
            task = result["task"]
            assert task is not None
            context = await session.call_tool("get_issue_context", {"task_code": task["code"], "include_document": False})
            assert not context.isError
            args = {"task_code": task["code"], "lease_token": task["lease_token"]}
            assert not (await session.call_tool("renew_issue", args)).isError
            args["analysis"] = "Synthetic HTTP transport test completed; no Feishu writes."
            assert not (await session.call_tool("submit_analysis", args)).isError
    print("HTTP MCP smoke passed: anonymous rejection, tools, list, claim, context, renew, submit")


if __name__ == "__main__":
    asyncio.run(main())
