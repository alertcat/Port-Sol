#!/bin/bash
# Deploy Port Sol to server 43.156.62.248
# Run this script on the server

set -e

echo "==================================="
echo "Port Sol Server Deployment"
echo "==================================="

# 1. Install dependencies
echo "Installing Python dependencies..."
cd /root/port-sol/world-api
pip install -r requirements.txt

# 2. Set environment variables
echo "Setting up environment..."
export SOLANA_RPC_URL=https://api.devnet.solana.com
export SOLANA_NETWORK=devnet
export API_URL=http://43.156.62.248:8000
# Set your Moltbook app key (get from https://moltbook.com/developers/dashboard)
# export MOLTBOOK_APP_KEY=moltdev_xxx
# export MOLTBOOK_AUDIENCE=portsol.world

# 3. Start API server
echo "Starting API server..."
cd /root/port-sol/world-api
uvicorn app:app --host 0.0.0.0 --port 8000 &

# 4. Install OpenClaw (if not installed)
if ! command -v openclaw &> /dev/null; then
    echo "Installing OpenClaw..."
    curl -fsSL https://openclaw.ai/install.sh | bash
fi

# 5. Copy OpenClaw config
echo "Setting up OpenClaw..."
mkdir -p ~/.openclaw
cp /root/port-sol/openclaw/openclaw.json ~/.openclaw/

# 6. Copy skills
mkdir -p ~/.openclaw/skills
cp -r /root/port-sol/openclaw/skills/* ~/.openclaw/skills/

# 7. Start OpenClaw gateway
echo "Starting OpenClaw gateway..."
openclaw gateway --port 18789 &

echo "==================================="
echo "Deployment complete!"
echo "API: http://43.156.62.248:8000"
echo "OpenClaw: ws://43.156.62.248:18789"
echo "==================================="
