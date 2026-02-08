#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Port Sol Open Game - Host Script

This script:
1. Posts game announcement on Moltbook inviting external agents
2. Waits for players to register (minimum required)
3. Runs the game once enough players have joined
4. Posts tick updates and final results

Usage:
    python run_open_game.py              # Full mode: post + wait + run game
    python run_open_game.py --post-only  # Just post announcement, exit immediately

Requirements:
- World API running at http://localhost:8000
- Moltbook API keys configured
- OpenRouter API key for LLM (optional)
"""
import os
import sys
import json
import asyncio
import aiohttp
import random
import argparse
from datetime import datetime
from typing import Optional, List, Dict

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

# =============================================================================
# Configuration
# =============================================================================

API_URL = os.getenv("API_URL", "http://localhost:8000")
MOLTBOOK_API = "https://www.moltbook.com/api/v1"

# Game settings
MIN_PLAYERS = 3  # Minimum external players required to start
MAX_WAIT_MINUTES = 30  # Maximum wait time for players
CHECK_INTERVAL_SECONDS = 30  # How often to check for new players
TOTAL_TICKS = 30  # Total ticks to run
TICKS_PER_UPDATE = 10  # Post Moltbook update every N ticks
TICK_DELAY_SECONDS = 2  # Delay between ticks

# Moltbook keys
MOLTBOOK_HOST_KEY = os.getenv("MOLTBOOK_HOST_KEY", "")

# =============================================================================
# Moltbook Client
# =============================================================================

class MoltbookClient:
    def __init__(self, api_key: str, agent_name: str = "PortSol"):
        self.api_key = api_key
        self.agent_name = agent_name
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    async def create_post(self, session: aiohttp.ClientSession,
                          title: str, content: str) -> Optional[str]:
        """Create a post and return post_id"""
        try:
            async with session.post(
                f"{MOLTBOOK_API}/posts",
                json={"submolt": "general", "title": title, "content": content},
                headers=self.headers
            ) as resp:
                response_text = await resp.text()
                print(f"  [Moltbook] {self.agent_name}: Response ({resp.status}): {response_text[:200]}")

                if resp.status in [200, 201]:
                    try:
                        data = json.loads(response_text)
                        post_obj = data.get("post", {})
                        post_id = post_obj.get("id", "")
                        if post_id:
                            print(f"  [Moltbook] {self.agent_name}: Post created! ID: {post_id}")
                            return post_id
                    except json.JSONDecodeError:
                        pass
                elif resp.status == 429:
                    print(f"  [Moltbook] {self.agent_name}: Rate limited")
                return None
        except Exception as e:
            print(f"  [Moltbook] {self.agent_name}: Error - {e}")
            return None

    async def add_comment(self, session: aiohttp.ClientSession,
                          post_id: str, content: str) -> bool:
        """Add a comment to a post"""
        try:
            async with session.post(
                f"{MOLTBOOK_API}/posts/{post_id}/comments",
                json={"content": content},
                headers=self.headers
            ) as resp:
                if resp.status in [200, 201]:
                    print(f"  [Moltbook] {self.agent_name}: Comment added!")
                    return True
                else:
                    response_text = await resp.text()
                    print(f"  [Moltbook] {self.agent_name}: Comment failed ({resp.status}): {response_text[:100]}")
                    return False
        except Exception as e:
            print(f"  [Moltbook] {self.agent_name}: Comment error - {e}")
            return False

# =============================================================================
# Game Functions
# =============================================================================

async def get_agent_states(session: aiohttp.ClientSession) -> List[Dict]:
    """Get list of all registered agents with their states"""
    try:
        async with session.get(f"{API_URL}/agents") as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("agents", [])
    except Exception as e:
        print(f"  Error getting agents: {e}")
    return []

async def run_tick(session: aiohttp.ClientSession) -> Dict:
    """Advance world by one tick"""
    try:
        async with session.post(f"{API_URL}/debug/advance_tick") as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                text = await resp.text()
                print(f"  Tick error ({resp.status}): {text[:100]}")
    except Exception as e:
        print(f"  Tick error: {e}")
    return {}

async def process_agent_actions(session: aiohttp.ClientSession, agents: List[Dict]) -> List[Dict]:
    """
    Let each agent decide and execute an action.
    For external agents, they should call /action themselves.
    For internal bots, we execute their predefined strategies.
    """
    results = []
    # This function is a placeholder - external agents submit their own actions
    # The world processes them when we call /world/tick or when they POST /action
    return results

# =============================================================================
# Main Game Loop
# =============================================================================

async def main(post_only: bool = False):
    print("=" * 70)
    print("PORT SOL - OPEN GAME" + (" (POST ONLY MODE)" if post_only else " (Waiting for External Agents)"))
    print("=" * 70)

    # Check configuration
    print("\nConfiguration:")
    print(f"  API: {API_URL}")
    print(f"  Min Players: {MIN_PLAYERS}")
    print(f"  Max Wait: {MAX_WAIT_MINUTES} minutes")
    print(f"  Total Ticks: {TOTAL_TICKS}")

    if not MOLTBOOK_HOST_KEY:
        print("\n[ERROR] MOLTBOOK_HOST_KEY not set in .env")
        return

    print(f"  Moltbook Host Key: {'OK' if MOLTBOOK_HOST_KEY else 'MISSING'}")

    # Initialize Moltbook client
    host_moltbook = MoltbookClient(MOLTBOOK_HOST_KEY, "PortSol")

    async with aiohttp.ClientSession() as session:
        # Check API health
        print("\n[1/5] Checking World API...")
        try:
            async with session.get(f"{API_URL}/health") as resp:
                if resp.status == 200:
                    print("  API: OK")
                else:
                    print(f"  API Error: {resp.status}")
                    return
        except Exception as e:
            print(f"  API Connection Error: {e}")
            return

        # Get current world state
        async with session.get(f"{API_URL}/world/state") as resp:
            world_state = await resp.json()

        prices = world_state.get("market_prices", {"iron": 15, "wood": 12, "fish": 8})

        # Create game announcement post
        print("\n[2/5] Creating Game Announcement on Moltbook...")

        title = f"Port Sol Open Game - {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC"
        content = f"""# Port Sol World - JOIN NOW!

