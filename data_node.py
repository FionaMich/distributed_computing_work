"""
Data Node (Participant Node) - N1, N2, or N3

This file implements a **Server Node (Participant)** as described in the architecture:
- Run this script 3 times with different --node-id values to create nodes N1, N2, N3
- Each instance stores account balances and participates in distributed transactions
- Example usage:
  - Node N1: python data_node.py --node-id N1 --port 6001
  - Node N2: python data_node.py --node-id N2 --port 6002
  - Node N3: python data_node.py --node-id N3 --port 6003
"""

import argparse
import json
import logging
import socket
import threading
from pathlib import Path
from typing import Dict, Tuple

from common import recv_json, send_json, make_address


class AccountStore:
    """
    Very simple in-memory **participant node** storage.

    This represents the "Server Nodes (Participants)" from your slide:
    - Each running `data_node.py` process is one participant (labeled as N1, N2, or N3).
    - Each participant stores a subset of **accounts** and their balances.

    Responsibilities:
    - Maintain an account map: account_id -> current integer balance.
    - Keep a write-ahead **commit log** on disk for durability.
    - Use per-account **locks** to avoid race conditions when many
      transactions touch the same account concurrently (lock-based CC).
    """

    def __init__(self, node_id: str, data_dir: Path) -> None:
        self.node_id = node_id
        self.data_dir = data_dir
        self.state_file = data_dir / f"node_{node_id}_state.json"
        self.log_file = data_dir / f"node_{node_id}_log.jsonl"
        self.accounts: Dict[str, int] = {}
        self.locks: Dict[str, threading.Lock] = {}
        self.global_lock = threading.Lock()
        self._load_state()

    def _load_state(self) -> None:
        """
        Load the most recently persisted account balances from disk.
        If no state file exists yet, start from an empty store.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.state_file.exists():
            try:
                with self.state_file.open("r", encoding="utf-8") as f:
                    self.accounts = json.load(f)
                logging.info(
                    "Loaded state from %s: %s",
                    self.state_file,
                    self.accounts,
                )
            except (json.JSONDecodeError, OSError, ValueError) as e:
                # If the state file contains comments or malformed JSON, don't crash; start empty
                self.accounts = {}
                logging.warning(
                    "Invalid or unreadable state file %s (%s). Starting with empty accounts.",
                    self.state_file,
                    e,
                )
            
        else:
            self.accounts = {}
            logging.info("No state file found at %s. Starting with empty accounts.", self.state_file)

    def _persist_state(self) -> None:
        """
        Persist the entire in-memory account map to disk.
        This runs after each committed update to approximate durability.
        """
        with self.state_file.open("w", encoding="utf-8") as f:
            json.dump(self.accounts, f, indent=2)

    def _append_log(self, record: dict) -> None:
        """
        Append a single JSON record to the node's log file.

        The log can be used in your report to:
        - Show the order of transaction events (prepare, commit, abort).
        - Reason about recovery and which operations were applied.
        """
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def get_lock(self, account_id: str) -> threading.Lock:
        """
        Get (or lazily create) the lock object for a specific account.

        This is the core of the node's **lock-based concurrency control**:
        - Each account has its own lock.
        - Conflicting transactions that touch the same account will serialize.
        """
        with self.global_lock:
            if account_id not in self.locks:
                self.locks[account_id] = threading.Lock()
            return self.locks[account_id]

    def apply_delta(self, txid: str, account_id: str, delta: int) -> bool:
        """
        Apply a delta to an account under lock.
        Returns False if the resulting balance would be negative.
        """
        lock = self.get_lock(account_id)
        with lock:
            old_balance = self.accounts.get(account_id, 0)
            new_balance = old_balance + delta
            if new_balance < 0:
                return False
            # Log the change before applying (write-ahead)
            self._append_log(
                {
                    "txid": txid,
                    "account_id": account_id,
                    "delta": delta,
                    "old_balance": old_balance,
                    "new_balance": new_balance,
                    "action": "update",
                }
            )
            self.accounts[account_id] = new_balance
            self._persist_state()
            return True


def handle_connection(conn: socket.socket, addr: Tuple[str, int], store: AccountStore) -> None:
    try:
        message = recv_json(conn)
        if not message:
            return
        msg_type = message.get("type")
        if msg_type == "PREPARE":
            # Phase 1 request from the coordinator: "Can you apply these updates?"
            txid = message["txid"]
            ops = message["operations"]  # list of {"account_id": str, "delta": int}
            # Validate that all operations are feasible (no negative balances)
            # We do a conservative check by simulating under locks.
            # Note: For simplicity, we lock accounts in sorted order to reduce deadlock risk.
            # Use non-blocking locks: if locks can't be acquired immediately, abort the transaction.
            accounts = sorted({op["account_id"] for op in ops})
            acquired = []
            try:
                # Try to acquire all locks for accounts touched by this transaction (non-blocking).
                # If any lock is already held by another transaction, abort immediately.
                for acc in accounts:
                    lock = store.get_lock(acc)
                    if not lock.acquire(blocking=False):
                        # Lock is already held - transaction conflicts with another in progress
                        # Vote ABORT immediately rather than waiting
                        store._append_log(
                            {"txid": txid, "action": "prepare_failed", "reason": f"lock_contention_on_{acc}"}
                        )
                        send_json(conn, {"type": "VOTE_ABORT", "txid": txid})
                        return
                    acquired.append(lock)
                # Check feasibility of the transaction under those locks.
                temp_balances = {k: store.accounts.get(k, 0) for k in accounts}
                for op in ops:
                    acc = op["account_id"]
                    delta = int(op["delta"])
                    temp_balances[acc] = temp_balances.get(acc, 0) + delta
                    if temp_balances[acc] < 0:
                        # Local constraint violated -> vote to ABORT globally.
                        store._append_log(
                            {"txid": txid, "action": "prepare_failed", "reason": "insufficient_balance"}
                        )
                        send_json(conn, {"type": "VOTE_ABORT", "txid": txid})
                        return
                # Feasible under current balances:
                # - record the intent in the log
                # - vote YES (VOTE_COMMIT) back to the coordinator
                store._append_log(
                    {"txid": txid, "action": "prepare_ok", "operations": ops}
                )
                send_json(conn, {"type": "VOTE_COMMIT", "txid": txid})
            finally:
                for lock in acquired:
                    lock.release()

        elif msg_type == "COMMIT":
            # Phase 2 request from the coordinator: "Apply the updates permanently."
            txid = message["txid"]
            ops = message["operations"]
            ok = True
            for op in ops:
                acc = op["account_id"]
                delta = int(op["delta"])
                if not store.apply_delta(txid, acc, delta):
                    ok = False
                    break
            if ok:
                store._append_log({"txid": txid, "action": "commit"})
                send_json(conn, {"type": "ACK", "txid": txid, "status": "COMMITTED"})
            else:
                # This should not normally happen if PREPARE succeeded, but we handle defensively.
                store._append_log({"txid": txid, "action": "commit_failed"})
                send_json(conn, {"type": "ACK", "txid": txid, "status": "FAILED"})

        elif msg_type == "ABORT":
            # Global decision is ABORT; we only need to log this outcome.
            txid = message["txid"]
            store._append_log({"txid": txid, "action": "abort"})
            send_json(conn, {"type": "ACK", "txid": txid, "status": "ABORTED"})

        elif msg_type == "READ":
            # Simple helper RPC: read the current balance of a single account.
            account_id = message["account_id"]
            balance = store.accounts.get(account_id, 0)
            send_json(
                conn,
                {
                    "type": "READ_RESULT",
                    "account_id": account_id,
                    "balance": balance,
                },
            )

        else:
            send_json(conn, {"type": "ERROR", "error": f"Unknown message type {msg_type}"})
    except Exception as e:
        logging.exception("Error handling connection from %s: %s", addr, e)
    finally:
        conn.close()


def run_node(node_id: str, host: str, port: int, data_dir: str) -> None:
    """
    Run a data node instance.
    
    Args:
        node_id: The node label (N1, N2, or N3) - used to identify this node
        host: Host address to bind to
        port: Port number (N1=6001, N2=6002, N3=6003)
        data_dir: Directory for storing node state and logs
    """
    logging.basicConfig(
        level=logging.INFO,
        format=f"[NODE {node_id}] %(asctime)s %(levelname)s %(message)s",
    )
    # Create store after logging is initialized so _load_state can log
    store = AccountStore(node_id=node_id, data_dir=Path(data_dir))
    logging.info("Starting data node %s (Participant Node) on %s:%s", node_id, host, port)

    # SO_REUSEPORT is not available on Windows; try with it first and fall back gracefully.
    # Do not request SO_REUSEPORT at all to avoid Windows-specific issues.
    try:
        server = socket.create_server(make_address(host, port))
    except Exception as exc:
        logging.error("Failed to bind node %s on %s:%s: %s", node_id, host, port, exc)
        raise

    with server:
        while True:
            conn, addr = server.accept()
            t = threading.Thread(
                target=handle_connection, args=(conn, addr, store), daemon=True
            )
            t.start()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Distributed account data node (Participant Node - N1, N2, or N3)"
    )
    parser.add_argument(
        "--node-id", 
        required=True, 
        help="Logical node identifier: N1, N2, or N3"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True, help="Port number (N1=6001, N2=6002, N3=6003)")
    parser.add_argument(
        "--data-dir", default="data", help="Directory where node state/logs are stored"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_node(args.node_id, args.host, args.port, args.data_dir)


