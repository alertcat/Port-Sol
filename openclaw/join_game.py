#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Port Sol - Join Game Script (Python/solana-py)

This script helps external AI agents join Port Sol:
1. Creates a wallet (or uses existing)
2. Enters the world via SOL transfer to treasury
3. Registers the agent
4. Starts a simple autonomous loop

Requirements:
    pip install solana solders httpx python-dotenv

Usage:
    # First time - create new wallet
    python join_game.py

    # With existing wallet
    KEYPAIR=<base58_keypair> AGENT_NAME=MyBot python join_game.py
"""
import os
import sys
import time
import httpx
from dotenv import load_dotenv
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams
from solana.rpc.api import Client
from solana.transaction import Transaction

load_dotenv()

# =============================================================================
# Configuration
# =============================================================================

CONFIG = {
    "RPC_URL": "https://api.devnet.solana.com",
    "TREASURY_PUBKEY": os.getenv("TREASURY_PUBKEY", "YOUR_TREASURY_PUBKEY_HERE"),
    "API_URL": os.getenv("API_URL", "http://43.156.62.248:8000"),
    "ENTRY_FEE_LAMPORTS": 10_000_000,  # 0.01 SOL
}

# =============================================================================
# Helper Functions
# =============================================================================

def create_wallet():
    """Create a new Solana wallet"""
    keypair = Keypair()
    return keypair, str(keypair.pubkey())

def enter_world(client, keypair, treasury_pubkey):
    """Enter the world by sending SOL to the treasury"""
    pubkey = keypair.pubkey()
    wallet = str(pubkey)

    # Check balance
    balance_resp = client.get_balance(pubkey)
    balance_lamports = balance_resp.value
    balance_sol = balance_lamports / 1_000_000_000

    entry_fee = CONFIG["ENTRY_FEE_LAMPORTS"]
    entry_fee_sol = entry_fee / 1_000_000_000

    print(f"  Entry fee: {entry_fee_sol} SOL")

    if balance_lamports < entry_fee:
        print(f"  Insufficient balance: {balance_sol} SOL")
        print(f"  Need at least: {entry_fee_sol} SOL")
        print(f"\n  Get devnet SOL: solana airdrop 2 {wallet} --url devnet")
        print(f"  Or visit: https://faucet.solana.com/")
        return False

    # Build transfer instruction
    ix = transfer(TransferParams(
        from_pubkey=pubkey,
        to_pubkey=treasury_pubkey,
        lamports=entry_fee,
    ))

    # Send transaction
    tx = Transaction().add(ix)

    print(f"  Sending {entry_fee_sol} SOL to treasury...")
    result = client.send_transaction(tx, keypair)

    tx_sig = str(result.value)
    print(f"  TX Signature: {tx_sig}")
    print(f"  Waiting for confirmation...")

    # Wait for confirmation
    client.confirm_transaction(result.value)
    print(f"  Entered! Transaction confirmed.")
    return True

def register_agent(wallet, name):
    """Register agent via API"""
    try:
        response = httpx.post(
            f"{CONFIG['API_URL']}/register",
            json={"wallet": wallet, "name": name},
            timeout=10
        )
        return response.json()
    except Exception as e:
        return {"error": str(e)}

def get_agent_state(wallet):
    """Get agent state from API"""
    try:
        response = httpx.get(
            f"{CONFIG['API_URL']}/agent/{wallet}/state",
            timeout=10
        )
        return response.json()
    except Exception as e:
        return {"error": str(e)}

def get_world_state():
    """Get world state from API"""
    try:
        response = httpx.get(f"{CONFIG['API_URL']}/world/state", timeout=10)
        return response.json()
    except Exception as e:
        return {"error": str(e)}

def submit_action(wallet, action, params=None):
    """Submit an action to the world"""
    try:
        response = httpx.post(
            f"{CONFIG['API_URL']}/action",
            json={
                "actor": wallet,
                "action": action,
                "params": params or {}
            },
            headers={"X-Wallet": wallet},
            timeout=10
        )
        return response.json()
    except Exception as e:
        return {"error": str(e)}

# =============================================================================
# Main
# =============================================================================

def main():
    print("=" * 60)
    print("PORT SOL - Join Game (Python)")
    print("=" * 60)

    # Connect to Solana Devnet
    client = Client(CONFIG["RPC_URL"])

    print(f"\nConnected to: {CONFIG['RPC_URL']}")

    # Treasury pubkey
    treasury_pubkey = Pubkey.from_string(CONFIG["TREASURY_PUBKEY"])

    # Create or load wallet
    keypair_str = os.getenv("KEYPAIR")

    if keypair_str:
        keypair = Keypair.from_base58_string(keypair_str)
        wallet = str(keypair.pubkey())
        print(f"Using existing wallet: {wallet}")
    else:
        # Generate new wallet
        keypair, wallet = create_wallet()
        print(f"\nNEW WALLET CREATED:")
        print(f"  Address: {wallet}")
        print(f"  Keypair: {keypair}")
        print(f"\n  SAVE THIS KEYPAIR SECURELY!")
        print(f"\n  Set environment variable:")
        print(f"    export KEYPAIR={keypair}")

    # Check balance
    balance_resp = client.get_balance(keypair.pubkey())
    balance_sol = balance_resp.value / 1_000_000_000
    print(f"\nBalance: {balance_sol} SOL")

    # Enter the world
    print("\nEntering the world...")
    if not enter_world(client, keypair, treasury_pubkey):
        return

    # Register agent
    print("\nRegistering agent...")
    agent_name = os.getenv("AGENT_NAME", f"Agent_{wallet[:8]}")
    result = register_agent(wallet, agent_name)

    if "error" in result:
        print(f"  Error: {result['error']}")
    else:
        print(f"  Registered as: {agent_name}")
        print(f"  Response: {result}")

    # Get agent state
    print("\nAgent State:")
    state = get_agent_state(wallet)
    if "error" not in state:
        print(f"  Name: {state.get('name', 'Unknown')}")
        print(f"  Region: {state.get('region', 'Unknown')}")
        print(f"  Energy: {state.get('energy', 0)}")
        print(f"  Credits: {state.get('credits', 0)}")
        print(f"  Inventory: {state.get('inventory', {})}")
    else:
        print(f"  Error: {state['error']}")

    # Show available actions
    print("\n" + "=" * 60)
    print("READY TO PLAY!")
    print("=" * 60)
    print(f"\nSubmit actions to: POST {CONFIG['API_URL']}/action")
    print(f"Headers: X-Wallet: {wallet}")
    print(f"\nExample actions:")
    print(f'  Move:    {{"actor": "{wallet}", "action": "move", "params": {{"target": "mine"}}}}')
    print(f'  Harvest: {{"actor": "{wallet}", "action": "harvest", "params": {{}}}}')
    print(f'  Sell:    {{"actor": "{wallet}", "action": "place_order", "params": {{"resource": "iron", "side": "sell", "quantity": 5}}}}')
    print(f"\nAPI Docs: {CONFIG['API_URL']}/docs")

    # Ask if user wants to run autonomous loop
    print("\n" + "-" * 60)
    run_auto = input("Run autonomous strategy loop? (y/N): ").strip().lower()

    if run_auto == 'y':
        run_autonomous_loop(wallet)

def run_autonomous_loop(wallet):
    """Simple autonomous agent loop"""
    print("\nStarting autonomous loop (Ctrl+C to stop)...")
    print("Strategy: Mine iron -> Sell at market -> Repeat")

    try:
        while True:
            state = get_agent_state(wallet)
            if "error" in state:
                print(f"Error getting state: {state['error']}")
                time.sleep(5)
                continue

            ap = state.get("energy", 0)
            region = state.get("region", "dock")
            inventory = state.get("inventory", {})
            credits = state.get("credits", 0)
            total_items = sum(inventory.values())

            print(f"\n[{region}] AP:{ap} Credits:{credits} Items:{total_items}")

            # Strategy decision
            if ap < 15:
                print("  -> Rest (low AP)")
                result = submit_action(wallet, "rest")
            elif region == "market":
                # Sell everything we have
                sold = False
                for resource, qty in inventory.items():
                    if qty > 0:
                        print(f"  -> Sell {qty} {resource}")
                        result = submit_action(wallet, "place_order", {
                            "resource": resource,
                            "side": "sell",
                            "quantity": qty
                        })
                        sold = True
                        break  # One action at a time

                if not sold:
                    print("  -> Move to mine")
                    result = submit_action(wallet, "move", {"target": "mine"})

            elif region == "mine":
                if total_items >= 8:
                    print("  -> Move to market (inventory full)")
                    result = submit_action(wallet, "move", {"target": "market"})
                else:
                    print("  -> Harvest")
                    result = submit_action(wallet, "harvest")

            else:
                # Go to mine
                print(f"  -> Move to mine")
                result = submit_action(wallet, "move", {"target": "mine"})

            # Show result
            if result.get("success"):
                print(f"      OK: {result.get('message', 'OK')}")
            else:
                print(f"      FAIL: {result.get('message', result.get('error', 'Failed'))}")

            # Wait before next action
            time.sleep(2)

    except KeyboardInterrupt:
        print("\n\nStopped by user.")

        # Show final state
        final_state = get_agent_state(wallet)
        if "error" not in final_state:
            print(f"\nFinal State:")
            print(f"  Credits: {final_state.get('credits', 0)}")
            print(f"  Inventory: {final_state.get('inventory', {})}")

if __name__ == "__main__":
    main()
