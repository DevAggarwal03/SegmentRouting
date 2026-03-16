from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller import dpset
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls

from ryu.ofproto import ofproto_v1_3

from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import arp
from ryu.lib.packet import ipv4

from ryu.topology import event
from ryu.topology.api import get_switch, get_link

import networkx as nx


class LoadBalancer(app_manager.RyuApp):

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    _CONTEXTS = {
        'dpset': dpset.DPSet
    }

    def __init__(self, *args, **kwargs):
        super(LoadBalancer, self).__init__(*args, **kwargs)

        self.dpset = kwargs['dpset']

        self.mac_to_port = {}
        self.host_location = {}

        self.net = nx.DiGraph()

    # ------------------------------
    # Switch Connection
    # ------------------------------

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):

        datapath = ev.msg.datapath
        dpid = datapath.id

        self.logger.info(f"Switch connected: {dpid}")

        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER)]

        self.add_flow(datapath, 0, match, actions)

        self.net.add_node(dpid)

    # ------------------------------
    # Topology Discovery
    # ------------------------------

    @set_ev_cls(event.EventSwitchEnter)
    def get_topology_data(self, ev):

        switch_list = get_switch(self, None)
        switches = [switch.dp.id for switch in switch_list]

        self.net.add_nodes_from(switches)

        links_list = get_link(self, None)

        for link in links_list:
            src = link.src.dpid
            dst = link.dst.dpid

            self.net.add_edge(src, dst, port=link.src.port_no)
            self.net.add_edge(dst, src, port=link.dst.port_no)

        self.logger.info("Topology discovered")

    # ------------------------------
    # Packet Handling
    # ------------------------------

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):

        msg = ev.msg
        datapath = msg.datapath
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        dpid = datapath.id
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)

        if eth is None:
            return

        src = eth.src
        dst = eth.dst

        self.logger.info(f"Packet received {src} -> {dst}")

        # learn host location
        self.host_location[src] = (dpid, in_port)

        if dst in self.host_location:

            dst_switch, dst_port = self.host_location[dst]

            path = nx.shortest_path(self.net, dpid, dst_switch)

            self.logger.info(f"Computed path: {path}")

            self.install_path(path, dst_port, dst, src)

        else:

            actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]

            out = parser.OFPPacketOut(
                datapath=datapath,
                buffer_id=msg.buffer_id,
                in_port=in_port,
                actions=actions,
                data=msg.data
            )

            datapath.send_msg(out)

    @set_ev_cls(event.EventLinkAdd)
    def link_add_handler(self, ev):
        self.build_topology()

    # ------------------------------
    # Install Flow Rules
    # ------------------------------

    def install_path(self, path, dst_port, dst, src):

        for i in range(len(path) - 1):

            sw = path[i]
            next_sw = path[i + 1]

            datapath = self.get_datapath(sw)

            if datapath is None:
                continue

            parser = datapath.ofproto_parser
            ofproto = datapath.ofproto

            out_port = self.net[sw][next_sw]['port']

            actions = [parser.OFPActionOutput(out_port)]

            match = parser.OFPMatch(
                eth_src=src,
                eth_dst=dst
            )

            self.add_flow(datapath, 1, match, actions)

        dst_switch = path[-1]

        datapath = self.get_datapath(dst_switch)

        if datapath is None:
            return

        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        actions = [parser.OFPActionOutput(dst_port)]

        match = parser.OFPMatch(
            eth_src=src,
            eth_dst=dst
        )

        self.add_flow(datapath, 1, match, actions)

    # ------------------------------
    # Add Flow
    # ------------------------------

    def add_flow(self, datapath, priority, match, actions):

        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [
            parser.OFPInstructionActions(
                ofproto.OFPIT_APPLY_ACTIONS,
                actions
            )
        ]

        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=inst
        )

        datapath.send_msg(mod)

    # ------------------------------
    # Datapath Lookup
    # ------------------------------

    def get_datapath(self, dpid):
        return self.dpset.get(dpid)

    # ------------------------------
    # Topology Rebuild
    # ------------------------------

    def build_topology(self):

        switch_list = get_switch(self, None)
        switches = [switch.dp.id for switch in switch_list]

        self.net.clear()
        self.net.add_nodes_from(switches)

        links_list = get_link(self, None)

        for link in links_list:
            src = link.src.dpid
            dst = link.dst.dpid

            self.net.add_edge(src, dst, port=link.src.port_no)
            self.net.add_edge(dst, src, port=link.dst.port_no)

        self.logger.info("Topology rebuilt")