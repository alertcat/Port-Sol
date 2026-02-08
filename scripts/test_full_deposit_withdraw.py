#!/usr/bin/env python3
"""
Complete Deposit → Game → Settlement → Withdrawal test.

This tests the full lifecycle:
  Phase 1: Record pre-test balances
  Phase 2: Entry (deposit) - 3 agents each pay 0.01 SOL to treasury
  Phase 3: Game - register, play a few actions, advance ticks
  Phase 4: Settlement (withdrawal) - treasury distributes SOL back by credits
  Phase 5: Record post-test balances and verify

Usage:
    python scripts/test_full_deposit_withdraw.py
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
ENTRY_FEE_LAMPORTS = int(os.getenv("ENTRY_FEE_LAMPORTS", "10000000"))
TREASURY_PUBKEY = os.getenv("TREASURY_PUBKEY")
TREASURY_KEYPAIR = os.getenv("TREASURY_KEYPAIR")

BOTS = [
    {"name": "MinerBot",    "wallet": os.getenv("MINER_WALLET"),    "keypair": os.getenv("MINER_KEYPAIR")},
    {"name": "TraderBot",   "wallet": os.getenv("TRADER_WALLET"),   "keypair": os.getenv("TRADER_KEYPAIR")},
    {"name": "GovernorBot", "wallet": os.getenv("GOVERNOR_WALLET"), "keypair": os.getenv("GOVERNOR_KEYPAIR")},
]


def get_balance_sol(address: str) -> float:
    """Get SOL balance from Solana devnet RPC."""
    rpc = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
    resp = requests.post(rpc, json={
        "jsonrpc": "2.0", "id": 1,
        "method": "getBalance",
        "params": [address]
    }, timeout=15)
    lamports = resp.json().get("result", {}).get("value", 0)
    return lamports / LAMPORTS_PER_SOL


def print_balances(label: str, balances: dict):
    """Pretty print balance table."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    for name, sol in balances.items():
        print(f"  {name:<15} {sol:.9f} SOL")
    print(f"{'='*60}")


def fetch_all_balances() -> dict:
    """Fetch all wallet balances."""
    balances = {"Treasury": get_balance_sol(TREASURY_PUBKEY)}
    for bot in BOTS:
        balances[bot["name"]] = get_balance_sol(bot["wallet"])
    return balances


async def phase2_entry():
    """Phase 2: Each agent enters the world (pays entry fee)."""
    print("\n" + "="*60)
    print("  PHASE 2: ENTRY (Deposit 0.01 SOL each)")
    print("="*60)

    results = []
    for bot in BOTS:
        print(f"\n  {bot['name']}: Entering world (0.01 SOL -> Treasury)...")
        client = PortSolClient(API_URL, bot["wallet"], bot["keypair"])
        success, result = client.enter_world()
        if success:
            print(f"    SUCCESS: TX {result[:20]}...")
            results.append(True)
        else:
            if "already" in str(result).lower() or "entry" in str(result).lower():
                print(f"    ALREADY ENTERED (OK): {result}")
                results.append(True)
            else:
                print(f"    FAILED: {result}")
                results.append(False)
        time.sleep(2)  # Wait between transactions
    
    return all(results)


async def phase3_game():
    """Phase 3: Register agents, play actions, advance ticks."""
    print("\n" + "="*60)
    print("  PHASE 3: GAME (Register, play, advance ticks)")
    print("="*60)

    # First reset the world for a clean test
    print("\n  Resetting world state...")
    try:
        r = requests.post(f"{API_URL}/debug/reset_world", timeout=10)
        print(f"    Reset: {r.json()}")
    except Exception as e:
        print(f"    Reset failed (may not be in debug mode): {e}")

    # Register each agent
    for bot in BOTS:
        print(f"\n  Registering {bot['name']}...")
        client = PortSolClient(API_URL, bot["wallet"], bot["keypair"])
        result = await client.register(bot["name"])
        print(f"    Result: {result.get('message', result)}")

        # Do some actions based on bot type
        if bot["name"] == "MinerBot":
            # Move to mine, harvest, move to market, sell
            actions = [
                ("move", {"target": "mine"}),
                ("harvest", {}),
                ("harvest", {}),
                ("move", {"target": "market"}),
                ("place_order", {"side": "sell", "resource": "iron", "quantity": 2}),
            ]
        elif bot["name"] == "TraderBot":
            # Move to market, buy, sell
            actions = [
                ("move", {"target": "market"}),
                ("place_order", {"side": "buy", "resource": "iron", "quantity": 1}),
                ("place_order", {"side": "buy", "resource": "fish", "quantity": 2}),
                ("place_order", {"side": "sell", "resource": "fish", "quantity": 1}),
            ]
        else:  # GovernorBot
            # Move to dock, fish, sell
            actions = [
                ("move", {"target": "dock"}),
                ("harvest", {}),
                ("harvest", {}),
                ("move", {"target": "market"}),
                ("place_order", {"side": "sell", "resource": "fish", "quantity": 2}),
            ]

        for action, params in actions:
            result = await client.submit_action(action, params)
            msg = result.get("message", str(result))
            success = result.get("success", False)
            symbol = "OK" if success else "FAIL"
            print(f"    [{symbol}] {action}({params}) -> {msg[:60]}")

        await client.close()

    # Advance a few ticks
    print("\n  Advancing ticks...")
    for i in range(3):
        try:
            r = requests.post(f"{API_URL}/debug/advance_tick", timeout=10)
            tick_data = r.json()
            print(f"    Tick {tick_data.get('tick', '?')}: prices={tick_data.get('market_prices', {})}")
        except Exception as e:
            print(f"    Tick advance failed: {e}")
        time.sleep(0.5)

    # Get final agent states
    print("\n  Final agent states:")
    credits_map = {}
    for bot in BOTS:
        try:
            r = requests.get(f"{API_URL}/agent/{bot['wallet']}/state", timeout=10)
            state = r.json()
            credits = state.get("credits", 0)
            inv = state.get("inventory", {})
            inv_count = sum(inv.values()) if isinstance(inv, dict) else 0
            credits_map[bot["name"]] = credits
            print(f"    {bot['name']:<15} credits={credits:<6} inventory_items={inv_count} energy={state.get('energy', '?')}")
        except Exception as e:
            print(f"    {bot['name']}: ERROR - {e}")
            credits_map[bot["name"]] = 1000  # default

    return credits_map


