from fastapi import APIRouter, HTTPException, Query

import logging

from app.auth.dependencies import CurrentUser
from app.models.books import (
    ApproveRequest,
    ApproveResponse,
    BooksSummaryResponse,
    BulkApproveRequest,
    BulkApproveResponse,
    BulkPostRequest,
    BulkPostResponse,
    ClassifyRequest,
    ClassifyResponse,
    CoaAccountResponse,
    CoaListResponse,
    CoaSyncResponse,
    ExcludeRequest,
    IntentRequest,
    MappingResponse,
    MappingUpsertRequest,
    PostRequest,
    PostResponse,
    QbPartyCreateRequest,
    QbPartyCreateResponse,
    QbPartyListResponse,
    QbPartyResponse,
    QbPartySuggestResponse,
    QbPartySyncResponse,
    QueueGroupResponse,
    QueueItemResponse,
    QueueListResponse,
    RejectRequest,
    RevertRequest,
    RevertResponse,
)
from app.services.books_service import (
    approve_transaction,
    approve_transactions_bulk,
    classify_user_transactions,
    ensure_coa_synced,
    exclude_transaction,
    get_mappings,
    get_queue,
    get_queue_groups,
    get_summary,
    list_coa as list_coa_rows,
    post_transaction as post_txn_service,
    post_transactions_bulk,
    reject_suggestion,
    revert_transaction,
    set_posting_intent,
    upsert_mapping as upsert_mapping_service,
)
from app.services.qb_party_service import (
    create_customer,
    create_vendor,
    list_customers,
    list_vendors,
    qb_party_type_for_posting,
    suggest_party_for_txn,
    sync_parties,
)
from app.services.quickbooks_service import get_connection_status, sync_chart_of_accounts
from app.database import get_supabase, run_db

router = APIRouter(prefix="/books", tags=["books"])
logger = logging.getLogger(__name__)


async def _ensure_qb_connected(user_id: str) -> None:
    status = await get_connection_status(user_id)
    if not status.get("connected"):
        raise HTTPException(status_code=400, detail="QuickBooks is not connected")


@router.post("/coa/sync", response_model=CoaSyncResponse)
async def sync_coa(user_id: CurrentUser) -> CoaSyncResponse:
    await _ensure_qb_connected(user_id)
    try:
        result = await sync_chart_of_accounts(user_id)
        return CoaSyncResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/coa", response_model=CoaListResponse)
async def list_coa(
    user_id: CurrentUser,
    account_type: str | None = None,
    fresh: bool = Query(False, description="Pull latest Chart of Accounts from QuickBooks first"),
) -> CoaListResponse:
    if fresh:
        await _ensure_qb_connected(user_id)
        await sync_chart_of_accounts(user_id)
    rows = await list_coa_rows(user_id, account_type)
    items = [
        CoaAccountResponse(
            id=r["id"],
            qb_account_id=r["qb_account_id"],
            name=r["name"],
            account_type=r.get("account_type"),
            account_sub_type=r.get("account_sub_type"),
            active=r.get("active", True),
        )
        for r in rows
    ]
    return CoaListResponse(items=items, total=len(items))


def _party_list_response(user_id: str, vendors: list, customers: list) -> QbPartyListResponse:
    return QbPartyListResponse(
        vendors=[
            QbPartyResponse(
                id=r["id"],
                qb_party_id=r["qb_vendor_id"],
                display_name=r["display_name"],
                party_type="Vendor",
                active=r.get("active", True),
            )
            for r in vendors
        ],
        customers=[
            QbPartyResponse(
                id=r["id"],
                qb_party_id=r["qb_customer_id"],
                display_name=r["display_name"],
                party_type="Customer",
                active=r.get("active", True),
            )
            for r in customers
        ],
    )


@router.post("/parties/sync", response_model=QbPartySyncResponse)
async def sync_qb_parties(user_id: CurrentUser) -> QbPartySyncResponse:
    await _ensure_qb_connected(user_id)
    try:
        result = await sync_parties(user_id)
        return QbPartySyncResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/parties", response_model=QbPartyListResponse)
async def list_qb_parties(
    user_id: CurrentUser,
    fresh: bool = Query(False, description="Pull latest vendors/customers from QuickBooks first"),
) -> QbPartyListResponse:
    if fresh:
        await _ensure_qb_connected(user_id)
        try:
            await sync_parties(user_id)
        except ValueError as exc:
            logger.warning("Party sync degraded to cache for user %s: %s", user_id, exc)
    vendors = await list_vendors(user_id)
    customers = await list_customers(user_id)
    return _party_list_response(user_id, vendors, customers)


@router.post("/parties", response_model=QbPartyCreateResponse)
async def create_qb_party(user_id: CurrentUser, body: QbPartyCreateRequest) -> QbPartyCreateResponse:
    await _ensure_qb_connected(user_id)
    try:
        if body.party_type == "Vendor":
            result = await create_vendor(user_id, body.display_name)
        else:
            result = await create_customer(user_id, body.display_name)
        return QbPartyCreateResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/parties/suggest", response_model=QbPartySuggestResponse)
