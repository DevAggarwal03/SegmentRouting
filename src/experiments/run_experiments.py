#!/usr/bin/env python3
"""
run_experiment.py
-----------------
Unified Python experiment orchestrator for SR-MPLS vs SRv6.

Why Python (not shell):
  Mininet requires root + Python API to properly control the network
  (bring links up/down, run host commands, etc.). This script wraps
  the full pipeline: controller → topology → traffic → failure → stats.

Usage (on Linux with Mininet + Ryu installed):
  sudo python3 run_experiment.py --mode sr-mpls --scenario latency
  sudo python3 run_experiment.py --mode srv6     --scenario bulk
  sudo python3 run_experiment.py --mode all      --scenario all

  # Run all combinations:
  sudo python3 run_experiment.py --mode all --scenario all

Output directory structure:
  /tmp/sr_results/
    sr-mpls_latency_<timestamp>.csv
    sr-mpls_latency_<timestamp>.json
    sr-mpls_bulk_<timestamp>.csv
    ...
    sr_mpls_metrics.json    (written by controller on exit)
    srv6_metrics.json       (written by controller on exit)
    failure_event.json      (written during failure scenario)
"""

import argparse
import os
import sys
import subprocess
import time
import signal

# Add src/ to path so we can import sibling modules
SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SRC_DIR)

from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel

from topology.sr_multipath_topo import SRMultipathTopo
from traffic.generate_traffic import run_profile
from traffic.inject_failure import inject_link_failure
from monitoring.stats_collector import StatsCollector


# ── Controller launcher ────────────────────────────────────────────────────────

CONTROLLER_SCRIPTS = {
    'sr-mpls': os.path.join(SRC_DIR, 'controller', 'sr_controller.py'),
    'srv6':    os.path.join(SRC_DIR, 'controller', 'srv6_controller.py'),
}

RYU_BIN = '/home/devnnd/.local/bin/ryu-manager'


def start_controller(mode: str) -> subprocess.Popen:
    """Start Ryu controller in background and return its Popen handle."""
    script = CONTROLLER_SCRIPTS[mode]
        cmd = [RYU_BIN, '--observe-links', '--wsapi-host', '127.0.0.1', script, 'ryu.app.ofctl_rest']
    print(f'[orchestrator] Starting {mode} controller ...')
    proc = subprocess.Popen(cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    time.sleep(4)   # give Ryu time to bind
    return proc


def stop_controller(proc: subprocess.Popen):
    """Gracefully terminate the Ryu controller."""
    if proc and proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    print('[orchestrator] Controller stopped.')


# ── Single experiment run ──────────────────────────────────────────────────────

def run_single(mode: str, scenario: str,
               bw: int, delay: str, loss: float,
               output_dir: str, duration: int):
    """Run one (mode, scenario) combination end-to-end."""

    print(f'\n{"="*60}')
    print(f' MODE={mode}  SCENARIO={scenario}')
    print(f'{"="*60}')

    ctrl_proc = start_controller(mode)

    topo = SRMultipathTopo(bw=bw, delay=delay, loss=loss)
    net  = Mininet(
        topo=topo,
        controller=None,
        switch=OVSSwitch,
        link=TCLink,
        autoSetMacs=False,
    )
    net.addController('c0', controller=RemoteController,
                      ip='127.0.0.1', port=6633)

    try:
        net.start()
        print('[orchestrator] Network started. Waiting for topology discovery ...')
        time.sleep(6)

        # Start stats collector
        run_output = os.path.join(output_dir, mode)
        collector  = StatsCollector(mode=mode, scenario=scenario,
                                    output_dir=run_output)
        collector.start()

        if scenario == 'failure':
            # Run latency traffic + inject failure after 15 s
            import threading
            fail_thread = threading.Thread(
                target=inject_link_failure,
                kwargs=dict(net=net, node1='s3', node2='s5',
                            hold=10, delay=15,
                            output_file=os.path.join(output_dir,
                                                     f'failure_event_{mode}.json')),
                daemon=True,
            )
            fail_thread.start()
            run_profile(net, 'latency', duration=duration,
                        output_dir=run_output)
            fail_thread.join()
        else:
            run_profile(net, scenario, duration=duration,
                        output_dir=run_output)

        collector.stop()
        saved = collector.save()
        print(f'[orchestrator] Results saved: {saved}')

    finally:
        net.stop()
        stop_controller(ctrl_proc)
        time.sleep(2)   # let ports release


# ── Main ───────────────────────────────────────────────────────────────────────

MODES     = ['sr-mpls', 'srv6']
SCENARIOS = ['latency', 'bulk', 'mixed', 'failure']


def main():
    parser = argparse.ArgumentParser(description='SR Experiment Orchestrator')
    parser.add_argument('--mode',     default='all',
                        choices=MODES + ['all'])
    parser.add_argument('--scenario', default='all',
                        choices=SCENARIOS + ['all'])
    parser.add_argument('--bw',       type=int,   default=10,    help='Link BW (Mbps)')
    parser.add_argument('--delay',    type=str,   default='5ms', help='Link delay')
    parser.add_argument('--loss',     type=float, default=0,     help='Link loss %%')
    parser.add_argument('--duration', type=int,   default=30,    help='Bulk/mixed duration (s)')
    parser.add_argument('--output',   default='/tmp/sr_results')
    args = parser.parse_args()

    setLogLevel('warning')
    os.makedirs(args.output, exist_ok=True)

    modes     = MODES     if args.mode     == 'all' else [args.mode]
    scenarios = SCENARIOS if args.scenario == 'all' else [args.scenario]

    for mode in modes:
        for scenario in scenarios:
            run_single(mode=mode,
                       scenario=scenario,
                       bw=args.bw,
                       delay=args.delay,
                       loss=args.loss,
                       output_dir=args.output,
                       duration=args.duration)

    print('\n[orchestrator] All experiments complete.')
    print(f'[orchestrator] Results in: {args.output}')
    print('[orchestrator] Run: python3 results/plots.py to generate charts.')


if __name__ == '__main__':
    if os.geteuid() != 0:
        print('[orchestrator] Must run as root (sudo). Exiting.')
        sys.exit(1)
    main()
