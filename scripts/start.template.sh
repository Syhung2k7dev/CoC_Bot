#!/bin/bash

PYTHON_ABS_PATH="" # Absolute path to python executable in CoC_Bot virtual environment
MAIN_ABS_PATH="" # Absolute path to CoC_Bot main.py

read -r -p "Enter instance ID: " INSTANCE_ID

if [[ ! "$INSTANCE_ID" =~ ^[A-Za-z0-9_-]{1,64}$ ]]; then
    echo "Invalid instance ID. Use 1-64 letters, numbers, underscores or hyphens."
    exit 1
fi

if [[ -z "$PYTHON_ABS_PATH" || -z "$MAIN_ABS_PATH" ]]; then
    echo "Set PYTHON_ABS_PATH and MAIN_ABS_PATH before running this script."
    exit 1
fi

BASE_NAME="CoC_Bot"
SESSION_NAME="${BASE_NAME}_${INSTANCE_ID}"

if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "$SESSION_NAME session already exists. Attaching..."
    tmux attach -t "$SESSION_NAME"
else
    echo "Starting new tmux session: $SESSION_NAME"
    BOT_COMMAND=$(printf '%q %q --id %q' "$PYTHON_ABS_PATH" "$MAIN_ABS_PATH" "$INSTANCE_ID")
    tmux new-session -d -s "$SESSION_NAME" "$BOT_COMMAND"
    echo "$SESSION_NAME session started and detached."
fi
