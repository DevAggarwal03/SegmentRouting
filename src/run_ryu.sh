#!/bin/bash
# run_ryu.sh — Start a Ryu SDN controller
# Usage: bash run_ryu.sh [sr-mpls|srv6|mac]
# Default: sr-mpls

MODE=${1:-sr-mpls}

case "$MODE" in
  sr-mpls)
    SCRIPT="controller/sr_controller.py"
    ;;
  srv6)
    SCRIPT="controller/srv6_controller.py"
    ;;
  mac)
    SCRIPT="controller/mac_controller.py"
    ;;
  *)
    echo "Unknown mode: $MODE. Choose sr-mpls | srv6 | mac"
    exit 1
    ;;
esac

echo "[ryu] Starting controller in mode: $MODE"
echo "[ryu] Script: $SCRIPT"

ryu-manager --observe-links --wsapi-host 127.0.0.1 "$SCRIPT" ryu.app.ofctl_rest
