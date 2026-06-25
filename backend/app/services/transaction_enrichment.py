"""Normalize categories, merchants, and descriptions from Plaid and Mono payloads."""

from __future__ import annotations

import re
from typing import Any

from app.services.categorization_service import (
    format_mono_category,
    load_user_category_rules,
    resolve_mono_transaction_category,
)

# Re-export for callers that already import from here.
__all__ = [
    "build_plaid_transaction_row",
    "build_mono_transaction_row",
    "load_user_category_rules",
]


def _title_slug(slug: str | None) -> str | None:
    if not slug:
        return None
    return slug.replace("_", " ").strip().title()


def _apply_user_rules(text: str, user_rules: dict[str, str]) -> str | None:
    lower = text.lower()
    for pattern, category in user_rules.items():
        if pattern and pattern in lower:
            return category
    return None


def _format_plaid_primary(primary: str | None) -> str:
    if not primary:
        return "Uncategorized"
    labels = {
        "INCOME": "Income",
        "TRANSFER_IN": "Transfer In",
        "TRANSFER_OUT": "Transfer Out",
        "LOAN_PAYMENTS": "Loan Payments",
        "BANK_FEES": "Bank Fees",
        "ENTERTAINMENT": "Entertainment",
        "FOOD_AND_DRINK": "Food & Drink",
        "GENERAL_MERCHANDISE": "General Merchandise",
        "HOME_IMPROVEMENT": "Home Improvement",
        "MEDICAL": "Medical",
        "PERSONAL_CARE": "Personal Care",
        "GENERAL_SERVICES": "General Services",
        "GOVERNMENT_AND_NON_PROFIT": "Government & Non-profit",
        "TRANSPORTATION": "Transportation",
        "TRAVEL": "Travel",
        "RENT_AND_UTILITIES": "Rent & Utilities",
    }
    return labels.get(primary, _title_slug(primary) or "Uncategorized")


def _format_plaid_sub_category(primary: str | None, detailed: str | None) -> str | None:
    if not detailed:
        return None
    if primary and detailed.startswith(f"{primary}_"):
        suffix = detailed[len(primary) + 1 :]
        return _title_slug(suffix)
    return _title_slug(detailed)


def _plaid_field(txn: Any, key: str, default: Any = None) -> Any:
    if isinstance(txn, dict):
        return txn.get(key, default)
    return getattr(txn, key, default)


def _plaid_pfc(txn: Any) -> dict[str, Any]:
    pfc = _plaid_field(txn, "personal_finance_category") or {}
    if not isinstance(pfc, dict) and hasattr(pfc, "to_dict"):
        return pfc.to_dict()
    return pfc if isinstance(pfc, dict) else {}


def _plaid_counterparty_merchant(txn: Any) -> str | None:
    for counterparty in _plaid_field(txn, "counterparties") or []:
        if not isinstance(counterparty, dict):
            if hasattr(counterparty, "to_dict"):
                counterparty = counterparty.to_dict()
            else:
                continue
        name = counterparty.get("name")
        if not name:
            continue
        cp_type = (counterparty.get("type") or "").lower()
        if cp_type in {"merchant", "financial_institution", "marketplace", "payment_app"}:
            return name
    return None


def resolve_plaid_category(txn: Any, user_rules: dict[str, str] | None = None) -> tuple[str, str | None]:
    pfc = _plaid_pfc(txn)
    primary = pfc.get("primary")
    detailed = pfc.get("detailed")

    merchant_text = " ".join(
        filter(
            None,
            [
                _plaid_field(txn, "merchant_name"),
                _plaid_field(txn, "name"),
                _plaid_field(txn, "original_description"),
            ],
        )
    )
    if user_rules:
        matched = _apply_user_rules(merchant_text, user_rules)
        if matched:
            return matched, _format_plaid_sub_category(primary, detailed)

    if primary:
        return _format_plaid_primary(primary), _format_plaid_sub_category(primary, detailed)

    legacy = _plaid_field(txn, "category")
    if isinstance(legacy, list) and legacy:
        return str(legacy[0]), str(legacy[-1]) if len(legacy) > 1 else None
    if isinstance(legacy, str) and legacy:
        return legacy, None

    return "Uncategorized", None


def extract_plaid_merchant(txn: Any) -> str | None:
    merchant = _plaid_field(txn, "merchant_name") or _plaid_counterparty_merchant(txn)
    if merchant:
        return merchant
    name = _plaid_field(txn, "name")
    return name if name else None


