"""Blockchain integration - Solana-native (SOL gate + SPL token support)"""
import os
import json
import struct
import base64
from pathlib import Path
from typing import Optional, Tuple

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction
from solders.message import Message
from solders.commitment_config import CommitmentLevel
from solders.rpc.responses import GetBalanceResp
from solana.rpc.api import Client as SolanaClient
from solana.rpc.commitment import Confirmed, Finalized
from solana.rpc.types import TxOpts

# SOL decimals
SOL_DECIMALS = 9
LAMPORTS_PER_SOL = 1_000_000_000

# Default entry fee: 0.01 SOL (for devnet testing)
DEFAULT_ENTRY_FEE_LAMPORTS = 10_000_000  # 0.01 SOL

# Solana Memo Program ID (for on-chain action logging)
MEMO_PROGRAM_ID = Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr")


class PortSolGate:
    """
    Solana-native gate client for Port Sol.

    Architecture:
      - Entry: Agent sends SOL to the treasury wallet (simple transfer)
      - Gate check: Treasury tracks active entries in a local registry
        synced with on-chain transfer records
      - Exit/Cashout: Treasury sends SOL back to the agent
      - Action logging: Memo program for on-chain proof of actions

    Phase 2 upgrade path: Replace simple transfers with an Anchor program (PDA-based).
    """

    def __init__(self, rpc_url: str = None, treasury_pubkey: str = None):
        self.rpc_url = rpc_url or os.getenv(
            'SOLANA_RPC_URL', 'https://api.devnet.solana.com'
        )
        self.network = os.getenv('SOLANA_NETWORK', 'devnet')

        treasury_str = treasury_pubkey or os.getenv('TREASURY_PUBKEY')
        self.treasury_pubkey = Pubkey.from_string(treasury_str) if treasury_str else None

        self.entry_fee_lamports = int(
            os.getenv('ENTRY_FEE_LAMPORTS', str(DEFAULT_ENTRY_FEE_LAMPORTS))
        )

        self.client = SolanaClient(self.rpc_url)

        # In-memory registry of active entries (wallet_pubkey -> entry_info)
        # Persisted to DB via the world engine
        self._active_entries: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------
    def is_connected(self) -> bool:
        """Check if connected to Solana RPC."""
        try:
            resp = self.client.get_health()
            return resp.value == "ok" if hasattr(resp, 'value') else True
        except Exception:
            return False

    def get_balance(self, wallet_pubkey: str) -> int:
        """Get SOL balance in lamports."""
        try:
            pubkey = Pubkey.from_string(wallet_pubkey)
            resp = self.client.get_balance(pubkey, commitment=Confirmed)
            return resp.value
        except Exception as e:
            print(f"Error getting balance: {e}")
            return 0

    def get_balance_sol(self, wallet_pubkey: str) -> float:
        """Get SOL balance as human-readable float."""
        return self.get_balance(wallet_pubkey) / LAMPORTS_PER_SOL

    def get_entry_fee(self) -> int:
        """Get entry fee in lamports."""
        return self.entry_fee_lamports

    def get_entry_fee_formatted(self) -> str:
        """Get entry fee as human-readable string."""
        return f"{self.entry_fee_lamports / LAMPORTS_PER_SOL} SOL"

    # ------------------------------------------------------------------
    # Entry management
    # ------------------------------------------------------------------
    def is_active_entry(self, wallet_pubkey: str) -> bool:
        """Check if wallet has an active entry."""
        # In DEBUG_MODE, skip check
        if os.getenv("DEBUG_MODE", "").lower() in ("1", "true", "yes"):
            return True

        return wallet_pubkey in self._active_entries

    def register_entry(self, wallet_pubkey: str, tx_signature: str = None):
        """Register an active entry after verifying payment."""
        import time
        self._active_entries[wallet_pubkey] = {
            "entered_at": int(time.time()),
            "tx_signature": tx_signature,
            "fee_paid": self.entry_fee_lamports,
        }

    def remove_entry(self, wallet_pubkey: str):
        """Remove an active entry (on exit/cashout)."""
        self._active_entries.pop(wallet_pubkey, None)

    def get_active_entries(self) -> dict:
        """Get all active entries (for persistence)."""
        return dict(self._active_entries)

    def load_entries(self, entries: dict):
        """Load entries from persistence (DB)."""
        self._active_entries = dict(entries)

    # ------------------------------------------------------------------
    # Transaction helpers
    # ------------------------------------------------------------------
    def verify_transfer(self, tx_signature: str, from_pubkey: str,
                        min_amount: int = None) -> Tuple[bool, str]:
        """
        Verify that a SOL transfer transaction actually happened on-chain.
        Checks: sender, receiver (treasury), amount >= entry_fee.
        """
        if not self.treasury_pubkey:
            return False, "Treasury pubkey not configured"

        try:
            from solders.signature import Signature
            sig = Signature.from_string(tx_signature)
            resp = self.client.get_transaction(sig, commitment=Confirmed)

            if resp.value is None:
                return False, "Transaction not found"

            # Parse the transaction to verify transfer details
            tx_meta = resp.value.transaction.meta
            if tx_meta.err is not None:
                return False, f"Transaction failed: {tx_meta.err}"

            # Check pre/post balances to verify transfer amount
            expected_amount = min_amount or self.entry_fee_lamports
            pre_balances = tx_meta.pre_balances
            post_balances = tx_meta.post_balances

            # Get account keys from the transaction
            account_keys = resp.value.transaction.transaction.message.account_keys
            treasury_idx = None
            sender_idx = None

            for i, key in enumerate(account_keys):
                if str(key) == str(self.treasury_pubkey):
                    treasury_idx = i
                if str(key) == from_pubkey:
                    sender_idx = i

            if treasury_idx is None:
                return False, "Treasury not found in transaction accounts"
            if sender_idx is None:
                return False, "Sender not found in transaction accounts"

            received = post_balances[treasury_idx] - pre_balances[treasury_idx]
            if received < expected_amount:
                return False, (
                    f"Insufficient transfer: {received} lamports, "
                    f"need {expected_amount}"
                )

            return True, f"Verified: {received} lamports transferred"

        except Exception as e:
            return False, f"Verification error: {e}"

    def send_sol(self, from_keypair_bytes: bytes, to_pubkey: str,
                 amount_lamports: int, max_retries: int = 3) -> Tuple[bool, str]:
        """Send SOL from a keypair to a destination pubkey."""
        last_error = None
        for attempt in range(max_retries):
            try:
                sender = Keypair.from_bytes(from_keypair_bytes)
                receiver = Pubkey.from_string(to_pubkey)

                # Build transfer instruction
                ix = transfer(TransferParams(
                    from_pubkey=sender.pubkey(),
                    to_pubkey=receiver,
                    lamports=amount_lamports,
                ))

                # Get recent blockhash with Finalized commitment for reliability
                blockhash_resp = self.client.get_latest_blockhash(commitment=Finalized)
                recent_blockhash = blockhash_resp.value.blockhash

                # Build and sign transaction
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
                    wait = 2 ** attempt
                    print(f"send_sol attempt {attempt + 1} failed: {last_error}, retrying in {wait}s...")
                    time.sleep(wait)

        return False, last_error

    def send_memo(self, from_keypair_bytes: bytes,
                  memo_text: str, max_retries: int = 3) -> Tuple[bool, str]:
        """
        Write a memo on-chain (Solana Memo Program).
        Used for proof-of-action logging.
        """
        last_error = None
        for attempt in range(max_retries):
            try:
                from solders.instruction import Instruction, AccountMeta

                sender = Keypair.from_bytes(from_keypair_bytes)

                # Memo instruction: data = UTF-8 bytes, signer as account
                memo_ix = Instruction(
                    program_id=MEMO_PROGRAM_ID,
                    data=memo_text.encode('utf-8')[:256],  # Max 256 bytes
                    accounts=[
                        AccountMeta(sender.pubkey(), is_signer=True, is_writable=True)
                    ],
                )

                # Use Finalized commitment for reliable blockhash
                blockhash_resp = self.client.get_latest_blockhash(commitment=Finalized)
                recent_blockhash = blockhash_resp.value.blockhash

                msg = Message.new_with_blockhash(
                    [memo_ix], sender.pubkey(), recent_blockhash
                )
                tx = Transaction.new_unsigned(msg)
                tx.sign([sender], recent_blockhash)

                resp = self.client.send_transaction(
                    tx,
                    opts=TxOpts(
                        skip_preflight=False,
                        preflight_commitment=Finalized,
                    ),
                )
                return True, str(resp.value)

            except Exception as e:
                last_error = str(e)
                if attempt < max_retries - 1:
                    import time
                    wait = 2 ** attempt
                    print(f"send_memo attempt {attempt + 1} failed: {last_error}, retrying in {wait}s...")
                    time.sleep(wait)

        return False, last_error

    # ------------------------------------------------------------------
    # Cashout: send SOL back to an agent
    # ------------------------------------------------------------------
    def cashout(self, treasury_keypair_bytes: bytes, agent_pubkey: str,
                credit_amount: int) -> Tuple[bool, str]:
        """
        Cash out agent credits back to SOL.
        Rate: 1000 credits = 0.000001 SOL (1000 lamports).
        """
        lamports = credit_amount  # 1 credit = 1 lamport for simplicity
        if lamports <= 0:
            return False, "Nothing to cash out"

        return self.send_sol(treasury_keypair_bytes, agent_pubkey, lamports)

    # ------------------------------------------------------------------
    # Reward pool tracking (off-chain, synced with treasury balance)
    # ------------------------------------------------------------------
    def get_reward_pool(self) -> int:
        """Get reward pool balance (treasury SOL balance in lamports)."""
        if not self.treasury_pubkey:
            return 0
        return self.get_balance(str(self.treasury_pubkey))

    def get_reward_pool_formatted(self) -> str:
        """Get reward pool as human-readable SOL."""
        pool = self.get_reward_pool()
        return f"{pool / LAMPORTS_PER_SOL:.6f} SOL"


