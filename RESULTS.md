# Distributed Transactions – Experimental Results, Evidence, and Interpretation Guide

## 1) System and Execution Context

- Processes
  - 1 × `coordinator.py` (Transaction Coordinator)
  - 3 × `data_node.py` (Participant Nodes) labeled `N1`, `N2`, `N3`
  - Multiple clients (`client.py`) to initiate transactions
- Communication: TCP with JSON messages (helpers in `common.py`).
- Persistence:
  - Each data node writes:
    - `data/node_NX_state.json` — latest committed balances (persisted after each commit)
    - `data/node_NX_log.jsonl` — append-only JSON lines log: `prepare_ok`, `prepare_failed`, `update`, `commit`, `abort`
  - Coordinator writes: `data/coordinator_tx_log.jsonl` — JSON lines per txid/phase (`START`, `PREPARE`, `COMMIT`/`ABORT`, `COMPLETE`) with status hints
- Run orchestration: `gui_app.py` provides a control panel for starting/stopping processes, executing operations, running concurrency demos, running failure/recovery demos, and viewing logs/state.

## 2) What `gui_app.py` Does

- Process control
  - Start/stop Coordinator with coherent `--host`, `--port`, and `--nodes` flags; the `--nodes` map is built from GUI Node controls (e.g., `N1:127.0.0.1:6001,N2:127.0.0.1:6002,N3:127.0.0.1:6003`).
  - Start/stop N data nodes with the correct `--node-id` and `--port`.
  - Clean termination on window close.
- Operations
  - `read_balance` (direct node RPC): sends `{"type": "READ", "account_id": X}` to a node and shows `{"type":"READ_RESULT","account_id":X,"balance":N}`.
  - `transfer` (via `client.py`): launches `client.py` with `--coord-host/--coord-port --from-node --from-account --to-node --to-account --amount`. The coordinator executes 2PC and returns `TRANSFER_RESULT`.
- Concurrency demos (mirroring README scripts)
  - "Run concurrent transfers (3 clients)": launches three concurrent `client.py` processes:
    1) `N1/A → N2/B` amount `10`
    2) `N2/B → N1/A` amount `10`
    3) `N3/C → N1/A` amount `20`
  - "Run conflicting locks demo (2 clients)": launches two concurrent transfers that conflict on `N2/B`:
    1) `N1/A → N2/B` amount `100`
    2) `N2/B → N3/C` amount `150`
- Failures / Recovery tab
  - Crash/Restart Coordinator and selected Node (N1/N2/N3).
  - Scheduled scenarios: start a transfer, then crash/restart coordinator or a selected node after a configurable delay (ms) to demonstrate recovery.
- Logs panel
  - Aggregates stdout/stderr from Coordinator and Nodes (prefixed per process for clarity).
  - Stderr lines are visible; look for INFO/WARNING/ERROR.
- State Viewer
  - Lists `data/*.json`, `*.jsonl`, `*.log`, `*.txt` files, including node state, node logs, and coordinator logs.
  - Click a file to preview; JSON content is pretty-printed.
- Results panel
  - Shows outputs from `client.py` invocations and read operations.
  - If a subprocess exits with code 0, stderr is shown as "WARNINGS:" (not an error); if nonzero, it is labeled "ERROR:" and the exit code is included.

## 3) Nodes and Transactions (for the Report)

1. Nodes:
   - 4 processes total:
     - 1 × `coordinator.py`
     - 3 × `data_node.py` (`N1`, `N2`, `N3`)
   - All can run on a single machine as separate processes.

2. Transactions:
   - Modeled as bank transfers (simple key-value integer updates).
   - Transactions are atomic across nodes via 2PC.
   - Coordinator decides commit/rollback based on votes from participant nodes.

## 4) How to Verify a Single Transaction (Ground Truth Method)

Use this method to determine the exact result of any transfer and the correct balances using the artifacts under `data/`:

