# Segment Routing Performance Evaluation in Programmable SDN Networks

## 1. Overview

This project implements and evaluates **Segment Routing (SR)** in a **Software Defined Networking (SDN)** environment using **Mininet** and an SDN controller. The objective is to experimentally analyze the performance of **SR-MPLS** and/or **SRv6** under realistic traffic conditions, including network congestion and link failures.

By building a fully programmable network testbed, this project studies how different segment routing mechanisms behave in terms of latency, convergence time, packet loss, and control-plane overhead.

This work is motivated by the lack of **undergraduate-level, reproducible experimental studies** comparing SR variants in programmable networks.

---

## 2. Objectives

The main goals of this project are:

- To build an SDN-based network testbed using Mininet
- To deploy a centralized SDN controller using Ryu
- To implement controller-driven explicit path steering
- To emulate segment-based routing behavior using flow-level forwarding rules
- To generate realistic traffic workloads (VoIP-like, streaming, bulk data)
- To simulate network failures and congestion scenarios
- To measure and analyze performance metrics
- To evaluate path setup and recovery behavior under dynamic conditions

---

## 3. System Architecture

The system consists of the following components:

- **Mininet**  
  Used to emulate the network topology, hosts, links, and Open vSwitch (OVS) switches.

- **SDN Controller (Ryu)**  
  A Python-based SDN controller responsible for:
  - Topology discovery
  - Path computation
  - Installation of OpenFlow rules
  - Failure detection and rerouting

- **Traffic Generators**  
  Used to generate synthetic and realistic traffic patterns:
  - Bulk traffic (iperf)
  - Latency-sensitive traffic (VoIP-like flows)

- **Monitoring & Measurement Tools**
  - ping, traceroute
  - iperf
  - Controller logs and flow statistics

---

## 4. Experimental Setup

### 4.1 Network Topology

- Custom Mininet topology (linear, mesh, or multi-path)
- Multiple hosts connected via programmable Open vSwitch instances
- Ryu controller connected remotely or locally to Mininet

### 4.2 Traffic Scenarios

- Single-flow vs multi-flow traffic
- Mixed traffic workloads:
  - Latency-sensitive flows
  - Bandwidth-intensive flows

### 4.3 Failure & Congestion Scenarios

- Manual link failures in Mininet
- Link congestion using traffic control (tc)
- Controller-triggered rerouting and flow reinstallation

---

## 5. Path Steering Model

Path steering is implemented by the Ryu controller using:

- Explicit path computation at the controller
- Per-hop OpenFlow rule installation
- Predefined forwarding paths acting as logical “segments”

This approach emulates key concepts of Segment Routing, such as:
- Explicit path control
- Source-controlled forwarding decisions
- Fast rerouting upon failures

---

## 6. Performance Metrics

The following metrics are evaluated:

- **Path setup latency**
- **End-to-end delay**
- **Packet loss**
- **Network convergence time after failures**
- **Control-plane overhead**
  - Number of flow rules installed
  - Controller reaction time

