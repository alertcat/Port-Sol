"""Random event system"""
import hashlib
import random
from dataclasses import dataclass, field
from typing import List, Dict, Any
from enum import Enum

class EventType(str, Enum):
    STORM = "storm"              # Storm
    PIRATES = "pirates"          # Pirates
    TRADE_BOOM = "trade_boom"    # Trade boom
    MINE_COLLAPSE = "mine_collapse"  # Mine collapse
    FESTIVAL = "festival"        # Festival
    PLAGUE = "plague"            # Plague

# Event probability table (per tick)
# Tuned so ~1-2 events per 10 ticks (balanced gameplay)
EVENT_PROBABILITIES = {
    EventType.STORM: 0.04,
    EventType.PIRATES: 0.03,
    EventType.TRADE_BOOM: 0.06,
    EventType.MINE_COLLAPSE: 0.02,
    EventType.FESTIVAL: 0.04,
    EventType.PLAGUE: 0.01,
}

# Event durations (ticks)
EVENT_DURATIONS = {
    EventType.STORM: 5,
    EventType.PIRATES: 3,
    EventType.TRADE_BOOM: 10,
    EventType.MINE_COLLAPSE: 8,
    EventType.FESTIVAL: 5,
    EventType.PLAGUE: 15,
}

# Event descriptions
EVENT_DESCRIPTIONS = {
    EventType.STORM: "A violent storm is raging! Fishing is dangerous.",
    EventType.PIRATES: "Pirates spotted near the harbor!",
    EventType.TRADE_BOOM: "Trade is booming! Prices are up.",
    EventType.MINE_COLLAPSE: "Part of the mine has collapsed. Mining efficiency reduced.",
    EventType.FESTIVAL: "The city is celebrating! Everyone is happy.",
    EventType.PLAGUE: "A plague has struck the city. AP recovery is reduced.",
}

@dataclass
class WorldEvent:
    event_id: str
    event_type: EventType
    started_tick: int
    duration: int
    description: str
    data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "started_tick": self.started_tick,
            "duration": self.duration,
            "description": self.description,
            "data": self.data
        }

class EventSystem:
    """Event system"""
    
    @staticmethod
    def generate_seed(tick: int, state_hash: str, salt: str = "port-sol-v1") -> int:
        """Generate deterministic seed"""
        data = f"{tick}:{state_hash}:{salt}"
        return int(hashlib.sha256(data.encode()).hexdigest()[:16], 16)
    
    @staticmethod
    def check_events(tick: int, state_hash: str) -> List[WorldEvent]:
        """Check if new events should trigger"""
        seed = EventSystem.generate_seed(tick, state_hash)
        rng = random.Random(seed)
        
        triggered = []
        for event_type, prob in EVENT_PROBABILITIES.items():
            if rng.random() < prob:
                event = EventSystem.create_event(event_type, tick, rng)
                triggered.append(event)
        
        return triggered
    
    @staticmethod
    def create_event(event_type: EventType, tick: int, rng: random.Random) -> WorldEvent:
        """Create event"""
        event_id = f"{event_type.value}_{tick}_{rng.randint(1000, 9999)}"
        
        return WorldEvent(
            event_id=event_id,
            event_type=event_type,
            started_tick=tick,
            duration=EVENT_DURATIONS[event_type],
            description=EVENT_DESCRIPTIONS[event_type]
        )
    
    @staticmethod
    def get_active_effects(events: List[WorldEvent]) -> Dict[str, Any]:
        """Get effects from active events"""
        effects = {
            "harvest_modifier": 1.0,
            "price_modifier": 1.0,
            "ap_recovery_modifier": 1.0,
            "danger_level": 0
        }
        
        for event in events:
            if event.event_type == EventType.STORM:
                effects["danger_level"] += 1
                effects["harvest_modifier"] *= 0.5  # Fishing efficiency halved
            
            elif event.event_type == EventType.PIRATES:
                effects["danger_level"] += 2
            
            elif event.event_type == EventType.TRADE_BOOM:
                effects["price_modifier"] *= 1.2  # Prices up 20%
            
            elif event.event_type == EventType.MINE_COLLAPSE:
                effects["harvest_modifier"] *= 0.7  # Mining efficiency -30%
            
            elif event.event_type == EventType.PLAGUE:
                effects["ap_recovery_modifier"] *= 0.5  # AP recovery halved
        
        return effects