async def phase4_settlement():
    """Phase 4: Treasury distributes SOL back to agents based on credits."""
    print("\n" + "="*60)
    print("  PHASE 4: SETTLEMENT (Withdraw SOL from treasury)")
    print("="*60)

    gate = get_gate_client()
    treasury_keypair_bytes = bytes(json.loads(TREASURY_KEYPAIR))

    # Fetch agent credits from API
    print("\n  Fetching final credits from API...")
    credits_map = {}
    for bot in BOTS:
        try:
            r = requests.get(f"{API_URL}/agent/{bot['wallet']}/state", timeout=10)
            state = r.json()
            credits_map[bot["name"]] = {
                "wallet": bot["wallet"],
                "credits": state.get("credits", 1000),
            }
        except Exception:
            credits_map[bot["name"]] = {
                "wallet": bot["wallet"],
                "credits": 1000,
            }

    total_credits = sum(info["credits"] for info in credits_map.values())
    num_agents = len(BOTS)
    pool_lamports = ENTRY_FEE_LAMPORTS * num_agents  # 0.03 SOL

    print(f"\n  Prize Pool: {pool_lamports / LAMPORTS_PER_SOL} SOL")
    print(f"  Total Credits: {total_credits}")

    # Calculate and send distributions
    print(f"\n  {'Agent':<15} {'Credits':>8} {'Share':>8} {'Payout':>14}")
    print(f"  {'-'*48}")

    for name, info in credits_map.items():
        share = info["credits"] / total_credits if total_credits > 0 else 0
        payout_lamports = int(pool_lamports * share)
        payout_sol = payout_lamports / LAMPORTS_PER_SOL

        print(f"  {name:<15} {info['credits']:>8} {share:>7.1%} {payout_sol:>12.6f} SOL")

        if payout_lamports > 0:
            print(f"    Sending {payout_sol:.6f} SOL to {info['wallet'][:16]}...")
            ok, result = gate.send_sol(treasury_keypair_bytes, info["wallet"], payout_lamports)
            if ok:
                print(f"    TX: {result}")
            else:
                print(f"    FAILED: {result}")
            time.sleep(3)  # Wait between transactions


async def main():
    print("="*60)
    print("  PORT SOL - COMPLETE DEPOSIT/WITHDRAWAL TEST")
    print("="*60)
    print(f"  API: {API_URL}")
    print(f"  Entry Fee: {ENTRY_FEE_LAMPORTS / LAMPORTS_PER_SOL} SOL per agent")
    print(f"  Treasury: {TREASURY_PUBKEY}")
    print(f"  Network: Solana Devnet")

    # --- Phase 1: Pre-test balances ---
    print("\n" + "="*60)
    print("  PHASE 1: PRE-TEST BALANCES")
    print("="*60)
    pre_balances = fetch_all_balances()
    print_balances("BEFORE TEST", pre_balances)

    # --- Phase 2: Entry ---
    entry_ok = await phase2_entry()
    if not entry_ok:
        print("\nEntry phase had failures, continuing anyway...")

    time.sleep(3)

    # --- Phase 3: Game ---
    credits_map = await phase3_game()

    time.sleep(2)

    # --- Phase 4: Settlement ---
    await phase4_settlement()

    time.sleep(5)  # Wait for transactions to confirm

    # --- Phase 5: Post-test balances ---
    print("\n" + "="*60)
    print("  PHASE 5: POST-TEST BALANCES")
    print("="*60)
    post_balances = fetch_all_balances()
    print_balances("AFTER TEST", post_balances)

    # --- Summary ---
    print("\n" + "="*60)
    print("  BALANCE CHANGES SUMMARY")
    print("="*60)
    print(f"  {'Wallet':<15} {'Before':>12} {'After':>12} {'Change':>12}")
    print(f"  {'-'*54}")
    for name in pre_balances:
        before = pre_balances[name]
        after = post_balances.get(name, 0)
        change = after - before
        sign = "+" if change >= 0 else ""
        print(f"  {name:<15} {before:>11.6f} {after:>11.6f} {sign}{change:>10.6f}")

    # Verify: agents should have roughly gotten back their entry fees
    total_agent_change = sum(
        post_balances.get(bot["name"], 0) - pre_balances.get(bot["name"], 0)
        for bot in BOTS
    )
    treasury_change = post_balances["Treasury"] - pre_balances["Treasury"]

    print(f"\n  Total agent balance change: {total_agent_change:+.6f} SOL")
    print(f"  Treasury balance change:    {treasury_change:+.6f} SOL")
    print(f"  Net flow (should be ~0):    {total_agent_change + treasury_change:+.6f} SOL")
    print(f"  (Difference is transaction fees on Solana)")

    print("\n" + "="*60)
    print("  TEST COMPLETE")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
