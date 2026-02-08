"""Port Sol SDK - Agent client with Solana on-chain support (Devnet)"""
import os
import json
import aiohttp
from pathlib import Path
from typing import Dict, Any, Optional

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction
from solders.message import Message
from solana.rpc.api import Client as SolanaClient
from solana.rpc.commitment import Confirmed, Finalized
from solana.rpc.types import TxOpts

LAMPORTS_PER_SOL = 1_000_000_000


class PortSolClient:
    """Port Sol API client with Solana on-chain integration"""

    def __init__(self, api_url: str, wallet_pubkey: str, keypair_json: str = None):
        self.api_url = api_url.rstrip("/")
        self.wallet = wallet_pubkey
        self._session: Optional[aiohttp.ClientSession] = None

        # Solana setup
        self.rpc_url = os.getenv('SOLANA_RPC_URL', 'https://api.devnet.solana.com')
        self.treasury_pubkey = os.getenv('TREASURY_PUBKEY')
        self.entry_fee_lamports = int(os.getenv('ENTRY_FEE_LAMPORTS', '10000000'))
        self.client = SolanaClient(self.rpc_url)

        # Load keypair if provided
        self._keypair: Optional[Keypair] = None
        if keypair_json:
            try:
                key_bytes = json.loads(keypair_json) if isinstance(keypair_json, str) else keypair_json
                self._keypair = Keypair.from_bytes(bytes(key_bytes))
            except Exception as e:
                print(f"Warning: Failed to load keypair: {e}")

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"X-Wallet": self.wallet}
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------
    # On-chain: balance and entry
    # ------------------------------------------------------------------
    def get_balance(self) -> float:
        """Get wallet SOL balance"""
        try:
            pubkey = Pubkey.from_string(self.wallet)
            resp = self.client.get_balance(pubkey, commitment=Confirmed)
            return resp.value / LAMPORTS_PER_SOL
        except Exception:
            return 0

    def get_balance_lamports(self) -> int:
        """Get wallet SOL balance in lamports"""
        try:
            pubkey = Pubkey.from_string(self.wallet)
            resp = self.client.get_balance(pubkey, commitment=Confirmed)
            return resp.value
        except Exception:
            return 0

    def enter_world(self, max_retries: int = 3) -> tuple:
        """
        Send SOL entry fee to treasury wallet.
        Returns: (success, tx_signature_or_error)

        Retries on transient errors (e.g. Blockhash not found on devnet).
        """
        if not self._keypair:
            return False, "Keypair not set"

        if not self.treasury_pubkey:
            return False, "TREASURY_PUBKEY not configured"

        sender = self._keypair
        receiver = Pubkey.from_string(self.treasury_pubkey)

        # Check balance
        balance = self.get_balance_lamports()
        if balance < self.entry_fee_lamports + 10000:  # +10000 for tx fee
            return False, (
                f"Insufficient SOL: {balance / LAMPORTS_PER_SOL:.6f} SOL, "
                f"need {self.entry_fee_lamports / LAMPORTS_PER_SOL} SOL + gas"
            )

        last_error = None
        for attempt in range(max_retries):
            try:
                # Build transfer instruction
                ix = transfer(TransferParams(
                    from_pubkey=sender.pubkey(),
                    to_pubkey=receiver,
                    lamports=self.entry_fee_lamports,
                ))

                # Get recent blockhash with Finalized commitment for reliability
                blockhash_resp = self.client.get_latest_blockhash(commitment=Finalized)
                recent_blockhash = blockhash_resp.value.blockhash

                # Build, sign, send
                msg = Message.new_with_blockhash(
                    [ix], sender.pubkey(), recent_blockhash
                )
                tx = Transaction.new_unsigned(msg)
                tx.sign([sender], recent_blockhash)

                # Send with matching preflight commitment
                resp = self.client.send_transaction(
                    tx,
                    opts=TxOpts(
                        skip_preflight=False,
                        preflight_commitment=Finalized,
                    ),
                )
                sig = str(resp.value)

                # Confirm
                self.client.confirm_transaction(resp.value, commitment=Confirmed)
                return True, sig

            except Exception as e:
                last_error = str(e)
                if attempt < max_retries - 1:
                    import time
                    wait = 2 ** attempt  # exponential backoff: 1s, 2s
                    print(f"  Attempt {attempt + 1} failed: {last_error}, retrying in {wait}s...")
                    time.sleep(wait)

        return False, last_error

    async def ensure_entered(self) -> bool:
        """Ensure agent has entered the world (send SOL if needed)"""
        # Check via API if already registered
        try:
            session = await self._get_session()
            async with session.get(f"{self.api_url}/gate/status/{self.wallet}") as resp:
                data = await resp.json()
                if data.get("is_active_entry"):
                    return True
        except Exception:
            pass

        print(f"  Not entered, sending {self.entry_fee_lamports / LAMPORTS_PER_SOL} SOL to treasury...")
        success, result = self.enter_world()
        if success:
            print(f"  Entry TX: {result}")
            return True
        else:
            print(f"  Failed to enter: {result}")
            return False

    # ------------------------------------------------------------------
    # API calls
    # ------------------------------------------------------------------
    async def register(self, name: str, tx_hash: str = None) -> dict:
        """Register agent with the world API"""
        session = await self._get_session()
        async with session.post(
            f"{self.api_url}/register",
            json={"wallet": self.wallet, "name": name, "tx_hash": tx_hash}
        ) as resp:
            return await resp.json()

    async def get_world_state(self) -> dict:
        """Get public world state"""
        session = await self._get_session()
        async with session.get(f"{self.api_url}/world/state") as resp:
            return await resp.json()

    async def get_my_state(self) -> dict:
        """Get own agent state"""
        session = await self._get_session()
        async with session.get(f"{self.api_url}/agent/{self.wallet}/state") as resp:
            return await resp.json()

    async def submit_action(self, action: str, params: Dict[str, Any] = None) -> dict:
        """Submit an action to the world"""
        session = await self._get_session()
        async with session.post(
            f"{self.api_url}/action",
            json={
                "actor": self.wallet,
                "action": action,
                "params": params or {}
            }
        ) as resp:
            return await resp.json()

    async def move(self, target: str) -> dict:
        """Move to target region"""
        return await self.submit_action("move", {"target": target})

    async def harvest(self) -> dict:
        """Harvest resources in current region"""
        return await self.submit_action("harvest")

    async def rest(self) -> dict:
        """Rest to recover AP"""
        return await self.submit_action("rest")

    async def place_order(self, resource: str, side: str, quantity: int, price: int = None) -> dict:
        """Place a market order (buy/sell)"""
        params = {"resource": resource, "side": side, "quantity": quantity}
        if price:
            params["price"] = price
        return await self.submit_action("place_order", params)

    # ------------------------------------------------------------------
    # Cashout (treasury sends SOL back to agent)
    # ------------------------------------------------------------------
    def cashout(self, credit_amount: int) -> tuple:
        """
        Request cashout: treasury sends SOL proportional to credits.
        This is called server-side via settle_and_exit.py.
        Returns: (success, message)
        """
        # Cashout is handled server-side by the treasury keypair
        # Agent simply reports credits for settlement
        return True, f"Cashout request: {credit_amount} credits"
