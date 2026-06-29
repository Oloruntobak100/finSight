from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class CreateRunRequest(BaseModel):
    mono_account_id: str
    qb_bank_account_id: str | None = None
    period_start: str
    period_end: str


class UpdateItemRequest(BaseModel):
    match_status: str | None = None
    confirm_suggested: bool = False
    reject_suggested: bool = False


class TransitionRequest(BaseModel):
    target_status: Literal["DRAFT", "IN_REVIEW", "ADJUSTED", "APPROVED", "LOCKED"]
    comment: str | None = None


class CreateAdjustmentRequest(BaseModel):
    item_id: str | None = None
    adjustment_type: str
    affects_side: Literal["BANK", "BOOK"]
    amount: float
    description: str | None = None
    offset_qb_account_id: str | None = None
    offset_qb_account_name: str | None = None
    journal_entry_required: bool = False


class RunSummary(BaseModel):
    id: str
    status: str
    period_start: str
    period_end: str
    mono_account_id: str | None = None
    qb_bank_account_id: str | None = None
    mono_closing_balance: float | None = None
    qbo_book_balance: float | None = None
    variance: float | None = None
    self_approved: bool | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    balance_proof: dict[str, Any] | None = None
