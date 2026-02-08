"""World Engine Core: WorldState, Agent, WorldEngine with PostgreSQL persistence"""
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
from datetime import datetime, timezone

class Region(str, Enum):
    DOCK = "dock"
    MARKET = "market"
    MINE = "mine"
    FOREST = "forest"

class Resource(str, Enum):
    IRON = "iron"
    WOOD = "wood"
    FISH = "fish"

# AP cost table
AP_COSTS = {
    "move": 5,
    "harvest": 10,
    "place_order": 3,
    "rest": 0,
    "raid": 25,       # Combat: attack another agent to steal credits
    "negotiate": 15,  # Politics: propose trade with another agent
}

# Harvest yields (region -> resources)
HARVEST_YIELDS = {
    Region.MINE: [Resource.IRON],
    Region.FOREST: [Resource.WOOD],
    Region.DOCK: [Resource.FISH],
}

@dataclass
class Agent:
    wallet: str
    name: str
    region: Region = Region.DOCK
    energy: int = 100
    max_energy: int = 100
    reputation: int = 100
    credits: int = 1000
    inventory: Dict[str, int] = field(default_factory=dict)
    entered_at: int = 0
    
    def to_dict(self) -> dict:
        return {
            "wallet": self.wallet,
            "name": self.name,
            "region": self.region.value if isinstance(self.region, Region) else self.region,
            "energy": self.energy,
            "max_energy": self.max_energy,
            "reputation": self.reputation,
            "credits": self.credits,
            "inventory": self.inventory,
            "entered_at": self.entered_at
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Agent":
        """Create Agent from dictionary (e.g., from database)"""
        region = data.get("region", "dock")
        if isinstance(region, str):
            try:
                region = Region(region)
            except ValueError:
                region = Region.DOCK
        
        inventory = data.get("inventory", {})
        if isinstance(inventory, str):
            inventory = json.loads(inventory)
        
        return cls(
            wallet=data["wallet"],
            name=data["name"],
            region=region,
            energy=data.get("energy", 100),
            max_energy=data.get("max_energy", 100),
            reputation=data.get("reputation", 100),
            credits=data.get("credits", 1000),
            inventory=inventory,
            entered_at=data.get("entered_at", 0)
        )

@dataclass 
class WorldState:
    tick: int = 0
    tax_rate: float = 0.05
    market_prices: Dict[str, int] = field(default_factory=lambda: {
        "iron": 15,
        "wood": 12,
        "fish": 8,
    })
    active_events: List = field(default_factory=list)
    state_hash: str = ""

class WorldEngine:
    """World Engine main class with PostgreSQL persistence"""
    
    def __init__(self, use_database: bool = True):
        self.state = WorldState()
        self.agents: Dict[str, Agent] = {}
        self.ledger: List[dict] = []
        self._use_database = use_database
        self._db = None
        
        if use_database:
            self._init_database()
        
        self._compute_state_hash()
    
    def _init_database(self):
        """Initialize database connection"""
        try:
            from engine.database import get_database
            self._db = get_database()
            
            # Load existing state from database
            self._load_from_database()
        except Exception as e:
            print(f"Database initialization failed: {e}")
            self._db = None
    
    def _load_from_database(self):
        """Load state from database"""
        if not self._db:
            return
        
        # Load world state
        world_state = self._db.get_latest_world_state()
        if world_state:
            self.state.tick = world_state.get("tick", 0)
            self.state.state_hash = world_state.get("state_hash", "")
            if world_state.get("market_prices"):
                self.state.market_prices = world_state["market_prices"]
        
        # Load agents
        agents = self._db.get_all_agents()
        for agent_data in agents:
            agent = Agent.from_dict(agent_data)
            self.agents[agent.wallet] = agent
        
        print(f"Loaded {len(self.agents)} agents from database, tick={self.state.tick}")
    
    def _save_to_database(self):
        """Save current state to database"""
        if not self._db:
            return
        
        # Save world state
        events_data = [e.to_dict() for e in self.state.active_events] if self.state.active_events else []
        self._db.save_world_state(
            self.state.tick,
            self.state.state_hash,
            self.state.market_prices,
            events_data
        )
        
        # Save all agents
        for agent in self.agents.values():
            self._db.save_agent(agent.to_dict())
    
    def _compute_state_hash(self) -> str:
        """Compute world state hash"""
        events_list = []
        for e in self.state.active_events:
            if hasattr(e, 'event_id'):
                events_list.append(e.event_id)
            elif isinstance(e, dict):
                events_list.append(e.get('event_id', ''))
        
        state_data = {
            "tick": self.state.tick,
            "prices": self.state.market_prices,
            "events": events_list,
            "agents": {
                w: {"region": a.region.value if isinstance(a.region, Region) else a.region, 
                    "inv": sum(a.inventory.values())}
                for w, a in sorted(self.agents.items())
            }
        }
        self.state.state_hash = hashlib.sha256(
            json.dumps(state_data, sort_keys=True).encode()
        ).hexdigest()[:16]
        return self.state.state_hash
    
    def register_agent(self, wallet: str, name: str) -> Agent:
        """Register new agent"""
        if wallet in self.agents:
            return self.agents[wallet]
        
        agent = Agent(wallet=wallet, name=name, entered_at=self.state.tick)
        self.agents[wallet] = agent
        
        # Save to database
        if self._db:
            self._db.save_agent(agent.to_dict())
        
        self._log_action(wallet, "register", {"name": name}, True, "Agent registered")
        return agent
    
    def get_agent(self, wallet: str) -> Optional[Agent]:
        """Get agent by wallet"""
        return self.agents.get(wallet)
    
    def update_agent(self, agent: Agent):
        """Update agent and persist to database"""
        self.agents[agent.wallet] = agent
        if self._db:
            self._db.save_agent(agent.to_dict())
    
    def get_public_state(self) -> dict:
        """Get public world state"""
        events_data = []
        for e in self.state.active_events:
            if hasattr(e, 'started_tick'):
                remaining = e.started_tick + e.duration - self.state.tick
                events_data.append({
                    "type": e.event_type.value if hasattr(e.event_type, 'value') else str(e.event_type),
                    "description": getattr(e, 'description', ''),
                    "remaining": remaining
                })
            elif isinstance(e, dict):
                events_data.append(e)
        
        return {
            "tick": self.state.tick,
            "tax_rate": self.state.tax_rate,
            "market_prices": self.state.market_prices,
            "active_events": events_data,
            "agent_count": len(self.agents),
            "state_hash": self.state.state_hash
        }
    
    def _log_action(self, wallet: str, action: str, params: dict, success: bool, message: str):
        """Log action to ledger"""
        entry = {
            "tick": self.state.tick,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "wallet": wallet,
            "action": action,
            "params": params,
            "success": success,
            "message": message,
            "state_hash": self.state.state_hash
        }
        self.ledger.append(entry)
        
        # Save to database
        if self._db:
            self._db.log_action(
                self.state.tick, wallet, action, params,
                {}, success, message, self.state.state_hash
            )
    
    def _update_market_prices(self, effects: dict):
        """
        Update market prices based on supply/demand dynamics.
        
        Mechanics:
        - Track total resources sold/bought per tick
        - High supply (lots of selling) → price drops
        - Low supply (lots of buying) → price rises
        - Random fluctuation ±5%
        - Event modifiers (trade_boom = +20%)
        - Prices clamped to min 3, max 50
        """
        import random as rng
        
        base_prices = {"iron": 15, "wood": 12, "fish": 8}
        
        # Count total inventory of each resource across all agents (supply indicator)
        total_supply = {}
        for agent in self.agents.values():
            for res, qty in agent.inventory.items():
                total_supply[res] = total_supply.get(res, 0) + qty
        
        for resource in self.state.market_prices:
            current = self.state.market_prices[resource]
            base = base_prices.get(resource, 10)
            supply = total_supply.get(resource, 0)
            
            # Supply pressure: more supply → lower price
            # Each unit of supply pushes price down slightly
            supply_factor = max(0.7, 1.0 - supply * 0.01)
            
            # Random fluctuation ±8%
            noise = rng.uniform(0.92, 1.08)
            
            # Mean reversion toward base price (weak pull)
            reversion = 1.0 + (base - current) * 0.02
            
            # Event modifier
            event_mod = effects.get("price_modifier", 1.0)
            
            # Calculate new price
            new_price = current * supply_factor * noise * reversion * event_mod
            
            # Clamp
            new_price = max(3, min(50, int(round(new_price))))
            
            self.state.market_prices[resource] = new_price
    
    def process_tick(self) -> dict:
        """Process one tick"""
        from engine.events import EventSystem
        
        # 1. Clean up expired events
        self.state.active_events = [
            e for e in self.state.active_events 
            if hasattr(e, 'started_tick') and e.started_tick + e.duration > self.state.tick
        ]
        
        # 2. Check for new events
        new_events = EventSystem.check_events(self.state.tick, self.state.state_hash)
        self.state.active_events.extend(new_events)
        
        # 3. Save new events to database
        if self._db and new_events:
            for event in new_events:
                self._db.save_event(
                    self.state.tick,
                    event.event_type.value if hasattr(event.event_type, 'value') else str(event.event_type),
                    event.to_dict(),
                    event.duration,
                    event.started_tick,
                    event.started_tick + event.duration
                )
        
        # 4. Get event effects
        effects = EventSystem.get_active_effects(self.state.active_events)
        
        # 5. Update market prices based on supply/demand
        self._update_market_prices(effects)
        
        # 6. Natural AP recovery (affected by events)
        base_recovery = 5
        actual_recovery = int(base_recovery * effects["ap_recovery_modifier"])
        for agent in self.agents.values():
            agent.energy = min(agent.max_energy, agent.energy + actual_recovery)
        
        # 7. Advance tick
        self.state.tick += 1
        
        # 8. Recompute state hash
        self._compute_state_hash()
        
        # 9. Persist to database
        self._save_to_database()
        
        return {
            "tick": self.state.tick,
            "state_hash": self.state.state_hash,
            "agent_count": len(self.agents),
            "market_prices": dict(self.state.market_prices),
            "new_events": [e.to_dict() for e in new_events] if new_events else [],
            "ap_recovery": actual_recovery
        }
