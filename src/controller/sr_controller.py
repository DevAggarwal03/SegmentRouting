#!/usr/bin/env python3
"""
sr_controller.py  —  SR-MPLS Controller (Ryu / OpenFlow 1.3)
-------------------------------------------------------------
Implements Segment Routing over MPLS using explicit per-hop label
push / swap / pop rules installed via OpenFlow 1.3.

Segment model
─────────────
  • Every switch gets a unique MPLS label (its DPID, offset by LABEL_BASE).
  • For a path [s1, s2, s3] the segment list is [label(s2), label(s3)].
  • Ingress switch pushes the full label stack (outermost = next hop).
  • Each transit switch swaps the top label for the next one (or pops on
    the penultimate hop so the egress switch sees plain Ethernet/IP).
  • Egress switch forwards to the destination host.

Fast-reroute
────────────
  On a PortStatus DOWN event the controller:
    1. Removes the affected link from the graph.
    2. Recomputes all paths that traversed that link.
    3. Reinstalls flow rules along the new paths (or logs "no backup").

Metrics collected (written to src/results/data/sr_mpls_metrics.json on exit)
────────────────────────────────────────────────────────────────
  • path_setup_latency_ms  : time from first PacketIn to FlowMod sent
  • flow_rules_installed   : total OFPFlowMod messages sent
  • reroute_events         : number of fast-reroute triggers
  • reroute_latency_ms     : time from PortDown to last FlowMod of rereroute

Run
───
  ryu-manager sr_controller.py --observe-links
"""

import json
import os
import time
import atexit
from collections import defaultdict

import networkx as nx

from ryu.base import app_manager
from ryu.controller import ofp_event, dpset
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3, ether
from ryu.lib.packet import packet, ethernet, ipv4, arp
from ryu.topology import event as topo_event
from ryu.topology.api import get_switch, get_link

# ── Constants ─────────────────────────────────────────────────────────────────
LABEL_BASE   = 100          # MPLS labels start at 100 (avoids special-purpose range)
FLOW_PRIO_SR = 200          # SR forwarding rules
FLOW_PRIO_ARP= 100          # ARP flood rules
FLOW_PRIO_DEFAULT = 0       # Table-miss → controller


