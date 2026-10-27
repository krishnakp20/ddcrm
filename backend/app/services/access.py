"""Roles and permissions.

A user's effective permissions = the permissions of their role, plus any extra permissions granted to that user,
minus any denied to that user, limited to what their kind of user may hold.

User kinds:  staff  = DialDesk's own admin users      client = a client company's users      agent = call agents
"""
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

USER_TYPES = ("staff", "client", "agent")
TYPE_LABEL = {"staff": "DialDesk admin user", "client": "Client user", "agent": "Agent"}


def P(key: str, label: str, types: tuple[str, ...], hint: str = "") -> dict[str, Any]:
    return {"key": key, "label": label, "types": list(types), "hint": hint}


STAFF, CLIENT, AGENT = "staff", "client", "agent"

# (group, [permissions]). `types` = which kinds of user may hold the permission at all.
CATALOG: list[tuple[str, list[dict[str, Any]]]] = [
    ("Dashboard", [
        P("dashboard.view", "See the dashboard", (STAFF, CLIENT, AGENT)),
    ]),
    ("Clients", [
        P("clients.view", "View clients", (STAFF,)),
        P("clients.manage", "Add, edit, activate, reject and suspend clients", (STAFF,)),
        P("clients.review", "Approve or reject client documents", (STAFF,)),
    ]),
    ("Plans and billing", [
        P("plans.view", "View plans", (STAFF,)),
        P("plans.manage", "Create, edit, clone and retire plans", (STAFF,)),
        P("plans.approve", "Approve or reject plans", (STAFF,), "Use with care: this lets a person release prices."),
        P("plans.assign", "Give plans to clients and set who is not billed", (STAFF,)),
    ]),
    ("Users and access", [
        P("users.view", "View users", (STAFF, CLIENT), "Client users see only their own company's users."),
        P("users.manage", "Add and edit users, and change their role and permissions", (STAFF, CLIENT),
          "Users can only be given access that the person adding them also has."),
        P("departments.manage", "Manage departments", (STAFF, CLIENT)),
        P("roles.manage", "Create and edit roles", (STAFF,)),
    ]),
    ("Campaigns", [
        P("campaigns.view", "See campaigns", (STAFF, CLIENT)),
        P("campaigns.manage", "Create and change campaigns", (STAFF, CLIENT),
          "Client users can only manage their own company's campaigns."),
    ]),
    ("Call and ticket forms", [
        P("forms.view", "See form setup (fields, scenarios, value lists)", (STAFF, CLIENT)),
        P("forms.manage", "Change form setup", (STAFF, CLIENT),
          "Client users can only change their own company's forms."),
    ]),
    ("Tickets", [
        P("tickets.view", "See tickets", (STAFF, CLIENT, AGENT), "Agents see tickets of the clients they work for; client users see their own company's."),
        P("tickets.manage", "Create tickets, comment, change status and assign", (STAFF, CLIENT, AGENT)),
        P("tickets.sla", "Set the SLA (time to resolve) per priority", (STAFF, CLIENT)),
    ]),
    ("Alerts and integrations", [
        P("alerts.manage", "Set up alerts, and the data webhook of campaigns", (STAFF, CLIENT),
          "Client users only manage their own company's alerts."),
    ]),
    ("Reports", [
        P("reports.view", "See and download reports", (STAFF, CLIENT), "Client users only see their own company's numbers."),
    ]),
    ("Dialer data (CDR and APR)", [
        P("cdr.view", "See call records (CDR) and play recordings", (STAFF, CLIENT, AGENT),
          "Client users see their own company's calls; agents only the calls they took."),
        P("apr.view", "See the agent performance report (APR)", (STAFF,)),
        P("dialer.manage", "Manage dialer servers, their keys and pause codes", (STAFF,)),
    ]),
    ("System", [
        P("settings.manage", "Change message templates and see the notification log", (STAFF,)),
    ]),
    ("Company", [
        P("profile.manage", "Edit the company profile and documents", (CLIENT,)),
    ]),
    ("Calls", [
        P("calls.work", "Take and make calls", (AGENT, CLIENT), "Used by the agent workspace, coming soon."),
    ]),
]

PERMISSIONS: dict[str, dict[str, Any]] = {p["key"]: p for _, items in CATALOG for p in items}


def allowed_for(user_type: str) -> set[str]:
    return {k for k, p in PERMISSIONS.items() if user_type in p["types"]}


