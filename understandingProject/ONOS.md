**unable to dowload(so not used)**

**What is ONOS**
- Open network operating system (ONOS)
- It's a **Centralized** SDN controller for large **Carrier-grade** networks

**what do you mean by Centralized?**
- Traditionally
    - each switch/routers deciedes where the packet would hop next
    - this arises problems because it becomes hard to change paths
    - And makes the whole procedure inflexible
- SDN with ONOS
    - It consists of one Centralized SDN controller
    - has a Global view of the Topology
    - Path taken by the packets are programmable hence making the network flexible.

**Why ONOS for the project**
- Has built in support for Segment Routing (SR-MPLS and SRv6)
- failure recovery
- path computation
- has built in features for metric and stats analysis

**mental model**
- MININET: cables, switches, hosts etc
- ONOS: Brain that decides how traffic should flow
- Segment routing: The rules that determine how the traffic will flow (taken care of by ONOS)

**ONOS installation**
- cd ~
wget https://repo1.maven.org/maven2/org/onosproject/onos-releases/2.7.0/onos-2.7.0.tar.gz tar -xvzf onos-2.7.0.tar.gz


**ONOS: programs the network to do SRouting**
