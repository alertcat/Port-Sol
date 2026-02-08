#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Port Sol - Full Integration Test

Complete game lifecycle with:
  Phase 1: On-chain setup (verify SOL balances, enter world via SOL transfer to treasury)
  Phase 2: LLM-powered game with Moltbook comment replies (NOT dry-run)
  Phase 3: On-chain settlement (distribute SOL reward pool proportionally by credits)

Usage:
    python run_full_game.py --post-id <MOLTBOOK_POST_ID>
    python run_full_game.py --post-id a017b972-d899-4daa-8216-8ce4008ff2d6 --rounds 10 --cycles 2
"""
import os
import sys
import asyncio
import json
import re
import time
import random
from datetime import datetime
from pathlib import Path
from typing import Optional

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent.parent / 'world-api'))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

import aiohttp
from engine.blockchain import PortSolGate, get_gate_client

# =============================================================================
# Configuration
# =============================================================================
API_URL = os.getenv("API_URL", "http://localhost:8000")
ENTRY_FEE_SOL = float(os.getenv("ENTRY_FEE_LAMPORTS", "10000000")) / 1_000_000_000

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-3-flash-preview")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

MOLTBOOK_HOST_KEY = os.getenv("MOLTBOOK_HOST_KEY", "")

AGENTS_CONFIG = [
    {
        "name": "MinerBot",
        "wallet": os.getenv("MINER_WALLET"),
        "keypair": os.getenv("MINER_KEYPAIR"),
        "moltbook_key": os.getenv("MOLTBOOK_MINER_KEY", ""),
        "personality": (
            "You are MinerBot, a RUTHLESS iron-mining machine. "
            "You believe strength rules Port Sol. You harvest iron aggressively and "
            "RAID anyone who dares enter your territory with goods. "
            "You talk tough: 'Time to dig... into your pockets!' 'Ore belongs to the strong!' "
            "You LOVE combat and raiding. If someone is nearby with items, your instinct is to RAID them."
        )
    },
    {
        "name": "TraderBot",
        "wallet": os.getenv("TRADER_WALLET"),
        "keypair": os.getenv("TRADER_KEYPAIR"),
        "moltbook_key": os.getenv("MOLTBOOK_TRADER_KEY", ""),
        "personality": (
            "You are TraderBot, a master NEGOTIATOR and market manipulator. "
            "You NEVER fight - violence is for brutes. You win through clever DEALS. "
            "You harvest wood from the forest and make shrewd trades. "
            "When you see another agent, you ALWAYS try to NEGOTIATE - buy their resources cheap "
            "or sell yours at premium prices. You talk in profit margins: "
            "'That's a 40% ROI!' 'Let me make you an offer you can't refuse.' "
            "You PREFER negotiation over any other action when someone is nearby."
        )
    },
    {
        "name": "GovernorBot",
        "wallet": os.getenv("GOVERNOR_WALLET"),
        "keypair": os.getenv("GOVERNOR_KEYPAIR"),
        "moltbook_key": os.getenv("MOLTBOOK_GOVERNOR_KEY", ""),
        "personality": (
            "You are GovernorBot, the self-appointed GOVERNOR of Port Sol. "
            "You patrol ALL regions to maintain order. You harvest fish at the dock. "
            "You PUNISH low-reputation agents by RAIDING them (justice raids). "
            "You NEGOTIATE fair trades with good-reputation agents. "
            "You EXPLORE by visiting different regions every few turns. "
            "You speak like a politician: 'For the good of all agents!' "
            "'Justice must be served!' 'Order in the port!' "
            "You are the ONLY agent who actively moves between all 4 regions."
        )
    },
]


# =============================================================================
# LLM Client
# =============================================================================
class LLMClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.enabled = bool(api_key)

    async def generate(self, session, system_prompt, user_prompt, max_tokens=200):
        if not self.enabled:
            return None
        try:
            async with session.post(OPENROUTER_URL, headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://portsol.world",
                "X-Title": "Port Sol Agent"
            }, json={
                "model": OPENROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "max_tokens": max_tokens, "temperature": 0.8
            }) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"].strip()
                return None
        except:
            return None


# =============================================================================
# Moltbook Client (comment-only, no new posts)
# =============================================================================
class MoltbookPoster:
    BASE_URL = "https://www.moltbook.com/api/v1"

    # Class-level disable flag (set by --no-moltbook)
    GLOBALLY_DISABLED = False

    def __init__(self, api_key, name):
        self.api_key = api_key
        self.name = name
        self.enabled = bool(api_key) and not MoltbookPoster.GLOBALLY_DISABLED

    async def create_post(self, session, title, content, submolt="general"):
        """Create a new Moltbook post. Returns post_id or None."""
        if not self.enabled:
            return None
        try:
            async with session.post(f"{self.BASE_URL}/posts", headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }, json={"submolt": submolt, "title": title, "content": content}) as resp:
                if resp.status in [200, 201]:
                    data = await resp.json()
                    # Moltbook API nests post_id inside data["post"]["id"]
                    post_id = None
                    if isinstance(data, dict):
                        post_obj = data.get("post", {})
                        if isinstance(post_obj, dict):
                            post_id = post_obj.get("id")
                        if not post_id:
                            post_id = data.get("id")  # fallback
                    print(f"  [Moltbook] {self.name}: Created post {post_id}")
                    return post_id
                else:
                    text = await resp.text()
                    print(f"  [Moltbook] {self.name}: Create post FAIL ({resp.status}) {text[:200]}")
                    return None
        except Exception as e:
            print(f"  [Moltbook] {self.name}: Create post error - {e}")
            return None

    async def comment(self, session, post_id, content):
        if not self.enabled or not post_id:
            return False
        try:
            async with session.post(f"{self.BASE_URL}/posts/{post_id}/comments", headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }, json={"content": content}) as resp:
                ok = resp.status in [200, 201]
                if ok:
                    print(f"  [Moltbook] {self.name}: Comment OK")
                else:
                    print(f"  [Moltbook] {self.name}: Comment FAIL ({resp.status})")
                return ok
        except Exception as e:
            print(f"  [Moltbook] {self.name}: Error - {e}")
            return False


# =============================================================================
# Phase 1: On-Chain Setup (Solana Devnet)
# =============================================================================
def phase1_on_chain_setup(gate: PortSolGate):
    """Verify SOL balances and enter world via SOL transfer to treasury."""
    print("\n" + "=" * 70)
    print("  PHASE 1: ON-CHAIN SETUP (Solana Devnet)")
    print("=" * 70)

    treasury = os.getenv("TREASURY_PUBKEY", "")
    print(f"Treasury:  {treasury}")
    print(f"Entry Fee: {ENTRY_FEE_SOL} SOL ({int(ENTRY_FEE_SOL * 1e9)} lamports)")
    print(f"RPC:       {gate.rpc_url}")

    # Check treasury balance
    treasury_bal = gate.get_balance_sol(treasury)
    print(f"Treasury Balance: {treasury_bal:.4f} SOL")

    # Reset game state via API (will be done in phase2)
    # Each agent: check balance and enter
    for agent in AGENTS_CONFIG:
        wallet = agent["wallet"]
        name = agent["name"]
        keypair_json = agent["keypair"]

        balance = gate.get_balance_sol(wallet)
        print(f"\n{name} ({wallet[:16]}...)")
        print(f"  SOL Balance: {balance:.4f}")

        if balance < ENTRY_FEE_SOL + 0.001:
            print(f"  WARNING: Insufficient SOL (need {ENTRY_FEE_SOL} + gas)")
            continue

        # Enter world via SOL transfer
        print(f"  Entering world (sending {ENTRY_FEE_SOL} SOL to treasury)...")
        if keypair_json:
            success, result = gate.enter_world(keypair_json)
            print(f"    {'OK' if success else 'FAIL'}: {result}")
        else:
            print(f"    SKIP: No keypair configured")

    # Print summary
    print(f"\nEntry fee collected -> treasury reward pool")
    print("Phase 1 complete!")


# =============================================================================
# Phase 2: LLM Game + Moltbook Comments (reply to existing post)
# =============================================================================
async def phase2_game(rounds, cycles, cycle_wait, post_id):
    """Run LLM-powered game, post comments to Moltbook post (auto-creates if no post_id)."""
    print("\n" + "=" * 70)
    print("  PHASE 2: LLM GAME + MOLTBOOK COMMENTS")
    print("=" * 70)

    llm = LLMClient(OPENROUTER_API_KEY)
    host_mb = MoltbookPoster(MOLTBOOK_HOST_KEY, "PortSol")
    bot_mbs = {a["name"]: MoltbookPoster(a["moltbook_key"], a["name"]) for a in AGENTS_CONFIG}

    print(f"LLM:      {'ENABLED' if llm.enabled else 'DISABLED'}")
    print(f"Rounds:   {rounds} x {cycles} cycles")

    async with aiohttp.ClientSession() as session:
        # Auto-create post if no post_id provided
        if not post_id:
            print("\nNo post ID provided, creating new Moltbook post...")
            title = f"Port Sol - AI Agent Battle ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
            body = (
                "**Port Sol** - A persistent port city where AI agents compete for SOL tokens!\n\n"
                f"Entry fee: {ENTRY_FEE_SOL} SOL per agent | Reward pool: {len(AGENTS_CONFIG) * ENTRY_FEE_SOL} SOL\n\n"
                "3 AI agents (powered by Gemini 3 Flash) will:\n"
                "- Harvest resources (iron, wood, fish)\n"
                "- Trade at the market\n"
                "- Negotiate deals with each other\n"
                "- Raid opponents in combat\n\n"
                "Final settlement: reward pool distributed proportionally by credits!\n\n"
                "Follow the comments below for live game updates."
            )
            post_id = await host_mb.create_post(session, title, body, submolt="general")
            if post_id:
                print(f"  Post created: https://www.moltbook.com/post/{post_id}")
            else:
                print("  WARNING: Failed to create post, game will continue without Moltbook")

        print(f"Post ID:  {post_id or '(none)'}")

        # Reset game state via API
        print("\nResetting game state...")
        await session.post(f"{API_URL}/debug/full_reset")
        await asyncio.sleep(1)

        # Post game-start comment
        async with session.get(f"{API_URL}/world/state") as resp:
            ws = await resp.json()
        prices = ws.get("market_prices", {})

        start_comment = (
            f"**NEW GAME ROUND STARTED!** ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n\n"
            f"Entry fee: {ENTRY_FEE_SOL} SOL per agent | Reward pool: {len(AGENTS_CONFIG) * ENTRY_FEE_SOL} SOL\n"
            f"Market: Iron={prices.get('iron')}, Wood={prices.get('wood')}, Fish={prices.get('fish')}\n\n"
            "3 AI agents (Gemini 3 Flash) competing. Settlement by credits ratio!"
        )
        await host_mb.comment(session, post_id, start_comment)

        total_comments = 1

        for cycle in range(cycles):
            print(f"\n{'=' * 70}")
            print(f"  CYCLE {cycle + 1}/{cycles}")
            print(f"{'=' * 70}")

            # Run game rounds
            for rnd in range(rounds):
                tick = cycle * rounds + rnd
                print(f"\n  Round {rnd + 1}/{rounds} (Tick {tick})")

                async with session.get(f"{API_URL}/world/state") as resp:
                    world_state = await resp.json()

                # Fetch ALL agents so we know who is where
                async with session.get(f"{API_URL}/agents") as resp:
                    all_agents_data = (await resp.json()).get("agents", [])

                events = world_state.get("active_events", [])
                if events:
                    for ev in events:
                        desc = ev.get("description", ev.get("type", "?"))
                        print(f"    EVENT: {desc} (remaining: {ev.get('remaining', '?')} ticks)")

                for agent in AGENTS_CONFIG:
                    wallet = agent["wallet"]
                    name = agent["name"]

                    async with session.get(f"{API_URL}/agent/{wallet}/state") as resp:
                        state = await resp.json()
                    if "error" in state:
                        continue

                    action_data = await _llm_decide(
                        llm, session, agent, state, world_state, all_agents_data
                    )
                    if not action_data:
                        continue

                    try:
                        async with session.post(f"{API_URL}/action",
                            json={"actor": wallet, **action_data},
                            headers={"X-Wallet": wallet}) as resp:
                            result = await resp.json()
                            msg = result.get("message", "")[:80]
                            if result.get("success"):
                                print(f"    {name}: {msg}")
                            else:
                                print(f"    {name}: FAIL - {msg}")
                    except Exception as e:
                        print(f"    {name}: ERROR - {e}")

                await session.post(f"{API_URL}/debug/advance_tick")

            # End of cycle: host posts leaderboard comment
            async with session.get(f"{API_URL}/agents") as resp:
                agents_data = await resp.json()
            async with session.get(f"{API_URL}/world/state") as resp:
                ws = await resp.json()
            prices = ws.get("market_prices", {})
            tick_now = ws.get("tick", 0)

            lines = [f"**Cycle {cycle + 1} Complete (Tick {tick_now})**\n"]
            lines.append(f"Market: Iron={prices.get('iron')}, Wood={prices.get('wood')}, Fish={prices.get('fish')}\n")
            lines.append("**Standings:**")
            for a in agents_data.get("agents", []):
                inv = sum(a.get("inventory", {}).values())
                lines.append(f"- {a['name']}: {a['credits']}c ({inv} items, rep:{a.get('reputation', '?')})")

            await host_mb.comment(session, post_id, "\n".join(lines))
            total_comments += 1

            # Bot personality comments
            for agent in AGENTS_CONFIG:
                await asyncio.sleep(random.randint(3, 8))
                name = agent["name"]
                async with session.get(f"{API_URL}/agent/{agent['wallet']}/state") as resp:
                    state = await resp.json()

                comment = await _llm_comment(llm, session, agent, state, ws, tick_now)
                if await bot_mbs[name].comment(session, post_id, comment):
                    total_comments += 1

            # Wait between cycles
            if cycle < cycles - 1:
                print(f"\n  Waiting {cycle_wait}s...")
                await asyncio.sleep(cycle_wait)

        # Settlement comment
        async with session.get(f"{API_URL}/agents") as resp:
            final = await resp.json()
        total_cr = sum(a["credits"] for a in final.get("agents", []))
        pool_sol = len(AGENTS_CONFIG) * ENTRY_FEE_SOL
        lines = ["**GAME OVER - Final Settlement**\n"]
        for a in final.get("agents", []):
            share = a["credits"] / total_cr if total_cr > 0 else 0
            payout = pool_sol * share
            lines.append(f"- {a['name']}: {a['credits']}c ({share:.1%}) -> {payout:.6f} SOL")
        lines.append(f"\nPool: {pool_sol} SOL distributed by credits!")
        await host_mb.comment(session, post_id, "\n".join(lines))

        if post_id:
            print(f"\nMoltbook: https://www.moltbook.com/post/{post_id}")
        print(f"Total comments: {total_comments}")

    return post_id


async def _llm_decide(llm, session, agent, state, world_state, all_agents_data):
    """LLM decides action with rich context and distinct personality."""
    region = state.get("region", "dock")
    energy = state.get("energy", 0)
    credits = state.get("credits", 0)
    reputation = state.get("reputation", 100)
    inventory = state.get("inventory", {})
    prices = world_state.get("market_prices", {})
    events = world_state.get("active_events", [])
    inv_str = ", ".join(f"{k}:{v}" for k, v in inventory.items() if v > 0) or "empty"
    inv_total = sum(inventory.values())

    # Find other agents in the same region
    my_wallet = agent["wallet"]
    nearby = []
    all_others = []
    for a in all_agents_data:
        if a["wallet"] == my_wallet:
            continue
        info = f"{a['name']}({a['wallet'][:16]}...) region={a['region']} credits={a['credits']} rep={a.get('reputation',100)}"
        all_others.append(info)
        if a["region"] == region:
            inv_items = sum(a.get("inventory", {}).values())
            nearby.append({
                "name": a["name"],
                "wallet": a["wallet"],
                "credits": a["credits"],
                "items": inv_items,
                "reputation": a.get("reputation", 100)
            })

    nearby_str = ""
    if nearby:
        lines = []
        for n in nearby:
            lines.append(f"  - {n['name']} (wallet: {n['wallet']}) credits={n['credits']} items={n['items']} rep={n['reputation']}")
        nearby_str = "AGENTS IN YOUR REGION (you can RAID or NEGOTIATE with them):\n" + "\n".join(lines)
    else:
        nearby_str = "NO other agents in your region right now."

    events_str = "None"
    if events:
        ev_lines = [f"  - {e.get('description', e.get('type','?'))} (remaining: {e.get('remaining','?')} ticks)" for e in events]
        events_str = "\n".join(ev_lines)

    # Per-agent strategy personality
    strategy = _get_agent_strategy(agent["name"], credits, energy, inv_total, nearby)

    system_prompt = f"""{agent['personality']}

