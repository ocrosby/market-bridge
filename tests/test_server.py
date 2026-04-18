"""Tests for MCP server tool registration and basic tool calls."""

from fastmcp import Client

from market_bridge.server import mcp

EXPECTED_TOOLS = {
    "get_price_data",
    "get_volume_profile",
    "get_order_flow",
    "get_levels",
    "get_heatmap",
    "get_market_state",
}


async def test_list_tools():
    async with Client(mcp) as client:
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}
        assert EXPECTED_TOOLS.issubset(tool_names)


async def test_all_tools_callable_without_args():
    """Every tool should be callable with defaults and not error."""
    async with Client(mcp) as client:
        for tool_name in EXPECTED_TOOLS:
            result = await client.call_tool(tool_name, {})
            assert not result.is_error, f"{tool_name} returned error"


async def test_get_price_data_returns_expected_shape():
    async with Client(mcp) as client:
        result = await client.call_tool("get_price_data", {"symbol": "/ES"})
        assert not result.is_error


async def test_get_market_state_returns_session_info():
    async with Client(mcp) as client:
        result = await client.call_tool("get_market_state", {"symbol": "/ES"})
        assert not result.is_error


async def test_get_market_state_unknown_symbol():
    async with Client(mcp) as client:
        result = await client.call_tool("get_market_state", {"symbol": "/ZZ"})
        assert not result.is_error
