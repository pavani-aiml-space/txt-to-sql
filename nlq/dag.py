"""The checklist item, and the runner that walks a list of them.

Purpose: answer a question that needs more than one dependent lookup.
Needed because some questions can't be answered by one query. Works by
running each step once its dependencies are done, passing along their
real results, and skipping anything downstream of a failure.

A step is just a name, a list of other step-names it needs finished first,
and a spot to record what happened once it runs.
"""

from dataclasses import dataclass, field


@dataclass
class PlanStep:
    name: str
    depends_on: list = field(default_factory=list)  # names of steps that must finish first
    status: str = "waiting"   # waiting -> done, or waiting -> skipped/failed
    result: object = None     # filled in once the step actually runs
    error: str = None


def run_plan(steps: list, step_functions: dict) -> list:
    """Walks `steps` in the given order (not a topological sort; the caller
    must list dependencies before their dependents). Runs each step once
    its dependencies are done, passing their results as {name: result} to
    the matching function in `step_functions`; skips a step, without
    running it, if a dependency didn't finish."""
    finished_results = {}

    for step in steps:
        missing = [dep for dep in step.depends_on if dep not in finished_results]
        if missing:
            step.status = "skipped"
            step.error = f"required step(s) did not finish: {missing}"
            continue

        inputs = {dep: finished_results[dep] for dep in step.depends_on}
        try:
            step.result = step_functions[step.name](inputs)
            step.status = "done"
            finished_results[step.name] = step.result
        except Exception as exc:
            step.status = "failed"
            step.error = str(exc)

    return steps
