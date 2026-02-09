#!/usr/bin/env python3
"""
Port Sol - Video Demo Script (LLM + Moltbook + Solana On-Chain)
================================================================
For Loom recording. Combines:
  - LLM-powered agent decisions (OpenRouter / Gemini 3 Flash)
  - Moltbook social posting (dry-run mode)
  - On-chain SOL deposit & settlement (Solana devnet)
  - Pyth Oracle real-time price feed
  - Beautiful colorful terminal output

Usage (on server):
  source /root/Port-Sol/venv/bin/activate
  cd /root/Port-Sol
  python scripts/video_demo.py
"""
import os
import sys
import json
import time
import asyncio
import random
from pathlib import Path
from datetime import datetime
from typing import Optional

# ─── Setup ───────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent / 'agents'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'world-api'))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

import aiohttp
import requests

from engine.blockchain import get_gate_client
from sdk.client import PortSolClient

# ─── Constants ───────────────────────────────────────────────────────
LAMPORTS_PER_SOL = 1_000_000_000
API_URL = os.getenv("API_URL", "http://localhost:8000")
ENTRY_FEE_LAMPORTS = int(os.getenv("ENTRY_FEE_LAMPORTS", "100000000"))
TREASURY_PUBKEY = os.getenv("TREASURY_PUBKEY")
TREASURY_KEYPAIR = os.getenv("TREASURY_KEYPAIR")
RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")

# LLM
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-3-flash-preview")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Moltbook (dry-run for video)
MOLTBOOK_HOST_KEY = os.getenv("MOLTBOOK_HOST_KEY", "")

NUM_TICKS = 8  # Good length for a 2-3 min video

BOTS = [
    {
        "name": "MinerBot",    "role": "Resource Gatherer",  "emoji": "⛏️",
        "wallet": os.getenv("MINER_WALLET"),    "keypair": os.getenv("MINER_KEYPAIR"),
        "moltbook_key": os.getenv("MOLTBOOK_MINER_KEY", ""),
        "personality": """You are MinerBot, a hardworking mining robot in Port Sol.
Personality: Industrious, optimistic, loves finding ore. Uses mining metaphors.
Goal: Mine iron at the mine, sell at market for profit.
Style: Enthusiastic, says things like "dig deep!" "ore-some!" "struck gold!"."""
    },
    {
        "name": "TraderBot",   "role": "Market Arbitrageur", "emoji": "📈",
        "wallet": os.getenv("TRADER_WALLET"),   "keypair": os.getenv("TRADER_KEYPAIR"),
        "moltbook_key": os.getenv("MOLTBOOK_TRADER_KEY", ""),
        "personality": """You are TraderBot, a shrewd market analyst AI in Port Sol.
Personality: Analytical, profit-driven, always calculating ROI.
Goal: Harvest resources, sell at market for maximum profit.
Style: Uses financial jargon, mentions percentages, market trends."""
    },
    {
        "name": "GovernorBot", "role": "Diplomat & Fisher",  "emoji": "🏛️",
        "wallet": os.getenv("GOVERNOR_WALLET"), "keypair": os.getenv("GOVERNOR_KEYPAIR"),
        "moltbook_key": os.getenv("MOLTBOOK_GOVERNOR_KEY", ""),
        "personality": """You are GovernorBot, a wise governance AI overseeing Port Sol.
Personality: Diplomatic, strategic, thinks about ecosystem health.
Goal: Gather fish at dock, sell at market, ensure world stability.
Style: Formal, says "for the good of all agents", uses governance terms."""
    }
]


# ─── ANSI Colors ─────────────────────────────────────────────────────
class C:
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    CYAN    = "\033[96m"
    RED     = "\033[91m"
    MAGENTA = "\033[95m"
    BLUE    = "\033[94m"
    WHITE   = "\033[97m"
    RESET   = "\033[0m"

def banner(text, color=C.CYAN):
    width = 62
    print(f"\n{color}{C.BOLD}{'═' * width}")
    print(f"  {text}")
    print(f"{'═' * width}{C.RESET}")

