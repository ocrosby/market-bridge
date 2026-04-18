from fastmcp import FastMCP

from market_bridge.tools.price import register_price_tools
from market_bridge.tools.volume import register_volume_tools
from market_bridge.tools.order_flow import register_order_flow_tools
from market_bridge.tools.levels import register_levels_tools
from market_bridge.tools.heatmap import register_heatmap_tools
from market_bridge.tools.market_state import register_market_state_tools

mcp = FastMCP("Market Bridge")

register_price_tools(mcp)
register_volume_tools(mcp)
register_order_flow_tools(mcp)
register_levels_tools(mcp)
register_heatmap_tools(mcp)
register_market_state_tools(mcp)


def main():
    mcp.run()
