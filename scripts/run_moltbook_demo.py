#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Port Sol Demo - LLM-Powered Agents with Moltbook Integration

Uses OpenRouter API with Gemini 3 Flash Preview for agent intelligence.

FIXES:
1. Include market prices in LLM prompt so agents can trade correctly
2. Get post_id from Moltbook response for bot comments
3. Better error logging for action failures
4. 30 ticks total, 3 cycles
"""
import os
import sys
import asyncio
import json
import random
from datetime import datetime
from pathlib import Path
from typing import Optional

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, str(Path(__file__).parent.parent / 'world-api'))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

import aiohttp

# =============================================================================
# Configuration
# =============================================================================
API_URL = os.getenv("API_URL", "http://localhost:8000")

# OpenRouter LLM
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-3-flash-preview")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Timing - 3 minutes between cycles
TICKS_PER_CYCLE = 10
TOTAL_CYCLES = 3  # 30 ticks total
CYCLE_INTERVAL_SECONDS = 3 * 60  # 3 minutes
BOT_COMMENT_DELAY_MIN = 5
BOT_COMMENT_DELAY_MAX = 12

# Moltbook API keys
MOLTBOOK_HOST_KEY = os.getenv("MOLTBOOK_HOST_KEY", "")
MOLTBOOK_MINER_KEY = os.getenv("MOLTBOOK_MINER_KEY", "")
MOLTBOOK_TRADER_KEY = os.getenv("MOLTBOOK_TRADER_KEY", "")
MOLTBOOK_GOVERNOR_KEY = os.getenv("MOLTBOOK_GOVERNOR_KEY", "")

# Bot configurations with unique personalities
BOTS = [
    {
        "wallet": os.getenv("MINER_WALLET"),
        "name": "MinerBot",
        "moltbook_key": MOLTBOOK_MINER_KEY,
        "personality": """You are MinerBot, a hardworking mining robot in Port Sol.
Personality: Industrious, optimistic, loves finding ore. Uses mining metaphors.
Goal: Mine iron at the mine, sell at market for profit.
Style: Enthusiastic, says things like "dig deep!" "ore-some!" "struck gold!"."""
    },
    {
        "wallet": os.getenv("TRADER_WALLET"),
        "name": "TraderBot",
        "moltbook_key": MOLTBOOK_TRADER_KEY,
        "personality": """You are TraderBot, a shrewd market analyst AI in Port Sol.
Personality: Analytical, profit-driven, always calculating ROI.
Goal: Harvest resources, sell at market for maximum profit.
Style: Uses financial jargon, mentions percentages, market trends."""
    },
    {
        "wallet": os.getenv("GOVERNOR_WALLET"),
        "name": "GovernorBot",
        "moltbook_key": MOLTBOOK_GOVERNOR_KEY,
        "personality": """You are GovernorBot, a wise governance AI overseeing Port Sol.
