#ifndef _HEADERS_
#define _HEADERS_


// const int __STREAM_ID__ = 1; // Null Stream + Active identification

const int __STREAM_ID_SIZE__ = 5;

const int __STREAM_GATE_SIZE__ = 4;

const int __FLOW_METER_SIZE__ = 2;


// Headers used in the P4 program
typedef bit<48> mac_addr_t;
typedef bit<32> ipv4_addr_t;
typedef bit<32> reg_index_t;

// Port ID type
typedef bit<9> PortId_t;

@noWarn("unused")
const bit<64> MAXIMUM_48_BIT_TS = 281474976710655;

// EtherType values
enum bit<16> ether_type_t {
    IPV4        = 0x0800,
    IPV6        = 0x86dd,
    ETH_802_1Q  = 0x8100
}

enum bit<8> ip_type_t {
    TCP = 6,
    UDP = 17
}

header ethernet_t {
    mac_addr_t dst_addr;
    mac_addr_t src_addr;
    bit<16> ether_type;
}

header transport_t{
    bit<16> srcPort;
    bit<16> dstPort;
}

header eth_802_1q_t {
    bit<3> pcp; // Priority Code Point
    bit<1> dei; // Drop Eligible Indicator
    bit<12> vid; // VLAN indicator
    bit<16> ether_type;
}

header ipv4_t {
    bit<4> version;
    bit<4> ihl;
    bit<6> diffserv;
    bit<2> ecn;
    bit<16> total_len;
    bit<16> identification;
    bit<3> flags;
    bit<13> frag_offset;
    bit<8> ttl;
    bit<8> protocol;
    bit<16> hdr_checksum;
    ipv4_addr_t srcAddr;
    ipv4_addr_t dstAddr;
}

struct header_t {
    ethernet_t ethernet;
    eth_802_1q_t eth_802_1q;
    ipv4_t ipv4;
    transport_t transport;
}

struct bytes_in_period_t {
    bit<32> period_id;
    bit<32> octects_in_this_period;
}

/*
Reason corresponds to the digest_type set and tells the control plane why and what to close.
    1: not used
    2: not used
    3: Block FlowMeter due to exceeding bandwidth (marked red by flow meter)
    4: not used
    5: not used
    6: Indicate that a full hyperperiod is finished.
*/
struct digest_block_t {
    bit<16> stream_handle;
    bit<12> stream_gate_id;
    bit<9> egress_spec;
    bit<1> PSFPGateEnabled;
    bit<3> reason;
    bit<2> color;
    bit<16> flow_meter_instance_id;
}

struct digest_finished_hyperperiod_t {
    bit<12> stream_gate_id;
    bit<48> ingress_ts;
    bit<48> hyperperiod_ts;         // Register value of last hyperperiod
    bit<48> last_hyperperiod;      // Timestamp of the last hyperperiod
}

struct digest_debug_gate_t {
    bit<20> rel_pos;
    bit<12> stream_gate_id;
    bit<64> diff_ts;                // Relative position in hyperperiod
    bit<64> ingress_timestamp;      
    bit<64> hyperperiod_ts;         // Register value of last hyperperiod
    bit<32> period_count;
    bit<16> pkt_len;
}

struct stream_filter_t {
    bit<16> stream_handle;
    bit<1> stream_blocked_due_to_oversize_frame;  // Max SDU exceeded, stream blocked permanently
    bit<1> stream_blocked_due_to_oversize_frame_enable;
    bit<1> active_stream_identification;          // Flag if header values will be overwritten on stream identification
    bit<12> stream_gate_id;
    bit<16> flow_meter_instance_id;
}

struct stream_gate_t {
    bit<4> ipv;
    bit<1> PSFPGateEnabled;
    bit<32> max_octects_interval;
    bit<32> initial_sdu;
    bit<1> reset_octets;
    bit<32> remaining_octets;
    bit<12> interval_identifier;
    bit<1> gate_closed_due_to_invalid_rx_enable;
    bit<1> gate_closed_due_to_octets_exceeded_enable;
    bit<1> gate_closed;
}

enum bit<2> MeterColor_t {
    GREEN       = 0,    // 00
    YELLOW      = 1,    // 01
    PRE_YELLOW  = 2,    // 10
    RED         = 3     // 11
}

struct flow_meter_t {
    bit<2> color;
    bit<1> drop_on_yellow;
    bit<1> meter_blocked;
    bit<1> mark_all_frames_red_enable;
    bit<1> color_aware;                       // true means packets labeled yellow from previous bridges will not be able to be labeled back to green
    MeterColor_t pre_color;
}

struct ingress_metadata_t {
    stream_filter_t stream_filter;
    stream_gate_t stream_gate;
    flow_meter_t flow_meter;
    bit<64> diff_ts;  // Relative position in hyperperiod  
    bit<1> to_be_dropped;
}

struct egress_metadata_t {
    bit<64> difference_max_to_hyperperiod;
    bit<64> rel_ts_plus_offset;
    bit<64> hyperperiod_duration;
    bit<64> new_rel_pos_with_offset;
    bit<64> offset;
    bit<64> hyperperiod_minus_offset;
}

struct hyperperiod_t {
    bit<48> hyperperiod_ts;        // Value from hyperperiod register loaded in here
    bit<16> pkt_count_hyperperiod; // Amount of packets that need to be captured until the hyperperiod TS is updated
    bit<16> pkt_count_register;    // Amount of packets that have been captured in the current hyperperiod
}

struct metadata_t {
    ingress_metadata_t ingress_md; // Metadata for ingress processing
    egress_metadata_t egress_md;   // Metadata for egress processing
    hyperperiod_t hyperperiod;
    bit<48> last_hyperperiod;      // Timestamp of the last hyperperiod
    bit<32> period_count;          // Used for OctectsExceeded param of stream gate
    bit<48> ingress_ts;            // Timestamp of the packet when it entered the switch
    bit<64> hyperperiod_ts;
    bit<64> delta;
}

#endif /* _HEADERS_ */
