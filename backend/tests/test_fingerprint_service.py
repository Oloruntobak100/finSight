"""Tests for transaction fingerprint helpers."""

from app.services.fingerprint_service import amount_band, extract_fingerprint, normalize_payee_pattern


def test_amount_bands():
    assert amount_band(1000) == "<5k"
    assert amount_band(25000) == "5k-50k"
    assert amount_band(200000) == "50k-500k"
    assert amount_band(600000) == ">500k"


def test_normalize_nip_payee():
    pattern = normalize_payee_pattern("NIP/GTB/LANDLORD PROPERTIES LTD/RNT", None)
    assert "landlord" in pattern


def test_extract_fingerprint_mono():
    txn = {
        "source_provider": "mono",
        "amount": 450000,
        "raw_metadata": {
            "narration": "NIP/GTB/LANDLORD PROPERTIES LTD/RNT",
            "metadata": {},
        },
    }
    fp = extract_fingerprint(txn)
    assert fp["channel"] == "NIP"
    assert fp["amount_band"] == "50k-500k"
    assert "landlord" in fp["payee_pattern"]


def test_uber_web_and_pos_share_payee_pattern():
    base = {
        "source_provider": "mono",
        "merchant_name": "Uber Trip",
        "amount": 12000,
    }
    web = {
        **base,
        "raw_metadata": {
            "narration": "Sent to Uber Trip (WEB)",
            "metadata": {"channel": "WEB"},
        },
    }
    pos = {
        **base,
        "raw_metadata": {
            "narration": "Sent to Uber Trip (POS)",
            "metadata": {"channel": "POS"},
        },
    }
    assert extract_fingerprint(web)["payee_pattern"] == extract_fingerprint(pos)["payee_pattern"]
    assert extract_fingerprint(web)["channel"] != extract_fingerprint(pos)["channel"]
