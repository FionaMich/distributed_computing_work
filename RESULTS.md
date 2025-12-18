# Results Analysis

This document provides analysis and observations of what happens when running the distributed transaction system.

## 1. Starting the Nodes

### Process
1. Start three data nodes (N1, N2, N3)
2. Start the coordinator

### Expected Observations

#### Data Nodes Startup

Each node should:
- Load its state file from disk (e.g., `data/node_N1_state.json`)
- Log the loaded accounts and balances
- Start listening on its assigned port (N1=6001, N2=6002, N3=6003)

**Example log output for N1:**
```
[NODE N1] 2025-12-16 XX:XX:XX,XXX INFO Loaded state from data/node_N1_state.json: {'A': 100}
[NODE N1] 2025-12-16 XX:XX:XX,XXX INFO Starting data node N1 (Participant Node) on 127.0.0.1:6001
```

**What to verify:**
- Each node loads the correct initial balances from its state file
- No errors occur during startup
- All nodes are listening on their respective ports
- The state loaded matches what's in the JSON files

#### Coordinator Startup

The coordinator should:
- Scan for incomplete transactions from previous runs
- Start listening on port 5000
- Be ready to coordinate transactions across all three nodes

**Example log output:**
```
[COORD] 2025-12-16 XX:XX:XX,XXX INFO No incomplete transactions found. System is consistent.
[COORD] 2025-12-16 XX:XX:XX,XXX INFO Coordinator listening on 127.0.0.1:5000
```

**What to verify:**
- Coordinator starts without errors
- If there were incomplete transactions, they are aborted
- Coordinator knows about all three nodes (N1, N2, N3)

### State Files Before Transactions

**Expected initial state:**
- `data/node_N1_state.json`: Contains account A (e.g., `{"A": 100}`)
- `data/node_N2_state.json`: Contains account B (e.g., `{"B": 100}`)
- `data/node_N3_state.json`: Contains account C (e.g., `{"C": 20000}`)

---

## 2. Concurrent Process Demonstration

### Running the Demo

Execute the concurrent transfers demo script:
- **Windows**: `.\demo_concurrent_transfers.ps1`
- **Linux/Mac**: `bash demo_concurrent_transfers.sh`

This runs three transfers simultaneously:
1. **N1 → N2**: Alice (N1/A) sends 10 to Bob (N2/B)
2. **N2 → N1**: Bob (N2/B) sends 10 to Alice (N1/A)
3. **N3 → N1**: Charlie (N3/C) sends 20 to Alice (N1/A)

### Expected Results

#### Coordinator Logs

The coordinator should show:
- Three transactions starting with unique transaction IDs (UUIDs)
- PREPARE phase for each transaction
- Node votes (VOTE_COMMIT or VOTE_ABORT)
- COMMIT phase for successful transactions
- Transaction completion status

**Example coordinator log pattern:**
```
[COORD] INFO Starting transaction <txid1>: N1/A -> N2/B amount=10
[COORD] INFO Starting transaction <txid2>: N2/B -> N1/A amount=10
[COORD] INFO Starting transaction <txid3>: N3/C -> N1/A amount=20
[COORD] INFO Node N1 vote for <txid1>: True
[COORD] INFO Node N2 vote for <txid1>: True
[COORD] INFO All nodes voted COMMIT for <txid1>. Committing.
[COORD] INFO Transaction <txid1> committed.
```

**Key observations:**
- Transactions can process concurrently (not serialized)
- Each transaction goes through PREPARE → COMMIT phases
- All nodes vote on each transaction
- Transactions complete independently

#### Node Logs

**Node N1 logs** (`data/node_N1_log.jsonl`):
- Should show PREPARE requests for transactions involving N1
- Should show updates to account A (both credits and debits)
- Should show COMMIT confirmations

**Example N1 log entries:**
```json
{"txid": "<txid1>", "action": "prepare_ok", "operations": [{"account_id": "A", "delta": -10}]}
{"txid": "<txid1>", "account_id": "A", "delta": -10, "old_balance": 100, "new_balance": 90, "action": "update"}
{"txid": "<txid1>", "action": "commit"}
{"txid": "<txid2>", "action": "prepare_ok", "operations": [{"account_id": "A", "delta": 10}]}
{"txid": "<txid2>", "account_id": "A", "delta": 10, "old_balance": 90, "new_balance": 100, "action": "update"}
{"txid": "<txid2>", "action": "commit"}
{"txid": "<txid3>", "action": "prepare_ok", "operations": [{"account_id": "A", "delta": 20}]}
{"txid": "<txid3>", "account_id": "A", "delta": 20, "old_balance": 100, "new_balance": 120, "action": "update"}
{"txid": "<txid3>", "action": "commit"}
```

**Node N2 logs** (`data/node_N2_log.jsonl`):
- Should show PREPARE requests for transactions involving N2
- Should show updates to account B

**Node N3 logs** (`data/node_N3_log.jsonl`):
- Should show PREPARE requests for transactions involving N3
- Should show updates to account C (debit of 20)

### Final State Analysis

After all transactions complete, verify the final balances:

**Expected final balances:**
- **N1/A**: Started with 100
  - Transaction 1: -10 (sent to Bob) → 90
  - Transaction 2: +10 (received from Bob) → 100
  - Transaction 3: +20 (received from Charlie) → **120**
- **N2/B**: Started with 100
  - Transaction 1: +10 (received from Alice) → 110
  - Transaction 2: -10 (sent to Alice) → **100**
- **N3/C**: Started with 20000
  - Transaction 3: -20 (sent to Alice) → **19980**

### Verification Checklist

- [ ] All three transactions completed successfully
- [ ] Coordinator logs show all transactions went through PREPARE → COMMIT
- [ ] All nodes voted COMMIT for their respective transactions
- [ ] Node logs show proper sequencing of PREPARE → UPDATE → COMMIT
- [ ] Final balances in state files match expected values
- [ ] No transactions were aborted
- [ ] Accounts never went negative
- [ ] Concurrent processing occurred (transactions didn't wait for each other)

### Key Insights

1. **Concurrent Processing**: Multiple transactions can be processed simultaneously by the coordinator, demonstrating that the system handles concurrent requests.

2. **Two-Phase Commit**: Each transaction follows the 2PC protocol:
   - Phase 1 (PREPARE): Nodes check feasibility and vote
   - Phase 2 (COMMIT): Nodes apply changes if all voted commit

3. **Atomicity**: Each transaction is atomic - either all nodes commit or all abort.

4. **Consistency**: Account balances remain consistent across all nodes, with no negative balances.

5. **No Serialization**: Since these transactions don't conflict (they use different accounts), they process concurrently without blocking.

---

## Next Steps

After completing this analysis, proceed to:
- **Conflicting Locks Demonstration**: Run `demo_conflicting_locks.ps1` (or `.sh`) to see how per-account locks handle conflicting concurrent transactions.

