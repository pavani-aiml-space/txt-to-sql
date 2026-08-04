"""End-to-end CLI walkthrough of the NLQ-SQL agent, no MCP client needed.

Purpose: try the agent from the terminal. Needed as the fastest way to see
a question actually answered without setting up an MCP client. Works by
calling ask() with either a scripted list of questions or one from argv.

Usage:
    python demo/run_demo.py "what's the highest rebate listing in Austin?"
    python demo/run_demo.py            # runs a small scripted walkthrough

Requires SUPABASE_DB_URL in .env -- there is no local database to fall back to.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nlq.logging_config import configure_logging  # noqa: E402
from nlq.text_to_sql import ask as nlq_ask  # noqa: E402

# Observability: each ask() call logs question/mode/attempts/latency at INFO.
# Routed to stderr so it doesn't interleave with the stdout demo output.
configure_logging()


def show_nlq(question: str):
    print(f"\n>> {question}")
    result = nlq_ask(question)
    print(f"   mode: {result.mode}")
    print(f"   sql:  {result.sql}")
    print(f"   rows: {len(result.rows)}")
    for row in result.rows[:3]:
        print(f"   - {row['address']}, {row['city']}: ${row['price']:,}"
              f" (rebate ${row['estimated_buyer_rebate']:,})")
    return result


def main():
    parser = argparse.ArgumentParser(description="CLI walkthrough of the NLQ-SQL agent.")
    parser.add_argument("question", nargs="*", help="a question to ask; omit to run the scripted walkthrough")
    args = parser.parse_args()

    if args.question:
        show_nlq(" ".join(args.question))
        return

    print("=" * 70)
    print("NLQ-SQL agent: scripted walkthrough")
    print("=" * 70)
    show_nlq("what's the highest rebate listing in Austin?")
    show_nlq("active listings under 400000 with 3 or more beds")
    show_nlq("which property has been on the market the longest?")


if __name__ == "__main__":
    main()
