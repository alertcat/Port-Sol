"""Moltbook Identity Verification Middleware"""
import os
import httpx
from typing import Optional
from fastapi import Request, HTTPException
from pydantic import BaseModel

# Moltbook API configuration
MOLTBOOK_API_URL = "https://moltbook.com/api/v1"
MOLTBOOK_APP_KEY = os.getenv("MOLTBOOK_APP_KEY", "")  # Your moltdev_xxx key
MY_DOMAIN = os.getenv("MOLTBOOK_AUDIENCE", "portsol.world")

class MoltbookAgent(BaseModel):
    """Verified Moltbook agent profile"""
    id: str
    name: str
    description: Optional[str] = None
    karma: int = 0
    avatar_url: Optional[str] = None
    is_claimed: bool = False
    follower_count: int = 0
    following_count: int = 0
    stats: Optional[dict] = None
    owner: Optional[dict] = None

class MoltbookVerificationResult(BaseModel):
    """Result of Moltbook identity verification"""
    success: bool
    valid: bool = False
    agent: Optional[MoltbookAgent] = None
    error: Optional[str] = None

async def verify_moltbook_identity(identity_token: str) -> MoltbookVerificationResult:
    """
    Verify a Moltbook identity token.
    
    Args:
        identity_token: The X-Moltbook-Identity token from the request
        
    Returns:
        MoltbookVerificationResult with agent info if valid
    """
    if not MOLTBOOK_APP_KEY:
        # If no app key configured, skip Moltbook verification
        return MoltbookVerificationResult(
            success=False,
            error="Moltbook app key not configured"
        )
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{MOLTBOOK_API_URL}/agents/verify-identity",
                headers={
                    "X-Moltbook-App-Key": MOLTBOOK_APP_KEY,
                    "Content-Type": "application/json"
                },
                json={
                    "token": identity_token,
                    "audience": MY_DOMAIN
                }
            )
            
            data = response.json()
            
            if not data.get("valid"):
                return MoltbookVerificationResult(
                    success=True,
                    valid=False,
                    error=data.get("error", "Invalid token")
                )
            
            agent_data = data.get("agent", {})
            return MoltbookVerificationResult(
                success=True,
                valid=True,
                agent=MoltbookAgent(
                    id=agent_data.get("id", ""),
                    name=agent_data.get("name", "Unknown"),
                    description=agent_data.get("description"),
                    karma=agent_data.get("karma", 0),
                    avatar_url=agent_data.get("avatar_url"),
                    is_claimed=agent_data.get("is_claimed", False),
                    follower_count=agent_data.get("follower_count", 0),
                    following_count=agent_data.get("following_count", 0),
                    stats=agent_data.get("stats"),
                    owner=agent_data.get("owner")
                )
            )
            
    except httpx.TimeoutException:
        return MoltbookVerificationResult(
            success=False,
            error="Moltbook verification timeout"
        )
    except Exception as e:
        return MoltbookVerificationResult(
            success=False,
            error=f"Moltbook verification error: {str(e)}"
        )

async def get_agent_identity(request: Request) -> dict:
    """
    Extract agent identity from request.
    
    Supports:
    1. Moltbook Identity (X-Moltbook-Identity header)
    2. Direct wallet (X-Wallet header)
    
    Returns:
        dict with 'wallet', 'name', 'moltbook_agent' (if verified)
    """
    identity = {
        "wallet": None,
        "name": None,
        "moltbook_agent": None,
        "auth_method": None
    }
    
    # Check for Moltbook identity first
    moltbook_token = request.headers.get("X-Moltbook-Identity")
    if moltbook_token:
        result = await verify_moltbook_identity(moltbook_token)
        if result.valid and result.agent:
            identity["moltbook_agent"] = result.agent
            identity["name"] = result.agent.name
            identity["auth_method"] = "moltbook"
            # Moltbook agents still need a wallet for on-chain verification
            # They should include X-Wallet header too
    
    # Check for direct wallet
    wallet = request.headers.get("X-Wallet")
    if wallet:
        identity["wallet"] = wallet
        if not identity["auth_method"]:
            identity["auth_method"] = "wallet"
    
    return identity

def require_moltbook_auth():
    """
    Dependency that requires Moltbook authentication.
    Use as: Depends(require_moltbook_auth())
    """
    async def verify(request: Request):
        moltbook_token = request.headers.get("X-Moltbook-Identity")
        if not moltbook_token:
            raise HTTPException(
                status_code=401,
                detail="Moltbook identity required. Include X-Moltbook-Identity header."
            )
        
        result = await verify_moltbook_identity(moltbook_token)
        if not result.valid:
            raise HTTPException(
                status_code=401,
                detail=f"Invalid Moltbook identity: {result.error}"
            )
        
        return result.agent
    
    return verify