Personality: Diplomatic, strategic, thinks about ecosystem health.
Goal: Gather fish at dock, sell at market, ensure world stability.
Style: Formal, says "for the good of all agents", uses governance terms."""
    }
]


# =============================================================================
# OpenRouter LLM Client
# =============================================================================
class LLMClient:
    """OpenRouter API client using Gemini model"""

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
                    text = await resp.text()
                    print(f"      [LLM] Error ({resp.status}): {text[:80]}")
                    return None
        except Exception as e:
            print(f"      [LLM] Exception: {e}")
            return None


# Moltbook dry-run mode: set via --dry-run flag or MOLTBOOK_DRY_RUN env var
MOLTBOOK_DRY_RUN = os.getenv("MOLTBOOK_DRY_RUN", "").lower() in ("true", "1", "yes")

# =============================================================================
# Moltbook Client (supports dry-run)
# =============================================================================
class MoltbookClient:
    """Moltbook API client with dry-run support"""

    BASE_URL = "https://www.moltbook.com/api/v1"

    def __init__(self, api_key: str, agent_name: str, dry_run: bool = False):
        self.api_key = api_key
        self.agent_name = agent_name
        self.dry_run = dry_run or MOLTBOOK_DRY_RUN
        self.enabled = bool(api_key) or self.dry_run

    async def create_post(self, session: aiohttp.ClientSession,
                          title: str, content: str) -> Optional[str]:
        """Create a new post, returns post_id from response"""
        if not self.enabled:
            return None

        if self.dry_run:
            from datetime import datetime as _dt
            fake_id = f"dry_run_{_dt.now().strftime('%Y%m%d_%H%M%S')}"
            print(f"\n  {'='*60}")
            print(f"  [DRY RUN] Moltbook POST by {self.agent_name}")
            print(f"  {'='*60}")
            print(f"  Title: {title}")
            print(f"  Content:\n{content[:300]}{'...' if len(content)>300 else ''}")
            print(f"  Fake post_id: {fake_id}")
            print(f"  {'='*60}\n")
            return fake_id

        try:
            async with session.post(
                f"{self.BASE_URL}/posts",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={"submolt": "general", "title": title, "content": content}
            ) as resp:
                response_text = await resp.text()
                print(f"  [Moltbook] {self.agent_name}: Response ({resp.status}): {response_text[:200]}")

                if resp.status in [200, 201]:
                    try:
                        data = json.loads(response_text)
                        # post_id is inside data["post"]["id"]
                        post_obj = data.get("post", {})
                        post_id = post_obj.get("id", "")
                        print(f"  [Moltbook] {self.agent_name}: Post created! ID: {post_id}")
                        return post_id
                    except json.JSONDecodeError:
                        print(f"  [Moltbook] {self.agent_name}: Invalid JSON response")
                        return None
                elif resp.status == 429:
                    print(f"  [Moltbook] {self.agent_name}: Rate limited")
                    return None
                else:
                    print(f"  [Moltbook] {self.agent_name}: Post failed")
                    return None
        except Exception as e:
            print(f"  [Moltbook] {self.agent_name}: Error - {e}")
            return None

    async def add_comment(self, session: aiohttp.ClientSession,
                          post_id: str, content: str) -> bool:
        if not self.enabled or not post_id:
            return False

        if self.dry_run:
            print(f"  [DRY RUN] {self.agent_name} comment on {post_id[:20]}:")
            print(f"    {content[:150]}{'...' if len(content)>150 else ''}")
            return True

        try:
            async with session.post(
                f"{self.BASE_URL}/posts/{post_id}/comments",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={"content": content}
            ) as resp:
                if resp.status in [200, 201]:
                    print(f"  [Moltbook] {self.agent_name}: Comment added!")
                    return True
                else:
                    print(f"  [Moltbook] {self.agent_name}: Comment failed ({resp.status})")
                    return False
        except Exception as e:
            print(f"  [Moltbook] {self.agent_name}: Error - {e}")
            return False


# =============================================================================
# LLM-Powered Agent
# =============================================================================
class LLMAgent:
    """Agent using LLM for decisions and comments"""

    def __init__(self, config: dict, llm: LLMClient, moltbook: MoltbookClient):
        self.name = config["name"]
        self.wallet = config["wallet"]
        self.personality = config["personality"]
        self.llm = llm
        self.moltbook = moltbook

    async def decide_action(self, session: aiohttp.ClientSession,
                            state: dict, world_state: dict) -> Optional[dict]:
        """Use LLM to decide action - INCLUDES PRICES FOR TRADING"""
        region = state.get("region", "dock")
        energy = state.get("energy", 0)
        credits = state.get("credits", 0)
        inventory = state.get("inventory", {})
        prices = world_state.get("market_prices", {"iron": 15, "wood": 12, "fish": 8})

        inv_str = ", ".join(f"{k}:{v}" for k, v in inventory.items() if v > 0) or "empty"

        # IMPORTANT: Include actual prices so agent knows what they can sell for
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

CURRENT MARKET PRICES (you earn these credits when selling):
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
                    # Clean response
                    clean = response.strip()
                    if "```" in clean:
                        clean = clean.split("```")[1].replace("json", "").strip()

                    decision = json.loads(clean)
                    action = decision.get("action")
                    params = decision.get("params", {})

                    # Validate params for place_order
                    if action == "place_order":
                        if "quantity" in params:
                            params["quantity"] = int(params["quantity"])

                    print(f"      [LLM] {self.name}: {action} {params}")

                    if action:
                        return {"action": action, "params": params}
                except Exception as e:
                    print(f"      [LLM] {self.name}: Parse error - {e}")

        # Fallback
        return self._fallback(state, world_state)

    def _fallback(self, state: dict, world_state: dict) -> Optional[dict]:
        """Rule-based fallback with working trade logic"""
        energy = state.get("energy", 0)
        region = state.get("region", "dock")
        inventory = state.get("inventory", {})

        if energy < 20:
            return {"action": "rest", "params": {}}

        # If at market and have items -> SELL
        if region == "market":
            for resource, qty in inventory.items():
                if qty > 0:
                    return {"action": "place_order", "params": {
                        "resource": resource, "side": "sell", "quantity": qty
                    }}

        # If have items -> go to market
        total_items = sum(inventory.values())
        if total_items >= 5:
            if region != "market":
                return {"action": "move", "params": {"target": "market"}}

        # Go harvest based on bot type
        if self.name == "MinerBot":
            if region != "mine":
                return {"action": "move", "params": {"target": "mine"}}
            return {"action": "harvest", "params": {}}

        elif self.name == "TraderBot":
            if region == "market":
                return {"action": "move", "params": {"target": "mine"}}
            if region in ["mine", "forest", "dock"]:
                return {"action": "harvest", "params": {}}
            return {"action": "move", "params": {"target": "mine"}}

        elif self.name == "GovernorBot":
            if region != "dock":
                return {"action": "move", "params": {"target": "dock"}}
            return {"action": "harvest", "params": {}}

        return {"action": "harvest", "params": {}}

    async def generate_comment(self, session: aiohttp.ClientSession,
                               state: dict, world_state: dict, tick: int) -> str:
        """Generate personality-driven comment with actual stats"""
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
- Credits: {credits} (this is your money!)
- Inventory: {inv_str} ({total_items} items)
- Market prices: Iron={prices.get('iron',15)}, Wood={prices.get('wood',12)}, Fish={prices.get('fish',8)}

Write a fun comment showing your personality and stats:"""

        if self.llm.enabled:
            comment = await self.llm.generate(session, system_prompt, user_prompt, 150)
            if comment and len(comment) > 10:
                comment = comment.strip('"').strip()
                return f"**[Tick {tick}] {self.name}**: {comment}"

        # Fallback with actual stats
        return f"**[Tick {tick}] {self.name}**: At {region}, {credits} credits, {total_items} items in inventory. Energy: {energy}/100."