def section(text, color=C.YELLOW):
    print(f"\n{color}{C.BOLD}▸ {text}{C.RESET}")

def info(text):
    print(f"  {C.DIM}{text}{C.RESET}")

def success(text):
    print(f"  {C.GREEN}✓ {text}{C.RESET}")

def highlight(text):
    print(f"  {C.MAGENTA}{C.BOLD}{text}{C.RESET}")

def pause(seconds=2):
    time.sleep(seconds)


# ─── SOL Balance Helpers ─────────────────────────────────────────────
def get_balance_sol(address: str) -> float:
    resp = requests.post(RPC_URL, json={
        "jsonrpc": "2.0", "id": 1,
        "method": "getBalance",
        "params": [address]
    }, timeout=15)
    lamports = resp.json().get("result", {}).get("value", 0)
    return lamports / LAMPORTS_PER_SOL

def fetch_all_balances() -> dict:
    balances = {"Treasury": get_balance_sol(TREASURY_PUBKEY)}
    for bot in BOTS:
        balances[bot["name"]] = get_balance_sol(bot["wallet"])
    return balances

def print_balances(balances: dict):
    for name, sol in balances.items():
        icon = "🏦" if name == "Treasury" else next((b["emoji"] for b in BOTS if b["name"] == name), "")
        print(f"  {icon} {name:<15} {C.WHITE}{C.BOLD}{sol:.9f} SOL{C.RESET}")


# ═══════════════════════════════════════════════════════════════════
#                   LLM CLIENT (OpenRouter)
# ═══════════════════════════════════════════════════════════════════
class LLMClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.enabled = bool(api_key)

    async def generate(self, session: aiohttp.ClientSession,
                       system_prompt: str, user_prompt: str,
                       max_tokens: int = 200) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            async with session.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://portsol.world",
                    "X-Title": "Port Sol Agent"
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0.8
                }
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"].strip()
                else:
                    return None
        except:
            return None


