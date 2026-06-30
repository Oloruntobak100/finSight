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
    removed: int = 0
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
    remaining_unclassified: int = 0


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
    payee_pattern: Optional[str] = None
    posting_intent: Optional[str] = None
    qb_sync_status: Optional[str] = None
    qb_account_id: Optional[str] = None
    qb_account_name: Optional[str] = None
    qb_payment_account_id: Optional[str] = None
    qb_party_id: Optional[str] = None
    qb_party_type: Optional[str] = None
    qb_party_name: Optional[str] = None
    qb_doc_number: Optional[str] = None
    qb_confidence: Optional[float] = None
    qb_suggestion_method: Optional[str] = None
    qb_confidence_reason: Optional[str] = None
    qb_posting_type: Optional[str] = None
    qb_entity_id: Optional[str] = None
    qb_posted_at: Optional[str] = None
    posted_date: Optional[str] = None
    discovered_date: Optional[str] = None
    posting_lag_days: Optional[int] = None
    qb_error: Optional[str] = None


class QueueListResponse(BaseModel):
    items: list[QueueItemResponse]
    total: int
    page: int
    limit: int
    total_pages: int


class QueueGroupResponse(BaseModel):
    payee_pattern: str
    count: int
    total_amount: float
    qb_account_id: Optional[str] = None
    qb_account_name: Optional[str] = None
    qb_confidence: Optional[float] = None
    qb_suggestion_method: Optional[str] = None
    transaction_ids: list[str]


class PostRequest(BaseModel):
    transaction_id: str
    closed_period_path: Optional[Literal["true_date", "catch_up_today"]] = None
    closed_period_reason: Optional[str] = None


class OpeningBalancePreviewResponse(BaseModel):
    account_id: str
    qb_account_id: Optional[str] = None
    qb_account_name: Optional[str] = None
    suggested_mono_balance: float = 0
    mono_balance_source: str = "none"
    qbo_current_balance: Optional[float] = None
    currency: str = "NGN"
    already_posted: bool = False
    opening_balance_amount: Optional[float] = None
    opening_balance_as_of: Optional[str] = None
    opening_balance_qb_journal_id: Optional[str] = None
    opening_balance_posted_at: Optional[str] = None


class OpeningBalancePostRequest(BaseModel):
    amount: float = Field(..., gt=0)
    as_of_date: str = Field(..., min_length=10, max_length=10)
    qb_bank_account_id: Optional[str] = None


class OpeningBalancePostResponse(BaseModel):
    posted: bool
    journal_entry_id: str
    amount: float
    as_of_date: str
    qb_bank_account_id: str


class BulkPostRequest(BaseModel):
    transaction_ids: list[str] = Field(..., min_length=1)


class ApproveRequest(BaseModel):
    transaction_id: str
    final_account_id: str
    post: bool = False
    payment_account_id: Optional[str] = None
    final_party_id: Optional[str] = None
    final_party_type: Optional[Literal["Vendor", "Customer"]] = None
    closed_period_path: Optional[Literal["true_date", "catch_up_today"]] = None
    closed_period_reason: Optional[str] = None


class BulkApproveItem(BaseModel):
    transaction_id: str
    final_account_id: str
    final_party_id: Optional[str] = None
    final_party_type: Optional[Literal["Vendor", "Customer"]] = None


class BulkApproveRequest(BaseModel):
    items: Optional[list[BulkApproveItem]] = None
    transaction_ids: Optional[list[str]] = None
    payee_pattern: Optional[str] = None
    final_account_id: Optional[str] = None
    post: bool = False


class BulkApproveResponse(BaseModel):
    approved: int
    failed: int
    similar_updated: int = 0
    errors: list[dict[str, str]] = Field(default_factory=list)


class IntentRequest(BaseModel):
    transaction_id: str
    intent: Literal["expense", "income", "transfer", "personal", "fee"]


class RejectRequest(BaseModel):
    transaction_id: str


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


class BooksReadiness(BaseModel):
    qb_connected: bool
    bank_connected: bool
    bank_accounts: list[dict[str, Any]] = []
    qb_environment: Optional[str] = None
    qb_account_name: Optional[str] = None


class BooksCoverage(BaseModel):
    total_bank_transactions: int = 0
    classified: int = 0
    unclassified: int = 0


class BooksSummaryResponse(BaseModel):
    counts: dict[str, int]
    coverage: BooksCoverage = BooksCoverage()
    automation: Optional[dict[str, Any]] = None
    readiness: Optional[BooksReadiness] = None


class ExcludeRequest(BaseModel):
    transaction_id: str


RevertTarget = Literal["needs_review", "unclassified"]


class RevertRequest(BaseModel):
    transaction_id: str
    target: RevertTarget


class RevertResponse(BaseModel):
    transaction_id: str
    previous_status: Optional[str] = None
    target: RevertTarget
    transaction: Optional[dict[str, Any]] = None


class QbPartyResponse(BaseModel):
    id: str
    qb_party_id: str
    display_name: str
    party_type: Literal["Vendor", "Customer"]
    active: bool = True


class QbPartyListResponse(BaseModel):
    vendors: list[QbPartyResponse]
    customers: list[QbPartyResponse]


class QbPartySyncResponse(BaseModel):
    synced: int
    removed: int = 0
    realm_id: Optional[str] = None
    vendors: Optional[dict[str, Any]] = None
    customers: Optional[dict[str, Any]] = None


class QbPartyCreateRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=100)
    party_type: Literal["Vendor", "Customer"]


class QbPartyCreateResponse(BaseModel):
    qb_party_id: str
    qb_party_type: Literal["Vendor", "Customer"]
    qb_party_name: str


class QbPartySuggestResponse(BaseModel):
    qb_party_id: str
    qb_party_type: Literal["Vendor", "Customer"]
    qb_party_name: Optional[str] = None
    match_score: int = 0


class ApproveResponse(BaseModel):
    approved: bool
    transaction_id: str
    decision: Optional[dict[str, Any]] = None
    post: Optional[dict[str, Any]] = None
    transaction: Optional[dict[str, Any]] = None
    similar_updated: int = 0
