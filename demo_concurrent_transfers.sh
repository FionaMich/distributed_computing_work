#!/bin/bash
# Demo script to run concurrent transfers between N1, N2, and N3
# This demonstrates concurrency: multiple transfers running simultaneously

echo "Starting concurrent transfers involving N1, N2, and N3:"
echo "  N1->N2: Alice sends money to Bob"
echo "  N2->N1: Bob sends money to Alice"
echo "  N3->N1: Charlie sends money to Alice"

# Start N1 to N2 transfer (Alice sends money to Bob) in background
python client.py --coord-host 127.0.0.1 --coord-port 5000 --from-node N1 --from-account A --to-node N2 --to-account B --amount 10 &

# Start N2 to N1 transfer (Bob sends money to Alice) in background
python client.py --coord-host 127.0.0.1 --coord-port 5000 --from-node N2 --from-account B --to-node N1 --to-account A --amount 10 &

# Start N3 to N1 transfer (Charlie sends money to Alice) in background
python client.py --coord-host 127.0.0.1 --coord-port 5000 --from-node N3 --from-account C --to-node N1 --to-account A --amount 20 &

# Wait for all background processes to complete
wait

echo ""
echo "All three transfers completed. Check coordinator and node logs to see concurrent processing."