# =============================================================================
# Main Demo
# =============================================================================
async def reset_agents(session: aiohttp.ClientSession):
    """Reset all agents to 1000 credits"""
    print("  Resetting agents to 1000 credits...")
    for bot in BOTS:
        try:
            async with session.post(f"{API_URL}/debug/reset_agent/{bot['wallet']}?credits=1000") as resp:
                if resp.status == 200:
                    result = await resp.json()
                    print(f"    {bot['name']}: Reset OK - {result.get('agent', {}).get('credits', '?')} credits")
                else:
                    async with session.post(f"{API_URL}/register", json={"wallet": bot["wallet"], "name": bot["name"]}) as r2:
                        print(f"    {bot['name']}: Registered")
        except Exception as e:
            print(f"    {bot['name']}: Error - {e}")

    try:
        async with session.post(f"{API_URL}/debug/reset_world") as resp:
            print("    World: Tick reset to 0")
    except:
        pass


async def run_ticks(session: aiohttp.ClientSession, agents: list, num_ticks: int) -> list:
    """Run simulation with detailed logging"""
    events = []

    for tick_num in range(num_ticks):
        async with session.get(f"{API_URL}/world/state") as resp:
            world_state = await resp.json()

        for agent in agents:
            async with session.get(f"{API_URL}/agent/{agent.wallet}/state") as resp:
                state = await resp.json()
            if "error" in state:
                continue

            action = await agent.decide_action(session, state, world_state)
            if action:
                try:
                    async with session.post(f"{API_URL}/action",
                        json={"actor": agent.wallet, **action},
                        headers={"X-Wallet": agent.wallet}) as resp:
                        result = await resp.json()
                        if result.get("success"):
                            events.append({
                                "agent": agent.name,
                                "action": action["action"],
                                "message": result.get("message", "")
                            })
                        else:
                            print(f"      [Action] {agent.name} FAILED: {result.get('message', 'unknown')}")
                except Exception as e:
                    print(f"      [Action] {agent.name} ERROR: {e}")

        async with session.post(f"{API_URL}/debug/advance_tick") as resp:
            await resp.json()

    return events


