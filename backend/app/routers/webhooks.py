import logging

from fastapi import APIRouter, Request

from app.services import plaid_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/plaid")
async def plaid_webhook(request: Request) -> dict:
    payload = await request.json()
    webhook_code = payload.get("webhook_code", "unknown")
    item_id = payload.get("item_id", "unknown")
    logger.info("Plaid webhook received: code=%s item_id=%s", webhook_code, item_id)

    result = await plaid_service.handle_plaid_webhook(payload)
    return {"received": True, **result}


@router.post("/stripe")
async def stripe_webhook(request: Request) -> dict:
    _ = await request.body()
    return {"received": True}
