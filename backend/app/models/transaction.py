from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class TransactionDetails(BaseModel):
    """Structured fields extracted from provider raw data (Mono metadata, Plaid counterparties)."""

    flow: Optional[Literal["incoming", "outgoing"]] = None
    flow_label: Optional[str] = None
    counterparty: Optional[str] = None
    counterparty_bank: Optional[str] = None
    channel: Optional[str] = None
    payment_method: Optional[str] = None
    payment_processor: Optional[str] = None
    reference: Optional[str] = None
    location: Optional[str] = None
    reason: Optional[str] = None
    narration: Optional[str] = None
    summary: Optional[str] = None


class TransactionResponse(BaseModel):
    id: str
    user_id: str
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    transaction_date: date
    description: Optional[str] = None
    merchant_name: Optional[str] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    amount: float
    currency: str = "USD"
    amount_usd: Optional[float] = None
    transaction_type: Literal["debit", "credit"]
    source_provider: str
    external_id: str
    is_recurring: bool = False
    created_at: Optional[str] = None
    details: Optional[TransactionDetails] = None
    qb_sync_status: Optional[str] = None
    qb_account_id: Optional[str] = None
    qb_account_name: Optional[str] = None
    qb_confidence: Optional[float] = None
    qb_posted_at: Optional[str] = None
    qb_error: Optional[str] = None


class TransactionListResponse(BaseModel):
    items: list[TransactionResponse]
    total: int
    page: int
    limit: int
    total_pages: int


class CategoryUpdateRequest(BaseModel):
    category: str = Field(..., min_length=1, max_length=100)
