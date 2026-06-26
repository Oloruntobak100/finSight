"""Nigeria-realistic Mono transaction narration templates for synthetic feed."""

from __future__ import annotations

import random
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

TxnKind = Literal[
    "nip_out",
    "nip_in",
    "ussd",
    "pos",
    "online",
    "airtime",
    "utility",
    "atm",
    "cash_deposit",
    "cheque",
    "bank_charge",
    "salary",
]

DEFAULT_BANKS = ["GTB", "KUDA", "ZENITH", "UBA", "ACCESS", "FCMB", "OPAY", "PALMPAY"]
DEFAULT_PEOPLE = [
    "CHUKWU EMEKA",
    "ADEBAYO TUNDE",
    "FOLAKE ADESANYA",
    "IBRAHIM MUSA",
    "GLORIA NNADI",
    "SAMUEL OLAMIDE",
    "NGOZI OKAFOR",
    "EMMANUEL ADEYEMI",
]
DEFAULT_MERCHANTS = [
    "SHOPRITE IKEJA",
    "JUMIA NIGERIA LTD",
    "SPORTY BET",
    "HOSTING SUBSCRIPTION",
    "UBER TRIP",
    "CHICKEN REPUBLIC",
]
DEFAULT_EMPLOYERS = [
    "BAPTON GREEN STAR LTD",
    "ACME DIGITAL SERVICES",
    "LAGOS CREATIVE AGENCY",
    "PAYSTACK TITAN",
]
DEFAULT_SUPPLIERS = [
    "ACME SUPPLIES LTD",
    "LANDLORD PROPERTIES LTD",
    "IKEDC PREPAID",
    "MTN NIGERIA",
]

REMARKS = ["NONE", "RNT JUN", "INV 4421", "SALARY", "FOOD", "TRANSPORT", "PAYMENT", "WAGES"]
REMARKS_NO_USER = ["NONE", "NONE", "NONE", "Transfer", "Payment"]


@dataclass
class GeneratedMonoTxn:
    raw: dict[str, Any]
    kind: TxnKind
    ref_stem: str | None = None


def _ref_stem() -> str:
    return f"000013{random.randint(100000000000000, 999999999999999)}"


def _random_amount_kobo(kind: TxnKind) -> int:
    ranges: dict[TxnKind, tuple[int, int]] = {
        "nip_out": (5_000_00, 500_000_00),
        "nip_in": (10_000_00, 2_000_000_00),
        "ussd": (2_000_00, 150_000_00),
        "pos": (1_500_00, 85_000_00),
        "online": (3_000_00, 120_000_00),
        "airtime": (500_00, 10_000_00),
        "utility": (5_000_00, 45_000_00),
        "atm": (5_000_00, 100_000_00),
        "cash_deposit": (20_000_00, 500_000_00),
        "cheque": (50_000_00, 1_000_000_00),
        "bank_charge": (10_00, 5_000_00),
        "salary": (150_000_00, 800_000_00),
    }
    lo, hi = ranges.get(kind, (1_000_00, 50_000_00))
    return random.randint(lo, hi)


def _maybe_category(kind: TxnKind, narration: str) -> str | None:
    """Honest categories — often unknown; salary/rent only when narration supports."""
    lower = narration.lower()
    if kind == "bank_charge":
        return "bank_charge"
    if kind == "salary" or "wages from" in lower or "payroll" in lower:
        return "salary"
    if kind in ("airtime",):
        return "phone_internet"
    if kind == "utility":
        return "utility"
    if kind in ("atm",):
        return "cash_withdrawal"
    if kind in ("cash_deposit",):
        return "cash_deposit"
    if kind == "cheque":
        return "cheque_deposits"
    if kind in ("pos", "online"):
        if random.random() < 0.5:
            return "online_payments"
        return None
    if kind in ("nip_out", "nip_in", "ussd"):
        if random.random() < 0.45:
            return "unknown"
        if random.random() < 0.6:
            return "transfer"
        return None
    if random.random() < 0.4:
        return "unknown"
    return None


