"""Writes every alert rule to a CSV file for review, one row per rule, grouped by client.

    python export_alerts.py                      # all rules  -> alert_rules_review.csv
    python export_alerts.py --moved              # only rules moved from the old CRM
    python export_alerts.py --out my_review.csv
"""
import argparse
import csv
import sys

from sqlalchemy import select

from app.database import SessionLocal
from app.models import AlertRule, Campaign, Client, User
from app.services import alerts as al

HEAD = ["Client", "Rule id", "Alert name", "Active", "When", "Scenario contains", "Campaign(s)", "Open for (hours)", "Tell: customer", "Tell: emails", "Tell: mobiles",
        "Tell: users", "Channels", "Message (empty = standard text)", "Warnings"]


def safe(v: str) -> str:
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v   # never let a cell run as a spreadsheet formula


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--moved", action="store_true", help="only rules moved from the old CRM")
    ap.add_argument("--out", default="alert_rules_review.csv")
    a = ap.parse_args()
    with SessionLocal() as db:
        stmt = select(AlertRule, Client.company_name).join(Client, Client.id == AlertRule.client_id).order_by(Client.company_name, AlertRule.event, AlertRule.id)
        if a.moved:
            stmt = stmt.where(AlertRule.name.like("Moved:%"))
        camps = {c.id: c.name for c in db.scalars(select(Campaign))}
        users = {u.id: u.name for u in db.scalars(select(User))}
        out, per_client, warn_n = [], {}, 0
        for r, client in db.execute(stmt):
            c, rec = r.conditions or {}, r.recipients or {}
            warns = []
            if rec.get("customer") and not any(ch in ("sms", "whatsapp") for ch in r.channels or []):
                warns.append("customer cannot be reached: needs SMS or WhatsApp")
            if rec.get("customer") and r.event == "call_tagged" and not c:
                warns.append("sends to the customer after EVERY tagged call")
            if not (rec.get("customer") or rec.get("emails") or rec.get("mobiles") or rec.get("users") or rec.get("assignee") or rec.get("agent")):
                warns.append("nobody to tell")
            if "email" in (r.channels or []) and not rec.get("emails") and not rec.get("users") and not rec.get("assignee") and not rec.get("agent"):
                warns.append("email channel but no email address")
            msg = (r.message or "").replace("\r", "")
            if "{" in msg and any(f"{{{k}}}" in msg for k in ("category1", "calldate")) is False and "(#var#)" in msg:
                warns.append("contains an unfilled provider variable (#var#)")
            warn_n += bool(warns)
            per_client[client] = per_client.get(client, 0) + 1
            out.append([client, r.id, r.name, "yes" if r.is_active else "no", al.EVENT_LABEL.get(r.event, r.event), c.get("scenario_contains", ""),
                        ", ".join(camps.get(i, str(i)) for i in c.get("campaign", [])), c.get("hours", ""), "yes" if rec.get("customer") else "",
                        "; ".join(rec.get("emails", [])), "; ".join(rec.get("mobiles", [])), "; ".join(users.get(i, str(i)) for i in rec.get("users", [])),
                        ", ".join(r.channels or []), msg, "; ".join(warns)])
    with open(a.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEAD)
        for row in out:
            w.writerow([safe(x) if isinstance(x, str) else x for x in row])
    print(f"{len(out)} rule(s) for {len(per_client)} client(s) written to {a.out}; {warn_n} with a warning to check")
    for name, n in sorted(per_client.items(), key=lambda x: -x[1])[:10]:
        print(f"  {n:>4}  {name}")


if __name__ == "__main__":
    sys.exit(main())