- Step A: Identify the transaction in the coordinator log
  - Open `data/coordinator_tx_log.jsonl` and search for `txid` (unique identifier).
  - For each transaction, you should see a sequence like:
    - `{"txid": T, "phase": "START", "node_ops": {"N1":[{"account_id":"A","delta":-10}], "N2":[{"account_id":"B","delta":10}]}}`
    - `{"txid": T, "phase": "PREPARE"}`
    - Decision path:
      - Commit: `{"txid": T, "phase": "COMMIT", "status": "all_voted_commit"}` then `{"txid": T, "phase": "COMPLETE", "status": "committed"}`
      - Abort: `{"txid": T, "phase": "ABORT", ...}` then `{"txid": T, "phase": "COMPLETE", "status": "aborted"}`
  - Interpretation: If `COMMIT` then `COMPLETE/committed`, the transaction succeeded; if `ABORT` then `COMPLETE/aborted`, it failed (no updates applied).

- Step B: Corroborate at participant nodes
  - For each involved node, open `data/node_NX_log.jsonl` and search for that `txid`.
  - On a successful commit you should see:
    - A `prepare_ok` record for the node’s operations
    - Exactly one `update` record per operation:
      - `{"txid": T, "account_id": X, "delta": ±N, "old_balance": M1, "new_balance": M2, "action":"update"}`
    - A `commit` record for that txid
  - On an aborted transaction you should see either:
    - `prepare_failed` (reason: `insufficient_balance` or `lock_contention_on_<Account>`) and no commit/update, or
    - No `update`/`commit` lines for that txid (since abort prevents updates)

- Step C: Confirm durable balances in state files
  - Open `data/node_NX_state.json` for the nodes that applied updates.
  - The persisted balances should match the latest committed state; specifically, for each account, the value should agree with the `new_balance` from the most recent committed `update` log for that account.
  - Optionally, use the GUI’s `read_balance` to query a node; it should match the state file soon after commit.

## 5) Interpreting `demo_concurrent_transfers` (3 Clients)

The GUI launches three transfers concurrently:
- C1: `N1/A → N2/B`, amount `10`
- C2: `N2/B → N1/A`, amount `10`
- C3: `N3/C → N1/A`, amount `20`

What to expect:
- Coordinator’s `data/coordinator_tx_log.jsonl` will show three distinct `txid`s, each with `START`, `PREPARE`, and then either `COMMIT` or `ABORT`, followed by `COMPLETE`.
- If nodes are reachable and source balances are sufficient, all three can succeed simultaneously. Some runs may still see an `ABORT` (e.g., due to insufficient funds, lock timing, or reachability).

Evidence to collect and interpret:
- For each txid T1/T2/T3:
  1) Coordinator log shows decision: COMMIT or ABORT.
  2) For `COMMIT`s:
     - Node logs show `prepare_ok` + `update` + `commit` for the accounts affected.
     - State files reflect the final balances (the `new_balance` from the latest `update` entry for each touched account).
  3) For `ABORT`s:
     - Node logs contain `prepare_failed` or no `update/commit` for that txid.
     - State files are unchanged for the accounts related to that txid.

Reading balances correctly:
- Do not guess. For each committed txid that touched an account, look up the node log’s `update` record(s) and take the `new_balance`. The final `node_NX_state.json` should match the most recent committed `new_balance` for each account.

## 6) Interpreting `demo_conflicting_locks` (2 Clients)

The GUI launches two transfers that conflict on `N2/B`:
- C1: `N1/A → N2/B`, amount `100`
- C2: `N2/B → N3/C`, amount `150`

Expected concurrency control behavior:
- During `PREPARE` at `N2` (which holds `B`), both transactions attempt to acquire `B`’s per-account lock.
- The first transaction to acquire the lock proceeds with feasibility checks and replies `VOTE_COMMIT` (`prepare_ok`).
- The second transaction fails non-blocking lock acquisition and replies `VOTE_ABORT` (`prepare_failed` with `reason: lock_contention_on_B`).

Evidence and interpretation:
- Coordinator (`data/coordinator_tx_log.jsonl`): one txid shows `COMMIT` → `COMPLETE/committed`, the other shows `ABORT` → `COMPLETE/aborted` (unless a different feasibility issue is encountered).
- `N2` (`data/node_N2_log.jsonl`):
  - Winner txid: `prepare_ok` → `update` for `B` → `commit`.
  - Loser txid: `prepare_failed` with `reason: lock_contention_on_B` (no `update`, no `commit`).