def extract_plaid_description(txn: Any) -> str | None:
    name = _plaid_field(txn, "name")
    original = _plaid_field(txn, "original_description")
    channel = _plaid_field(txn, "payment_channel")
    location = _plaid_field(txn, "location") or {}
    if not isinstance(location, dict) and hasattr(location, "to_dict"):
        location = location.to_dict()

    parts: list[str] = []
    if original and original != name:
        parts.append(str(original))
    elif name:
        parts.append(str(name))

    if isinstance(location, dict):
        city = location.get("city")
        region = location.get("region")
        if city and region:
            parts.append(f"{city}, {region}")
        elif city:
            parts.append(str(city))

    if channel:
        parts.append(f"via {str(channel).replace('_', ' ')}")

    return " · ".join(parts) if parts else None


def _title_case_name(value: str) -> str:
    return " ".join(word.capitalize() for word in value.split())


def parse_mono_narration(narration: str | None) -> tuple[str | None, str | None]:
    """Parse common Nigerian bank narration formats into merchant + description."""
    parts = parse_mono_narration_parts(narration)
    if not parts:
        if narration and narration.strip():
            return None, narration.strip()
        return None, None

    payee = parts.get("payee")
    bank = parts.get("bank")
    channel = parts.get("channel")
    action = parts.get("action") or "Transfer"

    desc_parts: list[str] = [action]
    if bank:
        desc_parts.append(f"via {bank}")
    if channel and channel.upper() not in {action.upper(), bank.upper() if bank else ""}:
        desc_parts.append(f"({channel})")

    return payee, " ".join(desc_parts)


def parse_mono_narration_parts(narration: str | None) -> dict[str, str] | None:
    """Extract structured NIP/POS/ATM fields from a bank narration string."""
    if not narration:
        return None

    text = narration.strip()
    parts = [p.strip() for p in text.split("/") if p.strip()]
    if len(parts) >= 3 and parts[0].upper() == "NIP":
        bank = _title_case_name(parts[1])
        payee = _title_case_name(parts[2])
        action_raw = parts[3] if len(parts) > 3 else "Transfer"
        action = re.sub(r"\s+\d+$", "", action_raw).strip() or "Transfer"
        return {
            "payee": payee,
            "bank": bank,
            "channel": "NIP",
            "action": action.title(),
        }

    if len(parts) >= 2 and parts[0].upper() in {"POS", "WEB", "ATM"}:
        channel = parts[0].upper()
        merchant = _title_case_name(parts[1])
        return {
            "payee": merchant,
            "channel": channel,
            "action": f"{channel} payment",
        }

    return None


def _mono_flow_prefix(txn_type: str | None) -> str:
    return "Received from" if txn_type == "credit" else "Sent to"


