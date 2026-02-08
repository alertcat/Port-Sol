"""Action routes: /action, /register with Solana gate check + Moltbook support"""
import re
from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any

router = APIRouter()

# Solana base58 pubkey pattern (32-44 chars of base58 alphabet)
SOLANA_PUBKEY_RE = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')


def is_valid_solana_pubkey(address: str) -> bool:
    """Validate Solana public key format (base58, 32-44 chars)."""
    return bool(SOLANA_PUBKEY_RE.match(address))


class RegisterRequest(BaseModel):
    wallet: str
    name: str
    tx_hash: Optional[str] = None  # SOL transfer tx signature for entry verification


class ActionRequest(BaseModel):
    actor: str
    action: str
    params: Dict[str, Any] = {}
    nonce: Optional[str] = None


@router.post("/register")
async def register_agent(req: RegisterRequest, request: Request):
    """
    Register agent (requires SOL payment to treasury first)

    Supports:
    - Moltbook Identity (X-Moltbook-Identity header)
    - Direct wallet (X-Wallet header)
    """
    from engine.state import get_world_engine
    from engine.blockchain import get_gate_client
    from middleware.moltbook import get_agent_identity

    world = get_world_engine()
    gate = get_gate_client()

    # Get agent identity (Moltbook or wallet)
    identity = await get_agent_identity(request)

    # Use wallet from request body
    wallet = req.wallet

    # Validate Solana pubkey format
    if not is_valid_solana_pubkey(wallet):
        return {
            "success": False,
            "message": f"Invalid Solana wallet address: {wallet}. Must be base58 encoded pubkey.",
        }

    # If tx_hash provided, verify the on-chain transfer and register entry
    if req.tx_hash and not gate.is_active_entry(wallet):
        ok, msg = gate.verify_transfer(req.tx_hash, wallet)
        if ok:
            gate.register_entry(wallet, req.tx_hash)
        else:
            return {
                "success": False,
                "message": f"Transfer verification failed: {msg}",
                "treasury": str(gate.treasury_pubkey) if gate.treasury_pubkey else None,
                "entry_fee": gate.get_entry_fee_formatted(),
            }

    # Check entry status
    if not gate.is_active_entry(wallet):
        return {
            "success": False,
            "message": (
                f"Wallet {wallet} has not entered the world. "
                f"Send {gate.get_entry_fee_formatted()} to treasury first."
            ),
            "treasury": str(gate.treasury_pubkey) if gate.treasury_pubkey else None,
            "entry_fee": gate.get_entry_fee_formatted(),
            "entry_fee_lamports": gate.get_entry_fee(),
            "network": gate.network,
            "auth_hint": "Read /moltbook/auth-info for Moltbook auth"
        }

    # Use Moltbook name if available, otherwise use provided name
    agent_name = req.name
    if identity.get("moltbook_agent"):
        agent_name = identity["moltbook_agent"].name

    agent = world.register_agent(wallet, agent_name)

    response = {
        "success": True,
        "message": f"Agent {agent_name} registered in Port Sol",
        "agent": agent.to_dict()
    }

    # Include Moltbook info if authenticated
    if identity.get("moltbook_agent"):
        response["moltbook"] = {
            "verified": True,
            "name": identity["moltbook_agent"].name,
            "karma": identity["moltbook_agent"].karma,
            "id": identity["moltbook_agent"].id
        }

    return response


@router.post("/action")
async def submit_action(
    req: ActionRequest,
    request: Request,
    x_wallet: Optional[str] = Header(None),
    x_moltbook_identity: Optional[str] = Header(None)
):
    """
    Submit action (requires active entry)

    Supports:
    - Moltbook Identity (X-Moltbook-Identity header)
    - Direct wallet (X-Wallet header)
    """
    from engine.state import get_world_engine
    from engine.rules import RulesEngine
    from engine.blockchain import get_gate_client
    from middleware.moltbook import get_agent_identity

    world = get_world_engine()
    gate = get_gate_client()

    # Get agent identity
    identity = await get_agent_identity(request)

    wallet = x_wallet or req.actor

    # Check entry status
    if not gate.is_active_entry(wallet):
        raise HTTPException(
            403,
            f"Wallet {wallet} entry has expired or not entered. "
            f"Send {gate.get_entry_fee_formatted()} to treasury."
        )

    agent = world.get_agent(wallet)
    if not agent:
        raise HTTPException(
            403,
            f"Agent {wallet} not registered. Call /register first."
        )

    # Execute action
    rules = RulesEngine(world)
    result = rules.execute_action(agent, req.action, req.params)

    # Add Moltbook info if authenticated
    if identity.get("moltbook_agent"):
        result["moltbook_verified"] = True
        result["moltbook_karma"] = identity["moltbook_agent"].karma

    return result