# Roles created on first start. They can be edited later, except super_admin (always everything).
SYSTEM_ROLES: list[dict[str, Any]] = [
    {"key": "super_admin", "name": "Super admin", "user_type": STAFF, "locked": True,
     "description": "Everything in DialDesk. Cannot be changed.", "permissions": sorted(allowed_for(STAFF))},
    {"key": "operations", "name": "Operations", "user_type": STAFF,
     "description": "Onboards and reviews clients.",
     "permissions": ["dashboard.view", "clients.view", "clients.manage", "clients.review", "plans.view", "users.view",
                     "forms.view", "forms.manage", "campaigns.view", "campaigns.manage", "tickets.view", "tickets.manage", "tickets.sla", "alerts.manage", "reports.view"]},
    {"key": "accounts", "name": "Accounts", "user_type": STAFF,
     "description": "Creates plans and gives them to clients.",
     "permissions": ["dashboard.view", "clients.view", "plans.view", "plans.manage", "plans.assign"]},
    {"key": "support", "name": "Support", "user_type": STAFF,
     "description": "Looks up clients and users to help them.",
     "permissions": ["dashboard.view", "clients.view", "users.view", "tickets.view", "tickets.manage"]},
    {"key": "client_admin", "name": "Client admin", "user_type": CLIENT,
     "description": "Runs the company account: profile, users and departments.",
     "permissions": ["dashboard.view", "profile.manage", "users.view", "users.manage", "departments.manage", "calls.work",
                     "forms.view", "campaigns.view", "tickets.view", "tickets.manage", "tickets.sla", "alerts.manage", "reports.view"]},
    {"key": "client_manager", "name": "Client manager", "user_type": CLIENT,
     "description": "Sees the company's users and activity.",
     "permissions": ["dashboard.view", "users.view", "calls.work", "tickets.view", "tickets.manage"]},
    {"key": "agent", "name": "Agent", "user_type": AGENT,
     "description": "Takes and makes calls.",
     "permissions": ["dashboard.view", "calls.work", "tickets.view", "tickets.manage"]},
]


# Permissions added after a role already existed. Applied once each, so an admin who later removes one is not overruled.
ROLE_ADDITIONS: dict[str, dict[str, list[str]]] = {
    "tickets_v1": {
        "operations": ["tickets.view", "tickets.manage", "tickets.sla"],
        "support": ["tickets.view", "tickets.manage"],
        "client_admin": ["tickets.view", "tickets.manage", "tickets.sla"],
        "client_manager": ["tickets.view", "tickets.manage"],
        "agent": ["tickets.view", "tickets.manage"],
    },
    "alerts_v1": {"operations": ["alerts.manage"], "client_admin": ["alerts.manage"]},
    "cdr_v1": {"operations": ["cdr.view", "apr.view", "dialer.manage"], "support": ["cdr.view"], "accounts": ["cdr.view"],
               "client_admin": ["cdr.view"], "client_manager": ["cdr.view"], "agent": ["cdr.view"]},
    "reports_v1": {"operations": ["reports.view"], "accounts": ["reports.view"], "support": ["reports.view"],
                   "client_admin": ["reports.view"], "client_manager": ["reports.view"]},
}


def ensure_system_roles(db: Session) -> None:
    from ..models import AccessRole, Setting  # local import: models import this module's constants

    have = {r.key: r for r in db.scalars(select(AccessRole))}
    for spec in SYSTEM_ROLES:
        row = have.get(spec["key"])
        if row is None:
            db.add(AccessRole(key=spec["key"], name=spec["name"], description=spec["description"],
                              user_type=spec["user_type"], permissions=spec["permissions"], is_system=True,
                              is_locked=bool(spec.get("locked"))))
        elif row.is_locked:
            row.permissions = spec["permissions"]  # the super admin always has every (current) staff permission
    db.commit()

    flag = db.get(Setting, "role_migrations") or Setting(key="role_migrations", value={"done": []})
    done = list(flag.value.get("done", []))
    for mig, additions in ROLE_ADDITIONS.items():
        if mig in done:
            continue
        for key, perms in additions.items():
            role = db.scalar(select(AccessRole).where(AccessRole.key == key))
            if role and not role.is_locked:
                role.permissions = sorted(set(role.permissions or []) | set(perms))
        done.append(mig)
    flag.value = {"done": done}
    db.add(flag)
    db.commit()


def effective_permissions(user) -> set[str]:
    """What a user may do. Roles that are locked (super admin) always have everything their kind allows."""
    role = user.role
    base = allowed_for(user.user_type) if role and role.is_locked else set(role.permissions if role else [])
    perms = (base | set(user.extra_permissions or [])) - set(user.denied_permissions or [])
    return perms & allowed_for(user.user_type)


def clean_permissions(keys: Iterable[str]) -> list[str]:
    return sorted({k for k in keys if k in PERMISSIONS})
