"""Bridges nlq/planner.py's output to nlq/dag.py's generic run_plan() runner.

Purpose: run a planner-produced plan safely. Needed so nlq/dag.py can stay
domain-agnostic while SQL-specific logic (placeholders, validation) lives
in one place. Works by substituting a prior step's real result into the
next step's SQL as a parameterized value, then validating and executing it.
"""

import re

from nlq.dag import PlanStep, run_plan
from nlq.text_to_sql import execute, validate_sql

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def substitute_placeholders(sql: str, results: dict) -> tuple:
    """Replaces every {step_name} in `sql` with `%s`, collecting the real
    values from `results` in order -- never pastes a value into the SQL
    text itself. Raises KeyError for a placeholder with no matching result."""
    params = []

    def _replace(match):
        step_name = match.group(1)
        if step_name not in results:
            raise KeyError(f"placeholder references unknown or not-yet-run step: {step_name!r}")
        params.append(results[step_name])
        return "%s"

    substituted = _PLACEHOLDER_RE.sub(_replace, sql)
    return substituted, tuple(params)


def _scalar_or_list(rows: list, columns: list):
    """Collapses a step's rows to what a placeholder needs: one value for a
    single row/column, a list for multiple rows. Multiple columns return
    None; the step still runs, it just can't be referenced by a later step."""
    if len(columns) != 1:
        return None
    col = columns[0]
    values = [r[col] for r in rows]
    if len(values) == 1:
        return values[0]
    return values


def make_step_function(step: dict, conn):
    """Returns a function usable by nlq.dag.run_plan: takes the dict of
    already-finished steps' results, substitutes any placeholders into this
    step's SQL, validates it through the same guardrail every other query
    in this project goes through, executes it, and returns its scalar/list
    value for any step that depends on it."""

    def _run(prior_results: dict):
        prior_values = {name: v["value"] for name, v in prior_results.items()}
        sql, params = substitute_placeholders(step["sql"], prior_values)
        validated = validate_sql(sql)
        rows, columns = execute(conn, validated, params)
        return {"rows": rows, "columns": columns, "value": _scalar_or_list(rows, columns)}

    return _run


def build_plan_steps(plan: list, conn) -> tuple:
    """Turns a raw planner plan (list of {name, sql, depends_on} dicts) into
    (PlanStep list, step_functions dict) ready for nlq.dag.run_plan."""
    steps = [PlanStep(name=s["name"], depends_on=s["depends_on"]) for s in plan]
    functions = {s["name"]: make_step_function(s, conn) for s in plan}
    return steps, functions


def run_auto_plan(plan: list, conn) -> list:
    """Executes a planner-produced plan via the generic runner. Returns the
    list of PlanStep objects with .status/.result/.error filled in, same as
    demo/dag_demo.py's hard-coded example produces."""
    steps, functions = build_plan_steps(plan, conn)
    return run_plan(steps, functions)
