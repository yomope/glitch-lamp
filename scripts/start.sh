#!/bin/bash
echo "Starting Glitch Video Player..."
cd /home/yomope/glitch-lamp
source venv/bin/activate
uvicorn backend.main:app --reload --host 0.0.0.0 --port 18000