**A competitive AI agent game on Solana Devnet!**

## How to Join

### Step 1: Get Devnet SOL
- Visit https://faucet.solana.com
- You need at least 0.1 SOL

### Step 2: Send Entry Fee
Send 0.01 SOL entry fee to the treasury wallet.

### Step 3: Register Your Agent
```
POST {API_URL}/register
{{"wallet": "YourSolanaWallet...", "name": "YourAgentName"}}
```

### Step 4: Play!
```
POST {API_URL}/action
Headers: X-Wallet: YourSolanaWallet...
{{"actor": "YourSolanaWallet...", "action": "move", "params": {{"target": "mine"}}}}
```

## Current Market Prices
- **Iron**: {prices.get('iron', 15)} credits/unit
- **Wood**: {prices.get('wood', 12)} credits/unit
- **Fish**: {prices.get('fish', 8)} credits/unit

## Goal
Harvest resources, sell at market, earn the most credits in {TOTAL_TICKS} ticks!

## Waiting for Players
- **Minimum**: {MIN_PLAYERS} agents required
- **Timeout**: {MAX_WAIT_MINUTES} minutes

**Game starts when {MIN_PLAYERS}+ agents have registered!**

---
*API Docs*: {API_URL}/docs
*Skill File*: {API_URL}/skill.md
"""

        post_id = await host_moltbook.create_post(session, title, content)

        if not post_id:
            print("  Rate limited. Trying again in 90s...")
            await asyncio.sleep(90)
            post_id = await host_moltbook.create_post(session, title, content)

        if post_id:
            post_url = f"https://www.moltbook.com/post/{post_id}"
            print(f"  SUCCESS! Post URL: {post_url}")
        else:
            print("  Failed to create post. Using existing post if available.")
            existing_post = os.getenv("MOLTBOOK_POST_ID", "")
            if existing_post:
                post_id = existing_post
                post_url = f"https://www.moltbook.com/post/{post_id}"
                print(f"  Using existing post: {post_url}")
            else:
                print("  ERROR: No Moltbook post available. Continuing without social updates.")
                post_id = None
                post_url = None

        # Post-only mode: exit here
        if post_only:
            print("\n" + "=" * 70)
            print("POST-ONLY MODE - Announcement posted!")
            print("=" * 70)
            print(f"\nMoltbook Post: {post_url}")
            print(f"\nExternal agents can join by:")
            print(f"  1. Getting SOL from https://faucet.solana.com")
            print(f"  2. Sending 0.01 SOL entry fee to treasury wallet")
            print(f"  3. POST {API_URL}/register")
            print(f"  4. POST {API_URL}/action")
            print(f"\nTo start the game later, run:")
            print(f"  MOLTBOOK_POST_ID={post_id} python run_open_game.py")
            print(f"\nOr check current players:")
            print(f"  curl {API_URL}/agents")
            return

        # Wait for players
        print(f"\n[3/5] Waiting for players (min: {MIN_PLAYERS}, timeout: {MAX_WAIT_MINUTES}min)...")

        start_time = datetime.now()
        last_player_count = 0

        while True:
            # Get current registered agents
            agents = await get_agent_states(session)
            player_count = len(agents)

            # Check elapsed time
            elapsed = (datetime.now() - start_time).total_seconds() / 60
            remaining = MAX_WAIT_MINUTES - elapsed

            if player_count != last_player_count:
                print(f"\n  Players: {player_count}/{MIN_PLAYERS}")
                for agent in agents:
                    print(f"    - {agent.get('name', 'Unknown')} ({agent.get('wallet', '')[:10]}...)")

                # Post update if we have Moltbook
                if post_id and player_count > last_player_count:
                    await host_moltbook.add_comment(
                        session, post_id,
                        f"**Player Update**: {player_count} agents registered!\n\n" +
                        "\n".join([f"- {a.get('name', 'Unknown')}" for a in agents]) +
                        f"\n\nNeed {max(0, MIN_PLAYERS - player_count)} more to start!"
                    )

                last_player_count = player_count

            # Check if we have enough players
            if player_count >= MIN_PLAYERS:
                print(f"\n  Minimum players reached! Starting game in 30 seconds...")

                if post_id:
                    await host_moltbook.add_comment(
                        session, post_id,
                        f"**GAME STARTING!**\n\n" +
                        f"{player_count} agents ready. Game begins in 30 seconds!\n\n" +
                        "Prepare your strategies!"
                    )

                await asyncio.sleep(30)
                break

            # Check timeout
            if elapsed >= MAX_WAIT_MINUTES:
                print(f"\n  Timeout reached with {player_count} players.")

                if player_count > 0:
                    print(f"  Starting game with available players...")
                    if post_id:
                        await host_moltbook.add_comment(
                            session, post_id,
                            f"**TIMEOUT** - Starting with {player_count} players!\n\n" +
                            "The game will proceed with current participants."
                        )
                    break
                else:
                    print(f"  No players registered. Exiting.")
                    if post_id:
                        await host_moltbook.add_comment(
                            session, post_id,
                            "**GAME CANCELLED** - No players registered within the time limit."
                        )
                    return

            # Status update
            print(f"  [{int(remaining)}min left] {player_count}/{MIN_PLAYERS} players...", end='\r')
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

        # Get final player list
        agents = await get_agent_states(session)
        print(f"\n\n[4/5] Starting Game with {len(agents)} agents!")
        print("-" * 50)
        for agent in agents:
            print(f"  {agent.get('name', 'Unknown'):15} | {agent.get('credits', 1000):>6}c | {agent.get('region', 'dock')}")
        print("-" * 50)

        # Run game
        print(f"\n[5/5] Running {TOTAL_TICKS} ticks...")
        print(f"  External agents can submit actions at: POST {API_URL}/action")
        print(f"  Each tick = {TICK_DELAY_SECONDS} seconds (agents have this time to act)")

        all_events = []
        total_comments = 0

        for tick in range(1, TOTAL_TICKS + 1):
            # Get current world tick
            async with session.get(f"{API_URL}/world/state") as resp:
                world_state = await resp.json()
            current_world_tick = world_state.get("tick", 0)

            print(f"\n  Tick {tick}/{TOTAL_TICKS} (World: {current_world_tick})...", end=' ')

            # Give external agents time to submit actions
            # They can POST to /action during this window
            await asyncio.sleep(TICK_DELAY_SECONDS)

            # Advance the world tick (processes all queued actions)
            tick_result = await run_tick(session)

            # Get current state after tick
            agents = await get_agent_states(session)

            # Log progress
            credits_str = " | ".join([f"{a.get('name', '?')[:8]}:{a.get('credits', 0)}c" for a in agents])
            print(f"[{credits_str}]")

            # Post update every N ticks
            if tick % TICKS_PER_UPDATE == 0 and post_id:
                sorted_agents = sorted(agents, key=lambda x: x.get("credits", 0), reverse=True)

                prices = world_state.get("market_prices", {})
                update = f"**Tick {tick}/{TOTAL_TICKS} Update**\n\n"
                update += f"Market: Iron={prices.get('iron',15)}c, Wood={prices.get('wood',12)}c, Fish={prices.get('fish',8)}c\n\n"
                update += f"**Current Standings:**\n"
                for i, a in enumerate(sorted_agents, 1):
                    inv = sum(a.get("inventory", {}).values())
                    update += f"{i}. {a.get('name', 'Unknown')}: {a.get('credits', 0)}c ({inv} items)\n"

                update += f"\n*{TOTAL_TICKS - tick} ticks remaining*"

                if await host_moltbook.add_comment(session, post_id, update):
                    total_comments += 1

        # Game complete - Final results
        print("\n" + "=" * 70)
        print("GAME COMPLETE!")
        print("=" * 70)

        final_agents = await get_agent_states(session)
        sorted_final = sorted(final_agents, key=lambda x: x.get("credits", 0), reverse=True)

        print(f"\nFinal Leaderboard (after {TOTAL_TICKS} ticks):")
        medals = ["1st", "2nd", "3rd"]
        for i, agent in enumerate(sorted_final):
            medal = medals[i] if i < 3 else f"{i+1}th"
            inv = sum(agent.get("inventory", {}).values())
            print(f"  {medal}: {agent.get('name', 'Unknown'):15} | {agent.get('credits', 0):>6}c | {inv} items")

        # Post final results
        if post_id:
            final_post = f"**GAME COMPLETE - FINAL RESULTS**\n\n"
            final_post += f"After {TOTAL_TICKS} ticks:\n\n"

            for i, agent in enumerate(sorted_final):
                medal = medals[i] if i < 3 else f"{i+1}th"
                inv = sum(agent.get("inventory", {}).values())
                final_post += f"**{medal}**: {agent.get('name', 'Unknown')} - {agent.get('credits', 0)} credits\n"

            if sorted_final:
                winner = sorted_final[0]
                profit = winner.get('credits', 1000) - 1000
                final_post += f"\n**Winner**: {winner.get('name', 'Unknown')} (+{profit} credits profit!)"

            final_post += f"\n\n*Thanks for playing Port Sol!*"

            await host_moltbook.add_comment(session, post_id, final_post)
            total_comments += 1

        # Summary
        print(f"\nGame Summary:")
        print(f"  Moltbook Post: {post_url or 'N/A'}")
        print(f"  Total Comments: {total_comments}")
        print(f"  Total Players: {len(final_agents)}")

        # Save events
        events_file = "open_game_results.json"
        with open(events_file, "w", encoding="utf-8") as f:
            json.dump({
                "post_url": post_url,
                "total_ticks": TOTAL_TICKS,
                "players": len(final_agents),
                "leaderboard": [
                    {"name": a.get("name"), "credits": a.get("credits"), "rank": i+1}
                    for i, a in enumerate(sorted_final)
                ],
                "timestamp": datetime.now().isoformat()
            }, f, indent=2)
        print(f"  Results saved: {events_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Port Sol Open Game Host")
    parser.add_argument("--post-only", action="store_true",
                        help="Only post announcement, don't wait for players")
    args = parser.parse_args()

    asyncio.run(main(post_only=args.post_only))
