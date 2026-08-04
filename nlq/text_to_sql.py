"""Natural-language -> SQL over the properties dataset, backed by Supabase Postgres.

Purpose: answer an arbitrary question about the listings without a
pre-written query for it. Needed because trusting an LLM's SQL on faith is
unsafe. Works by generating SQL (LLM, with a rule-based fallback),
validating it, executing it, and retrying with the error fed back on
failure (see README > Design notes for the full reasoning).

Modes: LLM (self-correcting, up to 3 attempts) if a key is configured,
otherwise the rule-based fallback. SUPABASE_DB_URL is always required;
there's no offline fallback for the database itself.
"""

import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Makes `python nlq/text_to_sql.py` work as a standalone script (not just
# `python -m nlq.text_to_sql`) despite the package-relative imports below --
# same pattern every other script in this project already uses.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from nlq import memory
from nlq.instructions import CURATED_EXAMPLES, INSTRUCTIONS
from nlq.llm_client import get_llm
from nlq.policy import ALLOWED_TABLES, DEFAULT_ROW_LIMIT, FORBIDDEN_KEYWORDS

load_dotenv()  # makes .env values available via os.getenv() everywhere in this module

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())  # library module: callers configure handlers

SCHEMA_DDL = """
CREATE TABLE properties (
    id INTEGER PRIMARY KEY,
    mls_id TEXT,
    address TEXT,
    city TEXT,
    state TEXT,
    zip_code TEXT,
    price INTEGER,
    beds INTEGER,
    baths REAL,
    sqft INTEGER,
    lot_size_sqft INTEGER,
    year_built INTEGER,
    property_type TEXT,        -- one of: Single Family, Townhouse, Condo, Multi-Family
    listing_status TEXT,       -- one of: Active, Pending, Sold, Coming Soon
    listing_date TEXT,         -- YYYY-MM-DD
    days_on_market INTEGER,
    estimated_buyer_rebate INTEGER,  -- cash HomeBuyMe rebates the buyer at closing
    listing_agent TEXT,
    description TEXT
);
"""

MAX_LLM_ATTEMPTS = 3


class UnsafeSQLError(ValueError):
    pass


class LLMExhaustedError(RuntimeError):
    def __init__(self, message: str, attempts: list):
        super().__init__(message)
        self.attempts = attempts


class _PgConnection:
    """Thin adapter so a Postgres connection supports conn.execute(sql).fetchall()
    -- psycopg2's raw connection doesn't have that shorthand the way
    sqlite3.Connection used to when this agent supported both backends."""

    def __init__(self, pg_conn):
        self._conn = pg_conn

    def execute(self, sql, params=None):
        from psycopg2.extras import RealDictCursor

        cur = self._conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params)
        return cur

    def close(self):
        self._conn.close()


def _connect_readonly() -> _PgConnection:
    """Defense-in-depth beneath validate_sql: Postgres itself refuses any
    write on this connection, regardless of what the regex validator
    missed. Enforces nlq.policy.READ_ONLY_CONNECTION.

    Note: this uses the transaction-mode pooler, which recycles connections
    across clients -- a write-needing caller should use session_pooler_url()
    below instead, or it can inherit this read-only state."""
    import psycopg2  # lazy: only needed once this is actually called

    url = os.getenv("SUPABASE_DB_URL")
    if not url:
        raise RuntimeError("SUPABASE_DB_URL must be set in .env -- this agent requires Supabase, there is no local fallback database")

    conn = psycopg2.connect(url, connect_timeout=10)
    conn.set_session(readonly=True, autocommit=True)
    return _PgConnection(conn)


def session_pooler_url(url: str) -> str:
    """Swaps a transaction-mode pooler URL (port 6543) for the session-mode
    one (port 5432, a dedicated connection), needed for writes or for
    holding a connection open (e.g. LISTEN/NOTIFY)."""
    from urllib.parse import urlsplit, urlunsplit

    parsed = urlsplit(url)
    session_netloc = parsed.netloc.replace(f":{parsed.port}", ":5432")
    return urlunsplit(parsed._replace(netloc=session_netloc))


