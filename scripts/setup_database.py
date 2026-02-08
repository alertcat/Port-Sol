#!/usr/bin/env python3
"""Setup PostgreSQL database for Port Sol"""
import os
import sys
from pathlib import Path

def check_psycopg2():
    """Check if psycopg2 is installed"""
    try:
        import psycopg2
        print("✓ psycopg2 is installed")
        return True
    except ImportError:
        print("✗ psycopg2 is not installed")
        print("  Install with: pip install psycopg2-binary")
        return False

def create_database(host="localhost", port=5432, user="postgres", password="postgres"):
    """Create the portsol database if it doesn't exist"""
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    print(f"\nConnecting to PostgreSQL at {host}:{port} as {user}...")

    try:
        # Connect to default postgres database
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database="postgres"
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()

        # Check if database exists
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = 'portsol'")
        exists = cursor.fetchone()

        if exists:
            print("✓ Database 'portsol' already exists")
        else:
            print("Creating database 'portsol'...")
            cursor.execute("CREATE DATABASE portsol")
            print("✓ Database 'portsol' created")

        cursor.close()
        conn.close()
        return True

    except psycopg2.OperationalError as e:
        print(f"✗ Connection failed: {e}")
        print("\nPossible causes:")
        print("  1. PostgreSQL is not running")
        print("  2. Wrong username/password")
        print("  3. Wrong host/port")
        print("\nTo start PostgreSQL on Windows:")
        print("  - Open Services (services.msc)")
        print("  - Find 'postgresql-x64-XX' and start it")
        print("  Or run: net start postgresql-x64-16")
        return False

def init_schema():
    """Initialize database schema"""
    import psycopg2

    print("\nInitializing database schema...")

    try:
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            user="postgres",
            password="postgres",
            database="portsol"
        )
        conn.autocommit = True
        cursor = conn.cursor()

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
            wallet VARCHAR(44) PRIMARY KEY,
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
            wallet VARCHAR(44) NOT NULL,
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

        cursor.execute(schema)
        print("✓ Schema initialized")

        # Show table info
        cursor.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
        """)
        tables = cursor.fetchall()
        print(f"\nTables created: {[t[0] for t in tables]}")

        cursor.close()
        conn.close()
        return True

    except Exception as e:
        print(f"✗ Schema initialization failed: {e}")
        return False

def test_connection():
    """Test database connection from the app"""
    print("\nTesting connection from app...")

    # Add parent to path
    sys.path.insert(0, str(Path(__file__).parent.parent / 'world-api'))

    try:
        from engine.database import get_database, reset_database
        reset_database()  # Reset singleton

        db = get_database()

        if db._use_memory:
            print("⚠ Using in-memory storage (PostgreSQL not available)")
            return False
        else:
            print("✓ Connected to PostgreSQL successfully")

            # Try a simple query
            with db.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM agents")
                count = cur.fetchone()
                print(f"  Agents in database: {count['count'] if count else 0}")

            return True

    except Exception as e:
        print(f"✗ Connection test failed: {e}")
        return False

def main():
    print("=" * 50)
    print("PostgreSQL Setup for Port Sol")
    print("=" * 50)

    # Check psycopg2
    if not check_psycopg2():
        print("\nInstall psycopg2 first:")
        print("  pip install psycopg2-binary")
        return

    # Get password from user or use default
    password = os.getenv("PGPASSWORD", "postgres")
    print(f"\nUsing password: {'*' * len(password)}")
    print("(Set PGPASSWORD environment variable to change)")

    # Create database
    if not create_database(password=password):
        return

    # Initialize schema
    if not init_schema():
        return

    # Test connection
    test_connection()

    print("\n" + "=" * 50)
    print("Setup complete!")
    print("=" * 50)
    print("\nNext steps:")
    print("  1. Restart the API server: python world-api/app.py")
    print("  2. Data will now persist to PostgreSQL")

if __name__ == "__main__":
    main()