def _build_metadata(
    *,
    payee: str | None,
    channel: str | None,
    ref_num: str | None,
    category: str | None,
) -> dict[str, str]:
    na = "N/A"
    return {
        "category": category or "unknown",
        "channel": channel or na,
        "payee": payee or na,
        "payment_method": na,
        "payment_processor": na,
        "ref_num": ref_num or na,
        "location": na,
        "reason": na,
    }


def _pick_remark(use_remark: bool, pool: list[str] | None = None) -> str:
    if not use_remark:
        return random.choice(REMARKS_NO_USER)
    choices = pool or REMARKS
    return random.choice(choices)


def generate_narration(
    kind: TxnKind,
    *,
    payee: str,
    bank: str,
    use_remark: bool,
    ref: str,
    employer: str | None = None,
    merchant: str | None = None,
) -> str:
    remark = _pick_remark(use_remark)
    if kind == "nip_out":
        if use_remark and remark not in ("NONE", "Transfer", "Payment"):
            return f"NIP/{bank}/{payee}/{remark}"
        if random.random() < 0.35:
            return f"NIBSS Instant Payment Outward {ref} TO {payee}/NONE"
        return f"NIP/{bank}/{payee}/NONE"
    if kind == "nip_in":
        if use_remark:
            return f"NIP/{bank}/{payee}/{remark}"
        return f"TRANSFER BETWEEN CUSTOMERS VIA NIP {ref}-NONE-{payee}"
    if kind == "ussd":
        return (
            f"Via USSD {bank} Transfer {ref}/21.5/ from CUSTOMER to {payee}"
        )
    if kind == "pos":
        m = merchant or payee
        return f"POS PURCHASE - {m} LAGOS"
    if kind == "online":
        m = merchant or payee
        return f"PAYSTACK*{m}"
    if kind == "airtime":
        return f"MTN VTU RECHARGE {random.randint(8030000000, 9099999999)}"
    if kind == "utility":
        return f"IKEDC PREPAID {random.randint(100000, 999999)}"
    if kind == "atm":
        return f"ATM WITHDRAWAL - VI LAGOS {ref}"
    if kind == "cash_deposit":
        return f"CASH DEPOSIT - TELLER {ref}"
    if kind == "cheque":
        return f"CHEQUE DEPOSIT - CHQ NO {random.randint(1000, 9999)}"
    if kind == "bank_charge":
        charge_type = random.choice(
            ["NIP CHARGE", "VAT ON NIP TRANSFER", "SMS ALERT CHARGE", "STAMP DUTY", "Electronic Money Transfer Levy"]
        )
        return f"{charge_type} {ref}"
    if kind == "salary":
        emp = employer or payee
        month = datetime.now(timezone.utc).strftime("%b %Y").upper()
        return f"WAGES FROM {emp} {month}"
    return f"{ref} NIP TRANSFER"


def _kind_weights(persona_type: str) -> dict[TxnKind, float]:
    presets: dict[str, dict[TxnKind, float]] = {
        "individual": {
            "nip_out": 0.22,
            "nip_in": 0.12,
            "ussd": 0.08,
            "pos": 0.15,
            "online": 0.08,
            "airtime": 0.10,
            "utility": 0.06,
            "atm": 0.08,
            "cash_deposit": 0.03,
            "cheque": 0.02,
            "bank_charge": 0.05,
            "salary": 0.01,
        },
        "freelancer": {
            "nip_out": 0.18,
            "nip_in": 0.22,
            "ussd": 0.06,
            "pos": 0.10,
            "online": 0.12,
            "airtime": 0.08,
            "utility": 0.05,
            "atm": 0.06,
            "cash_deposit": 0.04,
            "cheque": 0.02,
            "bank_charge": 0.05,
            "salary": 0.02,
        },
        "small_business": {
            "nip_out": 0.28,
            "nip_in": 0.18,
            "ussd": 0.05,
            "pos": 0.08,
            "online": 0.06,
            "airtime": 0.04,
            "utility": 0.08,
            "atm": 0.04,
            "cash_deposit": 0.06,
            "cheque": 0.04,
            "bank_charge": 0.08,
            "salary": 0.01,
        },
        "retail": {
            "nip_out": 0.15,
            "nip_in": 0.12,
            "ussd": 0.04,
            "pos": 0.30,
            "online": 0.05,
            "airtime": 0.03,
            "utility": 0.06,
            "atm": 0.05,
            "cash_deposit": 0.12,
            "cheque": 0.03,
            "bank_charge": 0.05,
            "salary": 0.0,
        },
    }
    return presets.get(persona_type, presets["individual"])