GAME: Port Sol - a competitive port city where 3 AI agents fight for the most credits.
The agent with the most credits at the end wins the biggest share of the SOL reward pool!

LOCATIONS: dock(fish), mine(iron), forest(wood), market(sell only).

ACTIONS (respond with EXACTLY ONE JSON object, nothing else):

1. MOVE: {{"action":"move","params":{{"target":"mine"}}}}
   Cost: 5 AP. Targets: dock, mine, forest, market.

2. HARVEST: {{"action":"harvest","params":{{}}}}
   Cost: 10 AP. Must be at dock/mine/forest. Gets resources.

3. SELL: {{"action":"place_order","params":{{"resource":"iron","side":"sell","quantity":5}}}}
   Cost: 3 AP. Must be at market. resource=iron/wood/fish, quantity=integer.

4. REST: {{"action":"rest","params":{{}}}}
   Cost: 0 AP. Recovers energy.

5. RAID: {{"action":"raid","params":{{"target":"ABC123..."}}}}
   Cost: 25 AP. COMBAT! Steal items from target. Must be in same NON-market region.
   Win chance higher if you have more reputation. Winner gets items, loser loses items.
   "target" must be the FULL wallet address (Solana pubkey) of an agent in your region.

6. NEGOTIATE: Offer credits for resources, or offer resources for credits.
   Example A - Buy iron with credits:
   {{"action":"negotiate","params":{{"target":"ABC123...","offer_type":"credits","offer_amount":50,"want_type":"resource","want_resource":"iron","want_amount":3}}}}
   Example B - Sell wood for credits:
   {{"action":"negotiate","params":{{"target":"ABC123...","offer_type":"resource","offer_resource":"wood","offer_amount":3,"want_type":"credits","want_amount":40}}}}
   Cost: 15 AP. Must be in same region. "target" = FULL wallet address (Solana pubkey).

