"""Call / ticket form setup: field rules, the scenario tree, and checking an agent's answers.

The same `validate_answers` is used by the setup preview now and by the call screen and tickets later,
so a form behaves identically everywhere.
"""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import FormField, Scenario, ScenarioField, ValueItem, ValueList
from . import india

CONTEXTS = {"in_call": "In call (also used when creating a ticket)", "out_call": "Out call"}
MAX_SCENARIO_LEVELS = 5
MAX_LIST_LEVELS = 5

FIELD_TYPES = {
    "text": "Text box", "textarea": "Text area", "number": "Whole number", "decimal": "Decimal number",
    "date": "Date", "datetime": "Date and time", "time": "Time", "select": "Dropdown", "multiselect": "Multi-select",
    "radio": "Radio buttons", "checkbox": "Yes / No tick", "phone": "Mobile number", "email": "Email",
}
CHOICE_TYPES = ("select", "multiselect", "radio")
TEXT_TYPES = ("text", "textarea")
VALIDATIONS = {
    "none": "Anything", "alphanumeric": "Letters and numbers", "alpha": "Letters only", "numeric": "Digits only",
    "pattern": "Custom pattern",
}
OUTCOMES = {
    "connected": "Connected", "not_connected": "Not connected", "callback": "Call back", "converted": "Converted",
    "closed": "Closed", "dnc": "Do not call",
}
RESERVED_KEYS = {"scenario", "scenarios", "path", "client", "client_id", "context"}


def in_scope(model, campaign_id: Optional[int]):
    """Rows of the in-call form have no campaign; rows of an out-call form belong to one campaign."""
    return model.campaign_id.is_(None) if campaign_id is None else model.campaign_id == campaign_id


