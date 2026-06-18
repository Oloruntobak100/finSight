"""Unit tests for Books Pipeline classification (no QB API)."""

from app.services.books_service import classify_transaction


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
    result = classify_transaction(txn, mappings, {}, [])
    assert result["qb_sync_status"] == "excluded"
    assert result["qb_posting_type"] == "skip"


def test_credit_skipped():
    txn = {
        "account_id": "bank-1",
        "category": "Salary",
        "merchant_name": "Employer",
        "transaction_type": "credit",
    }
    result = classify_transaction(txn, [], {}, [])
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
    result = classify_transaction(txn, mappings, {}, [])
    assert result["qb_sync_status"] == "pending"
    assert result["qb_account_id"] == "42"
    assert result["qb_payment_account_id"] == "35"


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
    result = classify_transaction(txn, mappings, {}, [])
    assert result["qb_sync_status"] == "needs_review"
