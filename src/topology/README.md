Topology Module

This directory contains scripts that define the network topology used
for the SDN experiments.

The topology represents a simplified data center network
based on a fat-tree architecture.

Files

fat_tree_topology.py

Creates the Mininet topology consisting of:

- Core switches
- Aggregation switches
- Edge switches
- Hosts connected to edge switches

Each switch is connected to the SDN controller (Ryu) using OpenFlow.
