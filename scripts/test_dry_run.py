#!/usr/bin/env python3
"""
Test script with Moltbook DRY RUN mode enabled.

This script tests the world simulation WITHOUT actually posting to Moltbook.
All Moltbook posts and comments will be printed to console instead.

Usage:
    python test_dry_run.py
    
    # Or with env var:
    MOLTBOOK_DRY_RUN=true python run_demo.py
"""
import sys
import os

# Add parent dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'world-api'))

# Enable DRY RUN mode BEFORE importing other modules
os.environ["MOLTBOOK_DRY_RUN"] = "true"
# Skip PostgreSQL for dry-run testing (use in-memory storage)
os.environ["DISABLE_POSTGRES"] = "true"

from engine.moltbook import (
    MoltbookClient, 
    MoltbookBotClient, 
    set_dry_run_mode, 
    is_dry_run_mode,
    get_host_client,
    get_bot_client
)
from engine.state import get_world_engine

def test_dry_run():
    """Test the dry run mode"""
    print("\n" + "="*70)
    print("🧪 MOLTBOOK DRY RUN TEST")
    print("="*70)
    
    # Verify dry run is enabled
    print(f"\n✅ DRY_RUN mode is: {'ENABLED' if is_dry_run_mode() else 'DISABLED'}")
    
    # Test 1: Create a client with explicit dry_run
    print("\n--- Test 1: Explicit dry_run=True client ---")
    client = MoltbookClient(api_key="fake_key", agent_name="TestAgent", dry_run=True)
    
    # Test posting
    post_id = client.post(
        title="Test Post from Port Sol",
        content="This is a test post. If you see this on Moltbook, something is wrong!"
    )
    print(f"Returned post_id: {post_id}")
    
    # Test commenting
    client.comment(post_id, "This is a test comment!")
    
    # Test 2: Use the global setting
    print("\n--- Test 2: Global DRY_RUN setting ---")
    set_dry_run_mode(True)
    
    host_client = get_host_client()
    print(f"Host client dry_run: {host_client.dry_run}")
    
    # Test tick digest
    world = get_world_engine()
    world_state = world.get_public_state()
    
    host_client.post_tick_digest(tick=world_state.get("tick", 0), world_state=world_state)
    
    # Test 3: Bot client
    print("\n--- Test 3: Bot client ---")
    bot = MoltbookBotClient(api_key="fake_key", bot_name="MinerBot", dry_run=True)
    
    fake_agent_state = {
        "region": "mine",
        "energy": 85,
        "credits": 150,
        "inventory": {"iron": 5, "wood": 2}
    }
    
    bot.post_status_comment("dry_run_post_123", fake_agent_state)
    
    print("\n" + "="*70)
    print("✅ DRY RUN TEST COMPLETE - No actual posts were made!")
    print("="*70 + "\n")

if __name__ == "__main__":
    test_dry_run()
