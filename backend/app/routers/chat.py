from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.auth.dependencies import CurrentUser
from app.database import get_supabase, run_db
from app.models.chat import (
    ChatMessageRequest,
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionResponse,
)
from app.services.chat_service import stream_chat_response

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/sessions", response_model=ChatSessionResponse)
async def create_session(user_id: CurrentUser, body: ChatSessionCreate) -> ChatSessionResponse:
    sb = get_supabase()
    row = {"user_id": user_id, "title": body.title or "New Chat"}
    res = await run_db(lambda: sb.table("chat_sessions").insert(row).execute())
    return ChatSessionResponse(**res.data[0])


@router.get("/sessions", response_model=list[ChatSessionResponse])
async def list_sessions(user_id: CurrentUser) -> list[ChatSessionResponse]:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("chat_sessions")
        .select("*")
        .eq("user_id", user_id)
        .order("last_message_at", desc=True)
        .execute()
    )
    return [ChatSessionResponse(**s) for s in (res.data or [])]


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageResponse])
async def get_messages(session_id: str, user_id: CurrentUser) -> list[ChatMessageResponse]:
    sb = get_supabase()
    session = await run_db(
        lambda: sb.table("chat_sessions")
        .select("id")
        .eq("id", session_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not session.data:
        raise HTTPException(status_code=404, detail="Session not found")

    res = await run_db(
        lambda: sb.table("chat_messages")
        .select("*")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )
    return [ChatMessageResponse(**m) for m in (res.data or [])]


@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, user_id: CurrentUser, body: ChatMessageRequest):
    sb = get_supabase()
    session = await run_db(
        lambda: sb.table("chat_sessions")
        .select("id")
        .eq("id", session_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not session.data:
        raise HTTPException(status_code=404, detail="Session not found")

    async def event_stream():
        async for chunk in stream_chat_response(user_id, session_id, body.content):
            yield chunk

    return StreamingResponse(event_stream(), media_type="text/plain")
