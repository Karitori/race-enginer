from typing import Any

from langchain_core.tools import tool

from db.contracts import TelemetryRepository
from utils.strategy_snapshot import collect_strategy_snapshot


def build_strategy_snapshot_tool(repository: TelemetryRepository):
    """Build a repository-bound LangChain tool for strategy snapshot collection."""

    @tool("collect_strategy_snapshot")
    def collect_strategy_snapshot_tool() -> dict[str, Any]:
        """Return latest strategy-critical telemetry snapshot from the local DB."""
        return collect_strategy_snapshot(repository)

    return collect_strategy_snapshot_tool

