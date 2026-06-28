from typing import Any

from app.services.transfer_utils import INTERNAL_TRANSFER_MARKERS

MONO_CATEGORY_LABELS: dict[str, str] = {
    "betting_payout": "Betting Payout",
    "betting_deposit": "Betting Deposit",
    "bills": "Bills",
    "cash_deposit": "Cash Deposit",
    "cash_withdrawal": "Cash Withdrawal",
    "cheque": "Cheque",
    "cheque_deposits": "Cheque Deposits",
    "education": "Education",
    "entertainment": "Entertainment",
    "bank_charge": "Bank Charges",
    "food": "Food",
    "gifts_donations": "Gifts & Donations",
    "groceries": "Groceries",
    "healthcare": "Health",
    "interest": "Interest",
    "investment_payout": "Investment Payout",
    "investment_deposit": "Investment Deposit",
    "leisure_activities": "Leisure & Travel",
    "loan": "Loans",
    "loan_repayment": "Loan Repayment",
    "other_outgoing_payments": "Other Payments",
    "online_payments": "Online Payments",
    "other_incoming_payments": "Other Income",
    "other_incoming_payments_from_employer": "Employer Income",
    "personal_care": "Personal Care",
    "transfer": "Transfer",
    "phone_internet": "Phone & Internet",
    "rent_maintanence": "Rent & Maintenance",
    "reversal": "Reversal",
    "salary": "Salary",
    "savings": "Savings",
    "transportation": "Transport",
    "utility": "Utility",
}

MERCHANT_RULES: dict[str, str] = {
    "netflix": "Entertainment",
    "spotify": "Entertainment",
    "uber": "Transport",
    "bolt": "Transport",
    "amazon": "Shopping",
    "starbucks": "Food & Drink",
    "shell": "Transport",
    "walmart": "Groceries",
    "airtime": "Phone & Internet",
    "mtn": "Phone & Internet",
    "glo": "Phone & Internet",
    "airtel": "Phone & Internet",
    "dstv": "Entertainment",
    "gotv": "Entertainment",
    "salary": "Salary",
    "payroll": "Salary",
}

NARRATION_RULES: list[tuple[tuple[str, ...], str]] = [
    (("salary", "payroll", "wages"), "Salary"),
    (("airtime", "data bundle", "mtn", "glo", "airtel", "9mobile"), "Phone & Internet"),
    (
        (
            "to self",
            "own account",
            "between own accounts",
            "between my accounts",
            "inter account",
            "inter-account",
            "self transfer",
            "transfer to self",
            "transfer from self",
        ),
        "Transfer",
    ),
    (("pos ", "pos/", "pos purchase"), "Shopping"),
    (("uber", "bolt", "indrive", "taxify"), "Transport"),
    (("netflix", "spotify", "youtube", "cinema"), "Entertainment"),
    (("dstv", "gotv", "startimes"), "Entertainment"),
    (("phcn", "ikedc", "ekedc", "electric", "utility"), "Utility"),
    (("rent", "landlord"), "Rent & Maintenance"),
    (("school", "tuition", "university"), "Education"),
    (("hospital", "pharmacy", "clinic"), "Health"),
    (("bet9ja", "sportybet", "betting"), "Betting"),
    (("charge", "fee", "commission", "vat", "stamp duty", "stamp ", "sms charge", "cot "), "Bank Charges"),
    (("atm", "cash withdrawal"), "Cash Withdrawal"),
]


def _apply_user_rules(text: str, user_rules: dict[str, str]) -> str | None:
    lower = text.lower()
    for pattern, category in user_rules.items():
        if pattern and pattern in lower:
            return category
    return None


def _apply_narration_rules(text: str) -> str | None:
    lower = text.lower()
    for patterns, category in NARRATION_RULES:
        if any(p in lower for p in patterns):
            return category
    return None


def _looks_like_payment_rail(text: str) -> bool:
    lower = text.lower()
    return any(
        marker in lower
        for marker in (
            "nip/",
            "nip ",
            "(nip)",
            " via kuda",
            " via opay",
            " via palmpay",
            " via moniepoint",
        )
    )


