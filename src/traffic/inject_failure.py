#!/usr/bin/env python3
"""
inject_failure.py
-----------------
Injects a link failure mid-experiment to trigger fast-reroute,
then restores the link after a configurable hold time.

Usage (from Mininet Python API):
  from traffic.inject_failure import inject_link_failure
  inject_link_failure(net, node1='s3', node2='s5', hold=10)

Usage (standalone for testing):
  python3 inject_failure.py --node1 s3 --node2 s5 --hold 10 --delay 15

The script:
  1. Waits `delay` seconds (so traffic is established first)
  2. Brings the link down  → triggers fast-reroute in the controller
  3. Records the down timestamp
  4. Waits `hold` seconds
  5. Restores the link
  6. Records restore timestamp
  7. Writes failure event metadata to /tmp/failure_event.json
"""

import argparse
import json
import time


def inject_link_failure(net, node1: str, node2: str,
                        hold: int = 10, delay: int = 0,
                        output_file: str = '/tmp/failure_event.json'):
    """
    Args:
        net      : Mininet net object
        node1    : first node of the link to fail
        node2    : second node of the link to fail
        hold     : seconds to keep the link down before restoring
        delay    : seconds to wait before injecting the failure
        output_file: path to write failure event metadata
    """
    if delay > 0:
        print(f'[failure] Waiting {delay}s before injecting failure ...')
        time.sleep(delay)

    print(f'[failure] Taking link {node1} ↔ {node2} DOWN')
    t_down = time.time()
    net.configLinkStatus(node1, node2, 'down')

    print(f'[failure] Link down. Holding for {hold}s ...')
    time.sleep(hold)

    print(f'[failure] Restoring link {node1} ↔ {node2}')
    net.configLinkStatus(node1, node2, 'up')
    t_up = time.time()

    event = {
        'node1':          node1,
        'node2':          node2,
        'down_timestamp': t_down,
        'up_timestamp':   t_up,
        'hold_seconds':   hold,
        'down_iso':       time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t_down)),
        'up_iso':         time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t_up)),
    }

    with open(output_file, 'w') as f:
        json.dump(event, f, indent=2)

    print(f'[failure] Event metadata saved → {output_file}')
    return event


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Link failure injector (standalone test)')
    parser.add_argument('--node1', default='s3')
    parser.add_argument('--node2', default='s5')
    parser.add_argument('--hold',  type=int, default=10)
    parser.add_argument('--delay', type=int, default=0)
    args = parser.parse_args()

    print('[failure] Standalone mode — no Mininet net object available.')
    print(f'[failure] Would fail link {args.node1} ↔ {args.node2} '
          f'after {args.delay}s, hold for {args.hold}s.')
    print('[failure] Run from experiment orchestrator to use with Mininet.')
