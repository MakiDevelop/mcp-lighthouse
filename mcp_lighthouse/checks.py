from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .transport import JsonRpcError, TransportError


KNOWN_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}


@dataclass
class CheckResult:
    check_id: str
    name: str
    category: str
    severity: str
    passed: bool
    message: str
    details: str = ""
    elapsed_ms: float = 0


@dataclass
class CheckInfo:
    check_id: str
    name: str
    category: str
    severity: str
    func: Callable[[Any], Awaitable[CheckResult]]


_checks: list[CheckInfo] = []


def check(id: str, name: str, category: str, severity: str):
    def decorator(func: Callable[[Any], Awaitable[CheckResult]]):
        _checks.append(CheckInfo(id, name, category, severity, func))
        return func

    return decorator


async def run_all_checks(transport: Any, categories: list[str] | None = None) -> list[CheckResult]:
    selected = set(categories or [])
    results: list[CheckResult] = []
    for info in _checks:
        if selected and info.category not in selected:
            continue
        if not transport.is_running():
            results.append(CheckResult(
                info.check_id, info.name, info.category, info.severity,
                False, "Skipped: server process died", details="subprocess_dead",
            ))
            continue
        start = _now_ms()
        try:
            result = await info.func(transport)
            if not result.elapsed_ms:
                result.elapsed_ms = _now_ms() - start
        except Exception as exc:
            result = CheckResult(
                info.check_id,
                info.name,
                info.category,
                info.severity,
                False,
                f"Check failed: {exc}",
                details=type(exc).__name__,
                elapsed_ms=_now_ms() - start,
            )
        results.append(result)
    return results


def all_checks() -> list[CheckInfo]:
    return list(_checks)


def _now_ms() -> float:
    import time

    return time.perf_counter() * 1000


def _result(info_id: str, passed: bool, message: str, details: str = "", elapsed_ms: float = 0) -> CheckResult:
    info = next(item for item in _checks if item.check_id == info_id)
    return CheckResult(info.check_id, info.name, info.category, info.severity, passed, message, details, elapsed_ms)


async def _tools(transport: Any) -> list[dict[str, Any]]:
    if not hasattr(transport, "_tools_cache"):
        result = await transport.send_request("tools/list")
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise TransportError("tools/list result.tools is not an array")
        transport._tools_cache = [tool for tool in tools if isinstance(tool, dict)]
    return transport._tools_cache


@check("proto-init", "Initialize response", "protocol", "critical")
async def proto_init(transport: Any) -> CheckResult:
    result = await transport.initialize()
    ok = (
        isinstance(result.get("protocolVersion"), str)
        and isinstance(result.get("capabilities"), dict)
        and isinstance(result.get("serverInfo"), dict)
    )
    return _result("proto-init", ok, "Server initializes correctly" if ok else "Initialize response is missing required fields")


@check("proto-init-version", "Protocol version", "protocol", "critical")
async def proto_init_version(transport: Any) -> CheckResult:
    result = await transport.initialize()
    version = result.get("protocolVersion")
    ok = version in KNOWN_PROTOCOL_VERSIONS
    return _result("proto-init-version", ok, f"Protocol version {version} is known" if ok else f"Unknown protocol version: {version}")


@check("proto-jsonrpc-version", "JSON-RPC version", "protocol", "critical")
async def proto_jsonrpc_version(transport: Any) -> CheckResult:
    await transport.send_request("tools/list")
    bad = [resp for resp in transport.response_history if resp.get("jsonrpc") != "2.0"]
    return _result("proto-jsonrpc-version", not bad, "All responses use JSON-RPC 2.0" if not bad else f"{len(bad)} responses missing jsonrpc 2.0")


@check("proto-id-match", "Response ID matching", "protocol", "critical")
async def proto_id_match(transport: Any) -> CheckResult:
    await transport.send_request("tools/list")
    response = transport.last_response or {}
    ok = response.get("id") == transport.last_request_id
    return _result("proto-id-match", ok, "Response id matches request id" if ok else "Response id does not match request id")


