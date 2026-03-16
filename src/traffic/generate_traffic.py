#!/usr/bin/env python3
"""
generate_traffic.py
-------------------
Traffic workload generator for SR-MPLS vs SRv6 experiments.
Runs from inside a Mininet session (fed via subprocess) or
invoked directly from the experiment shell script.

Profiles
────────
  latency  : ICMP ping bursts  — measures RTT distributions
  bulk     : iperf3 TCP flows  — measures throughput
  mixed    : concurrent latency + bulk flows

Usage (from within Mininet Python API):
  from traffic.generate_traffic import run_profile
  run_profile(net, profile='latency', duration=30, output_dir='/tmp/results')

Usage (from shell, requires mn to expose the Python API):
  python3 generate_traffic.py --profile latency --duration 30
"""

import argparse
import os
import subprocess
import time
from itertools import combinations


# ── Host pairs to test ────────────────────────────────────────────────────────
HOST_NAMES  = ['h1', 'h2', 'h3', 'h4']
HOST_PAIRS  = list(combinations(HOST_NAMES, 2))   # 6 unique pairs

# ── Default experiment parameters ─────────────────────────────────────────────
PING_COUNT  = 50
PING_INTERVAL = 0.2          # seconds between pings (0.2 s → ~10 s burst)
IPERF_DURATION = 30          # seconds for bulk flows
IPERF_PORT  = 5201


def _mn_cmd(net, host_name: str, cmd: str, bg: bool = False):
    """Run a shell command on a Mininet host."""
    host = net.get(host_name)
    if bg:
        host.cmd(cmd + ' &')
    else:
        return host.cmd(cmd)


def run_latency(net, output_dir: str):
    """
    Latency profile: all-pairs ICMP ping.
    Results written to output_dir/latency_<src>_<dst>.txt
    """
    os.makedirs(output_dir, exist_ok=True)
    procs = []

    for src, dst in HOST_PAIRS:
        dst_ip = net.get(dst).IP()
        out_file = os.path.join(output_dir, f'latency_{src}_{dst}.txt')
        cmd = f'ping -c {PING_COUNT} -i {PING_INTERVAL} {dst_ip} > {out_file} 2>&1'
        _mn_cmd(net, src, cmd, bg=True)
        procs.append((src, dst, out_file))

    # Wait for all pings to finish (PING_COUNT * PING_INTERVAL + slack)
    time.sleep(PING_COUNT * PING_INTERVAL + 5)
    return procs


def run_bulk(net, output_dir: str, duration: int = IPERF_DURATION):
    """
    Bulk profile: iperf3 TCP flows between all host pairs.
    Results written to output_dir/bulk_<src>_<dst>.json
    """
    os.makedirs(output_dir, exist_ok=True)
    results = []

    for src, dst in HOST_PAIRS:
        dst_ip   = net.get(dst).IP()
        out_file = os.path.join(output_dir, f'bulk_{src}_{dst}.json')

        # Start iperf3 server on destination
        _mn_cmd(net, dst, f'iperf3 -s -p {IPERF_PORT} -D --one-off')
        time.sleep(0.5)

        # Start iperf3 client on source
        cmd = (f'iperf3 -c {dst_ip} -p {IPERF_PORT} '
               f'-t {duration} -J > {out_file} 2>&1')
        _mn_cmd(net, src, cmd, bg=False)
        results.append((src, dst, out_file))

        # Kill server
        _mn_cmd(net, dst, 'pkill -f iperf3')

    return results


def run_mixed(net, output_dir: str, duration: int = IPERF_DURATION):
    """
    Mixed profile: concurrent latency + bulk flows.
    One pair runs iperf3; remaining pairs run ping simultaneously.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Start bulk flow (h1 → h4)
    bulk_dst_ip = net.get('h4').IP()
    bulk_out    = os.path.join(output_dir, 'mixed_bulk_h1_h4.json')
    _mn_cmd(net, 'h4', f'iperf3 -s -p {IPERF_PORT} -D')
    time.sleep(0.3)
    _mn_cmd(net, 'h1',
            f'iperf3 -c {bulk_dst_ip} -p {IPERF_PORT} -t {duration} '
            f'-J > {bulk_out} 2>&1 &',
            bg=False)

    # Concurrent pings from h2 → h3 (cross-path)
    lat_dst_ip = net.get('h3').IP()
    lat_out    = os.path.join(output_dir, 'mixed_latency_h2_h3.txt')
    _mn_cmd(net, 'h2',
            f'ping -c {PING_COUNT} -i {PING_INTERVAL} {lat_dst_ip} '
            f'> {lat_out} 2>&1',
            bg=True)

    time.sleep(duration + 5)
    _mn_cmd(net, 'h4', 'pkill -f iperf3')


def run_profile(net, profile: str, duration: int = IPERF_DURATION,
                output_dir: str = '/tmp/results'):
    """Entry point for the experiment orchestrator."""
    print(f'[traffic] Starting profile: {profile}')
    if profile == 'latency':
        run_latency(net, output_dir)
    elif profile == 'bulk':
        run_bulk(net, output_dir, duration)
    elif profile == 'mixed':
        run_mixed(net, output_dir, duration)
    else:
        raise ValueError(f'Unknown profile: {profile}')
    print(f'[traffic] Profile "{profile}" complete. Results in {output_dir}')


# ── CLI shim for standalone testing ───────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Traffic generator (standalone test mode)')
    parser.add_argument('--profile',  choices=['latency', 'bulk', 'mixed'],
                        default='latency')
    parser.add_argument('--duration', type=int, default=IPERF_DURATION)
    parser.add_argument('--output',   default='/tmp/sr_results')
    args = parser.parse_args()

    print('[traffic] Standalone mode — no Mininet net object available.')
    print(f'[traffic] Would run profile "{args.profile}" for {args.duration}s')
    print(f'[traffic] Output dir: {args.output}')
    print('[traffic] Run from experiment orchestrator to use with Mininet.')
