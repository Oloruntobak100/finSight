from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field


ComparePeriod = Literal["previous_month", "previous_year", "previous_period"]


class AnalysisFilters(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    providers: list[str] = Field(default_factory=list)
    account_ids: list[str] = Field(default_factory=list)
    include_transfers: bool = False
    compare_account_a: str | None = None
    compare_account_b: str | None = None
    compare_period: ComparePeriod = "previous_month"

    def resolved_date_range(self) -> tuple[date, date]:
        today = date.today()
        end = self.date_to or today
        start = self.date_from or (end - timedelta(days=180))
        if start > end:
            start, end = end, start
        return start, end

    def to_dict(self) -> dict:
        start, end = self.resolved_date_range()
        return {
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "providers": self.providers,
            "account_ids": self.account_ids,
            "include_transfers": self.include_transfers,
            "compare_account_a": self.compare_account_a,
            "compare_account_b": self.compare_account_b,
            "compare_period": self.compare_period,
        }


def parse_analysis_filters(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    provider: list[str] | None = None,
    account_id: list[str] | None = None,
    include_transfers: bool = False,
    compare_account_a: str | None = None,
    compare_account_b: str | None = None,
    compare_period: str = "previous_month",
) -> AnalysisFilters:
    cp: ComparePeriod = "previous_month"
    if compare_period in ("previous_month", "previous_year", "previous_period"):
        cp = compare_period  # type: ignore[assignment]

    return AnalysisFilters(
        date_from=date.fromisoformat(date_from) if date_from else None,
        date_to=date.fromisoformat(date_to) if date_to else None,
        providers=[p.lower() for p in (provider or []) if p],
        account_ids=list(account_id or []),
        include_transfers=include_transfers,
        compare_account_a=compare_account_a,
        compare_account_b=compare_account_b,
        compare_period=cp,
    )