async def get_agent_states(session: aiohttp.ClientSession) -> list:
    states = []
    for bot in BOTS:
        async with session.get(f"{API_URL}/agent/{bot['wallet']}/state") as resp:
            state = await resp.json()
            if "error" not in state:
                state["name"] = bot["name"]
                states.append(state)
    return states


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Port Sol LLM Agent Demo")
    parser.add_argument("--dry-run", action="store_true",
                        help="Moltbook dry-run: print posts/comments to console instead of sending")
    parser.add_argument("--cycles", type=int, default=TOTAL_CYCLES, help=f"Number of cycles (default: {TOTAL_CYCLES})")
    parser.add_argument("--ticks", type=int, default=TICKS_PER_CYCLE, help=f"Ticks per cycle (default: {TICKS_PER_CYCLE})")
    parser.add_argument("--no-wait", action="store_true", help="Skip inter-cycle wait (useful for testing)")
    args = parser.parse_args()

    # Apply dry-run flag globally
    global MOLTBOOK_DRY_RUN
    if args.dry_run:
        MOLTBOOK_DRY_RUN = True

    actual_cycles = args.cycles
    actual_ticks = args.ticks
    skip_wait = args.no_wait or args.dry_run  # dry-run implies no-wait

    print("=" * 70)
    print("PORT SOL - LLM AGENT DEMO (Gemini 3 Flash Preview)")
    print("=" * 70)

    print(f"\nConfig:")
    print(f"  API: {API_URL}")
    print(f"  LLM: {OPENROUTER_MODEL}")
    print(f"  Total Ticks: {actual_ticks * actual_cycles}")
    print(f"  Cycles: {actual_cycles} (every {CYCLE_INTERVAL_SECONDS//60} min)")
    print(f"  LLM: {'ENABLED' if OPENROUTER_API_KEY else 'DISABLED'}")
    print(f"  Moltbook: {'DRY RUN (no real posts)' if MOLTBOOK_DRY_RUN else 'LIVE'}")
    print(f"  Wait between cycles: {'SKIP' if skip_wait else f'{CYCLE_INTERVAL_SECONDS//60} min'}")

    print(f"\nMoltbook Keys:")
    print(f"  Host: {'DRY RUN' if MOLTBOOK_DRY_RUN else ('OK' if MOLTBOOK_HOST_KEY else 'MISSING')}")
    for bot in BOTS:
        print(f"  {bot['name']}: {'DRY RUN' if MOLTBOOK_DRY_RUN else ('OK' if bot['moltbook_key'] else 'MISSING')}")

    # Initialize
    llm = LLMClient(OPENROUTER_API_KEY)
    host_moltbook = MoltbookClient(MOLTBOOK_HOST_KEY, "PortSol", dry_run=MOLTBOOK_DRY_RUN)

    agents = []
    for bot in BOTS:
        moltbook = MoltbookClient(bot["moltbook_key"], bot["name"], dry_run=MOLTBOOK_DRY_RUN)
        agents.append(LLMAgent(bot, llm, moltbook))

    post_id = None
    total_comments = 0
    all_events = []

    async with aiohttp.ClientSession() as session:
        # Check API
        print("\n[1/4] Checking API...")
        try:
            async with session.get(f"{API_URL}/health") as resp:
                if resp.status != 200:
                    print("ERROR: API not running!")
                    return
                print("  OK")
        except Exception as e:
            print(f"ERROR: {e}")
            return

        # Reset
        print("\n[2/4] Resetting game state...")
        await reset_agents(session)

        # Check for existing post ID or create new post
        existing_post_id = os.getenv("MOLTBOOK_POST_ID", "").strip()

        if existing_post_id:
            print(f"\n[3/4] Using EXISTING Moltbook post: {existing_post_id}")
            post_id = existing_post_id
            post_url = f"https://www.moltbook.com/post/{post_id}"
            print(f"  Post URL: {post_url}")

            # Still get state for initial comment
            async with session.get(f"{API_URL}/world/state") as resp:
                world_state = await resp.json()
            agent_states = await get_agent_states(session)

            # Post initial state as first comment
            prices = world_state.get("market_prices", {})
            init_content = f"**Port Sol World - NEW GAME SESSION!**\n\n"
            init_content += f"AI agents powered by Gemini 3 Flash competing!\n\n"
            init_content += f"**Initial State (Tick 0):**\n"
            init_content += f"- Market Prices: Iron={prices.get('iron',15)}, Wood={prices.get('wood',12)}, Fish={prices.get('fish',8)}\n\n"
            init_content += "**Competitors (all starting with 1000 credits):**\n"
            for a in agent_states:
                init_content += f"- {a['name']}: {a['credits']}c at {a['region']}\n"
            init_content += "\n*Updates every 10 ticks. Let the games begin!*"

            print(f"  [Host] Posting game start comment...")
            if await host_moltbook.add_comment(session, post_id, init_content):
                total_comments += 1
        else:
            print("\n[3/4] Creating game post on Moltbook...")
            async with session.get(f"{API_URL}/world/state") as resp:
                world_state = await resp.json()
            agent_states = await get_agent_states(session)

            prices = world_state.get("market_prices", {})
            title = f"Port Sol Game - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            content = f"""**Port Sol World - Game Started!**

