"""Security policy for the NLQ-SQL agent: every safety rule, in one place.

Purpose: define what a generated query is allowed to do, separate from the
code that enforces it. Needed so the rules can be reviewed and edited
without reading through code. Enforced twice, by validate_sql (checks the
SQL text) and _connect_readonly (a connection that can't write regardless)
in nlq/text_to_sql.py.

Run this file directly to print the rules in plain English:
    python -m nlq.policy
"""

ALLOWED_TABLES = {"properties"}

FORBIDDEN_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "COPY", "GRANT", "REVOKE", "TRUNCATE", "CALL", "DO", "VACUUM",
]

DEFAULT_ROW_LIMIT = 50

# Enforced in nlq/text_to_sql.py's _connect_readonly via
# conn.set_session(readonly=True) -- a Postgres read-only session, so a
# write is structurally impossible on this connection regardless of
# whether validate_sql caught it.
READ_ONLY_CONNECTION = True

POLICY_RULES = [
    f"Only these tables may ever be queried: {sorted(ALLOWED_TABLES)}.",
    f"These SQL keywords are never allowed, in any query: {', '.join(FORBIDDEN_KEYWORDS)}.",
    f"Every query is capped at {DEFAULT_ROW_LIMIT} rows unless the question clearly asks for fewer.",
    "The database connection itself is opened as a read-only Postgres "
    "session, so a write is impossible even if the text-based checks "
    "above are somehow bypassed.",
]

if __name__ == "__main__":
    print("NLQ-SQL agent: safety policy\n")
    for i, rule in enumerate(POLICY_RULES, 1):
        print(f"{i}. {rule}")
