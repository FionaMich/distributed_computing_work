# Demo script to run concurrent transfers between N1, N2, and N3
# This demonstrates concurrency: multiple transfers running simultaneously

Write-Host "Starting concurrent transfers involving N1, N2, and N3:" -ForegroundColor Green
Write-Host "  N1->N2: Alice sends money to Bob" -ForegroundColor Yellow
Write-Host "  N2->N1: Bob sends money to Alice" -ForegroundColor Yellow
Write-Host "  N3->N1: Charlie sends money to Alice" -ForegroundColor Yellow

# Start N1 to N2 transfer (Alice sends money to Bob)
Start-Process python -ArgumentList "client.py --coord-host 127.0.0.1 --coord-port 5000 --from-node N1 --from-account A --to-node N2 --to-account B --amount 10" -NoNewWindow

# Start N2 to N1 transfer (Bob sends money to Alice)
Start-Process python -ArgumentList "client.py --coord-host 127.0.0.1 --coord-port 5000 --from-node N2 --from-account B --to-node N1 --to-account A --amount 10" -NoNewWindow

# Start N3 to N1 transfer (Charlie sends money to Alice)
Start-Process python -ArgumentList "client.py --coord-host 127.0.0.1 --coord-port 5000 --from-node N3 --from-account C --to-node N1 --to-account A --amount 20" -NoNewWindow

Write-Host ""
Write-Host "All three transfers started concurrently. Check coordinator and node logs to see concurrent processing." -ForegroundColor Yellow