def _pick_kind(persona_type: str) -> TxnKind:
    weights = _kind_weights(persona_type)
    kinds = list(weights.keys())
    probs = [weights[k] for k in kinds]
    return random.choices(kinds, weights=probs, k=1)[0]


def _txn_type_for_kind(kind: TxnKind) -> str:
    if kind in ("nip_in", "cash_deposit", "cheque", "salary"):
        return "credit"
    return "debit"


PERSONA_PRESETS: dict[str, dict[str, Any]] = {
    "individual": {
        "daily_tx_target": 15,
        "remark_rate": 0.25,
        "currency": "NGN",
        "people": DEFAULT_PEOPLE,
        "merchants": DEFAULT_MERCHANTS,
        "banks": DEFAULT_BANKS,
        "employers": DEFAULT_EMPLOYERS,
        "suppliers": DEFAULT_SUPPLIERS,
    },
    "freelancer": {
        "daily_tx_target": 22,
        "remark_rate": 0.30,
        "currency": "NGN",
        "people": DEFAULT_PEOPLE + ["CLIENT CO LTD", "DESIGN STUDIO NG"],
        "merchants": DEFAULT_MERCHANTS + ["FIGMA SUBSCRIPTION", "AWS CLOUD"],
        "banks": DEFAULT_BANKS,
        "employers": [],
        "suppliers": DEFAULT_SUPPLIERS,
    },
    "small_business": {
        "daily_tx_target": 65,
        "remark_rate": 0.35,
        "currency": "NGN",
        "people": DEFAULT_PEOPLE,
        "merchants": DEFAULT_MERCHANTS,
        "banks": DEFAULT_BANKS,
        "employers": DEFAULT_EMPLOYERS,
        "suppliers": DEFAULT_SUPPLIERS + ["OFFICE SUPPLIES NG", "PAYROLL SERVICES"],
    },
    "retail": {
        "daily_tx_target": 100,
        "remark_rate": 0.20,
        "currency": "NGN",
        "people": DEFAULT_PEOPLE,
        "merchants": DEFAULT_MERCHANTS + ["WHOLESALE DEPOT", "CASH REGISTER POS"],
        "banks": DEFAULT_BANKS,
        "employers": [],
        "suppliers": DEFAULT_SUPPLIERS,
    },
}


