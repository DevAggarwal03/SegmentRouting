#!/bin/bash

echo "Starting Ryu Controller..."

ryu-manager controller/load_balancer_controller.py
