import math
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.auth.dependencies import CurrentUser
from app.database import get_supabase, run_db
from app.models.transaction import CategoryUpdateRequest, TransactionDetails, TransactionListResponse, TransactionResponse
from app.services.transaction_enrichment import extract_transaction_details, reprocess_stored_transactions

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("/meta")
async def transaction_meta(user_id: CurrentUser) -> dict:
    sb = get_supabase()
    txns_res = await run_db(
        lambda: sb.table("transactions").select("category").eq("user_id", user_id).execute()
    )
    accounts_res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("id, account_name, provider")
        .eq("user_id", user_id)
        .neq("status", "disconnected")
        .order("account_name")
        .execute()
    )
    categories = sorted(
        {row["category"] for row in (txns_res.data or []) if row.get("category")}
    )
    total_res = await run_db(
        lambda: sb.table("transactions")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .is_("archived_at", "null")
        .execute()
    )
    synthetic_res = await run_db(
        lambda: sb.table("transactions")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("is_synthetic", True)
        .is_("archived_at", "null")
        .execute()
    )
    return {
        "categories": categories,
        "accounts": accounts_res.data or [],
        "counts": {
            "total": total_res.count or 0,
            "synthetic": synthetic_res.count or 0,
            "non_synthetic": (total_res.count or 0) - (synthetic_res.count or 0),
        },
    }


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
    query = sb.table("transactions").select("*", count="exact").eq("user_id", user_id)

    if not include_archived:
        query = query.is_("archived_at", "null")

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

    accounts_res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("id, account_name")
        .eq("user_id", user_id)
        .execute()
    )
    bank_map = {
        row["id"]: row.get("account_name")
        for row in (accounts_res.data or [])
        if row.get("account_name")
    }

    total = res.count or 0
    items = []
    for row in res.data or []:
        account_id = row.get("account_id")
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
                account_name=bank_map.get(account_id) if account_id else None,
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
