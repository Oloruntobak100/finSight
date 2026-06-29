"""Transaction fingerprint extraction and approval learning store."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database import get_supabase, run_db
from app.services.transaction_enrichment import (
    extract_mono_merchant,
    parse_mono_narration_parts,
)

AMOUNT_BANDS = (
    (5_000, "<5k"),
    (50_000, "5k-50k"),
    (500_000, "50k-500k"),
    (float("inf"), ">500k"),
)

CONFIDENCE_WINDOW_DAYS = 90
FINGERPRINT_MATCH_MIN = 0.60


def amount_band(amount: float | int | None) -> str:
    value = abs(float(amount or 0))
    for limit, label in AMOUNT_BANDS:
        if value < limit:
            return label
    return ">500k"


def normalize_payee_pattern(narration: str | None, payee: str | None = None) -> str:
    """Clean payee/narration into a stable lookup key."""
    if payee:
        text = str(payee).strip().lower()
    elif narration:
        parsed = parse_mono_narration_parts(narration)
        if parsed and parsed.get("payee"):
            text = parsed["payee"].strip().lower()
        else:
            text = narration.strip().lower()
    else:
        return "unknown"

    text = re.sub(r"\s+\d{4,}$", "", text)
    text = re.sub(r"[^a-z0-9\s/]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:120] if text else "unknown"


def extract_fingerprint(txn: dict[str, Any]) -> dict[str, str]:
    """Build fingerprint fields from a transaction row or raw mono payload."""
    raw = txn.get("raw_metadata") or {}
    if isinstance(raw, dict) and txn.get("source_provider") == "mono":
        narration = (raw.get("narration") or txn.get("description") or "").strip()
        parsed = parse_mono_narration_parts(narration)
        metadata = raw.get("metadata") or {}
        payee = metadata.get("payee") or (parsed.get("payee") if parsed else None)
        bank = (parsed.get("bank") if parsed else None) or ""
        channel = (
            metadata.get("channel")
            or (parsed.get("channel") if parsed else None)
            or "OTHER"
        )
    else:
        narration = (txn.get("description") or txn.get("merchant_name") or "").strip()
        payee = txn.get("merchant_name")
        parsed = parse_mono_narration_parts(narration) if narration else None
        bank = parsed.get("bank") if parsed else ""
        channel = parsed.get("channel") if parsed else "OTHER"

    if not payee and txn.get("merchant_name"):
        payee = txn.get("merchant_name")

    payee_pattern = normalize_payee_pattern(narration, str(payee) if payee else None)
    bank_code = str(bank).strip().upper()[:32] if bank else None
    channel_norm = str(channel).strip().upper()[:16] if channel else "OTHER"

    return {
        "payee_pattern": payee_pattern,
        "bank_code": bank_code or None,
        "channel": channel_norm,
        "amount_band": amount_band(txn.get("amount")),
    }


def fingerprint_fields_for_row(txn: dict[str, Any]) -> dict[str, Any]:
    """Denormalized fields to store on transactions at sync time."""
    fp = extract_fingerprint(txn)
    return {"payee_pattern": fp["payee_pattern"]}


async def _lookup_exact_fingerprint(user_id: str, fp: dict[str, str]) -> dict[str, Any] | None:
    sb = get_supabase()
    channel = fp.get("channel") or "OTHER"
    res = await run_db(
        lambda: sb.table("transaction_fingerprints")
        .select("*")
        .eq("user_id", user_id)
        .eq("payee_pattern", fp["payee_pattern"])
        .eq("channel", channel)
        .eq("amount_band", fp["amount_band"])
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def fingerprint_is_trained(row: dict[str, Any]) -> bool:
    return float(row.get("confidence") or 0) >= FINGERPRINT_MATCH_MIN or int(
        row.get("recurrence_count") or 0
    ) >= 1


async def lookup_fingerprint_by_payee(
    user_id: str, payee_pattern: str
) -> dict[str, Any] | None:
    """Best trained fingerprint for a payee across channels and amount bands."""
    if not payee_pattern or payee_pattern == "unknown":
        return None
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("transaction_fingerprints")
        .select("*")
        .eq("user_id", user_id)
        .eq("payee_pattern", payee_pattern)
        .order("confidence", desc=True)
        .order("recurrence_count", desc=True)
        .limit(5)
        .execute()
    )
    for row in res.data or []:
        if fingerprint_is_trained(row):
            return row
    return None


async def lookup_fingerprint(user_id: str, fp: dict[str, str]) -> dict[str, Any] | None:
    exact = await _lookup_exact_fingerprint(user_id, fp)
    if exact and fingerprint_is_trained(exact):
        return exact
    payee = await lookup_fingerprint_by_payee(user_id, fp["payee_pattern"])
    if payee:
        return payee
    return None


def fingerprint_match_confidence(txn: dict[str, Any], fp_row: dict[str, Any]) -> float:
    """Exact dimensional matches keep full confidence; payee-only matches stay in Review."""
    fp_txn = extract_fingerprint(txn)
    exact = (
        fp_row.get("payee_pattern") == fp_txn["payee_pattern"]
        and (fp_row.get("channel") or "OTHER") == (fp_txn.get("channel") or "OTHER")
        and fp_row.get("amount_band") == fp_txn["amount_band"]
    )
    raw = float(fp_row.get("confidence") or 0)
    if exact:
        return raw
    return min(raw, 0.84)


def _confidence_from_decisions(decisions: list[dict[str, Any]]) -> float:
    if not decisions:
        return 0.0
    accepted = sum(
        1 for d in decisions if d.get("was_accepted") and not d.get("edit_made")
    )
    edited = sum(1 for d in decisions if d.get("edit_made"))
    rejected = sum(1 for d in decisions if not d.get("was_accepted"))
    total = accepted + edited + rejected
    if total == 0:
        return 0.0
    return round(accepted / total, 4)


async def _decisions_for_fingerprint(
    user_id: str,
    fingerprint_id: str,
    days: int = CONFIDENCE_WINDOW_DAYS,
) -> list[dict[str, Any]]:
    sb = get_supabase()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    res = await run_db(
        lambda: sb.table("posting_decisions")
        .select("was_accepted, edit_made")
        .eq("user_id", user_id)
        .eq("fingerprint_id", fingerprint_id)
        .gte("created_at", since)
        .execute()
    )
    return res.data or []


async def recalculate_fingerprint_confidence(user_id: str, fingerprint_id: str) -> float:
    decisions = await _decisions_for_fingerprint(user_id, fingerprint_id)
    confidence = _confidence_from_decisions(decisions)
    sb = get_supabase()
    await run_db(
        lambda: sb.table("transaction_fingerprints")
        .update(
            {
                "confidence": confidence,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", fingerprint_id)
        .eq("user_id", user_id)
        .execute()
    )
    return confidence


async def upsert_fingerprint_from_decision(
    user_id: str,
    txn: dict[str, Any],
    final_account_id: str,
    final_account_name: str | None,
    *,
    posting_kind: str | None = None,
) -> dict[str, Any]:
    fp = extract_fingerprint(txn)
    sb = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    channel = fp.get("channel") or "OTHER"

    existing = await _lookup_exact_fingerprint(user_id, fp)
    if not existing:
        existing = await lookup_fingerprint_by_payee(user_id, fp["payee_pattern"])
    if existing:
        fingerprint_id = existing["id"]
        recurrence = int(existing.get("recurrence_count") or 0) + 1
        await run_db(
            lambda: sb.table("transaction_fingerprints")
            .update(
                {
                    "recurrence_count": recurrence,
                    "last_seen_at": now,
                    "qb_account_id": final_account_id,
                    "qb_account_name": final_account_name,
                    "bank_code": fp.get("bank_code"),
                    "updated_at": now,
                    **({"posting_kind": posting_kind} if posting_kind else {}),
                }
            )
            .eq("id", fingerprint_id)
            .execute()
        )
    else:
        row = {
            "user_id": user_id,
            "payee_pattern": fp["payee_pattern"],
            "bank_code": fp.get("bank_code"),
            "channel": channel,
            "amount_band": fp["amount_band"],
            "recurrence_count": 1,
            "last_seen_at": now,
            "qb_account_id": final_account_id,
            "qb_account_name": final_account_name,
            "confidence": 0.0,
            "posting_kind": posting_kind,
        }
        res = await run_db(
            lambda: sb.table("transaction_fingerprints").insert(row).execute()
        )
        fingerprint_id = (res.data or [row])[0]["id"]

    confidence = await recalculate_fingerprint_confidence(user_id, fingerprint_id)
    res = await run_db(
        lambda: sb.table("transaction_fingerprints")
        .select("*")
        .eq("id", fingerprint_id)
        .single()
        .execute()
    )
    row = res.data or {"id": fingerprint_id, "confidence": confidence, **fp}
    return row


async def touch_fingerprint_seen(user_id: str, txn: dict[str, Any]) -> str | None:
    """Increment seen count when classifying; returns fingerprint id if exists."""
    fp = extract_fingerprint(txn)
    existing = await lookup_fingerprint(user_id, fp)
    if not existing:
        return None
    now = datetime.now(timezone.utc).isoformat()
    sb = get_supabase()
    await run_db(
        lambda: sb.table("transaction_fingerprints")
        .update({"last_seen_at": now, "updated_at": now})
        .eq("id", existing["id"])
        .execute()
    )
    return existing["id"]


def fingerprint_confidence_reason(fp: dict[str, Any], decisions: list[dict[str, Any]] | None = None) -> str:
    count = int(fp.get("recurrence_count") or 0)
    conf = float(fp.get("confidence") or 0)
    name = fp.get("qb_account_name") or fp.get("qb_account_id") or "account"
    if decisions:
        accepted = sum(1 for d in decisions if d.get("was_accepted") and not d.get("edit_made"))
        total = len(decisions)
        return f"{accepted}/{total} approvals to this payee as {name} (90d)"
    return f"Seen {count} times as {name} ({conf:.0%} confidence)"


async def recalculate_all_fingerprints_for_user(user_id: str) -> int:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("transaction_fingerprints")
        .select("id")
        .eq("user_id", user_id)
        .execute()
    )
    count = 0
    for row in res.data or []:
        await recalculate_fingerprint_confidence(user_id, row["id"])
        count += 1
    return count


async def recalculate_all_fingerprints() -> int:
    sb = get_supabase()
    res = await run_db(lambda: sb.table("transaction_fingerprints").select("user_id, id").execute())
    seen_users: set[str] = set()
    total = 0
    for row in res.data or []:
        uid = row["user_id"]
        if uid not in seen_users:
            seen_users.add(uid)
        await recalculate_fingerprint_confidence(uid, row["id"])
        total += 1
    return total