def _default_category_for_payment_rail(txn_type: str | None) -> str:
    if txn_type == "credit":
        return "Other Income"
    return "Online Payments"


def _remap_generic_transfer_category(
    category: str,
    rule_text: str,
    txn_type: str | None,
) -> str:
    """Mono/bank 'transfer' labels on NIP payments are usually P&L, not inter-account."""
    normalized = category.strip().lower().replace("_", " ")
    if normalized not in ("transfer", "transfer in", "transfer out"):
        return category
    lower = rule_text.lower()
    if any(marker in lower for marker in INTERNAL_TRANSFER_MARKERS):
        return category
    return _default_category_for_payment_rail(txn_type)


def format_mono_category(slug: str | None) -> str | None:
    if not slug:
        return None
    normalized = slug.strip().lower()
    if normalized in ("unknown", "null", "uncategorized"):
        return None
    if normalized in MONO_CATEGORY_LABELS:
        return MONO_CATEGORY_LABELS[normalized]
    return slug.replace("_", " ").title()


def categorize_merchant(merchant_name: str | None, user_rules: dict[str, str] | None = None) -> str:
    if not merchant_name:
        return "Uncategorized"

    if user_rules:
        matched = _apply_user_rules(merchant_name, user_rules)
        if matched:
            return matched

    lower = merchant_name.lower()
    for pattern, category in MERCHANT_RULES.items():
        if pattern in lower:
            return category

    matched = _apply_narration_rules(merchant_name)
    if matched:
        return matched

    return "Uncategorized"


async def load_user_category_rules(user_id: str, sb: Any | None = None) -> dict[str, str]:
    if sb is None:
        from app.database import get_supabase

        sb = get_supabase()
    from app.database import run_db

    rules_res = await run_db(
        lambda: sb.table("user_category_rules")
        .select("merchant_pattern, assigned_category")
        .eq("user_id", user_id)
        .execute()
    )
    return {
        row["merchant_pattern"]: row["assigned_category"]
        for row in (rules_res.data or [])
        if row.get("merchant_pattern")
    }


def _apply_transfer_direction(category: str, txn_type: str | None) -> str:
    if not txn_type or category.lower() != "transfer":
        return category
    return "Transfer In" if txn_type == "credit" else "Transfer Out"


def _finalize_category(category: str, rule_text: str, txn_type: str | None) -> str:
    remapped = _remap_generic_transfer_category(category, rule_text, txn_type)
    return _apply_transfer_direction(remapped, txn_type)


def resolve_mono_transaction_category(
    txn: dict,
    user_rules: dict[str, str] | None = None,
    txn_type: str | None = None,
) -> str:
    metadata = txn.get("metadata") or {}
    narration = txn.get("narration") or txn.get("description") or ""
    payee = metadata.get("payee")
    payee_text = str(payee).strip() if payee not in (None, "", "N/A") else ""
    reason = metadata.get("reason")
    reason_text = str(reason).strip() if reason not in (None, "", "N/A") else ""

    rule_text = " ".join(part for part in (narration, payee_text, reason_text) if part)
    if user_rules and rule_text:
        matched = _apply_user_rules(rule_text, user_rules)
        if matched:
            return _finalize_category(matched, rule_text, txn_type)

    mono_slug = metadata.get("category") or txn.get("category")
    formatted = format_mono_category(mono_slug if isinstance(mono_slug, str) else None)
    if formatted:
        return _finalize_category(formatted, rule_text, txn_type)

    if payee_text:
        matched = categorize_merchant(payee_text, user_rules)
        if matched != "Uncategorized":
            return _finalize_category(matched, rule_text, txn_type)

    if reason_text:
        matched = _apply_narration_rules(reason_text)
        if matched:
            return _finalize_category(matched, rule_text, txn_type)

    matched = categorize_merchant(narration or None, user_rules)
    if matched == "Uncategorized" and narration and _looks_like_payment_rail(narration):
        matched = _default_category_for_payment_rail(txn_type)
    return _finalize_category(matched, rule_text, txn_type)
