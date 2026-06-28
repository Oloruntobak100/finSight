from pydantic import BaseModel, Field

from fastapi import APIRouter

from app.auth.dependencies import CurrentUser
from app.database import get_supabase, run_db
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


class UiPreferencesResponse(BaseModel):
    ui_preferences: dict


class UiPreferencesUpdate(BaseModel):
    ui_preferences: dict


async def _get_ui_preferences(user_id: str) -> dict:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("users")
        .select("ui_preferences")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return {}
    prefs = rows[0].get("ui_preferences")
    return prefs if isinstance(prefs, dict) else {}


@router.get("/ui-preferences", response_model=UiPreferencesResponse)
async def get_ui_preferences(user_id: CurrentUser) -> UiPreferencesResponse:
    return UiPreferencesResponse(ui_preferences=await _get_ui_preferences(user_id))


@router.patch("/ui-preferences", response_model=UiPreferencesResponse)
async def patch_ui_preferences(
    user_id: CurrentUser,
    body: UiPreferencesUpdate,
) -> UiPreferencesResponse:
    sb = get_supabase()
    current = await _get_ui_preferences(user_id)
    merged = {**current, **body.ui_preferences}
    await run_db(
        lambda: sb.table("users")
        .update({"ui_preferences": merged})
        .eq("id", user_id)
        .execute()
    )
    return UiPreferencesResponse(ui_preferences=merged)


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
