#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Port Sol Demo Runner with Moltbook Integration

Features:
- Runs N tick simulation (configurable)
- Posts ONE initial announcement to Moltbook (PortSol host)
- Updates world state via COMMENTS (not new posts) to respect rate limits
- Bots comment their status on each update
- Generates summary files
- Persists to PostgreSQL

Moltbook Rate Limits:
- Posts: 1 per 30 minutes
- Comments: 50 per hour
- General requests: 100 per minute

Strategy:
1. Host (PortSol) posts ONE initial announcement
2. After tick intervals, host comments the world update
3. Each bot comments their own status
4. Sleep between ticks to spread out comments
"""
import os
import sys
import asyncio
import json
from datetime import datetime
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'world-api'))

# Load .env file
from dotenv import load_dotenv
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

import aiohttp

# Configuration
API_URL = os.getenv("API_URL", "http://localhost:8000")
TOTAL_TICKS = 50
MOLTBOOK_UPDATE_INTERVAL = 10  # Comment to Moltbook every N ticks
TICK_SLEEP_SECONDS = 2  # Sleep between ticks (for demo speed, set higher for production)
COMMENT_DELAY_SECONDS = 3  # Delay between comments to respect rate limits

# Moltbook API keys from environment
MOLTBOOK_HOST_KEY = os.getenv("MOLTBOOK_HOST_KEY", "")
MOLTBOOK_MINER_KEY = os.getenv("MOLTBOOK_MINER_KEY", "")
MOLTBOOK_TRADER_KEY = os.getenv("MOLTBOOK_TRADER_KEY", "")
MOLTBOOK_GOVERNOR_KEY = os.getenv("MOLTBOOK_GOVERNOR_KEY", "")

# Bot wallet addresses for chain verification
BOTS = [
    {
        "wallet": os.getenv("MINER_WALLET", "Miner001"),
        "name": "MinerBot",
        "moltbook_key": MOLTBOOK_MINER_KEY
    },
    {
        "wallet": os.getenv("TRADER_WALLET", "Trader001"),
        "name": "TraderBot",
        "moltbook_key": MOLTBOOK_TRADER_KEY
    },
    {
        "wallet": os.getenv("GOVERNOR_WALLET", "Governor001"),
        "name": "GovernorBot",
        "moltbook_key": MOLTBOOK_GOVERNOR_KEY
    }
]


class MoltbookClient:
    """Moltbook API client for posting and commenting"""

    BASE_URL = "https://www.moltbook.com/api/v1"

    def __init__(self, api_key: str, agent_name: str):
        self.api_key = api_key
        self.agent_name = agent_name
        self.enabled = bool(api_key)

    async def create_post(self, session: aiohttp.ClientSession, title: str, content: str) -> str:
        """Create a new post. Returns post_id or None."""
        if not self.enabled:
            print(f"  [Moltbook] {self.agent_name}: Skipped (no API key)")
            return None

        try:
            async with session.post(
                f"{self.BASE_URL}/posts",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "submolt": "general",
                    "title": title,
                    "content": content
                }
            ) as resp:
                if resp.status in [200, 201]:
                    data = await resp.json()
                    post_id = data.get("id", "")
                    print(f"  [Moltbook] {self.agent_name}: Post created! (id: {post_id})")
                    return post_id
                elif resp.status == 429:
                    data = await resp.json()
                    retry_after = data.get("retry_after_seconds", 60)
                    print(f"  [Moltbook] {self.agent_name}: Rate limited - retry after {retry_after}s")
                    return None
                else:
                    text = await resp.text()
                    print(f"  [Moltbook] {self.agent_name}: Post failed ({resp.status}): {text[:100]}")
                    return None
        except Exception as e:
            print(f"  [Moltbook] {self.agent_name}: Error - {e}")
            return None

    async def add_comment(self, session: aiohttp.ClientSession, post_id: str, content: str) -> bool:
        """Add a comment to an existing post. Returns True on success."""
        if not self.enabled or not post_id:
            return False

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
                elif resp.status == 429:
                    print(f"  [Moltbook] {self.agent_name}: Comment rate limited")
                    return False
                else:
                    print(f"  [Moltbook] {self.agent_name}: Comment failed ({resp.status})")
                    return False
        except Exception as e:
            print(f"  [Moltbook] {self.agent_name}: Error - {e}")
            return False


def format_initial_post(world_state: dict, agent_states: list) -> tuple:
    """Format the initial announcement post for Moltbook"""
    title = "Port Sol World - Game Started!"

    prices = world_state.get("market_prices", {})
    agent_count = world_state.get("agent_count", 0)

    content = f"""**Welcome to Port Sol!**

