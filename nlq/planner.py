"""Breaks an arbitrary multi-step question into a sequence of SQL steps.

Purpose: decompose a question automatically instead of hand-writing steps
for it (demo/dag_demo.py's fixed example only covers one question). Works
via one LLM call that returns a JSON list of steps, parsed and checked for
basic structure. The plan is unverified LLM output; every step it produces
still goes through validate_sql before running (see nlq/dag_executor.py).
"""

import json
import re

from nlq.instructions import INSTRUCTIONS
from nlq.text_to_sql import SCHEMA_DDL

REQUIRED_STEP_KEYS = {"name", "sql", "depends_on"}

# One worked example, shown to the model the same way single-question SQL
# generation shows worked examples -- this is what teaches the expected
# shape of a plan, not instructions describing it in the abstract.
PLANNER_EXAMPLE_QUESTION = (
    "which listing agent has sold the most homes, and what's their average "
    "rebate on those sales?"
)
PLANNER_EXAMPLE_PLAN = [
    {
        "name": "top_agent",
        "sql": (
            "SELECT listing_agent FROM properties WHERE listing_status = 'Sold' "
            "GROUP BY listing_agent ORDER BY COUNT(*) DESC LIMIT 1"
        ),
        "depends_on": [],
    },
    {
        "name": "agent_avg_rebate",
        "sql": (
            "SELECT AVG(estimated_buyer_rebate) FROM properties "
            "WHERE listing_status = 'Sold' AND listing_agent = {top_agent}"
        ),
        "depends_on": ["top_agent"],
    },
]


class PlanError(ValueError):
    pass


def plan_steps(question: str, llm, max_steps: int = 4) -> list:
    """Returns a list of step dicts: {"name": str, "sql": str, "depends_on": list[str]}.
    Raises PlanError if the LLM's response isn't valid JSON in the expected shape."""
    prompt = (
        "You break a natural-language question into a short sequence of SQL steps "
        f"(at most {max_steps}) over exactly this schema:\n\n"
        f"{SCHEMA_DDL}\n"
        "Each step is an object with:\n"
        '  "name": a short snake_case identifier, unique within the plan\n'
        '  "sql": a single read-only SELECT statement. If this step needs a result '
        "from an earlier step, reference it with a placeholder like {step_name} in "
        "place of the literal value -- never guess the value yourself.\n"
        '  "depends_on": a list of step names this step needs to run first '
        "(empty list if none)\n\n"
        "Rules: SELECT only, one statement per step, reference only the "
        "`properties` table, no semicolons, no comments, no markdown fences. "
        "If the question can be answered in one step, return a plan with just "
        "one step and an empty depends_on list. "
        "Return ONLY a JSON array of steps, nothing else.\n\n"
    )
    if INSTRUCTIONS:
        instructions_block = "\n".join(f"- {rule}" for rule in INSTRUCTIONS)
        prompt += f"Domain instructions:\n{instructions_block}\n\n"

    prompt += (
        f"Example -- Question: {PLANNER_EXAMPLE_QUESTION}\n"
        f"Plan: {json.dumps(PLANNER_EXAMPLE_PLAN)}\n\n"
        f"Question: {question}\nPlan:"
    )

    response = llm.invoke(prompt)
    text = getattr(response, "content", str(response))
    text = re.sub(r"^```json|^```|```$", "", text.strip(), flags=re.IGNORECASE | re.MULTILINE).strip()

    try:
        plan = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlanError(f"planner did not return valid JSON: {exc}\nraw response: {text!r}") from exc

    if not isinstance(plan, list) or not plan:
        raise PlanError(f"planner must return a non-empty JSON array of steps, got: {plan!r}")
    if len(plan) > max_steps:
        raise PlanError(f"planner returned {len(plan)} steps, more than max_steps={max_steps}")

    names = set()
    for step in plan:
        if not isinstance(step, dict) or not REQUIRED_STEP_KEYS.issubset(step):
            raise PlanError(f"each step must have name/sql/depends_on, got: {step!r}")
        names.add(step["name"])
    for step in plan:
        unknown_deps = set(step["depends_on"]) - names
        if unknown_deps:
            raise PlanError(f"step {step['name']!r} depends on unknown step(s): {unknown_deps}")

    return plan
