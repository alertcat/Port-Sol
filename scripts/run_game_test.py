#!/usr/bin/env python3
"""
Run a full game simulation test - faithfully replicating actual agent behavior.

- Uses REAL wallet addresses (blockchain-connected agents)
- Agent decision logic is IDENTICAL to agents/miner_bot.py, trader_bot.py, governor_bot.py
- Includes: harvest, trade, combat (raid), politics (negotiate), exploration
- ONLY Moltbook posting is disabled (dry run mode)
- Tick is reset to 0 at start

Usage:
    python run_game_test.py
    python run_game_test.py --rounds 10
"""
import os
import sys
import time
import random
import requests
import logging

# Fix Windows encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# API endpoint
API_URL = os.getenv("API_URL", "http://localhost:8000")

# NOTE: Server must be started with DEBUG_MODE=true for /debug/* endpoints to work
# e.g.: cmd /c "set DEBUG_MODE=true && set MOLTBOOK_DRY_RUN=true && python app.py"

# Real agent wallets (on-chain)
REAL_AGENTS = {
    "MinerBot": os.getenv("MINER_WALLET", "MinerBotSolWallet"),
    "TraderBot": os.getenv("TRADER_WALLET", "TraderBotSolWallet"),
    "GovernorBot": os.getenv("GOVERNOR_WALLET", "GovernorBotSolWallet"),
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s')

# ---- API helpers ----

def api_get(endpoint: str):
    try:
        r = requests.get(f"{API_URL}{endpoint}")
        if r.status_code == 200:
            return r.json()
        return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}

