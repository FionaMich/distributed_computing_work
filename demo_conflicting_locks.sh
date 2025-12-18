#!/bin/bash
# Demo script to demonstrate per-account locks serializing conflicting updates
# Both clients involve all three nodes (N1, N2, N3) with conflicting accounts:
# - Client 1: N1/A -> N2/B (uses N1 and N2)
# - Client 2: N2/B -> N3/C (uses N2 and N3, conflicts on N2/B)
# 
# The per-account locks will serialize these transactions, ensuring only one processes at a time
# on account B. The second client will fail immediately if locks are held (non-blocking locks).

echo "Starting conflicting concurrent transfers involving N1, N2, and N3:"
echo "  Client 1: N1/A -> N2/B (amount 100) - Alice sends to Bob"
echo "  Client 2: N2/B -> N3/C (amount 150) - Bob sends to Charlie (conflicts on N2/B!)"
echo ""
echo "Per-account locks will serialize these transactions on account B."
echo "The second transaction will abort immediately if it can't acquire the lock."

# Start Client 1 (Alice sends 100 from N1/A to N2/B) in background
python client.py --coord-host 127.0.0.1 --coord-port 5000 --from-node N1 --from-account A --to-node N2 --to-account B --amount 100 &

# Start Client 2 (Bob sends 150 from N2/B to N3/C - conflicting on account B!) in background
python client.py --coord-host 127.0.0.1 --coord-port 5000 --from-node N2 --from-account B --to-node N3 --to-account C --amount 150 &

# Wait for both background processes to complete
wait

echo ""
echo "Both transfers completed. Check coordinator and node logs to see:"
echo "  1. Both transactions initiate simultaneously"
echo "  2. Per-account locks serialize PREPARE phase on account B (N2)"
echo "  3. One transaction acquires the lock and proceeds"
echo "  4. The second transaction fails immediately (aborts) because it can't acquire the lock"