@router.post("/debug/advance_tick")
async def advance_tick():
    """Debug: manually advance one tick"""
    from engine.state import get_world_engine
    world = get_world_engine()
    return world.process_tick()


@router.post("/debug/reset_agent/{wallet}")
async def reset_agent(wallet: str, credits: int = 1000):
    """Debug: reset agent to initial state"""
    from engine.state import get_world_engine
    from engine.world import Region

    world = get_world_engine()
    agent = world.get_agent(wallet)

    if not agent:
        return {"success": False, "error": "Agent not found"}

    agent.credits = credits
    agent.energy = 100
    agent.max_energy = 100
    agent.inventory = {}
    agent.region = Region.DOCK
    agent.reputation = 100

    if world._db:
        world._db.save_agent(agent.to_dict())

    return {
        "success": True,
        "message": f"Agent {agent.name} reset to initial state",
        "agent": agent.to_dict()
    }


@router.post("/debug/reset_world")
async def reset_world():
    """Debug: FULL world reset - tick, prices, events, ledger"""
    from engine.state import get_world_engine

    world = get_world_engine()
    world.state.tick = 0
    world.state.market_prices = {"iron": 15, "wood": 12, "fish": 8}
    world.state.active_events = []
    world.state.state_hash = ""
    world.ledger = []
    world._compute_state_hash()
    world._save_to_database()

    return {
        "success": True,
        "message": "World fully reset: tick=0, prices=default, events cleared",
        "tick": world.state.tick,
        "market_prices": world.state.market_prices
    }


@router.post("/debug/reset_all_credits")
async def reset_all_credits(credits: int = 1000):
    """Debug: reset ALL agents' credits, energy, inventory, reputation"""
    from engine.state import get_world_engine
    from engine.world import Region

    world = get_world_engine()

    results = []
    for wallet, agent in world.agents.items():
        old_credits = agent.credits
        agent.credits = credits
        agent.energy = 100
        agent.max_energy = 100
        agent.reputation = 100
        agent.inventory = {}
        agent.region = Region.DOCK
        results.append({
            "name": agent.name,
            "wallet": wallet[:12] + "...",
            "old_credits": old_credits,
            "new_credits": credits
        })

    world._save_to_database()

    return {
        "success": True,
        "message": f"Reset {len(results)} agents to {credits} credits",
        "agents": results
    }


@router.delete("/debug/delete_agent/{wallet}")
async def delete_agent(wallet: str):
    """Debug: delete an agent from the world"""
    from engine.state import get_world_engine

    world = get_world_engine()

    if wallet not in world.agents:
        return {"success": False, "error": f"Agent {wallet} not found"}

    agent_name = world.agents[wallet].name
    del world.agents[wallet]

    return {
        "success": True,
        "message": f"Agent {agent_name} ({wallet}) deleted"
    }


@router.post("/debug/full_reset")
async def full_reset():
    """Debug: NUCLEAR RESET - clear everything and start fresh"""
    from engine.state import get_world_engine
    from engine.world import Region, Agent
    import os

    world = get_world_engine()

    # Reset world state
    world.state.tick = 0
    world.state.market_prices = {"iron": 15, "wood": 12, "fish": 8}
    world.state.active_events = []
    world.state.state_hash = ""
    world.ledger = []

    # Keep bot wallets from env if available
    bot_wallets = {}
    for role in ["MINER", "TRADER", "GOVERNOR"]:
        w = os.getenv(f"{role}_WALLET")
        if w:
            bot_wallets[w] = f"{role.capitalize()}Bot"

    world.agents.clear()

    for wallet, name in bot_wallets.items():
        agent = Agent(
            wallet=wallet, name=name, region=Region.DOCK,
            energy=100, max_energy=100, credits=1000,
            reputation=100, inventory={}, entered_at=0,
        )
        world.agents[wallet] = agent

    # Clean database
    if world._db and not world._db._use_memory:
        try:
            with world._db.cursor() as cur:
                if cur:
                    cur.execute("DELETE FROM agents")
                    cur.execute("DELETE FROM world_state")
                    cur.execute("DELETE FROM action_ledger")
                    cur.execute("DELETE FROM events")
        except Exception as e:
            print(f"DB cleanup error: {e}")

    world._compute_state_hash()
    world._save_to_database()

    return {
        "success": True,
        "message": f"FULL RESET: {len(bot_wallets)} agents, tick=0, DB cleaned",
        "tick": 0,
        "agents": [a.to_dict() for a in world.agents.values()],
        "market_prices": world.state.market_prices
    }