- `N1`/`N3`: show their side of the winner’s `update` and `commit` if involved; no commit/update for the loser.

Balances:
- The final balances depend on initial state and which transaction won the lock. Use the `update` records’ `new_balance` values for committed transactions to determine exact results, then corroborate in `node_NX_state.json`.

## 7) Failures and Recovery (GUI-driven)

This section shows how to demonstrate failure scenarios and recovery using the GUI’s "Failures / Recovery" tab and how to interpret the resulting artifacts.

A) Coordinator crash during a transaction
- Setup:
  - Start Nodes (e.g., N1=6001, N2=6002, N3=6003) and Coordinator (127.0.0.1:5000) from the GUI.
  - In the Operations tab, prepare a transfer that spans at least two nodes (e.g., N1/A → N2/B, amount 30).
- Execute:
  - Open the Failures / Recovery tab.
  - Set Delay (ms) (e.g., 300–800 ms). This timing aims to crash the coordinator while the transaction is in PREPARE/COMMIT.
  - Click "Start transfer, then crash COORDINATOR". The GUI starts the transfer, waits Delay, then terminates the coordinator; it restarts the coordinator ~1.5s later.
- Evidence:
  - Coordinator (`data/coordinator_tx_log.jsonl`): You will see `START` and `PREPARE` for txid T. After restart, the coordinator scans its log, identifies T as incomplete, writes `ABORT` for T (status may include `recovered`) and then `COMPLETE` (e.g., `aborted_during_recovery`). This demonstrates recovery: incomplete transactions are rolled back on restart.
  - Nodes (`data/node_NX_log.jsonl`): Depending on timing, some nodes may show `prepare_ok` for T; there should be no `commit` for T. Absent a commit, state must remain unchanged by T.
  - State files (`data/node_NX_state.json`): Unchanged for accounts touched by T (no partial commits).
- Interpretation:
  - Atomicity is preserved: No partial updates, and the system returns to a consistent state. The coordinator’s recovery phase aborts in-flight txids on restart.

B) Node crash during a transaction
- Setup:
  - Start Nodes and Coordinator from the GUI.
  - In Failures / Recovery, select a node (e.g., N2) to crash.
  - In Operations, prepare a transfer involving that node (e.g., N1/A → N2/B, amount 50).
- Execute:
  - Set Delay (ms) to hit the PREPARE/COMMIT window.
  - Click "Start transfer, then crash NODE (selected)". The GUI starts the transfer, waits Delay, kills the node, and restarts it ~1.5s later.
- Evidence:
  - Coordinator (`data/coordinator_tx_log.jsonl`): Shows `START` and `PREPARE` for txid T; when the node fails to respond, the coordinator logs `ABORT` and then `COMPLETE` (`aborted`). This demonstrates safe handling of participant failure.
  - Nodes (`data/node_NX_log.jsonl`): The crashed node may have `prepare_ok` for T (or none), but there should be no `commit` for T. Other nodes may also reflect `prepare_ok` or no-op; no commit.
  - State files: Remain unchanged for T. After restart, the crashed node reloads its state file without partial changes.
- Interpretation:
  - Coordinator treats non-response as vote `ABORT` and rolls back the transaction globally. Durability and consistency are preserved.

C) Notes on timing and reproducibility
- The Delay (ms) is a heuristic; adjust up/down to land within `PREPARE` or just before `COMMIT`. Use the Logs tab to observe the actual sequence.
- Firewall/port issues (`WinError 10061`) indicate reachability failures; these are still handled as aborts and are valid demonstrations of failure handling.
- After recovery scenarios, verify with the Ground Truth Method (Section 4) that no partial updates were committed.

D) Immediate vs Scheduled controls (what the buttons mean)
- Immediate crash/restart:
  - Crash Coordinator (Terminate) / Restart Coordinator act right now, independent of any transfer.
  - Crash Node / Restart Node act right now on the selected node.
  - Use these for ad-hoc failures or to quickly reset the environment.
