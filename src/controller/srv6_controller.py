#!/usr/bin/env python3
"""
srv6_controller.py  —  SRv6 Controller (Ryu / OpenFlow 1.3)
------------------------------------------------------------
Implements Segment Routing over IPv6 (SRv6) emulation using OpenFlow.

Segment model (emulation strategy)
────────────────────────────────────
Real SRv6 uses a Segment Routing Header (SRH) extension header.
OVS/OpenFlow 1.3 does not support SRH directly.

Emulation approach (standard in OF-based SRv6 research):
  • Each switch is assigned a unique IPv6 Segment ID (SID).
  • A routing state is encoded in the IPv6 dst field.
  • At each hop the controller pre-installs a rule:
      match(ipv6_dst = current_SID)  →  set_field(ipv6_dst = next_SID), output(port)
  • The ingress host encapsulates traffic to the first SID.
  • The egress switch matches the final SID and de-capsulates (sets ipv6_dst
    back to the real host IPv6 address before forwarding).

SID assignment:  fd00::<dpid>  (e.g. s3 with dpid=3 → fd00::3)
Host IPv6:       fd00:1::<host_id>  (h1→fd00:1::1, h4→fd00:1::4)

NOTE on paper disclosure: the SRH is emulated rather than transported;
latency and overhead numbers reflect the OpenFlow control plane rather
than a native SRv6 data plane. This must be declared in the paper.

Metrics collected (written to src/results/data/srv6_metrics.json on exit)
───────────────────────────────────────────────────────────
  • path_setup_latency_ms
  • flow_rules_installed
  • reroute_events
  • reroute_latency_ms

Run
───
  ryu-manager srv6_controller.py --observe-links
"""

import json
import os
import time
import atexit

import networkx as nx

from ryu.base import app_manager
from ryu.controller import ofp_event, dpset
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3, ether, inet
from ryu.lib.packet import packet, ethernet, ipv6, arp
from ryu.topology import event as topo_event
from ryu.topology.api import get_switch, get_link

# ── Constants ─────────────────────────────────────────────────────────────────
SID_PREFIX     = 'fd00::'          # fd00::<dpid>   e.g. fd00::3
HOST_PREFIX    = 'fd00:1::'        # fd00:1::<host#>
FLOW_PRIO_SRv6 = 200
FLOW_PRIO_DEFAULT = 0
ETH_TYPE_IPV6  = ether.ETH_TYPE_IPV6


def _sid(dpid: int) -> str:
    """Return the IPv6 SID for a switch: fd00::<dpid>."""
    return f'{SID_PREFIX}{dpid}'


def _host_ipv6(host_id: int) -> str:
    """Return host IPv6 address: fd00:1::<host_id>."""
    return f'{HOST_PREFIX}{host_id}'


