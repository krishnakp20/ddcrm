"""Plan fields, validation and the per-pulse rates.

The field list is the single source of truth: the API validates against it and the screens are drawn from it
(GET /api/plans/schema), so adding a charge later means adding one line here.
Money and rates are stored as decimal strings (never floats) so billing can use exact arithmetic.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from ..config import settings

PULSES = [1, 6, 10, 30, 60]  # seconds per pulse
PLAN_TYPES = ["prepaid", "postpaid"]
PLAN_MODES = ["monthly", "quarterly", "half_yearly", "yearly"]
MODE_LABEL = {"monthly": "Monthly", "quarterly": "Quarterly", "half_yearly": "Half yearly", "yearly": "Yearly"}


def F(key, label, kind, **kw):
    return {"key": key, "label": label, "kind": kind, **kw}


# (section id, title, fields). kind: text | select | money | pct | int | bool | pulse
SECTIONS: list[tuple[str, str, list[dict[str, Any]]]] = [
    ("basic", "Plan basics", [
        F("plan_name", "Plan name", "text", required=True, core=True),
        F("plan_type", "Plan type", "select", options=PLAN_TYPES, required=True, core=True,
          hint="Prepaid: the client pays first and usage is deducted. Postpaid: usage is billed afterwards."),
        F("plan_mode", "Plan mode (billing period)", "select", options=PLAN_MODES, required=True, core=True),
    ]),
    ("fees", "Fees and credit", [
        F("setup_fee", "Setup fee", "money", unit="Rs."),
        F("subscription_amount", "Subscription amount", "money", unit="Rs.", hint="Charged every plan period."),
        F("credit_value", "Credit value", "money", unit="Rs."),
        F("credit_value_per_mode", "Credit value as per plan mode", "money", unit="Rs."),
        F("subscription_credit_pct", "Subscription credit", "pct", unit="%", hint="Share of the subscription given as usable credit."),
        F("topup_talktime_pct", "Top-up talktime", "pct", unit="%", hint="Share of a top-up given as talktime."),
        F("balance_carry_forward", "Balance carry forward", "bool", hint="Unused balance moves to the next period."),
    ]),
    ("voice", "Voice calls", [
        F("first_minute", "First minute billed in full", "bool"),
        F("ib_day_charge", "Inbound call charge, day shift", "money", unit="Rs./min", pair=("ib_day_pulse", "ib_day_rate")),
        F("ib_day_pulse", "Pulse, day shift", "pulse"),
        F("ib_night_charge", "Inbound call charge, night shift", "money", unit="Rs./min", pair=("ib_night_pulse", "ib_night_rate")),
        F("ib_night_pulse", "Pulse, night shift", "pulse"),
        F("ob_charge", "Outbound call charge", "money", unit="Rs./min", pair=("ob_pulse", "ob_rate")),
        F("ob_pulse", "Pulse, outbound", "pulse"),
        F("ml_ib_charge", "Multi-language inbound charge", "money", unit="Rs./min", pair=("ml_ib_pulse", "ml_ib_rate")),
        F("ml_ib_pulse", "Pulse, multi-language inbound", "pulse"),
        F("ml_ob_charge", "Multi-language outbound charge", "money", unit="Rs./min", pair=("ml_ob_pulse", "ml_ob_rate")),
        F("ml_ob_pulse", "Pulse, multi-language outbound", "pulse"),
        F("miss_call_charge", "Miss call charge", "money", unit="Rs./min"),
        F("ivr_charge", "IVR call charge", "money", unit="Rs./call"),
        F("vfo_charge", "VFO call charge", "money", unit="Rs./min"),
    ]),
    ("messages", "Messages and chat", [
        F("sms_charge", "SMS charge", "money", unit="Rs./SMS", hint="Per SMS of up to 160 characters."),
        F("email_charge", "Email charge", "money", unit="Rs./email"),
        F("whatsapp_charge", "WhatsApp charge", "money", unit="Rs./message"),
        F("ml_live_chat_charge", "Multi-language live chat", "money", unit="Rs."),
    ]),
    ("users", "Users and seats", [
        F("free_users", "Free users included", "int", unit="users"),
        F("extra_user_charge", "Charge per extra user", "money", unit="Rs./user"),
        F("total_seat", "Total seats", "int"),
        F("seat_rate", "Seat rate", "money", unit="Rs."),
        F("remote_user_enabled", "Remote users allowed", "bool"),
        F("remote_user_rate", "Remote user rate", "money", unit="Rs."),
        F("total_remote_user", "Total remote users", "int"),
    ]),
]

FIELDS = {f["key"]: f for _, _, fields in SECTIONS for f in fields}
CONFIG_KEYS = [k for k, f in FIELDS.items() if not f.get("core")]
DEFAULTS = {"pulse": 60, "money": "0", "pct": "0", "int": 0, "bool": False}
MAX_MONEY = Decimal("10000000")


def default_config() -> dict[str, Any]:
    return {k: DEFAULTS[FIELDS[k]["kind"]] for k in CONFIG_KEYS}


def schema() -> dict[str, Any]:
    return {
        "sections": [{"id": sid, "title": title, "fields": fields} for sid, title, fields in SECTIONS],
        "pulses": PULSES, "mode_labels": MODE_LABEL, "defaults": default_config(),
    }


def _dec(value: Any) -> Decimal:
    return Decimal(str(value).strip())


def normalize(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Returns ({plan_name, plan_type, plan_mode, config}, errors). Money is kept as exact decimal text."""
    errors: dict[str, str] = {}
    out: dict[str, Any] = {}
    config = default_config()
    for key, f in FIELDS.items():
        value = raw.get(key)
        blank = value is None or (isinstance(value, str) and not value.strip())
        kind = f["kind"]
        if blank and f.get("required"):
            errors[key] = f"{f['label']} is required"
            continue
        if blank:
            continue  # keeps the default
        try:
            if kind == "text":
                parsed: Any = " ".join(str(value).split())
                if len(parsed) > 150:
                    raise ValueError("Use at most 150 characters")
            elif kind == "select":
                parsed = str(value)
                if parsed not in f["options"]:
                    raise ValueError("Choose one of the listed options")
            elif kind == "pulse":
                parsed = int(value)
                if parsed not in PULSES:
                    raise ValueError("Choose a pulse from the list")
            elif kind == "bool":
                parsed = bool(value) if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")
            elif kind == "int":
                parsed = int(_dec(value))
                if parsed != _dec(value) or not 0 <= parsed <= 1_000_000:
                    raise ValueError("Enter a whole number, 0 or more")
            else:  # money, pct
                d = _dec(value)
                if not d.is_finite() or d < 0:
                    raise ValueError("Enter 0 or more")
                if d != d.quantize(Decimal("0.0001")):
                    raise ValueError("Use at most 4 decimal places")
                if kind == "pct" and d > 100:
                    raise ValueError("A percentage cannot be more than 100")
                if kind == "money" and d > MAX_MONEY:
                    raise ValueError("That amount is too large")
                parsed = format(d.normalize(), "f") if d != 0 else "0"
        except (ValueError, InvalidOperation) as exc:
            errors[key] = str(exc) if isinstance(exc, ValueError) and exc.args else "Enter a valid value"
            continue
        if f.get("core"):
            out[key] = parsed
        else:
            config[key] = parsed
    if config["remote_user_enabled"] and config["total_remote_user"] > 0 and _dec(config["remote_user_rate"]) == 0:
        errors["remote_user_rate"] = "Enter the remote user rate, or switch remote users off"
    out["config"] = add_rates(config)
    return out, errors


def add_rates(config: dict[str, Any]) -> dict[str, Any]:
    """Fills the per-pulse rate for each call charge: rate per pulse = charge per minute x pulse seconds / 60."""
    for key, f in FIELDS.items():
        if f.get("pair"):
            pulse_key, rate_key = f["pair"]
            rate = (_dec(config[key]) * Decimal(config[pulse_key]) / Decimal(60)).quantize(Decimal("0.0001"))
            config[rate_key] = format(rate.normalize(), "f") if rate != 0 else "0"
    return config


def today():
    """Today's date in the CRM's own time zone, not the server's."""
    return datetime.now(ZoneInfo(settings.TIMEZONE)).date()


def timeline(assignments: list, on) -> dict[str, Any]:
    """Splits a client's plan assignments into history / current / upcoming, with the end date of each period."""
    live = sorted((a for a in assignments if not a.cancelled_at), key=lambda a: a.effective_from)
    rows = []
    for i, a in enumerate(live):
        end = live[i + 1].effective_from - timedelta(days=1) if i + 1 < len(live) else None
        rows.append({"assignment": a, "effective_to": end,
                     "state": "upcoming" if a.effective_from > on else ("current" if end is None or end >= on else "past")})
    return {"rows": rows}