@check("proto-error-format", "Error format", "protocol", "critical")
async def proto_error_format(transport: Any) -> CheckResult:
    try:
        await transport.send_request("lighthouse/unknown")
    except JsonRpcError as exc:
        error = exc.error
        ok = isinstance(error.get("code"), int) and isinstance(error.get("message"), str)
        return _result("proto-error-format", ok, "Error response has code and message" if ok else "Error response has invalid shape")
    return _result("proto-error-format", False, "Unknown method did not return a JSON-RPC error")


@check("schema-tools-list", "Tools list", "schema", "warning")
async def schema_tools_list(transport: Any) -> CheckResult:
    tools = await _tools(transport)
    return _result("schema-tools-list", bool(tools), f"tools/list returned {len(tools)} tools" if tools else "tools/list returned no tools")


@check("schema-tool-name", "Tool names present", "schema", "warning")
async def schema_tool_name(transport: Any) -> CheckResult:
    tools = await _tools(transport)
    bad = [tool for tool in tools if not isinstance(tool.get("name"), str) or not tool["name"].strip()]
    return _result("schema-tool-name", not bad, "Every tool has a non-empty name" if not bad else f"{len(bad)} tools have missing names")


@check("schema-tool-description", "Tool descriptions present", "schema", "warning")
async def schema_tool_description(transport: Any) -> CheckResult:
    tools = await _tools(transport)
    bad = [tool for tool in tools if not isinstance(tool.get("description"), str) or len(tool["description"].strip()) <= 10]
    return _result("schema-tool-description", not bad, "Every tool has a useful description" if not bad else f"{len(bad)} tools have short or missing descriptions")


@check("schema-tool-input-schema", "Tool input schemas", "schema", "warning")
async def schema_tool_input_schema(transport: Any) -> CheckResult:
    tools = await _tools(transport)
    bad = [tool for tool in tools if not isinstance(tool.get("inputSchema"), dict) or tool["inputSchema"].get("type") != "object"]
    return _result("schema-tool-input-schema", not bad, "Every tool inputSchema is an object" if not bad else f"{len(bad)} tools have invalid inputSchema")


@check("schema-required-fields", "Required fields", "schema", "warning")
async def schema_required_fields(transport: Any) -> CheckResult:
    tools = await _tools(transport)
    bad = []
    for tool in tools:
        schema = tool.get("inputSchema")
        if isinstance(schema, dict) and schema.get("properties") and "required" not in schema:
            bad.append(tool.get("name", "<unnamed>"))
    return _result("schema-required-fields", not bad, "Schemas with properties declare required fields" if not bad else f"{len(bad)} schemas with properties omit required")


@check("schema-no-duplicate-tools", "No duplicate tools", "schema", "warning")
async def schema_no_duplicate_tools(transport: Any) -> CheckResult:
    tools = await _tools(transport)
    names: list[str] = [tool["name"] for tool in tools if isinstance(tool.get("name"), str)]
    duplicates = sorted(n for n in set(names) if names.count(n) > 1)
    return _result("schema-no-duplicate-tools", not duplicates, "No duplicate tool names" if not duplicates else f"Duplicate tool names: {', '.join(duplicates)}")


@check("robust-unknown-method", "Unknown method handling", "robustness", "warning")
async def robust_unknown_method(transport: Any) -> CheckResult:
    try:
        await transport.send_request("foo/bar")
    except JsonRpcError as exc:
        code = exc.error.get("code")
        if code == -32601:
            return _result("robust-unknown-method", True, "Unknown method returns -32601")
        return _result("robust-unknown-method", True, f"Unknown method returns error (code {code}, recommend -32601)")
    return _result("robust-unknown-method", False, "Unknown method did not return an error")


@check("robust-invalid-tool", "Invalid tool handling", "robustness", "warning")
async def robust_invalid_tool(transport: Any) -> CheckResult:
    try:
        await transport.send_request("tools/call", {"name": "__mcp_lighthouse_missing_tool__", "arguments": {}})
    except JsonRpcError:
        return _result("robust-invalid-tool", transport.is_running(), "Invalid tool returns an error without crashing")
    except TransportError as exc:
        return _result("robust-invalid-tool", False, f"Invalid tool broke transport: {exc}")
    result = (transport.last_response or {}).get("result", {})
    if isinstance(result, dict) and result.get("isError"):
        return _result("robust-invalid-tool", True, "Invalid tool reported error via isError flag")
    return _result("robust-invalid-tool", False, "Invalid tool unexpectedly succeeded")


