from app.database import get_supabase, run_db
from app.services.analytics_service import calculate_metrics
from app.services.forecasting_service import generate_forecast
from app.services import mono_service, plaid_service


async def nightly_sync_all() -> None:
    sb = get_supabase()
    accounts_res = await run_db(
        lambda: sb.table("connected_accounts").select("id, user_id, provider").eq("status", "active").execute()
    )
    for account in accounts_res.data or []:
        try:
            if account["provider"] == "plaid":
                await plaid_service.sync_plaid_transactions(account["user_id"], account["id"])
            elif account["provider"] == "mono":
                await mono_service.sync_mono_transactions(account["user_id"], account["id"])
        except Exception:
            continue


async def nightly_metrics_all() -> None:
    sb = get_supabase()
    users_res = await run_db(lambda: sb.table("users").select("id").execute())
    for user in users_res.data or []:
        try:
            await calculate_metrics(user["id"])
        except Exception:
            continue


async def nightly_forecast_all() -> None:
    sb = get_supabase()
    users_res = await run_db(lambda: sb.table("users").select("id").execute())
    for user in users_res.data or []:
        try:
            await generate_forecast(user["id"])
        except Exception:
            continue
