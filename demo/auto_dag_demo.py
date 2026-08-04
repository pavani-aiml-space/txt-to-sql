"""Automatic version of demo/dag_demo.py: an LLM planner (nlq/planner.py)
breaks an arbitrary question into steps instead of using a hard-coded one.

Purpose: show a real, new multi-step question get answered with no
hand-written steps, proving the planner generalizes. Works by calling
plan_steps() then running the result through run_auto_plan(). Requires an
LLM key; there's no rule-based fallback for planning itself.

Requires SUPABASE_DB_URL in .env -- there is no local database to fall back to.

Usage: python demo/auto_dag_demo.py
       python demo/auto_dag_demo.py "your own multi-step question"
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nlq.dag_executor import run_auto_plan  # noqa: E402
from nlq.llm_client import get_llm  # noqa: E402
from nlq.planner import PlanError, plan_steps  # noqa: E402
from nlq.text_to_sql import _connect_readonly  # noqa: E402

EXAMPLE_QUESTIONS = [
    "which listing agent has sold the most homes, and what's their average rebate on those sales?",
    "in the city with the most active listings, what's the highest-rebate deal, and is it above or below that city's average price?",
]


def show(question, steps):
    print(f"\n>> {question}")
    for step in steps:
        print(f"   [{step.status:>8}] {step.name}  (depends_on={step.depends_on})")
        if step.status == "done":
            # .value is None for a multi-column result (can't be used as a
            # downstream placeholder, per nlq/dag_executor.py's
            # _scalar_or_list) -- fall back to the full rows so a step like
            # that doesn't print misleadingly as empty.
            value = step.result.get("value")
            shown = value if value is not None else step.result.get("rows")
            print(f"              -> {shown}")
        elif step.error:
            print(f"              -> {step.error}")


def run_question(question, llm):
    try:
        plan = plan_steps(question, llm)
    except PlanError as exc:
        print(f"\n>> {question}\n   PLAN ERROR: {exc}")
        return

    conn = _connect_readonly()
    try:
        steps = run_auto_plan(plan, conn)
        show(question, steps)
    finally:
        conn.close()


def main():
    llm = get_llm()
    if llm is None:
        raise SystemExit(
            "auto_dag_demo requires an LLM key (Azure OpenAI or OpenAI) -- "
            "breaking a question into steps has no rule-based fallback."
        )

    if len(sys.argv) > 1:
        run_question(" ".join(sys.argv[1:]), llm)
        return

    for q in EXAMPLE_QUESTIONS:
        run_question(q, llm)


if __name__ == "__main__":
    main()
