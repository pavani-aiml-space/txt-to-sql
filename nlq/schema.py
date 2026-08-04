"""Single source of truth for the `properties` table shape.

Purpose: define the table's columns and CREATE TABLE statement once.
Needed so scripts/seed_supabase.py isn't hand-typing the schema separately
from where it's used elsewhere. Works as two plain constants, COLUMNS and
CREATE_TABLE_SQL, imported wherever the schema is needed.

Kept separate from nlq/text_to_sql.py's SCHEMA_DDL: that's prompt text
shown to the LLM, not SQL that gets executed.
"""

TABLE_NAME = "properties"

COLUMNS = [
    "id", "mls_id", "address", "city", "state", "zip_code", "price", "beds",
    "baths", "sqft", "lot_size_sqft", "year_built", "property_type",
    "listing_status", "listing_date", "days_on_market",
    "estimated_buyer_rebate", "listing_agent", "description",
]

CREATE_TABLE_SQL = """
CREATE TABLE properties (
    id INTEGER PRIMARY KEY,
    mls_id TEXT NOT NULL,
    address TEXT NOT NULL,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    zip_code TEXT NOT NULL,
    price INTEGER NOT NULL,
    beds INTEGER NOT NULL,
    baths REAL NOT NULL,
    sqft INTEGER NOT NULL,
    lot_size_sqft INTEGER NOT NULL,
    year_built INTEGER NOT NULL,
    property_type TEXT NOT NULL,
    listing_status TEXT NOT NULL,
    listing_date TEXT NOT NULL,
    days_on_market INTEGER NOT NULL,
    estimated_buyer_rebate INTEGER NOT NULL,
    listing_agent TEXT NOT NULL,
    description TEXT NOT NULL
)
"""
