#!/bin/bash
echo "Starting Glitch Video Player..."
source venv/bin/activate
uvicorn backend.main:app --reload --host 0.0.0.0 --port 18000
