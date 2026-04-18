from fastmcp import Client

from market_bridge.server import mcp


async def test_list_tools():
    async with Client(mcp) as client:
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}
        assert "get_price_data" in tool_names
        assert "get_volume_profile" in tool_names
        assert "get_order_flow" in tool_names
        assert "get_levels" in tool_names
        assert "get_heatmap" in tool_names
        assert "get_market_state" in tool_names


async def test_get_price_data_returns_stub():
    async with Client(mcp) as client:
        result = await client.call_tool("get_price_data", {"symbol": "/ES"})
        assert not result.is_error


async def test_get_market_state_returns_stub():
    async with Client(mcp) as client:
        result = await client.call_tool("get_market_state", {"symbol": "/ES"})
        assert not result.is_error
