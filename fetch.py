"""Stage 1: pull the onchain evidence for one transaction from Etherscan.

Usage: python fetch.py <tx_hash> [chain_id]     (chain_id 1 = Ethereum mainnet)
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
API = "https://api.etherscan.io/v2/api"
# keccak256("Transfer(address,address,uint256)"), the standard ERC20 transfer event
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def call(chain, **params):
    params.update({"chainid": chain, "apikey": os.environ["ETHERSCAN_API_KEY"]})
    url = API + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as response:
        data = json.load(response)
    time.sleep(0.3)  # stay under the free tier rate limit
    return data.get("result")


def contract_name(chain, address, cache):
    """Look up the verified contract name, if any."""
    if address not in cache:
        result = call(chain, module="contract", action="getsourcecode", address=address)
        name = result[0].get("ContractName") if isinstance(result, list) and result else ""
        cache[address] = name or "EOA or unverified"
    return cache[address]


def topic_to_address(topic):
    return "0x" + topic[-40:]


def collect(tx_hash, chain=1):
    tx = call(chain, module="proxy", action="eth_getTransactionByHash", txhash=tx_hash)
    if not isinstance(tx, dict):
        sys.exit("Transaction not found. Check the hash, chain ID and API key.")
    receipt = call(chain, module="proxy", action="eth_getTransactionReceipt", txhash=tx_hash)
    internal = call(chain, module="account", action="txlistinternal", txhash=tx_hash)
    internal = internal if isinstance(internal, list) else []

    # ETH that moved inside the transaction
    eth_moves = []
    top_value = int(tx["value"], 16)
    if top_value:
        eth_moves.append({"from": tx["from"], "to": tx["to"], "eth": top_value / 1e18})
    for item in internal:
        if int(item.get("value", "0")) > 0:
            eth_moves.append({"from": item["from"], "to": item["to"], "eth": int(item["value"]) / 1e18})

    # ERC20 tokens that moved, decoded from Transfer events
    token_moves = []
    for log in receipt.get("logs", []):
        topics = log.get("topics", [])
        if len(topics) == 3 and topics[0].lower() == TRANSFER_TOPIC:
            data = log.get("data", "0x")
            token_moves.append({
                "token": log["address"].lower(),
                "from": topic_to_address(topics[1]),
                "to": topic_to_address(topics[2]),
                "raw_amount": int(data, 16) if len(data) > 2 else 0,
            })

    # Net gain or loss per address, per asset (who ended up with the money?)
    net = defaultdict(int)
    for m in eth_moves:
        wei = int(round(m["eth"] * 1e18))
        net[(m["from"].lower(), "ETH")] -= wei
        net[(m["to"].lower(), "ETH")] += wei
    for m in token_moves:
        net[(m["from"], m["token"])] -= m["raw_amount"]
        net[(m["to"], m["token"])] += m["raw_amount"]

    names = {}
    key_addresses = [tx["from"].lower(), (tx["to"] or "").lower()]
    key_addresses += sorted({m["token"] for m in token_moves})[:10]
    for address in key_addresses:
        if address:
            contract_name(chain, address, names)

    gainers = sorted(
        ({"address": a, "asset": asset, "net_raw": v} for (a, asset), v in net.items() if v > 0),
        key=lambda g: -g["net_raw"],
    )[:10]

    return {
        "tx_hash": tx_hash,
        "chain_id": chain,
        "status": "success" if receipt.get("status") == "0x1" else "failed",
        "block": int(tx["blockNumber"], 16),
        "sender": tx["from"].lower(),
        "target": (tx["to"] or "contract creation").lower(),
        "function_selector": tx["input"][:10],
        "gas_used": int(receipt.get("gasUsed", "0x0"), 16),
        "log_count": len(receipt.get("logs", [])),
        "internal_call_count": len(internal),
        "eth_moves": eth_moves,
        "token_moves": token_moves,
        "biggest_gainers": gainers,
        "contract_names": names,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python fetch.py <tx_hash> [chain_id]")
    tx_hash = sys.argv[1]
    chain = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    evidence = collect(tx_hash, chain)

    Path("evidence").mkdir(exist_ok=True)
    out = Path("evidence") / (tx_hash[:12] + ".json")
    out.write_text(json.dumps(evidence, indent=2))

    print("Status: {}   Block: {}".format(evidence["status"], evidence["block"]))
    print("Sender: {}".format(evidence["sender"]))
    print("Target: {} ({})".format(evidence["target"], evidence["contract_names"].get(evidence["target"], "?")))
    print("ETH movements: {}   Token transfers: {}   Internal calls: {}".format(
        len(evidence["eth_moves"]), len(evidence["token_moves"]), evidence["internal_call_count"]))
    print("\nBiggest gainers:")
    for g in evidence["biggest_gainers"]:
        asset = g["asset"] if g["asset"] == "ETH" else evidence["contract_names"].get(g["asset"], g["asset"])
        print("  {}  +{}  {}".format(g["address"], g["net_raw"], asset))
    print("\nSaved to {}".format(out))
