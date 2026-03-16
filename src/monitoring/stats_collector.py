#!/usr/bin/env python3
"""
stats_collector.py
------------------
Collects per-flow statistics from the Ryu REST API and writes
structured CSV/JSON output for post-experiment analysis.

Ryu REST endpoints used:
  GET /stats/flow/{dpid}      — per-flow byte/packet counters
  GET /stats/port/{dpid}      — per-port TX/RX byte counters

Usage (from experiment orchestrator):
  collector = StatsCollector(mode='sr-mpls', scenario='bulk',
                             output_dir='/tmp/sr_results',
                             controller_url='http://127.0.0.1:8080')
  collector.start()
  # ... run traffic ...
  collector.stop()
  collector.save()

Run standalone (polls until Ctrl-C):
  python3 stats_collector.py --mode sr-mpls --scenario bulk
"""

import argparse
import csv
import json
import os
import time
import threading
from typing import Optional
import requests
from datetime import datetime


class StatsCollector:
    """Polls Ryu REST API and accumulates per-switch flow statistics."""

    FLOW_URL  = 'http://{host}/stats/flow/{dpid}'
    PORT_URL  = 'http://{host}/stats/port/{dpid}'
    DPIDS     = [1, 2, 3, 4, 5, 6]     # matches sr_multipath_topo switch IDs

    def __init__(self, mode: str, scenario: str,
                 output_dir: str = '/tmp/sr_results',
                 controller_host: str = '127.0.0.1:8080',
                 poll_interval: float = 2.0):
        self.mode      = mode
        self.scenario  = scenario
        self.output_dir= output_dir
        self.host      = controller_host
        self.interval  = poll_interval

        self._records: list                         = []
        self._running: bool                          = False
        self._thread:  Optional[threading.Thread]    = None

        os.makedirs(output_dir, exist_ok=True)

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self):
        """Start background polling thread."""
        self._running = True
        self._thread  = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        print(f'[stats] Collector started — mode={self.mode} scenario={self.scenario}')

    def stop(self):
        """Stop polling."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=self.interval + 1)
        print(f'[stats] Collector stopped — {len(self._records)} records captured')

    def save(self):
        """Write collected data to CSV and JSON."""
        ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        base = os.path.join(self.output_dir, f'{self.mode}_{self.scenario}_{ts}')
        self._save_csv(base + '.csv')
        self._save_json(base + '.json')
        return base

    # ── Internal ───────────────────────────────────────────────────────────────

    def _poll_loop(self):
        prev_bytes = {}         # (dpid, match_str) → byte_count

        while self._running:
            ts = time.time()

            for dpid in self.DPIDS:
                try:
                    flow_data = self._get_json(
                        self.FLOW_URL.format(host=self.host, dpid=dpid))
                    port_data = self._get_json(
                        self.PORT_URL.format(host=self.host, dpid=dpid))
                except Exception as e:
                    print(f'[stats] Poll error dpid={dpid}: {e}')
                    continue

                flows = flow_data.get(str(dpid), [])
                ports = port_data.get(str(dpid), [])

                # Aggregate flow counters
                total_flow_rules = len(flows)
                total_packets    = sum(f.get('packet_count', 0) for f in flows)
                total_bytes      = sum(f.get('byte_count',   0) for f in flows)

                # Per-port RX/TX
                rx_bytes = sum(p.get('rx_bytes', 0) for p in ports)
                tx_bytes = sum(p.get('tx_bytes', 0) for p in ports)
                rx_drop  = sum(p.get('rx_dropped', 0) for p in ports)
                tx_drop  = sum(p.get('tx_dropped', 0) for p in ports)

                # Throughput delta
                key = f'{dpid}_total'
                prev = prev_bytes.get(key, total_bytes)
                delta_bytes = total_bytes - prev
                throughput_bps = (delta_bytes * 8) / self.interval
                prev_bytes[key] = total_bytes

                self._records.append({
                    'timestamp':       ts,
                    'mode':            self.mode,
                    'scenario':        self.scenario,
                    'dpid':            dpid,
                    'flow_rules':      total_flow_rules,
                    'packet_count':    total_packets,
                    'byte_count':      total_bytes,
                    'throughput_bps':  throughput_bps,
                    'rx_bytes':        rx_bytes,
                    'tx_bytes':        tx_bytes,
                    'rx_dropped':      rx_drop,
                    'tx_dropped':      tx_drop,
                })

            time.sleep(self.interval)

    @staticmethod
    def _get_json(url: str) -> dict:
        resp = requests.get(url, timeout=3)
        resp.raise_for_status()
        return resp.json()

    def _save_csv(self, path: str):
        if not self._records:
            return
        fieldnames = list(self._records[0].keys())
        with open(path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self._records)
        print(f'[stats] CSV saved → {path}')

    def _save_json(self, path: str):
        with open(path, 'w') as f:
            json.dump(self._records, f, indent=2)
        print(f'[stats] JSON saved → {path}')


# ── Standalone CLI ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Ryu stats collector')
    parser.add_argument('--mode',     default='sr-mpls',
                        choices=['sr-mpls', 'srv6'])
    parser.add_argument('--scenario', default='bulk',
                        choices=['latency', 'bulk', 'mixed', 'failure'])
    parser.add_argument('--output',   default='/tmp/sr_results')
    parser.add_argument('--host',     default='127.0.0.1:8080')
    parser.add_argument('--interval', type=float, default=2.0)
    args = parser.parse_args()

    col = StatsCollector(mode=args.mode, scenario=args.scenario,
                         output_dir=args.output,
                         controller_host=args.host,
                         poll_interval=args.interval)
    col.start()
    print('[stats] Press Ctrl-C to stop collecting.')
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        col.stop()
        col.save()
