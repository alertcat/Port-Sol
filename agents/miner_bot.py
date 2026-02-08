"""MinerBot - Mining robot with on-chain entry

Strategy:
  1. Primary: harvest iron/wood in mine, sell at market
  2. Combat: raid nearby agents when strong and target is weak
  3. Exploration: periodically visit forest for wood diversification
  4. Politics: negotiate resource trades when profitable
"""
import asyncio
import os
import random
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load .env
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

from sdk.client import PortSolClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s [MinerBot] %(message)s')
log = logging.getLogger(__name__)

class MinerBot:
    """Miner robot: harvest -> sell, with combat and exploration"""
    
    SELL_THRESHOLD = 10
    EXPLORE_CHANCE = 0.15       # 15% chance to explore forest
    RAID_CHANCE = 0.20          # 20% chance to raid when conditions met
    NEGOTIATE_CHANCE = 0.25     # 25% chance to negotiate a trade
    
    def __init__(self, client: PortSolClient):
        self.client = client
        self.cycle_count = 0
    
    async def decide(self, my_state: dict, world_state: dict, all_agents: list) -> dict:
        """Decide: return action to execute
        
        Decision priority:
          1. Low AP → rest
          2. Inventory full → go sell at market
          3. At market with inventory → sell
          4. At market, consider negotiate with nearby agents
          5. Chance to raid weak agent in same region
          6. Chance to explore forest for wood
          7. Default: go to mine → harvest
        """
        energy = my_state.get("energy", 0)
        inventory = my_state.get("inventory", {})
        region = my_state.get("region", "dock")
        credits = my_state.get("credits", 0)
        reputation = my_state.get("reputation", 100)
        my_wallet = my_state.get("wallet", "")
        
        iron = inventory.get("iron", 0)
        wood = inventory.get("wood", 0)
        total_resources = iron + wood
        
        self.cycle_count += 1
        
        # Priority 1: Low AP, rest
        if energy < 20:
            log.info(f"Low AP ({energy}), resting")
            return {"action": "rest"}
        
        # Priority 2: Inventory full, go to market to sell
        if total_resources >= self.SELL_THRESHOLD:
            if region != "market":
                log.info(f"Inventory full ({total_resources}), going to market")
                return {"action": "move", "params": {"target": "market"}}
            else:
                # At market: sell resources
                if iron > 0:
                    log.info(f"Selling {iron} iron")
                    return {"action": "place_order", "params": {
                        "resource": "iron", "side": "sell", "quantity": iron
                    }}
                if wood > 0:
                    log.info(f"Selling {wood} wood")
                    return {"action": "place_order", "params": {
                        "resource": "wood", "side": "sell", "quantity": wood
                    }}
        
        # Priority 3: Negotiate (Politics) - trade resources with nearby agent
        if region == "market" and energy >= 15 and random.random() < self.NEGOTIATE_CHANCE:
            nearby = [a for a in all_agents 
                      if a["region"] == region 
                      and a["wallet"] != my_wallet
                      and a.get("inventory", {}).get("fish", 0) > 0]
            if nearby and iron >= 2:
                target = random.choice(nearby)
                log.info(f"[POLITICS] Negotiating with {target['name']}: offer 2 iron for 3 fish")
                return {"action": "negotiate", "params": {
                    "target": target["wallet"],
                    "offer_type": "resource",
                    "offer_resource": "iron",
                    "offer_amount": 2,
                    "want_type": "resource",
                    "want_resource": "fish",
                    "want_amount": 3
                }}
        
        # Priority 4: Raid (Combat) - attack nearby agents for their credits
        if energy >= 25 and random.random() < self.RAID_CHANCE:
            raid_targets = [a for a in all_agents 
                            if a["region"] == region 
                            and a["wallet"] != my_wallet
                            and region != "market"
                            and a.get("credits", 0) > 200]
            if raid_targets:
                target = max(raid_targets, key=lambda a: a.get("credits", 0))
                log.info(f"[COMBAT] Raiding {target['name']} (credits: {target['credits']}, rep: {target.get('reputation', '?')})")
                return {"action": "raid", "params": {"target": target["wallet"]}}
        
        # Priority 5: Exploration - visit forest for wood
        if region == "mine" and random.random() < self.EXPLORE_CHANCE and energy >= 15:
            log.info("[EXPLORATION] Heading to forest to gather wood")
            return {"action": "move", "params": {"target": "forest"}}
        
        # Priority 6: Harvest in forest (if exploring)
        if region == "forest":
            if wood >= 5:
                log.info(f"[EXPLORATION] Got enough wood ({wood}), returning to mine")
                return {"action": "move", "params": {"target": "mine"}}
            log.info("[EXPLORATION] Gathering wood in forest")
            return {"action": "harvest"}
        
        # Default: Go to mine and harvest
        if region != "mine":
            log.info("Going to mine")
            return {"action": "move", "params": {"target": "mine"}}
        
        log.info("Mining")
        return {"action": "harvest"}
    
    async def run_cycle(self):
        """Run one decision cycle"""
        try:
            my_state = await self.client.get_my_state()
            if "error" in my_state:
                log.error(f"Failed to get state: {my_state}")
                return None
            
            world_state = await self.client.get_world_state()
            
            # Get all agents for social interactions
            session = await self.client._get_session()
            async with session.get(f"{self.client.api_url}/agents") as resp:
                agents_data = await resp.json()
            all_agents = agents_data.get("agents", [])
            
            action = await self.decide(my_state, world_state, all_agents)
            
            if action:
                result = await self.client.submit_action(
                    action["action"],
                    action.get("params", {})
                )
                log.info(f"Result: {result.get('message', result)}")
                return result
        except Exception as e:
            log.error(f"Cycle failed: {e}")
        return None

async def main():
    api_url = os.getenv("API_URL", "http://localhost:8000")
    wallet = os.getenv("MINER_WALLET")
    keypair_json = os.getenv("MINER_KEYPAIR")

    if not wallet or not keypair_json:
        log.error("MINER_WALLET and MINER_KEYPAIR must be set in .env")
        return

    log.info(f"Wallet: {wallet}")
    client = PortSolClient(api_url, wallet, keypair_json)
    log.info(f"Balance: {client.get_balance()} SOL")
    
    # 1. Ensure entered on-chain
    log.info("Checking on-chain entry status...")
    if not await client.ensure_entered():
        log.error("Failed to enter world on-chain")
        return
    
    # 2. Register with API
    log.info(f"Registering with API...")
    result = await client.register("MinerBot")
    log.info(f"Registration: {result.get('message', result)}")
    
    if not result.get('success'):
        log.error(f"Registration failed: {result}")
        return
    
    # 3. Run bot loop
    log.info("Starting bot loop...")
    bot = MinerBot(client)
    while True:
        await bot.run_cycle()
        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
