#!/usr/bin/env python3
"""Generate 4 Solana wallets for Port Sol: Treasury, Miner, Trader, Governor."""
import json
from pathlib import Path
from solders.keypair import Keypair

WALLETS = ["treasury", "miner", "trader", "governor"]
OUTPUT_DIR = Path(__file__).parent.parent / "wallets"


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    print("=" * 60)
    print("Port Sol Wallet Generator")
    print("=" * 60)

    env_lines = []

    for name in WALLETS:
        kp = Keypair()
        pubkey = str(kp.pubkey())
        secret_bytes = list(bytes(kp))  # 64-byte secret key as JSON array

        # Save keypair JSON (Solana CLI compatible format)
        keypair_file = OUTPUT_DIR / f"{name}.json"
        keypair_file.write_text(json.dumps(secret_bytes))

        print(f"\n  {name.upper()}")
        print(f"    Pubkey:   {pubkey}")
        print(f"    Keypair:  {keypair_file}")

        # Build .env lines
        role = name.upper()
        if name == "treasury":
            env_lines.append(f"TREASURY_PUBKEY={pubkey}")
            env_lines.append(f"TREASURY_KEYPAIR={json.dumps(secret_bytes)}")
        else:
            env_lines.append(f"{role}_WALLET={pubkey}")
            env_lines.append(f"{role}_KEYPAIR={json.dumps(secret_bytes)}")

    # Write .env snippet
    env_file = OUTPUT_DIR / "env_snippet.txt"
    env_file.write_text("\n".join(env_lines) + "\n")

    print(f"\n{'=' * 60}")
    print(f"  Keypair files saved to: {OUTPUT_DIR}")
    print(f"  .env snippet saved to:  {env_file}")
    print(f"{'=' * 60}")

    print("\n  Next steps:")
    print("  1. Fund wallets with devnet SOL:")
    print("     - Go to https://faucet.solana.com")
    print("     - Or use this script: python scripts/airdrop_devnet.py")
    print("  2. Copy env_snippet.txt contents into .env")
    print()

    # Print pubkeys for easy copy-paste to faucet
    print("  Pubkeys for faucet (copy-paste one at a time):")
    for name in WALLETS:
        kp_data = json.loads((OUTPUT_DIR / f"{name}.json").read_text())
        kp = Keypair.from_bytes(bytes(kp_data))
        print(f"    {name:10s} {kp.pubkey()}")


if __name__ == "__main__":
    main()
