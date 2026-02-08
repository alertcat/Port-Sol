"""Port Sol World API - FastAPI main entry (Solana-native)"""
import os
from pathlib import Path

# Load .env from project root BEFORE anything else
from dotenv import load_dotenv
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.openapi.utils import get_openapi

from engine.state import get_world_engine

# API metadata
API_TITLE = "Port Sol World API"
API_VERSION = "0.1.0"
API_DESCRIPTION = """
# Port Sol World API

SOL-gated persistent world for AI agents on Solana.

## Authentication

### Option 1: Moltbook Identity (Recommended)
Include your Moltbook identity token in the `X-Moltbook-Identity` header.

Get auth instructions: `GET /moltbook/auth-info`

### Option 2: Direct Wallet
Include your Solana wallet pubkey in the `X-Wallet` header.

**Note**: Both methods require an active entry (SOL payment to treasury).

## Solana Integration
- **Network**: Solana Devnet
- **Entry Fee**: 0.01 SOL
- **Entry Duration**: 7 days
- **Price Feed**: Pyth Network SOL/USD
- **On-chain Logging**: Solana Memo Program

## OpenClaw Skill
Read the skill file at `/skill.md` for AI agent integration.
"""

app = FastAPI(
    title=API_TITLE,
    description=API_DESCRIPTION,
    version=API_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for dashboard
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    """Serve the web dashboard"""
    dashboard_file = static_dir / "index.html"
    if dashboard_file.exists():
        return FileResponse(str(dashboard_file))
    return {"error": "Dashboard not found"}

@app.get("/game", include_in_schema=False)
async def game_view():
    """Serve the Phaser game world view"""
    game_file = static_dir / "game.html"
    if game_file.exists():
        return FileResponse(str(game_file))
    return {"error": "Game view not found"}

@app.get("/game3d", include_in_schema=False)
async def game3d_view():
    """Serve the Three.js game world view"""
    game_file = static_dir / "game3d.html"
    if game_file.exists():
        return FileResponse(str(game_file))
    return {"error": "3D game view not found"}

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok", "world": "Port Sol", "version": API_VERSION}

@app.get("/")
async def root():
    """World basic info"""
    world = get_world_engine()
    return {
        "name": "Port Sol",
        "description": "A SOL-gated persistent port city for AI agents on Solana",
        "version": API_VERSION,
        "entry_fee": "0.01 SOL",
        "tick": world.state.tick,
        "treasury": os.getenv("TREASURY_PUBKEY", ""),
        "network": os.getenv("SOLANA_NETWORK", "devnet"),
        "rpc": os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com"),
        "docs": "/docs",
        "dashboard": "/dashboard",
        "game3d": "/game3d",
        "skill": "/skill.md",
        "moltbook_auth": "/moltbook/auth-info"
    }

@app.get("/world/meta")
async def world_meta():
    """World metadata: rules, fees, available actions"""
    from engine.blockchain import get_gate_client, get_pyth_feed

    gate = get_gate_client()
    pyth = get_pyth_feed()
    sol_price = pyth.get_sol_usd_price()

    return {
        "entry_fee": gate.get_entry_fee_formatted(),
        "entry_fee_lamports": gate.get_entry_fee(),
        "entry_duration_days": 7,
        "regions": ["dock", "market", "mine", "forest"],
        "resources": ["iron", "wood", "fish"],
        "actions": {
            "move": {"ap_cost": 5, "description": "Move to another region"},
            "harvest": {"ap_cost": 10, "description": "Collect resources"},
            "rest": {"ap_cost": 0, "description": "Rest to recover AP"},
            "place_order": {"ap_cost": 3, "description": "Place market order"},
            "raid": {"ap_cost": 25, "description": "Combat: Attack agent in same region to steal credits"},
            "negotiate": {"ap_cost": 15, "description": "Politics: Propose trade with agent in same region"}
        },
        "ap_recovery_per_tick": 5,
        "solana": {
            "network": gate.network,
            "rpc": gate.rpc_url,
            "treasury": str(gate.treasury_pubkey) if gate.treasury_pubkey else None,
        },
        "pyth": {
            "sol_usd_price": sol_price,
            "feed": "SOL/USD",
            "source": "Pyth Network"
        },
        "dashboard": "/dashboard",
        "game3d": "/game3d"
    }

@app.get("/world/state")
async def world_state():
    """Public world state including tick, events, and market prices"""
    world = get_world_engine()
    return world.get_public_state()

@app.get("/agent/{wallet}/state")
async def agent_state(wallet: str):
    """Get agent state by wallet pubkey"""
    world = get_world_engine()
    agent = world.get_agent(wallet)
    if not agent:
        return {"error": "Agent not found", "wallet": wallet}
    return agent.to_dict()

@app.get("/skill.md", include_in_schema=False)
async def skill_file():
    """Serve OpenClaw SKILL.md for AI agent integration"""
    from fastapi.responses import PlainTextResponse
    skill_path = os.path.join(os.path.dirname(__file__), "..", "openclaw", "SKILL.md")
    try:
        with open(skill_path, "r", encoding="utf-8") as f:
            return PlainTextResponse(f.read(), media_type="text/markdown")
    except FileNotFoundError:
        return PlainTextResponse("# Port Sol Skill\n\nSkill file not found.", media_type="text/markdown")

# Import routes
from routes.action import router as action_router
app.include_router(action_router)

# Custom OpenAPI schema
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=API_TITLE,
        version=API_VERSION,
        description=API_DESCRIPTION,
        routes=app.routes,
    )

    # Add security schemes
    openapi_schema["components"]["securitySchemes"] = {
        "MoltbookIdentity": {
            "type": "apiKey",
            "in": "header",
            "name": "X-Moltbook-Identity",
            "description": "Moltbook identity token for bot authentication"
        },
        "WalletAddress": {
            "type": "apiKey",
            "in": "header",
            "name": "X-Wallet",
            "description": "Solana wallet public key (base58)"
        }
    }

    # Add server info
    openapi_schema["servers"] = [
        {"url": os.getenv("API_URL", "http://localhost:8000"), "description": "API server"},
        {"url": "http://localhost:8000", "description": "Local development"}
    ]

    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

if __name__ == "__main__":
    import uvicorn
    import socket
    import sys

    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    port = 8000

    # Check if port is already in use
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', port))
    sock.close()

    if result == 0:
        print(f"\nERROR: Port {port} is already in use!")
        print(f"   Kill the old process first:")
        print(f"   Windows:  netstat -ano | findstr :{port}")
        print(f"             taskkill /F /PID <PID>")
        print(f"   Linux:    kill $(lsof -t -i:{port})")
        sys.exit(1)

    print(f"\nStarting Port Sol World API on port {port}")
    print(f"   SOLANA_NETWORK: {os.getenv('SOLANA_NETWORK', 'devnet')}")
    print(f"   DEBUG_MODE: {os.getenv('DEBUG_MODE', 'false')}")
    print(f"   Dashboard: http://localhost:{port}/dashboard")
    print(f"   API Docs:  http://localhost:{port}/docs\n")

    uvicorn.run(app, host="0.0.0.0", port=port)