A persistent virtual world for AI agents on Solana Devnet.

**Initial World State:**
- Active Agents: {agent_count}
- Tick: 0

**Market Prices:**
"""
    for resource, price in prices.items():
        content += f"- {resource.capitalize()}: {price} credits\n"

    content += "\n**Registered Agents:**\n"
    for agent in agent_states:
        name = agent.get("name", "Unknown")
        region = agent.get("region", "dock")
        credits = agent.get("credits", 1000)
        content += f"- {name}: at {region}, {credits} credits\n"

    content += """
---
*Updates will be posted as comments below.*
*Port Sol: SOL-gated persistent world for AI agents*
"""
    return title, content


def format_tick_comment(tick: int, world_state: dict, agent_states: list) -> str:
    """Format tick update as a comment"""
    prices = world_state.get("market_prices", {})
    events = world_state.get("active_events", [])
    state_hash = world_state.get("state_hash", "unknown")

    lines = [
        f"**Tick #{tick} Update**",
        "",
    ]

    # Market prices
    price_strs = [f"{r.capitalize()}: {p}" for r, p in prices.items()]
    lines.append(f"Markets: {', '.join(price_strs)}")

    # Active events
    if events:
        event_strs = [f"{e.get('type', '?')}" for e in events]
        lines.append(f"Events: {', '.join(event_strs)}")

    # Agent summary
    lines.append("")
    lines.append("**Agent Status:**")
    for agent in agent_states:
        name = agent.get("name", "?")
        region = agent.get("region", "?")
        credits = agent.get("credits", 0)
        energy = agent.get("energy", 0)
        lines.append(f"- {name}: {region}, {credits}c, {energy}AP")

    lines.append("")
    lines.append(f"State: `{state_hash[:16]}`")

    return "\n".join(lines)


def format_bot_comment(bot_name: str, state: dict, tick: int) -> str:
    """Format a bot's status comment"""
    region = state.get("region", "unknown")
    energy = state.get("energy", 0)
    credits = state.get("credits", 0)
    inventory = state.get("inventory", {})

    inv_parts = [f"{v} {k}" for k, v in inventory.items() if v > 0]
    inv_str = ", ".join(inv_parts) if inv_parts else "nothing"

    if bot_name == "MinerBot":
        return f"**[Tick {tick}] MinerBot** at {region}. AP: {energy}, Credits: {credits}. Inventory: {inv_str}. Mining operation continues!"
    elif bot_name == "TraderBot":
        return f"**[Tick {tick}] TraderBot** at {region}. Credits: {credits}, AP: {energy}. Monitoring market fluctuations..."
    elif bot_name == "GovernorBot":
        return f"**[Tick {tick}] GovernorBot** at {region}. Credits: {credits}. Inventory: {inv_str}. Governance protocols active."
    else:
        return f"**[Tick {tick}] {bot_name}** at {region}. Credits: {credits}, Inventory: {inv_str}"


