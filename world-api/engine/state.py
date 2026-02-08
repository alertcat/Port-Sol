"""Global state management"""
from typing import Optional
from engine.world import WorldEngine

# Global world engine instance
_world_engine: Optional[WorldEngine] = None

def get_world_engine() -> WorldEngine:
    """Get world engine instance"""
    global _world_engine
    if _world_engine is None:
        _world_engine = WorldEngine()
    return _world_engine

def reset_world_engine():
    """Reset world engine (for testing)"""
    global _world_engine
    _world_engine = None
