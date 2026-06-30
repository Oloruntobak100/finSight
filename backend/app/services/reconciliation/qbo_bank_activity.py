"""Fetch and normalize QuickBooks bank-register activity."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from app.services.quickbooks_service import qb_query
from app.services.reconciliation.identity_matching import parse_finsight_transaction_id

QBO_PAGE_SIZE = 500


def _qb_ref_value(ref: Any) -> str | None:
    if isinstance(ref, dict) and ref.get("value") is not None:
        return str(ref["value"])
    return None


def _parse_period(period_start: str, period_end: str) -> list[tuple[str, str]]:
    """Split long periods into weekly chunks for QBO MAXRESULTS limits."""
    start = datetime.strptime(period_start[:10], "%Y-%m-%d").date()
    end = datetime.strptime(period_end[:10], "%Y-%m-%d").date()
    if (end - start).days <= 31:
        return [(period_start[:10], period_end[:10])]

    chunks: list[tuple[str, str]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=6), end)
        chunks.append((cursor.isoformat(), chunk_end.isoformat()))
        cursor = chunk_end + timedelta(days=1)
    return chunks


async def _query_entity(
    user_id: str,
    entity: str,
    period_start: str,
    period_end: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for chunk_start, chunk_end in _parse_period(period_start, period_end):
        sql = (
            f"SELECT * FROM {entity} WHERE TxnDate >= '{chunk_start}' "
            f"AND TxnDate <= '{chunk_end}' MAXRESULTS {QBO_PAGE_SIZE}"
        )
        try:
            data = await qb_query(user_id, sql)
            batch = data.get("QueryResponse", {}).get(entity, []) or []
            if isinstance(batch, dict):
                batch = [batch]
            items.extend(batch)
        except Exception:
            continue
    return items


def _normalize_purchase(purchase: dict[str, Any], qb_bank_account_id: str) -> dict[str, Any] | None:
    bank_ref = _qb_ref_value(purchase.get("AccountRef"))
    if bank_ref != str(qb_bank_account_id):
        return None
    amount = abs(float(purchase.get("TotalAmt") or 0))
    private_note = purchase.get("PrivateNote") or ""

    return {
        "source": "QBO",
        "qbo_entity_id": str(purchase.get("Id") or ""),
        "qbo_entity_type": "Purchase",
        "transaction_date": str(purchase.get("TxnDate") or "")[:10],
        "amount": amount,
        "signed_amount": -amount,
        "currency": "NGN",
        "direction": "out",
        "payee": (purchase.get("EntityRef") or {}).get("name") or private_note or "",
        "narration": private_note,
        "private_note": private_note,
        "finsight_transaction_id": parse_finsight_transaction_id(private_note),
        "reference": purchase.get("DocNumber") or "",
    }


def _normalize_deposit(deposit: dict[str, Any], qb_bank_account_id: str) -> dict[str, Any] | None:
    bank_ref = _qb_ref_value(deposit.get("DepositToAccountRef"))
    if bank_ref != str(qb_bank_account_id):
        return None
    amount = abs(float(deposit.get("TotalAmt") or 0))
    private_note = deposit.get("PrivateNote") or ""

    return {
        "source": "QBO",
        "qbo_entity_id": str(deposit.get("Id") or ""),
        "qbo_entity_type": "Deposit",
        "transaction_date": str(deposit.get("TxnDate") or "")[:10],
        "amount": amount,
        "signed_amount": amount,
        "currency": "NGN",
        "direction": "in",
        "payee": private_note or "",
        "narration": private_note,
        "private_note": private_note,
        "finsight_transaction_id": parse_finsight_transaction_id(private_note),
        "reference": deposit.get("DocNumber") or "",
    }


def _normalize_transfer(transfer: dict[str, Any], qb_bank_account_id: str) -> dict[str, Any] | None:
    from_ref = _qb_ref_value(transfer.get("FromAccountRef"))
    to_ref = _qb_ref_value(transfer.get("ToAccountRef"))
    target = str(qb_bank_account_id)
    if from_ref == target:
        direction = "out"
        signed = -abs(float(transfer.get("Amount") or 0))
    elif to_ref == target:
        direction = "in"
        signed = abs(float(transfer.get("Amount") or 0))
    else:
        return None
    amount = abs(signed)
    private_note = transfer.get("PrivateNote") or ""

    return {
        "source": "QBO",
        "qbo_entity_id": str(transfer.get("Id") or ""),
        "qbo_entity_type": "Transfer",
        "transaction_date": str(transfer.get("TxnDate") or "")[:10],
        "amount": amount,
        "signed_amount": signed,
        "currency": "NGN",
        "direction": direction,
        "payee": "Transfer",
        "narration": private_note or "Transfer",
        "private_note": private_note,
        "finsight_transaction_id": parse_finsight_transaction_id(private_note),
        "reference": transfer.get("DocNumber") or "",
    }


async def load_qbo_bank_activity(
    user_id: str,
    *,
    qb_bank_account_id: str,
    period_start: str,
    period_end: str,
) -> list[dict[str, Any]]:
    purchases, deposits, transfers = await asyncio.gather(
        _query_entity(user_id, "Purchase", period_start, period_end),
        _query_entity(user_id, "Deposit", period_start, period_end),
        _query_entity(user_id, "Transfer", period_start, period_end),
    )

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for purchase in purchases:
        row = _normalize_purchase(purchase, qb_bank_account_id)
        if row and row["qbo_entity_id"] not in seen_ids:
            seen_ids.add(row["qbo_entity_id"])
            normalized.append(row)

    for deposit in deposits:
        row = _normalize_deposit(deposit, qb_bank_account_id)
        if row and row["qbo_entity_id"] not in seen_ids:
            seen_ids.add(row["qbo_entity_id"])
            normalized.append(row)

    for transfer in transfers:
        row = _normalize_transfer(transfer, qb_bank_account_id)
        if row and row["qbo_entity_id"] not in seen_ids:
            seen_ids.add(row["qbo_entity_id"])
            normalized.append(row)

    normalized.sort(key=lambda r: (r.get("transaction_date") or "", r.get("qbo_entity_id") or ""))
    return normalized


async def qbo_bank_account_balance(user_id: str, qb_bank_account_id: str) -> float | None:
    try:
        sql = f"SELECT * FROM Account WHERE Id = '{qb_bank_account_id}'"
        data = await qb_query(user_id, sql)
        accounts = data.get("QueryResponse", {}).get("Account", []) or []
        if isinstance(accounts, dict):
            accounts = [accounts]
        if not accounts:
            return None
        acct = accounts[0]
        bal = acct.get("CurrentBalance")
        if bal is not None:
            return float(bal)
        return None
    except Exception:
        return None


async def qbo_bank_register_net_through(
    user_id: str,
    qb_bank_account_id: str,
    period_end: str,
) -> float:
    """Net signed bank-register movement through period_end (inclusive)."""
    lines = await load_qbo_bank_activity(
        user_id,
        qb_bank_account_id=qb_bank_account_id,
        period_start="1970-01-01",
        period_end=period_end,
    )
    return round(sum(float(line.get("signed_amount") or 0) for line in lines), 2)


async def qbo_bank_account_balance_as_of(
    user_id: str,
    qb_bank_account_id: str,
    period_end: str,
    *,
    opening_balance_amount: float | None = None,
    opening_balance_as_of: str | None = None,
) -> tuple[float, str, str | None]:
    """Return (balance, source, warning)."""
    if opening_balance_amount is not None and opening_balance_as_of:
        start = opening_balance_as_of[:10]
        if start <= period_end[:10]:
            activity = await load_qbo_bank_activity(
                user_id,
                qb_bank_account_id=qb_bank_account_id,
                period_start=start,
                period_end=period_end,
            )
            net = sum(float(line.get("signed_amount") or 0) for line in activity)
            return round(float(opening_balance_amount) + net, 2), "opening_plus_activity", None

    current = await qbo_bank_account_balance(user_id, qb_bank_account_id)
    warning = "Opening balance not set — book balance may not reflect bank"
    return float(current or 0), "current_balance_fallback", warning
