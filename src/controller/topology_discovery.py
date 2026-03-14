from ryu.topology import event
from ryu.topology.api import get_switch, get_link

def __init__(self, *args, **kwargs):
	super(SRController, self).__init__(*args, **kwargs)

	self.switches = []
	self.links = []

	@set_ev_cls(event.EventSwitchEnter)
	def get_topology_data(self, ev):
	
		switch_list = get_switch(self, None)
		self.switches = [switch.dp.id for switch in switch_list]

	        links_list = get_link(self, None)
	        self.links = [(link.src.dpid, link.dst.dpid) for link in links_list]

	        self.logger.info("Switches: %s", self.switches)
	        self.logger.info("Links: %s", self.links)
