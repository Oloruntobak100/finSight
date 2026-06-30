import math
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.auth.dependencies import CurrentUser
from app.config import settings
from app.database import get_supabase, run_db
from app.models.transaction import CategoryUpdateRequest, TransactionDetails, TransactionListResponse, TransactionResponse
from app.services import synthetic_feed_service as synthetic_feed_svc
from app.services.bank_transaction_scope import (
    apply_active_bank_scope,
    archive_detached_bank_transactions,
    count_scoped_transactions,
    get_active_bank_accounts,
)
from app.services.bank_account_lifecycle import maybe_auto_restore_bank_data
from app.services.transaction_enrichment import extract_transaction_details, reprocess_stored_transactions

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _bank_map(accounts: list[dict]) -> dict[str, str | None]:
    return {
        row["id"]: row.get("account_name")
        for row in accounts
        if row.get("account_name")
    }


@router.get("/meta")
async def transaction_meta(user_id: CurrentUser) -> dict:
    sb = get_supabase()
    bank_accounts, active_bank_ids = await get_active_bank_accounts(user_id)

    categories: set[str] = set()
    if active_bank_ids:
        offset = 0
        while True:
            def _page(off: int = offset) -> object:
                q = sb.table("transactions").select("category").eq("user_id", user_id)
                q = apply_active_bank_scope(q, active_bank_ids)
                return q.range(off, off + 499).execute()

            batch = (await run_db(_page)).data or []
            if not batch:
                break
            for row in batch:
                if row.get("category"):
                    categories.add(row["category"])
            if len(batch) < 500:
                break
            offset += 500

    total = await count_scoped_transactions(user_id, active_bank_ids) if active_bank_ids else 0
    auto_restore = await maybe_auto_restore_bank_data(
        user_id, bank_accounts, visible_count=total
    )
    if auto_restore and active_bank_ids:
        total = await count_scoped_transactions(user_id, active_bank_ids)
    synthetic = 0
    if active_bank_ids:
        syn_res = await run_db(
            lambda: apply_active_bank_scope(
                sb.table("transactions")
                .select("id", count="exact")
                .eq("user_id", user_id)
                .eq("is_synthetic", True),
                active_bank_ids,
            ).execute()
        )
        synthetic = syn_res.count or 0

    counts = {
        "total": total,
        "synthetic": synthetic,
        "non_synthetic": total - synthetic,
    }
    return {
        "categories": sorted(categories),
        "accounts": [
            {
                "id": a["id"],
                "account_name": a.get("account_name"),
                "provider": a.get("provider"),
                "external_account_id": a.get("external_account_id"),
            }
            for a in bank_accounts
        ],
        "counts": counts,
        "cleanup_available": settings.synthetic_feed_allowed and counts["non_synthetic"] > 0,
    }


@router.post("/cleanup/keep-synthetic-only")
async def cleanup_keep_synthetic(user_id: CurrentUser) -> dict:
    if not settings.synthetic_feed_allowed:
        raise HTTPException(status_code=403, detail="Cleanup is only available in Mono sandbox / synthetic feed mode.")
    return await synthetic_feed_svc.keep_synthetic_only_user(user_id)


@router.post("/cleanup/archive-detached")
async def cleanup_archive_detached(user_id: CurrentUser) -> dict:
    archived = await archive_detached_bank_transactions(user_id)
    return {"archived": archived}


@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    user_id: CurrentUser,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    category: Optional[str] = None,
    merchant: Optional[str] = None,
    search: Optional[str] = None,
    account_id: Optional[str] = None,
    transaction_type: Optional[str] = None,
    is_recurring: Optional[bool] = None,
    is_synthetic: Optional[bool] = None,
    include_archived: bool = False,
) -> TransactionListResponse:
    sb = get_supabase()
    bank_accounts, active_bank_ids = await get_active_bank_accounts(user_id)
    bank_map = _bank_map(bank_accounts)

    if active_bank_ids:
        visible = await count_scoped_transactions(user_id, active_bank_ids)
        await maybe_auto_restore_bank_data(user_id, bank_accounts, visible_count=visible)
        bank_accounts, active_bank_ids = await get_active_bank_accounts(user_id)
        bank_map = _bank_map(bank_accounts)

    if not active_bank_ids:
        return TransactionListResponse(
            items=[],
            total=0,
            page=page,
            limit=limit,
            total_pages=1,
        )

    query = sb.table("transactions").select("*", count="exact").eq("user_id", user_id)

    if not include_archived:
        query = apply_active_bank_scope(query, active_bank_ids)
    else:
        query = query.in_("source_provider", ["mono", "plaid"])

    if date_from:
        query = query.gte("transaction_date", date_from)
    if date_to:
        query = query.lte("transaction_date", date_to)
    if category:
        query = query.eq("category", category)
    if merchant:
        query = query.ilike("merchant_name", f"%{merchant}%")
    if search:
        query = query.or_(f"merchant_name.ilike.%{search}%,description.ilike.%{search}%")
    if account_id:
        if account_id not in active_bank_ids:
            raise HTTPException(status_code=400, detail="Account is not an active connected bank.")
        query = query.eq("account_id", account_id)
    if transaction_type in ("debit", "credit"):
        query = query.eq("transaction_type", transaction_type)
    if is_recurring is not None:
        query = query.eq("is_recurring", is_recurring)
    if is_synthetic is not None:
        query = query.eq("is_synthetic", is_synthetic)

    offset = (page - 1) * limit
    res = await run_db(
        lambda: query.order("transaction_date", desc=True)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )

    total = res.count or 0
    items = []
    for row in res.data or []:
        row_account_id = row.get("account_id")
        raw = row.get("raw_metadata") if isinstance(row.get("raw_metadata"), dict) else None
        details_data = extract_transaction_details(
            source_provider=row.get("source_provider") or "",
            transaction_type=row.get("transaction_type") or "debit",
            raw_metadata=raw,
            merchant_name=row.get("merchant_name"),
            description=row.get("description"),
        )
        items.append(
            TransactionResponse(
                **row,
                account_name=bank_map.get(row_account_id) if row_account_id else None,
                details=TransactionDetails(**details_data),
            )
        )
    return TransactionListResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
        total_pages=max(1, math.ceil(total / limit)),
    )


@router.post("/reprocess")
async def reprocess_transactions(user_id: CurrentUser) -> dict:
    """Re-apply merchant, description, and category enrichment from stored raw data."""
    count = await reprocess_stored_transactions(user_id)
    return {"reprocessed": count}


@router.patch("/{transaction_id}/category", response_model=TransactionResponse)
async def update_category(
    transaction_id: str,
    user_id: CurrentUser,
    body: CategoryUpdateRequest,
) -> TransactionResponse:
    sb = get_supabase()
    txn_res = await run_db(
        lambda: sb.table("transactions")
        .select("*")
        .eq("id", transaction_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not txn_res.data:
        raise HTTPException(status_code=404, detail="Transaction not found")

    merchant = txn_res.data.get("merchant_name") or ""
    if merchant:
        await run_db(
            lambda: sb.table("user_category_rules")
            .upsert(
                {
                    "user_id": user_id,
                    "merchant_pattern": merchant.lower(),
                    "assigned_category": body.category,
                },
                on_conflict="user_id,merchant_pattern",
            )
            .execute()
        )

    updated = await run_db(
        lambda: sb.table("transactions")
        .update({"category": body.category})
        .eq("id", transaction_id)
        .execute()
    )
    return TransactionResponse(**updated.data[0])
