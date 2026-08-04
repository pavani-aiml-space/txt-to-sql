"""Real 3-step example of the checklist/runner from nlq/dag.py.

Purpose: prove the step runner works, as a known-correct baseline before
automating the decomposition (see nlq/planner.py). Works with 3
hand-written steps, each running direct parameterized SQL rather than the
plain-English parser, since re-describing a prior result in English and
re-parsing it would reintroduce fragile-parsing bugs.

Question: "Find the best rebate deals in cities where homes sit unsold
longer than average, and summarize them."
  1. find_slow_cities - which cities are above the overall average?
  2. best_rebates      - among active listings in those cities, top deals
  3. summarize         - a plain-English summary of step 2

Requires SUPABASE_DB_URL in .env -- there is no local database to fall back to.

Usage: python demo/dag_demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nlq.dag import PlanStep, run_plan  # noqa: E402
from nlq.text_to_sql import _connect_readonly  # noqa: E402


def step_find_slow_cities(inputs):
    conn = _connect_readonly()
    try:
        overall_avg = conn.execute("SELECT AVG(days_on_market) FROM properties").fetchone()["avg"]
        rows = conn.execute(
            "SELECT city FROM properties GROUP BY city HAVING AVG(days_on_market) > %s",
            (overall_avg,),
        ).fetchall()
        return [r["city"] for r in rows]
    finally:
        conn.close()


def step_best_rebates(inputs):
    cities = inputs["find_slow_cities"]
    conn = _connect_readonly()
    try:
        rows = conn.execute(
            """SELECT city, address, estimated_buyer_rebate FROM properties
                WHERE listing_status = 'Active' AND city = ANY(%s)
                ORDER BY estimated_buyer_rebate DESC LIMIT 5""",
            (cities,),
        ).fetchall()
        return [{"city": r["city"], "address": r["address"], "rebate": r["estimated_buyer_rebate"]} for r in rows]
    finally:
        conn.close()


def step_summarize(inputs):
    deals = inputs["best_rebates"]
    if not deals:
        return "No qualifying deals found."
    lines = [f"- {d['address']} in {d['city']}: ${d['rebate']:,} rebate" for d in deals]
    return "Top rebate deals in slow-moving markets:\n" + "\n".join(lines)


def build_checklist():
    return [
        PlanStep(name="find_slow_cities"),
        PlanStep(name="best_rebates", depends_on=["find_slow_cities"]),
        PlanStep(name="summarize", depends_on=["best_rebates"]),
    ]


FUNCTIONS = {
    "find_slow_cities": step_find_slow_cities,
    "best_rebates": step_best_rebates,
    "summarize": step_summarize,
}


def show(checklist):
    for step in checklist:
        print(f"[{step.status:>8}] {step.name}")
        if step.status == "done":
            print(f"           -> {step.result}")
        elif step.error:
            print(f"           -> {step.error}")


def main():
    print("=" * 70)
    print("Success run")
    print("=" * 70)
    checklist = build_checklist()
    run_plan(checklist, FUNCTIONS)
    show(checklist)

    print()
    print("=" * 70)
    print("Failure run (step 1 forced to break)")
    print("=" * 70)
    broken_functions = dict(FUNCTIONS)
    broken_functions["find_slow_cities"] = lambda inputs: (_ for _ in ()).throw(
        RuntimeError("the database connection dropped")
    )
    checklist2 = build_checklist()
    run_plan(checklist2, broken_functions)
    show(checklist2)


if __name__ == "__main__":
    main()
