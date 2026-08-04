"""Generates synthetic HomeBuyMe-style listing data and loads it directly
into Supabase Postgres.

Purpose: give the agent real data to query against. Needed since every
other part of this project depends on data existing in Supabase. Works by
generating rows in Python and inserting them directly, no intermediate file.

Synthetic only, no real MLS or customer data.

Requires SUPABASE_DB_URL in .env. Safe to re-run: drops and recreates the
table each time.

Usage: python scripts/seed_supabase.py
"""

import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

from nlq.schema import COLUMNS, CREATE_TABLE_SQL as _BASE_CREATE_TABLE_SQL
from nlq.text_to_sql import session_pooler_url

load_dotenv()

CITIES = [
    ("Austin", "TX", 78704), ("Austin", "TX", 78745), ("Round Rock", "TX", 78664),
    ("Denver", "CO", 80202), ("Aurora", "CO", 80012), ("Raleigh", "NC", 27601),
    ("Cary", "NC", 27511), ("Tampa", "FL", 33602), ("Orlando", "FL", 32801),
    ("Phoenix", "AZ", 85004),
]

PROPERTY_TYPES = ["Single Family", "Townhouse", "Condo", "Multi-Family"]
STATUSES = ["Active", "Pending", "Sold", "Coming Soon"]

AGENT_NAMES = [
    "Maria Chen", "Devon Rollins", "Priya Nair", "Jake Sorensen", "Amara Okafor",
    "Liam Bennett", "Sofia Reyes", "Tom Whitfield",
]

DESC_TEMPLATES = [
    "Bright {beds}-bed {ptype} in {city} with an updated kitchen and a fenced backyard. "
    "Walkable to parks and light rail; {dom} days on market.",
    "Move-in ready {beds}-bed, {baths}-bath {ptype} near downtown {city}. Recent roof and "
    "HVAC, open-concept living area, 2-car garage.",
    "Cozy {ptype} in a quiet {city} cul-de-sac. {beds} bedrooms, hardwood floors throughout, "
    "and a new deck overlooking a large lot.",
    "Spacious {beds}/{baths} {ptype} close to top-rated schools in {city}. Chef's kitchen "
    "with island, primary suite on main floor.",
    "Charming starter-home {ptype} in {city}, {sqft} sq ft, freshly painted, low HOA, "
    "priced to move after {dom} days on market.",
]

# Same table definition nlq/schema.py defines, just with a DROP first since
# this script is meant to be safely re-runnable.
CREATE_TABLE_SQL = f"DROP TABLE IF EXISTS properties;\n{_BASE_CREATE_TABLE_SQL};"

# Plain Postgres LISTEN/NOTIFY -- not a Supabase-specific feature, works on
# any Postgres. Fires on every insert/update/delete so a listening
# connection can react to changes live instead of only answering on request.
NOTIFY_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION notify_properties_change() RETURNS trigger AS $$
BEGIN
  PERFORM pg_notify(
    'properties_changed',
    json_build_object('operation', TG_OP, 'id', COALESCE(NEW.id, OLD.id))::text
  );
  RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS properties_change_trigger ON properties;
CREATE TRIGGER properties_change_trigger
AFTER INSERT OR UPDATE OR DELETE ON properties
FOR EACH ROW EXECUTE FUNCTION notify_properties_change();
"""


def make_properties(n=60):
    rows = []
    for i in range(1, n + 1):
        city, state, zip_code = random.choice(CITIES)
        ptype = random.choice(PROPERTY_TYPES)
        status = random.choices(STATUSES, weights=[55, 15, 25, 5])[0]
        beds = random.choice([2, 3, 3, 4, 4, 5])
        baths = round(random.choice([1, 1.5, 2, 2.5, 3, 3.5]), 1)
        sqft = random.randint(950, 4200)
        lot_size_sqft = random.randint(2500, 12000)
        year_built = random.randint(1975, 2024)
        price = round(random.randint(220_000, 950_000), -3)
        dom = random.randint(1, 120)
        # HomeBuyMe's core value prop: a share of the buyer-agent commission
        # rebated back to the buyer at closing.
        commission_pct = 0.025
        rebate_share = 0.6
        estimated_buyer_rebate = round(price * commission_pct * rebate_share, -1)
        agent = random.choice(AGENT_NAMES)
        desc = random.choice(DESC_TEMPLATES).format(
            beds=beds, baths=baths, ptype=ptype.lower(), city=city, sqft=sqft, dom=dom
        )
        listing_date = f"2026-{random.randint(1,7):02d}-{random.randint(1,28):02d}"
        rows.append((
            i, f"MLS{100000+i}", f"{100+i} {random.choice(['Maple','Oak','Cedar','Sunset','Ridge','River'])} "
            f"{random.choice(['St','Ave','Dr','Ln','Ct'])}", city, state, str(zip_code),
            price, beds, baths, sqft, lot_size_sqft, year_built, ptype, status,
            listing_date, dom, estimated_buyer_rebate, agent, desc,
        ))
    return rows


def main():
    supabase_url = os.getenv("SUPABASE_DB_URL")
    if not supabase_url:
        raise SystemExit("SUPABASE_DB_URL not set in .env")

    rows = make_properties()

    # Session-mode pooler, not the raw (transaction-mode) SUPABASE_DB_URL:
    # this script writes, and a transaction-pooler connection can come back
    # already stuck read-only, left over from ask()'s own read-only session
    # setting on a different client sharing the same recycled connection
    # (see the note on _connect_readonly in nlq/text_to_sql.py).
    pg_conn = psycopg2.connect(session_pooler_url(supabase_url))
    try:
        with pg_conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
            execute_values(
                cur,
                f"INSERT INTO properties ({', '.join(COLUMNS)}) VALUES %s",
                rows,
            )
            cur.execute(NOTIFY_TRIGGER_SQL)
        pg_conn.commit()
    finally:
        pg_conn.close()

    print(f"Loaded {len(rows)} rows into Supabase `properties` table, and installed the change-notify trigger.")


if __name__ == "__main__":
    main()