def merge_persona_config(persona_type: str, overrides: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(PERSONA_PRESETS.get(persona_type, PERSONA_PRESETS["individual"]))
    if overrides:
        base.update({k: v for k, v in overrides.items() if v is not None})
    return base


def drip_batch_size(daily_tx_target: int, live_interval_hours: int) -> int:
    ticks_per_day = max(1, 24 // max(1, live_interval_hours))
    return max(1, round(daily_tx_target / ticks_per_day))


def spread_dates(count: int, start: datetime, end: datetime) -> list[datetime]:
    if count <= 0:
        return []
    if start >= end:
        end = start + timedelta(days=1)
    total_seconds = (end - start).total_seconds()
    dates: list[datetime] = []
    for _ in range(count):
        offset = random.random() * total_seconds
        dt = start + timedelta(seconds=offset)
        # Weekday bias: skip some Sundays
        if dt.weekday() == 6 and random.random() < 0.6:
            dt -= timedelta(days=1)
        dates.append(dt)
    dates.sort()
    return dates


def generate_mono_payload(
    *,
    persona_type: str,
    persona_config: dict[str, Any],
    when: datetime,
    external_prefix: str,
) -> GeneratedMonoTxn:
    config = merge_persona_config(persona_type, persona_config)
    remark_rate = float(config.get("remark_rate", 0.25))
    kind = _pick_kind(persona_type)
    txn_type = _txn_type_for_kind(kind)

    people = config.get("people") or DEFAULT_PEOPLE
    merchants = config.get("merchants") or DEFAULT_MERCHANTS
    banks = config.get("banks") or DEFAULT_BANKS
    employers = config.get("employers") or DEFAULT_EMPLOYERS
    suppliers = config.get("suppliers") or DEFAULT_SUPPLIERS

    if kind == "salary":
        payee = random.choice(employers) if employers else random.choice(suppliers)
        employer = payee
        merchant = None
        bank = random.choice(banks)
    elif kind in ("nip_out", "ussd") and persona_type in ("small_business", "retail"):
        payee = random.choice(suppliers)
        employer = None
        merchant = None
        bank = random.choice(banks)
    elif kind == "nip_in" and persona_type == "freelancer":
        payee = random.choice(config.get("people") or DEFAULT_PEOPLE)
        employer = None
        merchant = None
        bank = random.choice(banks)
    elif kind in ("pos", "online"):
        payee = random.choice(merchants)
        merchant = payee
        employer = None
        bank = random.choice(banks)
    else:
        payee = random.choice(people)
        employer = None
        merchant = None
        bank = random.choice(banks)

    ref = _ref_stem()
    use_remark = random.random() < remark_rate
    narration = generate_narration(
        kind,
        payee=payee,
        bank=bank,
        use_remark=use_remark,
        ref=ref,
        employer=employer,
        merchant=merchant,
    )

    channel = None
    if kind in ("nip_out", "nip_in", "ussd"):
        channel = "NIP"
    elif kind == "pos":
        channel = "POS"
    elif kind == "online":
        channel = "WEB"

    payee_meta = payee if channel else None
    if "/NONE" in narration or narration.endswith("/NONE"):
        payee_meta = payee

    category = _maybe_category(kind, narration)
    metadata = _build_metadata(
        payee=payee_meta,
        channel=channel,
        ref_num=ref,
        category=category,
    )

    amount_kobo = _random_amount_kobo(kind)
    ext_id = f"{external_prefix}{uuid.uuid4().hex}"

    raw: dict[str, Any] = {
        "id": ext_id,
        "narration": narration,
        "amount": amount_kobo,
        "type": txn_type,
        "balance": random.randint(100_000_00, 5_000_000_00),
        "date": when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "category": category,
        "metadata": metadata,
        "_finsight_synthetic": True,
    }

    result = GeneratedMonoTxn(raw=raw, kind=kind, ref_stem=ref)

    # Bank charge siblings: occasionally add VAT line after main NIP
    return result


def generate_charge_sibling(main: GeneratedMonoTxn, when: datetime, external_prefix: str) -> GeneratedMonoTxn | None:
    if main.kind not in ("nip_out", "nip_in", "ussd") or not main.ref_stem:
        return None
    if random.random() > 0.35:
        return None
    ref = main.ref_stem
    charge_kind = random.choice(["NIP CHARGE", "VAT ON NIP TRANSFER"])
    narration = f"{charge_kind} {ref}"
    amount_kobo = random.randint(10_00, 75_00) if "VAT" in charge_kind else random.randint(10_00, 50_00)
    ext_id = f"{external_prefix}{uuid.uuid4().hex}"
    raw: dict[str, Any] = {
        "id": ext_id,
        "narration": narration,
        "amount": amount_kobo,
        "type": "debit",
        "balance": random.randint(100_000_00, 5_000_000_00),
        "date": (when + timedelta(minutes=1)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "category": "bank_charge",
        "metadata": _build_metadata(payee=None, channel="NIP", ref_num=ref, category="bank_charge"),
        "_finsight_synthetic": True,
    }
    return GeneratedMonoTxn(raw=raw, kind="bank_charge", ref_stem=ref)


def narration_has_none_remark(narration: str) -> bool:
    return bool(re.search(r"/NONE\b|NONE-", narration, re.I))
