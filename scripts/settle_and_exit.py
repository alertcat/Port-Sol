#!/usr/bin/env python3
"""
Settlement script - distribute treasury SOL proportionally by credits.

Phase 4: Exit / Settlement
  1. Fetch final agent states from API
  2. Calculate each agent's credit proportion
  3. Calculate SOL payout (entry_fee * num_agents * share)
  4. Transfer SOL from treasury to each agent proportionally
  5. Print final settlement summary

Usage:
    python settle_and_exit.py
    python settle_and_exit.py --api http://43.156.62.248:8000
"""
import os
import sys
import time
import argparse
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / '.env')

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'world-api'))
from engine.blockchain import PortSolGate, get_gate_client

LAMPORTS_PER_SOL = 1_000_000_000
ENTRY_FEE_LAMPORTS = int(os.getenv("ENTRY_FEE_LAMPORTS", "10000000"))  # 0.01 SOL default
TREASURY_PUBKEY = os.getenv("TREASURY_PUBKEY")
TREASURY_KEYPAIR = os.getenv("TREASURY_KEYPAIR")

AGENTS = {
    "MinerBot":    os.getenv("MINER_WALLET"),
    "TraderBot":   os.getenv("TRADER_WALLET"),
    "GovernorBot": os.getenv("GOVERNOR_WALLET"),
}


def fetch_agent_credits(api_url: str) -> dict:
    """Fetch final credits from the World API."""
    import requests
    r = requests.get(f"{api_url}/agents")
    data = r.json()

    credits_map = {}
    for agent in data.get("agents", []):
        wallet = agent["wallet"]
        if wallet in AGENTS.values():
            credits_map[wallet] = {
                "name": agent["name"],
                "credits": agent["credits"],
                "inventory": agent.get("inventory", {}),
            }
    return credits_map


def main():
    parser = argparse.ArgumentParser(description="Settle and exit - distribute treasury SOL")
    parser.add_argument("--api", default=os.getenv("API_URL", "http://localhost:8000"))
    parser.add_argument("--dry-run", action="store_true", help="Calculate only, don't send transactions")
    args = parser.parse_args()

    print("=" * 60)
    print("  PORT SOL - Settlement & Exit")
    print("=" * 60)

    gate = get_gate_client()

    if not TREASURY_KEYPAIR:
        print("ERROR: TREASURY_KEYPAIR not set in environment")
        sys.exit(1)

    if not TREASURY_PUBKEY:
        print("ERROR: TREASURY_PUBKEY not set in environment")
        sys.exit(1)

    # Parse keypair bytes for sending transactions
    import json as _json
    treasury_keypair_bytes = bytes(_json.loads(TREASURY_KEYPAIR))

    # --- Step 1: Calculate the prize pool from entry fees ---
    num_agents = len(AGENTS)
    pool_lamports = ENTRY_FEE_LAMPORTS * num_agents
    pool_sol = pool_lamports / LAMPORTS_PER_SOL

    treasury_balance_sol = gate.get_balance_sol(TREASURY_PUBKEY)

    print(f"\nPrize Pool:  {pool_sol} SOL ({pool_lamports} lamports)")
    print(f"Entry Fee:   {ENTRY_FEE_LAMPORTS / LAMPORTS_PER_SOL} SOL per agent ({num_agents} agents)")
    print(f"Treasury:    {treasury_balance_sol} SOL")
    print(f"Network:     Solana Devnet")
    print(f"API:         {args.api}")

    if treasury_balance_sol < pool_sol:
        print(f"\nWARNING: Treasury balance ({treasury_balance_sol} SOL) is less than prize pool ({pool_sol} SOL)")
        print("Will distribute available balance proportionally.")
        pool_lamports = int(treasury_balance_sol * LAMPORTS_PER_SOL)
        pool_sol = pool_lamports / LAMPORTS_PER_SOL

    # --- Step 2: Fetch agent credits ---
    print(f"\n--- Fetching agent states from API ---")
    credits_map = fetch_agent_credits(args.api)

    if len(credits_map) == 0:
        print("ERROR: No agents found in API")
        sys.exit(1)

    total_credits = sum(info["credits"] for info in credits_map.values())
    print(f"\n{'Agent':<15} {'Credits':>10} {'Share':>10}")
    print("-" * 40)
    for wallet, info in credits_map.items():
        share = info["credits"] / total_credits if total_credits > 0 else 0
        print(f"{info['name']:<15} {info['credits']:>10} {share:>9.1%}")
    print(f"{'TOTAL':<15} {total_credits:>10} {'100.0%':>10}")

    # --- Step 3: Calculate SOL distribution ---
    print(f"\n--- SOL Distribution (pool: {pool_sol} SOL) ---")
    distributions = []
    for wallet, info in credits_map.items():
        share = info["credits"] / total_credits if total_credits > 0 else 0
        payout_lamports = int(pool_lamports * info["credits"] / total_credits) if total_credits > 0 else 0
        payout_sol = payout_lamports / LAMPORTS_PER_SOL
        distributions.append({
            "name": info["name"],
            "wallet": wallet,
            "credits": info["credits"],
            "share": share,
            "payout_lamports": payout_lamports,
            "payout": payout_sol,
        })
        print(f"  {info['name']:<15} {info['credits']:>6}cr ({share:.1%}) -> {payout_sol:.6f} SOL")

    if args.dry_run:
        print("\n[DRY RUN] No transactions sent.")
        return

    # --- Step 4: Distribute SOL from treasury ---
    print(f"\n--- Distributing SOL from treasury ---")
    for d in distributions:
        if d["payout_lamports"] == 0:
            print(f"  {d['name']}: 0 SOL (skipping)")
            continue

        print(f"  Sending {d['payout']:.6f} SOL to {d['name']} ({d['wallet'][:12]}...)...")
        ok, result = gate.send_sol(treasury_keypair_bytes, d["wallet"], d["payout_lamports"])
        if ok:
            print(f"    TX: {result}")
        else:
            print(f"    FAILED: {result}")
        time.sleep(3)

    # --- Final Summary ---
    print(f"\n{'='*60}")
    print("  SETTLEMENT COMPLETE")
    print(f"{'='*60}")
    print(f"\n{'Agent':<15} {'Credits':>8} {'Share':>8} {'SOL Received':>14}")
    print("-" * 50)
    total_sent = 0
    for d in distributions:
        print(f"{d['name']:<15} {d['credits']:>8} {d['share']:>7.1%} {d['payout']:>12.6f} SOL")
        total_sent += d['payout']
    print("-" * 50)
    print(f"{'TOTAL':<15} {total_credits:>8} {'100%':>8} {total_sent:>12.6f} SOL")

    # Final balances
    print(f"\n--- Final Balances ---")
    for d in distributions:
        bal = gate.get_balance_sol(d["wallet"])
        print(f"  {d['name']:<15} {bal} SOL")

    treasury_final = gate.get_balance_sol(TREASURY_PUBKEY)
    print(f"  {'Treasury':<15} {treasury_final} SOL")


if __name__ == "__main__":
    main()