@check("robust-missing-args", "Missing arguments handling", "robustness", "warning")
async def robust_missing_args(transport: Any) -> CheckResult:
    tools = await _tools(transport)
    candidate = None
    for tool in tools:
        schema = tool.get("inputSchema")
        if isinstance(schema, dict) and schema.get("required"):
            candidate = tool
            break
    if candidate is None:
        return _result("robust-missing-args", True, "No tool with required arguments found")
    try:
        await transport.send_request("tools/call", {"name": candidate.get("name"), "arguments": {}})
    except JsonRpcError:
        return _result("robust-missing-args", transport.is_running(), "Missing required arguments return an error")
    result = (transport.last_response or {}).get("result", {})
    if isinstance(result, dict) and result.get("isError"):
        return _result("robust-missing-args", True, "Missing args reported error via isError flag")
    return _result("robust-missing-args", False, f"{candidate.get('name')} accepted missing required arguments")


@check("robust-malformed-json", "Malformed JSON handling", "robustness", "warning")
async def robust_malformed_json(transport: Any) -> CheckResult:
    await transport.send_raw_line('{"jsonrpc":"2.0","id":999,"method":')
    try:
        response = await transport.read_raw_response(timeout=1)
    except TransportError:
        ok = transport.is_running()
        return _result("robust-malformed-json", ok, "Malformed JSON did not crash server" if ok else "Server stopped after malformed JSON")
    error = response.get("error") if response else None
    ok = isinstance(error, dict) and error.get("code") == -32700
    return _result("robust-malformed-json", ok, "Malformed JSON returns parse error" if ok else "Malformed JSON response is not a parse error")


@check("bp-tool-name-format", "Tool name format", "best_practices", "info")
async def bp_tool_name_format(transport: Any) -> CheckResult:
    tools = await _tools(transport)
    pattern = re.compile(r"^[a-z0-9]+([_-][a-z0-9]+)*$")
    bad = [tool.get("name", "") for tool in tools if not pattern.match(str(tool.get("name", "")))]
    return _result("bp-tool-name-format", not bad, "Tool names use snake_case or kebab-case" if not bad else f"Non-standard tool names: {', '.join(bad)}")


@check("bp-description-length", "Description length", "best_practices", "info")
async def bp_description_length(transport: Any) -> CheckResult:
    tools = await _tools(transport)
    bad = []
    for tool in tools:
        description = tool.get("description")
        if not isinstance(description, str) or not 20 <= len(description.strip()) <= 500:
            bad.append(str(tool.get("name", "<unnamed>")))
    return _result("bp-description-length", not bad, "Tool descriptions are 20-500 chars" if not bad else f"{len(bad)} tool descriptions are outside 20-500 chars")


@check("bp-server-info", "Server info", "best_practices", "info")
async def bp_server_info(transport: Any) -> CheckResult:
    result = await transport.initialize()
    server_info = result.get("serverInfo")
    ok = isinstance(server_info, dict) and bool(server_info.get("name")) and bool(server_info.get("version"))
    return _result("bp-server-info", ok, "serverInfo includes name and version" if ok else "serverInfo should include name and version")


@check("bp-capabilities-declared", "Capabilities declared", "best_practices", "info")
async def bp_capabilities_declared(transport: Any) -> CheckResult:
    result = await transport.initialize()
    capabilities = result.get("capabilities")
    ok = isinstance(capabilities, dict) and bool(capabilities)
    return _result("bp-capabilities-declared", ok, "Server declares at least one capability" if ok else "Server declares no capabilities")


@check("perf-init-time", "Initialize time", "performance", "info")
async def perf_init_time(transport: Any) -> CheckResult:
    await transport.initialize()
    elapsed = transport.initialize_elapsed_ms
    ok = elapsed < 5000
    return _result("perf-init-time", ok, f"Initialize completed in {elapsed:.0f} ms", elapsed_ms=elapsed)


@check("perf-tools-list-time", "Tools list time", "performance", "info")
async def perf_tools_list_time(transport: Any) -> CheckResult:
    start = _now_ms()
    await transport.send_request("tools/list")
    elapsed = _now_ms() - start
    ok = elapsed < 3000
    return _result("perf-tools-list-time", ok, f"tools/list completed in {elapsed:.0f} ms", elapsed_ms=elapsed)