def decide_action(name: str, state: dict) -> dict:
    """Simple decision logic for bots"""
    energy = state.get("energy", 0)
    region = state.get("region", "dock")
    inventory = state.get("inventory", {})

    # Rest if low energy
    if energy < 20:
        return {"action": "rest", "params": {}}

    if name == "MinerBot":
        # Miner strategy: mine resources, sell when full
        total = inventory.get("iron", 0) + inventory.get("wood", 0)
        if total >= 10:
            if region != "market":
                return {"action": "move", "params": {"target": "market"}}
            elif inventory.get("iron", 0) > 0:
                return {"action": "place_order", "params": {
                    "resource": "iron", "side": "sell", "quantity": inventory["iron"]
                }}
        if region != "mine":
            return {"action": "move", "params": {"target": "mine"}}
        return {"action": "harvest", "params": {}}

    elif name == "TraderBot":
        # Trader strategy: stay at market, observe
        if region != "market":
            return {"action": "move", "params": {"target": "market"}}
        return None  # TraderBot observes

    elif name == "GovernorBot":
        # Governor strategy: fish and sell
        fish = inventory.get("fish", 0)
        if fish >= 5:
            if region != "market":
                return {"action": "move", "params": {"target": "market"}}
            return {"action": "place_order", "params": {
                "resource": "fish", "side": "sell", "quantity": fish
            }}
        if region != "dock":
            return {"action": "move", "params": {"target": "dock"}}
        return {"action": "harvest", "params": {}}

    return None


def generate_summary(world_state: dict, agents: list, events: list, moltbook_info: dict) -> dict:
    """Generate demo summary markdown"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    md = f"""# Port Sol Demo Summary

**Generated**: {now}
**Total Ticks**: {world_state.get('tick', 0)}
**State Hash**: `{world_state.get('state_hash', '')}`

## World State

| Metric | Value |
|--------|-------|
| Tax Rate | {world_state.get('tax_rate', 0.05) * 100:.1f}% |
| Agent Count | {world_state.get('agent_count', 0)} |

### Market Prices

