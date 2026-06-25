from pydantic import BaseModel, Field

from fastapi import APIRouter

from app.auth.dependencies import CurrentUser
from app.services.books_service import get_learning_progress, get_user_automation, update_user_automation

router = APIRouter(prefix="/users", tags=["users"])


class AutomationSettingsResponse(BaseModel):
    auto_approve_enabled: bool
    auto_approve_threshold: float
    digest_enabled: bool


class AutomationSettingsUpdate(BaseModel):
    auto_approve_enabled: bool | None = None
    auto_approve_threshold: float | None = Field(None, ge=0.70, le=0.99)
    digest_enabled: bool | None = None


@router.get("/automation", response_model=AutomationSettingsResponse)
async def get_automation(user_id: CurrentUser) -> AutomationSettingsResponse:
    data = await get_user_automation(user_id)
    return AutomationSettingsResponse(**data)


@router.patch("/automation", response_model=AutomationSettingsResponse)
async def patch_automation(
    user_id: CurrentUser,
    body: AutomationSettingsUpdate,
) -> AutomationSettingsResponse:
    data = await update_user_automation(
        user_id,
        auto_approve_enabled=body.auto_approve_enabled,
        auto_approve_threshold=body.auto_approve_threshold,
        digest_enabled=body.digest_enabled,
    )
    return AutomationSettingsResponse(**data)


@router.get("/learning-progress")
async def learning_progress(user_id: CurrentUser) -> dict:
    items = await get_learning_progress(user_id)
    automation = await get_user_automation(user_id)
    return {"items": items, "automation": automation}
