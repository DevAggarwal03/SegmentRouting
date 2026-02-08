# Segment Routing Performance Evaluation in Programmable SDN Networks

## 1. Overview

This project implements and evaluates **Segment Routing (SR)** in a **Software Defined Networking (SDN)** environment using **Mininet** and an SDN controller. The objective is to experimentally analyze the performance of **SR-MPLS** and/or **SRv6** under realistic traffic conditions, including network congestion and link failures.

By building a fully programmable network testbed, this project studies how different segment routing mechanisms behave in terms of latency, convergence time, packet loss, and control-plane overhead.

This work is motivated by the lack of **undergraduate-level, reproducible experimental studies** comparing SR variants in programmable networks.

---

## 2. Objectives

The main goals of this project are:

- To build an SDN-based network testbed using Mininet
- To deploy a centralized SDN controller capable of programming segment routing paths
- To implement Segment Routing using:
  - SR-MPLS (via FRRouting), and/or
  - SRv6 (via IPv6-based segment routing)
- To generate realistic traffic workloads (VoIP, streaming, bulk data)
- To simulate network failures and congestion scenarios
- To measure and analyze performance metrics
- To compare SR-MPLS and SRv6 under identical conditions

---

## 3. System Architecture

The system consists of the following components:

- **Mininet**  
  Used to emulate the network topology, hosts, links, and switches.

- **SDN Controller (ONOS)**  
  Responsible for topology discovery, path computation, and programming segment routing policies.

- **FRRouting (FRR)**  
  Runs on Mininet switches/routers to enable SR-MPLS and routing protocols.

- **Traffic Generators**  
  Used to generate synthetic and realistic traffic patterns:
  - Bulk traffic (iperf)
  - Latency-sensitive traffic (VoIP-like flows)

- **Monitoring & Measurement Tools**
  - ping, traceroute
  - iperf
  - controller logs and statistics

---

## 4. Experimental Setup

### 4.1 Network Topology
- Custom Mininet topology (linear / mesh / multi-path)
- Multiple hosts connected via programmable switches
- Controller connected remotely to Mininet

### 4.2 Traffic Scenarios
- Single-flow vs multi-flow traffic
- Mixed traffic:
  - VoIP (low-latency)
  - Streaming
  - Bulk file transfer

### 4.3 Failure & Congestion Scenarios
- Manual link failures
- Congested links using traffic control (tc)
- Controller-driven rerouting
