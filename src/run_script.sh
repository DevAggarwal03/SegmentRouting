#!/bin/bash

echo "Starting Ryu Controller..."
gnome-terminal -- ryu-manager controller/load_balancer_controller.py

sleep 5

echo "Starting Mininet Topology..."
sudo python3 topology/fat_tree_topology.py