def execute(conn, sql: str, params=None):
    """Runs sql, returns (rows_as_dicts, column_names). Shared by every
    caller so row/column extraction lives in one place. Also used by
    nlq/dag_executor.py, which runs each plan step's SQL through this same
    path -- hence the public name instead of a leading underscore."""
    cursor = conn.execute(sql, params)
    rows = [dict(r) for r in cursor.fetchall()]
    columns = [d[0] for d in cursor.description]
    return rows, columns


@dataclass
class NLQResult:
    question: str
    sql: str
    columns: list
    rows: list
    mode: str  # "llm", "llm (self-corrected, Nx)", "rule-based", or a fallback variant
    attempts: list  # each: {"attempt": int, "sql": str|None, "ok": bool, "error": str|None}


def validate_sql(sql: str) -> str:
    sql = sql.strip().strip(";").strip()
    if ";" in sql:
        raise UnsafeSQLError("Multiple statements are not allowed.")
    if not re.match(r"^\s*SELECT\b", sql, re.IGNORECASE):
        raise UnsafeSQLError("Only SELECT statements are allowed.")
    forbidden = r"\b(" + "|".join(FORBIDDEN_KEYWORDS) + r")\b"
    if re.search(forbidden, sql, re.IGNORECASE):
        raise UnsafeSQLError("Statement contains a disallowed keyword.")
    tables_referenced = set(re.findall(r"\bFROM\s+(\w+)", sql, re.IGNORECASE))
    tables_referenced |= set(re.findall(r"\bJOIN\s+(\w+)", sql, re.IGNORECASE))
    if not tables_referenced or not tables_referenced.issubset(ALLOWED_TABLES):
        raise UnsafeSQLError(f"Query may only reference {ALLOWED_TABLES}, got {tables_referenced}.")
    if not re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
        sql = f"{sql} LIMIT {DEFAULT_ROW_LIMIT}"
    return sql


def _llm_to_sql(
    question: str, llm, prior_sql: str = None, prior_error: str = None,
    examples: list = None, known_failures: list = None,
) -> str:
    prompt = (
        "You translate a natural-language question into a single PostgreSQL SELECT "
        "statement over exactly this schema:\n\n"
        f"{SCHEMA_DDL}\n"
        "Rules: read-only SELECT only, one statement, no semicolons, no comments, "
        "no markdown fences, reference only the `properties` table, "
        f"cap results with LIMIT {DEFAULT_ROW_LIMIT} unless the question implies fewer. "
        "Return ONLY the SQL.\n"
    )
    if INSTRUCTIONS:
        instructions_block = "\n".join(f"- {rule}" for rule in INSTRUCTIONS)
        prompt += f"\nDomain instructions:\n{instructions_block}\n"
    if examples:
        example_block = "\n".join(f"Q: {e['question']}\nSQL: {e['sql']}" for e in examples)
        prompt += f"\nSimilar past examples (for reference, do not copy blindly):\n{example_block}\n"
    if known_failures:
        failures_block = "\n".join(
            f"Q: {f['question']}\nWrong SQL: {f['sql']}\nWhy it failed: {f['error']}"
            for f in known_failures
        )
        prompt += f"\nKnown incorrect patterns from past attempts on similar questions -- avoid repeating these mistakes:\n{failures_block}\n"
    prompt += f"\nQuestion: {question}\nSQL:"
    if prior_error:
        prompt += (
            f"\n\nYour previous attempt failed. "
            f"Previous SQL: {prior_sql}\nError: {prior_error}\n"
            "Return a corrected SQL statement that fixes this error. SQL:"
        )
    response = llm.invoke(prompt)
    sql = getattr(response, "content", str(response))
    sql = re.sub(r"^```sql|```$", "", sql.strip(), flags=re.IGNORECASE | re.MULTILINE).strip()
    return sql


