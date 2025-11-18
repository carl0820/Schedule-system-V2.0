#!/bin/bash
# Stop Service Script for Mac/Linux
# Used to stop the robot scheduling system service

echo "Stopping robot scheduling service..."

# Find and kill processes using port 8000
PIDS=$(lsof -ti:8000 2>/dev/null)

if [ -z "$PIDS" ]; then
    echo "[INFO] No service running on port 8000"
    exit 0
fi

echo "Found process(es): $PIDS"

# Kill processes
for PID in $PIDS; do
    echo "Stopping process $PID..."
    kill $PID 2>/dev/null
done

# Wait a bit
sleep 2

# Force kill if still running
REMAINING=$(lsof -ti:8000 2>/dev/null)
if [ ! -z "$REMAINING" ]; then
    echo "Force stopping remaining processes..."
    for PID in $REMAINING; do
        kill -9 $PID 2>/dev/null
    done
    sleep 1
fi

# Verify
if lsof -ti:8000 >/dev/null 2>&1; then
    echo "[WARN] Some processes may still be running"
else
    echo "[OK] Service stopped successfully"
fi