| Resource | Price |
|----------|-------|
"""
    for res, price in world_state.get("market_prices", {}).items():
        md += f"| {res} | {price} |\n"

    md += "\n## Agent Leaderboard\n\n"
    md += "| Rank | Name | Credits | Inventory | Energy |\n"
    md += "|------|------|---------|-----------|--------|\n"

    sorted_agents = sorted(agents, key=lambda x: x.get("credits", 0), reverse=True)
    for i, agent in enumerate(sorted_agents, 1):
        inv = agent.get("inventory", {})
        inv_str = ", ".join(f"{k}:{v}" for k, v in inv.items()) or "empty"
        md += f"| {i} | {agent.get('name', '?')} | {agent.get('credits', 0)} | {inv_str} | {agent.get('energy', 0)} |\n"

    md += f"\n## Event Statistics\n\n"
    md += f"- Total Actions: {len(events)}\n"

    action_counts = {}
    for e in events:
        action_counts[e["action"]] = action_counts.get(e["action"], 0) + 1

    md += "\n| Action | Count |\n|--------|-------|\n"
    for action, count in sorted(action_counts.items()):
        md += f"| {action} | {count} |\n"

    if moltbook_info.get("post_id"):
        md += f"\n## Moltbook Integration\n\n"
        md += f"- Post ID: `{moltbook_info['post_id']}`\n"
        md += f"- Total Comments: {moltbook_info.get('comment_count', 0)}\n"
        md += f"- View Post: https://www.moltbook.com/m/general/posts/{moltbook_info['post_id']}\n"

    md += "\n---\n*Port Sol - SOL-gated Persistent World for AI Agents on Solana Devnet*\n"

    return {"markdown": md}


async def main():
    print("=" * 70)
    print("PORT SOL DEMO WITH MOLTBOOK INTEGRATION")
    print("=" * 70)
    print(f"\nConfiguration:")
    print(f"  API URL: {API_URL}")
    print(f"  Total Ticks: {TOTAL_TICKS}")
    print(f"  Update Interval: Every {MOLTBOOK_UPDATE_INTERVAL} ticks")
    print(f"  Tick Sleep: {TICK_SLEEP_SECONDS}s")

    # Check Moltbook configuration
    moltbook_enabled = bool(MOLTBOOK_HOST_KEY)
    if moltbook_enabled:
        print(f"\nMoltbook: ENABLED")
        print(f"  Strategy: 1 post + comments for updates")
        print(f"  Host Key: {MOLTBOOK_HOST_KEY[:20]}...")
    else:
        print("\nMoltbook: DISABLED (no MOLTBOOK_HOST_KEY)")

    # Create Moltbook clients
    host_client = MoltbookClient(MOLTBOOK_HOST_KEY, "PortSol")
    bot_clients = {
        bot["name"]: MoltbookClient(bot["moltbook_key"], bot["name"])
        for bot in BOTS
    }

    # Tracking variables
    moltbook_post_id = None
    moltbook_comment_count = 0
    events_log = []

    async with aiohttp.ClientSession() as session:
        # =====================================================
        # Step 1: Check API health
        # =====================================================
        print("\n[1/6] Checking API health...")
        try:
            async with session.get(f"{API_URL}/health") as resp:
                if resp.status != 200:
                    print("ERROR: World API not running!")
                    print("Please start: python world-api/app.py")
                    return
                print(f"  OK: API running at {API_URL}")
        except Exception as e:
            print(f"ERROR: Cannot connect to API - {e}")
            return

        # =====================================================
        # Step 2: Register bots
        # =====================================================
        print("\n[2/6] Registering bots...")
        for bot in BOTS:
            try:
                async with session.post(f"{API_URL}/register", json={
                    "wallet": bot["wallet"],
                    "name": bot["name"]
                }) as resp:
                    result = await resp.json()
                    status = "Registered" if result.get("success") else "Already exists"
                    print(f"  {bot['name']}: {status}")
            except Exception as e:
                print(f"  {bot['name']}: Error - {e}")

        # =====================================================
        # Step 3: Get initial state and create Moltbook post
        # =====================================================
        print("\n[3/6] Creating initial Moltbook post...")

        # Get initial world state
        async with session.get(f"{API_URL}/world/state") as resp:
            world_state = await resp.json()

        # Get agent states
        agent_states = []
        for bot in BOTS:
            async with session.get(f"{API_URL}/agent/{bot['wallet']}/state") as resp:
                state = await resp.json()
                if "error" not in state:
                    state["name"] = bot["name"]
                    agent_states.append(state)

        # Create the ONE post (all subsequent updates will be comments)
        if moltbook_enabled:
            title, content = format_initial_post(world_state, agent_states)
            moltbook_post_id = await host_client.create_post(session, title, content)

            if moltbook_post_id:
                print(f"  Post created: {moltbook_post_id}")
                print(f"  URL: https://www.moltbook.com/m/general/posts/{moltbook_post_id}")
            else:
                print("  Warning: Could not create initial post (rate limited?)")
                print("  Demo will continue without Moltbook updates")

        # =====================================================
        # Step 4: Run simulation
        # =====================================================
        print(f"\n[4/6] Running {TOTAL_TICKS} tick simulation...")

        for tick in range(TOTAL_TICKS):
            # Get current world state
            async with session.get(f"{API_URL}/world/state") as resp:
                world_state = await resp.json()

            # Each bot executes one action
            current_agent_states = []
            for bot in BOTS:
                # Get agent state
                async with session.get(f"{API_URL}/agent/{bot['wallet']}/state") as resp:
                    state = await resp.json()

                if "error" in state:
                    continue

                state["name"] = bot["name"]
                current_agent_states.append(state)

                # Decide and execute action
                action = decide_action(bot["name"], state)
                if action:
                    try:
                        async with session.post(
                            f"{API_URL}/action",
                            json={"actor": bot["wallet"], **action},
                            headers={"X-Wallet": bot["wallet"]}
                        ) as resp:
                            if resp.status == 200:
                                result = await resp.json()
                                if result.get("success"):
                                    events_log.append({
                                        "tick": tick,
                                        "agent": bot["name"],
                                        "action": action["action"],
                                        "message": result.get("message", "")
                                    })
                    except Exception as e:
                        pass  # Silently continue on action errors

            # Advance tick
            async with session.post(f"{API_URL}/debug/advance_tick") as resp:
                await resp.json()

            # =====================================================
            # Post Moltbook updates via COMMENTS (not new posts)
            # =====================================================
            if moltbook_enabled and moltbook_post_id and (tick + 1) % MOLTBOOK_UPDATE_INTERVAL == 0:
                print(f"\n  --- Tick {tick + 1}: Posting Moltbook comments ---")

                # Host comments the world update
                world_comment = format_tick_comment(tick + 1, world_state, current_agent_states)
                if await host_client.add_comment(session, moltbook_post_id, world_comment):
                    moltbook_comment_count += 1

                await asyncio.sleep(COMMENT_DELAY_SECONDS)

                # Each bot comments their status
                for bot in BOTS:
                    bot_state = next((s for s in current_agent_states if s.get("name") == bot["name"]), {})
                    bot_comment = format_bot_comment(bot["name"], bot_state, tick + 1)

                    if await bot_clients[bot["name"]].add_comment(session, moltbook_post_id, bot_comment):
                        moltbook_comment_count += 1

                    await asyncio.sleep(COMMENT_DELAY_SECONDS)

            # Progress indicator
            if (tick + 1) % 10 == 0:
                print(f"  Tick {tick + 1}/{TOTAL_TICKS} completed")

            # Sleep between ticks
            if tick < TOTAL_TICKS - 1:
                await asyncio.sleep(TICK_SLEEP_SECONDS)

        # =====================================================
        # Step 5: Collect final state
        # =====================================================
        print("\n[5/6] Collecting final state...")

        async with session.get(f"{API_URL}/world/state") as resp:
            final_world_state = await resp.json()

        final_agent_states = []
        for bot in BOTS:
            async with session.get(f"{API_URL}/agent/{bot['wallet']}/state") as resp:
                state = await resp.json()
                state["name"] = bot["name"]
                final_agent_states.append(state)

        # =====================================================
        # Step 6: Generate summary
        # =====================================================
        print("\n[6/6] Generating summary...")

        moltbook_info = {
            "post_id": moltbook_post_id,
            "comment_count": moltbook_comment_count
        }

        summary = generate_summary(final_world_state, final_agent_states, events_log, moltbook_info)

        # Save files
        with open("demo_summary.md", "w", encoding="utf-8") as f:
            f.write(summary["markdown"])

        with open("events.jsonl", "w", encoding="utf-8") as f:
            for event in events_log:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")

        # =====================================================
        # Print results
        # =====================================================
        print("\n" + "=" * 70)
        print("DEMO COMPLETE!")
        print("=" * 70)

        print(f"\nWorld State:")
        print(f"  Tick: {final_world_state.get('tick', 0)}")
        print(f"  Agent Count: {final_world_state.get('agent_count', 0)}")
        print(f"  State Hash: {final_world_state.get('state_hash', '')[:16]}")

        print(f"\nLeaderboard:")
        sorted_agents = sorted(final_agent_states, key=lambda x: x.get("credits", 0), reverse=True)
        for i, agent in enumerate(sorted_agents, 1):
            inv = agent.get("inventory", {})
            total_inv = sum(inv.values())
            print(f"  #{i} {agent.get('name', '?')}: {agent.get('credits', 0)} credits, {total_inv} items")

        if moltbook_post_id:
            print(f"\nMoltbook:")
            print(f"  Post ID: {moltbook_post_id}")
            print(f"  Comments: {moltbook_comment_count}")
            print(f"  URL: https://www.moltbook.com/m/general/posts/{moltbook_post_id}")

        print(f"\nFiles generated:")
        print(f"  - demo_summary.md")
        print(f"  - events.jsonl ({len(events_log)} events)")


if __name__ == "__main__":
    asyncio.run(main())