def _llm_to_sql_with_retry(question: str, llm, conn, max_attempts: int = MAX_LLM_ATTEMPTS):
    """Generate -> validate -> execute, retrying with the error fed back on
    a SQL problem. Returns (sql, rows, columns, attempts) on success, or
    raises LLMExhaustedError after exhausting attempts.

    A bad-SQL error is worth retrying that way; an LLM-call failure (rate
    limit, network) is not, since there's no "corrected SQL" to retry
    toward, so that fails fast after one attempt instead."""
    examples = memory.retrieve_examples(question, pool=CURATED_EXAMPLES)
    known_failures = memory.retrieve_known_failures(question)
    attempts = []
    prior_sql, prior_error = None, None
    for attempt_num in range(1, max_attempts + 1):
        candidate = None
        try:
            candidate = _llm_to_sql(
                question, llm, prior_sql=prior_sql, prior_error=prior_error,
                examples=examples, known_failures=known_failures,
            )
        except Exception as exc:
            attempts.append({"attempt": attempt_num, "sql": None, "ok": False, "error": f"LLM call failed: {exc}"})
            logger.warning("llm_call attempt=%d failed, not retrying as a SQL error: %s", attempt_num, exc)
            raise LLMExhaustedError(
                f"LLM call failed on attempt {attempt_num} -- not a SQL error to self-correct", attempts
            ) from exc

        try:
            validated = validate_sql(candidate)
            rows, columns = execute(conn, validated)
            attempts.append({"attempt": attempt_num, "sql": validated, "ok": True, "error": None})
            logger.info("llm_attempt attempt=%d ok=True sql=%r", attempt_num, validated)
            return validated, rows, columns, attempts
        except Exception as exc:
            attempts.append({"attempt": attempt_num, "sql": candidate, "ok": False, "error": str(exc)})
            logger.warning("llm_attempt attempt=%d ok=False error=%s", attempt_num, exc)
            memory.record_failure(question, candidate, str(exc))
            prior_sql, prior_error = candidate, str(exc)
    raise LLMExhaustedError(
        f"LLM failed to produce a valid query after {max_attempts} attempts", attempts
    )


_AMOUNT_RE = r"\$?(\d[\d,]*\.?\d*)\s*(k|m|thousand|million)?\b"
_AMOUNT_MULTIPLIERS = {"k": 1_000, "thousand": 1_000, "m": 1_000_000, "million": 1_000_000}
_PRICE_COMPARISONS = [("under|below", "<"), ("over|above", ">")]


def _parse_amount(number: str, suffix: str) -> int:
    value = float(number.replace(",", ""))
    return int(value * _AMOUNT_MULTIPLIERS.get((suffix or "").lower(), 1))


def _price_filters(q: str) -> list:
    clauses = []
    for keywords, comparator in _PRICE_COMPARISONS:
        m = re.search(rf"(?:{keywords})\s*{_AMOUNT_RE}", q)
        if m:
            clauses.append(f"price {comparator} {_parse_amount(m.group(1), m.group(2))}")
    return clauses


def _beds_filter(q: str) -> str:
    m = re.search(r"at least\s*(\d+)\s*bed", q) or re.search(r"(\d+)\s*(?:\+\s*|or\s+more\s+)?bed", q)
    return f"beds >= {int(m.group(1))}" if m else None


def _known_cities(conn) -> list:
    # name-based lookup, not positional: psycopg2's RealDictRow has no
    # positional access
    return [r["city"] for r in conn.execute("SELECT DISTINCT city FROM properties").fetchall()]


def _city_filter(q: str, conn) -> str:
    for city in _known_cities(conn):
        if city.lower() in q:
            return f"city = '{city}'"
    return None


_STATUS_VALUES = ["Active", "Pending", "Sold", "Coming Soon"]


