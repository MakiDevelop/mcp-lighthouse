# MCP Lighthouse

Audit tool for [MCP](https://modelcontextprotocol.io) servers. Run 21 automated checks across 5 dimensions and get a compliance score — like Lighthouse, but for your MCP server.

```
MCP Lighthouse — my-server v1.0

  Protocol    ████████████████████  100
  Schema      ██████████████░░░░░░   70
  Robustness  ████████████████░░░░   75
  Practices   ██████████░░░░░░░░░░   50
  Performance ████████████████████  100

  Overall Score: 83/100

  21 checks: 17 passed, 2 warnings, 2 failed
```

## Why

You built an MCP server. It works in Claude Code. But does it:
- Return proper JSON-RPC 2.0 responses?
- Include `inputSchema` on every tool?
- Handle invalid tool names without crashing?
- Respond to `initialize` within a reasonable time?

MCP Lighthouse tests all of this automatically.

## Install

```bash
pip install mcp-lighthouse
```

Or from source:

```bash
git clone https://github.com/MakiDevelop/mcp-lighthouse.git
cd mcp-lighthouse
pip install -e .
```

## Quick Start

```bash
# Audit an MCP server via stdio
mcp-lighthouse scan --stdio "python my_server.py"
mcp-lighthouse scan --stdio "npx @modelcontextprotocol/server-filesystem /"

# Only run specific category
mcp-lighthouse scan --stdio "python my_server.py" --category protocol

# Export markdown report
mcp-lighthouse scan --stdio "python my_server.py" --report audit.md

# List all checks
mcp-lighthouse list
```

## Checks (21 total)

### Protocol Compliance (5 checks, 40% weight) — critical

| Check | What it tests |
|-------|---------------|
| `proto-init` | Server responds to `initialize` with valid protocolVersion + capabilities + serverInfo |
| `proto-init-version` | protocolVersion is a known version (2024-11-05, 2025-03-26, 2025-06-18, 2025-11-25) |
| `proto-jsonrpc-version` | All responses include `"jsonrpc": "2.0"` |
| `proto-id-match` | Response `id` matches request `id` |
| `proto-error-format` | Error responses have `code` (int) + `message` (string) |

### Schema Quality (6 checks, 25% weight) — warning

| Check | What it tests |
|-------|---------------|
| `schema-tools-list` | `tools/list` returns non-empty tools array |
| `schema-tool-name` | Every tool has a non-empty `name` |
| `schema-tool-description` | Every tool has a description (>10 chars) |
| `schema-tool-input-schema` | Every tool has `inputSchema` with `type: "object"` |
| `schema-required-fields` | `inputSchema` with properties has a `required` array |
| `schema-no-duplicate-tools` | No duplicate tool names |

### Robustness (4 checks, 20% weight) — warning

| Check | What it tests |
|-------|---------------|
| `robust-unknown-method` | Server returns `-32601` for unknown method |
| `robust-invalid-tool` | `tools/call` with non-existent tool returns error (not crash) |
| `robust-missing-args` | `tools/call` with missing required args returns error |
| `robust-malformed-json` | Server handles malformed JSON without crashing |

### Best Practices (4 checks, 10% weight) — info

| Check | What it tests |
|-------|---------------|
| `bp-tool-name-format` | Tool names use snake_case or kebab-case |
| `bp-description-length` | Tool descriptions are 20-500 chars |
| `bp-server-info` | `serverInfo` includes both `name` and `version` |
| `bp-capabilities-declared` | Server declares at least one capability |

### Performance (2 checks, 5% weight) — info

| Check | What it tests |
|-------|---------------|
| `perf-init-time` | `initialize` completes in < 5 seconds |
| `perf-tools-list-time` | `tools/list` responds in < 3 seconds |

## Scoring

- **Overall**: Weighted average of category scores (protocol 40%, schema 25%, robustness 20%, practices 10%, performance 5%)
- **Per category**: (passed checks / total checks) * 100
- A single critical failure in Protocol drops that category to 0

## CLI Reference

```
mcp-lighthouse scan [OPTIONS]
  --stdio COMMAND       Server command to spawn (required for now)
  --category CATEGORY   Only run checks in this category
  --timeout SECONDS     Per-check timeout (default: 10)
  --verbose             Show detailed output
  --report PATH         Write markdown report

mcp-lighthouse list
  Lists all available checks
```

## License

MIT
