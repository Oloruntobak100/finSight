from typing import Any

from app.database import get_supabase, run_db


async def create_notification(user_id: str, type_: str, title: str, body: str) -> dict[str, Any]:
    sb = get_supabase()
    row = {"user_id": user_id, "type": type_, "title": title, "body": body}
    result = await run_db(lambda: sb.table("notifications").insert(row).execute())
    return result.data[0]