class SRMPLSController(app_manager.RyuApp):
    """Segment Routing over MPLS — Ryu SDN Controller."""

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    _CONTEXTS = {'dpset': dpset.DPSet}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.dpset       = kwargs['dpset']
        self.net         = nx.DiGraph()          # switch topology graph
        self.host_loc    = {}                    # mac → (dpid, port)
        self.installed   = {}                    # (src_mac, dst_mac) → path

        # ── metrics ────────────────────────────────────────────────────────
        self._metrics = {
            'path_setup_latency_ms': [],
            'flow_rules_installed':  0,
            'reroute_events':        0,
            'reroute_latency_ms':    [],
        }
        self._pkt_in_ts = {}    # (src_mac, dst_mac) → timestamp of first PacketIn

        atexit.register(self._dump_metrics)

    # ══════════════════════════════════════════════════════════════════════════
    # 1.  Switch Connect
    # ══════════════════════════════════════════════════════════════════════════

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp     = ev.msg.datapath
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        dpid   = dp.id

        self.logger.info('[SR-MPLS] Switch connected: dpid=%s  label=%d',
                         dpid, self._label(dpid))

        self.net.add_node(dpid)

        # Table-miss: send to controller
        self._add_flow(dp, FLOW_PRIO_DEFAULT,
                       parser.OFPMatch(),
                       [parser.OFPActionOutput(ofp.OFPP_CONTROLLER,
                                               ofp.OFPCML_NO_BUFFER)])

    # ══════════════════════════════════════════════════════════════════════════
    # 2.  Topology Discovery
    # ══════════════════════════════════════════════════════════════════════════

    @set_ev_cls(topo_event.EventSwitchEnter)
    def _on_switch_enter(self, ev):
        self._rebuild_topology()

    @set_ev_cls(topo_event.EventLinkAdd)
    def _on_link_add(self, ev):
        self._rebuild_topology()

    def _rebuild_topology(self):
        switches = [s.dp.id for s in get_switch(self, None)]
        self.net.add_nodes_from(switches)

        for lnk in get_link(self, None):
            src, dst = lnk.src.dpid, lnk.dst.dpid
            self.net.add_edge(src, dst, port=lnk.src.port_no)
            self.net.add_edge(dst, src, port=lnk.dst.port_no)

        self.logger.info('[SR-MPLS] Topology: %d switches, %d directed links',
                         self.net.number_of_nodes(), self.net.number_of_edges())

    # ══════════════════════════════════════════════════════════════════════════
    # 3.  Port Status — Fast Reroute
    # ══════════════════════════════════════════════════════════════════════════

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def _port_status(self, ev):
        msg    = ev.msg
        dp     = msg.datapath
        ofp    = dp.ofproto
        reason = msg.reason
        port   = msg.desc.port_no

        if reason != ofp.OFPPR_DELETE and msg.desc.state & ofp.OFPPS_LINK_DOWN:
            self.logger.warning('[SR-MPLS] PortDown dpid=%s port=%s — fast-reroute',
                                dp.id, port)
            t0 = time.time()
            self._fast_reroute(dp.id, port)
            elapsed = (time.time() - t0) * 1000
            self._metrics['reroute_events']    += 1
            self._metrics['reroute_latency_ms'].append(round(elapsed, 3))
            self.logger.info('[SR-MPLS] Reroute complete in %.1f ms', elapsed)

    def _fast_reroute(self, failed_dpid, failed_port):
        """Remove the failed link from the graph and reinstall affected paths."""
        # Identify and remove the failed edge
        to_remove = [(u, v) for u, v, d in self.net.edges(data=True)
                     if u == failed_dpid and d.get('port') == failed_port]
        for u, v in to_remove:
            self.net.remove_edge(u, v)
            # Remove reverse too (undirected failure)
            if self.net.has_edge(v, u):
                self.net.remove_edge(v, u)

        # Reinstall every path that went through the failed link
        stale = {k: v for k, v in self.installed.items()
                 if self._path_uses_link(v, failed_dpid, failed_port)}

        for (src_mac, dst_mac), old_path in stale.items():
            del self.installed[(src_mac, dst_mac)]

            if dst_mac not in self.host_loc:
                continue
            dst_dpid, dst_port = self.host_loc[dst_mac]
            src_dpid, _        = self.host_loc.get(src_mac, (None, None))
            if src_dpid is None:
                continue

            try:
                new_path = nx.dijkstra_path(self.net, src_dpid, dst_dpid)
            except nx.NetworkXNoPath:
                self.logger.error('[SR-MPLS] No backup path %s → %s',
                                  src_mac, dst_mac)
                continue

            self._install_sr_path(new_path, dst_port, src_mac, dst_mac)
            self.installed[(src_mac, dst_mac)] = new_path
            self.logger.info('[SR-MPLS] Rerouted %s→%s via %s',
                             src_mac, dst_mac, new_path)

    @staticmethod
    def _path_uses_link(path, dpid, port):
        for i in range(len(path) - 1):
            if path[i] == dpid:
                return True
        return False

    # ══════════════════════════════════════════════════════════════════════════
    # 4.  Packet-In Handler
    # ══════════════════════════════════════════════════════════════════════════

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg    = ev.msg
        dp     = msg.datapath
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        dpid   = dp.id
        in_port= msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None:
            self.logger.debug('[SR-MPLS] No Ethernet protocol in PacketIn from %s', dp.id)
            return

        src, dst = eth.src, eth.dst

        # Learn host location
        self.host_loc[src] = (dpid, in_port)

        # Handle ARP with flood
        if eth.ethertype == ether.ETH_TYPE_ARP:
            self._flood(dp, in_port, msg)
            return

        # Already installed — shouldn't get here but guard anyway
        if (src, dst) in self.installed:
            return

        # Record first PacketIn timestamp for latency metric
        self._pkt_in_ts[(src, dst)] = time.time()

        if dst not in self.host_loc:
            self._flood(dp, in_port, msg)
            return

        dst_dpid, dst_port = self.host_loc[dst]

        try:
            path = nx.dijkstra_path(self.net, dpid, dst_dpid)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            self._flood(dp, in_port, msg)
            return

        self.logger.info('[SR-MPLS] Path %s→%s : %s', src, dst, path)

        t_before = time.time()
        self._install_sr_path(path, dst_port, src, dst)
        latency_ms = (time.time() - t_before) * 1000
        self._metrics['path_setup_latency_ms'].append(round(latency_ms, 3))

        self.installed[(src, dst)] = path

        # Send the buffered packet out
        out = parser.OFPPacketOut(
            datapath=dp,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=[parser.OFPActionOutput(
                self.net[path[0]][path[1]]['port'] if len(path) > 1 else dst_port
            )],
            data=msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None,
        )
        dp.send_msg(out)

    # ══════════════════════════════════════════════════════════════════════════
    # 5.  SR-MPLS Path Installation
    # ══════════════════════════════════════════════════════════════════════════

    def _install_sr_path(self, path, dst_port, src_mac, dst_mac):
        """
        Install MPLS push/swap/pop rules along `path`.

        Segment list = labels of intermediate + egress switches.
        Stack (outermost first):  label[1], label[2], ..., label[-1]

        We use penultimate-hop popping (PHP): the second-to-last switch
        pops the MPLS header so the egress switch forwards plain Ethernet.
        """
        if len(path) == 1:
            # Src and dst on the same switch
            dp = self._get_dp(path[0])
            if dp:
                parser = dp.ofproto_parser
                match  = parser.OFPMatch(eth_src=src_mac, eth_dst=dst_mac)
                self._add_flow(dp, FLOW_PRIO_SR, match,
                               [parser.OFPActionOutput(dst_port)])
            return

        segment_labels = [self._label(sw) for sw in path[1:]]
        n = len(path)

        for i, sw in enumerate(path):
            dp = self._get_dp(sw)
            if dp is None:
                continue
            parser = dp.ofproto_parser

            if i == 0:
                # ── Ingress: push full label stack ────────────────────────────
                actions = []
                # Push labels in reverse order (innermost pushed first)
                for lbl in reversed(segment_labels):
                    actions += [
                        parser.OFPActionPushMpls(ether.ETH_TYPE_MPLS),
                        parser.OFPActionSetField(mpls_label=lbl),
                    ]
                out_port = self.net[sw][path[i + 1]]['port']
                actions.append(parser.OFPActionOutput(out_port))

                match = parser.OFPMatch(eth_src=src_mac, eth_dst=dst_mac)
                self._add_flow(dp, FLOW_PRIO_SR, match, actions)

            elif i == n - 2:
                # ── Penultimate hop: pop label (PHP) ──────────────────────────
                out_port = self.net[sw][path[i + 1]]['port']
                match = parser.OFPMatch(
                    eth_type=ether.ETH_TYPE_MPLS,
                    mpls_label=segment_labels[i],
                )
                actions = [
                    parser.OFPActionPopMpls(ether.ETH_TYPE_IP),
                    parser.OFPActionOutput(out_port),
                ]
                self._add_flow(dp, FLOW_PRIO_SR, match, actions)

            elif i == n - 1:
                # ── Egress: plain Ethernet forward to host ────────────────────
                match = parser.OFPMatch(eth_dst=dst_mac)
                self._add_flow(dp, FLOW_PRIO_SR, match,
                               [parser.OFPActionOutput(dst_port)])

            else:
                # ── Transit: swap label ───────────────────────────────────────
                current_label = segment_labels[i]
                next_label    = segment_labels[i + 1]
                out_port      = self.net[sw][path[i + 1]]['port']

                match = parser.OFPMatch(
                    eth_type=ether.ETH_TYPE_MPLS,
                    mpls_label=current_label,
                )
                actions = [
                    parser.OFPActionSetField(mpls_label=next_label),
                    parser.OFPActionOutput(out_port),
                ]
                self._add_flow(dp, FLOW_PRIO_SR, match, actions)

    # ══════════════════════════════════════════════════════════════════════════
    # 6.  Helpers
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _label(dpid):
        return LABEL_BASE + dpid

    def _get_dp(self, dpid):
        return self.dpset.get(dpid)

    def _add_flow(self, dp, priority, match, actions):
        parser = dp.ofproto_parser
        ofp    = dp.ofproto
        inst   = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        mod    = parser.OFPFlowMod(
            datapath=dp,
            priority=priority,
            match=match,
            instructions=inst,
            idle_timeout=0,
            hard_timeout=0,
        )
        dp.send_msg(mod)
        self._metrics['flow_rules_installed'] += 1

    def _flood(self, dp, in_port, msg):
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        out = parser.OFPPacketOut(
            datapath=dp,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=[parser.OFPActionOutput(ofp.OFPP_FLOOD)],
            data=msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None,
        )
        dp.send_msg(out)

    def _dump_metrics(self):
        _dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'results', 'data')
        os.makedirs(_dir, exist_ok=True)
        path = os.path.join(_dir, 'sr_mpls_metrics.json')
        lats = self._metrics['path_setup_latency_ms']
        rts  = self._metrics['reroute_latency_ms']
        out  = {
            'mode':                   'sr-mpls',
            'flow_rules_installed':   self._metrics['flow_rules_installed'],
            'reroute_events':         self._metrics['reroute_events'],
            'path_setup_latency_ms': {
                'samples': lats,
                'avg':     round(sum(lats) / len(lats), 3) if lats else 0,
                'max':     max(lats) if lats else 0,
            },
            'reroute_latency_ms': {
                'samples': rts,
                'avg':     round(sum(rts) / len(rts), 3) if rts else 0,
                'max':     max(rts) if rts else 0,
            },
        }
        with open(path, 'w') as f:
            json.dump(out, f, indent=2)
        self.logger.info('[SR-MPLS] Metrics saved → %s', path)
