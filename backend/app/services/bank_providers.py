"""Bank data provider registry — route sync/disconnect through adapters."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.config import settings


@runtime_checkable
class BankProvider(Protocol):
    provider_id: str

    async def sync_transactions(self, user_id: str, account_id: str, **kwargs: Any) -> int: ...

    async def disconnect(self, user_id: str, account_id: str) -> None: ...


class MonoBankProvider:
    provider_id = "mono"

    async def sync_transactions(self, user_id: str, account_id: str, **kwargs: Any) -> int:
        from app.services.mono_service import sync_mono_transactions

        return await sync_mono_transactions(user_id, account_id, **kwargs)

    async def disconnect(self, user_id: str, account_id: str) -> None:
        from app.services.mono_service import disconnect_mono_account

        await disconnect_mono_account(user_id, account_id)


class PlaidBankProvider:
    provider_id = "plaid"

    async def sync_transactions(self, user_id: str, account_id: str, **kwargs: Any) -> int:
        from app.services.plaid_service import sync_plaid_transactions

        _ = kwargs
        return await sync_plaid_transactions(user_id, account_id)

    async def disconnect(self, user_id: str, account_id: str) -> None:
        from app.services.plaid_service import disconnect_plaid_account

        await disconnect_plaid_account(user_id, account_id)

    async def mark_recurring(self, user_id: str, account_id: str) -> int:
        from app.services.plaid_service import mark_recurring_transactions

        return await mark_recurring_transactions(user_id, account_id)


PROVIDERS: dict[str, BankProvider] = {
    "mono": MonoBankProvider(),
    "plaid": PlaidBankProvider(),
}


def get_bank_provider(provider: str) -> BankProvider:
    adapter = PROVIDERS.get(provider)
    if not adapter:
        raise ValueError(f"Unsupported bank provider: {provider}")
    return adapter


def should_skip_sync(provider: str) -> bool:
    return provider == "mono" and settings.skip_mono_sandbox_sync


async def sync_bank_account(
    user_id: str,
    account_id: str,
    provider: str,
    **kwargs: Any,
) -> int:
    if should_skip_sync(provider):
        return 0
    return await get_bank_provider(provider).sync_transactions(user_id, account_id, **kwargs)


async def disconnect_bank_account(user_id: str, account_id: str, provider: str) -> None:
    await get_bank_provider(provider).disconnect(user_id, account_id)


async def mark_recurring_if_supported(user_id: str, account_id: str, provider: str) -> int:
    if provider != "plaid":
        return 0
    adapter = get_bank_provider("plaid")
    if isinstance(adapter, PlaidBankProvider):
        return await adapter.mark_recurring(user_id, account_id)
    return 0
