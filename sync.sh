#!/bin/bash
# Discards locally-generated files and pulls the CI versions.
# Use this before pulling when you've run update.py locally.

GENERATED_FILES=(
    "data/processed.csv"
    "data/history.csv"
    "data/untracked_models.json"
    "alerts.txt"
    "metadata.json"
)

echo "Restoring CI-generated files..."
git checkout -- "${GENERATED_FILES[@]}" 2>/dev/null
echo "Pulling latest..."
git pull
echo "Done."