# ---------------------------------------------------------------------------
# Pyth Price Feed integration
# ---------------------------------------------------------------------------
class PythPriceFeed:
    """
    Fetch real-time SOL/USD price from Pyth Network.
    Used to make in-game market prices react to real-world SOL price movements.
    """

    # Pyth SOL/USD price feed ID (mainnet & devnet)
    SOL_USD_FEED_ID = "ef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d"
    PYTH_HERMES_URL = "https://hermes.pyth.network"

    def __init__(self):
        self._cached_price: Optional[float] = None
        self._cache_timestamp: float = 0
        self._cache_ttl: float = 30.0  # Cache for 30 seconds

    def get_sol_usd_price(self) -> Optional[float]:
        """Fetch current SOL/USD price from Pyth Hermes API."""
        import time
        import requests

        # Return cached if fresh
        now = time.time()
        if self._cached_price and (now - self._cache_timestamp) < self._cache_ttl:
            return self._cached_price

        try:
            url = (
                f"{self.PYTH_HERMES_URL}/v2/updates/price/latest"
                f"?ids[]={self.SOL_USD_FEED_ID}"
            )
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if data.get("parsed") and len(data["parsed"]) > 0:
                price_data = data["parsed"][0]["price"]
                price = int(price_data["price"]) * (10 ** int(price_data["expo"]))
                self._cached_price = price
                self._cache_timestamp = now
                return price

        except Exception as e:
            print(f"Pyth price fetch error: {e}")

        return self._cached_price  # Return stale cache on error


# ---------------------------------------------------------------------------
# Global singletons
# ---------------------------------------------------------------------------
_gate_client: Optional[PortSolGate] = None
_pyth_feed: Optional[PythPriceFeed] = None


def get_gate_client() -> PortSolGate:
    """Get PortSolGate singleton."""
    global _gate_client
    if _gate_client is None:
        _gate_client = PortSolGate()
    return _gate_client


def get_pyth_feed() -> PythPriceFeed:
    """Get PythPriceFeed singleton."""
    global _pyth_feed
    if _pyth_feed is None:
        _pyth_feed = PythPriceFeed()
    return _pyth_feed
