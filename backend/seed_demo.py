"""Creates one fully set-up demo client for testing. Run with the backend running:

    .\\.venv\\Scripts\\python.exe seed_demo.py

Safe to run twice: it stops if the demo client already exists.
Demo logins (test only): see the DEMO_* values below.
"""
import re
import sys

import httpx

BASE = "http://localhost:8000"
ADMIN = ("admin@dialdesk.in", "admin123")
CLIENT_ADMIN = ("demo.admin@democlient.in", "Demo#12345")
OWN_AGENT = ("demo.agent@democlient.in", "Agent#12345")
SHARED_AGENT_NAME = "krishna kumar"  # the shared agent you already added; allocated if found
SHARED_AGENT_NEW = ("demo.shared@dialdesk.in", "Shared#12345")

c = httpx.Client(base_url=BASE, timeout=30)


def login(e, p):
    r = c.post("/api/auth/login", data={"username": e, "password": p})
    assert r.status_code == 200, f"login {e}: {r.text}"
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def ok(r, what):
    assert r.status_code < 400, f"{what}: {r.status_code} {r.text[:300]}"
    return r.json()


adm = login(*ADMIN)
roles = {r["key"]: r["id"] for r in c.get("/api/roles", headers=adm).json()}

existing = c.get("/api/clients", headers=adm).json()
existing = existing.get("items", existing) if isinstance(existing, dict) else existing
if any(x.get("company_name") == "Demo Insurance Services" or x.get("name") == "Demo Insurance Services" for x in existing):
    print("Demo client already exists. Nothing to do.")
    sys.exit(0)


def setpw(email, pw):
    notes = c.get("/api/settings/notifications", headers=adm).json()
    n = [x for x in notes if x["recipient"] == email and x["channel"] == "email" and "set-password" in x["body"]][0]
    ok(c.post("/api/auth/set-password", json={"token": re.search(r"/set-password/(\S+)", n["body"]).group(1), "password": pw}), "set password")


# ---- client (active; its admin gets a login)
cl = ok(c.post("/api/clients", headers=adm, json={
    "company_name": "Demo Insurance Services", "gstin": "27AAPFU0939F1ZV", "contact_name": "Demo Admin",
    "mobile": "9811100001", "email": CLIENT_ADMIN[0], "activate_now": True}), "client")
cid = cl["id"]
setpw(CLIENT_ADMIN[0], CLIENT_ADMIN[1])

# ---- dialer ids
D = f"/api/clients/{cid}/dialer-ids"
for kind, value in (("vendor", "7001"), ("ingroup", "demo_support"), ("ingroup", "demo_sales")):
    ok(c.post(D, headers=adm, json={"kind": kind, "value": value}), f"dialer id {value}")

# ---- inbound form (also used for tickets): dependent Country > State, text, dropdown, scenario tree
vl = ok(c.post("/api/value-lists", headers=adm, json={"client_id": cid, "name": "Country > State", "level_names": ["Country", "State"]}), "list")
for country, states in {"India": ["Maharashtra", "Delhi", "Karnataka"], "UAE": ["Dubai", "Abu Dhabi"]}.items():
    p = ok(c.post(f"/api/value-lists/{vl['id']}/items", headers=adm, json={"label": country}), "country")
    for s in states:
        ok(c.post(f"/api/value-lists/{vl['id']}/items", headers=adm, json={"label": s, "parent_id": p["id"]}), "state")

IN = f"/api/forms/{cid}/in_call"
ok(c.post(IN + "/fields", headers=adm, json={"label": "Policy Number", "field_type": "text", "validation": "alphanumeric", "required": True}), "f")
country = ok(c.post(IN + "/fields", headers=adm, json={"label": "Country", "field_type": "select", "value_list_id": vl["id"], "list_level": 1}), "f")
ok(c.post(IN + "/fields", headers=adm, json={"label": "State", "field_type": "select", "value_list_id": vl["id"], "list_level": 2, "parent_field_id": country["id"]}), "f")
ok(c.post(IN + "/fields", headers=adm, json={"label": "Priority", "field_type": "select", "own_values": ["Low", "Medium", "High"]}), "f")
ok(c.post(IN + "/fields", headers=adm, json={"label": "Remarks", "field_type": "textarea"}), "f")


