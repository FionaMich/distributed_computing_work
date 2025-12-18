# Demo script to demonstrate per-account locks serializing conflicting updates
# Both clients involve all three nodes (N1, N2, N3) with conflicting accounts:
# - Client 1: N1/A -> N2/B (uses N1 and N2)
# - Client 2: N2/B -> N3/C (uses N2 and N3, conflicts on N2/B)
# 
# The per-account locks will serialize these transactions, ensuring only one processes at a time
# on account B. The second client will fail immediately if locks are held (non-blocking locks).

Write-Host "Starting conflicting concurrent transfers involving N1, N2, and N3:" -ForegroundColor Green
Write-Host "  Client 1: N1/A -> N2/B (amount 100) - Alice sends to Bob" -ForegroundColor Yellow
Write-Host "  Client 2: N2/B -> N3/C (amount 150) - Bob sends to Charlie (conflicts on N2/B!)" -ForegroundColor Yellow
Write-Host ""
Write-Host "Per-account locks will serialize these transactions on account B." -ForegroundColor Cyan
Write-Host "The second transaction will abort immediately if it can't acquire the lock." -ForegroundColor Cyan

# Start Client 1 (Alice sends 100 from N1/A to N2/B)
Start-Process python -ArgumentList "client.py --coord-host 127.0.0.1 --coord-port 5000 --from-node N1 --from-account A --to-node N2 --to-account B --amount 100" -NoNewWindow

# Start Client 2 (Bob sends 150 from N2/B to N3/C - conflicting on account B!)
Start-Process python -ArgumentList "client.py --coord-host 127.0.0.1 --coord-port 5000 --from-node N2 --from-account B --to-node N3 --to-account C --amount 150" -NoNewWindow

Write-Host ""
Write-Host "Both transfers started concurrently. Check coordinator and node logs to see:" -ForegroundColor Yellow
Write-Host "  1. Both transactions initiate simultaneously" -ForegroundColor White
Write-Host "  2. Per-account locks serialize PREPARE phase on account B (N2)" -ForegroundColor White
Write-Host "  3. One transaction acquires the lock and proceeds" -ForegroundColor White
Write-Host "  4. The second transaction fails immediately (aborts) because it can't acquire the lock" -ForegroundColor White
