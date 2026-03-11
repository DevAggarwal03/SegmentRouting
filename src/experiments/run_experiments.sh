#!/bin/bash

echo "Running baseline experiment"

python3 traffic/generate_traffic.py

sleep 20

echo "Running load balancing experiment"

python3 traffic/elephant_mice_flows.py
