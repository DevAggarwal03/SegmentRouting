from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.cli import CLI
from mininet.link import TCLink

class FatTreeTopo(Topo):

    def build(self):

        s1 = self.addSwitch('s1', protocols='OpenFlow13')
        s2 = self.addSwitch('s2', protocols='OpenFlow13')
        s3 = self.addSwitch('s3', protocols='OpenFlow13')
        s4 = self.addSwitch('s4', protocols='OpenFlow13')

        h1 = self.addHost('h1')
        h2 = self.addHost('h2')
        h3 = self.addHost('h3')
        h4 = self.addHost('h4')

        self.addLink(h1, s1)
        self.addLink(h2, s1)

        self.addLink(h3, s2)
        self.addLink(h4, s2)

        self.addLink(s1, s3)
        self.addLink(s2, s3)

        self.addLink(s1, s4)
        self.addLink(s2, s4)


if __name__ == '__main__':
    topo = FatTreeTopo()

    net = Mininet(
        topo=topo,
	controller=None
    )

    c0 = net.addController(
	'c0',
	 controller=RemoteController,
	 ip='127.0.0.1',
	 port=6633
    )

    net.start()

    CLI(net)

    net.stop()
