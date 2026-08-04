"""Curated domain configuration for the NLQ-SQL agent.

Purpose: give the LLM domain knowledge as editable data instead of
hardcoded logic. Needed so a wrong assumption can be fixed by editing a
list, not the code. Works via two lists, plain-English rules and worked
question/SQL examples, both injected into every prompt.

Kept distinct from scripts/eval_nlq.py's TEST_CASES: examples here are
few-shot inputs to the model, TEST_CASES are held-out checks on its
output. Reusing the same questions in both would be training on the test set.
"""

INSTRUCTIONS = [
    "'inactive' means listing_status is NOT 'Active'; there is no literal 'Inactive' status value in this data.",
    "Negations like 'not sold' or \"isn't active\" mean listing_status != <that value>, not listing_status = <that value>.",
    "Dollar amounts may use 'k' (thousands) or 'm'/'million' suffixes, e.g. '400k' means 400000, '1.2m' means 1200000.",
    "'rebate' refers to the estimated_buyer_rebate column: the cash HomeBuyMe returns to the buyer at closing.",
    "Always include a LIMIT unless the question clearly asks for exactly one row (e.g. 'the cheapest listing').",
]

CURATED_EXAMPLES = [
    {
        "question": "homes priced under 350k",
        "sql": "SELECT * FROM properties WHERE price < 350000 LIMIT 50",
    },
    {
        "question": "listings in Phoenix that are not sold",
        "sql": "SELECT * FROM properties WHERE city = 'Phoenix' AND listing_status != 'Sold' LIMIT 50",
    },
    {
        "question": "any inactive listings in Cary",
        "sql": "SELECT * FROM properties WHERE city = 'Cary' AND listing_status != 'Active' LIMIT 50",
    },
    {
        "question": "top rebate listing in Raleigh",
        "sql": "SELECT * FROM properties WHERE city = 'Raleigh' ORDER BY estimated_buyer_rebate DESC LIMIT 1",
    },
]
