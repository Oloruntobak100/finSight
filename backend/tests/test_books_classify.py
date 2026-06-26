"""Unit tests for Books Pipeline classification (no QB API)."""

from app.services.books_service import classify_transaction


def _coa_ids(*ids: str) -> set[str]:
    return set(ids)


def _coa(*rows: tuple[str, str, str]) -> list[dict]:
    """(qb_account_id, name, account_type)"""
    return [
        {"qb_account_id": qb_id, "name": name, "account_type": acct_type}
        for qb_id, name, acct_type in rows
    ]


def test_transfer_excluded():
    txn = {
        "account_id": "bank-1",
        "category": "Transfer Out",
        "merchant_name": "NIP/John",
        "description": "",
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
    assert result["qb_sync_status"] == "excluded"
    assert result["qb_posting_type"] == "transfer"
    assert result["qb_confidence"] is None


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
    }
    result = classify_transaction(
        txn, mappings, {}, coa, _coa_ids("35", "42"), fingerprint_row=fp
    )
    assert result["qb_sync_status"] == "pending"
    assert result["qb_account_id"] == "42"
    assert result["qb_suggestion_method"] == "fingerprint"


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
