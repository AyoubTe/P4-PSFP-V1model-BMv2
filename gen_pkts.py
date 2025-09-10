#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Reason-GPL: import-scapy
import random
import socket
import sys
from scapy.all import IP, TCP, UDP, Ether, Dot1Q, get_if_hwaddr, get_if_list, sendp

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
    if len(sys.argv) < 4:
        print('pass 3 arguments: <destination> "<message>" <flow_type>')
        exit(1)

    addr = socket.gethostbyname(sys.argv[1])
    message = sys.argv[2]
    flow_type = sys.argv[3].lower()

    flows = {
        "1": {"pcp": 5, "vid": 100, "dscp": 46, "ecn": 0, "protocol": 17, "ttl": 64}, # Audio
        "2": {"pcp": 4, "vid": 200, "dscp": 34, "ecn": 0, "protocol": 17, "ttl": 64}, # Video
        "3": {"pcp": 0, "vid": 300, "dscp": 0, "ecn": 0, "protocol": 6, "ttl": 128}, # Text
        "4": {"pcp": 3, "vid": 400, "dscp": 26, "ecn": 0, "protocol": 17, "ttl": 64}, # Streaming
        "5": {"pcp": 2, "vid": 500, "dscp": 18, "ecn": 0, "protocol": 6, "ttl": 128}, # Varied
    }

    if flow_type not in flows:
        print("Invalid flow type. Choose from: 1. audio, 2. video, 3. text, 4. streaming, 5. varied")
        exit(1)

    param = flows[flow_type]
    iface = get_if()
    dst_mac = '08:00:00:00:02:22'  # Destination MAC address for the packets is host 2

    print(f"Sending {flow_type} packets on interface {iface} to {addr} with VLAN ID {param['vid']}, PCP {param['pcp']}")

    ether = Ether(src=get_if_hwaddr(iface), dst=dst_mac)
    dot1q = Dot1Q(prio=param["pcp"], vlan=param["vid"])
    ip = IP(dst=addr, ttl=param["ttl"], tos=(param["dscp"] << 2) | param["ecn"])

    if param["protocol"] == 17:
        transport = UDP(dport=1234, sport=random.randint(49152, 65535))
    else:
        transport = TCP(dport=1234, sport=random.randint(49152, 65535))

    pkt = ether / dot1q / ip / transport / (message * 100)
    pkt.show2()
    sendp(pkt, iface=iface, verbose=False)

if __name__ == '__main__':
    main()