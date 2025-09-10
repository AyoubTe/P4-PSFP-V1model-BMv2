control IPv4(
    inout header_t hdr,
    inout metadata_t meta,
    inout standard_metadata_t std_md
) {

    direct_counter(CounterType.packets) debug_counter;

    action ipv4_forward(mac_addr_t eth_dst_addr, PortId_t port) {
        // Set output port from control plane
        std_md.egress_spec = port;

        // Change layer 2 addresses: Src of switch, dest of target
        hdr.ethernet.src_addr = hdr.ethernet.dst_addr;
		hdr.ethernet.dst_addr = eth_dst_addr;

        // Decrement TTL
        hdr.ipv4.ttl = hdr.ipv4.ttl - 1;
        debug_counter.count();
    }

    action drop(){
        mark_to_drop(std_md);
    }

    table ipv4 {
        key = {
            hdr.ipv4.dstAddr: lpm;
        }
        actions = {
            ipv4_forward;
            drop;
        }
        size = 1024;
        counters = debug_counter;
        default_action = drop;
    }

    apply {
        if (hdr.ipv4.isValid()) {
            ipv4.apply();
        }
    }
}
