// P4 Implementation of a V1model-compatible parser and deparser
// This code defines the parser and deparser for a P4 program that processes Ethernet, IPv4, and transport headers.
// It includes parsing logic for both standard Ethernet frames and VLAN-tagged frames
// and handles IPv4 packets with TCP and UDP protocols.

// V1model-compatible parser
parser ParserImpl(
    packet_in pkt,
    out header_t hdr,
    inout metadata_t meta,
    inout standard_metadata_t standard_metadata
) {
    state start {
        transition parse_ethernet;
    }

    // Ethernet header parsing
    state parse_ethernet {
        pkt.extract(hdr.ethernet);
        transition select(hdr.ethernet.ether_type) {
            ether_type_t.IPV4 : parse_ipv4;
            ether_type_t.ETH_802_1Q : parse_802_1q;
            default : accept;
        }
    }

    // IPv4 header parsing
    state parse_ipv4 {
        pkt.extract(hdr.ipv4);
        transition select(hdr.ipv4.protocol) {
            ip_type_t.UDP : parse_transport;
            ip_type_t.TCP : parse_transport;
            default : accept;
        }
    }

    // Transport layer header parsing
    state parse_transport {
        pkt.extract(hdr.transport);
        transition accept;
    }

    // 802.1Q VLAN header parsing
    state parse_802_1q {
        pkt.extract(hdr.eth_802_1q);
        transition select(hdr.eth_802_1q.ether_type) {
            ether_type_t.IPV4 : parse_ipv4;
            default: accept;
        }
    }
}

// V1model-compatible deparser
control DeparserImpl(
    packet_out pkt,
    in header_t hdr
) {

    apply {
        // We don't need to update ckecksum fields in this deparser
        // Because is done in the checksums control
        // Emit headers
        pkt.emit(hdr.ethernet);
        pkt.emit(hdr.eth_802_1q);
        pkt.emit(hdr.ipv4);
        pkt.emit(hdr.transport);
    }
}
