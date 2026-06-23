from __future__ import annotations

import asyncio
import json
import shlex
from typing import Any


class TransportError(RuntimeError):
    pass


class JsonRpcError(TransportError):
    def __init__(self, error: dict[str, Any], response: dict[str, Any] | None = None) -> None:
        self.error = error
        self.response = response or {}
        message = error.get("message", "JSON-RPC error")
        code = error.get("code", "unknown")
        super().__init__(f"{code}: {message}")


class StdioTransport:
    def __init__(self, command: str, timeout: float = 10) -> None:
        self.command = command
        self.timeout = timeout
        self.process: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self.last_request_id: int | None = None
        self.last_response: dict[str, Any] | None = None
        self.response_history: list[dict[str, Any]] = []
        self.server_info: dict[str, Any] = {}
        self.capabilities: dict[str, Any] = {}
        self.initialize_result: dict[str, Any] | None = None
        self.initialize_elapsed_ms: float = 0

    async def start(self) -> None:
        if self.process is not None:
            return
        args = shlex.split(self.command)
        if not args:
            raise TransportError("Empty stdio command")
        self.process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def send_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self.last_request_id = request_id
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params

        await self._write_message(message)
        response = await self._read_message()
        self.last_response = response
        self.response_history.append(response)

        if response.get("id") != request_id:
            raise TransportError(f"Response id mismatch: expected {request_id}, got {response.get('id')}")
        if "error" in response:
            error = response["error"]
            if isinstance(error, dict):
                raise JsonRpcError(error, response)
            raise TransportError("JSON-RPC error field is not an object")
        if "result" not in response:
            raise TransportError("JSON-RPC response missing result")
        result = response["result"]
        if not isinstance(result, dict):
            raise TransportError("JSON-RPC result is not an object")
        return result

    async def send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        await self._write_message(message)

    async def initialize(self) -> dict[str, Any]:
        if self.initialize_result is not None:
            return self.initialize_result

        start = asyncio.get_running_loop().time()
        result = await self.send_request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "mcp-lighthouse", "version": "0.2.0"},
            },
        )
        self.initialize_elapsed_ms = (asyncio.get_running_loop().time() - start) * 1000
        self.initialize_result = result
        self.capabilities = result.get("capabilities") if isinstance(result.get("capabilities"), dict) else {}
        self.server_info = result.get("serverInfo") if isinstance(result.get("serverInfo"), dict) else {}
        await self.send_notification("notifications/initialized")
        return result

    async def send_raw_line(self, line: str) -> None:
        if not line.endswith("\n"):
            line += "\n"
        await self._ensure_started()
        assert self.process is not None
        if self.process.stdin is None:
            raise TransportError("Subprocess stdin is unavailable")
        self.process.stdin.write(line.encode("utf-8"))
        await self.process.stdin.drain()

    async def read_raw_response(self, timeout: float | None = None) -> dict[str, Any] | None:
        response = await self._read_message(timeout=timeout)
        self.last_response = response
        self.response_history.append(response)
        return response

    def is_running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    async def get_stderr(self) -> str:
        """Read any stderr output from the subprocess."""
        if self.process is None or self.process.stderr is None:
            return ""
        try:
            data = await asyncio.wait_for(self.process.stderr.read(4096), timeout=0.5)
            return data.decode("utf-8", errors="replace").strip()
        except (asyncio.TimeoutError, Exception):
            return ""

    async def close(self) -> None:
        if self.process is None:
            return
        if self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=2)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        self.process = None

    async def _ensure_started(self) -> None:
        if self.process is None or self.process.returncode is not None:
            self.process = None
            await self.start()

    async def _write_message(self, message: dict[str, Any]) -> None:
        await self._ensure_started()
        assert self.process is not None
        if self.process.stdin is None:
            raise TransportError("Subprocess stdin is unavailable")
        data = json.dumps(message, separators=(",", ":")) + "\n"
        self.process.stdin.write(data.encode("utf-8"))
        await self.process.stdin.drain()

    async def _read_message(self, timeout: float | None = None) -> dict[str, Any]:
        await self._ensure_started()
        assert self.process is not None
        if self.process.stdout is None:
            raise TransportError("Subprocess stdout is unavailable")
        try:
            line = await asyncio.wait_for(self.process.stdout.readline(), timeout=timeout or self.timeout)
        except asyncio.TimeoutError as exc:
            raise TransportError("Timed out waiting for JSON-RPC response") from exc
        if not line:
            raise TransportError("Subprocess closed stdout")
        try:
            response = json.loads(line.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise TransportError(f"Invalid JSON response: {line.decode('utf-8', errors='replace').strip()}") from exc
        if not isinstance(response, dict):
            raise TransportError("JSON-RPC response is not an object")
        return response
