#!/bin/bash
# Start Service Script for Mac/Linux
# Used to quickly start the robot scheduling system service

echo "========================================"
echo "  Start Robot Scheduling Service"
echo "========================================"
echo ""

# Check if service is already running
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo "[WARN] Port 8000 is already in use"
    echo "   Service may already be running"
    echo ""
    read -p "Do you want to force stop and restart? (y/N): " response
    if [ "$response" != "y" ] && [ "$response" != "Y" ]; then
        echo "Start cancelled"
        exit 0
    fi
    echo "Stopping existing service..."
    lsof -ti:8000 | xargs kill -9 2>/dev/null
    sleep 2
    echo "[OK] Stopped existing service"
    echo ""
fi

# Check virtual environment
PYTHON_CMD="python3"
if [ -f "venv/bin/python" ]; then
    PYTHON_CMD="venv/bin/python"
    echo "[OK] Using virtual environment: venv/bin/python"
elif [ -f "venv/bin/python3" ]; then
    PYTHON_CMD="venv/bin/python3"
    echo "[OK] Using virtual environment: venv/bin/python3"
else
    # Check if python3 exists
    if ! command -v python3 &> /dev/null; then
        echo "[ERROR] python3 not found"
        echo "   Please install Python 3.8 or higher"
        exit 1
    fi
    echo "[WARN] Virtual environment not found, using system Python"
fi

# Check if main.py exists
if [ ! -f "main.py" ]; then
    echo "[ERROR] main.py file not found"
    echo "   Please make sure you are running this script from the project root directory"
    exit 1
fi

# Start service
echo ""
echo "Starting service..."
echo ""

# Run in foreground
$PYTHON_CMD main.py &
PID=$!

# Wait for service to start
echo "Waiting for service to initialize..."
sleep 3

# Check if service started successfully
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo ""
    echo "========================================"
    echo "  Service started successfully!"
    echo "========================================"
    echo ""
    echo "  Process ID: $PID"
    echo "  Service URL: http://localhost:8000"
    echo "  API Docs: http://localhost:8000/docs"
    echo "  Homepage: http://localhost:8000/"
    echo ""
    
    # Try to check service health
    if curl -s http://localhost:8000/api/health >/dev/null 2>&1; then
        echo "[OK] Service health check: OK"
    else
        echo "[WARN] Service health check: Not responding (may still be starting)"
    fi
else
    echo ""
    echo "[WARN] Service process started but port 8000 is not listening yet"
    echo "   Please wait a moment, or check the log file logs/app.log"
fi

echo ""
echo "Tip: Use stop_service.sh to stop the service"
echo "     Use restart_service.sh to restart the service"
echo "     Press Ctrl+C to stop the service (if running in foreground)"

