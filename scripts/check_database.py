#!/usr/bin/env python3
"""Check database contents"""
import psycopg2
from psycopg2.extras import RealDictCursor

def main():
    conn = psycopg2.connect('postgresql://postgres:postgres@localhost:5432/portsol')
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    print("=" * 60)
    print("PORT SOL DATABASE STATUS")
    print("=" * 60)
    
    print("\n=== AGENTS ===")
    cur.execute('SELECT wallet, name, region, energy, credits FROM agents')
    agents = cur.fetchall()
    if agents:
        for row in agents:
            print(f"  {row['name']:15} | Region: {row['region']:8} | AP: {row['energy']:3} | Credits: {row['credits']}")
    else:
        print("  (no agents)")
    
    print(f"\n  Total: {len(agents)} agents")
    
    print("\n=== ACTION LEDGER (Last 10) ===")
    cur.execute('SELECT wallet, action, message, created_at FROM action_ledger ORDER BY id DESC LIMIT 10')
    actions = cur.fetchall()
    if actions:
        for row in actions:
            wallet_short = row['wallet'][:10] + '...'
            print(f"  {wallet_short} | {row['action']:10} | {row['message']}")
    else:
        print("  (no actions)")
    
    cur.execute('SELECT COUNT(*) as count FROM action_ledger')
    count = cur.fetchone()
    print(f"\n  Total: {count['count']} actions logged")
    
    print("\n=== WORLD STATE (Latest) ===")
    cur.execute('SELECT tick, state_hash, market_prices FROM world_state ORDER BY id DESC LIMIT 1')
    row = cur.fetchone()
    if row:
        print(f"  Tick: {row['tick']}")
        print(f"  Hash: {row['state_hash']}")
        print(f"  Prices: {row['market_prices']}")
    else:
        print("  (no world state saved yet)")
    
    print("\n=== EVENTS ===")
    cur.execute('SELECT event_type, started_at, expires_at FROM events ORDER BY id DESC LIMIT 5')
    events = cur.fetchall()
    if events:
        for row in events:
            print(f"  {row['event_type']:20} | Tick {row['started_at']}-{row['expires_at']}")
    else:
        print("  (no events)")
    
    print("\n" + "=" * 60)
    print("PostgreSQL persistence is working!")
    print("=" * 60)
    
    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