class SRv6Controller(app_manager.RyuApp):
    """Segment Routing over IPv6 (emulated) — Ryu SDN Controller."""

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'dpset': dpset.DPSet}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.dpset    = kwargs['dpset']
        self.net      = nx.DiGraph()
        self.host_loc = {}          # mac → (dpid, port, ipv6_addr)
        self.installed= {}          # (src_mac, dst_mac) → path

        self._metrics = {
            'path_setup_latency_ms': [],
            'flow_rules_installed':  0,
            'reroute_events':        0,
            'reroute_latency_ms':    [],
        }

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

        self.logger.info('[SRv6] Switch connected: dpid=%s  SID=%s',
                         dpid, _sid(dpid))
        self.net.add_node(dpid)

        # Table-miss → controller
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
        self.logger.info('[SRv6] Topology: %d switches, %d links',
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
            self.logger.warning('[SRv6] PortDown dpid=%s port=%s — fast-reroute',
                                dp.id, port)
            t0 = time.time()
            self._fast_reroute(dp.id, port)
            elapsed = (time.time() - t0) * 1000
            self._metrics['reroute_events']    += 1
            self._metrics['reroute_latency_ms'].append(round(elapsed, 3))
            self.logger.info('[SRv6] Reroute complete in %.1f ms', elapsed)

    def _fast_reroute(self, failed_dpid, failed_port):
        to_remove = [(u, v) for u, v, d in self.net.edges(data=True)
                     if u == failed_dpid and d.get('port') == failed_port]
        for u, v in to_remove:
            self.net.remove_edge(u, v)
            if self.net.has_edge(v, u):
                self.net.remove_edge(v, u)

        stale = {k: v for k, v in self.installed.items()
                 if failed_dpid in v}

        for (src_mac, dst_mac), _ in stale.items():
            del self.installed[(src_mac, dst_mac)]

            if dst_mac not in self.host_loc:
                continue
            dst_dpid, dst_port, dst_ipv6 = self.host_loc[dst_mac]
            if src_mac not in self.host_loc:
                continue
            src_dpid, _, _ = self.host_loc[src_mac]

            try:
                new_path = nx.dijkstra_path(self.net, src_dpid, dst_dpid)
            except nx.NetworkXNoPath:
                self.logger.error('[SRv6] No backup path %s → %s',
                                  src_mac, dst_mac)
                continue

            self._install_srv6_path(new_path, dst_port, dst_ipv6,
                                    src_mac, dst_mac)
            self.installed[(src_mac, dst_mac)] = new_path

    # ══════════════════════════════════════════════════════════════════════════
    # 4.  Packet-In Handler
    # ══════════════════════════════════════════════════════════════════════════

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg     = ev.msg
        dp      = msg.datapath
        ofp     = dp.ofproto
        parser  = dp.ofproto_parser
        dpid    = dp.id
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None:
            return

        src_mac, dst_mac = eth.src, eth.dst

        # ARP — extract IPv6 hint from NDP / use neighbour discovery
        if eth.ethertype == ether.ETH_TYPE_ARP:
            self.host_loc.setdefault(src_mac, (dpid, in_port, None))
            self._flood(dp, in_port, msg)
            return

        # Learn host location from IPv6 packet
        ip6 = pkt.get_protocol(ipv6.ipv6)
        if ip6:
            src_ipv6 = ip6.src
            self.host_loc[src_mac] = (dpid, in_port, src_ipv6)
        else:
            self.host_loc.setdefault(src_mac, (dpid, in_port, None))

        if (src_mac, dst_mac) in self.installed:
            return

        if dst_mac not in self.host_loc:
            self._flood(dp, in_port, msg)
            return

        dst_dpid, dst_port, dst_ipv6 = self.host_loc[dst_mac]
        if dst_ipv6 is None:
            self._flood(dp, in_port, msg)
            return

        try:
            path = nx.dijkstra_path(self.net, dpid, dst_dpid)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            self._flood(dp, in_port, msg)
            return

        self.logger.info('[SRv6] Path %s→%s : %s', src_mac, dst_mac, path)

        t0 = time.time()
        self._install_srv6_path(path, dst_port, dst_ipv6, src_mac, dst_mac)
        self._metrics['path_setup_latency_ms'].append(
            round((time.time() - t0) * 1000, 3))

        self.installed[(src_mac, dst_mac)] = path

        # Re-send buffered packet
        out_port = (self.net[path[0]][path[1]]['port']
                    if len(path) > 1 else dst_port)
        out = parser.OFPPacketOut(
            datapath=dp,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=[parser.OFPActionOutput(out_port)],
            data=msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None,
        )
        dp.send_msg(out)

    # ══════════════════════════════════════════════════════════════════════════
    # 5.  SRv6 Path Installation
    # ══════════════════════════════════════════════════════════════════════════

    def _install_srv6_path(self, path, dst_port, dst_ipv6,
                           src_mac, dst_mac):
        """
        Install per-hop IPv6-dst-rewrite rules that emulate SRv6 forwarding.

        Segment list  =  [SID(path[0]), SID(path[1]), ..., SID(path[-1])]
        At each hop i:  match(ipv6_dst == SID[i]) → set(ipv6_dst = SID[i+1]), fwd
        At final hop:   match(ipv6_dst == SID[-1]) → set(ipv6_dst = dst_ipv6), fwd to host
        """
        n    = len(path)
        sids = [_sid(sw) for sw in path]

        for i, sw in enumerate(path):
            dp = self._get_dp(sw)
            if dp is None:
                continue
            parser = dp.ofproto_parser

            if i == 0 and n == 1:
                # Single-switch: direct forward
                match  = parser.OFPMatch(eth_src=src_mac, eth_dst=dst_mac)
                self._add_flow(dp, FLOW_PRIO_SRv6, match,
                               [parser.OFPActionOutput(dst_port)])
                continue

            current_sid = sids[i]
            out_port    = (self.net[sw][path[i + 1]]['port']
                           if i < n - 1 else dst_port)

            if i == 0:
                # ── Ingress: match Ethernet src/dst, rewrite ipv6_dst → SID[1] ─
                match = parser.OFPMatch(
                    eth_type=ETH_TYPE_IPV6,
                    eth_src=src_mac,
                    eth_dst=dst_mac,
                )
                actions = [
                    parser.OFPActionSetField(ipv6_dst=sids[1]),
                    parser.OFPActionOutput(out_port),
                ]
                self._add_flow(dp, FLOW_PRIO_SRv6, match, actions)

            elif i < n - 1:
                # ── Transit: match current SID, rewrite → next SID ────────────
                match = parser.OFPMatch(
                    eth_type=ETH_TYPE_IPV6,
                    ipv6_dst=current_sid,
                )
                actions = [
                    parser.OFPActionSetField(ipv6_dst=sids[i + 1]),
                    parser.OFPActionOutput(out_port),
                ]
                self._add_flow(dp, FLOW_PRIO_SRv6, match, actions)

            else:
                # ── Egress: match final SID, restore real dst IPv6, fwd to host ─
                match = parser.OFPMatch(
                    eth_type=ETH_TYPE_IPV6,
                    ipv6_dst=current_sid,
                )
                actions = [
                    parser.OFPActionSetField(ipv6_dst=dst_ipv6),
                    parser.OFPActionOutput(dst_port),
                ]
                self._add_flow(dp, FLOW_PRIO_SRv6, match, actions)

    # ══════════════════════════════════════════════════════════════════════════
    # 6.  Helpers
    # ══════════════════════════════════════════════════════════════════════════

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
        path = os.path.join(_dir, 'srv6_metrics.json')
        lats = self._metrics['path_setup_latency_ms']
        rts  = self._metrics['reroute_latency_ms']
        out  = {
            'mode':                  'srv6',
            'flow_rules_installed':  self._metrics['flow_rules_installed'],
            'reroute_events':        self._metrics['reroute_events'],
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
        self.logger.info('[SRv6] Metrics saved → %s', path)