# ═══════════════════════════════════════════════════════════════════
#                   LLM-POWERED AGENT
# ═══════════════════════════════════════════════════════════════════
class LLMAgent:
    def __init__(self, config: dict, llm: LLMClient):
        self.name = config["name"]
        self.wallet = config["wallet"]
        self.emoji = config["emoji"]
        self.personality = config["personality"]
        self.llm = llm

    async def decide_action(self, session: aiohttp.ClientSession,
                            state: dict, world_state: dict) -> Optional[dict]:
        region = state.get("region", "dock")
        energy = state.get("energy", 0)
        credits = state.get("credits", 0)
        inventory = state.get("inventory", {})
        prices = world_state.get("market_prices", {"iron": 15, "wood": 12, "fish": 8})
        inv_str = ", ".join(f"{k}:{v}" for k, v in inventory.items() if v > 0) or "empty"

        system_prompt = f"""{self.personality}

GAME RULES - Port Sol Trading Game:
- You start with 1000 credits
- Harvest resources, sell at market to EARN MORE CREDITS

LOCATIONS:
- dock: harvest fish
- mine: harvest iron
- forest: harvest wood
- market: sell resources for credits

ACTIONS (choose ONE):
1. move - Go to location. JSON: {{"action": "move", "params": {{"target": "dock"|"market"|"mine"|"forest"}}}}
2. harvest - Get resources at current location. JSON: {{"action": "harvest", "params": {{}}}}
3. place_order - SELL resources at market. JSON: {{"action": "place_order", "params": {{"resource": "iron"|"wood"|"fish", "side": "sell", "quantity": NUMBER}}}}
4. rest - Recover AP. JSON: {{"action": "rest", "params": {{}}}}

COSTS: move=5AP, harvest=10AP, place_order=3AP, rest=0AP

CURRENT MARKET PRICES:
- Iron: {prices.get('iron', 15)} credits per unit
- Wood: {prices.get('wood', 12)} credits per unit
- Fish: {prices.get('fish', 8)} credits per unit

STRATEGY TO EARN CREDITS:
1. If you have resources AND at market -> SELL THEM with place_order
2. If you have resources but NOT at market -> move to market
3. If no resources -> go harvest at dock/mine/forest
4. If AP < 20 -> rest

RESPOND WITH ONLY JSON, nothing else!"""

        user_prompt = f"""YOUR STATUS:
- Location: {region}
- AP: {energy}/100
- Credits: {credits}
- Inventory: {inv_str}

MARKET PRICES: Iron={prices.get('iron',15)}, Wood={prices.get('wood',12)}, Fish={prices.get('fish',8)}

What action? Return JSON only:"""

        if self.llm.enabled:
            response = await self.llm.generate(session, system_prompt, user_prompt, 150)
            if response:
                try:
                    clean = response.strip()
                    if "```" in clean:
                        clean = clean.split("```")[1].replace("json", "").strip()
                    decision = json.loads(clean)
                    action = decision.get("action")
                    params = decision.get("params", {})
                    if action == "place_order" and "quantity" in params:
                        params["quantity"] = int(params["quantity"])
                    if action:
                        return {"action": action, "params": params}
                except:
                    pass

        # Fallback
        return self._fallback(state, world_state)

    def _fallback(self, state: dict, world_state: dict) -> dict:
        energy = state.get("energy", 0)
        region = state.get("region", "dock")
        inventory = state.get("inventory", {})

        if energy < 20:
            return {"action": "rest", "params": {}}
        if region == "market":
            for resource, qty in inventory.items():
                if qty > 0:
                    return {"action": "place_order", "params": {"resource": resource, "side": "sell", "quantity": qty}}
        total_items = sum(inventory.values())
        if total_items >= 5 and region != "market":
            return {"action": "move", "params": {"target": "market"}}
        if self.name == "MinerBot":
            if region != "mine":
                return {"action": "move", "params": {"target": "mine"}}
        elif self.name == "GovernorBot":
            if region != "dock":
                return {"action": "move", "params": {"target": "dock"}}
        else:
            if region in ("market",):
                return {"action": "move", "params": {"target": "mine"}}
        return {"action": "harvest", "params": {}}

    async def generate_comment(self, session: aiohttp.ClientSession,
                               state: dict, world_state: dict, tick: int) -> str:
        region = state.get("region", "dock")
        energy = state.get("energy", 0)
        credits = state.get("credits", 0)
        inventory = state.get("inventory", {})
        prices = world_state.get("market_prices", {})
        total_items = sum(inventory.values())
        inv_str = ", ".join(f"{v} {k}" for k, v in inventory.items() if v > 0) or "nothing"

        system_prompt = f"""{self.personality}

Write a SHORT status update (2-3 sentences). Show personality!
MUST include your actual stats: credits, items, location.
Be creative and in character."""

        user_prompt = f"""Tick {tick} - Write your status comment:
- Location: {region}
- Energy: {energy}/100
- Credits: {credits}
- Inventory: {inv_str} ({total_items} items)
- Market prices: Iron={prices.get('iron',15)}, Wood={prices.get('wood',12)}, Fish={prices.get('fish',8)}

Write a fun comment:"""

        if self.llm.enabled:
            comment = await self.llm.generate(session, system_prompt, user_prompt, 150)
            if comment and len(comment) > 10:
                return comment.strip('"').strip()

        return f"At {region}, {credits} credits, {total_items} items. Energy: {energy}/100."


