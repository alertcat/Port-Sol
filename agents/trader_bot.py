"""TraderBot - Trading robot with on-chain entry

Strategy:
  1. Primary: observe market prices, buy low sell high
  2. Politics: negotiate resource trades with other agents at market
  3. Exploration: visit dock/mine/forest to buy cheap from harvesters
  4. Combat: defend credits by staying in market (protected zone)
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s [TraderBot] %(message)s')
log = logging.getLogger(__name__)

class TraderBot:
    """Trading robot: observe market, buy low sell high, negotiate trades"""
    
    EXPLORE_CHANCE = 0.10         # 10% chance to explore other regions
    NEGOTIATE_CHANCE = 0.30       # 30% chance to negotiate
    
    def __init__(self, client: PortSolClient):
        self.client = client
        self.price_history = {}
        self.cycle_count = 0
        self.explore_target = None  # Current exploration destination
    
    async def decide(self, my_state: dict, world_state: dict, all_agents: list) -> dict:
        """Decide action based on market analysis and social strategy
        
        Decision priority:
          1. Low AP → rest
          2. If exploring another region → gather intel or return
          3. Not at market → go to market
          4. Negotiate favorable trades with nearby agents
          5. Price below average → buy
          6. Price above average with stock → sell
          7. Chance to explore other regions for direct trades
          8. Watch market
        """
        energy = my_state.get("energy", 0)
        credits = my_state.get("credits", 0)
        inventory = my_state.get("inventory", {})
        region = my_state.get("region", "dock")
        reputation = my_state.get("reputation", 100)
        my_wallet = my_state.get("wallet", "")
        
        self.cycle_count += 1
        
        # Update price history
        prices = world_state.get("market_prices", {})
        for resource, price in prices.items():
            if resource not in self.price_history:
                self.price_history[resource] = []
            self.price_history[resource].append(price)
            self.price_history[resource] = self.price_history[resource][-20:]
        
        # Priority 1: Low AP, rest
        if energy < 10:
            log.info(f"Low AP ({energy}), resting")
            return {"action": "rest"}
        
        # Priority 2: Exploring another region
        if region != "market" and self.explore_target:
            if region == self.explore_target:
                # Arrived at exploration target - look for negotiate opportunities
                nearby = [a for a in all_agents 
                          if a["region"] == region 
                          and a["wallet"] != my_wallet]
                
                if nearby and credits > 100 and energy >= 15:
                    # Try to buy resources directly from harvesters at discount
                    target = random.choice(nearby)
                    for res in ["iron", "wood", "fish"]:
                        target_stock = target.get("inventory", {}).get(res, 0)
                        if target_stock >= 3:
                            market_price = prices.get(res, 10)
                            offer = int(market_price * 0.8 * 3)  # Offer 80% market price
                            log.info(f"[POLITICS] Negotiating with {target['name']}: offer {offer} credits for 3 {res}")
                            self.explore_target = None  # Done exploring
                            return {"action": "negotiate", "params": {
                                "target": target["wallet"],
                                "offer_type": "credits",
                                "offer_amount": offer,
                                "want_type": "resource",
                                "want_resource": res,
                                "want_amount": 3
                            }}
                
                # Done exploring, return to market
                log.info("[EXPLORATION] Returning to market")
                self.explore_target = None
                return {"action": "move", "params": {"target": "market"}}
            else:
                # Still traveling to explore target
                log.info(f"[EXPLORATION] Heading to {self.explore_target}")
                return {"action": "move", "params": {"target": self.explore_target}}
        
        # Priority 3: Go to market if not there
        if region != "market":
            log.info("Going to market")
            self.explore_target = None
            return {"action": "move", "params": {"target": "market"}}
        
        # Priority 4: Negotiate at market (Politics)
        if energy >= 15 and random.random() < self.NEGOTIATE_CHANCE:
            nearby = [a for a in all_agents 
                      if a["region"] == "market" 
                      and a["wallet"] != my_wallet]
            
            for target in nearby:
                target_inv = target.get("inventory", {})
                # Buy resources from other agents at slight discount
                for res in ["iron", "wood", "fish"]:
                    target_stock = target_inv.get(res, 0)
                    if target_stock >= 2 and credits > 50:
                        market_price = prices.get(res, 10)
                        offer = int(market_price * 0.9 * 2)  # 90% of market price
                        log.info(f"[POLITICS] Offer {target['name']}: {offer} credits for 2 {res}")
                        return {"action": "negotiate", "params": {
                            "target": target["wallet"],
                            "offer_type": "credits",
                            "offer_amount": offer,
                            "want_type": "resource",
                            "want_resource": res,
                            "want_amount": 2
                        }}
        
        # Priority 5: Market trading - buy low, sell high
        for resource, history in self.price_history.items():
            if len(history) < 3:
                continue
            
            current = history[-1]
            avg = sum(history) / len(history)
            my_stock = inventory.get(resource, 0)
            
            # Buy low
            if current < avg * 0.9 and credits > current * 5:
                qty = min(5, credits // current)
                log.info(f"Buy low: {resource}@{current} (avg:{avg:.1f}), qty:{qty}")
                return {"action": "place_order", "params": {
                    "resource": resource, "side": "buy", "quantity": qty
                }}
            
            # Sell high
            if current > avg * 1.1 and my_stock > 0:
                log.info(f"Sell high: {resource}@{current} (avg:{avg:.1f}), qty:{my_stock}")
                return {"action": "place_order", "params": {
                    "resource": resource, "side": "sell", "quantity": my_stock
                }}
        
        # Priority 6: Exploration - visit other regions to negotiate direct trades
        if energy >= 20 and random.random() < self.EXPLORE_CHANCE:
            explore_dest = random.choice(["mine", "dock", "forest"])
            log.info(f"[EXPLORATION] Exploring {explore_dest} for direct trade opportunities")
            self.explore_target = explore_dest
            return {"action": "move", "params": {"target": explore_dest}}
        
        log.info("Watching market, no opportunity...")
        return None  # No action
    
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
    wallet = os.getenv("TRADER_WALLET")
    keypair_json = os.getenv("TRADER_KEYPAIR")

    if not wallet or not keypair_json:
        log.error("TRADER_WALLET and TRADER_KEYPAIR must be set in .env")
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
    result = await client.register("TraderBot")
    log.info(f"Registration: {result.get('message', result)}")
    
    if not result.get('success'):
        log.error(f"Registration failed: {result}")
        return
    
    # 3. Run bot loop
    log.info("Starting bot loop...")
    bot = TraderBot(client)
    while True:
        await bot.run_cycle()
        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