def scen(name, parent=None, outcome=None):
    return ok(c.post(IN + "/scenarios", headers=adm, json={"name": name, "parent_id": parent, "outcome": outcome}), "scenario")


q = scen("Query")
scen("Policy status", q["id"], "closed")
scen("Premium due date", q["id"], "closed")
cm = scen("Complaint")
scen("Claim delay", cm["id"], "callback")
scen("Wrong charge", cm["id"], "callback")
scen("Renewal interested", None, "converted")
scen("Not interested", None, "closed")
scen("Wrong number", None, "not_connected")

# ---- outbound campaign with its own form
camp = ok(c.post("/api/campaigns", headers=adm, json={"client_id": cid, "name": "Renewal Drive"}), "campaign")
CF = f"/api/forms/{cid}/campaign-{camp['id']}"
ok(c.post(CF + "/fields", headers=adm, json={"label": "Promise Date", "field_type": "date", "required": True}), "f")
ok(c.post(CF + "/fields", headers=adm, json={"label": "Premium Amount", "field_type": "decimal"}), "f")
ok(c.post(CF + "/fields", headers=adm, json={"label": "Remarks", "field_type": "textarea"}), "f")
ok(c.post(CF + "/scenarios", headers=adm, json={"name": "Promise to pay", "outcome": "callback"}), "s")
ok(c.post(CF + "/scenarios", headers=adm, json={"name": "Paid", "outcome": "converted"}), "s")
ok(c.post(CF + "/scenarios", headers=adm, json={"name": "Call back later", "outcome": "callback"}), "s")
ok(c.post(CF + "/scenarios", headers=adm, json={"name": "Do not call", "outcome": "dnc"}), "s")
ok(c.post(f"/api/campaigns/{camp['id']}/status", headers=adm, json={"status": "active"}), "activate")
ok(c.post(D, headers=adm, json={"kind": "campaign", "value": "DEMO-RENEW", "campaign_id": camp["id"]}), "campaign dialer id")

# ---- agents
def agent(name, email, pw, **k):
    ok(c.post("/api/users", headers=adm, json={"name": name, "email": email, "user_type": "agent", "role_id": roles["agent"], **k}), "agent")
    setpw(email, pw)
    return [u for u in _users() if u["email"] == email][0]


def _users():
    r = c.get("/api/users", headers=adm).json()
    return r.get("items", r) if isinstance(r, dict) else r


own = agent("Demo Client Agent", OWN_AGENT[0], OWN_AGENT[1], client_id=cid)
shared = [u for u in _users() if u["name"].lower() == SHARED_AGENT_NAME and u["user_type"] == "agent" and not u.get("client_id")]
shared = shared[0] if shared else agent("Demo Shared Agent", SHARED_AGENT_NEW[0], SHARED_AGENT_NEW[1], phone="9876500002")
ok(c.put(f"/api/users/{shared['id']}/clients", headers=adm, json={"ids": [cid]}), "allocate client")
ok(c.put(f"/api/campaigns/{camp['id']}/agents", headers=adm, json={"ids": [own["id"], shared["id"]]}), "allocate campaign")

print(f"""Demo client ready: Demo Insurance Services
  client admin : {CLIENT_ADMIN[0]} / {CLIENT_ADMIN[1]}
  client agent : {OWN_AGENT[0]} / {OWN_AGENT[1]}
  shared agent : {shared['name']} ({shared['email']}) allocated to the client and the campaign
  vendor id 7001 | ingroups demo_support, demo_sales | campaign id DEMO-RENEW
  Inbound test : http://localhost:5173/agent/call?phonenumber=9876543210&vendor_id=7001&ingroup_id=demo_support
  PD test      : http://localhost:5173/agent/call?phonenumber=9876543211&vendor_id=7001&campaign_id=DEMO-RENEW""")

