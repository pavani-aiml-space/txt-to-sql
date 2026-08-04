"""Real-time illustration: the agent notices a live database change and
reacts, instead of only answering when asked.

Purpose: prove the agent isn't purely request/response. Works via a real
Postgres push notification (LISTEN/NOTIFY, see the trigger installed by
scripts/seed_supabase.py), not a polling timer. Uses the session-mode
pooler (port 5432), not the transaction-mode one ask() uses, since LISTEN
needs a persistent connection.

Requires SUPABASE_DB_URL in .env.

Usage: python demo/realtime_demo.py
"""

import json
import os
import select
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg2
from dotenv import load_dotenv

from nlq.text_to_sql import ask, session_pooler_url

load_dotenv()

QUESTION = "what's the highest rebate listing in Austin?"
NEW_LISTING_ID = 9999  # outside the real 1-60 range, cleaned up at the end


def session_url() -> str:
    url = os.getenv("SUPABASE_DB_URL")
    if not url:
        raise SystemExit("SUPABASE_DB_URL not set in .env")
    return session_pooler_url(url)


def show_answer(label: str):
    result = ask(QUESTION)
    top = result.rows[0] if result.rows else None
    if top:
        print(f"{label}: {top['address']} in {top['city']} -- ${top['estimated_buyer_rebate']:,} rebate")
    else:
        print(f"{label}: no listings found")
    return result


def insert_new_listing(conn):
    conn.cursor().execute(
        """
        INSERT INTO properties (id, mls_id, address, city, state, zip_code, price, beds, baths,
            sqft, lot_size_sqft, year_built, property_type, listing_status, listing_date,
            days_on_market, estimated_buyer_rebate, listing_agent, description)
        VALUES (%s, 'MLS999999', '999 New Listing Dr', 'Austin', 'TX', '78704', 999000, 4, 3.0,
            3000, 8000, 2024, 'Single Family', 'Active', '2026-08-03', 0, 25000, 'Demo Agent',
            'Just listed -- highest rebate in Austin, added live during this demo.')
        ON CONFLICT (id) DO NOTHING
        """,
        (NEW_LISTING_ID,),
    )


def cleanup(conn):
    conn.cursor().execute("DELETE FROM properties WHERE id = %s", (NEW_LISTING_ID,))


def main():
    url = session_url()

    listen_conn = psycopg2.connect(url)
    listen_conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    listen_conn.cursor().execute("LISTEN properties_changed;")

    write_conn = psycopg2.connect(url)
    write_conn.autocommit = True

    try:
        show_answer("BEFORE")

        print("\n(simulating a different process inserting a new listing...)\n")
        insert_new_listing(write_conn)

        print("waiting for a live notification...")
        if select.select([listen_conn], [], [], 5) == ([], [], []):
            print("TIMED OUT -- no notification received")
            return

        listen_conn.poll()
        for n in listen_conn.notifies:
            payload = json.loads(n.payload)
            print(f"NOTIFIED: {payload['operation']} on row id={payload['id']}\n")
        listen_conn.notifies.clear()

        show_answer("AFTER (agent re-queried live data)")
    finally:
        cleanup(write_conn)
        listen_conn.close()
        write_conn.close()


if __name__ == "__main__":
    main()
