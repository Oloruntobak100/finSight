"""Unit tests for Books Pipeline classification (no QB API)."""

from app.services.books_service import _decision_method, classify_transaction
from app.services.fingerprint_service import extract_fingerprint


def _coa_ids(*ids: str) -> set[str]:
    return set(ids)


def _coa(*rows: tuple[str, str, str]) -> list[dict]:
    """(qb_account_id, name, account_type)"""
    return [
        {"qb_account_id": qb_id, "name": name, "account_type": acct_type}
        for qb_id, name, acct_type in rows
    ]


def test_decision_method_maps_category_for_posting_decisions():
    assert _decision_method("category") == "rule"
    assert _decision_method("auto_detect") == "manual"
    assert _decision_method("fingerprint") == "fingerprint"


def test_transfer_goes_to_review_queue():
    txn = {
        "account_id": "bank-1",
        "category": "Transfer Out",
        "merchant_name": "Kuda",
        "description": "Transfer to own account",
        "transaction_type": "debit",
    }
    mappings = [
        {
            "mapping_type": "bank_account",
            "finsight_key": "bank-1",
            "qb_account_id": "35",
            "qb_account_name": "Checking",
        }
    ]
    coa = _coa(("35", "Checking", "Bank"))
    result = classify_transaction(txn, mappings, {}, coa, _coa_ids("35"))
    assert result["qb_sync_status"] == "needs_review"
    assert result["qb_posting_type"] == "transfer"
    assert result["qb_suggestion_method"] == "auto_detect"


def test_transfer_expense_intent_not_excluded():
    txn = {
        "account_id": "bank-1",
        "category": "Transfer Out",
        "merchant_name": "Landlord",
        "description": "NIP/GTB/LANDLORD/RNT",
        "transaction_type": "debit",
        "posting_intent": "expense",
    }
    mappings = [
        {
            "mapping_type": "bank_account",
            "finsight_key": "bank-1",
            "qb_account_id": "35",
            "qb_account_name": "Checking",
        },
        {
            "mapping_type": "category",
            "finsight_key": "Transfer Out",
            "qb_account_id": "42",
            "qb_account_name": "Rent",
        },
    ]
    coa = _coa(("35", "Checking", "Bank"), ("42", "Rent", "Expense"))
    result = classify_transaction(txn, mappings, {}, coa, _coa_ids("35", "42"))
    assert result["qb_sync_status"] != "excluded"


def test_credit_income_pending():
    txn = {
        "account_id": "bank-1",
        "category": "Salary",
        "merchant_name": "Employer",
        "transaction_type": "credit",
    }
    mappings = [
        {
            "mapping_type": "bank_account",
            "finsight_key": "bank-1",
            "qb_account_id": "35",
            "qb_account_name": "Checking",
        },
        {
            "mapping_type": "category",
            "finsight_key": "Salary",
            "qb_account_id": "50",
            "qb_account_name": "Sales Income",
        },
    ]
    coa = _coa(("35", "Checking", "Bank"), ("50", "Sales Income", "Income"))
    result = classify_transaction(txn, mappings, {}, coa, _coa_ids("35", "50"))
    assert result["qb_sync_status"] == "pending"
    assert result["qb_posting_type"] == "deposit"
    assert result["qb_account_id"] == "50"


def test_bank_fee_maps_to_charges():
    txn = {
        "account_id": "bank-1",
        "category": "Bank Charges",
        "merchant_name": "STAMP DUTY",
        "description": "Stamp duty charge",
        "transaction_type": "debit",
    }
    mappings = [
        {
            "mapping_type": "bank_account",
            "finsight_key": "bank-1",
            "qb_account_id": "35",
            "qb_account_name": "Checking",
        },
    ]
    coa = _coa(("35", "Checking", "Bank"), ("99", "Bank Charges", "Expense"))
    result = classify_transaction(txn, mappings, {}, coa, _coa_ids("35", "99"))
    assert result["qb_posting_type"] == "fee"
    assert result["qb_account_id"] == "99"
    assert result["qb_sync_status"] in ("pending", "needs_review")


def test_category_mapping_pending():
    txn = {
        "account_id": "bank-1",
        "category": "Food",
        "merchant_name": "Starbucks",
        "transaction_type": "debit",
    }
    mappings = [
        {
            "mapping_type": "bank_account",
            "finsight_key": "bank-1",
            "qb_account_id": "35",
            "qb_account_name": "Checking",
        },
        {
            "mapping_type": "category",
            "finsight_key": "Food",
            "qb_account_id": "42",
            "qb_account_name": "Meals",
        },
    ]
    coa = _coa(("35", "Checking", "Bank"), ("42", "Meals", "Expense"))
    result = classify_transaction(txn, mappings, {}, coa, _coa_ids("35", "42"))
    assert result["qb_sync_status"] == "pending"
    assert result["qb_account_id"] == "42"
    assert result["qb_payment_account_id"] == "35"
    assert result["qb_suggestion_method"] == "rule"