def _mono_metadata_value(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() == "N/A":
        return None
    return text


def extract_mono_merchant(txn: dict[str, Any]) -> str | None:
    metadata = txn.get("metadata") or {}
    payee = _mono_metadata_value(metadata, "payee")
    if payee:
        return _title_case_name(payee)

    parsed_merchant, _ = parse_mono_narration(txn.get("narration"))
    if parsed_merchant:
        return parsed_merchant

    narration = (txn.get("narration") or "").strip()
    return narration[:80] if narration else None


def extract_mono_description(txn: dict[str, Any], txn_type: str | None = None) -> str | None:
    metadata = txn.get("metadata") or {}
    narration = (txn.get("narration") or "").strip()
    parsed = parse_mono_narration_parts(narration)

    payee = _mono_metadata_value(metadata, "payee")
    if payee:
        payee = _title_case_name(payee)
    elif parsed:
        payee = parsed.get("payee")

    bank = parsed.get("bank") if parsed else None
    channel = _mono_metadata_value(metadata, "channel") or (parsed.get("channel") if parsed else None)

    if payee and txn_type:
        summary = _mono_flow_prefix(txn_type) + f" {payee}"
        if bank:
            summary += f" via {bank}"
        if channel:
            summary += f" ({channel.upper() if len(channel) <= 4 else channel.title()})"
    else:
        _, summary = parse_mono_narration(narration)

    parts: list[str] = []
    reason = _mono_metadata_value(metadata, "reason")
    processor = _mono_metadata_value(metadata, "payment_processor")
    payment_method = _mono_metadata_value(metadata, "payment_method")
    location = _mono_metadata_value(metadata, "location")
    ref_num = _mono_metadata_value(metadata, "ref_num")

    if summary:
        parts.append(summary)
    if reason and reason.lower() not in (summary or "").lower():
        parts.append(reason)
    if payment_method:
        parts.append(f"Method: {payment_method}")
    if processor:
        parts.append(f"Processor: {processor}")
    if location:
        parts.append(f"Location: {location}")
    if ref_num:
        parts.append(f"Ref: {ref_num}")
    if narration and narration not in parts and (not summary or narration.lower() not in summary.lower()):
        parts.append(narration)

    seen: set[str] = set()
    unique_parts: list[str] = []
    for part in parts:
        key = part.lower()
        if key in seen:
            continue
        seen.add(key)
        unique_parts.append(part)

    return " · ".join(unique_parts) if unique_parts else None


def resolve_mono_category(
    txn: dict[str, Any],
    user_rules: dict[str, str] | None = None,
    txn_type: str | None = None,
) -> tuple[str, str | None]:
    metadata = txn.get("metadata") or {}
    merged = {**txn, "category": metadata.get("category") or txn.get("category")}
    category = resolve_mono_transaction_category(merged, user_rules, txn_type)

    mono_slug = metadata.get("category") or txn.get("category")
    sub_category = None
    if isinstance(mono_slug, str):
        formatted = format_mono_category(mono_slug)
        if formatted and formatted != category:
            sub_category = formatted

    return category, sub_category


def extract_transaction_details(
    *,
    source_provider: str,
    transaction_type: str,
    raw_metadata: dict[str, Any] | None,
    merchant_name: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Build structured counterparty / channel / reference fields for API responses."""
    flow = "incoming" if transaction_type == "credit" else "outgoing"
    flow_label = "From" if transaction_type == "credit" else "To"

    details: dict[str, Any] = {
        "flow": flow,
        "flow_label": flow_label,
        "counterparty": merchant_name.strip() if merchant_name else None,
        "counterparty_bank": None,
        "channel": None,
        "payment_method": None,
        "payment_processor": None,
        "reference": None,
        "location": None,
        "reason": None,
        "narration": None,
        "summary": description.strip() if description else None,
    }

    if not raw_metadata:
        if details["counterparty"]:
            verb = "Received from" if flow == "incoming" else "Sent to"
            details["summary"] = f"{verb} {details['counterparty']}"
        return details

    if source_provider == "mono":
        metadata = raw_metadata.get("metadata") or {}
        narration = (raw_metadata.get("narration") or "").strip()
        parsed = parse_mono_narration_parts(narration)
        details["narration"] = narration or None

        payee = _mono_metadata_value(metadata, "payee")
        if payee:
            details["counterparty"] = _title_case_name(payee)
        elif parsed and parsed.get("payee"):
            details["counterparty"] = parsed["payee"]

        if parsed and parsed.get("bank"):
            details["counterparty_bank"] = parsed["bank"]

        channel = _mono_metadata_value(metadata, "channel")
        if channel:
            details["channel"] = channel.upper() if len(channel) <= 4 else channel.title()
        elif parsed and parsed.get("channel"):
            details["channel"] = parsed["channel"]

        details["payment_method"] = _mono_metadata_value(metadata, "payment_method")
        details["payment_processor"] = _mono_metadata_value(metadata, "payment_processor")
        details["reference"] = _mono_metadata_value(metadata, "ref_num")
        details["location"] = _mono_metadata_value(metadata, "location")
        details["reason"] = _mono_metadata_value(metadata, "reason")

    elif source_provider == "plaid":
        narration = (
            _plaid_field(raw_metadata, "original_description")
            or _plaid_field(raw_metadata, "name")
            or ""
        )
        details["narration"] = str(narration).strip() or None
        details["channel"] = _plaid_field(raw_metadata, "payment_channel")
        if details["channel"]:
            details["channel"] = str(details["channel"]).replace("_", " ").title()

        location = _plaid_field(raw_metadata, "location") or {}
        if not isinstance(location, dict) and hasattr(location, "to_dict"):
            location = location.to_dict()
        if isinstance(location, dict):
            city = location.get("city")
            region = location.get("region")
            if city and region:
                details["location"] = f"{city}, {region}"
            elif city:
                details["location"] = str(city)

        counterparty = _plaid_counterparty_merchant(raw_metadata)
        if counterparty:
            details["counterparty"] = counterparty
        elif not details["counterparty"]:
            details["counterparty"] = _plaid_field(raw_metadata, "merchant_name") or _plaid_field(
                raw_metadata, "name"
            )

    if details["counterparty"]:
        verb = "Received from" if flow == "incoming" else "Sent to"
        summary_parts = [f"{verb} {details['counterparty']}"]
        if details["counterparty_bank"]:
            summary_parts.append(f"via {details['counterparty_bank']}")
        if details["channel"]:
            summary_parts.append(f"({details['channel']})")
        details["summary"] = " ".join(summary_parts)
    elif details["narration"] and not details["summary"]:
        details["summary"] = details["narration"]

    return details


def build_plaid_transaction_row(
    txn: Any,
    *,
    user_id: str,
    account_id: str,
    amount: float,
    txn_type: str,
    currency: str,
    external_id: str,
    raw_metadata: dict[str, Any],
    user_rules: dict[str, str] | None = None,
) -> dict[str, Any]:
    category, sub_category = resolve_plaid_category(txn, user_rules)
    merchant = extract_plaid_merchant(txn)
    description = extract_plaid_description(txn)

    row = {
        "user_id": user_id,
        "account_id": account_id,
        "transaction_date": str(_plaid_field(txn, "date")),
        "description": description,
        "merchant_name": merchant,
        "category": category,
        "sub_category": sub_category,
        "amount": abs(amount),
        "currency": currency,
        "transaction_type": txn_type,
        "source_provider": "plaid",
        "external_id": external_id,
        "raw_metadata": raw_metadata,
    }
    from app.services.fingerprint_service import fingerprint_fields_for_row

    row.update(fingerprint_fields_for_row(row))
    return row


def build_mono_transaction_row(
    txn: dict[str, Any],
    *,
    user_id: str,
    account_id: str,
    amount: float,
    txn_type: str,
    currency: str,
    external_id: str,
    user_rules: dict[str, str] | None = None,
) -> dict[str, Any]:
    category, sub_category = resolve_mono_category(txn, user_rules, txn_type)
    merchant = extract_mono_merchant(txn)
    description = extract_mono_description(txn, txn_type)

    row = {
        "user_id": user_id,
        "account_id": account_id,
        "transaction_date": (txn.get("date") or "")[:10],
        "description": description,
        "merchant_name": merchant,
        "category": category,
        "sub_category": sub_category,
        "amount": abs(amount),
        "currency": currency,
        "transaction_type": txn_type,
        "source_provider": "mono",
        "external_id": external_id,
        "raw_metadata": txn,
    }
    from app.services.fingerprint_service import fingerprint_fields_for_row

    row.update(fingerprint_fields_for_row({**row, "raw_metadata": txn}))
    return row


async def reprocess_stored_transactions(
    user_id: str,
    account_id: str | None = None,
) -> int:
    """Re-apply enrichment to transactions already in the database."""
    from app.database import get_supabase, run_db

    sb = get_supabase()
    user_rules = await load_user_category_rules(user_id, sb)

    query = sb.table("transactions").select("*").eq("user_id", user_id)
    if account_id:
        query = query.eq("account_id", account_id)

    res = await run_db(lambda: query.execute())
    updated = 0

    for row in res.data or []:
        raw = row.get("raw_metadata")
        if not isinstance(raw, dict) or not raw:
            continue

        provider = row.get("source_provider")
        patch: dict[str, Any] | None = None

        if provider == "mono":
            enriched = build_mono_transaction_row(
                raw,
                user_id=user_id,
                account_id=row["account_id"],
                amount=float(row.get("amount") or 0),
                txn_type=row.get("transaction_type") or "debit",
                currency=row.get("currency") or "NGN",
                external_id=row.get("external_id") or "",
                user_rules=user_rules,
            )
            patch = {
                "merchant_name": enriched["merchant_name"],
                "description": enriched["description"],
                "category": enriched["category"],
                "sub_category": enriched["sub_category"],
            }
        elif provider == "plaid":
            enriched = build_plaid_transaction_row(
                raw,
                user_id=user_id,
                account_id=row["account_id"],
                amount=float(row.get("amount") or 0),
                txn_type=row.get("transaction_type") or "debit",
                currency=row.get("currency") or "USD",
                external_id=row.get("external_id") or "",
                raw_metadata=raw,
                user_rules=user_rules,
            )
            patch = {
                "merchant_name": enriched["merchant_name"],
                "description": enriched["description"],
                "category": enriched["category"],
                "sub_category": enriched["sub_category"],
            }

        if not patch:
            continue

        await run_db(
            lambda r=row, p=patch: sb.table("transactions")
            .update(p)
            .eq("id", r["id"])
            .eq("user_id", user_id)
            .execute()
        )
        updated += 1

    return updated
