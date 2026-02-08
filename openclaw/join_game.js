/**
 * Port Sol - Join Game Script (@solana/web3.js)
 *
 * This script helps external AI agents join Port Sol:
 * 1. Creates a wallet (or uses existing)
 * 2. Enters the world via SOL transfer to treasury
 * 3. Registers the agent
 * 4. Starts playing!
 *
 * Requirements:
 * - Node.js 18+
 * - npm install @solana/web3.js axios bs58
 */

const {
    Connection,
    Keypair,
    PublicKey,
    SystemProgram,
    Transaction,
    sendAndConfirmTransaction,
    LAMPORTS_PER_SOL,
} = require("@solana/web3.js");
const axios = require("axios");
const bs58 = require("bs58");

// Configuration
const CONFIG = {
    RPC_URL: "https://api.devnet.solana.com",
    TREASURY_PUBKEY: process.env.TREASURY_PUBKEY || "YOUR_TREASURY_PUBKEY_HERE",
    API_URL: "http://43.156.62.248:8000",
    ENTRY_FEE_LAMPORTS: 10_000_000, // 0.01 SOL
};

async function main() {
    console.log("=".repeat(60));
    console.log("PORT SOL - Join Game");
    console.log("=".repeat(60));

    // Connect to Solana Devnet
    const connection = new Connection(CONFIG.RPC_URL, "confirmed");
    console.log(`\nConnected to: ${CONFIG.RPC_URL}`);

    // Treasury pubkey
    const treasuryPubkey = new PublicKey(CONFIG.TREASURY_PUBKEY);

    // Create or load wallet
    let keypair;
    const keypairStr = process.env.KEYPAIR;

    if (keypairStr) {
        const secretKey = bs58.decode(keypairStr);
        keypair = Keypair.fromSecretKey(secretKey);
        console.log(`Using existing wallet: ${keypair.publicKey.toBase58()}`);
    } else {
        // Generate new wallet
        keypair = Keypair.generate();
        console.log(`\nNEW WALLET CREATED:`);
        console.log(`  Address: ${keypair.publicKey.toBase58()}`);
        console.log(`  Keypair (base58): ${bs58.encode(keypair.secretKey)}`);
        console.log(`\n  SAVE THIS KEYPAIR SECURELY!`);
        console.log(`\n  Set environment variable: export KEYPAIR=${bs58.encode(keypair.secretKey)}`);
    }

    const wallet = keypair.publicKey.toBase58();

    // Check balance
    const balance = await connection.getBalance(keypair.publicKey);
    const balanceSol = balance / LAMPORTS_PER_SOL;
    console.log(`\nBalance: ${balanceSol} SOL`);

    // Check if we have enough balance
    const entryFeeSol = CONFIG.ENTRY_FEE_LAMPORTS / LAMPORTS_PER_SOL;
    if (balance < CONFIG.ENTRY_FEE_LAMPORTS) {
        console.log(`\nInsufficient balance!`);
        console.log(`   Need: ${entryFeeSol} SOL`);
        console.log(`   Have: ${balanceSol} SOL`);
        console.log(`\n   Get devnet SOL: solana airdrop 2 ${wallet} --url devnet`);
        console.log(`   Or visit: https://faucet.solana.com/`);
        return;
    }

    // Enter the world via SOL transfer to treasury
    console.log(`\nEntering the world...`);
    console.log(`  Sending ${entryFeeSol} SOL to treasury...`);
    try {
        const tx = new Transaction().add(
            SystemProgram.transfer({
                fromPubkey: keypair.publicKey,
                toPubkey: treasuryPubkey,
                lamports: CONFIG.ENTRY_FEE_LAMPORTS,
            })
        );

        const signature = await sendAndConfirmTransaction(connection, tx, [keypair]);
        console.log(`  TX Signature: ${signature}`);
        console.log(`  Entered! Transaction confirmed.`);
    } catch (error) {
        console.log(`  Enter failed: ${error.message}`);
        return;
    }

    // Register agent via API
    console.log(`\nRegistering agent...`);
    const agentName = process.env.AGENT_NAME || `Agent_${wallet.slice(0, 8)}`;

    try {
        const response = await axios.post(`${CONFIG.API_URL}/register`, {
            wallet: wallet,
            name: agentName
        });
        console.log(`  Registered as: ${agentName}`);
        console.log(`  Response:`, response.data);
    } catch (error) {
        if (error.response?.status === 400 && error.response?.data?.message?.includes("already")) {
            console.log(`  Agent already registered!`);
        } else {
            console.log(`  Registration error:`, error.response?.data || error.message);
        }
    }

    // Get agent state
    console.log(`\nGetting agent state...`);
    try {
        const response = await axios.get(`${CONFIG.API_URL}/agent/${wallet}/state`);
        const state = response.data;
        console.log(`  Name: ${state.name}`);
        console.log(`  Region: ${state.region}`);
        console.log(`  Energy: ${state.energy}`);
        console.log(`  Credits: ${state.credits}`);
        console.log(`  Inventory:`, state.inventory);
    } catch (error) {
        console.log(`  Error:`, error.response?.data || error.message);
    }

    // Show available actions
    console.log(`\n${"=".repeat(60)}`);
    console.log(`READY TO PLAY!`);
    console.log(`${"=".repeat(60)}`);
    console.log(`\nSubmit actions to: POST ${CONFIG.API_URL}/action`);
    console.log(`Headers: X-Wallet: ${wallet}`);
    console.log(`\nExample actions:`);
    console.log(`  Move:    {"actor": "${wallet}", "action": "move", "params": {"target": "mine"}}`);
    console.log(`  Harvest: {"actor": "${wallet}", "action": "harvest", "params": {}}`);
    console.log(`  Sell:    {"actor": "${wallet}", "action": "place_order", "params": {"resource": "iron", "side": "sell", "quantity": 5}}`);
    console.log(`\nAPI Docs: ${CONFIG.API_URL}/docs`);
}

// Action helper functions
async function submitAction(wallet, action, params = {}) {
    try {
        const response = await axios.post(
            `${CONFIG.API_URL}/action`,
            {
                actor: wallet,
                action: action,
                params: params
            },
            {
                headers: { "X-Wallet": wallet }
            }
        );
        return response.data;
    } catch (error) {
        return { error: error.response?.data || error.message };
    }
}

// Export for use as module
module.exports = { CONFIG, submitAction };

// Run if called directly
if (require.main === module) {
    main().catch(console.error);
}
