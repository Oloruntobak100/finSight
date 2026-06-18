from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class CoaAccountResponse(BaseModel):
    id: str
    qb_account_id: str
    name: str
    account_type: Optional[str] = None
    account_sub_type: Optional[str] = None
    active: bool = True


class CoaListResponse(BaseModel):
    items: list[CoaAccountResponse]
    total: int


class CoaSyncResponse(BaseModel):
    synced: int
    realm_id: Optional[str] = None
    cached: Optional[bool] = None


class MappingResponse(BaseModel):
    id: Optional[str] = None
    mapping_type: Literal["bank_account", "category"]
    finsight_key: str
    qb_account_id: str
    qb_account_name: Optional[str] = None


class MappingUpsertRequest(BaseModel):
    mapping_type: Literal["bank_account", "category"]
    finsight_key: str = Field(..., min_length=1)
    qb_account_id: str = Field(..., min_length=1)
    qb_account_name: Optional[str] = None


class ClassifyRequest(BaseModel):
    transaction_ids: Optional[list[str]] = None


class ClassifyResponse(BaseModel):
    classified: int


class QueueItemResponse(BaseModel):
    id: str
    transaction_date: str
    merchant_name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    amount: float
    currency: str = "USD"
    transaction_type: str
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    qb_sync_status: Optional[str] = None
    qb_account_id: Optional[str] = None
    qb_account_name: Optional[str] = None
    qb_payment_account_id: Optional[str] = None
    qb_confidence: Optional[float] = None
    qb_posting_type: Optional[str] = None
    qb_entity_id: Optional[str] = None
    qb_posted_at: Optional[str] = None
    qb_error: Optional[str] = None


class QueueListResponse(BaseModel):
    items: list[QueueItemResponse]
    total: int
    page: int
    limit: int
    total_pages: int


class PostRequest(BaseModel):
    transaction_id: str


class BulkPostRequest(BaseModel):
    transaction_ids: list[str] = Field(..., min_length=1)


class PostResponse(BaseModel):
    posted: Optional[bool] = None
    skipped: Optional[bool] = None
    reason: Optional[str] = None
    qb_entity_id: Optional[str] = None
    transaction: Optional[dict[str, Any]] = None


class BulkPostResponse(BaseModel):
    posted: int
    skipped: int
    failed: int
    errors: list[dict[str, str]]


class BooksSummaryResponse(BaseModel):
    counts: dict[str, int]


class ExcludeRequest(BaseModel):
    transaction_id: str
