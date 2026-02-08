#!/usr/bin/env python3
"""
Complete Deposit → Long Game → Settlement → Withdrawal test (v2).
Entry fee: 0.1 SOL, 10 ticks, more gameplay for larger credit divergence.
"""
import os
import sys
import json
import time
import asyncio
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / '.env')

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent.parent / 'agents'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'world-api'))

from sdk.client import PortSolClient
from engine.blockchain import PortSolGate, get_gate_client

LAMPORTS_PER_SOL = 1_000_000_000
API_URL = os.getenv("API_URL", "http://localhost:8000")
ENTRY_FEE_LAMPORTS = int(os.getenv("ENTRY_FEE_LAMPORTS", "100000000"))  # 0.1 SOL
TREASURY_PUBKEY = os.getenv("TREASURY_PUBKEY")
TREASURY_KEYPAIR = os.getenv("TREASURY_KEYPAIR")
RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")

BOTS = [
    {"name": "MinerBot",    "wallet": os.getenv("MINER_WALLET"),    "keypair": os.getenv("MINER_KEYPAIR")},
    {"name": "TraderBot",   "wallet": os.getenv("TRADER_WALLET"),   "keypair": os.getenv("TRADER_KEYPAIR")},
    {"name": "GovernorBot", "wallet": os.getenv("GOVERNOR_WALLET"), "keypair": os.getenv("GOVERNOR_KEYPAIR")},
]

NUM_TICKS = 10


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


def print_balances(label: str, balances: dict):
    print(f"\n  {'='*50}")
    print(f"  {label}")
    print(f"  {'='*50}")
    for name, sol in balances.items():
        print(f"  {name:<15} {sol:.9f} SOL")


async def run_agent_turn(bot: dict, tick: int):
    """Run one turn of gameplay for a bot based on simple strategy."""
    client = PortSolClient(API_URL, bot["wallet"], bot["keypair"])

    # Get current state
    state = await client.get_my_state()
    region = state.get("region", "dock")
    energy = state.get("energy", 0)
    inventory = state.get("inventory", {})
    credits = state.get("credits", 1000)
    inv_total = sum(inventory.values()) if isinstance(inventory, dict) else 0

    actions_taken = []

    if bot["name"] == "MinerBot":
        # Strategy: mine iron aggressively, sell when full
        if energy < 10:
            result = await client.submit_action("rest", {})
            actions_taken.append("rest")
        elif inv_total >= 4 and region != "market":
            result = await client.submit_action("move", {"target": "market"})
            actions_taken.append("move->market")
        elif inv_total >= 4 and region == "market":
            qty = inventory.get("iron", 0)
            if qty > 0:
                result = await client.submit_action("place_order", {"side": "sell", "resource": "iron", "quantity": qty})
                actions_taken.append(f"sell {qty} iron")
            qty = inventory.get("wood", 0)
            if qty > 0:
                result = await client.submit_action("place_order", {"side": "sell", "resource": "wood", "quantity": qty})
                actions_taken.append(f"sell {qty} wood")
            qty = inventory.get("fish", 0)
            if qty > 0:
                result = await client.submit_action("place_order", {"side": "sell", "resource": "fish", "quantity": qty})
                actions_taken.append(f"sell {qty} fish")
        elif region != "mine":
            result = await client.submit_action("move", {"target": "mine"})
            actions_taken.append("move->mine")
        else:
            result = await client.submit_action("harvest", {})
            actions_taken.append("harvest")

    elif bot["name"] == "TraderBot":
        # Strategy: buy cheap resources, sell at profit
        if energy < 10:
            result = await client.submit_action("rest", {})
            actions_taken.append("rest")
        elif region != "market":
            result = await client.submit_action("move", {"target": "market"})
            actions_taken.append("move->market")
        elif inv_total >= 3:
            # Sell everything
            for res, qty in (inventory or {}).items():
                if qty > 0:
                    result = await client.submit_action("place_order", {"side": "sell", "resource": res, "quantity": qty})
                    actions_taken.append(f"sell {qty} {res}")
        elif credits > 900:
            # Buy cheapest resource
            try:
                world = await client.get_world_state()
                prices = world.get("market_prices", {"iron": 15, "wood": 12, "fish": 8})
                cheapest = min(prices, key=prices.get)
                result = await client.submit_action("place_order", {"side": "buy", "resource": cheapest, "quantity": 3})
                actions_taken.append(f"buy 3 {cheapest}")
            except:
                result = await client.submit_action("place_order", {"side": "buy", "resource": "fish", "quantity": 3})
                actions_taken.append("buy 3 fish")
        else:
            result = await client.submit_action("rest", {})
            actions_taken.append("rest")

    elif bot["name"] == "GovernorBot":
        # Strategy: fish aggressively at dock, sell at market
        if energy < 10:
            result = await client.submit_action("rest", {})
            actions_taken.append("rest")
        elif inv_total >= 5 and region != "market":
            result = await client.submit_action("move", {"target": "market"})
            actions_taken.append("move->market")
        elif inv_total >= 5 and region == "market":
            qty = inventory.get("fish", 0)
            if qty > 0:
                result = await client.submit_action("place_order", {"side": "sell", "resource": "fish", "quantity": qty})
                actions_taken.append(f"sell {qty} fish")
            for res in ["iron", "wood"]:
                qty = inventory.get(res, 0)
                if qty > 0:
                    result = await client.submit_action("place_order", {"side": "sell", "resource": res, "quantity": qty})
                    actions_taken.append(f"sell {qty} {res}")
        elif region != "dock":
            result = await client.submit_action("move", {"target": "dock"})
            actions_taken.append("move->dock")
        else:
            result = await client.submit_action("harvest", {})
            actions_taken.append("harvest")

    await client.close()
    return actions_taken


