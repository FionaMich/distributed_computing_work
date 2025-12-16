"""
Coordinator Node - Transaction Manager

This file implements the **Coordinator Node** as described in the architecture:
- Single instance runs to manage all distributed transactions
- Orchestrates two-phase commit (2PC) protocol across data nodes N1, N2, N3
- Does NOT store account data itself - only coordinates transactions
- Example usage:
  python coordinator.py --port 5000 --nodes N1:127.0.0.1:6001,N2:127.0.0.1:6002,N3:127.0.0.1:6003
"""

import argparse
import json
import logging
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Tuple

from common import send_json, recv_json, make_address


class Coordinator:
    """
    Simple **Coordinator Node** implementing a two-phase commit protocol.

    This corresponds to the "Coordinator Node" in your slide:
    - It does NOT store business data itself.
    - It orchestrates distributed transactions across server/participant nodes.
    - It is responsible for deciding COMMIT vs ABORT to preserve ACID-like
      properties (especially Atomicity and Consistency) across all nodes.
    
    Crash Recovery:
    - Maintains a transaction log file to track in-flight transactions.
    - On restart, scans for incomplete transactions and aborts them.
    - This ensures nodes never remain in an uncertain state after coordinator crash.
    """

    def __init__(self, nodes: Dict[str, Tuple[str, int]], timeout: float = 5.0, data_dir: str = "data") -> None:
        self.nodes = nodes
        self.timeout = timeout
        self.lock = threading.Lock()
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.tx_log_file = self.data_dir / "coordinator_tx_log.jsonl"
        # Track active transactions for recovery
        self.active_txs: Dict[str, Dict] = {}
        # Load and recover incomplete transactions from log
        self._recover_incomplete_transactions()

    def _log_transaction(self, txid: str, phase: str, node_ops: Dict[str, List[dict]] = None, status: str = None) -> None:
        """
        Append a transaction log entry for crash recovery.
        
        Phases: START, PREPARE, COMMIT, ABORT, COMPLETE
        """
        entry = {
            "txid": txid,
            "phase": phase,
            "timestamp": time.time(),
        }
        if node_ops:
            entry["node_ops"] = {k: v for k, v in node_ops.items()}
        if status:
            entry["status"] = status
        
        with self.tx_log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        
        # Keep in-memory tracking for active transactions
        if phase in ["START", "PREPARE", "COMMIT"]:
            self.active_txs[txid] = entry
        elif phase in ["COMPLETE", "ABORT"]:
            self.active_txs.pop(txid, None)

    def _recover_incomplete_transactions(self) -> None:
        """
        On coordinator restart, scan the transaction log for incomplete transactions
        and abort them to ensure system consistency.
        
        Incomplete transactions are those that reached PREPARE or COMMIT phase
        but never reached COMPLETE or ABORT.
        """
        if not self.tx_log_file.exists():
            logging.info("No transaction log found. Starting fresh.")
            return
        
        incomplete_txs = {}
        # Read all log entries
        with self.tx_log_file.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    txid = entry["txid"]
                    phase = entry["phase"]
                    
                    if phase in ["START", "PREPARE", "COMMIT"]:
                        incomplete_txs[txid] = entry
                    elif phase in ["COMPLETE", "ABORT"]:
                        incomplete_txs.pop(txid, None)
                except (json.JSONDecodeError, KeyError):
                    continue
        
        if incomplete_txs:
            logging.warning("Found %d incomplete transactions from previous run. Aborting them...", len(incomplete_txs))
            for txid, entry in incomplete_txs.items():
                node_ops = entry.get("node_ops", {})
                logging.info("Recovery: Aborting transaction %s", txid)
                # Abort on all involved nodes (if nodes are down, they'll handle it on restart)
                for node_id in node_ops.keys():
                    self._abort_on_node(node_id, txid)
                # Mark as aborted and complete in log
                self._log_transaction(txid, "ABORT", status="recovered")
                self._log_transaction(txid, "COMPLETE", status="aborted_during_recovery")
        else:
            logging.info("No incomplete transactions found. System is consistent.")

    def _connect(self, host: str, port: int) -> socket.socket:
        s = socket.create_connection(make_address(host, port), timeout=self.timeout)
        return s

    def _prepare_on_node(self, node_id: str, txid: str, operations: List[dict]) -> bool:
        host, port = self.nodes[node_id]
        try:
            # Ask a single participant node whether it is ready to commit.
            with self._connect(host, port) as conn:
                send_json(
                    conn,
                    {
                        "type": "PREPARE",
                        "txid": txid,
                        "operations": operations,
                    },
                )
                reply = recv_json(conn)
                if reply and reply.get("type") == "VOTE_COMMIT":
                    return True
        except Exception as e:
            logging.warning("PREPARE failed on node %s: %s", node_id, e)
        return False

    def _commit_on_node(self, node_id: str, txid: str, operations: List[dict]) -> None:
        host, port = self.nodes[node_id]
        try:
            with self._connect(host, port) as conn:
                send_json(
                    conn,
                    {
                        "type": "COMMIT",
                        "txid": txid,
                        "operations": operations,
                    },
                )
                recv_json(conn)
        except Exception as e:
            logging.warning("COMMIT failed on node %s: %s", node_id, e)

    def _abort_on_node(self, node_id: str, txid: str) -> None:
        host, port = self.nodes[node_id]
        try:
            with self._connect(host, port) as conn:
                send_json(
                    conn,
                    {
                        "type": "ABORT",
                        "txid": txid,
                    },
                )
                recv_json(conn)
        except Exception as e:
            logging.warning("ABORT failed on node %s: %s", node_id, e)

    def transfer(
        self,
        from_node: str,
        from_account: str,
        to_node: str,
        to_account: str,
        amount: int,
    ) -> bool:
        """
        Perform one **distributed money transfer** across nodes.

        High level:
        - Build a sub-transaction (debit, credit) per participant node.
        - Run **Phase 1 (PREPARE)** on each node.
        - If every node votes COMMIT, run **Phase 2 (COMMIT)**.
        - Otherwise, send ABORT to everyone.
        """
        txid = str(uuid.uuid4())
        logging.info(
            "Starting transaction %s: %s/%s -> %s/%s amount=%s",
            txid,
            from_node,
            from_account,
            to_node,
            to_account,
            amount,
        )
        
        # Group operations by node
        node_ops: Dict[str, List[dict]] = {}
        node_ops.setdefault(from_node, []).append(
            {"account_id": from_account, "delta": -amount}
        )
        node_ops.setdefault(to_node, []).append(
            {"account_id": to_account, "delta": amount}
        )
        
        # Log transaction start
        self._log_transaction(txid, "START", node_ops=node_ops)
        
        # Serialize transfers in this demo to simplify reasoning in logs.
        with self.lock:
            votes: Dict[str, bool] = {}
            # Phase 1: PREPARE
            self._log_transaction(txid, "PREPARE", node_ops=node_ops)
            
            for node_id, ops in node_ops.items():
                ok = self._prepare_on_node(node_id, txid, ops)
                votes[node_id] = ok
                logging.info("Node %s vote for %s: %s", node_id, txid, ok)

            if all(votes.values()):
                # Phase 2: COMMIT everywhere
                logging.info("All nodes voted COMMIT for %s. Committing.", txid)
                self._log_transaction(txid, "COMMIT", node_ops=node_ops, status="all_voted_commit")
                for node_id, ops in node_ops.items():
                    self._commit_on_node(node_id, txid, ops)
                logging.info("Transaction %s committed.", txid)
                self._log_transaction(txid, "COMPLETE", status="committed")
                return True
            else:
                logging.info(
                    "At least one node voted ABORT for %s. Aborting on all nodes.", txid
                )
                self._log_transaction(txid, "ABORT", node_ops=node_ops, status="vote_abort")
                for node_id in node_ops:
                    self._abort_on_node(node_id, txid)
                self._log_transaction(txid, "COMPLETE", status="aborted")
                return False


