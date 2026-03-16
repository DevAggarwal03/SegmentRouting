#!/usr/bin/env python3
"""
sr_multipath_topo.py
--------------------
Primary shared topology for SR-MPLS vs SRv6 experiments.

Topology (6 switches, 4 hosts, 2 disjoint paths between every host pair):

    h1 ─── s1 ─── s3 ─── s5 ─── h3
                ╲   / \   ╱
                 s4 ─ s6 ------h4
                ╱       ╲
    h2 ─── s2 ─── s3     s5    (shared core)

Actual wiring:
  h1 - s1
  h2 - s2
  h3 - s5
  h4 - s6
  s1 - s3  (path A upper)
  s1 - s4  (path B lower)
  s2 - s3  (path A upper)
  s2 - s4  (path B lower)
  s3 - s5  (path A upper egress)
  s3 - s6  (cross link)
  s4 - s5  (cross link)
  s4 - s6  (path B lower egress)
  s5 - s6  (egress cross link)

This gives every src-dst pair at least 2 disjoint forwarding paths,
which is essential for SR path-selection evaluation.

CLI usage:
  sudo python3 sr_multipath_topo.py [--bw BW] [--delay DELAY] [--loss LOSS]
  sudo mn --custom sr_multipath_topo.py --topo sr_multipath,bw=10,delay=5ms
"""

import argparse
from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import setLogLevel, info


class SRMultipathTopo(Topo):
    """6-switch 4-host diamond/multi-path topology.

    Args:
        bw    : link bandwidth in Mbps  (default 10)
        delay : one-way link delay      (default '5ms')
        loss  : link loss percentage    (default 0)
    """

    def build(self, bw=10, delay='5ms', loss=0):

        link_opts = dict(bw=bw, delay=delay, loss=loss, use_htb=True)

        # ── Hosts ────────────────────────────────────────────────────────────
        h1 = self.addHost('h1', ip='10.0.0.1/24', mac='00:00:00:00:00:01')
        h2 = self.addHost('h2', ip='10.0.0.2/24', mac='00:00:00:00:00:02')
        h3 = self.addHost('h3', ip='10.0.0.3/24', mac='00:00:00:00:00:03')
        h4 = self.addHost('h4', ip='10.0.0.4/24', mac='00:00:00:00:00:04')

        # ── Switches (OpenFlow 1.3) ───────────────────────────────────────────
        s1 = self.addSwitch('s1', protocols='OpenFlow13')
        s2 = self.addSwitch('s2', protocols='OpenFlow13')
        s3 = self.addSwitch('s3', protocols='OpenFlow13')   # upper core
        s4 = self.addSwitch('s4', protocols='OpenFlow13')   # lower core
        s5 = self.addSwitch('s5', protocols='OpenFlow13')   # upper egress
        s6 = self.addSwitch('s6', protocols='OpenFlow13')   # lower egress

        # ── Host-to-switch links (no BW shaping for host links) ──────────────
        self.addLink(h1, s1)
        self.addLink(h2, s2)
        self.addLink(h3, s5)
        self.addLink(h4, s6)

        # ── Intra-core links (TC-shaped) ──────────────────────────────────────
        # Ingress layer
        self.addLink(s1, s3, **link_opts)   # path-A upper
        self.addLink(s1, s4, **link_opts)   # path-B lower
        self.addLink(s2, s3, **link_opts)   # path-A upper
        self.addLink(s2, s4, **link_opts)   # path-B lower

        # Core cross-links
        self.addLink(s3, s5, **link_opts)
        self.addLink(s3, s6, **link_opts)
        self.addLink(s4, s5, **link_opts)
        self.addLink(s4, s6, **link_opts)

        # Egress cross-link
        self.addLink(s5, s6, **link_opts)


# Allow use as `--custom` with `--topo sr_multipath[,bw=X,delay=Y]`
topos = {
    'sr_multipath': SRMultipathTopo
}


def run(bw, delay, loss, controller_ip, controller_port):
    """Spin up the topology and hand control to the Mininet CLI."""
    setLogLevel('info')

    topo = SRMultipathTopo(bw=bw, delay=delay, loss=loss)

    net = Mininet(
        topo=topo,
        controller=None,
        switch=OVSSwitch,
        link=TCLink,
        autoSetMacs=False,
    )

    c0 = net.addController(
        'c0',
        controller=RemoteController,
        ip=controller_ip,
        port=controller_port,
    )

    net.start()
    info('\n*** SR Multi-path Topology Ready ***\n')
    info(f'    Controller : {controller_ip}:{controller_port}\n')
    info(f'    Link  bw   : {bw} Mbps\n')
    info(f'    Link delay : {delay}\n')
    info(f'    Link loss  : {loss}%\n\n')

    CLI(net)
    net.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='SR Multi-path Mininet Topology')
    parser.add_argument('--bw',    type=int,   default=10,        help='Link bandwidth (Mbps)')
    parser.add_argument('--delay', type=str,   default='5ms',     help='Link delay (e.g. 5ms)')
    parser.add_argument('--loss',  type=float, default=0,         help='Link loss %%')
    parser.add_argument('--ctrl-ip',   default='127.0.0.1',       help='Controller IP')
    parser.add_argument('--ctrl-port', type=int, default=6633,    help='Controller port')
    args = parser.parse_args()

    run(args.bw, args.delay, args.loss, args.ctrl_ip, args.ctrl_port)