def api_post(endpoint: str, data: dict = None):
    try:
        r = requests.post(f"{API_URL}{endpoint}", json=data or {})
        if r.status_code == 200:
            return r.json()
        return {"success": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def submit_action(wallet: str, action: str, params: dict = None):
    data = {"actor": wallet, "action": action, "params": params or {}}
    return api_post("/action", data)

def get_agent_state(wallet: str):
    return api_get(f"/agent/{wallet}/state")

def get_world_state():
    return api_get("/world/state")

def get_all_agents():
    result = api_get("/agents")
    return result.get("agents", [])


# ============================================================
# Agent decision logic - IDENTICAL to actual agent scripts
# ============================================================

class MinerBotLogic:
    """Exact replica of agents/miner_bot.py MinerBot.decide()"""
    
    SELL_THRESHOLD = 10
    EXPLORE_CHANCE = 0.15
    RAID_CHANCE = 0.20
    NEGOTIATE_CHANCE = 0.25
    log = logging.getLogger("MinerBot")
    cycle_count = 0
    
    @classmethod
    def decide(cls, my_state: dict, world_state: dict, all_agents: list) -> dict:
        energy = my_state.get("energy", 0)
        inventory = my_state.get("inventory", {})
        region = my_state.get("region", "dock")
        credits = my_state.get("credits", 0)
        reputation = my_state.get("reputation", 100)
        my_wallet = my_state.get("wallet", "")
        
        iron = inventory.get("iron", 0)
        wood = inventory.get("wood", 0)
        total_resources = iron + wood
        
        cls.cycle_count += 1
        
        # Priority 1: Low AP, rest
        if energy < 20:
            cls.log.info(f"Low AP ({energy}), resting")
            return {"action": "rest"}
        
        # Priority 2: Inventory full, go to market to sell
        if total_resources >= cls.SELL_THRESHOLD:
            if region != "market":
                cls.log.info(f"Inventory full ({total_resources}), going to market")
                return {"action": "move", "params": {"target": "market"}}
            else:
                if iron > 0:
                    cls.log.info(f"Selling {iron} iron")
                    return {"action": "place_order", "params": {
                        "resource": "iron", "side": "sell", "quantity": iron
                    }}
                if wood > 0:
                    cls.log.info(f"Selling {wood} wood")
                    return {"action": "place_order", "params": {
                        "resource": "wood", "side": "sell", "quantity": wood
                    }}
        
        # Priority 3: Negotiate (Politics)
        if region == "market" and energy >= 15 and random.random() < cls.NEGOTIATE_CHANCE:
            nearby = [a for a in all_agents 
                      if a["region"] == region 
                      and a["wallet"] != my_wallet
                      and a.get("inventory", {}).get("fish", 0) > 0]
            if nearby and iron >= 2:
                target = random.choice(nearby)
                cls.log.info(f"[POLITICS] Negotiating with {target['name']}: offer 2 iron for 3 fish")
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
        if energy >= 25 and random.random() < cls.RAID_CHANCE:
            raid_targets = [a for a in all_agents 
                            if a["region"] == region 
                            and a["wallet"] != my_wallet
                            and region != "market"
                            and a.get("credits", 0) > 200]
            if raid_targets:
                target = max(raid_targets, key=lambda a: a.get("credits", 0))
                cls.log.info(f"[COMBAT] Raiding {target['name']} (credits: {target['credits']}, rep: {target.get('reputation', '?')})")
                return {"action": "raid", "params": {"target": target["wallet"]}}
        
        # Priority 5: Exploration - visit forest
        if region == "mine" and random.random() < cls.EXPLORE_CHANCE and energy >= 15:
            cls.log.info("[EXPLORATION] Heading to forest to gather wood")
            return {"action": "move", "params": {"target": "forest"}}
        
        # Priority 6: Harvest in forest (if exploring)
        if region == "forest":
            if wood >= 5:
                cls.log.info(f"[EXPLORATION] Got enough wood ({wood}), returning to mine")
                return {"action": "move", "params": {"target": "mine"}}
            cls.log.info("[EXPLORATION] Gathering wood in forest")
            return {"action": "harvest"}
        
        # Default: Go to mine and harvest
        if region != "mine":
            cls.log.info("Going to mine")
            return {"action": "move", "params": {"target": "mine"}}
        
        cls.log.info("Mining")
        return {"action": "harvest"}


class TraderBotLogic:
    """Exact replica of agents/trader_bot.py TraderBot.decide()"""
    
    EXPLORE_CHANCE = 0.10
    NEGOTIATE_CHANCE = 0.30
    log = logging.getLogger("TraderBot")
    price_history = {}
    cycle_count = 0
    explore_target = None
    
    @classmethod
    def decide(cls, my_state: dict, world_state: dict, all_agents: list) -> dict:
        energy = my_state.get("energy", 0)
        credits = my_state.get("credits", 0)
        inventory = my_state.get("inventory", {})
        region = my_state.get("region", "dock")
        reputation = my_state.get("reputation", 100)
        my_wallet = my_state.get("wallet", "")
        
        cls.cycle_count += 1
        
        # Update price history
        prices = world_state.get("market_prices", {})
        for resource, price in prices.items():
            if resource not in cls.price_history:
                cls.price_history[resource] = []
            cls.price_history[resource].append(price)
            cls.price_history[resource] = cls.price_history[resource][-20:]
        
        # Priority 1: Low AP
        if energy < 10:
            cls.log.info(f"Low AP ({energy}), resting")
            return {"action": "rest"}
        
        # Priority 2: Exploring another region
        if region != "market" and cls.explore_target:
            if region == cls.explore_target:
                nearby = [a for a in all_agents 
                          if a["region"] == region 
                          and a["wallet"] != my_wallet]
                
                if nearby and credits > 100 and energy >= 15:
                    target = random.choice(nearby)
                    for res in ["iron", "wood", "fish"]:
                        target_stock = target.get("inventory", {}).get(res, 0)
                        if target_stock >= 3:
                            market_price = prices.get(res, 10)
                            offer = int(market_price * 0.8 * 3)
                            cls.log.info(f"[POLITICS] Negotiating with {target['name']}: offer {offer} credits for 3 {res}")
                            cls.explore_target = None
                            return {"action": "negotiate", "params": {
                                "target": target["wallet"],
                                "offer_type": "credits",
                                "offer_amount": offer,
                                "want_type": "resource",
                                "want_resource": res,
                                "want_amount": 3
                            }}
                
                cls.log.info("[EXPLORATION] Returning to market")
                cls.explore_target = None
                return {"action": "move", "params": {"target": "market"}}
            else:
                cls.log.info(f"[EXPLORATION] Heading to {cls.explore_target}")
                return {"action": "move", "params": {"target": cls.explore_target}}
        
        # Priority 3: Go to market
        if region != "market":
            cls.log.info("Going to market")
            cls.explore_target = None
            return {"action": "move", "params": {"target": "market"}}
        
        # Priority 4: Negotiate at market (Politics)
        if energy >= 15 and random.random() < cls.NEGOTIATE_CHANCE:
            nearby = [a for a in all_agents 
                      if a["region"] == "market" 
                      and a["wallet"] != my_wallet]
            
            for target in nearby:
                target_inv = target.get("inventory", {})
                for res in ["iron", "wood", "fish"]:
                    target_stock = target_inv.get(res, 0)
                    if target_stock >= 2 and credits > 50:
                        market_price = prices.get(res, 10)
                        offer = int(market_price * 0.9 * 2)
                        cls.log.info(f"[POLITICS] Offer {target['name']}: {offer} credits for 2 {res}")
                        return {"action": "negotiate", "params": {
                            "target": target["wallet"],
                            "offer_type": "credits",
                            "offer_amount": offer,
                            "want_type": "resource",
                            "want_resource": res,
                            "want_amount": 2
                        }}
        
        # Priority 5: Market trading
        for resource, history in cls.price_history.items():
            if len(history) < 3:
                continue
            current = history[-1]
            avg = sum(history) / len(history)
            my_stock = inventory.get(resource, 0)
            
            if current < avg * 0.9 and credits > current * 5:
                qty = min(5, credits // current)
                cls.log.info(f"Buy low: {resource}@{current} (avg:{avg:.1f}), qty:{qty}")
                return {"action": "place_order", "params": {
                    "resource": resource, "side": "buy", "quantity": qty
                }}
            
            if current > avg * 1.1 and my_stock > 0:
                cls.log.info(f"Sell high: {resource}@{current} (avg:{avg:.1f}), qty:{my_stock}")
                return {"action": "place_order", "params": {
                    "resource": resource, "side": "sell", "quantity": my_stock
                }}
        
        # Priority 6: Exploration
        if energy >= 20 and random.random() < cls.EXPLORE_CHANCE:
            explore_dest = random.choice(["mine", "dock", "forest"])
            cls.log.info(f"[EXPLORATION] Exploring {explore_dest} for direct trade opportunities")
            cls.explore_target = explore_dest
            return {"action": "move", "params": {"target": explore_dest}}
        
        cls.log.info("Watching market, no opportunity...")
        return None


class GovernorBotLogic:
    """Exact replica of agents/governor_bot.py GovernorBot.decide()"""
    
    SELL_THRESHOLD = 5
    NEGOTIATE_CHANCE = 0.35
    PATROL_CHANCE = 0.15
    JUSTICE_RAID_CHANCE = 0.20
    PATROL_ROUTE = ["dock", "mine", "forest", "market"]
    log = logging.getLogger("GovernorBot")
    cycle_count = 0
    patrol_index = 0
    is_patrolling = False
    
    @classmethod
    def decide(cls, my_state: dict, world_state: dict, all_agents: list) -> dict:
        energy = my_state.get("energy", 0)
        inventory = my_state.get("inventory", {})
        region = my_state.get("region", "dock")
        credits = my_state.get("credits", 0)
        reputation = my_state.get("reputation", 100)
        my_wallet = my_state.get("wallet", "")
        
        fish = inventory.get("fish", 0)
        
        cls.cycle_count += 1
        
        # Priority 1: Low AP
        if energy < 20:
            cls.log.info(f"Low AP ({energy}), resting")
            cls.is_patrolling = False
            return {"action": "rest"}
        
        # Priority 2: Patrolling (Exploration)
        if cls.is_patrolling and energy >= 10:
            current_target = cls.PATROL_ROUTE[cls.patrol_index % len(cls.PATROL_ROUTE)]
            
            if region == current_target:
                # Check for bad actors
                bad_actors = [a for a in all_agents
                              if a["region"] == region
                              and a["wallet"] != my_wallet
                              and a.get("reputation", 100) < 60
                              and a.get("credits", 0) > 100
                              and region != "market"]
                
                if bad_actors and energy >= 25:
                    target = min(bad_actors, key=lambda a: a.get("reputation", 100))
                    cls.log.info(f"[COMBAT/JUSTICE] Punishing bad actor {target['name']} (rep: {target.get('reputation', '?')})")
                    cls.patrol_index += 1
                    return {"action": "raid", "params": {"target": target["wallet"]}}
                
                cls.patrol_index += 1
                if cls.patrol_index >= len(cls.PATROL_ROUTE):
                    cls.log.info("[EXPLORATION] Patrol complete, returning to normal")
                    cls.is_patrolling = False
                    cls.patrol_index = 0
                else:
                    next_target = cls.PATROL_ROUTE[cls.patrol_index % len(cls.PATROL_ROUTE)]
                    cls.log.info(f"[EXPLORATION] Patrol: moving to {next_target}")
                    return {"action": "move", "params": {"target": next_target}}
            else:
                cls.log.info(f"[EXPLORATION] Patrol: heading to {current_target}")
                return {"action": "move", "params": {"target": current_target}}
        
        # Priority 3: Fish inventory full
        if fish >= cls.SELL_THRESHOLD:
            if region != "market":
                cls.log.info(f"Inventory full ({fish} fish), going to market")
                return {"action": "move", "params": {"target": "market"}}
            else:
                cls.log.info(f"Selling {fish} fish")
                return {"action": "place_order", "params": {
                    "resource": "fish", "side": "sell", "quantity": fish
                }}
        
        # Priority 4: Negotiate at market (Politics)
        if region == "market" and energy >= 15 and random.random() < cls.NEGOTIATE_CHANCE:
            nearby = [a for a in all_agents 
                      if a["region"] == "market" 
                      and a["wallet"] != my_wallet]
            
            for target in nearby:
                target_inv = target.get("inventory", {})
                target_iron = target_inv.get("iron", 0)
                my_fish = inventory.get("fish", 0)
                
                if target_iron >= 2 and my_fish >= 2:
                    prices = world_state.get("market_prices", {})
                    iron_price = prices.get("iron", 15)
                    fish_price = prices.get("fish", 8)
                    fish_needed = max(2, int(2 * iron_price / fish_price))
                    fish_to_offer = min(fish_needed, my_fish)
                    
                    cls.log.info(f"[POLITICS] Offering {fish_to_offer} fish for 2 iron to {target['name']}")
                    return {"action": "negotiate", "params": {
                        "target": target["wallet"],
                        "offer_type": "resource",
                        "offer_resource": "fish",
                        "offer_amount": fish_to_offer,
                        "want_type": "resource",
                        "want_resource": "iron",
                        "want_amount": 2
                    }}
                
                for res in ["iron", "wood"]:
                    target_stock = target_inv.get(res, 0)
                    if target_stock >= 3 and credits > 100:
                        prices = world_state.get("market_prices", {})
                        fair_price = int(prices.get(res, 10) * 3 * 1.05)
                        cls.log.info(f"[POLITICS] Offering {fair_price} credits for 3 {res} to {target['name']}")
                        return {"action": "negotiate", "params": {
                            "target": target["wallet"],
                            "offer_type": "credits",
                            "offer_amount": fair_price,
                            "want_type": "resource",
                            "want_resource": res,
                            "want_amount": 3
                        }}
        
        # Priority 5: Justice raid - punish agents with lower reputation
        if energy >= 25 and random.random() < cls.JUSTICE_RAID_CHANCE:
            raid_targets = [a for a in all_agents
                            if a["region"] == region
                            and a["wallet"] != my_wallet
                            and a.get("reputation", 100) < reputation
                            and a.get("credits", 0) > 100
                            and region != "market"]
            if raid_targets:
                target = min(raid_targets, key=lambda a: a.get("reputation", 100))
                cls.log.info(f"[COMBAT/JUSTICE] Raiding {target['name']} (rep: {target.get('reputation', '?')}, credits: {target['credits']})")
                return {"action": "raid", "params": {"target": target["wallet"]}}
        
        # Priority 6: Start patrol
        if energy >= 40 and random.random() < cls.PATROL_CHANCE:
            cls.log.info("[EXPLORATION] Starting patrol of all regions")
            cls.is_patrolling = True
            cls.patrol_index = 0
            first_target = cls.PATROL_ROUTE[0]
            if region == first_target:
                cls.patrol_index = 1
                first_target = cls.PATROL_ROUTE[1]
            return {"action": "move", "params": {"target": first_target}}
        
        # Default: dock → fish
        if region != "dock":
            cls.log.info("Going to dock")
            return {"action": "move", "params": {"target": "dock"}}
        
        cls.log.info("Fishing")
        return {"action": "harvest"}


AGENT_LOGIC = {
    "MinerBot": MinerBotLogic,
    "TraderBot": TraderBotLogic,
    "GovernorBot": GovernorBotLogic,
}


# ============================================================
# Display and control
# ============================================================

def print_status():
    world = get_world_state()
    agents = get_all_agents()
    
    print("\n" + "="*70)
    print(f"🌍 WORLD STATE - Tick {world.get('tick', '?')}")
    print("="*70)
    prices = world.get("market_prices", {})
    print(f"💰 Market: Iron={prices.get('iron','?')}, Wood={prices.get('wood','?')}, Fish={prices.get('fish','?')}")
    print(f"📊 Tax Rate: {world.get('tax_rate',0)*100:.1f}%")
    events = world.get("active_events", [])
    print(f"⚡ Events: {events if events else 'None'}")
    
    print(f"\n{'👥 AGENTS':-<70}")
    for agent in agents:
        inv = agent.get('inventory', {})
        inv_str = ", ".join([f"{v} {k}" for k, v in inv.items() if v > 0]) or "empty"
        print(f"  {agent['name']:12} | {agent['region']:8} | "
              f"Cr: {agent['credits']:6} | AP: {agent['energy']:3} | "
              f"Rep: {agent.get('reputation', '?'):>3} | Inv: [{inv_str}]")
    print("="*70 + "\n")


def run_simulation(rounds: int = 10):
    print("\n" + "#"*70)
    print("#" + " "*14 + "PORT SOL FULL GAME SIMULATION" + " "*14 + "#")
    print("#" + " "*8 + "(Moltbook Dry Run - No Real Posts)" + " "*16 + "#")
    print("#" + " "*8 + "Combat | Trade | Politics | Exploration" + " "*11 + "#")
    print("#"*70)
    
    # Full reset: clears DB, keeps only 3 real agents, resets everything
    print("\n🔄 Full reset (tick=0, prices=default, 3 agents, DB cleaned)...")
    result = api_post("/debug/full_reset")
    if result.get("success"):
        print(f"   ✅ {result.get('message', 'Reset complete')}")
    else:
        # Fallback to individual resets
        print(f"   ⚠️ Full reset failed: {result.get('error', '?')}")
        print("   Trying individual resets...")
        api_post("/debug/reset_world")
        api_post("/debug/delete_test_agents")
        api_post("/debug/reset_all_credits?credits=1000")
    
    # Initial status
    print_status()
    
    # Track action stats
    stats = {"harvest": 0, "move": 0, "place_order": 0, "rest": 0, 
             "raid": 0, "negotiate": 0, "watch": 0}
    
    for round_num in range(1, rounds + 1):
        print(f"\n{'='*70}")
        print(f"🎮 ROUND {round_num}/{rounds}")
        print(f"{'='*70}")
        
        world_state = get_world_state()
        all_agents = get_all_agents()
        
        for name, wallet in REAL_AGENTS.items():
            my_state = get_agent_state(wallet)
            if "error" in my_state:
                print(f"\n❌ {name}: {my_state['error']}")
                continue
            
            logic = AGENT_LOGIC[name]
            decision = logic.decide(my_state, world_state, all_agents)
            
            if decision is None:
                stats["watch"] += 1
                continue
            
            action = decision["action"]
            params = decision.get("params", {})
            stats[action] = stats.get(action, 0) + 1
            
            result = submit_action(wallet, action, params)
            
            if result.get("success"):
                print(f"   ✅ {result.get('message', 'OK')}")
            else:
                print(f"   ❌ {result.get('message', result.get('error', 'Unknown'))}")
            
            # Re-fetch agents after each action (state changed)
            all_agents = get_all_agents()
            
            time.sleep(0.2)
        
        # Advance tick
        print(f"\n⏰ Advancing tick...")
        tick_result = api_post("/debug/advance_tick")
        print(f"   Tick: {tick_result.get('tick', '?')}")
        
        print_status()
        time.sleep(0.5)
    
    # ---- FINAL SETTLEMENT: Convert all inventory to credits ----
    print("\n" + "="*70)
    print("💎 FINAL SETTLEMENT - Converting inventory to credits")
    print("="*70)
    
    world_state = get_world_state()
    prices = world_state.get("market_prices", {})
    
    for name, wallet in REAL_AGENTS.items():
        agent = get_agent_state(wallet)
        if "error" in agent:
            continue
        
        inventory = agent.get("inventory", {})
        total_value = 0
        
        for resource, qty in inventory.items():
            if qty > 0:
                price = prices.get(resource, 10)
                value = int(price * qty * 0.95)  # 5% tax
                total_value += value
                print(f"   {name}: {qty} {resource} × {price} = {value} credits (after 5% tax)")
        
        if total_value > 0:
            # Move to market and sell everything
            submit_action(wallet, "move", {"target": "market"})
            time.sleep(0.2)
            for resource, qty in inventory.items():
                if qty > 0:
                    result = submit_action(wallet, "place_order", {
                        "resource": resource, "side": "sell", "quantity": qty
                    })
                    if result.get("success"):
                        print(f"   ✅ {name}: Sold {qty} {resource}")
                    time.sleep(0.2)
        else:
            print(f"   {name}: No inventory to settle")
    
    print("="*70)
    
    # Final summary
    print("\n" + "#"*70)
    print("#" + " "*22 + "SIMULATION SUMMARY" + " "*18 + "#")
    print("#"*70)
    print(f"\n📊 Action Statistics ({rounds} rounds):")
    print(f"   ⛏️  Harvest:    {stats['harvest']}")
    print(f"   🚶 Move:       {stats['move']}")
    print(f"   📈 Trade:      {stats['place_order']}")
    print(f"   😴 Rest:       {stats['rest']}")
    print(f"   ⚔️  Raid:       {stats['raid']}")
    print(f"   🤝 Negotiate:  {stats['negotiate']}")
    print(f"   👀 Watch:      {stats['watch']}")
    print(f"   📍 Total:      {sum(stats.values())}")
    
    print(f"\n🏆 Final Standings (after settlement):")
    print_status()
    
    print("#"*70 + "\n")


def run_on_chain_setup():
    """Phase 1+2: Set entry fee, distribute SOL, enter world, fund pool."""
    print("\n" + "="*70)
    print("  ON-CHAIN SETUP: Entry Fee + Enter World + Fund Pool (SOL)")
    print("="*70)

    # Import and run setup
    import subprocess
    print("\n--- Running setup_entry_test.py ---")
    subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "setup_entry_test.py")], check=False)

    print("\n--- Running test_enter.py ---")
    subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "test_enter.py")], check=False)

    print("\nOn-chain setup complete!\n")


def run_on_chain_settlement(api_url: str):
    """Phase 4: Settle credits and distribute SOL proportionally."""
    print("\n" + "="*70)
    print("  ON-CHAIN SETTLEMENT: Distribute SOL Reward Pool by Credits")
    print("="*70)

    import subprocess
    subprocess.run([
        sys.executable,
        os.path.join(os.path.dirname(__file__), "settle_and_exit.py"),
        "--api", api_url
    ], check=False)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Port Sol full game simulation")
    parser.add_argument("--rounds", "-r", type=int, default=10, help="Number of rounds (default: 10)")
    parser.add_argument("--with-chain", action="store_true",
                        help="Enable on-chain operations: setup entry fee, enter world, settle SOL at end")
    parser.add_argument("--api", default=os.getenv("API_URL", "http://localhost:8000"))
    args = parser.parse_args()

    if args.with_chain:
        run_on_chain_setup()

    run_simulation(args.rounds)

    if args.with_chain:
        run_on_chain_settlement(args.api)
