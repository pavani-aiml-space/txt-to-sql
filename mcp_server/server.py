"""MCP server exposing the NLQ-SQL agent as a single tool.

Purpose: let any MCP-compatible client (not just this project's own demos)
ask the agent a question. Needed to make the agent usable outside a direct
Python import. Works by wrapping ask() in one tool, query_properties.

Run with: python -m mcp_server.server
Inspect with the official MCP inspector: npx @modelcontextprotocol/inspector python -m mcp_server.server

Requires SUPABASE_DB_URL in .env -- there is no local database to fall back to.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server import MCPServer  # noqa: E402

from nlq.logging_config import configure_logging  # noqa: E402
from nlq.text_to_sql import ask as nlq_ask  # noqa: E402

configure_logging()

mcp = MCPServer("nlq-sql")


@mcp.tool()
def query_properties(question: str) -> dict:
    """Answer a natural-language question about the listings dataset by translating it to SQL and running it against Supabase."""
    result = nlq_ask(question)
    return {
        "question": result.question,
        "sql": result.sql,
        "mode": result.mode,
        "row_count": len(result.rows),
        "rows": result.rows,
    }


if __name__ == "__main__":
    mcp.run()
