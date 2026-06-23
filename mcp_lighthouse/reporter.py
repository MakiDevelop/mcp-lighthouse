from __future__ import annotations

from collections import defaultdict
from typing import Any

from .checks import CheckResult


CATEGORY_WEIGHTS = {
    "protocol": 40,
    "schema": 25,
    "robustness": 20,
    "best_practices": 10,
    "performance": 5,
}

CATEGORY_LABELS = {
    "protocol": "Protocol",
    "schema": "Schema",
    "robustness": "Robustness",
    "best_practices": "Practices",
    "performance": "Performance",
}


def category_scores(results: list[CheckResult]) -> dict[str, float]:
    grouped: dict[str, list[CheckResult]] = defaultdict(list)
    for result in results:
        grouped[result.category].append(result)
    scores: dict[str, float] = {}
    for category in CATEGORY_WEIGHTS:
        items = grouped.get(category, [])
        scores[category] = 100.0 if not items else sum(1 for item in items if item.passed) / len(items) * 100
    return scores


def overall_score(results: list[CheckResult]) -> int:
    scores = category_scores(results)
    executed = {r.category for r in results}
    if not executed:
        return 0
    total = sum(CATEGORY_WEIGHTS[cat] for cat in executed if cat in CATEGORY_WEIGHTS)
    if total == 0:
        return 0
    weighted = sum(scores[cat] * CATEGORY_WEIGHTS.get(cat, 0) for cat in executed) / total
    return round(weighted)


def render_terminal(results: list[CheckResult], server_info: dict[str, Any] | None = None) -> None:
    try:
        from rich.console import Console
        from rich.text import Text
    except ImportError:
        print(render_plain(results, server_info))
        return

    console = Console()
    name = (server_info or {}).get("name", "unknown-server")
    version = (server_info or {}).get("version", "unknown")
    console.print(f"[bold]MCP Lighthouse[/bold] — {name} v{version}\n")

    scores = category_scores(results)
    for category, score in scores.items():
        filled = round(score / 5)
        bar = "█" * filled + "░" * (20 - filled)
        console.print(f"  {CATEGORY_LABELS[category]:<11} [cyan]{bar}[/cyan]  {score:>3.0f}")

    console.print(f"\n  [bold]Overall Score:[/bold] {overall_score(results)}/100\n")

    for result in results:
        icon = "✅" if result.passed else ("❌" if result.severity == "critical" else "⚠️")
        style = "green" if result.passed else ("red" if result.severity == "critical" else "yellow")
        line = Text(f"  {icon} {result.check_id:<26} {result.message}", style=style)
        console.print(line)

    passed = sum(1 for result in results if result.passed)
    warnings = sum(1 for result in results if not result.passed and result.severity != "critical")
    failed = sum(1 for result in results if not result.passed and result.severity == "critical")
    console.print(f"\n  {len(results)} checks: {passed} passed, {warnings} warnings, {failed} failed")


def render_plain(results: list[CheckResult], server_info: dict[str, Any] | None = None) -> str:
    name = (server_info or {}).get("name", "unknown-server")
    version = (server_info or {}).get("version", "unknown")
    lines = [f"MCP Lighthouse — {name} v{version}", ""]
    for category, score in category_scores(results).items():
        filled = round(score / 5)
        lines.append(f"  {CATEGORY_LABELS[category]:<11} {'#' * filled}{'.' * (20 - filled)}  {score:.0f}")
    lines.append("")
    lines.append(f"  Overall Score: {overall_score(results)}/100")
    lines.append("")
    for result in results:
        icon = "PASS" if result.passed else ("FAIL" if result.severity == "critical" else "WARN")
        lines.append(f"  {icon:<4} {result.check_id:<26} {result.message}")
    return "\n".join(lines)


def render_markdown(results: list[CheckResult], server_info: dict[str, Any] | None = None) -> str:
    name = (server_info or {}).get("name", "unknown-server")
    version = (server_info or {}).get("version", "unknown")
    lines = [
        f"# MCP Lighthouse Report — {name} v{version}",
        "",
        f"Overall Score: **{overall_score(results)}/100**",
        "",
        "## Category Scores",
        "",
        "| Category | Score |",
        "|---|---:|",
    ]
    for category, score in category_scores(results).items():
        lines.append(f"| {CATEGORY_LABELS[category]} | {score:.0f} |")

    lines.extend(
        [
            "",
            "## Checks",
            "",
            "| Status | Check | Category | Severity | Message | Elapsed |",
            "|---|---|---|---|---|---:|",
        ]
    )
    for result in results:
        status = "Passed" if result.passed else "Failed"
        lines.append(
            f"| {status} | `{result.check_id}` | {result.category} | {result.severity} | "
            f"{_escape(result.message)} | {result.elapsed_ms:.0f} ms |"
        )

    failures = [result for result in results if not result.passed]
    if failures:
        lines.extend(["", "## Recommendations", ""])
        for result in failures:
            lines.append(f"- `{result.check_id}`: {_recommendation(result)}")

    return "\n".join(lines) + "\n"


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _recommendation(result: CheckResult) -> str:
    recommendations = {
        "protocol": "Fix JSON-RPC protocol handling before relying on this server in automated clients.",
        "schema": "Tighten tool metadata and JSON Schema so clients can validate calls correctly.",
        "robustness": "Return JSON-RPC errors for invalid input while keeping the server process alive.",
        "best_practices": "Improve metadata quality for better discoverability and client compatibility.",
        "performance": "Profile startup or request handling and remove avoidable blocking work.",
    }
    return recommendations.get(result.category, "Review the failing behavior and add a regression test.")