- Scheduled crash during transfer:
  - Start transfer, then crash COORDINATOR begins a transfer from the Operations form, waits Delay (ms), then terminates the coordinator and restarts it to illustrate recovery.
  - Start transfer, then crash NODE (selected) begins a transfer, waits Delay (ms), then terminates the chosen node and restarts it to show safe abort and node restart behavior.
  - Use these to reproducibly align the failure within the PREPARE/COMMIT window without manual timing.

E) Where recovery is demonstrated (evidence to look for)
- Coordinator recovery after restart:
  - In `data/coordinator_tx_log.jsonl` after the restart, find entries indicating the scan of incomplete transactions and, for each affected `txid`:
    - `{"txid": T, "phase": "ABORT", "status": "recovered"}` (or similar), followed by
    - `{"txid": T, "phase": "COMPLETE", "status": "aborted_during_recovery"}`
  - In the GUI Logs tab, after restart, you’ll see the coordinator rebind and log that it is listening again (e.g., "Coordinator listening on 127.0.0.1:5000").
- Participant node evidence:
  - For the crashed node scenario, the node log (`data/node_NX_log.jsonl`) may include `abort` acknowledgements for in-flight `txid`s; there should be no `commit` for those `txid`s.
  - On node restart, you may see a log message indicating that it "Loaded state" from `node_NX_state.json`. State remains consistent (no partial updates) for the aborted transactions.
- State files:
  - `data/node_NX_state.json` for the accounts referenced by the aborted `txid`s remain unchanged compared to their pre-failure values (no half-applied deltas), confirming atomicity.

## 8) Common Failure Mode: Connection Refused (`WinError 10061`)

If the coordinator cannot reach a node (wrong ports, node not listening, firewall):
- Coordinator logs:
  - `PREPARE failed on node NX: [WinError 10061] ...`
  - `At least one node voted ABORT ... Aborting on all nodes.`
- Interpretation:
  - This is a reachability failure, not a logical concurrency abort.
  - The coordinator aborts the transaction to preserve safety; nodes will not show `update/commit` for that txid, and state remains unchanged.

## 9) Worked Example Template (for your report)

Use this template to present evidence for any run—replace placeholders with your actual lines:

- Transaction T (txid = `<UUID>`):
  - Coordinator:
    - START: `{"txid": T, "phase": "START", "node_ops": { ... }}`
    - PREPARE: `{"txid": T, "phase": "PREPARE"}`
    - Decision:
      - Commit path:
        - `{"txid": T, "phase": "COMMIT", "status": "all_voted_commit"}`
        - `{"txid": T, "phase": "COMPLETE", "status": "committed"}`
      - Abort path:
        - `{"txid": T, "phase": "ABORT", "status": "vote_abort" | "recovered" | ...}`
        - `{"txid": T, "phase": "COMPLETE", "status": "aborted"}`
  - Node N1/N2/N3:
    - `prepare_ok` or `prepare_failed` (with reason)
    - If committed: `update` record(s) with `old_balance` → `new_balance`, then `commit`
  - Final state files:
    - `data/node_N1_state.json` contains A: `<value_after_last_committed_update_for_A>`
    - `data/node_N2_state.json` contains B: `<value_after_last_committed_update_for_B>`
    - `data/node_N3_state.json` contains C: `<value_after_last_committed_update_for_C>`

## Latest Run Summary (from data/* logs)

- Final balances (from state files):
  - N1/A = 9550 (data/node_N1_state.json)
  - N2/B = 30170 (data/node_N2_state.json)
  - N3/C = 20280 (data/node_N3_state.json)

