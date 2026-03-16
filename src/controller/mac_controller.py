from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller import dpset
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls

from ryu.ofproto import ofproto_v1_3

from ryu.lib.packet import packet
from ryu.lib.packet import ethernet

from ryu.topology import event
from ryu.topology.api import get_switch, get_link

import networkx as nx
import random


class LoadBalancer(app_manager.RyuApp):

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    _CONTEXTS = {
        'dpset': dpset.DPSet
    }

    def __init__(self, *args, **kwargs):
        super(LoadBalancer, self).__init__(*args, **kwargs)

        self.dpset = kwargs['dpset']

        self.host_location = {}
        self.net = nx.DiGraph()

        # NEW: cache installed flows
        self.installed_paths = {}

    # --------------------------------
    # Switch Connection
    # --------------------------------

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):

        datapath = ev.msg.datapath
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        dpid = datapath.id

        self.logger.info(f"Switch connected: {dpid}")

        # send unknown packets to controller
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER)]

        self.add_flow(datapath, 0, match, actions)

        self.net.add_node(dpid)

    # --------------------------------
    # Topology Discovery
    # --------------------------------

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

    # --------------------------------
    # Packet Handling
    # --------------------------------

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

        # learn host location
        self.host_location[src] = (dpid, in_port)

        # check if we already installed this flow
        if (src, dst) in self.installed_paths:
            return

        if dst in self.host_location:

            dst_switch, dst_port = self.host_location[dst]

            # multipath routing
            paths = list(nx.all_shortest_paths(self.net, dpid, dst_switch))

            path = random.choice(paths)

            self.logger.info(f"Selected path: {path}")

            self.install_path(path, dst_port, src, dst)

            # cache the path
            self.installed_paths[(src, dst)] = path

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

    # --------------------------------
    # Install Path
    # --------------------------------

    def install_path(self, path, dst_port, src, dst):

        for i in range(len(path) - 1):

            sw = path[i]
            next_sw = path[i + 1]

            datapath = self.get_datapath(sw)

            if datapath is None:
                continue

            parser = datapath.ofproto_parser

            out_port = self.net[sw][next_sw]['port']

            actions = [parser.OFPActionOutput(out_port)]

            match = parser.OFPMatch(
                eth_src=src,
                eth_dst=dst
            )

            self.add_flow(datapath, 10, match, actions)

        # final switch → host
        last_switch = path[-1]

        datapath = self.get_datapath(last_switch)

        parser = datapath.ofproto_parser

        actions = [parser.OFPActionOutput(dst_port)]

        match = parser.OFPMatch(
            eth_src=src,
            eth_dst=dst
        )

        self.add_flow(datapath, 10, match, actions)

    # --------------------------------
    # Flow Installation
    # --------------------------------

    def add_flow(self, datapath, priority, match, actions):

        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

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

    # --------------------------------
    # Datapath Lookup
    # --------------------------------

    def get_datapath(self, dpid):

        return self.dpset.get(dpid)