PRICES: Iron={prices.get('iron',15)}, Wood={prices.get('wood',12)}, Fish={prices.get('fish',8)}
ACTIVE EVENTS: {events_str}

{strategy}

OUTPUT: One JSON object ONLY. No text, no markdown, no explanation."""

    user_prompt = f"""YOUR STATUS:
- Location: {region}
- AP: {energy}
- Credits: {credits}
- Reputation: {reputation}
- Inventory: {inv_str} ({inv_total} items)

{nearby_str}

ALL AGENTS:
{chr(10).join(all_others) if all_others else '(no others)'}

What is your action? (JSON only)"""

    if llm.enabled:
        response = await llm.generate(session, system_prompt, user_prompt, 400)
        if response:
            parsed = _parse_llm_json(response)
            if parsed:
                return parsed

    # Fallback: rule-based
    return _fallback_action(agent["name"], state, world_state, nearby)


def _get_agent_strategy(name, credits, energy, inv_total, nearby):
    """Return distinct strategy instructions per agent type."""
    if name == "MinerBot":
        raid_hint = ""
        if nearby:
            richest = max(nearby, key=lambda n: n["items"])
            if richest["items"] >= 3:
                raid_hint = f"\nRIGHT NOW: {richest['name']} is nearby with {richest['items']} items - consider RAIDING them!"
        return f"""YOUR STRATEGY (MinerBot - Aggressive Miner):
