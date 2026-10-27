"""Repairs text that came across from the old CRM garbled (for example an en dash shown as three odd characters).

The old tables stored UTF-8 bytes in latin1 columns, so accents, dashes and Hindi text arrived as mojibake.
Only text that decodes cleanly back to UTF-8 is changed, so correct text is never touched.

    python fix_mojibake.py            # count what would change
    python fix_mojibake.py --commit   # repair it
"""
import argparse
import json
import re
import sys

from sqlalchemy import text

from app.database import engine

# the first characters of a garbled sequence: a-circumflex + euro sign, A-tilde + a continuation, A-circumflex + a continuation
MARK = re.compile("[ÂÃâ][\u0080-¿€™ŒœŽžŠš‘-„†-•…‰‹›ˆ˜]")
PG_MARK = "[" + chr(0xC2) + chr(0xC3) + chr(0xE2) + "]"
PG_JSON_MARK = r"\\u00(c2|c3|e2)"  # a json column stores non-ascii text as \uXXXX escapes

TEXT = {
    "interactions": ["notes"], "customers": ["name", "city", "email", "ext_ref"], "leads": ["name", "city", "ext_ref", "email"],
    "scenarios": ["name"], "tickets": ["subject", "description"], "ticket_comments": ["body"], "form_fields": ["label", "help_text"],
    "value_items": ["label"], "value_lists": ["name"], "clients": ["company_name", "address", "city", "state", "billing_address"],
    "client_contacts": ["name", "designation"], "users": ["name"], "campaigns": ["name", "description"], "campaign_batches": ["filename"],
    "plans": ["name", "notes"],
}
JSON = {
    "interactions": ["scenario_names", "answers"], "tickets": ["scenario_names", "answers", "answer_labels"], "leads": ["extra"],
}


def fix(v: str) -> str:
    if not MARK.search(v):
        return v
    try:
        return v.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return v


def fix_json(o):
    if isinstance(o, str):
        return fix(o)
    if isinstance(o, list):
        return [fix_json(x) for x in o]
    if isinstance(o, dict):
        return {fix(k) if isinstance(k, str) else k: fix_json(v) for k, v in o.items()}
    return o


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    total = 0
    with engine.begin() as conn:
        for table, cols in TEXT.items():
            for col in cols:
                ids = conn.execute(text(f'select id, "{col}" from {table} where "{col}" ~ :p'), {"p": PG_MARK}).all()
                n = 0
                for i, v in ids:
                    nv = fix(v)
                    if nv != v:
                        n += 1
                        if a.commit:
                            conn.execute(text(f'update {table} set "{col}" = :v where id = :i'), {"v": nv, "i": i})
                if n:
                    print(f"{table}.{col}: {n}")
                total += n
        for table, cols in JSON.items():
            for col in cols:
                rows = conn.execute(text(f'select id, "{col}"::text from {table} where "{col}"::text ~ :p'), {"p": PG_JSON_MARK}).all()
                n = 0
                for i, raw in rows:
                    old = json.loads(raw)
                    new = fix_json(old)
                    if new != old:
                        n += 1
                        if a.commit:
                            conn.execute(text(f'update {table} set "{col}" = cast(:v as json) where id = :i'), {"v": json.dumps(new), "i": i})
                if n:
                    print(f"{table}.{col}: {n}")
                total += n
        if not a.commit:
            conn.rollback()
    print(("repaired" if a.commit else "would repair") + f" {total} value(s)")


if __name__ == "__main__":
    sys.exit(main())
