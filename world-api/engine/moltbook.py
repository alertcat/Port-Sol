"""
Moltbook Integration - Post world updates and agent comments

Usage:
    from engine.moltbook import MoltbookClient
    
    # Production mode (actually posts)
    client = MoltbookClient(api_key="your_api_key")
    
    # Test mode (only prints, no actual posting)
    client = MoltbookClient(api_key="your_api_key", dry_run=True)
    
    post_id = client.post_tick_digest(tick=10, state=world_state)
    client.post_comment(post_id, "MinerBot checking in!")

Environment variables:
    MOLTBOOK_DRY_RUN=true   # Enable dry run mode globally
"""
import os
import httpx
from typing import Optional, Dict, Any
from datetime import datetime

# IMPORTANT: Always use www.moltbook.com to avoid 307 redirect issues
MOLTBOOK_API = "https://www.moltbook.com/api/v1"

# Global dry run mode - set via env var or code
DRY_RUN_MODE = os.getenv("MOLTBOOK_DRY_RUN", "false").lower() in ("true", "1", "yes")

class MoltbookClient:
    """Client for posting to Moltbook"""
    
    def __init__(self, api_key: str = None, agent_name: str = "PortSol", dry_run: bool = None):
        self.api_key = api_key or os.getenv("MOLTBOOK_API_KEY", "")
        self.agent_name = agent_name
        self._client = None
        # dry_run can be set per-instance or globally via env var
        self.dry_run = dry_run if dry_run is not None else DRY_RUN_MODE
    
    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=MOLTBOOK_API,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                timeout=30.0
            )
        return self._client
    
    def is_configured(self) -> bool:
        """Check if API key is configured"""
        return bool(self.api_key)
    
    def post(self, title: str, content: str, submolt: str = "general") -> Optional[str]:
        """
        Create a post on Moltbook
        Returns: post_id or None (or fake_post_id in dry_run mode)
        """
        # DRY RUN MODE - just print, don't actually post
        if self.dry_run:
            fake_id = f"dry_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            print("\n" + "="*60)
            print(f"🧪 [DRY RUN] Moltbook POST (not actually sent)")
            print("="*60)
            print(f"📝 Title: {title}")
            print(f"📂 Submolt: {submolt}")
            print(f"📄 Content:\n{content}")
            print("="*60 + "\n")
            return fake_id
        
        if not self.is_configured():
            print("Warning: Moltbook API key not configured")
            return None
        
        try:
            response = self.client.post(
                "/posts",
                json={
                    "submolt": submolt,
                    "title": title,
                    "content": content
                }
            )
            
            if response.status_code in [200, 201]:
                data = response.json()
                post_id = data.get("id")
                print(f"Moltbook: Posted '{title}' (id: {post_id})")
                return post_id
            else:
                print(f"Moltbook post failed: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            print(f"Moltbook post error: {e}")
            return None
    
    def comment(self, post_id: str, content: str) -> bool:
        """
        Add a comment to a post
        Returns: True if successful
        """
        # DRY RUN MODE - just print, don't actually comment
        if self.dry_run:
            print("\n" + "-"*50)
            print(f"🧪 [DRY RUN] Moltbook COMMENT (not actually sent)")
            print("-"*50)
            print(f"📌 Post ID: {post_id}")
            print(f"💬 Comment: {content}")
            print("-"*50 + "\n")
            return True
        
        if not self.is_configured():
            return False
        
        try:
            response = self.client.post(
                f"/posts/{post_id}/comments",
                json={"content": content}
            )
            
            if response.status_code in [200, 201]:
                print(f"Moltbook: Commented on post {post_id}")
                return True
            else:
                print(f"Moltbook comment failed: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"Moltbook comment error: {e}")
            return False
    
    def post_tick_digest(self, tick: int, world_state: dict) -> Optional[str]:
        """
        Post a tick digest to Moltbook
        
        Args:
            tick: Current tick number
            world_state: World state from get_public_state()
        
        Returns: post_id or None
        """
        # Format title
        title = f"Port Sol Tick #{tick} — World Update"
        
        # Format content
        prices = world_state.get("market_prices", {})
        events = world_state.get("active_events", [])
        agent_count = world_state.get("agent_count", 0)
        state_hash = world_state.get("state_hash", "unknown")
        
        # Build content
        lines = [
            f"📰 **Port Sol Daily Digest**",
            f"",
            f"🕐 Tick: {tick}",
            f"👥 Active Agents: {agent_count}",
            f"",
            f"📊 **Market Prices:**",
        ]
        
        for resource, price in prices.items():
            lines.append(f"  • {resource.capitalize()}: {price} credits")
        
        if events:
            lines.append("")
            lines.append("🌍 **Active Events:**")
            for event in events:
                event_type = event.get("type", "Unknown")
                remaining = event.get("remaining", 0)
                lines.append(f"  • {event_type} ({remaining} ticks remaining)")
        else:
            lines.append("")
            lines.append("🌤️ No active events")
        
        lines.append("")
        lines.append(f"🔗 State Hash: `{state_hash}`")
        lines.append("")
        lines.append("---")
        lines.append("*Port Sol: A persistent world for AI agents on Solana Devnet*")
        
        content = "\n".join(lines)
        
        return self.post(title, content)
    
    def close(self):
        """Close the HTTP client"""
        if self._client:
            self._client.close()
            self._client = None


class MoltbookBotClient(MoltbookClient):
    """Client for bot-specific Moltbook interactions"""
    
    def __init__(self, api_key: str = None, bot_name: str = "Bot", dry_run: bool = None):
        super().__init__(api_key, bot_name, dry_run)
        self.bot_name = bot_name
    
    def post_status_comment(self, post_id: str, agent_state: dict) -> bool:
        """
        Post a status comment from this bot
        
        Args:
            post_id: The tick digest post to comment on
            agent_state: The bot's current state
        """
        region = agent_state.get("region", "unknown")
        energy = agent_state.get("energy", 0)
        credits = agent_state.get("credits", 0)
        inventory = agent_state.get("inventory", {})
        
        # Format inventory
        inv_str = ", ".join([f"{v} {k}" for k, v in inventory.items()]) if inventory else "empty"
        
        content = f"**{self.bot_name}** checking in from {region}! AP: {energy}, Credits: {credits}, Inventory: [{inv_str}]"
        
        return self.comment(post_id, content)


# Singleton instances for different agents
_host_client: Optional[MoltbookClient] = None
_bot_clients: Dict[str, MoltbookBotClient] = {}

def set_dry_run_mode(enabled: bool = True):
    """
    Enable or disable dry run mode globally.
    
    Usage:
        from engine.moltbook import set_dry_run_mode
        set_dry_run_mode(True)  # Enable test mode - prints instead of posting
        set_dry_run_mode(False) # Disable test mode - actually posts
    """
    global DRY_RUN_MODE, _host_client, _bot_clients
    DRY_RUN_MODE = enabled
    # Reset clients so they pick up new setting
    _host_client = None
    _bot_clients = {}
    print(f"🧪 Moltbook DRY_RUN mode: {'ENABLED (will print only)' if enabled else 'DISABLED (will post)'}")

def is_dry_run_mode() -> bool:
    """Check if dry run mode is enabled"""
    return DRY_RUN_MODE

def get_host_client() -> MoltbookClient:
    """Get the world host Moltbook client"""
    global _host_client
    if _host_client is None:
        api_key = os.getenv("MOLTBOOK_HOST_KEY") or os.getenv("MOLTBOOK_API_KEY")
        _host_client = MoltbookClient(api_key, "PortSolWorldHost", dry_run=DRY_RUN_MODE)
    return _host_client

def get_bot_client(bot_name: str, api_key_env: str) -> MoltbookBotClient:
    """Get a bot's Moltbook client"""
    global _bot_clients
    if bot_name not in _bot_clients:
        api_key = os.getenv(api_key_env)
        _bot_clients[bot_name] = MoltbookBotClient(api_key, bot_name, dry_run=DRY_RUN_MODE)
    return _bot_clients[bot_name]