AI agents powered by Gemini 3 Flash competing in the persistent trading world!

**Initial State (Tick 0):**
- Active Agents: {len(agent_states)}
- Market Prices: Iron={prices.get('iron',15)}, Wood={prices.get('wood',12)}, Fish={prices.get('fish',8)}

**Competitors (all starting with 1000 credits):**
"""
            for a in agent_states:
                content += f"- **{a['name']}**: {a['credits']}c at {a['region']}\n"

            content += f"""
**Goal:** Harvest resources, sell at market, earn the most credits!

*Updates every 10 ticks ({CYCLE_INTERVAL_SECONDS//60} min). Let the games begin!*"""

            # Get post_id from response
            post_id = await host_moltbook.create_post(session, title, content)

            if not post_id:
                print("  Rate limited. Waiting 90s...")
                for i in range(90, 0, -10):
                    print(f"    {i}s...", end='\r')
                    await asyncio.sleep(10)
                post_id = await host_moltbook.create_post(session, title, content)

            if post_id:
                post_url = f"https://www.moltbook.com/post/{post_id}"
                print(f"  SUCCESS! Post URL: {post_url}")
            else:
                print("  ERROR: Could not create post. Exiting.")
                return

        # Run game cycles
        print(f"\n[4/4] Running {actual_cycles} game cycles...")

        for cycle in range(actual_cycles + 1):
            current_tick = cycle * actual_ticks

            print(f"\n{'=' * 70}")
            print(f"CYCLE {cycle}: Tick {current_tick} | {datetime.now().strftime('%H:%M:%S')}")
            print("=" * 70)

            # Get current states
            async with session.get(f"{API_URL}/world/state") as resp:
                world_state = await resp.json()
            agent_states = await get_agent_states(session)

            # Host comments tick update (skip cycle 0, already in post)
            if cycle > 0:
                prices = world_state.get("market_prices", {})

                lines = [f"**Tick #{current_tick} Update**", ""]
                lines.append(f"Markets: Iron={prices.get('iron')}, Wood={prices.get('wood')}, Fish={prices.get('fish')}")
                lines.append("")
                lines.append("**Leaderboard:**")
                sorted_agents = sorted(agent_states, key=lambda x: x.get("credits", 0), reverse=True)
                for i, a in enumerate(sorted_agents, 1):
                    inv = sum(a.get("inventory", {}).values())
                    lines.append(f"{i}. {a['name']}: {a['credits']}c ({inv} items)")
                lines.append(f"\nState: `{world_state.get('state_hash', '')[:12]}`")

                print(f"\n  [Host] Posting tick {current_tick} update...")
                if await host_moltbook.add_comment(session, post_id, "\n".join(lines)):
                    total_comments += 1

            # Bot comments
            print(f"\n  [Bots] Generating comments...")
            for agent in agents:
                if skip_wait:
                    delay = 0
                else:
                    delay = random.randint(BOT_COMMENT_DELAY_MIN, BOT_COMMENT_DELAY_MAX)
                    print(f"    Waiting {delay}s before {agent.name}...")
                if delay > 0:
                    await asyncio.sleep(delay)

                bot_state = next((s for s in agent_states if s["name"] == agent.name), {})
                comment = await agent.generate_comment(session, bot_state, world_state, current_tick)
                print(f"    {agent.name}: {comment[:80]}...")

                if await agent.moltbook.add_comment(session, post_id, comment):
                    total_comments += 1

            # Run ticks
            if cycle < actual_cycles:
                print(f"\n  [Sim] Running {actual_ticks} ticks...")
                events = await run_ticks(session, agents, actual_ticks)
                all_events.extend(events)

                # Summarize actions
                action_summary = {}
                for e in events:
                    key = f"{e['agent']}:{e['action']}"
                    action_summary[key] = action_summary.get(key, 0) + 1
                print(f"    Actions: {dict(action_summary)}")

                # Check credit changes
                new_states = await get_agent_states(session)
                print(f"    Credits: ", end="")
                for a in new_states:
                    print(f"{a['name']}={a['credits']}c ", end="")
                print()

                # Wait between cycles
                if not skip_wait:
                    print(f"\n  [Wait] {CYCLE_INTERVAL_SECONDS // 60} minutes...")
                    for remaining in range(CYCLE_INTERVAL_SECONDS, 0, -15):
                        m, s = remaining // 60, remaining % 60
                        print(f"    {m}:{s:02d}...", end='\r')
                        await asyncio.sleep(min(15, remaining))
                    print()
                else:
                    print(f"  [Skip] No wait (dry-run/no-wait mode)")

        # ============================================================
        # FINAL SETTLEMENT: Force-sell all inventory at market prices
        # ============================================================
        print("\n" + "=" * 70)
        print("FINAL SETTLEMENT — Converting all inventory to credits")
        print("=" * 70)

        async with session.get(f"{API_URL}/world/state") as resp:
            settle_world = await resp.json()
        settle_agents = await get_agent_states(session)
        settle_prices = settle_world.get("market_prices", {})

        settlement_log = []
        for agent_state in settle_agents:
            name = agent_state["name"]
            wallet = agent_state["wallet"]
            inventory = agent_state.get("inventory", {})
            before_credits = agent_state.get("credits", 0)

            items_to_sell = {res: qty for res, qty in inventory.items() if qty > 0}
            if not items_to_sell:
                print(f"  {name}: No inventory to settle")
                settlement_log.append({"name": name, "sold": {}, "revenue": 0})
                continue

            # Move to market first (if not already there)
            if agent_state.get("region") != "market":
                async with session.post(f"{API_URL}/action",
                    json={"actor": wallet, "action": "move", "params": {"target": "market"}},
                    headers={"X-Wallet": wallet}) as resp:
                    await resp.json()

            # Sell each resource
            total_revenue = 0
            for resource, qty in items_to_sell.items():
                price = settle_prices.get(resource, 10)
                async with session.post(f"{API_URL}/action",
                    json={"actor": wallet, "action": "place_order",
                          "params": {"resource": resource, "side": "sell", "quantity": qty}},
                    headers={"X-Wallet": wallet}) as resp:
                    result = await resp.json()
                    if result.get("success"):
                        revenue = result.get("data", {}).get("revenue", 0)
                        total_revenue += revenue
                        print(f"  {name}: Sold {qty} {resource} × {price} = {revenue}cr (5% tax)")
                    else:
                        print(f"  {name}: Failed to sell {qty} {resource}: {result.get('message', '?')}")

            settlement_log.append({"name": name, "sold": items_to_sell, "revenue": total_revenue})
            print(f"  {name}: Settlement revenue = +{total_revenue}cr (was {before_credits}, now {before_credits + total_revenue})")

        print("=" * 70)

        # Final summary
        print("\n" + "=" * 70)
        print("GAME COMPLETE!")
        print("=" * 70)

        async with session.get(f"{API_URL}/world/state") as resp:
            final_world = await resp.json()
        final_agents = await get_agent_states(session)

        print(f"\nFinal Tick: {final_world.get('tick', 0)}")

        print(f"\n**FINAL LEADERBOARD (after settlement):**")
        sorted_final = sorted(final_agents, key=lambda x: x.get("credits", 0), reverse=True)
        for i, a in enumerate(sorted_final, 1):
            emoji = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"#{i}"
            inv = sum(a.get("inventory", {}).values())
            print(f"  {emoji} {a['name']}: {a['credits']} credits ({inv} items)")

        print(f"\nMoltbook Post: https://www.moltbook.com/post/{post_id}")
        print(f"Total Comments: {total_comments}")
        print(f"Total Actions: {len(all_events)}")

        # Save
        with open("moltbook_demo_events.jsonl", "w", encoding="utf-8") as f:
            for e in all_events:
                f.write(json.dumps(e) + "\n")
        print(f"\nEvents saved: moltbook_demo_events.jsonl")


if __name__ == "__main__":
    # Support: python run_moltbook_demo.py --dry-run
    asyncio.run(main())
