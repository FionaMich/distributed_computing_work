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
    parser = argparse.ArgumentParser(description="Simple transaction client")
    parser.add_argument("--coord-host", default="127.0.0.1")
    parser.add_argument("--coord-port", type=int, default=5000)
    parser.add_argument("--from-node", required=True)
    parser.add_argument("--from-account", required=True)
    parser.add_argument("--to-node", required=True)
    parser.add_argument("--to-account", required=True)
    parser.add_argument("--amount", type=int, required=True)
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