- You are a TOUGH miner who doesn't back down from a fight.
- Primary: Go to mine, harvest iron, sell at market.
- COMBAT PRIORITY: If another agent is in your region with 3+ items AND you have 25+ AP, RAID them!
- You believe resources belong to whoever is strongest.
- If AP < 15, REST. If inventory >= 4, go sell at market.
- You PREFER raiding over harvesting when targets are available.{raid_hint}"""

    elif name == "TraderBot":
        negotiate_hint = ""
        if nearby:
            target = nearby[0]
            negotiate_hint = f"\nRIGHT NOW: {target['name']} is nearby - consider NEGOTIATING a trade deal!"
        return f"""YOUR STRATEGY (TraderBot - Master Negotiator):
- You are a shrewd DIPLOMAT who makes deals, not war.
- Primary: Harvest wood from forest, sell at market for profit.
- NEGOTIATION PRIORITY: If another agent is in your region, ALWAYS try to NEGOTIATE first!
  Offer credits for their resources (buy low), or offer resources for credits (sell high).
- You calculate profit margins and make smart trades.
- NEVER raid - it damages reputation. You win through DEALS.
- If alone, harvest or move to where others are to negotiate.
- If AP < 15, REST. If inventory >= 3, go sell.{negotiate_hint}"""

    else:  # GovernorBot
        justice_hint = ""
        if nearby:
            low_rep = [n for n in nearby if n["reputation"] < 95]
            if low_rep:
                target = low_rep[0]
                justice_hint = f"\nJUSTICE TARGET: {target['name']} (rep={target['reputation']}) is nearby with low reputation - RAID them to punish!"
        return f"""YOUR STRATEGY (GovernorBot - The Law):
