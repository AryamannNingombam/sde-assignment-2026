#!/usr/bin/env bash
# Replace this with your controller. Contract: ./run.sh <SIM_URL> runs until the scenario finishes.
set -euo pipefail
SIM_URL="${1:?usage: ./run.sh <SIM_URL>}"
exec python controller.py "$SIM_URL"
