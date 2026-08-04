"""Two-sided query memory: successes to repeat, failures to avoid.

Purpose: let the agent learn from its own history across separate
questions, not just within one retry loop. Needed so a mistake found once
isn't repeated on a different but similarly-worded question later. Works
by appending to two JSONL files and retrieving similar past entries by
shared words (not embeddings; see README > Roadmap).
"""

import json
from pathlib import Path

MEMORY_PATH = Path(__file__).resolve().parent.parent / "data" / "query_memory.jsonl"
FAILURES_PATH = Path(__file__).resolve().parent.parent / "data" / "query_failures.jsonl"


def _load(path: Path) -> list:
    if not path.exists():
        return []
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def _append(entry: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def _rank(question: str, entries: list, k: int) -> list:
    """Token-overlap ranking shared by both stores below -- same scoring,
    two different things being scored (successes vs. failures)."""
    if not entries:
        return []
    q_tokens = set(question.lower().split())
    scored = [
        (len(q_tokens & set(e["question"].lower().split())), e)
        for e in entries
    ]
    scored = [(score, e) for score, e in scored if score > 0]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [e for _, e in scored[:k]]


def record(question: str, sql: str, path: Path = MEMORY_PATH) -> None:
    """Append a validated (question, sql) pair for future few-shot retrieval.
    Skips if this exact question (case/whitespace-insensitive) is already
    recorded, so re-asking the same thing doesn't pile up duplicates."""
    existing = _load(path)
    if any(e["question"].strip().lower() == question.strip().lower() for e in existing):
        return
    _append({"question": question, "sql": sql}, path)


def retrieve_examples(question: str, k: int = 3, pool: list = None, path: Path = MEMORY_PATH) -> list:
    """Return up to k examples with the most word overlap with `question`,
    ranked across both a curated `pool` (e.g. nlq.instructions.CURATED_EXAMPLES)
    and past recorded successes on disk. Curated examples are included so
    the agent has decent few-shot coverage from the start, before any
    queries have been recorded."""
    return _rank(question, (pool or []) + _load(path), k)


def record_failure(question: str, sql: str, error: str, path: Path = FAILURES_PATH) -> None:
    """Append a (question, attempted sql, error) that failed validation or
    execution -- recorded regardless of whether a later retry on the same
    question eventually succeeded, since the failed attempt is still a
    useful "don't do this" signal for a different future question. Same
    dedup rule as record(): skip if this exact (question, sql) pair is
    already recorded."""
    existing = _load(path)
    key = (question.strip().lower(), sql.strip().lower() if sql else sql)
    if any((e["question"].strip().lower(), (e["sql"] or "").strip().lower()) == key for e in existing):
        return
    _append({"question": question, "sql": sql, "error": error}, path)


def retrieve_known_failures(question: str, k: int = 2, path: Path = FAILURES_PATH) -> list:
    """Return up to k past failures with the most word overlap with
    `question` -- shown to the LLM as patterns to avoid, not to copy."""
    return _rank(question, _load(path), k)
