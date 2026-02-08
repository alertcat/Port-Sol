"""PostgreSQL Database Integration"""
import os
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

# Try to import psycopg2, fall back to in-memory if not available
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor, Json
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    print("Warning: psycopg2 not installed, using in-memory storage")

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/portsol")
# Set DISABLE_POSTGRES=true to skip PostgreSQL and use in-memory storage directly
DISABLE_POSTGRES = os.getenv("DISABLE_POSTGRES", "").lower() in ("true", "1", "yes")

def parse_database_url(url: str) -> dict:
    """Parse DATABASE_URL into connection parameters"""
    # postgresql://user:password@host:port/database
    if url.startswith("postgresql://"):
        url = url[13:]
    
    # Split user:password@host:port/database
    if "@" in url:
        auth, rest = url.split("@", 1)
        if ":" in auth:
            user, password = auth.split(":", 1)
        else:
            user, password = auth, ""
    else:
        user, password = "postgres", "postgres"
        rest = url
    
    if "/" in rest:
        host_port, database = rest.rsplit("/", 1)
    else:
        host_port, database = rest, "portsol"
    
    if ":" in host_port:
        host, port = host_port.split(":", 1)
        port = int(port)
    else:
        host, port = host_port, 5432
    
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "database": database
    }

class Database:
    """PostgreSQL database wrapper with fallback to in-memory"""
    
    def __init__(self, url: str = None):
        self.url = url or DATABASE_URL
        self.config = parse_database_url(self.url)
        self._conn = None
        self._use_memory = not POSTGRES_AVAILABLE or DISABLE_POSTGRES
        
        # In-memory fallback storage
        self._memory_agents = {}
        self._memory_world_state = {}
        self._memory_actions = []
        self._memory_events = []
    
    def connect(self) -> bool:
        """Connect to database"""
        if self._use_memory:
            print("Using in-memory storage (PostgreSQL not available)")
            return True
        
        try:
            self._conn = psycopg2.connect(
                host=self.config["host"],
                port=self.config["port"],
                user=self.config["user"],
                password=self.config["password"],
                database=self.config["database"]
            )
            self._conn.autocommit = True
            print(f"Connected to PostgreSQL: {self.config['host']}:{self.config['port']}/{self.config['database']}")
            return True
        except UnicodeDecodeError:
            # On Chinese Windows, OS error messages are GBK-encoded but psycopg2
            # tries to decode them as UTF-8, causing this error.
            # The root cause is that PostgreSQL is not running or unreachable.
            print("PostgreSQL connection failed: unable to connect (OS error message encoding issue on non-UTF-8 locale)")
            print("Falling back to in-memory storage")
            self._use_memory = True
            return True
        except Exception as e:
            try:
                msg = str(e)
            except Exception:
                msg = "(error message could not be decoded)"
            print(f"PostgreSQL connection failed: {msg}")
            print("Falling back to in-memory storage")
            self._use_memory = True
            return True
    
    def init_schema(self):
        """Initialize database schema"""
        if self._use_memory:
            return
        
        schema = """
        -- World state table
        CREATE TABLE IF NOT EXISTS world_state (
            id SERIAL PRIMARY KEY,
            tick INTEGER NOT NULL,
            state_hash VARCHAR(64) NOT NULL,
            market_prices JSONB DEFAULT '{}',
            active_events JSONB DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        -- Agents table
        CREATE TABLE IF NOT EXISTS agents (
            wallet VARCHAR(42) PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            region VARCHAR(50) DEFAULT 'dock',
            energy INTEGER DEFAULT 100,
            max_energy INTEGER DEFAULT 100,
            credits INTEGER DEFAULT 1000,
            reputation INTEGER DEFAULT 100,
            inventory JSONB DEFAULT '{}',
            entered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        -- Action ledger (audit log)
        CREATE TABLE IF NOT EXISTS action_ledger (
            id SERIAL PRIMARY KEY,
            tick INTEGER NOT NULL,
            wallet VARCHAR(42) NOT NULL,
            action VARCHAR(50) NOT NULL,
            params JSONB DEFAULT '{}',
            result JSONB DEFAULT '{}',
            success BOOLEAN DEFAULT true,
            message TEXT,
            state_hash VARCHAR(64),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        -- Events log
        CREATE TABLE IF NOT EXISTS events (
            id SERIAL PRIMARY KEY,
            tick INTEGER NOT NULL,
            event_type VARCHAR(50) NOT NULL,
            event_data JSONB DEFAULT '{}',
            duration INTEGER DEFAULT 1,
            started_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        -- Indexes
        CREATE INDEX IF NOT EXISTS idx_agents_region ON agents(region);
        CREATE INDEX IF NOT EXISTS idx_action_ledger_wallet ON action_ledger(wallet);
        CREATE INDEX IF NOT EXISTS idx_action_ledger_tick ON action_ledger(tick);
        CREATE INDEX IF NOT EXISTS idx_events_tick ON events(tick);
        """
        
        with self._conn.cursor() as cur:
            cur.execute(schema)
        
        print("Database schema initialized")
    
    @contextmanager
    def cursor(self):
        """Get a database cursor"""
        if self._use_memory:
            yield None
            return
        
        cur = self._conn.cursor(cursor_factory=RealDictCursor)
        try:
            yield cur
        finally:
            cur.close()
    
    # Agent operations
    def save_agent(self, agent_data: dict):
        """Save or update an agent"""
        if self._use_memory:
            self._memory_agents[agent_data["wallet"]] = agent_data
            return
        
        with self.cursor() as cur:
            cur.execute("""
                INSERT INTO agents (wallet, name, region, energy, max_energy, credits, reputation, inventory)
                VALUES (%(wallet)s, %(name)s, %(region)s, %(energy)s, %(max_energy)s, %(credits)s, %(reputation)s, %(inventory)s)
                ON CONFLICT (wallet) DO UPDATE SET
                    name = EXCLUDED.name,
                    region = EXCLUDED.region,
                    energy = EXCLUDED.energy,
                    credits = EXCLUDED.credits,
                    reputation = EXCLUDED.reputation,
                    inventory = EXCLUDED.inventory,
                    updated_at = CURRENT_TIMESTAMP
            """, {
                **agent_data,
                "inventory": Json(agent_data.get("inventory", {}))
            })
    
    def get_agent(self, wallet: str) -> Optional[dict]:
        """Get agent by wallet"""
        if self._use_memory:
            return self._memory_agents.get(wallet)
        
        with self.cursor() as cur:
            cur.execute("SELECT * FROM agents WHERE wallet = %s", (wallet,))
            return cur.fetchone()
    
    def get_all_agents(self) -> List[dict]:
        """Get all agents"""
        if self._use_memory:
            return list(self._memory_agents.values())
        
        with self.cursor() as cur:
            cur.execute("SELECT * FROM agents ORDER BY entered_at")
            return cur.fetchall()
    
    # World state operations
    def save_world_state(self, tick: int, state_hash: str, market_prices: dict, active_events: list):
        """Save world state snapshot"""
        if self._use_memory:
            self._memory_world_state = {
                "tick": tick,
                "state_hash": state_hash,
                "market_prices": market_prices,
                "active_events": active_events
            }
            return
        
        with self.cursor() as cur:
            cur.execute("""
                INSERT INTO world_state (tick, state_hash, market_prices, active_events)
                VALUES (%s, %s, %s, %s)
            """, (tick, state_hash, Json(market_prices), Json(active_events)))
    
    def get_latest_world_state(self) -> Optional[dict]:
        """Get latest world state"""
        if self._use_memory:
            return self._memory_world_state if self._memory_world_state else None
        
        with self.cursor() as cur:
            cur.execute("SELECT * FROM world_state ORDER BY tick DESC LIMIT 1")
            return cur.fetchone()
    
    # Action ledger operations
    def log_action(self, tick: int, wallet: str, action: str, params: dict, 
                   result: dict, success: bool, message: str, state_hash: str):
        """Log an action to the ledger"""
        if self._use_memory:
            self._memory_actions.append({
                "tick": tick,
                "wallet": wallet,
                "action": action,
                "params": params,
                "result": result,
                "success": success,
                "message": message,
                "state_hash": state_hash,
                "created_at": datetime.utcnow().isoformat()
            })
            return
        
        with self.cursor() as cur:
            cur.execute("""
                INSERT INTO action_ledger (tick, wallet, action, params, result, success, message, state_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (tick, wallet, action, Json(params), Json(result), success, message, state_hash))
    
    def get_actions(self, wallet: str = None, limit: int = 100) -> List[dict]:
        """Get action history"""
        if self._use_memory:
            actions = self._memory_actions
            if wallet:
                actions = [a for a in actions if a["wallet"] == wallet]
            return actions[-limit:]
        
        with self.cursor() as cur:
            if wallet:
                cur.execute("""
                    SELECT * FROM action_ledger 
                    WHERE wallet = %s 
                    ORDER BY created_at DESC LIMIT %s
                """, (wallet, limit))
            else:
                cur.execute("""
                    SELECT * FROM action_ledger 
                    ORDER BY created_at DESC LIMIT %s
                """, (limit,))
            return cur.fetchall()
    
    # Event operations
    def save_event(self, tick: int, event_type: str, event_data: dict, 
                   duration: int, started_at: int, expires_at: int):
        """Save a world event"""
        if self._use_memory:
            self._memory_events.append({
                "tick": tick,
                "event_type": event_type,
                "event_data": event_data,
                "duration": duration,
                "started_at": started_at,
                "expires_at": expires_at
            })
            return
        
        with self.cursor() as cur:
            cur.execute("""
                INSERT INTO events (tick, event_type, event_data, duration, started_at, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (tick, event_type, Json(event_data), duration, started_at, expires_at))
    
    def get_active_events(self, current_tick: int) -> List[dict]:
        """Get currently active events"""
        if self._use_memory:
            return [e for e in self._memory_events if e["expires_at"] > current_tick]
        
        with self.cursor() as cur:
            cur.execute("""
                SELECT * FROM events 
                WHERE expires_at > %s 
                ORDER BY started_at DESC
            """, (current_tick,))
            return cur.fetchall()
    
    def close(self):
        """Close database connection"""
        if self._conn:
            self._conn.close()
            self._conn = None

# Global database instance
_db: Optional[Database] = None

def get_database() -> Database:
    """Get database singleton"""
    global _db
    if _db is None:
        _db = Database()
        _db.connect()
        _db.init_schema()
    return _db

def reset_database():
    """Reset database (for testing)"""
    global _db
    if _db:
        _db.close()
    _db = None
