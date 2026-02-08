#!/usr/bin/env python3
"""Airdrop devnet SOL to all Port Sol wallets."""
import json
import time
from pathlib import Path
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.api import Client

WALLETS_DIR = Path(__file__).parent.parent / "wallets"
RPC_URL = "https://api.devnet.solana.com"

# Airdrop amounts (in SOL)
AMOUNTS = {
    "treasury": 2,
    "miner": 1,
    "trader": 1,
    "governor": 1,
}


def main():
    client = Client(RPC_URL)

    print("=" * 60)
    print("Port Sol Devnet Airdrop")
    print(f"RPC: {RPC_URL}")
    print("=" * 60)

    for name, sol_amount in AMOUNTS.items():
        keypair_file = WALLETS_DIR / f"{name}.json"
        if not keypair_file.exists():
            print(f"\n  SKIP {name}: keypair file not found")
            continue

        kp_data = json.loads(keypair_file.read_text())
        kp = Keypair.from_bytes(bytes(kp_data))
        pubkey = kp.pubkey()

        lamports = int(sol_amount * 1_000_000_000)

        print(f"\n  {name.upper()} ({pubkey})")
        print(f"    Requesting {sol_amount} SOL airdrop...")

        try:
            resp = client.request_airdrop(pubkey, lamports)
            sig = resp.value
            print(f"    TX: {sig}")

            # Wait for confirmation
            print(f"    Confirming...", end="", flush=True)
            for _ in range(30):
                time.sleep(2)
                balance_resp = client.get_balance(pubkey)
                balance = balance_resp.value / 1_000_000_000
                if balance >= sol_amount * 0.9:  # Allow for small variance
                    print(f" OK!")
                    print(f"    Balance: {balance:.4f} SOL")
                    break
                print(".", end="", flush=True)
            else:
                print(f" TIMEOUT (check balance manually)")

        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "Too Many Requests" in error_msg:
                print(f"    RATE LIMITED - wait 30s and retry, or use https://faucet.solana.com")
            else:
                print(f"    ERROR: {e}")

        # Devnet rate limit: wait between requests
        time.sleep(3)

    # Print final balances
    print(f"\n{'=' * 60}")
    print("Final Balances:")
    print(f"{'=' * 60}")

    for name in AMOUNTS:
        keypair_file = WALLETS_DIR / f"{name}.json"
        if not keypair_file.exists():
            continue
        kp_data = json.loads(keypair_file.read_text())
        kp = Keypair.from_bytes(bytes(kp_data))
        try:
            balance = client.get_balance(kp.pubkey()).value / 1_000_000_000
            print(f"  {name:10s} {kp.pubkey()}  {balance:.4f} SOL")
        except Exception:
            print(f"  {name:10s} {kp.pubkey()}  (error)")


if __name__ == "__main__":
    main()
