Controller Module

This directory contains the SDN controller implementation.

The controller is written using the Ryu framework and implements
dynamic load balancing.

Responsibilities

- Install initial OpenFlow rules
- Monitor flow statistics
- Detect congestion
- Select alternate paths
- Reroute traffic dynamically

File

load_balancer_controller.py

Main controller that communicates with switches and controls routing.
