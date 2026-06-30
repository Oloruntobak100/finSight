from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    secret_key: str = "change-me"
    cors_origins: str = "http://localhost:3000"
    frontend_url: str = "http://localhost:3000"

    # Supabase
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""

    # Encryption
    encryption_key: str = ""

    # Plaid
    plaid_client_id: str = ""
    plaid_secret: str = ""
    plaid_env: str = "sandbox"
    plaid_products: str = "transactions"
    plaid_optional_products: str = "liabilities,investments"
    plaid_country_codes: str = "US,GB"
    plaid_redirect_uri: str = ""
    plaid_webhook_url: str = ""
    fastapi_url: str = "http://localhost:8001"

    # Mono
    mono_secret_key: str = ""
    mono_public_key: str = ""

    # Synthetic data feed (dev / Mono sandbox assist)
    enable_synthetic_feed: bool = False
    # Secures POST /synthetic-feed/cron/live-drip (falls back to secret_key if unset)
    cron_secret: str = ""

    # QuickBooks
    quickbooks_client_id: str = ""
    quickbooks_client_secret: str = ""
    quickbooks_redirect_uri: str = ""
    quickbooks_env: str = "sandbox"

    # Xero
    xero_client_id: str = ""
    xero_client_secret: str = ""
    xero_redirect_uri: str = "http://localhost:8000/oauth/xero/callback"

    # LLM — openai | anthropic | auto (prefers OpenAI when key is set)
    llm_provider: str = "auto"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # Stripe / Paystack / Resend / Redis
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    paystack_secret_key: str = ""
    resend_api_key: str = ""
    upstash_redis_url: str = ""
    upstash_redis_token: str = ""

    @property
    def cors_origin_list(self) -> List[str]:
        origins = [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]
        frontend = self.frontend_url.strip().rstrip("/") if self.frontend_url else ""
        if frontend and frontend not in origins:
            origins.append(frontend)
        return origins

    @property
    def quickbooks_base_url(self) -> str:
        return "https://sandbox-quickbooks.api.intuit.com" if self.quickbooks_env == "sandbox" else "https://quickbooks.api.intuit.com"

    @property
    def quickbooks_oauth_base(self) -> str:
        return "https://appcenter.intuit.com/connect/oauth2"

    @property
    def plaid_environment(self) -> str:
        return self.plaid_env

    @property
    def plaid_product_list(self) -> List[str]:
        return [p.strip() for p in self.plaid_products.split(",") if p.strip()]

    @property
    def plaid_optional_product_list(self) -> List[str]:
        return [p.strip() for p in self.plaid_optional_products.split(",") if p.strip()]

    @property
    def plaid_country_code_list(self) -> List[str]:
        return [c.strip() for c in self.plaid_country_codes.split(",") if c.strip()]

    @property
    def mono_env(self) -> str:
        key = (self.mono_secret_key or self.mono_public_key or "").lower()
        return "sandbox" if key.startswith("test_") else "live"

    @property
    def synthetic_feed_allowed(self) -> bool:
        return self.enable_synthetic_feed or self.mono_env == "sandbox"

    @property
    def skip_mono_sandbox_sync(self) -> bool:
        """Skip pulling Mono sandbox transactions — use synthetic feed instead."""
        return self.mono_env == "sandbox" and self.synthetic_feed_allowed


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
