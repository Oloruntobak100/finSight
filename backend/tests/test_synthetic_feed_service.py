"""Tests for synthetic data feed narration and drip sizing."""

from app.services.synthetic_narration_templates import (
    PERSONA_PRESETS,
    drip_batch_size,
    drip_batch_size_for_profile,
    generate_mono_payload,
    merge_persona_config,
    narration_has_none_remark,
    resolve_daily_tx_range,
)
from app.services.transaction_enrichment import build_mono_transaction_row


def test_drip_batch_size_individual():
    # 15–15/day, every 6h => 4 ticks => ~4 per batch
    assert drip_batch_size(15, 15, 6) == 4
    assert drip_batch_size(20, 20, 6) == 5
    assert drip_batch_size(65, 65, 6) == 16


def test_drip_batch_size_range():
    batch = drip_batch_size(8, 20, 6)
    assert 2 <= batch <= 5


def test_drip_batch_size_for_profile():
    profile = {"daily_tx_min": 15, "daily_tx_max": 15, "live_interval_hours": 6}
    assert drip_batch_size_for_profile(profile) == 4


def test_resolve_daily_tx_range_from_profile():
    lo, hi = resolve_daily_tx_range({"daily_tx_min": 10, "daily_tx_max": 25})
    assert lo == 10
    assert hi == 25


def test_resolve_daily_tx_range_legacy_target():
    lo, hi = resolve_daily_tx_range({"daily_tx_target": 15})
    assert lo == 8
    assert hi == 22


def test_drip_batch_size_minimum_one():
    assert drip_batch_size(1, 1, 24) >= 1


def test_narration_mix_includes_none_and_remarks():
    none_count = 0
    remark_count = 0
    for _ in range(80):
        gen = generate_mono_payload(
            persona_type="individual",
            persona_config={"remark_rate": 0.25},
            when=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            external_prefix="syn-test-",
        )
        narr = gen.raw["narration"]
        if narration_has_none_remark(narr) or "/NONE" in narr.upper():
            none_count += 1
        elif any(k in narr.upper() for k in ("RNT", "INV", "WAGES", "PAYROLL", "SALARY")):
            remark_count += 1
    assert none_count > 10
    assert none_count + remark_count <= 80


def test_salary_category_only_with_wages_narration():
    for _ in range(30):
        gen = generate_mono_payload(
            persona_type="individual",
            persona_config={"remark_rate": 0.5, "employers": ["BAPTON GREEN STAR LTD"]},
            when=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            external_prefix="syn-test-",
        )
        if gen.kind == "salary":
            assert "WAGES FROM" in gen.raw["narration"].upper()
            assert gen.raw.get("category") == "salary"


def test_external_id_prefix():
    gen = generate_mono_payload(
        persona_type="individual",
        persona_config={},
        when=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        external_prefix="syn-live-",
    )
    assert gen.raw["id"].startswith("syn-live-")


def test_build_mono_transaction_row_integration():
    gen = generate_mono_payload(
        persona_type="freelancer",
        persona_config=PERSONA_PRESETS["freelancer"],
        when=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        external_prefix="syn-hist-",
    )
    row = build_mono_transaction_row(
        gen.raw,
        user_id="user-1",
        account_id="acct-1",
        amount=float(gen.raw["amount"]) / 100,
        txn_type=gen.raw["type"],
        currency="NGN",
        external_id=gen.raw["id"],
    )
    assert row["source_provider"] == "mono"
    assert row["merchant_name"] or row["description"]
    assert row["transaction_date"]


def test_persona_presets_merge():
    merged = merge_persona_config("individual", {"remark_rate": 0.4})
    assert merged["remark_rate"] == 0.4
    assert merged["daily_tx_min"] == PERSONA_PRESETS["individual"]["daily_tx_min"]
    assert merged["daily_tx_max"] == PERSONA_PRESETS["individual"]["daily_tx_max"]


def test_rows_helper_handles_none_response():
    from app.services.synthetic_feed_service import _first_row, _rows

    assert _rows(None) == []
    assert _first_row(None) is None
    assert _rows(type("R", (), {"data": []})()) == []
    assert _first_row(type("R", (), {"data": [{"id": "1"}]})()) == {"id": "1"}