def test_fingerprint_match():
    txn = {
        "account_id": "bank-1",
        "category": "Uncategorized",
        "merchant_name": "Landlord",
        "payee_pattern": "landlord properties ltd",
        "transaction_type": "debit",
    }
    mappings = [
        {
            "mapping_type": "bank_account",
            "finsight_key": "bank-1",
            "qb_account_id": "35",
            "qb_account_name": "Checking",
        },
    ]
    coa = _coa(("35", "Checking", "Bank"), ("42", "Rent", "Expense"))
    fp = {
        "id": "fp-1",
        "qb_account_id": "42",
        "qb_account_name": "Rent",
        "confidence": 0.95,
        "recurrence_count": 5,
        **extract_fingerprint(txn),
    }
    result = classify_transaction(
        txn, mappings, {}, coa, _coa_ids("35", "42"), fingerprint_row=fp
    )
    assert result["qb_sync_status"] == "pending"
    assert result["qb_account_id"] == "42"
    assert result["qb_suggestion_method"] == "fingerprint"


def test_payee_fingerprint_suggests_across_channels():
    txn = {
        "account_id": "bank-1",
        "category": "Transportation",
        "merchant_name": "Uber Trip",
        "description": "Sent to Uber Trip (POS)",
        "transaction_type": "debit",
        "amount": 12000,
        "raw_metadata": {
            "narration": "Sent to Uber Trip (POS)",
            "metadata": {"channel": "POS"},
        },
    }
    mappings = [
        {
            "mapping_type": "bank_account",
            "finsight_key": "bank-1",
            "qb_account_id": "35",
            "qb_account_name": "Checking",
        },
    ]
    coa = _coa(("35", "Checking", "Bank"), ("88", "Travel expense", "Expense"))
    fp = {
        "id": "fp-uber",
        "qb_account_id": "88",
        "qb_account_name": "Travel expense",
        "confidence": 1.0,
        "recurrence_count": 1,
        "payee_pattern": "uber trip",
        "channel": "WEB",
        "amount_band": "5k-50k",
    }
    result = classify_transaction(
        txn, mappings, {}, coa, _coa_ids("35", "88"), fingerprint_row=fp
    )
    assert result["qb_account_id"] == "88"
    assert result["qb_suggestion_method"] == "fingerprint"
    assert result["qb_sync_status"] == "needs_review"
    assert result["qb_confidence"] <= 0.84


def test_fingerprint_stale_coa_falls_through():
    txn = {
        "account_id": "bank-1",
        "category": "Uncategorized",
        "merchant_name": "Landlord",
        "payee_pattern": "landlord properties ltd",
        "transaction_type": "debit",
    }
    mappings = [
        {
            "mapping_type": "bank_account",
            "finsight_key": "bank-1",
            "qb_account_id": "35",
            "qb_account_name": "Checking",
        },
    ]
    coa = _coa(("35", "Checking", "Bank"), ("42", "Rent", "Expense"))
    fp = {
        "id": "fp-1",
        "qb_account_id": "99",
        "qb_account_name": "Deleted Account",
        "confidence": 0.95,
        "recurrence_count": 5,
    }
    rag_result = ("42", "Rent", 0.91, "Similar to prior rent payment")
    result = classify_transaction(
        txn,
        mappings,
        {},
        coa,
        _coa_ids("35", "42"),
        fingerprint_row=fp,
        rag_result=rag_result,
    )
    assert result["qb_suggestion_method"] == "rag"
    assert result["qb_account_id"] == "42"


def test_missing_bank_mapping_needs_review():
    txn = {
        "account_id": "bank-1",
        "category": "Food",
        "merchant_name": "Starbucks",
        "transaction_type": "debit",
    }
    mappings = [
        {
            "mapping_type": "category",
            "finsight_key": "Food",
            "qb_account_id": "42",
            "qb_account_name": "Meals",
        },
    ]
    coa = _coa(("42", "Meals", "Expense"))
    result = classify_transaction(txn, mappings, {}, coa, _coa_ids("42"))
    assert result["qb_sync_status"] == "needs_review"


def test_auto_approve_when_opted_in():
    txn = {
        "account_id": "bank-1",
        "category": "Uncategorized",
        "merchant_name": "Landlord",
        "payee_pattern": "landlord properties ltd",
        "transaction_type": "debit",
    }
    mappings = [
        {
            "mapping_type": "bank_account",
            "finsight_key": "bank-1",
            "qb_account_id": "35",
            "qb_account_name": "Checking",
        },
    ]
    coa = _coa(("35", "Checking", "Bank"), ("42", "Rent", "Expense"))
    fp = {
        "id": "fp-1",
        "qb_account_id": "42",
        "qb_account_name": "Rent",
        "confidence": 0.95,
        "recurrence_count": 10,
        **extract_fingerprint(txn),
    }
    automation = {"auto_approve_enabled": True, "auto_approve_threshold": 0.90}
    result = classify_transaction(
        txn,
        mappings,
        {},
        coa,
        _coa_ids("35", "42"),
        fingerprint_row=fp,
        automation=automation,
    )
    assert result["qb_sync_status"] == "auto_approved"
    assert result["qb_suggestion_method"] == "fingerprint"


