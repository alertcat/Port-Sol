"""Rules Engine: Execute action settlements"""
import random
from typing import Dict, Any
from engine.world import (
    WorldEngine, Agent, Region, Resource, 
    AP_COSTS, HARVEST_YIELDS
)

class RulesEngine:
    """Rules Engine: Handle all action settlement logic"""
    
    def __init__(self, world: WorldEngine):
        self.world = world
    
    def execute_action(self, agent: Agent, action: str, params: Dict[str, Any]) -> dict:
        """Execute action and return result"""
        # Check AP
        ap_cost = AP_COSTS.get(action, 0)
        if action != "rest" and agent.energy < ap_cost:
            return self._fail(agent, action, params, f"Insufficient AP: need {ap_cost}, have {agent.energy}")
        
        # Dispatch to handler
        handlers = {
            "move": self._handle_move,
            "harvest": self._handle_harvest,
            "rest": self._handle_rest,
            "place_order": self._handle_place_order,
            "raid": self._handle_raid,           # Combat: steal credits
            "negotiate": self._handle_negotiate,  # Politics: trade with agent
        }
        
        handler = handlers.get(action)
        if not handler:
            return self._fail(agent, action, params, f"Unknown action: {action}")
        
        return handler(agent, params)
    
    def _success(self, agent: Agent, action: str, params: dict, message: str, data: dict = None) -> dict:
        """Success result — persist agent state changes to database"""
        self.world.update_agent(agent)
        self.world._log_action(agent.wallet, action, params, True, message)
        self.world._compute_state_hash()
        result = {
            "success": True,
            "action": action,
            "message": message,
            "agent": agent.to_dict(),
            "tick": self.world.state.tick
        }
        if data:
            result["data"] = data
        return result
    
    def _fail(self, agent: Agent, action: str, params: dict, message: str) -> dict:
        """Failure result"""
        self.world._log_action(agent.wallet, action, params, False, message)
        return {
            "success": False,
            "action": action,
            "message": message,
            "agent": agent.to_dict()
        }
    
    def _handle_move(self, agent: Agent, params: dict) -> dict:
        """Handle move action"""
        target = params.get("target")
        if not target:
            return self._fail(agent, "move", params, "Missing target region")
        
        try:
            target_region = Region(target)
        except ValueError:
            return self._fail(agent, "move", params, f"Invalid region: {target}")
        
        if agent.region == target_region:
            return self._fail(agent, "move", params, f"Already in {target}")
        
        # Deduct AP and move
        agent.energy -= AP_COSTS["move"]
        old_region = agent.region
        agent.region = target_region
        
        return self._success(
            agent, "move", params,
            f"Moved from {old_region.value} to {target_region.value}",
            {"from": old_region.value, "to": target_region.value}
        )
    
    def _handle_harvest(self, agent: Agent, params: dict) -> dict:
        """Handle harvest action"""
        if agent.region not in HARVEST_YIELDS:
            return self._fail(agent, "harvest", params, f"Cannot harvest in {agent.region.value}")
        
        # Deduct AP
        agent.energy -= AP_COSTS["harvest"]
        
        # Determine yield (use state_hash as seed for determinism)
        seed = int(self.world.state.state_hash, 16) + self.world.state.tick + hash(agent.wallet)
        rng = random.Random(seed)
        
        yields = HARVEST_YIELDS[agent.region]
        resource = rng.choice(yields)
        quantity = rng.randint(1, 5)
        
        # Add to inventory
        current = agent.inventory.get(resource.value, 0)
        agent.inventory[resource.value] = current + quantity
        
        return self._success(
            agent, "harvest", params,
            f"Harvested {quantity} {resource.value}",
            {"resource": resource.value, "quantity": quantity}
        )
    
    def _handle_rest(self, agent: Agent, params: dict) -> dict:
        """Handle rest action"""
        if agent.region == Region.DOCK:
            # Dock has a tavern — more efficient rest
            recovery = 30
        else:
            # Can rest anywhere, but dock is more efficient
            recovery = 20
        
        old_energy = agent.energy
        agent.energy = min(agent.max_energy, agent.energy + recovery)
        actual_recovery = agent.energy - old_energy
        
        return self._success(
            agent, "rest", params,
            f"Rested and recovered {actual_recovery} AP",
            {"recovery": actual_recovery}
        )
    
    def _handle_place_order(self, agent: Agent, params: dict) -> dict:
        """Handle place order (simplified: direct trade with system)"""
        resource = params.get("resource")
        side = params.get("side")  # buy/sell
        quantity = params.get("quantity", 1)
        
        if not resource or not side:
            return self._fail(agent, "place_order", params, "Missing resource or side parameter")
        
        if agent.region != Region.MARKET:
            return self._fail(agent, "place_order", params, "Must be in market to trade")
        
        price = self.world.state.market_prices.get(resource)
        if not price:
            return self._fail(agent, "place_order", params, f"Unknown resource: {resource}")
        
        if side == "sell":
            # Validate BEFORE deducting AP
            current = agent.inventory.get(resource, 0)
            if current < quantity:
                return self._fail(agent, "place_order", params, f"Insufficient inventory: {current}/{quantity}")
            
            # Deduct AP only after validation passes
            agent.energy -= AP_COSTS["place_order"]
            
            agent.inventory[resource] = current - quantity
            revenue = int(price * quantity * (1 - self.world.state.tax_rate))
            agent.credits += revenue
            
            return self._success(
                agent, "place_order", params,
                f"Sold {quantity} {resource} for {revenue} credits",
                {"resource": resource, "quantity": quantity, "revenue": revenue}
            )
        
        elif side == "buy":
            # Validate BEFORE deducting AP
            cost = price * quantity
            if agent.credits < cost:
                return self._fail(agent, "place_order", params, f"Insufficient funds: {agent.credits}/{cost}")
            
            # Deduct AP only after validation passes
            agent.energy -= AP_COSTS["place_order"]
            
            agent.credits -= cost
            current = agent.inventory.get(resource, 0)
            agent.inventory[resource] = current + quantity
            
            return self._success(
                agent, "place_order", params,
                f"Bought {quantity} {resource} for {cost} credits",
                {"resource": resource, "quantity": quantity, "cost": cost}
            )
        
        return self._fail(agent, "place_order", params, f"Invalid side: {side}")
    
    def _handle_raid(self, agent: Agent, params: dict) -> dict:
        """
        Handle raid action (Combat)
        Attack another agent in the same region to steal credits.
        
        Params:
            target: wallet address of target agent
        
        Mechanics:
            - Must be in same region as target
            - 60% base success rate, modified by reputation difference
            - Success: steal 10-25% of target's credits
            - Failure: lose 5% of own credits as penalty
            - Both agents lose reputation
        """
        target_wallet = params.get("target")
        if not target_wallet:
            return self._fail(agent, "raid", params, "Missing target wallet")
        
        # Can't raid yourself
        if target_wallet == agent.wallet:
            return self._fail(agent, "raid", params, "Cannot raid yourself")
        
        # Find target agent
        target = self.world.agents.get(target_wallet)
        if not target:
            return self._fail(agent, "raid", params, f"Target agent not found: {target_wallet}")
        
        # Must be in same region
        if agent.region != target.region:
            return self._fail(agent, "raid", params, 
                f"Target is in {target.region.value}, you are in {agent.region.value}")
        
        # Can't raid in market (protected zone)
        if agent.region == Region.MARKET:
            return self._fail(agent, "raid", params, "Cannot raid in the market (protected zone)")
        
        # Deduct AP (all validations passed)
        agent.energy -= AP_COSTS.get("raid", 25)
        
        # Calculate success rate (base 60%, modified by reputation)
        seed = int(self.world.state.state_hash, 16) + self.world.state.tick + hash(agent.wallet + target_wallet)
        rng = random.Random(seed)
        
        rep_bonus = (agent.reputation - target.reputation) / 200  # +/- 0.5 max
        success_rate = 0.6 + rep_bonus
        success_rate = max(0.2, min(0.9, success_rate))  # Clamp to 20-90%
        
        roll = rng.random()
        
        if roll < success_rate:
            # Success! Steal credits
            steal_percent = rng.uniform(0.10, 0.25)
            stolen = int(target.credits * steal_percent)
            stolen = min(stolen, target.credits)  # Can't steal more than they have
            
            target.credits -= stolen
            agent.credits += stolen
            
            # Reputation changes
            agent.reputation = max(0, agent.reputation - 10)  # Raider loses rep
            target.reputation = min(200, target.reputation + 5)  # Victim gains sympathy
            
            return self._success(
                agent, "raid", params,
                f"Raid successful! Stole {stolen} credits from {target.name}",
                {"stolen": stolen, "target": target.name, "target_remaining": target.credits}
            )
        else:
            # Failure! Pay penalty
            penalty = int(agent.credits * 0.05)
            agent.credits -= penalty
            
            # Still lose some reputation for trying
            agent.reputation = max(0, agent.reputation - 5)
            
            return self._success(
                agent, "raid", params,
                f"Raid failed! {target.name} defended successfully. Lost {penalty} credits as penalty",
                {"penalty": penalty, "target": target.name}
            )
    
    def _handle_negotiate(self, agent: Agent, params: dict) -> dict:
        """
        Handle negotiate action (Politics)
        Propose a trade with another agent. Direct exchange of resources or credits.
        
        Params:
            target: wallet address of target agent
            offer_type: "credits" or "resource"
            offer_amount: amount to offer
            offer_resource: (if offer_type is resource) which resource
            want_type: "credits" or "resource"
            want_amount: amount wanted
            want_resource: (if want_type is resource) which resource
        
        Mechanics:
            - Both agents must be in the same region
            - Simulates immediate acceptance based on fairness
            - Higher reputation = better negotiation outcomes
        """
        target_wallet = params.get("target")
        if not target_wallet:
            return self._fail(agent, "negotiate", params, "Missing target wallet")
        
        if target_wallet == agent.wallet:
            return self._fail(agent, "negotiate", params, "Cannot negotiate with yourself")
        
        # Find target
        target = self.world.agents.get(target_wallet)
        if not target:
            return self._fail(agent, "negotiate", params, f"Target agent not found")
        
        # Must be in same region
        if agent.region != target.region:
            return self._fail(agent, "negotiate", params,
                f"Target is in {target.region.value}, you are in {agent.region.value}")
        
        # Parse offer
        offer_type = params.get("offer_type", "credits")
        offer_amount = params.get("offer_amount", 0)
        offer_resource = params.get("offer_resource")
        want_type = params.get("want_type", "credits")
        want_amount = params.get("want_amount", 0)
        want_resource = params.get("want_resource")
        
        # Validate offer
        if offer_type == "credits":
            if agent.credits < offer_amount:
                return self._fail(agent, "negotiate", params, 
                    f"Insufficient credits to offer: have {agent.credits}, offering {offer_amount}")
        elif offer_type == "resource":
            if not offer_resource:
                return self._fail(agent, "negotiate", params, "Must specify offer_resource")
            if agent.inventory.get(offer_resource, 0) < offer_amount:
                return self._fail(agent, "negotiate", params,
                    f"Insufficient {offer_resource}: have {agent.inventory.get(offer_resource, 0)}")
        
        # Validate want
        if want_type == "credits":
            if target.credits < want_amount:
                return self._fail(agent, "negotiate", params,
                    f"Target has insufficient credits: {target.credits}")
        elif want_type == "resource":
            if not want_resource:
                return self._fail(agent, "negotiate", params, "Must specify want_resource")
            if target.inventory.get(want_resource, 0) < want_amount:
                return self._fail(agent, "negotiate", params,
                    f"Target has insufficient {want_resource}")
        
        # Deduct AP (all validations passed)
        agent.energy -= AP_COSTS.get("negotiate", 15)
        
        # Calculate acceptance probability based on trade fairness
        # Use market prices to estimate value
        prices = self.world.state.market_prices
        
        offer_value = offer_amount if offer_type == "credits" else offer_amount * prices.get(offer_resource, 10)
        want_value = want_amount if want_type == "credits" else want_amount * prices.get(want_resource, 10)
        
        # Fairness ratio (1.0 = perfectly fair)
        if want_value > 0:
            fairness = offer_value / want_value
        else:
            fairness = 2.0  # Free gift = always accept
        
        # Reputation bonus
        rep_bonus = (agent.reputation - 100) / 200  # +/- 0.5
        
        # Acceptance threshold (higher = harder to accept)
        # Fair trade (1.0) + good rep = easy accept
        # Unfair trade (0.5) + bad rep = likely reject
        acceptance_threshold = 0.7 - rep_bonus
        
        seed = int(self.world.state.state_hash, 16) + hash(agent.wallet + target_wallet)
        rng = random.Random(seed)
        
        # Add some randomness
        roll = rng.uniform(0.8, 1.2)
        
        if fairness * roll >= acceptance_threshold:
            # Trade accepted! Execute exchange
            
            # Transfer from agent
            if offer_type == "credits":
                agent.credits -= offer_amount
                target.credits += offer_amount
            else:
                agent.inventory[offer_resource] = agent.inventory.get(offer_resource, 0) - offer_amount
                target.inventory[offer_resource] = target.inventory.get(offer_resource, 0) + offer_amount
            
            # Transfer to agent
            if want_type == "credits":
                target.credits -= want_amount
                agent.credits += want_amount
            else:
                target.inventory[want_resource] = target.inventory.get(want_resource, 0) - want_amount
                agent.inventory[want_resource] = agent.inventory.get(want_resource, 0) + want_amount
            
            # Both gain reputation for successful trade
            agent.reputation = min(200, agent.reputation + 3)
            target.reputation = min(200, target.reputation + 3)
            
            offer_str = f"{offer_amount} {offer_resource if offer_type == 'resource' else 'credits'}"
            want_str = f"{want_amount} {want_resource if want_type == 'resource' else 'credits'}"
            
            return self._success(
                agent, "negotiate", params,
                f"Trade accepted! Exchanged {offer_str} for {want_str} with {target.name}",
                {"accepted": True, "offer": offer_str, "received": want_str, "partner": target.name}
            )
        else:
            # Trade rejected
            return self._success(
                agent, "negotiate", params,
                f"Trade rejected by {target.name}. Try a fairer offer or improve reputation.",
                {"accepted": False, "partner": target.name, "fairness": round(fairness, 2)}
            )