def _status_filter(q: str) -> str:
    """Matches a status word by word boundary (not substring: "inactive"
    must not match "active"), checking negation ("not sold", "isn't
    active") first. Doesn't handle all English negation (e.g. "in-active");
    see README > Roadmap."""
    if re.search(r"\binactive\b", q):
        return "listing_status != 'Active'"
    for status in _STATUS_VALUES:
        s = re.escape(status.lower())
        if re.search(rf"\b(?:not|isn'?t|non-?)\s*{s}\b", q):
            return f"listing_status != '{status}'"
        if re.search(rf"\b{s}\b", q):
            return f"listing_status = '{status}'"
    return None


def _order_by_clause(q: str) -> str:
    """First matching rule wins."""
    if "rebate" in q and any(w in q for w in ("highest", "top", "most", "best")):
        return "estimated_buyer_rebate DESC"
    if "longest" in q and "market" in q:
        return "days_on_market DESC"
    if "newest" in q or "recent" in q:
        return "listing_date DESC"
    if "cheapest" in q or "lowest price" in q:
        return "price ASC"
    if "most expensive" in q or "highest price" in q:
        return "price DESC"
    return None


def _rule_based_to_sql(question: str, conn) -> str:
    q = question.lower()
    where = [c for c in (*_price_filters(q), _beds_filter(q), _city_filter(q, conn), _status_filter(q)) if c]
    order_by = _order_by_clause(q)

    sql = "SELECT * FROM properties"
    if where:
        sql += " WHERE " + " AND ".join(where)
    if order_by:
        sql += f" ORDER BY {order_by}"
    sql += f" LIMIT {DEFAULT_ROW_LIMIT}"
    return sql


def _rule_based_answer(question: str, conn):
    sql = validate_sql(_rule_based_to_sql(question, conn))
    rows, columns = execute(conn, sql)
    return sql, rows, columns


def _answer(question: str, llm, conn):
    """Tries the LLM path if one is configured; on any failure (or no LLM
    at all), falls back to the rule-based one. Always returns
    (sql, rows, columns, mode, attempts)."""
    if llm is None:
        sql, rows, columns = _rule_based_answer(question, conn)
        return sql, rows, columns, "rule-based", []

    try:
        sql, rows, columns, attempts = _llm_to_sql_with_retry(question, llm, conn)
        n = attempts[-1]["attempt"]
        mode = "llm" if n == 1 else f"llm (self-corrected, {n} attempts)"
        memory.record(question, sql)
        return sql, rows, columns, mode, attempts
    except LLMExhaustedError as exc:
        attempts = exc.attempts
        mode = f"rule-based (llm failed after {len(attempts)} attempts)"
    except Exception as exc:
        logger.warning("llm path raised unexpectedly, falling back: %s", exc)
        attempts = []
        mode = "rule-based (llm error)"

    sql, rows, columns = _rule_based_answer(question, conn)
    return sql, rows, columns, mode, attempts


def ask(question: str) -> NLQResult:
    start = time.perf_counter()
    conn = _connect_readonly()
    try:
        sql, rows, columns, mode, attempts = _answer(question, get_llm(), conn)

        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "nlq_query question=%r mode=%s attempts=%d rows=%d latency_ms=%d sql=%r",
            question, mode, len(attempts) or 1, len(rows), latency_ms, sql,
        )
        return NLQResult(question=question, sql=sql, columns=columns, rows=rows, mode=mode, attempts=attempts)
    finally:
        conn.close()


if __name__ == "__main__":
    from nlq.logging_config import configure_logging

    configure_logging()

    q = " ".join(sys.argv[1:]) or "What are the 3 highest rebate listings in Austin?"
    result = ask(q)
    print(f"Q: {result.question}\nMode: {result.mode}\nSQL: {result.sql}\nRows: {len(result.rows)}")
    for row in result.rows[:5]:
        print(row)
