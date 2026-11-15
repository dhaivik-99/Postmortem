# Postmortem

**An AI incident responder for onchain exploits.** Give it the hash of an attack transaction and it follows the money, finds the likely victim, reads the victim contract, and writes a structured incident report: what happened, how the attack worked, the root cause, and where the funds went.

## Why

After a hack, the first questions are always the same: what happened, how did it work, and where did the money go? Today, researchers answer them by hand, reading traces and transfers on Etherscan, often under time pressure while funds are still moving. Postmortem automates the first draft so an analyst starts from a reconstruction instead of a blank page.

Example: in March 2023 Euler Finance lost about $197M in a single flash-loan attack. Researchers reconstructed it from public onchain data within hours. That reconstruction is the job this tool does.

## How it works

```
tx hash
   |
   v
1. fetch.py        Collect evidence from Etherscan: transaction, receipt,
                   internal ETH transfers, ERC20 Transfer events, contract names
   |
   v
2. investigate.py  Net every address gain and loss to find the attacker (biggest
                   gainer) and likely victim (biggest loser), pull the victim
                   verified source code, and have an investigator agent write
                   the incident report
   |
   v
3. evaluate.py     Run the investigator on a labeled set of real hacks and score
                   how often it names the correct attack type
```

### Key design choices

- **Follow the money backwards.** Attack transactions usually call the attacker own contract, not the victim. Postmortem computes net flows per address and asset to find who actually lost funds, then investigates that contract.
- **Grounded reports.** The agent may only use addresses, amounts and names present in the evidence, and must end every report with a "Confidence and gaps" section listing what the evidence does not show.
- **Fixed attack taxonomy.** Every report classifies the incident as one of: reentrancy, access control, signature replay, oracle or price manipulation, flash loan business logic, bridge or message verification, rug pull or admin abuse, or other. This makes results measurable.
- **Provider-agnostic.** `llm.py` switches between Gemini and Claude with one line in `.env`, so the pipeline can be compared across models without code changes.

## Report format

Each report is saved to `reports/<tx>.md` with these sections:

1. Summary
2. Attack type
3. Step by step reconstruction
4. Root cause
5. Where the funds went
6. Confidence and gaps

## Evaluation

`cases.json` holds real exploit transactions, sourced from [DeFiHackLabs](https://github.com/SunWeb3Sec/DeFiHackLabs), each labeled with its correct attack type. `evaluate.py` investigates every case and writes `scorecard.json`.

| Metric | Result |
|---|---|
| Hacks evaluated | _pending first run_ |
| Correct attack type | _pending first run_ |

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install python-dotenv google-genai anthropic
```

Create a `.env` file (never commit it):

```
PROVIDER=gemini
GEMINI_API_KEY=your-key
ETHERSCAN_API_KEY=your-key
```

Both keys are available on free tiers: Gemini at aistudio.google.com and Etherscan at etherscan.io. To use Claude instead, set `PROVIDER=anthropic` and `ANTHROPIC_API_KEY`.

## Usage

Investigate one transaction (chain ID defaults to 1, Ethereum mainnet):

```bash
python investigate.py <tx_hash> [chain_id]
```

Score the investigator on every case in `cases.json`:

```bash
python evaluate.py
```

Collect raw evidence only:

```bash
python fetch.py <tx_hash> [chain_id]
```

## Limitations

- Token amounts are reported in raw base units, since decimals are not fetched.
- Only the first verified contract among the likely victims is read, truncated for length.
- Evidence comes from one transaction. Multi-transaction attacks (setup, then exploit) need each transaction investigated.
- Reports are a first draft for an analyst, not a final verdict.

## Related projects

- [web3-attack-pocs](https://github.com/dhaivik-99/web3-attack-pocs): Foundry reproductions of five real-world exploits
- [Tribunal](https://github.com/dhaivik-99/Tribunal): multi-agent smart contract auditor that debates every finding and validates it with a working exploit
