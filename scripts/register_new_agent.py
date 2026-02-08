#!/usr/bin/env python3
"""Register a new Moltbook agent with unique name"""
import sys
import httpx
import json
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

MOLTBOOK_API = "https://www.moltbook.com/api/v1"

def register_agent(name: str, description: str):
    """Register agent and save credentials"""
    
    print("=" * 60)
    print(f"Registering: {name}")
    print("=" * 60)
    
    try:
        response = httpx.post(
            f"{MOLTBOOK_API}/agents/register",
            json={"name": name, "description": description},
            timeout=30.0
        )
        
        print(f"Status: {response.status_code}")
        
        if response.status_code in [200, 201]:
            data = response.json()
            
            # Save to file
            filename = f"moltbook_{name.lower().replace(' ', '_')}.json"
            with open(filename, "w") as f:
                json.dump(data, f, indent=2)
            
            print(f"\nSUCCESS! Credentials saved to: {filename}")
            print(f"\nAPI Key: {data.get('api_key', 'N/A')}")
            print(f"Claim URL: {data.get('claim_url', 'N/A')}")
            print(f"Verification Code: {data.get('verification_code', 'N/A')}")
            
            return data
        else:
            result = response.json()
            print(f"Failed: {result.get('error', 'Unknown error')}")
            print(f"Hint: {result.get('hint', '')}")
            return None
            
    except Exception as e:
        print(f"Error: {e}")
        return None

def main():
    # Generate unique name with timestamp
    timestamp = datetime.now().strftime("%m%d%H%M")
    
    agents = [
        (f"PortSolHost{timestamp}", "Port Sol world host - posts tick digests and world events"),
    ]
    
    for name, desc in agents:
        result = register_agent(name, desc)
        if result:
            print("\n" + "=" * 60)
            print("NEXT STEPS:")
            print("=" * 60)
            print(f"""
1. Tweet this (from your Twitter/X account):
   "Verifying my Moltbook agent: {result.get('verification_code', 'CODE')}"

2. Visit claim URL:
   {result.get('claim_url', 'URL')}

3. Add to .env:
   MOLTBOOK_HOST_KEY={result.get('api_key', 'KEY')}
   MOLTBOOK_MINER_KEY={result.get('api_key', 'KEY')}
   MOLTBOOK_TRADER_KEY={result.get('api_key', 'KEY')}
   MOLTBOOK_GOVERNOR_KEY={result.get('api_key', 'KEY')}

4. Run demo:
   python scripts/run_demo.py
""")

if __name__ == "__main__":
    main()
