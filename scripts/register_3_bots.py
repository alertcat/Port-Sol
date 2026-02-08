#!/usr/bin/env python3
"""Register 3 bot agents on Moltbook"""
import sys
import httpx
import json
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

MOLTBOOK_API = "https://www.moltbook.com/api/v1"

def register_agent(name: str, description: str) -> dict:
    """Register agent and return credentials"""
    print(f"\n{'='*60}")
    print(f"Registering: {name}")
    print('='*60)
    
    try:
        response = httpx.post(
            f"{MOLTBOOK_API}/agents/register",
            json={"name": name, "description": description},
            timeout=30.0
        )
        
        print(f"Status: {response.status_code}")
        
        if response.status_code in [200, 201]:
            data = response.json()
            print(f"SUCCESS!")
            print(f"  API Key: {data.get('api_key', 'N/A')[:40]}...")
            print(f"  Verification Code: {data.get('verification_code', 'N/A')}")
            print(f"  Claim URL: {data.get('claim_url', 'N/A')}")
            return {"name": name, "success": True, **data}
        else:
            result = response.json()
            error = result.get('error', 'Unknown')
            hint = result.get('hint', '')
            print(f"FAILED: {error}")
            if hint:
                print(f"  Hint: {hint}")
            return {"name": name, "success": False, "error": error}
            
    except Exception as e:
        print(f"ERROR: {e}")
        return {"name": name, "success": False, "error": str(e)}

def main():
    timestamp = datetime.now().strftime("%m%d")
    
    # 3 bot agents to register
    bots = [
        {
            "name": f"PortSolMiner{timestamp}",
            "description": "Mining bot in Port Sol persistent world. Harvests iron and wood, trades at market. Part of the Solana Devnet AI agent ecosystem."
        },
        {
            "name": f"PortSolTrader{timestamp}",
            "description": "Trading bot in Port Sol persistent world. Buys low, sells high, arbitrages between regions. Part of the Solana Devnet AI agent ecosystem."
        },
        {
            "name": f"PortSolGovernor{timestamp}",
            "description": "Governance bot in Port Sol persistent world. Proposes and votes on world rules, manages tax policy. Part of the Solana Devnet AI agent ecosystem."
        }
    ]
    
    print("=" * 60)
    print("MOLTBOOK BOT REGISTRATION")
    print("=" * 60)
    print(f"Registering {len(bots)} bots...")
    
    results = []
    for bot in bots:
        result = register_agent(bot["name"], bot["description"])
        results.append(result)
    
    # Summary
    print("\n" + "=" * 60)
    print("REGISTRATION SUMMARY")
    print("=" * 60)
    
    successful = [r for r in results if r.get("success")]
    failed = [r for r in results if not r.get("success")]
    
    print(f"\nSuccessful: {len(successful)}")
    print(f"Failed: {len(failed)}")
    
    if successful:
        # Save credentials
        with open("moltbook_bots_credentials.json", "w") as f:
            json.dump(successful, f, indent=2)
        print(f"\nCredentials saved to: moltbook_bots_credentials.json")
        
        print("\n" + "=" * 60)
        print("TWITTER VERIFICATION REQUIRED")
        print("=" * 60)
        
        for i, bot in enumerate(successful, 1):
            print(f"\n--- Bot {i}: {bot['name']} ---")
            print(f"1. Tweet this:")
            print(f'   "Verifying my Moltbook agent: {bot.get("verification_code", "CODE")}"')
            print(f"\n2. Then visit:")
            print(f"   {bot.get('claim_url', 'URL')}")
        
        print("\n" + "=" * 60)
        print("AFTER VERIFICATION - Add to .env:")
        print("=" * 60)
        
        for bot in successful:
            name = bot["name"]
            key = bot.get("api_key", "YOUR_KEY")
            if "Miner" in name:
                print(f"MOLTBOOK_MINER_KEY={key}")
            elif "Trader" in name:
                print(f"MOLTBOOK_TRADER_KEY={key}")
            elif "Governor" in name:
                print(f"MOLTBOOK_GOVERNOR_KEY={key}")
    
    if failed:
        print("\n" + "=" * 60)
        print("FAILED REGISTRATIONS")
        print("=" * 60)
        for bot in failed:
            print(f"  {bot['name']}: {bot.get('error', 'Unknown error')}")

if __name__ == "__main__":
    main()
