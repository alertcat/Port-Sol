"""GovernorBot - Governance robot with on-chain entry

Strategy:
  1. Primary: fish at dock, sell at market (steady income)
  2. Politics: negotiate trades, build reputation through fair deals
  3. Combat: raid agents with very low reputation (punish raiders)
  4. Exploration: patrol all regions to gather world intelligence
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s [GovernorBot] %(message)s')
log = logging.getLogger(__name__)

class GovernorBot:
    """Governor robot: fish, trade, govern (punish bad actors, reward good ones)"""
    
    SELL_THRESHOLD = 5
    NEGOTIATE_CHANCE = 0.35     # 35% - governor is social
    PATROL_CHANCE = 0.15        # 15% chance to patrol other regions
    JUSTICE_RAID_CHANCE = 0.20  # 20% chance to raid low-rep agents
    
    # Patrol route: dock -> mine -> forest -> market -> dock
    PATROL_ROUTE = ["dock", "mine", "forest", "market"]
    
    def __init__(self, client: PortSolClient):
        self.client = client
        self.cycle_count = 0
        self.patrol_index = 0
        self.is_patrolling = False
    
    async def decide(self, my_state: dict, world_state: dict, all_agents: list) -> dict:
        """Decide action based on governance strategy
        
        Decision priority:
          1. Low AP → rest
          2. Patrol mode → move through regions, raid bad actors
          3. Fish inventory full → go sell at market
          4. At market → sell fish, negotiate with others
          5. Justice raid: punish agents with very low reputation
          6. Chance to start patrol (exploration)
          7. Default: go to dock → fish
        """
        energy = my_state.get("energy", 0)
        inventory = my_state.get("inventory", {})
        region = my_state.get("region", "dock")
        credits = my_state.get("credits", 0)
        reputation = my_state.get("reputation", 100)
        my_wallet = my_state.get("wallet", "")
        
        fish = inventory.get("fish", 0)
        
        self.cycle_count += 1
        
        # Priority 1: Low AP, rest
        if energy < 20:
            log.info(f"Low AP ({energy}), resting")
            self.is_patrolling = False
            return {"action": "rest"}
        
        # Priority 2: Patrolling (Exploration)
        if self.is_patrolling and energy >= 10:
            current_target = self.PATROL_ROUTE[self.patrol_index % len(self.PATROL_ROUTE)]
            
            if region == current_target:
                # Arrived at patrol point - check for bad actors
                bad_actors = [a for a in all_agents
                              if a["region"] == region
                              and a["wallet"] != my_wallet
                              and a.get("reputation", 100) < 60
                              and a.get("credits", 0) > 100
                              and region != "market"]
                
                if bad_actors and energy >= 25:
                    target = min(bad_actors, key=lambda a: a.get("reputation", 100))
                    log.info(f"[COMBAT/JUSTICE] Punishing bad actor {target['name']} (rep: {target.get('reputation', '?')})")
                    self.patrol_index += 1
                    return {"action": "raid", "params": {"target": target["wallet"]}}
                
                # Move to next patrol point
                self.patrol_index += 1
                if self.patrol_index >= len(self.PATROL_ROUTE):
                    log.info("[EXPLORATION] Patrol complete, returning to normal")
                    self.is_patrolling = False
                    self.patrol_index = 0
                else:
                    next_target = self.PATROL_ROUTE[self.patrol_index % len(self.PATROL_ROUTE)]
                    log.info(f"[EXPLORATION] Patrol: moving to {next_target}")
                    return {"action": "move", "params": {"target": next_target}}
            else:
                log.info(f"[EXPLORATION] Patrol: heading to {current_target}")
                return {"action": "move", "params": {"target": current_target}}
        
        # Priority 3: Fish inventory full, go to market to sell
        if fish >= self.SELL_THRESHOLD:
            if region != "market":
                log.info(f"Inventory full ({fish} fish), going to market")
                return {"action": "move", "params": {"target": "market"}}
            else:
                log.info(f"Selling {fish} fish")
                return {"action": "place_order", "params": {
                    "resource": "fish", "side": "sell", "quantity": fish
                }}
        
        # Priority 4: Negotiate at market (Politics) - governor prefers fair trades
        if region == "market" and energy >= 15 and random.random() < self.NEGOTIATE_CHANCE:
            nearby = [a for a in all_agents 
                      if a["region"] == "market" 
                      and a["wallet"] != my_wallet]
            
            for target in nearby:
                target_inv = target.get("inventory", {})
                # Offer fish for iron (fair trade based on market prices)
                target_iron = target_inv.get("iron", 0)
                my_fish = inventory.get("fish", 0)
                
                if target_iron >= 2 and my_fish >= 2:
                    prices = world_state.get("market_prices", {})
                    iron_price = prices.get("iron", 15)
                    fish_price = prices.get("fish", 8)
                    # Offer fair amount of fish for iron
                    fish_needed = max(2, int(2 * iron_price / fish_price))
                    fish_to_offer = min(fish_needed, my_fish)
                    
                    log.info(f"[POLITICS] Offering {fish_to_offer} fish for 2 iron to {target['name']}")
                    return {"action": "negotiate", "params": {
                        "target": target["wallet"],
                        "offer_type": "resource",
                        "offer_resource": "fish",
                        "offer_amount": fish_to_offer,
                        "want_type": "resource",
                        "want_resource": "iron",
                        "want_amount": 2
                    }}
                
                # Offer credits for resources 
                for res in ["iron", "wood"]:
                    target_stock = target_inv.get(res, 0)
                    if target_stock >= 3 and credits > 100:
                        prices = world_state.get("market_prices", {})
                        fair_price = int(prices.get(res, 10) * 3 * 1.05)  # 5% above market
                        log.info(f"[POLITICS] Offering {fair_price} credits for 3 {res} to {target['name']}")
                        return {"action": "negotiate", "params": {
                            "target": target["wallet"],
                            "offer_type": "credits",
                            "offer_amount": fair_price,
                            "want_type": "resource",
                            "want_resource": res,
                            "want_amount": 3
                        }}
        
        # Priority 5: Justice raid - punish agents with lower reputation
        if energy >= 25 and random.random() < self.JUSTICE_RAID_CHANCE:
            raid_targets = [a for a in all_agents
                            if a["region"] == region
                            and a["wallet"] != my_wallet
                            and a.get("reputation", 100) < reputation
                            and a.get("credits", 0) > 100
                            and region != "market"]
            if raid_targets:
                target = min(raid_targets, key=lambda a: a.get("reputation", 100))
                log.info(f"[COMBAT/JUSTICE] Raiding {target['name']} (rep: {target.get('reputation', '?')}, credits: {target['credits']})")
                return {"action": "raid", "params": {"target": target["wallet"]}}
        
        # Priority 6: Start patrol (Exploration)
        if energy >= 40 and random.random() < self.PATROL_CHANCE:
            log.info("[EXPLORATION] Starting patrol of all regions")
            self.is_patrolling = True
            self.patrol_index = 0
            first_target = self.PATROL_ROUTE[0]
            if region == first_target:
                self.patrol_index = 1
                first_target = self.PATROL_ROUTE[1]
            return {"action": "move", "params": {"target": first_target}}
        
        # Default: Go to dock and fish
        if region != "dock":
            log.info("Going to dock")
            return {"action": "move", "params": {"target": "dock"}}
        
        log.info("Fishing")
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
    wallet = os.getenv("GOVERNOR_WALLET")
    keypair_json = os.getenv("GOVERNOR_KEYPAIR")

    if not wallet or not keypair_json:
        log.error("GOVERNOR_WALLET and GOVERNOR_KEYPAIR must be set in .env")
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
    result = await client.register("GovernorBot")
    log.info(f"Registration: {result.get('message', result)}")
    
    if not result.get('success'):
        log.error(f"Registration failed: {result}")
        return
    
    # 3. Run bot loop
    log.info("Starting bot loop...")
    bot = GovernorBot(client)
    while True:
        await bot.run_cycle()
        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
