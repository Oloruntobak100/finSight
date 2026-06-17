from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ChatSessionCreate(BaseModel):
    title: Optional[str] = None


class ChatSessionResponse(BaseModel):
    id: str
    user_id: str
    title: Optional[str] = None
    created_at: Optional[str] = None
    last_message_at: Optional[str] = None


class ChatMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=8000)


class ChatMessageResponse(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "assistant"]
    content: str
    context_snapshot: Optional[dict[str, Any]] = None
    created_at: Optional[str] = None
