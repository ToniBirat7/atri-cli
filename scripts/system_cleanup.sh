#!/bin/bash
echo "Cleaning up Atri Code system artifacts..."
rm -f ~/.local/bin/atri-cli
rm -f ~/.local/bin/atri-code
# Kill any remaining processes
pkill -f "llama-server"
pkill -f "uvicorn api:app"
echo "System artifacts removed."