async def suggest_qb_party(
    user_id: CurrentUser,
    transaction_id: str = Query(...),
    account_id: str = Query(...),
) -> QbPartySuggestResponse:
    await _ensure_qb_connected(user_id)
    sb = get_supabase()
    txn_res = await run_db(
        lambda: sb.table("transactions")
        .select("*")
        .eq("id", transaction_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    txn = txn_res.data
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    coa = await list_coa_rows(user_id)
    coa_row = next((r for r in coa if r.get("qb_account_id") == account_id), None)
    if not coa_row:
        raise HTTPException(status_code=400, detail="Invalid QuickBooks account")

    party_type = qb_party_type_for_posting(
        qb_posting_type=txn.get("qb_posting_type"),
        offset_account_type=coa_row.get("account_type"),
        transaction_type=txn.get("transaction_type"),
    )
    if not party_type:
        raise HTTPException(status_code=400, detail="No vendor or customer applies to this transaction")

    suggestion = await suggest_party_for_txn(user_id, txn, party_type)
    if not suggestion:
        raise HTTPException(status_code=404, detail="No matching vendor or customer found")

    return QbPartySuggestResponse(**suggestion)


@router.get("/mappings", response_model=list[MappingResponse])
async def list_mappings(user_id: CurrentUser) -> list[MappingResponse]:
    await _ensure_qb_connected(user_id)
    await sync_chart_of_accounts(user_id)
    rows = await get_mappings(user_id)
    return [MappingResponse(**r) for r in rows]


@router.put("/mappings", response_model=MappingResponse)
async def upsert_mapping(user_id: CurrentUser, body: MappingUpsertRequest) -> MappingResponse:
    await _ensure_qb_connected(user_id)
    row = await upsert_mapping_service(
        user_id,
        body.mapping_type,
        body.finsight_key,
        body.qb_account_id,
        body.qb_account_name,
    )
    return MappingResponse(**row)


@router.post("/classify", response_model=ClassifyResponse)
async def classify_transactions(
    user_id: CurrentUser,
    body: ClassifyRequest = ClassifyRequest(),
) -> ClassifyResponse:
    await _ensure_qb_connected(user_id)
    await ensure_coa_synced(user_id)
    result = await classify_user_transactions(user_id, body.transaction_ids)
    return ClassifyResponse(**result)


@router.get("/queue", response_model=QueueListResponse)
async def books_queue(
    user_id: CurrentUser,
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
) -> QueueListResponse:
    data = await get_queue(
        user_id, status, page, limit, date_from=date_from, date_to=date_to
    )
    return QueueListResponse(
        items=[QueueItemResponse(**i) for i in data["items"]],
        total=data["total"],
        page=data["page"],
        limit=data["limit"],
        total_pages=data["total_pages"],
    )


@router.get("/groups", response_model=list[QueueGroupResponse])
async def books_queue_groups(
    user_id: CurrentUser,
    status: str = Query("pending"),
) -> list[QueueGroupResponse]:
    groups = await get_queue_groups(user_id, status)
    return [QueueGroupResponse(**g) for g in groups]


@router.get("/summary", response_model=BooksSummaryResponse)
async def books_summary(user_id: CurrentUser) -> BooksSummaryResponse:
    data = await get_summary(user_id)
    return BooksSummaryResponse(**data)


@router.post("/approve", response_model=ApproveResponse)
async def approve_txn(user_id: CurrentUser, body: ApproveRequest) -> ApproveResponse:
    await _ensure_qb_connected(user_id)
    try:
        result = await approve_transaction(
            user_id,
            body.transaction_id,
            body.final_account_id,
            post=body.post,
            payment_account_id=body.payment_account_id,
            final_party_id=body.final_party_id,
            final_party_type=body.final_party_type,
        )
        return ApproveResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/approve/bulk", response_model=BulkApproveResponse)
async def approve_bulk(user_id: CurrentUser, body: BulkApproveRequest) -> BulkApproveResponse:
    await _ensure_qb_connected(user_id)
    try:
        items = (
            [
                {
                    "transaction_id": i.transaction_id,
                    "final_account_id": i.final_account_id,
                    "final_party_id": i.final_party_id,
                    "final_party_type": i.final_party_type,
                }
                for i in body.items
            ]
            if body.items
            else None
        )
        result = await approve_transactions_bulk(
            user_id,
            body.transaction_ids,
            body.payee_pattern,
            items=items,
            post=body.post,
            final_account_id=body.final_account_id,
        )
        return BulkApproveResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reject")
async def reject_txn(user_id: CurrentUser, body: RejectRequest) -> dict:
    try:
        return await reject_suggestion(user_id, body.transaction_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/intent")
async def set_intent(user_id: CurrentUser, body: IntentRequest) -> dict:
    await _ensure_qb_connected(user_id)
    try:
        txn = await set_posting_intent(user_id, body.transaction_id, body.intent)
        return {"intent": body.intent, "transaction": txn}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/post", response_model=PostResponse)
async def post_transaction(user_id: CurrentUser, body: PostRequest) -> PostResponse:
    await _ensure_qb_connected(user_id)
    try:
        result = await post_txn_service(user_id, body.transaction_id)
        return PostResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/post/bulk", response_model=BulkPostResponse)
async def post_bulk(user_id: CurrentUser, body: BulkPostRequest) -> BulkPostResponse:
    await _ensure_qb_connected(user_id)
    result = await post_transactions_bulk(user_id, body.transaction_ids)
    return BulkPostResponse(**result)


@router.post("/exclude")
async def exclude_txn(user_id: CurrentUser, body: ExcludeRequest) -> dict:
    try:
        row = await exclude_transaction(user_id, body.transaction_id)
        return {"excluded": True, "transaction": row}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/revert", response_model=RevertResponse)
async def revert_txn(user_id: CurrentUser, body: RevertRequest) -> RevertResponse:
    try:
        result = await revert_transaction(user_id, body.transaction_id, body.target)
        return RevertResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
