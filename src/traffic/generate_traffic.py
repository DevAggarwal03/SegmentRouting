import os
import time

hosts = ["h1", "h2", "h3", "h4"]

for src in hosts:
    for dst in hosts:

        if src != dst:

            cmd = f"mininet> {src} ping -c 5 {dst} &"
            print(cmd)

time.sleep(10)
