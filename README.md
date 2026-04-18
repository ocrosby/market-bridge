# Market Bridge - Trading Data MCP Server

An MCP (Model Context Protocol) server that bridges trading platforms to Claude, enabling real-time /ES (S&P 500 E-mini futures) data analysis during conversations.

## Problem

Claude has no native connection to trading platforms like Bookmap, Tradovate, or Thinkorswim. Today, the only way to get /ES data into Claude is through manual CSV exports — a slow, disconnected workflow that prevents real-time analysis.

## Solution

Build an MCP server that acts as a bridge between trading platforms and Claude. Claude calls the MCP server like a tool, requesting price data, levels, volume nodes, and order flow in real time.

```
Bookmap / Tradovate / TOS  →  MCP Server  →  Claude
```

## Supported Platforms

| Platform       | Connection Method         | Priority |
|----------------|---------------------------|----------|
| Tradovate      | REST API + WebSocket API  | High     |
| Bookmap        | Data export / API         | Medium   |
| Thinkorswim    | thinkScript CSV export    | Low      |

## MCP Tools to Expose

The MCP server will expose the following tools for Claude to call:

- **get_price_data** - Current and historical /ES price (OHLCV) at configurable timeframes
- **get_volume_profile** - Volume-at-price / volume profile for a given session or range
- **get_order_flow** - Real-time order flow, delta, and cumulative delta
- **get_levels** - Key support/resistance levels, high-volume nodes, POC, VAH, VAL
- **get_heatmap** - Liquidity heatmap data (bid/ask depth from Bookmap)
- **get_market_state** - Current session info, market hours, overnight vs RTH context

## Project Plan

### Phase 1: Foundation
- [ ] Choose runtime and MCP SDK (Python or TypeScript)
- [ ] Scaffold MCP server with stdio transport
- [ ] Implement health check / ping tool
- [ ] Set up project structure, linting, and testing
- [ ] Register server in Claude Code MCP config for local development

### Phase 2: Tradovate Integration (Primary Data Source)
- [ ] Implement Tradovate OAuth2 authentication flow
- [ ] Connect to Tradovate WebSocket API for real-time /ES data
- [ ] Implement `get_price_data` tool (OHLCV at multiple timeframes)
- [ ] Implement `get_levels` tool (session high/low, POC, value area)
- [ ] Implement `get_order_flow` tool (delta, cumulative delta)
- [ ] Add reconnection logic and error handling for WebSocket drops
- [ ] Write integration tests against Tradovate demo account

### Phase 3: Bookmap Integration
- [ ] Research Bookmap API / data export capabilities
- [ ] Implement `get_heatmap` tool (bid/ask liquidity depth)
- [ ] Implement `get_volume_profile` tool from Bookmap data
- [ ] Handle Bookmap data format parsing and normalization

### Phase 4: Thinkorswim Integration
- [ ] Build CSV watcher for TOS thinkScript exports
- [ ] Parse and normalize TOS study data
- [ ] Expose TOS data through existing MCP tools as a fallback source

### Phase 5: Analysis and Polish
- [ ] Implement `get_market_state` tool (session context, RTH vs overnight)
- [ ] Add data caching layer to reduce API calls
- [ ] Support multiple instruments beyond /ES (e.g., /NQ, /CL)
- [ ] Add configurable alerts / threshold notifications
- [ ] Write documentation and usage examples

## Architecture

```
┌─────────────────────────────────────────────┐
│                Claude (LLM)                 │
│          calls MCP tools as needed          │
└──────────────────┬──────────────────────────┘
                   │ MCP Protocol (stdio/SSE)
┌──────────────────▼──────────────────────────┐
│          Market Bridge MCP Server            │
│  ┌─────────┐ ┌─────────┐ ┌──────────────┐  │
│  │Tradovate│ │Bookmap  │ │Thinkorswim   │  │
│  │Connector│ │Connector│ │CSV Watcher   │  │
│  └────┬────┘ └────┬────┘ └──────┬───────┘  │
│       │           │             │           │
│  ┌────▼───────────▼─────────────▼────────┐  │
│  │        Normalized Data Layer          │  │
│  │   (unified format across sources)     │  │
│  └───────────────────────────────────────┘  │
│  ┌───────────────────────────────────────┐  │
│  │           Cache / State               │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
                   │
    ┌──────────────┼──────────────┐
    ▼              ▼              ▼
Tradovate API   Bookmap       TOS CSV
(WebSocket)     (Export)      (File Watch)
```

## Getting Started

> **TODO** - Setup instructions will be added once Phase 1 is complete.

## License

MIT
