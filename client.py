"""
Client - Initiates Transactions

This file implements a **Client** as described in the architecture:
- Multiple instances of this script can run concurrently
- Each client initiates transactions (bank transfers) by sending requests to the coordinator
- No labels needed - clients are identified by their connection, not by IDs
- Example usage:
  python client.py --coord-host 127.0.0.1 --coord-port 5000 --from-node N1 --from-account A --to-node N2 --to-account B --amount 10
"""

import argparse
import logging
import socket

from common import send_json, recv_json, make_address


def run_client(
    coordinator_host: str,
    coordinator_port: int,
    from_node: str,
    from_account: str,
    to_node: str,
    to_account: str,
    amount: int,
) -> None:
    """
    Simple **Client** as described in your architecture slide.

    Responsibilities:
    - Initiate a transaction (money transfer) by sending a TRANSFER request
      to the coordinator node.
    - Wait for the final COMMIT/ABORT decision from the coordinator.
    """
    logging.basicConfig(
        level=logging.INFO, format="[CLIENT] %(asctime)s %(levelname)s %(message)s"
    )
    msg = {
        "type": "TRANSFER",
        "from_node": from_node,
        "from_account": from_account,
        "to_node": to_node,
        "to_account": to_account,
        "amount": amount,
    }
    # Open a TCP connection to the coordinator node.
    with socket.create_connection(
        make_address(coordinator_host, coordinator_port), timeout=5.0
    ) as conn:
        # Send the TRANSFER request and block for the final result.
        send_json(conn, msg)
        reply = recv_json(conn)
        logging.info("Result from coordinator: %s", reply)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Client - Initiates distributed transactions (no labels needed, run multiple instances)"
    )
    parser.add_argument("--coord-host", default="127.0.0.1", help="Coordinator host address")
    parser.add_argument("--coord-port", type=int, default=5000, help="Coordinator port (default: 5000)")
    parser.add_argument("--from-node", required=True, help="Source node label: N1, N2, or N3")
    parser.add_argument("--from-account", required=True, help="Source account ID")
    parser.add_argument("--to-node", required=True, help="Destination node label: N1, N2, or N3")
    parser.add_argument("--to-account", required=True, help="Destination account ID")
    parser.add_argument("--amount", type=int, required=True, help="Transfer amount")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_client(
        coordinator_host=args.coord_host,
        coordinator_port=args.coord_port,
        from_node=args.from_node,
        from_account=args.from_account,
        to_node=args.to_node,
        to_account=args.to_account,
        amount=args.amount,
    )