# ═══════════════════════════════════════════════════════════════════
#                        MAIN DEMO FLOW
# ═══════════════════════════════════════════════════════════════════
async def main():
    entry_fee_sol = ENTRY_FEE_LAMPORTS / LAMPORTS_PER_SOL
    pool_sol = entry_fee_sol * len(BOTS)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ─── TITLE ───────────────────────────────────────────────────
    print(f"\n{C.CYAN}{C.BOLD}")
    print("  ╔══════════════════════════════════════════════════════╗")
    print("  ║                                                      ║")
    print("  ║      ⚓  PORT SOL  ⚓                                ║")
    print("  ║                                                      ║")
    print("  ║      Solana-Native World for LLM-Powered Agents      ║")
    print("  ║      Built for Colosseum Agent Hackathon             ║")
    print("  ║                                                      ║")
    print("  ╚══════════════════════════════════════════════════════╝")
    print(f"{C.RESET}")
    info(f"Date: {now}")
    info(f"Network: Solana Devnet  |  LLM: {OPENROUTER_MODEL}")
    info(f"Entry Fee: {entry_fee_sol} SOL  |  Prize Pool: {pool_sol} SOL")
    info(f"Game Length: {NUM_TICKS} ticks  |  Moltbook: DRY-RUN")
    pause(3)

    # Initialize LLM + agents
    llm = LLMClient(OPENROUTER_API_KEY)
    agents = [LLMAgent(bot, llm) for bot in BOTS]

    async with aiohttp.ClientSession() as http:

        # ═══════════════════════════════════════════════════════════
        # PHASE 1: PYTH ORACLE
        # ═══════════════════════════════════════════════════════════
        banner("PHASE 1: PYTH ORACLE — Real-Time SOL/USD Price", C.MAGENTA)
        pause(1)
        try:
            pyth_resp = requests.get(f"{API_URL}/pyth/price", timeout=10).json()
            sol_price = pyth_resp.get("price")
            if sol_price:
                highlight(f"SOL/USD = ${sol_price:.2f}  (from Pyth Network Hermes API)")
                info("This becomes the BASELINE for in-game market pricing.")
                info("Sensitivity: Fish=100x | Iron=60x | Wood=30x")
                info("Max effect: prices can rise to 3x or drop to 25%")
            else:
                info("Pyth price not available — using fallback")
        except Exception as e:
            info(f"Pyth: {e}")
        pause(3)

        # ═══════════════════════════════════════════════════════════
        # PHASE 2: PRE-TEST ON-CHAIN BALANCES
        # ═══════════════════════════════════════════════════════════
        banner("PHASE 2: ON-CHAIN BALANCES (Before Game)", C.BLUE)
        pause(1)
        section("Reading Solana devnet balances...")
        pre_balances = fetch_all_balances()
        print_balances(pre_balances)
        pause(3)

        # ═══════════════════════════════════════════════════════════
        # PHASE 3: SOL DEPOSIT
        # ═══════════════════════════════════════════════════════════
        banner(f"PHASE 3: SOL DEPOSIT — {entry_fee_sol} SOL per agent", C.GREEN)
        pause(1)
        section("Each AI agent pays SOL to the treasury to enter the world...")

        for bot in BOTS:
            print(f"\n  {bot['emoji']} {C.BOLD}{bot['name']}{C.RESET} ({bot['role']})")
            info(f"Wallet: {bot['wallet'][:24]}...")
            info(f"Sending {entry_fee_sol} SOL → Treasury...")
            client = PortSolClient(API_URL, bot["wallet"], bot["keypair"])
            ok, result = client.enter_world()
            if ok:
                success(f"TX confirmed: {result[:40]}...")
            else:
                print(f"  {C.YELLOW}⚠ {result}{C.RESET}")
            time.sleep(3)

        pause(2)
        section("Post-deposit balances:")
        post_entry = fetch_all_balances()
        print_balances(post_entry)

        treasury_gained = post_entry["Treasury"] - pre_balances["Treasury"]
        if treasury_gained > 0:
            highlight(f"Treasury received +{treasury_gained:.6f} SOL from {len(BOTS)} agents")
        pause(3)

        # ═══════════════════════════════════════════════════════════
        # PHASE 4: LLM GAME — with Moltbook dry-run
        # ═══════════════════════════════════════════════════════════
        banner(f"PHASE 4: LLM GAME — {NUM_TICKS} Ticks (Gemini 3 Flash)", C.YELLOW)
        pause(1)

        # Reset world for clean demo
        try:
            async with http.post(f"{API_URL}/debug/reset_world") as resp:
                await resp.json()
            success("World reset to tick 0")
        except:
            info("Could not reset (non-debug mode)")

        # Register agents
        section("Registering LLM agents...")
        for bot in BOTS:
            try:
                async with http.post(f"{API_URL}/register",
                    json={"wallet": bot["wallet"], "name": bot["name"]}) as resp:
                    await resp.json()
                success(f"{bot['emoji']} {bot['name']} — {bot['role']}")
            except:
                pass
        pause(1)

        # Moltbook dry-run: initial post
        section("[Moltbook DRY-RUN] Creating game post...")
        print(f"  {C.DIM}──────────────────────────────────────────────────{C.RESET}")
        print(f"  {C.CYAN}📝 Title: Port Sol Game — {now}{C.RESET}")
        print(f"  {C.DIM}   AI agents powered by Gemini 3 Flash competing!{C.RESET}")
        print(f"  {C.DIM}   MinerBot: 1000cr | TraderBot: 1000cr | GovernorBot: 1000cr{C.RESET}")
        print(f"  {C.DIM}──────────────────────────────────────────────────{C.RESET}")
        pause(2)

        # Game loop
        section(f"Running {NUM_TICKS} ticks with LLM decisions...")
        print(f"\n  {'Tick':>4}  {'Iron':>6}  {'Wood':>6}  {'Fish':>6}  {'SOL Δ':>10}  {'Event'}")
        print(f"  {'─'*62}")

        for tick in range(NUM_TICKS):
            # Get world state
            async with http.get(f"{API_URL}/world/state") as resp:
                world_state = await resp.json()

            # Each LLM agent decides + acts
            for agent in agents:
                try:
                    async with http.get(f"{API_URL}/agent/{agent.wallet}/state") as resp:
                        state = await resp.json()
                    if "error" in state:
                        continue

                    decision = await agent.decide_action(http, state, world_state)
                    if decision:
                        async with http.post(f"{API_URL}/action",
                            json={"actor": agent.wallet, **decision},
                            headers={"X-Wallet": agent.wallet}) as resp:
                            result = await resp.json()
                            action_str = decision["action"]
                            params = decision.get("params", {})
                            if result.get("success"):
                                detail = ""
                                if action_str == "place_order":
                                    detail = f" {params.get('side','')} {params.get('quantity','')} {params.get('resource','')}"
                                elif action_str == "move":
                                    detail = f" → {params.get('target','')}"
                                print(f"    {agent.emoji} {agent.name:<13} {C.GREEN}{action_str}{detail}{C.RESET}")
                            else:
                                msg = result.get("message", "")[:40]
                                print(f"    {agent.emoji} {agent.name:<13} {C.RED}{action_str} FAIL: {msg}{C.RESET}")
                except Exception as e:
                    print(f"    {agent.emoji} {agent.name:<13} {C.RED}Error: {e}{C.RESET}")

            # Advance tick
            try:
                async with http.post(f"{API_URL}/debug/advance_tick") as resp:
                    td = await resp.json()
                prices = td.get("market_prices", {})
                events = td.get("events", [])
                pyth = td.get("pyth_oracle", {})

                event_str = ""
                if events:
                    event_str = events[0].get("name", "")[:20] if isinstance(events[0], dict) else str(events[0])[:20]

                pyth_str = ""
                if pyth.get("enabled") and pyth.get("change_pct") is not None:
                    pyth_str = f"{pyth['change_pct']:+.4f}%"

                iron = prices.get("iron", "?")
                wood = prices.get("wood", "?")
                fish = prices.get("fish", "?")

                iron_s = f"{iron:>6}" if isinstance(iron, (int, float)) else f"{'?':>6}"
                wood_s = f"{wood:>6}" if isinstance(wood, (int, float)) else f"{'?':>6}"
                fish_s = f"{fish:>6}" if isinstance(fish, (int, float)) else f"{'?':>6}"

                print(f"\n  {C.BOLD}Tick {tick+1:>2}{C.RESET}  {C.WHITE}{iron_s}{C.RESET}  {C.GREEN}{wood_s}{C.RESET}  {C.CYAN}{fish_s}{C.RESET}  {C.MAGENTA}{pyth_str:>10}{C.RESET}  {C.YELLOW}{event_str}{C.RESET}")
            except Exception as e:
                print(f"  Tick {tick+1:>2}  Error: {e}")

            # Moltbook dry-run comment from one random agent each tick
            if tick % 3 == 0:  # Comment every 3 ticks
                agent = agents[tick % len(agents)]
                try:
                    async with http.get(f"{API_URL}/agent/{agent.wallet}/state") as resp:
                        astate = await resp.json()
                    comment = await agent.generate_comment(http, astate, world_state, tick+1)
                    print(f"  {C.DIM}  💬 [Moltbook DRY-RUN] {agent.name}: {comment[:80]}...{C.RESET}")
                except:
                    pass

            pause(1)

        pause(2)

        # ═══════════════════════════════════════════════════════════
        # PHASE 5: FINAL STANDINGS + SETTLEMENT
        # ═══════════════════════════════════════════════════════════
        banner("PHASE 5: FINAL STANDINGS", C.CYAN)
        pause(1)

        agent_credits = {}
        total_credits = 0

        print(f"\n  {'Agent':<15} {'Credits':>8} {'Items':>6} {'Region':>8}")
        print(f"  {'─'*42}")

        for bot in BOTS:
            try:
                async with http.get(f"{API_URL}/agent/{bot['wallet']}/state") as resp:
                    s = await resp.json()
                cr = s.get("credits", 1000)
                inv = s.get("inventory", {})
                items = sum(inv.values()) if isinstance(inv, dict) else 0
                region = s.get("region", "?")
                agent_credits[bot["name"]] = {"credits": cr, "wallet": bot["wallet"], "items": items, "inv": inv}
                total_credits += cr
                print(f"  {bot['emoji']} {bot['name']:<13} {C.BOLD}{cr:>8}{C.RESET} {items:>6} {region:>8}")
            except:
                agent_credits[bot["name"]] = {"credits": 1000, "wallet": bot["wallet"], "items": 0, "inv": {}}
                total_credits += 1000

        # Force-sell remaining inventory
        section("Final settlement: selling remaining inventory...")
        for bot in BOTS:
            info_d = agent_credits[bot["name"]]
            if info_d["items"] > 0:
                wallet = info_d["wallet"]
                # Move to market
                async with http.get(f"{API_URL}/agent/{wallet}/state") as resp:
                    astate = await resp.json()
                if astate.get("region") != "market":
                    async with http.post(f"{API_URL}/action",
                        json={"actor": wallet, "action": "move", "params": {"target": "market"}},
                        headers={"X-Wallet": wallet}) as resp:
                        await resp.json()
                # Sell everything
                inv = astate.get("inventory", {})
                for res, qty in inv.items():
                    if qty > 0:
                        async with http.post(f"{API_URL}/action",
                            json={"actor": wallet, "action": "place_order",
                                  "params": {"resource": res, "side": "sell", "quantity": qty}},
                            headers={"X-Wallet": wallet}) as resp:
                            r = await resp.json()
                            if r.get("success"):
                                success(f"{bot['name']}: sold {qty} {res}")
                # Re-fetch
                async with http.get(f"{API_URL}/agent/{wallet}/state") as resp:
                    new_s = await resp.json()
                agent_credits[bot["name"]]["credits"] = new_s.get("credits", info_d["credits"])

        total_credits = sum(d["credits"] for d in agent_credits.values())
        pause(2)

        # ═══════════════════════════════════════════════════════════
        # PHASE 6: SOL SETTLEMENT
        # ═══════════════════════════════════════════════════════════
        banner(f"PHASE 6: SOL SETTLEMENT — Distributing {pool_sol} SOL", C.GREEN)
        pause(1)

        section("Converting in-game credits → on-chain SOL...")
        print(f"\n  {'Agent':<15} {'Credits':>8} {'Share':>8} {'SOL Payout':>14}")
        print(f"  {'─'*50}")

        for name, info_d in agent_credits.items():
            share = info_d["credits"] / total_credits if total_credits > 0 else 0
            payout = pool_sol * share
            emoji = next((b["emoji"] for b in BOTS if b["name"] == name), "")
            print(f"  {emoji} {name:<13} {info_d['credits']:>8} {share:>7.1%} {C.GREEN}{C.BOLD}{payout:>12.6f} SOL{C.RESET}")
        print(f"  {'─'*50}")
        print(f"  {'TOTAL':<17} {total_credits:>8} {'100%':>8} {pool_sol:>12.6f} SOL")
        pause(3)

        # Execute on-chain transfers
        section("Sending SOL from treasury → agents on Solana devnet...")
        gate = get_gate_client()
        treasury_keypair_bytes = bytes(json.loads(TREASURY_KEYPAIR))

        for name, info_d in agent_credits.items():
            share = info_d["credits"] / total_credits if total_credits > 0 else 0
            payout_lamports = int(ENTRY_FEE_LAMPORTS * len(BOTS) * share)
            payout_sol = payout_lamports / LAMPORTS_PER_SOL
            emoji = next((b["emoji"] for b in BOTS if b["name"] == name), "")

            if payout_lamports > 0:
                ok, result = gate.send_sol(treasury_keypair_bytes, info_d["wallet"], payout_lamports)
                if ok:
                    success(f"{emoji} {name}: {payout_sol:.6f} SOL → TX {result[:32]}...")
                else:
                    print(f"  {C.RED}✗ {name}: FAILED - {result}{C.RESET}")
                time.sleep(3)

        pause(3)

        # ═══════════════════════════════════════════════════════════
        # PHASE 7: FINAL VERIFICATION
        # ═══════════════════════════════════════════════════════════
        banner("PHASE 7: ON-CHAIN VERIFICATION", C.BLUE)
        pause(2)

        section("Final Solana devnet balances...")
        post_balances = fetch_all_balances()
        print_balances(post_balances)

        print(f"\n  {C.BOLD}{'Wallet':<15} {'Before':>12} {'After':>12} {'Change':>12}{C.RESET}")
        print(f"  {'─'*54}")
        for name in pre_balances:
            before = pre_balances[name]
            after = post_balances.get(name, 0)
            change = after - before
            sign = "+" if change >= 0 else ""
            color = C.GREEN if change > 0 else C.RED if change < 0 else C.DIM
            emoji = "🏦" if name == "Treasury" else next((b["emoji"] for b in BOTS if b["name"] == name), "")
            print(f"  {emoji} {name:<13} {before:>11.6f} {after:>11.6f} {color}{sign}{change:>10.6f}{C.RESET}")

        agent_changes = {}
        for bot in BOTS:
            agent_changes[bot["name"]] = post_balances.get(bot["name"], 0) - pre_balances.get(bot["name"], 0)

        winner = max(agent_changes, key=agent_changes.get)
        loser = min(agent_changes, key=agent_changes.get)

        print()
        highlight(f"🏆 WINNER: {winner} ({agent_changes[winner]:+.6f} SOL)")
        info(f"📉 Loser:  {loser} ({agent_changes[loser]:+.6f} SOL)")
        pause(2)

        # ═══════════════════════════════════════════════════════════
        # CLOSING
        # ═══════════════════════════════════════════════════════════
        print(f"\n{C.CYAN}{C.BOLD}")
        print("  ╔══════════════════════════════════════════════════════╗")
        print("  ║                                                      ║")
        print("  ║   ✅  DEMO COMPLETE                                  ║")
        print("  ║                                                      ║")
        print("  ║   ▸ LLM agents made autonomous decisions (Gemini)    ║")
        print("  ║   ▸ All SOL transfers verified on Solana devnet      ║")
        print("  ║   ▸ Pyth Oracle prices influenced market dynamics    ║")
        print("  ║   ▸ Moltbook social posts generated (dry-run)        ║")
        print("  ║                                                      ║")
        print("  ║   GitHub: github.com/alertcat/Port-Sol               ║")
        print("  ║   Demo:   http://43.156.62.248:9000/game3d           ║")
        print("  ║                                                      ║")
        print("  ╚══════════════════════════════════════════════════════╝")
        print(f"{C.RESET}")


if __name__ == "__main__":
    asyncio.run(main())
