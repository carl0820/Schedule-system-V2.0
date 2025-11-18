#!/bin/bash
# Restart Service Script for Mac/Linux
# Used to restart the robot scheduling system service

echo "Restarting robot scheduling service..."

# Stop service
if [ -f "stop_service.sh" ]; then
    bash stop_service.sh
else
    # Fallback: kill processes on port 8000
    lsof -ti:8000 | xargs kill -9 2>/dev/null
    sleep 2
fi

# Start service
if [ -f "start_service.sh" ]; then
    bash start_service.sh
else
    # Fallback: start directly
    if [ -f "venv/bin/python" ]; then
        venv/bin/python main.py &
    elif [ -f "venv/bin/python3" ]; then
        venv/bin/python3 main.py &
    else
        python3 main.py &
    fi
    echo "Service started!"
    echo "Access: http://localhost:8000/docs"
fi

