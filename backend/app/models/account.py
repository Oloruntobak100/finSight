from typing import Literal, Optional

from pydantic import BaseModel, Field


class ConnectedAccountResponse(BaseModel):
    id: str
    user_id: str
    provider: str
    account_name: Optional[str] = None
    account_type: Optional[str] = None
    external_account_id: Optional[str] = None
    last_synced_at: Optional[str] = None
    status: str = "active"
    created_at: Optional[str] = None


class PlaidLinkTokenResponse(BaseModel):
    link_token: str


class PlaidExchangeRequest(BaseModel):
    public_token: str
    account_name: Optional[str] = None


class MonoConnectRequest(BaseModel):
    code: str
    account_name: Optional[str] = "Mono Account"


class MonoConfigResponse(BaseModel):
    public_key: str
    mono_env: str
    configured: bool


class OAuthAuthorizeResponse(BaseModel):
    authorization_url: str


class QuickBooksConfigResponse(BaseModel):
    client_id: str
    redirect_uri: str
    scope: str
    oauth_url: str
    environment: str
    configured: bool


class QuickBooksExchangeRequest(BaseModel):
    code: str
    realm_id: str = Field(..., alias="realmId")

    model_config = {"populate_by_name": True}


class SandboxSimulateRequest(BaseModel):
    account_id: str
    description: str = "FinSight Sandbox Coffee"
    amount: float = Field(4.75, gt=0)
    transaction_type: Literal["expense", "income"] = "expense"