def handle_client(conn: socket.socket, addr: Tuple[str, int], coordinator: Coordinator) -> None:
    try:
        message = recv_json(conn)
        if not message:
            return
        if message.get("type") == "TRANSFER":
            # A client is asking to transfer money between two accounts,
            # possibly stored on different participant nodes.
            ok = coordinator.transfer(
                from_node=message["from_node"],
                from_account=message["from_account"],
                to_node=message["to_node"],
                to_account=message["to_account"],
                amount=int(message["amount"]),
            )
            send_json(
                conn,
                {
                    "type": "TRANSFER_RESULT",
                    "success": ok,
                },
            )
        else:
            send_json(conn, {"type": "ERROR", "error": "Unknown client message"})
    except Exception as e:
        logging.exception("Error handling client %s: %s", addr, e)
    finally:
        conn.close()


def run_server(coordinator: Coordinator, host: str, port: int) -> None:
    # Windows lacks SO_REUSEPORT; try with it when available and fall back.
    reuse_port_requested = hasattr(socket, "SO_REUSEPORT")
    try:
        server = socket.create_server(make_address(host, port), reuse_port=reuse_port_requested)
    except ValueError as exc:
        if "SO_REUSEPORT" in str(exc):
            logging.warning("SO_REUSEPORT not supported; retrying without port reuse.")
            server = socket.create_server(make_address(host, port), reuse_port=False)
        else:
            raise

    with server:
        logging.info("Coordinator listening on %s:%s", host, port)
        while True:
            conn, addr = server.accept()
            t = threading.Thread(
                target=handle_client, args=(conn, addr, coordinator), daemon=True
            )
            t.start()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Coordinator Node - Manages distributed transactions across data nodes N1, N2, N3"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host address to bind to")
    parser.add_argument("--port", type=int, default=5000, help="Port number (default: 5000)")
    parser.add_argument(
        "--nodes",
        default="N1:127.0.0.1:6001,N2:127.0.0.1:6002,N3:127.0.0.1:6003",
        help="Comma-separated list of node_id:host:port entries (N1, N2, N3)",
    )
    parser.add_argument(
        "--data-dir", default="data", help="Directory where coordinator transaction log is stored"
    )
    return parser.parse_args()


def parse_nodes(spec: str) -> Dict[str, Tuple[str, int]]:
    result: Dict[str, Tuple[str, int]] = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        node_id, host, port_str = part.split(":")
        result[node_id] = (host, int(port_str))
    return result


if __name__ == "__main__":
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO, format="[COORD] %(asctime)s %(levelname)s %(message)s"
    )
    nodes = parse_nodes(args.nodes)
    coord = Coordinator(nodes=nodes, data_dir=args.data_dir)
    run_server(coord, args.host, args.port)