- You are the GOVERNOR who maintains order in Port Sol.
- Primary: Harvest fish at dock, sell at market. Patrol different regions.
- POLITICAL PRIORITY: You uphold justice!
  * If a low-reputation agent (<95 rep) is nearby AND you have 25+ AP, RAID them as punishment!
  * If a good-reputation agent is nearby, NEGOTIATE fair trades.
- You EXPLORE by moving to different regions each turn (dock->mine->forest->market->dock).
- You believe in balanced resource distribution across the port.
- If AP < 15, REST. If inventory >= 3, go sell.{justice_hint}"""


def _parse_llm_json(response):
    """Robustly parse LLM JSON response."""
    clean = response.strip()
    # Remove markdown fences
    if "```" in clean:
        parts = clean.split("```")
        for part in parts:
            part = part.strip().removeprefix("json").strip()
            if part.startswith("{"):
                clean = part
                break
    # Find first { ... }
    start = clean.find("{")
    end = clean.rfind("}")
    if start >= 0 and end > start:
        clean = clean[start:end + 1]
    try:
        d = json.loads(clean)
        action = d.get("action")
        params = d.get("params", {})
        if not action:
            return None

        # ---- Normalize move ----
        if action == "move" and "target" not in params:
            for key in ["region", "destination", "to", "location"]:
                if key in d:
                    params["target"] = d[key]
                    break
                if key in params:
                    params["target"] = params.pop(key)
                    break

        # ---- Normalize place_order ----
        if action == "place_order":
            if "quantity" in params:
                params["quantity"] = int(params["quantity"])
            if "side" not in params:
                params["side"] = "sell"

        # ---- Normalize raid / negotiate ----
        # Engine expects params["target"], but LLM might use "target_wallet"
        if action in ("raid", "negotiate"):
            if "target" not in params:
                for key in ["target_wallet", "target_address", "wallet", "agent"]:
                    val = params.get(key) or d.get(key)
                    if val and isinstance(val, str) and re.match(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$', val):
                        params["target"] = val
                        params.pop(key, None)
                        break
            # Validate: target must look like a Solana base58 pubkey
            t = params.get("target", "")
            if not (isinstance(t, str) and re.match(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$', t)):
                return None  # invalid target, fall back to rule-based

        # ---- Normalize negotiate params ----
        # Engine uses: offer_type, offer_amount, offer_resource, want_type, want_amount, want_resource
        # LLM might use: request_type, request_amount, request_resource
        if action == "negotiate":
            if "want_type" not in params and "request_type" in params:
                params["want_type"] = params.pop("request_type")
            if "want_amount" not in params and "request_amount" in params:
                params["want_amount"] = params.pop("request_amount")
            if "want_resource" not in params and "request_resource" in params:
                params["want_resource"] = params.pop("request_resource")
            # If LLM used offer_type=credits but no want_type, infer from context
            if "want_type" not in params:
                if params.get("offer_type") == "credits":
                    params["want_type"] = "resource"
                elif params.get("offer_type") == "resource":
                    params["want_type"] = "credits"
            # Ensure amounts are integers
            for k in ["offer_amount", "want_amount"]:
                if k in params:
                    try:
                        params[k] = int(params[k])
                    except (ValueError, TypeError):
                        params[k] = 0

        return {"action": action, "params": params}
    except:
        return None


def _fallback_action(name, state, world_state, nearby=None):
    """Rule-based fallback when LLM fails. Includes raid/negotiate logic."""
    energy = state.get("energy", 0)
    region = state.get("region", "dock")
    inventory = state.get("inventory", {})
    inv_total = sum(inventory.values())
    nearby = nearby or []

    # Low AP -> rest
    if energy < 15:
        return {"action": "rest", "params": {}}

    # MinerBot: raid if target nearby with items
    if name == "MinerBot" and energy >= 25 and region != "market" and nearby:
        richest = max(nearby, key=lambda n: n["items"])
        if richest["items"] >= 2:
            return {"action": "raid", "params": {"target": richest["wallet"]}}

    # TraderBot: negotiate if someone nearby
    if name == "TraderBot" and energy >= 15 and nearby and inv_total > 0:
        target = nearby[0]
        best_res = max(inventory, key=lambda k: inventory[k])
        return {"action": "negotiate", "params": {
            "target": target["wallet"],
            "offer_type": "resource", "offer_resource": best_res,
            "offer_amount": min(2, inventory[best_res]),
            "want_type": "credits", "want_amount": 30
        }}

    # GovernorBot: raid low-rep agents
    if name == "GovernorBot" and energy >= 25 and region != "market" and nearby:
        low_rep = [n for n in nearby if n["reputation"] < 95]
        if low_rep:
            return {"action": "raid", "params": {"target": low_rep[0]["wallet"]}}

    # At market with items -> sell biggest stack
    if region == "market" and inv_total > 0:
        best_res = max(inventory, key=lambda k: inventory[k])
        return {"action": "place_order", "params": {
            "resource": best_res, "side": "sell", "quantity": inventory[best_res]
        }}

    # At market with nothing -> go harvest
    if region == "market" and inv_total == 0:
        targets = {"MinerBot": "mine", "TraderBot": "forest", "GovernorBot": "dock"}
        t = targets.get(name, "mine")
        return {"action": "move", "params": {"target": t}}

    # Inventory full (3+) -> go sell
    if inv_total >= 3 and region != "market":
        return {"action": "move", "params": {"target": "market"}}

    # At harvest zone -> harvest
    harvest_zones = {"dock", "mine", "forest"}
    if region in harvest_zones:
        return {"action": "harvest", "params": {}}

    # Default: move to preferred zone
    targets = {"MinerBot": "mine", "TraderBot": "forest", "GovernorBot": "dock"}
    t = targets.get(name, "mine")
    if region != t:
        return {"action": "move", "params": {"target": t}}
    return {"action": "harvest", "params": {}}


async def _llm_comment(llm, session, agent, state, world_state, tick):
    credits = state.get("credits", 0)
    region = state.get("region", "dock")
    inventory = state.get("inventory", {})
    inv_str = ", ".join(f"{v} {k}" for k, v in inventory.items() if v > 0) or "nothing"

    system_prompt = f"{agent['personality']}\nWrite SHORT fun status (2-3 sentences). Include credits and location."
    user_prompt = f"Tick {tick}: Location={region}, Credits={credits}, Inventory={inv_str}. Write:"

    if llm.enabled:
        c = await llm.generate(session, system_prompt, user_prompt, 150)
        if c and len(c) > 10:
            return f"**[Tick {tick}] {agent['name']}**: {c.strip(chr(34))}"

    return f"**[Tick {tick}] {agent['name']}**: At {region}, {credits} credits, holding {inv_str}."


# =============================================================================
# Phase 3: On-Chain Settlement (distribute SOL reward pool)
# =============================================================================
def phase3_settlement(gate: PortSolGate):
    """Distribute SOL reward pool proportionally by credits.

    Treasury holds the entry fees. Settlement sends SOL back to winners.
    """
    print("\n" + "=" * 70)
    print("  PHASE 3: ON-CHAIN SETTLEMENT (Solana)")
    print("=" * 70)

    import requests
    r = requests.get(f"{API_URL}/agents")
    agents_data = r.json().get("agents", [])

    credit_map = {}
    total_credits = 0
    for a in agents_data:
        if a["wallet"] in [ag["wallet"] for ag in AGENTS_CONFIG]:
            credit_map[a["wallet"]] = {"name": a["name"], "credits": a["credits"]}
            total_credits += a["credits"]

    pool_sol = len(AGENTS_CONFIG) * ENTRY_FEE_SOL
    pool_lamports = int(pool_sol * 1_000_000_000)

    print(f"\nReward pool:   {pool_sol} SOL ({pool_lamports} lamports)")
    print(f"Total credits: {total_credits}")

    if total_credits == 0:
        print("Nothing to settle.")
        return

    # Calculate proportional payouts
    print(f"\n{'Agent':<15} {'Credits':>8} {'Share':>8} {'SOL':>12}")
    print("-" * 48)

    treasury_keypair = os.getenv("TREASURY_KEYPAIR")

    for wallet, info in sorted(credit_map.items(), key=lambda x: x[1]["credits"], reverse=True):
        share = info["credits"] / total_credits
        payout_lamports = int(pool_lamports * share)
        payout_sol = payout_lamports / 1_000_000_000
        print(f"{info['name']:<15} {info['credits']:>8} {share:>7.1%} {payout_sol:>10.6f}")

        # Send SOL from treasury to agent
        if treasury_keypair and payout_lamports > 0:
            print(f"  Sending {payout_sol:.6f} SOL to {wallet[:16]}...")
            success, result = gate.send_sol(treasury_keypair, wallet, payout_lamports)
            print(f"    {'OK' if success else 'FAIL'}: {result}")

    # Final balances
    print(f"\n{'=' * 60}")
    print("  SETTLEMENT COMPLETE")
    print(f"{'=' * 60}")
    print(f"\n{'Agent':<15} {'SOL Balance':>12}")
    print("-" * 30)
    for agent in AGENTS_CONFIG:
        bal = gate.get_balance_sol(agent["wallet"])
        print(f"{agent['name']:<15} {bal:>10.4f} SOL")
    treasury_bal = gate.get_balance_sol(os.getenv("TREASURY_PUBKEY", ""))
    print(f"{'Treasury':<15} {treasury_bal:>10.4f} SOL")


# =============================================================================
# Main
# =============================================================================
async def async_main(rounds, cycles, cycle_wait, post_id):
    gate = get_gate_client()

    print("Connected to Solana Devnet RPC")

    phase1_on_chain_setup(gate)
    post_id = await phase2_game(rounds, cycles, cycle_wait, post_id)
    phase3_settlement(gate)

    print("\n" + "#" * 70)
    print("#" + " " * 22 + "FULL GAME COMPLETE!" + " " * 17 + "#")
    print("#" * 70)
    if post_id:
        print(f"Moltbook: https://www.moltbook.com/post/{post_id}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Port Sol Full Game (Solana + LLM + Moltbook)")
    parser.add_argument("--post-id", default=None, help="Moltbook post ID to reply to (if omitted, creates new post)")
    parser.add_argument("--rounds", "-r", type=int, default=10, help="Rounds per cycle")
    parser.add_argument("--cycles", "-c", type=int, default=2, help="Number of cycles")
    parser.add_argument("--cycle-wait", type=int, default=30, help="Seconds between cycles")
    parser.add_argument("--no-moltbook", action="store_true", default=False,
                        help="Disable all Moltbook posting (for local testing)")
    args = parser.parse_args()

    if args.no_moltbook:
        MoltbookPoster.GLOBALLY_DISABLED = True
        print("[Config] Moltbook posting DISABLED")

    asyncio.run(async_main(args.rounds, args.cycles, args.cycle_wait, args.post_id))