def slug(label: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    key = re.sub(r"^(\d)", r"f_\1", key)
    return (key or "field")[:40]


# ---------- checking a field definition made by an admin ----------

def check_field_def(body: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    label = (body.get("label") or "").strip()
    if not label:
        errors["label"] = "Name is required"
    elif len(label) > 120:
        errors["label"] = "Use at most 120 characters"
    ftype = body.get("field_type")
    if ftype not in FIELD_TYPES:
        errors["field_type"] = "Choose a type"
    validation = body.get("validation") or "none"
    if validation not in VALIDATIONS:
        errors["validation"] = "Choose a validation"
    elif validation != "none" and ftype not in TEXT_TYPES:
        errors["validation"] = "Validation applies to text boxes only"
    rules = body.get("rules") or {}
    if validation == "pattern":
        try:
            re.compile(rules.get("pattern", ""))
        except re.error:
            errors["rules"] = "The custom pattern is not valid"
        if not rules.get("pattern"):
            errors["rules"] = "Enter the custom pattern"
    for key in ("min_length", "max_length", "min", "max"):
        if rules.get(key) not in (None, ""):
            try:
                Decimal(str(rules[key]))
            except InvalidOperation:
                errors["rules"] = f"{key.replace('_', ' ')} must be a number"
    return errors


# ---------- reading the whole form ----------

def scenario_tree(db: Session, client_id: int, context: str, only_active: bool = False,
                  campaign_id: Optional[int] = None) -> list[dict[str, Any]]:
    rows = list(db.scalars(select(Scenario).where(Scenario.client_id == client_id, Scenario.context == context,
                                                  in_scope(Scenario, campaign_id))
                           .order_by(Scenario.level, Scenario.sort_order, Scenario.id)))
    if only_active:
        rows = [r for r in rows if r.is_active]
    links: dict[int, list[dict[str, Any]]] = {}
    ids = [r.id for r in rows]
    for link in db.scalars(select(ScenarioField).where(ScenarioField.scenario_id.in_(ids or [0]))):
        links.setdefault(link.scenario_id, []).append({"field_id": link.field_id, "required": link.required})
    nodes = {r.id: {"id": r.id, "parent_id": r.parent_id, "level": r.level, "name": r.name, "outcome": r.outcome,
                    "is_active": r.is_active, "sort_order": r.sort_order, "fields": links.get(r.id, []), "children": []}
             for r in rows}
    roots = []
    for r in rows:
        node = nodes[r.id]
        if r.parent_id and r.parent_id in nodes:
            nodes[r.parent_id]["children"].append(node)
        elif not r.parent_id:
            roots.append(node)
    return roots


def field_out(f: FormField) -> dict[str, Any]:
    return {"id": f.id, "key": f.key, "label": f.label, "field_type": f.field_type, "validation": f.validation,
            "rules": f.rules or {}, "required": f.required, "help_text": f.help_text, "sort_order": f.sort_order,
            "is_active": f.is_active, "show_always": f.show_always, "value_list_id": f.value_list_id,
            "list_level": f.list_level, "parent_field_id": f.parent_field_id, "context": f.context}


def form_fields(db: Session, client_id: int, context: str, only_active: bool = False,
                campaign_id: Optional[int] = None) -> list[FormField]:
    stmt = select(FormField).where(FormField.client_id == client_id, FormField.context == context,
                                   in_scope(FormField, campaign_id))
    if only_active:
        stmt = stmt.where(FormField.is_active.is_(True))
    return list(db.scalars(stmt.order_by(FormField.sort_order, FormField.id)))


# ---------- the rules for one scenario path ----------

def path_nodes(db: Session, client_id: int, context: str, path: list[int],
               campaign_id: Optional[int] = None) -> tuple[list[Scenario], Optional[str]]:
    """Checks that `path` is a chain of scenarios from level 1 down to a last level. Returns (nodes, error)."""
    scenarios = list(db.scalars(select(Scenario).where(Scenario.client_id == client_id, Scenario.context == context,
                                                       in_scope(Scenario, campaign_id), Scenario.is_active.is_(True))))
    if not scenarios:
        return [], None if not path else "This form has no scenarios"
    by_id = {s.id: s for s in scenarios}
    children: dict[Optional[int], list[Scenario]] = {}
    for s in scenarios:
        children.setdefault(s.parent_id, []).append(s)
    if not path:
        return [], "Choose the call scenario"
    nodes: list[Scenario] = []
    parent: Optional[int] = None
    for sid in path:
        node = by_id.get(sid)
        if not node or node.parent_id != parent:
            return [], "The chosen scenario does not fit this form"
        nodes.append(node)
        parent = node.id
    if children.get(nodes[-1].id):
        return nodes, f"Choose a more specific option under “{nodes[-1].name}”"
    return nodes, None


def visible_fields(db: Session, client_id: int, context: str, nodes: list[Scenario],
                   campaign_id: Optional[int] = None) -> list[tuple[FormField, bool]]:
    """The fields that apply to this scenario path, each with whether it is mandatory here."""
    ids = [n.id for n in nodes]
    links: dict[int, bool] = {}
    for link in db.scalars(select(ScenarioField).where(ScenarioField.scenario_id.in_(ids or [0]))):
        links[link.field_id] = links.get(link.field_id, False) or link.required
    out = []
    for f in form_fields(db, client_id, context, only_active=True, campaign_id=campaign_id):
        if f.show_always:
            out.append((f, f.required or links.get(f.id, False)))
        elif f.id in links:
            out.append((f, f.required or links[f.id]))
    return out


# ---------- checking an agent's answers ----------

def _item(db: Session, list_id: int, level: int, parent_id: Optional[int], label: str) -> Optional[ValueItem]:
    stmt = select(ValueItem).where(ValueItem.list_id == list_id, ValueItem.level == level, ValueItem.label == label,
                                   ValueItem.is_active.is_(True))
    stmt = stmt.where(ValueItem.parent_id.is_(None) if parent_id is None else ValueItem.parent_id == parent_id)
    return db.scalars(stmt).first()


def validate_answers(db: Session, client_id: int, context: str, path: list[int], answers: dict[str, Any],
                     campaign_id: Optional[int] = None) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """Returns (clean answers, errors by field key, scenario names). `errors` may hold the key "scenario"."""
    errors: dict[str, str] = {}
    nodes, path_error = path_nodes(db, client_id, context, path, campaign_id)
    if path_error:
        errors["scenario"] = path_error
    fields = visible_fields(db, client_id, context, nodes, campaign_id)
    clean: dict[str, Any] = {}
    chosen: dict[int, Optional[ValueItem]] = {}  # the list item each choice field resolved to

    for f, required in fields:
        raw = answers.get(f.key)
        blank = raw is None or raw == "" or raw == []
        if blank:
            if required:
                errors[f.key] = "Required"
            chosen[f.id] = None
            continue
        try:
            clean[f.key] = _check_value(db, f, raw, chosen)
            if f.field_type == "checkbox" and required and clean[f.key] is not True:
                errors[f.key] = "Please tick this"
        except ValueError as exc:
            errors[f.key] = str(exc)
            chosen[f.id] = None
    return clean, errors, [n.name for n in nodes]


def _check_value(db: Session, f: FormField, raw: Any, chosen: dict[int, Optional[ValueItem]]) -> Any:
    r = f.rules or {}
    t = f.field_type
    if t in TEXT_TYPES:
        v = str(raw).strip()
        if f.validation == "alphanumeric" and not re.fullmatch(r"[A-Za-z0-9 ]+", v):
            raise ValueError("Use letters and numbers only")
        if f.validation == "alpha" and not re.fullmatch(r"[A-Za-z ]+", v):
            raise ValueError("Use letters only")
        if f.validation == "numeric" and not re.fullmatch(r"[0-9]+", v):
            raise ValueError("Use digits only")
        if f.validation == "pattern" and not re.fullmatch(r.get("pattern", ".*"), v):
            raise ValueError("Does not match the required format")
        if r.get("min_length") not in (None, "") and len(v) < int(r["min_length"]):
            raise ValueError(f"Enter at least {int(r['min_length'])} characters")
        if r.get("max_length") not in (None, "") and len(v) > int(r["max_length"]):
            raise ValueError(f"Enter at most {int(r['max_length'])} characters")
        return v
    if t in ("number", "decimal"):
        try:
            d = Decimal(str(raw).strip())
        except InvalidOperation:
            raise ValueError("Enter a number")
        if t == "number" and d != d.to_integral_value():
            raise ValueError("Enter a whole number")
        if r.get("min") not in (None, "") and d < Decimal(str(r["min"])):
            raise ValueError(f"Must be at least {r['min']}")
        if r.get("max") not in (None, "") and d > Decimal(str(r["max"])):
            raise ValueError(f"Must be at most {r['max']}")
        return int(d) if t == "number" else format(d.normalize(), "f")
    if t == "date":
        try:
            return date.fromisoformat(str(raw)).isoformat()
        except ValueError:
            raise ValueError("Enter a valid date")
    if t == "datetime":
        try:
            return datetime.fromisoformat(str(raw)).strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            raise ValueError("Enter a valid date and time")
    if t == "time":
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(raw)):
            raise ValueError("Enter a valid time")
        return str(raw)
    if t == "email":
        v = str(raw).strip().lower()
        if not india.EMAIL_RE.match(v):
            raise ValueError("Enter a valid email")
        return v
    if t == "phone":
        v = india.normalize_mobile(str(raw))
        if not india.valid_mobile(v):
            raise ValueError("Enter a valid 10-digit mobile number")
        return v
    if t == "checkbox":
        return bool(raw)
    if t in CHOICE_TYPES:
        return _check_choice(db, f, raw, chosen)
    raise ValueError("Unsupported field")


def _check_choice(db: Session, f: FormField, raw: Any, chosen: dict[int, Optional[ValueItem]]) -> Any:
    if not f.value_list_id:
        raise ValueError("This field has no values set up yet")
    parent_item = None
    if f.parent_field_id:
        parent_item = chosen.get(f.parent_field_id)
        if parent_item is None:
            raise ValueError("Choose the field above first")
    values = raw if f.field_type == "multiselect" and isinstance(raw, list) else [raw]
    if f.field_type != "multiselect" and isinstance(raw, list):
        raise ValueError("Choose one option")
    items = []
    for label in values:
        item = _item(db, f.value_list_id, f.list_level, parent_item.id if parent_item else None, str(label))
        if not item:
            raise ValueError("This option is not available" if not parent_item else
                             f"This option does not belong to “{parent_item.label}”")
        items.append(item)
    chosen[f.id] = items[0]
    return [i.label for i in items] if f.field_type == "multiselect" else items[0].label


# ---------- value lists: reading and importing ----------

def list_out(db: Session, vl: ValueList) -> dict[str, Any]:
    count = len(list(db.scalars(select(ValueItem.id).where(ValueItem.list_id == vl.id))))
    return {"id": vl.id, "client_id": vl.client_id, "name": vl.name, "description": vl.description,
            "level_names": vl.level_names or [], "is_private": vl.is_private, "is_active": vl.is_active,
            "items_count": count}


def import_rows(db: Session, vl: ValueList, rows: list[list[str]]) -> tuple[int, int]:
    """Adds items from rows such as [Country, State, City]. Existing items are reused. Returns (added, skipped rows)."""
    levels = len(vl.level_names)
    cache: dict[tuple[Optional[int], str], ValueItem] = {}
    for it in db.scalars(select(ValueItem).where(ValueItem.list_id == vl.id)):
        cache[(it.parent_id, it.label.lower())] = it
    added = skipped = 0
    for row in rows:
        cells = [c.strip() for c in row[:levels]]
        while cells and not cells[-1]:
            cells.pop()
        if not cells or not all(cells):
            skipped += 1
            continue
        parent: Optional[int] = None
        for depth, label in enumerate(cells, start=1):
            key = (parent, label.lower())
            item = cache.get(key)
            if not item:
                item = ValueItem(list_id=vl.id, parent_id=parent, level=depth, label=label[:200], sort_order=len(cache))
                db.add(item)
                db.flush()
                cache[key] = item
                added += 1
            parent = item.id
    return added, skipped


SHARED_LISTS = [("India: states and union territories", ["State"], [[x] for x in india.STATES])]


def ensure_shared_lists(db: Session) -> None:
    """Lists every client can use. Created once; DialDesk can add more later."""
    for name, levels, rows in SHARED_LISTS:
        if db.scalar(select(ValueList.id).where(ValueList.client_id.is_(None), ValueList.name == name)):
            continue
        vl = ValueList(client_id=None, name=name, level_names=levels, description="Provided by DialDesk")
        db.add(vl)
        db.flush()
        import_rows(db, vl, rows)
    db.commit()


def build_config(db: Session, client, context: str, campaign_id: Optional[int] = None, campaign=None) -> dict[str, Any]:
    """The whole form of one client / campaign: what the setup screens edit and the agent page fills in."""
    fields = form_fields(db, client.id, context, campaign_id=campaign_id)
    list_ids = {f.value_list_id for f in fields if f.value_list_id}
    lists = [list_out(db, vl) for vl in db.scalars(select(ValueList).where(ValueList.id.in_(list_ids or [0])))]
    return {
        "client": {"id": client.id, "name": client.company_name}, "context": context,
        "form_key": "in_call" if campaign_id is None else f"campaign-{campaign_id}",
        "campaign": {"id": campaign.id, "name": campaign.name, "status": campaign.status} if campaign else None,
        "fields": [field_out(f) for f in fields], "scenarios": scenario_tree(db, client.id, context, campaign_id=campaign_id),
        "lists": lists,
        "options": {"field_types": FIELD_TYPES, "validations": VALIDATIONS, "outcomes": OUTCOMES,
                    "contexts": CONTEXTS, "max_levels": MAX_SCENARIO_LEVELS},
    }