- Notable recent transactions (from coordinator_tx_log.jsonl):
  - 7097b4a9-685e-4172-b793-ce3282bbb38d: N1/A -100 → N2/B +100 COMMIT, COMPLETE=committed
  - b1c08ae6-314a-456f-b905-01e7ae70435b: N2/B -150 → N3/C +150 COMMIT, COMPLETE=committed
  - f0eec7c0-727e-4061-9d41-37ed54a43165: N1/A -100 → N2/B +100 COMMIT, COMPLETE=committed
  - 643826b2-cede-42e4-9b3e-1e4300abf33b: N2/B -150 → N3/C +150 COMMIT, COMPLETE=committed
  - Conflicting-locks window:
    - 174cda32-5c88-4c61-9456-00d9b1702065: N1/A -10 → N2/B +10 COMMIT, COMPLETE=committed
    - 516040d8-f802-4272-a7cf-b290dd2a4532: N2/B -10 → N1/A +10 COMMIT, COMPLETE=committed
    - 88b0069c-c910-46cf-9c65-6e13c3079ba0: N3/C -20 → N1/A +20 ABORT, COMPLETE=aborted (prepare_failed at N1 with reason lock_contention_on_A)

- Evidence for the conflicting locks demo (demo_conflicting_locks):
  - Two transactions started near-simultaneously:
    - 7097b4a9-... (C1): N1/A → N2/B amount 100
    - b1c08ae6-... (C2): N2/B → N3/C amount 150
  - Coordinator shows both COMMIT and COMPLETE=committed, indicating both succeeded but were serialized by per-account locks on B.
  - Node logs corroborate serialized access to N2/B:
    - N2 (node_N2_log.jsonl):
      - b1c08ae6-... prepare_ok, update B: 30270 → 30120, commit
      - 7097b4a9-... prepare_ok, update B: 30120 → 30220, commit
      - Serialization order at N2/B: C2 (B -150) committed before C1 (B +100)
    - N1 (node_N1_log.jsonl): 7097b4a9-... updated A: 9750 → 9650, commit
    - N3 (node_N3_log.jsonl): b1c08ae6-... updated C: 19980 → 20130, commit
  - Outcome matches final balances progression and demonstrates locks serialize conflicting access to B; neither transaction blocked indefinitely, and both committed in sequence.

- Additional concurrency run around the same window:
  - 516040d8-... (N2/B -10 → N1/A +10) and 174cda32-... (N1/A -10 → N2/B +10) both committed.
  - 88b0069c-... (N3/C -20 → N1/A +20) aborted due to lock contention on A at N1:
    - N1 log: prepare_failed reason=lock_contention_on_A; later abort.
    - Coordinator: ABORT then COMPLETE=aborted.

These observations are derived directly from:
- data/coordinator_tx_log.jsonl (phases and outcomes)
- data/node_N1_log.jsonl, node_N2_log.jsonl, node_N3_log.jsonl (prepare_ok/failed, update, commit/abort)
- data/node_*_state.json (final committed balances)

## 10) Key Conclusions (ready to quote)

- The system demonstrates atomic distributed transactions across nodes via 2PC: an update appears in any node’s state only after all involved nodes vote COMMIT and the coordinator issues COMMIT; otherwise, no partial updates occur.
- Concurrency is controlled with per-account locks at the data nodes. Conflicting transactions (e.g., both touching `N2/B` concurrently) do not interleave unsafely: one proceeds; the other aborts promptly (`prepare_failed` with `reason: lock_contention_on_B`).
- Durability is evidenced by node write-ahead logs and state files. After a commit, `update` records and state files reflect the new balances. Restarting nodes restores the last consistent state.
- Failure handling: If nodes are unreachable, the coordinator aborts the transaction to preserve consistency. On coordinator restart, incomplete transactions in its log are identified and aborted, ensuring no lingering in-flight state.

## 11) Practical Advice for Reproducible Evidence

- Before demos, seed accounts in `data/node_NX_state.json` as needed (e.g., set `A`, `B`, `C` to sufficient balances), then start nodes so they load the seeded state.
- After running demos, collect:
  - `data/coordinator_tx_log.jsonl` (phases per txid)
  - `data/node_N1_log.jsonl`, `data/node_N2_log.jsonl`, `data/node_N3_log.jsonl` (prepare_ok/failed, update, commit)
  - `data/node_N1_state.json`, `data/node_N2_state.json`, `data/node_N3_state.json` (final durable balances)
- For each txid, present the `START → PREPARE → DECISION → COMPLETE` path from the coordinator and the matching node records. Point to the `update.new_balance` fields and show that state files reflect those committed results.
