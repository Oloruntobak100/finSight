from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, Field


class FinancialMetricsResponse(BaseModel):
    id: Optional[str] = None
    user_id: Optional[str] = None
    period_start: date
    period_end: date
    total_income: float
    total_expenses: float
    net_cash_flow: float
    savings_rate: Optional[float] = None
    burn_rate: Optional[float] = None
    calculated_at: Optional[str] = None
    data_source: str = "quickbooks"
    books_coverage_pct: Optional[float] = None
    books_posted_count: Optional[int] = None
    books_total_count: Optional[int] = None
    cash_in: Optional[float] = None
    cash_out: Optional[float] = None
    qb_unavailable_reason: Optional[str] = None


class ForecastResponse(BaseModel):
    id: Optional[str] = None
    user_id: Optional[str] = None
    forecast_date: date
    horizon_days: int
    predicted_income: float
    predicted_expenses: float
    projected_balance: float
    confidence_score: Optional[float] = None
    confidence_low: Optional[float] = None
    confidence_high: Optional[float] = None
    currency: str = "USD"
    model_version: Optional[str] = None
    created_at: Optional[str] = None


class SubscriptionResponse(BaseModel):
    merchant_name: str
    amount: float
    currency: str
    frequency: str
    annual_cost: float
    transaction_count: int


class SubscriptionsListResponse(BaseModel):
    items: list[SubscriptionResponse]
    total_monthly: float
    total_annual: float


class BalanceAccountResponse(BaseModel):
    connected_account_id: str
    institution_name: str
    provider: Optional[str] = None
    account_id: str | None = None
    name: str
    type: str | None = None
    subtype: str | None = None
    mask: str | None = None
    current: float
    available: float | None = None
    currency: str = "USD"


class BalancesResponse(BaseModel):
    total_balance: float
    totals_by_currency: dict[str, float] = Field(default_factory=dict)
    primary_currency: str = "USD"
    accounts: list[BalanceAccountResponse]
    as_of: str
    errors: list[str] = []


class MonthlyTrendPoint(BaseModel):
    month: str
    income: float
    expenses: float
    net: float


class YearlyTrendPoint(BaseModel):
    year: str
    income: float
    expenses: float
    net: float


class CategorySpendPoint(BaseModel):
    category: str
    amount: float
    pct: float


class BankSummaryPoint(BaseModel):
    bank: str
    account_id: str | None = None
    provider: str | None = None
    currency: str = "USD"
    income: float
    expenses: float
    net: float
    transaction_count: int


class TopMerchantPoint(BaseModel):
    merchant: str
    amount: float
    count: int


class DailyCashflowPoint(BaseModel):
    date: str
    income: float
    expenses: float
    net: float


class PeriodTotals(BaseModel):
    income: float = 0
    expenses: float = 0
    net: float = 0
    transfer_volume: float = 0
    transaction_count: int = 0


class PeriodComparison(BaseModel):
    label: str = ""
    current: PeriodTotals = Field(default_factory=PeriodTotals)
    previous: PeriodTotals = Field(default_factory=PeriodTotals)
    income_change_pct: float | None = None
    expense_change_pct: float | None = None
    net_change_pct: float | None = None
    transfer_volume_change_pct: float | None = None


class InsightBullet(BaseModel):
    title: str
    body: str
    type: str = "info"


class FinancialAnalysisResponse(BaseModel):
    filters_applied: dict = Field(default_factory=dict)
    primary_currency: str = "USD"
    currencies: list[str] = Field(default_factory=list)
    by_currency: dict = Field(default_factory=dict)
    balances: BalancesResponse
    metrics: dict
    monthly_trend: list[MonthlyTrendPoint]
    yearly_trend: list[YearlyTrendPoint] = Field(default_factory=list)
    category_spending: list[CategorySpendPoint]
    bank_summary: list[BankSummaryPoint]
    top_merchants: list[TopMerchantPoint]
    daily_cashflow: list[DailyCashflowPoint]
    period_comparison: PeriodComparison
    spending_habits: dict = Field(default_factory=dict)
    income_insights: dict = Field(default_factory=dict)
    cash_runway: list[dict] = Field(default_factory=list)
    counterparty_flows: list[dict] = Field(default_factory=list)
    transfer_activity: dict = Field(default_factory=dict)
    anomalies: list[dict] = Field(default_factory=list)
    recurring_detected: list[dict] = Field(default_factory=list)
    account_comparison: dict | None = None
    insights: list[InsightBullet] = Field(default_factory=list)
    transaction_count: int
    data_source: str = "bank"
    qb_unavailable_reason: Optional[str] = None
    books_coverage: dict = Field(default_factory=dict)
    bank_activity: dict = Field(default_factory=dict)
    qb_reports: dict = Field(default_factory=dict)
