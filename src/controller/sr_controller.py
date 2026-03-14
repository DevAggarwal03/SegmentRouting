from ryu.base import app_manager
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3

from ryu.topology import event
from ryu.topology.api import get_switch, get_link


class SRController(app_manager.RyuApp):

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(SRController, self).__init__(*args, **kwargs)

        self.switches = []
        self.links = []

        self.logger.info("SR Controller Started")

# event to discover the topology when any switch enters the network
    @set_ev_cls(event.EventSwitchEnter)
    def get_topology_data(self, ev):

        switch_list = get_switch(self, None)
        self.switches = [switch.dp.id for switch in switch_list]

        links_list = get_link(self, None)
        self.links = [(link.src.dpid, link.dst.dpid) for link in links_list]

        self.logger.info("Discovered Switches: %s", self.switches)
        self.logger.info("Discovered Links: %s", self.links)
