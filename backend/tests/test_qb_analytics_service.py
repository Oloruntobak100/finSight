"""Tests for QuickBooks P&L parsing helpers."""

from app.services.qb_analytics_service import extract_monthly_trend_from_report, extract_pnl_categories, extract_pnl_kpis


def _sample_pnl_report() -> dict:
    return {
        "Columns": {
            "Column": [
                {"ColTitle": "", "ColType": "Account"},
                {"ColTitle": "Jan 2026", "ColType": "Money"},
                {"ColTitle": "Feb 2026", "ColType": "Money"},
            ]
        },
        "Rows": {
            "Row": [
                {
                    "type": "Section",
                    "Header": {"ColData": [{"value": "Income"}]},
                    "Rows": {
                        "Row": [
                            {
                                "type": "Data",
                                "ColData": [
                                    {"value": "Sales"},
                                    {"value": "1000.00"},
                                    {"value": "1200.00"},
                                ],
                            },
                            {
                                "type": "Summary",
                                "Summary": {
                                    "ColData": [
                                        {"value": "Total Income"},
                                        {"value": "1000.00"},
                                        {"value": "1200.00"},
                                    ]
                                },
                            },
                        ]
                    },
                },
                {
                    "type": "Section",
                    "Header": {"ColData": [{"value": "Expenses"}]},
                    "Rows": {
                        "Row": [
                            {
                                "type": "Data",
                                "ColData": [
                                    {"value": "Utilities"},
                                    {"value": "200.00"},
                                    {"value": "250.00"},
                                ],
                            },
                            {
                                "type": "Summary",
                                "Summary": {
                                    "ColData": [
                                        {"value": "Total Expenses"},
                                        {"value": "200.00"},
                                        {"value": "250.00"},
                                    ]
                                },
                            },
                        ]
                    },
                },
                {
                    "type": "Section",
                    "Summary": {
                        "ColData": [
                            {"value": "Net Income"},
                            {"value": "800.00"},
                            {"value": "950.00"},
                        ]
                    },
                },
            ]
        },
    }


def test_extract_pnl_kpis_single_column():
    report = _sample_pnl_report()
    kpis = extract_pnl_kpis(report)
    assert kpis["total_income"] == 1000.0
    assert kpis["total_expenses"] == 200.0
    assert kpis["net_income"] == 800.0


def test_extract_pnl_categories():
    report = _sample_pnl_report()
    cats = extract_pnl_categories(report)
    assert any(c["category"] == "Utilities" for c in cats)


def test_extract_monthly_trend():
    report = _sample_pnl_report()
    trend = extract_monthly_trend_from_report(report)
    assert len(trend) == 2
    assert trend[0]["month"] == "Jan 2026"
    assert trend[0]["income"] == 1000.0
    assert trend[1]["net"] == 950.0