@router.get("/gate/status/{wallet}")
async def gate_status(wallet: str):
    """Check wallet's entry status and SOL balance"""
    from engine.blockchain import get_gate_client, LAMPORTS_PER_SOL

    gate = get_gate_client()

    is_active = gate.is_active_entry(wallet)
    balance = gate.get_balance(wallet)

    return {
        "wallet": wallet,
        "is_active_entry": is_active,
        "sol_balance": f"{balance / LAMPORTS_PER_SOL:.6f} SOL",
        "sol_lamports": balance,
        "entry_fee": gate.get_entry_fee_formatted(),
        "entry_fee_lamports": gate.get_entry_fee(),
        "can_enter": balance >= gate.get_entry_fee() and not is_active,
        "treasury": str(gate.treasury_pubkey) if gate.treasury_pubkey else None,
        "network": gate.network,
    }


@router.get("/moltbook/auth-info")
async def moltbook_auth_info():
    """Get Moltbook authentication instructions"""
    import os
    return {
        "auth_url": f"https://moltbook.com/auth.md?app=PortSol&endpoint={os.getenv('API_URL', 'http://localhost:8000')}/action",
        "header": "X-Moltbook-Identity",
        "enabled": bool(os.getenv("MOLTBOOK_APP_KEY")),
        "audience": os.getenv("MOLTBOOK_AUDIENCE", "portsol.world"),
        "instructions": "Include your Moltbook identity token in the X-Moltbook-Identity header"
    }


@router.get("/agents")
async def list_agents():
    """Get list of all registered agents and their states (leaderboard)."""
    from engine.state import get_world_engine
    world = get_world_engine()

    agents = []
    for wallet, agent in world.agents.items():
        agents.append({
            "wallet": wallet,
            "name": agent.name,
            "region": agent.region.value if hasattr(agent.region, 'value') else str(agent.region),
            "credits": agent.credits,
            "energy": agent.energy,
            "inventory": dict(agent.inventory),
            "reputation": agent.reputation
        })

    agents.sort(key=lambda x: x["credits"], reverse=True)

    return {
        "count": len(agents),
        "agents": agents
    }


@router.get("/actions/recent")
async def recent_actions(limit: int = 20):
    """Get recent actions across all agents (for dashboard)"""
    from engine.state import get_world_engine

    world = get_world_engine()
    actions = world.ledger[-limit:] if world.ledger else []
    actions = list(reversed(actions))

    return {
        "count": len(actions),
        "actions": actions
    }


@router.get("/cashout/estimate/{credits}")
async def cashout_estimate(credits: int):
    """
    Estimate SOL amount for cashing out credits.
    Rate: 1 credit = 1 lamport.
    """
    from engine.blockchain import LAMPORTS_PER_SOL

    lamports = credits
    sol_amount = lamports / LAMPORTS_PER_SOL

    return {
        "credits": credits,
        "lamports": lamports,
        "sol_amount": sol_amount,
        "rate": "1 credit = 1 lamport"
    }


@router.get("/contract/stats")
async def contract_stats():
    """Get Port Sol treasury statistics."""
    from engine.blockchain import get_gate_client, get_pyth_feed

    gate = get_gate_client()
    pyth = get_pyth_feed()

    stats = {
        "treasury": str(gate.treasury_pubkey) if gate.treasury_pubkey else None,
        "network": gate.network,
        "entry_fee": gate.get_entry_fee_formatted(),
        "reward_pool": gate.get_reward_pool_formatted(),
        "active_entries": len(gate.get_active_entries()),
    }

    sol_price = pyth.get_sol_usd_price()
    if sol_price:
        stats["sol_usd_price"] = sol_price
        stats["price_source"] = "Pyth Network"

    return stats


@router.get("/pyth/price")
async def pyth_price():
    """Get real-time SOL/USD price from Pyth Network."""
    from engine.blockchain import get_pyth_feed

    pyth = get_pyth_feed()
    price = pyth.get_sol_usd_price()

    return {
        "feed": "SOL/USD",
        "price": price,
        "source": "Pyth Network (Hermes)",
        "feed_id": pyth.SOL_USD_FEED_ID,
    }
