#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Reason-GPL: import-scapy
import random
import socket
import sys

from scapy.all import IP, TCP, Ether, Dot1Q, get_if_hwaddr, get_if_list, sendp


def get_if():
    ifs = get_if_list()
    iface = None  # "h1-eth0"
    for i in get_if_list():
        if "eth0" in i:
            iface = i
            break
    if not iface:
        print("Cannot find eth0 interface")
        exit(1)
    return iface


def main():
    if len(sys.argv) < 4:
        print('pass 3 arguments: <destination> "<message>" <vlan_id>')
        exit(1)

    addr = socket.gethostbyname(sys.argv[1])
    try:
        vlan_id = int(sys.argv[3])
        if not (1 <= vlan_id <= 4094):
            print("VLAN ID must be between 1 and 4094")
            exit(1)
    except ValueError:
        print("VLAN ID must be a valid integer")
        exit(1)

    iface = get_if()

    print("Sending on interface %s to %s with VLAN ID %d" % (iface, str(addr), vlan_id))
    pkt = Ether(src=get_if_hwaddr(iface), dst='08:00:00:00:02:22')
    pkt = pkt / Dot1Q(vlan=vlan_id) / IP(dst=addr) / TCP(dport=1234, sport=random.randint(49152, 65535)) / sys.argv[2]
    pkt.show2()
    sendp(pkt, iface=iface, verbose=False)


if __name__ == '__main__':
    main()