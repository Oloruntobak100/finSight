from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


PersonaType = Literal["individual", "freelancer", "small_business", "retail"]


class PersonaConfig(BaseModel):
    remark_rate: Optional[float] = Field(None, ge=0, le=1)
    currency: Optional[str] = "NGN"
    people: Optional[list[str]] = None
    merchants: Optional[list[str]] = None
    banks: Optional[list[str]] = None
    employers: Optional[list[str]] = None
    suppliers: Optional[list[str]] = None


class ProfileUpdateRequest(BaseModel):
    persona_type: PersonaType = "individual"
    persona_config: Optional[dict[str, Any]] = None
    daily_tx_min: Optional[int] = Field(None, ge=1, le=500)
    daily_tx_max: Optional[int] = Field(None, ge=1, le=500)
    daily_tx_target: Optional[int] = Field(None, ge=1, le=500)  # legacy midpoint
    live_interval_hours: Optional[int] = Field(None, ge=1, le=24)
    auto_classify: Optional[bool] = True
    historical_start: Optional[str] = None
    historical_end: Optional[str] = None


class DateRangeRequest(BaseModel):
    start: str = Field(..., description="ISO date YYYY-MM-DD")
    end: str = Field(..., description="ISO date YYYY-MM-DD")


class FillHistoryRequest(DateRangeRequest):
    count: Optional[int] = Field(None, ge=1, le=2000)


class ImportMonoResponse(BaseModel):
    imported: int
    start: str
    end: str
    run_id: str


class GenerateResponse(BaseModel):
    created: int
    classified: int = 0
    classify_pending: bool = False
    run_id: str
    next_live_run_at: Optional[str] = None


class SyntheticFeedStatusResponse(BaseModel):
    enabled: bool
    accounts: list[dict[str, Any]]


class AccountDetailResponse(BaseModel):
    profile: dict[str, Any]
    runs: list[dict[str, Any]]
    presets: dict[str, Any]