def test_balance_sheet_goes_to_review_queue():
    txn = {
        "account_id": "bank-1",
        "category": "Loan Repayment",
        "transaction_type": "debit",
        "amount": 50000,
    }
    result = classify_transaction(txn, [], {}, _coa(), _coa_ids())
    assert result["qb_sync_status"] == "needs_review"
    assert result["qb_posting_type"] == "balance_sheet"
    assert result["qb_suggestion_method"] == "auto_detect"
    assert "map to" in (result["qb_confidence_reason"] or "").lower()


def test_refund_uses_expense_coa_path():
    txn = {
        "account_id": "bank-1",
        "category": "Shopping",
        "merchant_name": "Vendor",
        "description": "Refund for returned item",
        "transaction_type": "credit",
        "amount": 10000,
    }
    mappings = [
        {
            "mapping_type": "bank_account",
            "finsight_key": "bank-1",
            "qb_account_id": "35",
            "qb_account_name": "Checking",
        },
        {
            "mapping_type": "category",
            "finsight_key": "Shopping",
            "qb_account_id": "42",
            "qb_account_name": "Supplies",
        },
    ]
    coa = _coa(("35", "Checking", "Bank"), ("42", "Supplies", "Expense"))
    result = classify_transaction(txn, mappings, {}, coa, _coa_ids("35", "42"))
    assert result["qb_posting_type"] == "refund"
    assert result["qb_account_id"] == "42"
    assert result["qb_suggestion_method"] == "rule"



def test_nip_credit_is_income_not_excluded():
    txn = {
        "account_id": "bank-1",
        "category": "Other Income",
        "merchant_name": "Samuel Olamide",
        "description": "Received from Samuel Olamide via Kuda (NIP)",
        "transaction_type": "credit",
        "raw_metadata": {"narration": "NIP/Kuda/Samuel Olamide/Payment", "metadata": {"channel": "NIP"}},
    }
    mappings = [
        {
            "mapping_type": "bank_account",
            "finsight_key": "bank-1",
            "qb_account_id": "35",
            "qb_account_name": "Checking",
        },
    ]
    coa = _coa(("35", "Checking", "Bank"))
    result = classify_transaction(txn, mappings, {}, coa, _coa_ids("35"))
    assert result["qb_sync_status"] != "excluded"
    assert result["qb_posting_type"] == "deposit"


def test_transfer_in_category_nip_credit_not_excluded():
    txn = {
        "account_id": "bank-1",
        "category": "Transfer In",
        "merchant_name": "Ibrahim Musa",
        "description": "Received from Ibrahim Musa (NIP)",
        "transaction_type": "credit",
    }
    mappings = [
        {
            "mapping_type": "bank_account",
            "finsight_key": "bank-1",
            "qb_account_id": "35",
            "qb_account_name": "Checking",
        },
    ]
    coa = _coa(("35", "Checking", "Bank"))
    result = classify_transaction(txn, mappings, {}, coa, _coa_ids("35"))
    assert result["qb_sync_status"] != "excluded"
    assert result["qb_posting_type"] == "deposit"


def test_category_hint_without_mapping():
    txn = {
        "account_id": "bank-1",
        "category": "Food & Dining",
        "merchant_name": "Chicken Republic",
        "transaction_type": "debit",
    }
    mappings = [
        {
            "mapping_type": "bank_account",
            "finsight_key": "bank-1",
            "qb_account_id": "35",
            "qb_account_name": "Checking",
        },
    ]
    coa = _coa(("35", "Checking", "Bank"))
    result = classify_transaction(txn, mappings, {}, coa, _coa_ids("35"))
    assert result["qb_sync_status"] == "needs_review"
    assert result["qb_suggestion_method"] == "category"
    assert "Food & Dining" in (result["qb_confidence_reason"] or "")


def test_nip_debit_to_landlord_is_expense_not_excluded():
    txn = {
        "account_id": "bank-1",
        "category": "Rent & Maintenance",
        "merchant_name": "Landlord Properties Ltd",
        "description": "Sent to Landlord Properties Ltd (NIP)",
        "transaction_type": "debit",
    }
    mappings = [
        {
            "mapping_type": "bank_account",
            "finsight_key": "bank-1",
            "qb_account_id": "35",
            "qb_account_name": "Checking",
        },
    ]
    coa = _coa(("35", "Checking", "Bank"))
    result = classify_transaction(txn, mappings, {}, coa, _coa_ids("35"))
    assert result["qb_sync_status"] != "excluded"
    assert result["qb_posting_type"] == "expense"