async def main():
    entry_fee_sol = ENTRY_FEE_LAMPORTS / LAMPORTS_PER_SOL
    pool_sol = entry_fee_sol * len(BOTS)

    print("=" * 60)
    print("  PORT SOL - DEPOSIT/WITHDRAWAL TEST v2")
    print("=" * 60)
    print(f"  Entry Fee:  {entry_fee_sol} SOL per agent")
    print(f"  Prize Pool: {pool_sol} SOL (from {len(BOTS)} agents)")
    print(f"  Ticks:      {NUM_TICKS}")
    print(f"  API:        {API_URL}")

    # ==================== PHASE 1: PRE-TEST BALANCES ====================
    print("\n\n  PHASE 1: PRE-TEST BALANCES")
    pre_balances = fetch_all_balances()
    print_balances("BEFORE", pre_balances)

    # ==================== PHASE 2: ENTRY (DEPOSIT) ====================
    print(f"\n\n  PHASE 2: ENTRY ({entry_fee_sol} SOL each)")
    print("  " + "-" * 50)

    for bot in BOTS:
        print(f"  {bot['name']}: Paying {entry_fee_sol} SOL to treasury...")
        client = PortSolClient(API_URL, bot["wallet"], bot["keypair"])
        success, result = client.enter_world()
        if success:
            print(f"    OK: TX {result[:24]}...")
        else:
            print(f"    Result: {result}")
        time.sleep(2)

    time.sleep(3)
    post_entry = fetch_all_balances()
    print_balances("AFTER ENTRY", post_entry)

    # ==================== PHASE 3: GAME ====================
    print(f"\n\n  PHASE 3: GAME ({NUM_TICKS} ticks)")
    print("  " + "-" * 50)

    # Reset world
    try:
        r = requests.post(f"{API_URL}/debug/reset_world", timeout=10)
        print(f"  World reset: tick=0")
    except:
        print("  Could not reset world (non-debug mode?)")

    # Register agents
    for bot in BOTS:
        client = PortSolClient(API_URL, bot["wallet"], bot["keypair"])
        result = await client.register(bot["name"])
        print(f"  Registered {bot['name']}: {result.get('message', 'ok')}")
        await client.close()

    # Game loop
    for tick in range(NUM_TICKS):
        # Each bot takes actions
        for bot in BOTS:
            actions = await run_agent_turn(bot, tick)

        # Advance tick
        try:
            r = requests.post(f"{API_URL}/debug/advance_tick", timeout=10)
            td = r.json()
            prices = td.get("market_prices", {})
            pyth = td.get("pyth_oracle", {})
            pyth_str = ""
            if pyth.get("enabled") and pyth.get("change_pct") is not None:
                pyth_str = f" | SOL {pyth['change_pct']:+.4f}%"
            print(f"  Tick {td.get('tick', '?'):>2}: iron={prices.get('iron', '?'):>3} wood={prices.get('wood', '?'):>3} fish={prices.get('fish', '?'):>3}{pyth_str}")
        except Exception as e:
            print(f"  Tick advance error: {e}")

    # Final agent states
    print(f"\n  FINAL AGENT STATES:")
    print(f"  {'Agent':<15} {'Credits':>8} {'Items':>6} {'Energy':>7}")
    print(f"  {'-'*40}")
    total_credits = 0
    agent_credits = {}
    for bot in BOTS:
        try:
            r = requests.get(f"{API_URL}/agent/{bot['wallet']}/state", timeout=10)
            s = r.json()
            cr = s.get("credits", 1000)
            inv = s.get("inventory", {})
            items = sum(inv.values()) if isinstance(inv, dict) else 0
            en = s.get("energy", 0)
            agent_credits[bot["name"]] = {"credits": cr, "wallet": bot["wallet"], "items": items, "inv": inv}
            total_credits += cr
            print(f"  {bot['name']:<15} {cr:>8} {items:>6} {en:>7}")
        except Exception as e:
            agent_credits[bot["name"]] = {"credits": 1000, "wallet": bot["wallet"], "items": 0, "inv": {}}
            total_credits += 1000
            print(f"  {bot['name']:<15} ERROR: {e}")

    # Force sell remaining inventory at current market prices
    print(f"\n  FINAL SETTLEMENT (force-sell inventory)...")
    for bot in BOTS:
        info = agent_credits[bot["name"]]
        if info["items"] > 0:
            client = PortSolClient(API_URL, bot["wallet"], bot["keypair"])
            state = await client.get_my_state()
            region = state.get("region", "dock")
            if region != "market":
                await client.submit_action("move", {"target": "market"})
            inv = state.get("inventory", {})
            for res, qty in inv.items():
                if qty > 0:
                    result = await client.submit_action("place_order", {"side": "sell", "resource": res, "quantity": qty})
                    msg = result.get("message", "")
                    print(f"    {bot['name']}: sold {qty} {res} -> {msg[:50]}")
            # Re-fetch credits
            state = await client.get_my_state()
            new_cr = state.get("credits", info["credits"])
            agent_credits[bot["name"]]["credits"] = new_cr
            await client.close()

    # Recalculate totals
    total_credits = sum(info["credits"] for info in agent_credits.values())
    print(f"\n  SETTLED CREDITS:")
    print(f"  {'Agent':<15} {'Credits':>8} {'Share':>8} {'Expected SOL':>14}")
    print(f"  {'-'*48}")
    for name, info in agent_credits.items():
        share = info["credits"] / total_credits if total_credits > 0 else 0
        payout = pool_sol * share
        print(f"  {name:<15} {info['credits']:>8} {share:>7.1%} {payout:>12.6f} SOL")
    print(f"  {'TOTAL':<15} {total_credits:>8} {'100%':>8} {pool_sol:>12.6f} SOL")

    # ==================== PHASE 4: SETTLEMENT (WITHDRAW) ====================
    print(f"\n\n  PHASE 4: SETTLEMENT (distribute {pool_sol} SOL)")
    print("  " + "-" * 50)

    gate = get_gate_client()
    treasury_keypair_bytes = bytes(json.loads(TREASURY_KEYPAIR))

    for name, info in agent_credits.items():
        share = info["credits"] / total_credits if total_credits > 0 else 0
        payout_lamports = int(ENTRY_FEE_LAMPORTS * len(BOTS) * share)
        payout_sol = payout_lamports / LAMPORTS_PER_SOL

        print(f"  {name}: {payout_sol:.6f} SOL ({share:.1%}) -> {info['wallet'][:20]}...")
        if payout_lamports > 0:
            ok, result = gate.send_sol(treasury_keypair_bytes, info["wallet"], payout_lamports)
            if ok:
                print(f"    TX: {result}")
            else:
                print(f"    FAILED: {result}")
            time.sleep(3)

    # ==================== PHASE 5: POST-TEST ====================
    time.sleep(5)
    print(f"\n\n  PHASE 5: POST-TEST RESULTS")
    post_balances = fetch_all_balances()
    print_balances("AFTER SETTLEMENT", post_balances)

    print(f"\n  BALANCE CHANGES:")
    print(f"  {'Wallet':<15} {'Before':>12} {'After':>12} {'Change':>12}")
    print(f"  {'-'*54}")
    for name in pre_balances:
        before = pre_balances[name]
        after = post_balances.get(name, 0)
        change = after - before
        sign = "+" if change >= 0 else ""
        print(f"  {name:<15} {before:>11.6f} {after:>11.6f} {sign}{change:>10.6f}")

    # Calculate net flows
    agent_changes = {bot["name"]: post_balances.get(bot["name"], 0) - pre_balances.get(bot["name"], 0) for bot in BOTS}
    treasury_change = post_balances["Treasury"] - pre_balances["Treasury"]

    print(f"\n  PROFIT/LOSS per agent:")
    winner = max(agent_changes, key=agent_changes.get)
    loser = min(agent_changes, key=agent_changes.get)
    for name, change in agent_changes.items():
        label = ""
        if name == winner:
            label = " <- WINNER"
        elif name == loser:
            label = " <- LOSER"
        print(f"    {name:<15} {change:>+.6f} SOL{label}")

    net = sum(agent_changes.values()) + treasury_change
    print(f"\n  Net flow (tx fees): {net:+.6f} SOL")
    print(f"  Treasury change:    {treasury_change:+.6f} SOL")

    print("\n" + "=" * 60)
    print("  TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
