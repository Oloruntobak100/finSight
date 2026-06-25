"""Unit tests for Books Pipeline classification (no QB API)."""

from app.services.books_service import classify_transaction


def _coa_ids(*ids: str) -> set[str]:
    return set(ids)


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
    result = classify_transaction(txn, mappings, {}, [], _coa_ids("35"))
    assert result["qb_sync_status"] == "excluded"
    assert result["qb_posting_type"] == "skip"
    assert result["qb_confidence"] is None
    assert "transfer" in (result.get("qb_confidence_reason") or "").lower()


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
    result = classify_transaction(txn, mappings, {}, [], _coa_ids("35", "42"))
    assert result["qb_sync_status"] != "excluded"


def test_credit_skipped():
    txn = {
        "account_id": "bank-1",
        "category": "Salary",
        "merchant_name": "Employer",
        "transaction_type": "credit",
    }
    result = classify_transaction(txn, [], {}, [], set())
    assert result["qb_sync_status"] == "skipped"


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
    result = classify_transaction(txn, mappings, {}, [], _coa_ids("35", "42"))
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
    fp = {
        "id": "fp-1",
        "qb_account_id": "42",
        "qb_account_name": "Rent",
        "confidence": 0.95,
        "recurrence_count": 5,
    }
    result = classify_transaction(
        txn, mappings, {}, [], _coa_ids("35", "42"), fingerprint_row=fp
    )
    assert result["qb_sync_status"] == "pending"
    assert result["qb_account_id"] == "42"
    assert result["qb_suggestion_method"] == "fingerprint"


def test_fingerprint_stale_coa_falls_through():
    """Fingerprint with deleted QB account should not be used."""
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
        [],
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
    result = classify_transaction(txn, mappings, {}, [], _coa_ids("42"))
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
        [],
        _coa_ids("35", "42"),
        fingerprint_row=fp,
        automation=automation,
    )
    assert result["qb_sync_status"] == "auto_approved"
    assert result["qb_suggestion_method"] == "fingerprint"
