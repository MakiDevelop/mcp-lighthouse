from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .checks import all_checks, run_all_checks
from .reporter import render_markdown, render_terminal
from .transport import StdioTransport


VALID_CATEGORIES = ["protocol", "schema", "robustness", "best_practices", "performance"]


def main() -> None:
    parser = argparse.ArgumentParser(prog="mcp-lighthouse")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="scan an MCP server")
    scan_parser.add_argument("--stdio", required=True, help="stdio command to launch the MCP server")
    scan_parser.add_argument("--report", help="write a Markdown report to this path")
    scan_parser.add_argument("--category", choices=VALID_CATEGORIES, action="append", help="run only this check category")
    scan_parser.add_argument("--timeout", type=float, default=10, help="transport timeout in seconds")

    subparsers.add_parser("list", help="list registered checks")

    args = parser.parse_args()
    if args.command == "list":
        _list_checks()
        return
    if args.command == "scan":
        asyncio.run(_scan(args))


def _list_checks() -> None:
    for info in all_checks():
        print(f"{info.check_id:<28} {info.category:<15} {info.severity:<8} {info.name}")


async def _scan(args: argparse.Namespace) -> None:
    transport = StdioTransport(args.stdio, timeout=args.timeout)
    try:
        await transport.start()
        await transport.initialize()
        results = await run_all_checks(transport, categories=args.category)
        render_terminal(results, transport.server_info)
        if args.report:
            Path(args.report).write_text(render_markdown(results, transport.server_info), encoding="utf-8")
    finally:
        await transport.close()


if __name__ == "__main__":
    main()
