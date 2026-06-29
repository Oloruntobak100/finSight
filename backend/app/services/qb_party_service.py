"""QuickBooks Vendor / Customer sync, lookup, and suggestions."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Literal

from app.database import get_supabase, run_db
from app.services.fingerprint_service import payee_pattern_for_row
from app.services.quickbooks_service import (
    get_valid_account,
    qb_company_post_json,
    qb_query,
)
from app.services.transaction_posting_utils import BALANCE_SHEET_ACCOUNT_TYPES

logger = logging.getLogger(__name__)

QbPartyType = Literal["Vendor", "Customer"]


def normalize_party_lookup(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def qb_party_type_for_posting(
    *,
    qb_posting_type: str | None,
    offset_account_type: str | None,
    transaction_type: str | None,
) -> QbPartyType | None:
    """Whether this post should offer Vendor vs Customer (or neither)."""
    pt = (qb_posting_type or "").strip().lower()
    at = (offset_account_type or "").strip().lower()
    txn_type = (transaction_type or "").strip().lower()

    if pt in ("transfer", "balance_sheet"):
        return None
    if pt in ("expense", "fee", "refund"):
        return "Vendor"
    if pt == "deposit" and at in ("income", "other income"):
        return "Customer"
    if at in BALANCE_SHEET_ACCOUNT_TYPES:
        return None
    if txn_type == "debit" and at in (
        "expense",
        "other expense",
        "cost of goods sold",
    ):
        return "Vendor"
    if txn_type == "credit" and at in ("income", "other income"):
        return "Customer"
    return None


def txn_doc_number(txn: dict[str, Any]) -> str | None:
    """Bank reference for QBO DocNumber when available."""
    raw = txn.get("raw_metadata") or {}
    if not isinstance(raw, dict):
        return None
    meta = raw.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    ref = meta.get("ref_num") or raw.get("reference") or meta.get("reference")
    if not ref:
        return None
    cleaned = str(ref).strip()
    return cleaned[:21] if cleaned else None


def party_display_name_for_txn(txn: dict[str, Any]) -> str:
    payee = payee_pattern_for_row(txn)
    if payee and payee != "unknown":
        return payee.title()
    merchant = (txn.get("merchant_name") or "").strip()
    if merchant:
        return merchant[:100]
    return "Unknown payee"


async def list_vendors(user_id: str) -> list[dict[str, Any]]:
    sb = get_supabase()
    try:
        res = await run_db(
            lambda: sb.table("qb_vendors")
            .select("*")
            .eq("user_id", user_id)
            .eq("active", True)
            .order("display_name")
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.warning("list_vendors failed for %s: %s", user_id, exc)
        return []


async def list_customers(user_id: str) -> list[dict[str, Any]]:
    sb = get_supabase()
    try:
        res = await run_db(
            lambda: sb.table("qb_customers")
            .select("*")
            .eq("user_id", user_id)
            .eq("active", True)
            .order("display_name")
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.warning("list_customers failed for %s: %s", user_id, exc)
        return []


async def _purge_stale_parties(
    user_id: str,
    table: str,
    id_column: str,
    realm_id: str,
    synced_ids: set[str],
) -> int:
    sb = get_supabase()
    await run_db(
        lambda: sb.table(table)
        .delete()
        .eq("user_id", user_id)
        .neq("realm_id", realm_id)
        .execute()
    )
    res = await run_db(
        lambda: sb.table(table)
        .select(id_column)
        .eq("user_id", user_id)
        .eq("realm_id", realm_id)
        .execute()
    )
    stale = [
        str(row[id_column])
        for row in (res.data or [])
        if str(row[id_column]) not in synced_ids
    ]
    if not stale:
        return 0
    await run_db(
        lambda ids=stale: sb.table(table)
        .delete()
        .eq("user_id", user_id)
        .in_(id_column, ids)
        .execute()
    )
    return len(stale)


async def sync_vendors(user_id: str) -> dict[str, Any]:
    account = await get_valid_account(user_id)
    if not account:
        raise ValueError("QuickBooks not connected")

    realm_id = account["realm_id"]
    data = await qb_query(
        user_id,
        "SELECT Id, DisplayName, CompanyName, Active FROM Vendor WHERE Active = true MAXRESULTS 1000",
    )
    items = (data.get("QueryResponse") or {}).get("Vendor") or []
    if isinstance(items, dict):
        items = [items]

    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "user_id": user_id,
            "realm_id": realm_id,
            "qb_vendor_id": str(item.get("Id")),
            "display_name": item.get("DisplayName") or item.get("CompanyName") or "Vendor",
            "active": item.get("Active", True),
            "synced_at": now,
        }
        for item in items
        if item.get("Id")
    ]
    synced_ids = {row["qb_vendor_id"] for row in rows}

    sb = get_supabase()
    if rows:
        await run_db(
            lambda: sb.table("qb_vendors")
            .upsert(rows, on_conflict="user_id,qb_vendor_id")
            .execute()
        )
    removed = await _purge_stale_parties(
        user_id, "qb_vendors", "qb_vendor_id", realm_id, synced_ids
    )
    return {"synced": len(rows), "removed": removed, "realm_id": realm_id}


async def sync_customers(user_id: str) -> dict[str, Any]:
    account = await get_valid_account(user_id)
    if not account:
        raise ValueError("QuickBooks not connected")

    realm_id = account["realm_id"]
    data = await qb_query(
        user_id,
        "SELECT Id, DisplayName, CompanyName, Active FROM Customer WHERE Active = true MAXRESULTS 1000",
    )
    items = (data.get("QueryResponse") or {}).get("Customer") or []
    if isinstance(items, dict):
        items = [items]

    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "user_id": user_id,
            "realm_id": realm_id,
            "qb_customer_id": str(item.get("Id")),
            "display_name": item.get("DisplayName") or item.get("CompanyName") or "Customer",
            "active": item.get("Active", True),
            "synced_at": now,
        }
        for item in items
        if item.get("Id")
    ]
    synced_ids = {row["qb_customer_id"] for row in rows}

    sb = get_supabase()
    if rows:
        await run_db(
            lambda: sb.table("qb_customers")
            .upsert(rows, on_conflict="user_id,qb_customer_id")
            .execute()
        )
    removed = await _purge_stale_parties(
        user_id, "qb_customers", "qb_customer_id", realm_id, synced_ids
    )
    return {"synced": len(rows), "removed": removed, "realm_id": realm_id}


async def sync_parties(user_id: str) -> dict[str, Any]:
    vendors: dict[str, Any] = {"synced": 0, "removed": 0, "error": None}
    customers: dict[str, Any] = {"synced": 0, "removed": 0, "error": None}

    try:
        vendors = await sync_vendors(user_id)
    except ValueError as exc:
        logger.warning("Vendor sync failed for %s: %s", user_id, exc)
        vendors = {"synced": 0, "removed": 0, "error": str(exc)}

    try:
        customers = await sync_customers(user_id)
    except ValueError as exc:
        logger.warning("Customer sync failed for %s: %s", user_id, exc)
        customers = {"synced": 0, "removed": 0, "error": str(exc)}

    if vendors.get("error") and customers.get("error"):
        raise ValueError(
            f"QuickBooks party sync failed: {vendors['error']}; {customers['error']}"
        )

    return {
        "vendors": vendors,
        "customers": customers,
        "synced": int(vendors.get("synced") or 0) + int(customers.get("synced") or 0),
        "removed": int(vendors.get("removed") or 0) + int(customers.get("removed") or 0),
        "realm_id": vendors.get("realm_id") or customers.get("realm_id"),
    }


async def ensure_parties_synced(user_id: str) -> dict[str, Any]:
    return await sync_parties(user_id)


def suggest_party(
    payee_pattern: str | None,
    party_type: QbPartyType,
    parties: list[dict[str, Any]],
    *,
    id_key: str,
) -> dict[str, Any] | None:
    """Best fuzzy match from cached QB vendors/customers."""
    if not payee_pattern or payee_pattern == "unknown" or not parties:
        return None

    needle = normalize_party_lookup(payee_pattern)
    if not needle:
        return None

    best: dict[str, Any] | None = None
    best_score = 0

    for row in parties:
        name = row.get("display_name") or ""
        norm = normalize_party_lookup(name)
        if not norm:
            continue
        score = 0
        if norm == needle:
            score = 100
        elif needle in norm or norm in needle:
            score = 80
        elif any(token in norm for token in needle.split() if len(token) >= 4):
            score = 60
        if score > best_score:
            best_score = score
            best = row

    if not best or best_score < 60:
        return None
    return {
        "qb_party_id": str(best[id_key]),
        "qb_party_type": party_type,
        "qb_party_name": best.get("display_name"),
        "match_score": best_score,
    }


async def suggest_party_for_txn(
    user_id: str,
    txn: dict[str, Any],
    party_type: QbPartyType,
) -> dict[str, Any] | None:
    payee = payee_pattern_for_row(txn)
    if party_type == "Vendor":
        parties = await list_vendors(user_id)
        return suggest_party(payee, party_type, parties, id_key="qb_vendor_id")
    parties = await list_customers(user_id)
    return suggest_party(payee, party_type, parties, id_key="qb_customer_id")


async def validate_party(
    user_id: str,
    party_id: str | None,
    party_type: QbPartyType | None,
) -> tuple[str | None, str | None]:
    if not party_id or not party_type:
        return None, None
    if party_type == "Vendor":
        rows = await list_vendors(user_id)
        for row in rows:
            if str(row.get("qb_vendor_id")) == str(party_id):
                return str(party_id), row.get("display_name")
    else:
        rows = await list_customers(user_id)
        for row in rows:
            if str(row.get("qb_customer_id")) == str(party_id):
                return str(party_id), row.get("display_name")
    raise ValueError(f"Invalid QuickBooks {party_type.lower()}")


async def create_vendor(user_id: str, display_name: str) -> dict[str, Any]:
    name = display_name.strip()
    if not name:
        raise ValueError("Display name is required")
    data = await qb_company_post_json(
        user_id,
        "/vendor?minorversion=75",
        {"DisplayName": name[:100]},
    )
    vendor = data.get("Vendor") or {}
    vendor_id = str(vendor.get("Id") or "")
    if not vendor_id:
        raise ValueError("QuickBooks did not return a vendor id")
    await sync_vendors(user_id)
    return {
        "qb_party_id": vendor_id,
        "qb_party_type": "Vendor",
        "qb_party_name": vendor.get("DisplayName") or name,
    }


async def create_customer(user_id: str, display_name: str) -> dict[str, Any]:
    name = display_name.strip()
    if not name:
        raise ValueError("Display name is required")
    data = await qb_company_post_json(
        user_id,
        "/customer?minorversion=75",
        {"DisplayName": name[:100]},
    )
    customer = data.get("Customer") or {}
    customer_id = str(customer.get("Id") or "")
    if not customer_id:
        raise ValueError("QuickBooks did not return a customer id")
    await sync_customers(user_id)
    return {
        "qb_party_id": customer_id,
        "qb_party_type": "Customer",
        "qb_party_name": customer.get("DisplayName") or name,
    }


def entity_ref_for_txn(txn: dict[str, Any]) -> dict[str, str] | None:
    party_id = txn.get("qb_party_id")
    party_type = txn.get("qb_party_type")
    if not party_id or party_type not in ("Vendor", "Customer"):
        return None
    return {"value": str(party_id), "type": str(party_type)}
