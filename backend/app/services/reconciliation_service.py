"""Bank vs QuickBooks reconciliation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from app.database import get_supabase, run_db
from app.services.bank_transaction_scope import get_active_bank_accounts
from app.services.books_service import _mapping_lookup, get_mappings, list_coa
from app.services.quickbooks_service import qb_query

BANK_PROVIDERS = ("plaid", "mono")
DATE_TOLERANCE_DAYS = 3
AMOUNT_TOLERANCE_PCT = 0.01
TransactionSide = Literal["debit", "credit", "all"]


def _parse_qb_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _amounts_match(a: float, b: float) -> bool:
    a, b = abs(a), abs(b)
    if a == 0 and b == 0:
        return True
    if max(a, b) == 0:
        return False
    return abs(a - b) / max(a, b) <= AMOUNT_TOLERANCE_PCT


def _dates_match(bank_date: str, qb_date: str | None) -> bool:
    bd = _parse_qb_date(bank_date)
    qd = _parse_qb_date(qb_date)
    if not bd or not qd:
        return False
    return abs((bd - qd).days) <= DATE_TOLERANCE_DAYS


def _qb_ref_value(ref: Any) -> str | None:
    if isinstance(ref, dict) and ref.get("value") is not None:
        return str(ref["value"])
    return None


def _purchase_bank_account_id(purchase: dict[str, Any]) -> str | None:
    return _qb_ref_value(purchase.get("AccountRef"))


def _deposit_bank_account_id(deposit: dict[str, Any]) -> str | None:
    return _qb_ref_value(deposit.get("DepositToAccountRef"))


def _bank_side_types(transaction_side: TransactionSide) -> set[str]:
    if transaction_side == "debit":
        return {"debit"}
    if transaction_side == "credit":
        return {"credit"}
    return {"debit", "credit"}


def _filter_qb_by_bank(
    items: list[dict[str, Any]],
    qb_bank_account_id: str | None,
    *,
    bank_ref: Any,
) -> list[dict[str, Any]]:
    if not qb_bank_account_id:
        return items
    target = str(qb_bank_account_id)
    return [item for item in items if bank_ref(item) == target]


def _match_bank_to_qb(
    bank_txns: list[dict[str, Any]],
    qb_items: list[dict[str, Any]],
    *,
    bank_types: set[str],
    qb_kind: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    matched: list[dict[str, Any]] = []
    unmatched_bank: list[dict[str, Any]] = []
    used_qb: set[int] = set()

    for bank in bank_txns:
        if bank.get("transaction_type") not in bank_types:
            continue
        bank_amount = abs(float(bank.get("amount") or 0))
        found = False
        for idx, qb_item in enumerate(qb_items):
            if idx in used_qb:
                continue
            qb_amount = abs(float(qb_item.get("TotalAmt") or 0))
            if _amounts_match(bank_amount, qb_amount) and _dates_match(
                str(bank.get("transaction_date")), qb_item.get("TxnDate")
            ):
                matched.append({"bank": bank, "qb": qb_item, "qb_kind": qb_kind})
                used_qb.add(idx)
                found = True
                break
        if not found:
            unmatched_bank.append(bank)

    unmatched_qb = [
        {**item, "qb_kind": qb_kind} for i, item in enumerate(qb_items) if i not in used_qb
    ]
    return matched, unmatched_bank, unmatched_qb


async def _resolve_qb_bank_account_id(
    user_id: str,
    *,
    bank_account_id: str | None,
    qb_bank_account_id: str | None,
) -> str | None:
    if qb_bank_account_id:
        return str(qb_bank_account_id)
    if not bank_account_id:
        return None
    mappings = await get_mappings(user_id)
    bank_map = _mapping_lookup(mappings, "bank_account", str(bank_account_id))
    if bank_map and bank_map.get("qb_account_id"):
        return str(bank_map["qb_account_id"])
    return None


async def get_reconciliation_options(user_id: str) -> dict[str, Any]:
    bank_accounts, _ = await get_active_bank_accounts(user_id)
    mappings = await get_mappings(user_id)
    coa = await list_coa(user_id)
    qb_banks = [row for row in coa if row.get("account_type") == "Bank"]

    banks: list[dict[str, Any]] = []
    for account in bank_accounts:
        bank_map = _mapping_lookup(mappings, "bank_account", account["id"])
        banks.append(
            {
                "id": account["id"],
                "account_name": account.get("account_name"),
                "provider": account.get("provider"),
                "qb_account_id": bank_map.get("qb_account_id") if bank_map else None,
                "qb_account_name": bank_map.get("qb_account_name") if bank_map else None,
            }
        )

    return {
        "bank_accounts": banks,
        "qb_bank_accounts": [
            {"qb_account_id": row["qb_account_id"], "name": row.get("name") or "Unknown"}
            for row in qb_banks
        ],
    }


async def reconcile(
    user_id: str,
    period_start: str,
    period_end: str,
    *,
    bank_account_id: str | None = None,
    qb_bank_account_id: str | None = None,
    transaction_side: TransactionSide = "debit",
) -> dict[str, Any]:
    resolved_qb_bank = await _resolve_qb_bank_account_id(
        user_id,
        bank_account_id=bank_account_id,
        qb_bank_account_id=qb_bank_account_id,
    )

    sb = get_supabase()

    def _bank_query() -> Any:
        q = (
            sb.table("transactions")
            .select("*")
            .eq("user_id", user_id)
            .in_("source_provider", list(BANK_PROVIDERS))
            .gte("transaction_date", period_start)
            .lte("transaction_date", period_end)
        )
        if bank_account_id:
            q = q.eq("account_id", bank_account_id)
        return q.execute()

    bank_res = await run_db(_bank_query)
    bank_txns = bank_res.data or []

    accounts, _ = await get_active_bank_accounts(user_id)
    account_names = {a["id"]: a.get("account_name") for a in accounts}
    for txn in bank_txns:
        aid = txn.get("account_id")
        if aid and aid in account_names:
            txn["account_name"] = account_names[aid]

    qb_purchases: list[dict[str, Any]] = []
    qb_deposits: list[dict[str, Any]] = []
    qb_error = False

    need_purchases = transaction_side in ("debit", "all")
    need_deposits = transaction_side in ("credit", "all")

    if need_purchases:
        try:
            sql = (
                f"SELECT * FROM Purchase WHERE TxnDate >= '{period_start}' "
                f"AND TxnDate <= '{period_end}' MAXRESULTS 500"
            )
            qb_data = await qb_query(user_id, sql)
            qb_purchases = qb_data.get("QueryResponse", {}).get("Purchase", []) or []
            if isinstance(qb_purchases, dict):
                qb_purchases = [qb_purchases]
        except Exception:
            qb_purchases = []
            qb_error = True

    if need_deposits:
        try:
            sql = (
                f"SELECT * FROM Deposit WHERE TxnDate >= '{period_start}' "
                f"AND TxnDate <= '{period_end}' MAXRESULTS 500"
            )
            qb_data = await qb_query(user_id, sql)
            qb_deposits = qb_data.get("QueryResponse", {}).get("Deposit", []) or []
            if isinstance(qb_deposits, dict):
                qb_deposits = [qb_deposits]
        except Exception:
            qb_deposits = []
            qb_error = True

    qb_purchases = _filter_qb_by_bank(
        qb_purchases, resolved_qb_bank, bank_ref=_purchase_bank_account_id
    )
    qb_deposits = _filter_qb_by_bank(
        qb_deposits, resolved_qb_bank, bank_ref=_deposit_bank_account_id
    )

    matched: list[dict[str, Any]] = []
    unmatched_bank: list[dict[str, Any]] = []
    unmatched_qb: list[dict[str, Any]] = []

    if need_purchases:
        m, ub, uq = _match_bank_to_qb(
            bank_txns,
            qb_purchases,
            bank_types={"debit"} if transaction_side == "all" else _bank_side_types(transaction_side),
            qb_kind="purchase",
        )
        matched.extend(m)
        unmatched_bank.extend(ub)
        unmatched_qb.extend(uq)

    if need_deposits:
        m, ub, uq = _match_bank_to_qb(
            bank_txns,
            qb_deposits,
            bank_types={"credit"} if transaction_side == "all" else _bank_side_types(transaction_side),
            qb_kind="deposit",
        )
        matched.extend(m)
        unmatched_bank.extend(ub)
        unmatched_qb.extend(uq)

    bank_side_types = _bank_side_types(transaction_side)
    bank_count = len(
        [b for b in bank_txns if b.get("transaction_type") in bank_side_types]
    )

    matched_amount = sum(abs(float(m["bank"].get("amount") or 0)) for m in matched)
    variance = sum(abs(float(b.get("amount") or 0)) for b in unmatched_bank)

    bank_account_name: str | None = None
    if bank_account_id:
        accounts, _ = await get_active_bank_accounts(user_id)
        bank_account_name = next(
            (a.get("account_name") for a in accounts if a.get("id") == bank_account_id),
            None,
        )

    qb_bank_account_name: str | None = None
    if resolved_qb_bank:
        coa = await list_coa(user_id)
        qb_bank_account_name = next(
            (
                row.get("name")
                for row in coa
                if str(row.get("qb_account_id")) == str(resolved_qb_bank)
            ),
            None,
        )

    side_label = {
        "debit": "debits",
        "credit": "credits",
        "all": "transactions",
    }[transaction_side]

    summary = {
        "matched_count": len(matched),
        "unmatched_bank_count": len(unmatched_bank),
        "unmatched_qb_count": len(unmatched_qb),
        "bank_count": bank_count,
        "matched_amount": matched_amount,
        "variance": variance,
        "match_rate": round(len(matched) / max(1, len(matched) + len(unmatched_bank)), 4),
        "transaction_side": transaction_side,
        "side_label": side_label,
        "filters": {
            "bank_account_id": bank_account_id,
            "bank_account_name": bank_account_name,
            "qb_bank_account_id": resolved_qb_bank,
            "qb_bank_account_name": qb_bank_account_name,
        },
    }

    run_row = {
        "user_id": user_id,
        "period_start": period_start,
        "period_end": period_end,
        "summary": summary,
        "matched": matched,
        "unmatched_bank": unmatched_bank,
        "unmatched_qb": unmatched_qb,
    }
    res = await run_db(lambda: sb.table("reconciliation_runs").insert(run_row).execute())
    saved = (res.data or [run_row])[0]

    if bank_account_id and not resolved_qb_bank:
        summary["message"] = (
            "This bank is not mapped to a QuickBooks bank account yet. "
            "Map it under Books → Mappings for tighter matching."
        )
    elif qb_error and bank_txns:
        summary["message"] = (
            "Could not load all QuickBooks transactions for this period. "
            "Check your QuickBooks connection and try again."
        )
    elif not qb_purchases and not qb_deposits and bank_txns:
        summary["message"] = (
            "No QuickBooks transactions found for this period and filters. "
            "Make sure your books are posted and filters are correct."
        )

    return {
        "id": saved.get("id"),
        "summary": summary,
        "matched": matched,
        "unmatched_bank": unmatched_bank,
        "unmatched_qb": unmatched_qb,
    }
