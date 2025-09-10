#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Reason-GPL: import-scapy
import random
import socket
import sys
from scapy.all import IP, TCP, Ether, Dot1Q, get_if_hwaddr, get_if_list, sendp

def get_if():
    ifs = get_if_list()
    iface = None
    for i in get_if_list():
        if "eth0" in i:
            iface = i
            break
    if not iface:
        print("Cannot find eth0 interface")
        exit(1)
    return iface

def main():
    if len(sys.argv) < 3:
        print('pass 2 arguments: <destination> "<message>"')
        exit(1)

    addr = socket.gethostbyname(sys.argv[1])
    vlan_id = 2  # VLAN ID for text traffic
    pcp = 4       # Priority Code Point for audio (moderate priority)
    iface = get_if()

    print(f"Sending audio packets on interface {iface} to {addr} with VLAN ID {vlan_id}, PCP {pcp}")
    pkt = (Ether(src=get_if_hwaddr(iface), dst='08:00:00:00:02:22') /
           Dot1Q(prio=pcp, vlan=vlan_id) /
           IP(dst=addr) /
           TCP(dport=1234, sport=random.randint(49152, 65535)) /
           (sys.argv[2] * 10))  # Smaller payload for audio
    pkt.show2()
    sendp(pkt, iface=iface, verbose=False)

if __name__ == '__main__':
    main()