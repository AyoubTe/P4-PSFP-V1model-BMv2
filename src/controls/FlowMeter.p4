control FlowMeter(
    inout header_t hdr,
    inout metadata_t meta,
    inout standard_metadata_t std_md
) {
    // Counts the number of packets that passed the flow meter
    direct_meter<bit<2>>(MeterType.bytes) flow_meter;

    // Counts the number of packets that were marked red by the flow meter
    counter(__FLOW_METER_SIZE__, CounterType.packets_and_bytes) marked_red_counter;

    // Counts the number of packets that were marked yellow by the flow meter
    // (i.e. the packets that were marked as DEI=1)
    counter(__FLOW_METER_SIZE__, CounterType.packets_and_bytes) marked_yellow_counter;

    // Counts the number of packets that were marked green by the flow meter
    counter(__FLOW_METER_SIZE__, CounterType.packets_and_bytes) marked_green_counter;

    register<bit<1>>(__FLOW_METER_SIZE__) reg_meter_blocked;

    action drop_packet() {
        mark_to_drop(std_md);
        // Drop the packet by setting the egress_spec to 0

        meta.ingress_md.to_be_dropped = 1w1;
    }

    action set_color_direct() {
        /*
        0: GREEN
        1: YELLOW
        2: YELLOW
        3: RED
        */
        flow_meter.read(meta.ingress_md.flow_meter.color);
    }

    action set_flow_meter_config(bit<1> dropOnYellow, bit<1> markAllFramesRedEnable, bit<1> colorAware){
        meta.ingress_md.flow_meter.drop_on_yellow = dropOnYellow;
        meta.ingress_md.flow_meter.mark_all_frames_red_enable = markAllFramesRedEnable;
        meta.ingress_md.flow_meter.color_aware = colorAware;
    }

    table flow_meter_config {
        key = {
            meta.ingress_md.stream_filter.flow_meter_instance_id: exact;
        }
        actions = {
            set_flow_meter_config;
        }
        size = __STREAM_ID_SIZE__;
    }

    table flow_meter_instance {
        key = {
            meta.ingress_md.stream_filter.flow_meter_instance_id: exact;
        }
        actions = {
            set_color_direct;
        }
        meters = flow_meter;
        size = __STREAM_ID_SIZE__;
    }

    apply {
        flow_meter_config.apply();

        // PRE-COLORING
        if (meta.ingress_md.flow_meter.color_aware == 1 && hdr.eth_802_1q.dei == 1) {
            // We are in color-aware mode and the received pkt is labeled yellow.
            // --> Keep it yellow
            meta.ingress_md.flow_meter.pre_color = MeterColor_t.YELLOW;
        } else {
            // color-blind mode or no pre-color: Assume all pkts green
            meta.ingress_md.flow_meter.pre_color = MeterColor_t.GREEN;
        }

        if (meta.ingress_md.to_be_dropped != 1w1) {
            // Only pay tokens for this packet if it is not supposed to be dropped anyway
            flow_meter_instance.apply();
        }

        // Color evaluation
        if (meta.ingress_md.flow_meter.color == 1 || meta.ingress_md.flow_meter.color == 2) {
            // Yellow colored
            reg_meter_blocked.read(meta.ingress_md.flow_meter.meter_blocked, (bit<32>)meta.ingress_md.stream_filter.flow_meter_instance_id);
            if (meta.ingress_md.flow_meter.drop_on_yellow == 1w1 || meta.ingress_md.flow_meter.meter_blocked == 1w1) {
                drop_packet();
                meta.ingress_md.flow_meter.color = 3; // Mark as red
                // Count the packet as red
                marked_red_counter.count((bit<32>)meta.ingress_md.stream_filter.flow_meter_instance_id);
            } else {
                hdr.eth_802_1q.dei = 1;
                marked_yellow_counter.count((bit<32>)meta.ingress_md.stream_filter.flow_meter_instance_id);
            }
        } else if (meta.ingress_md.flow_meter.color == 3) {
            // Red colored
            drop_packet();
            // Count the packet as red
            marked_red_counter.count((bit<32>)meta.ingress_md.stream_filter.flow_meter_instance_id);
            if (meta.ingress_md.flow_meter.mark_all_frames_red_enable == 1w1) {
                reg_meter_blocked.write((bit<32>)meta.ingress_md.stream_filter.flow_meter_instance_id, 1w1);
                
                digest<digest_block_t>(
                    12, // receiver
                    {
                        meta.ingress_md.stream_filter.stream_handle,
                        meta.ingress_md.stream_filter.stream_gate_id,
                        std_md.egress_spec,
                        meta.ingress_md.stream_gate.PSFPGateEnabled,
                        6,
                        meta.ingress_md.flow_meter.color,
                        meta.ingress_md.stream_filter.flow_meter_instance_id
                    }
                );
            }
        } else if (meta.ingress_md.flow_meter.color == 0 && meta.ingress_md.to_be_dropped != 1w1) {
            // Green colored
            reg_meter_blocked.read(meta.ingress_md.flow_meter.meter_blocked, (bit<32>)meta.ingress_md.stream_filter.flow_meter_instance_id);
            if (meta.ingress_md.flow_meter.meter_blocked == 1) {
                drop_packet();
                // Mark the packet as red
                meta.ingress_md.flow_meter.color = 3;
                // Count the packet as red
                marked_red_counter.count((bit<32>)meta.ingress_md.stream_filter.flow_meter_instance_id);
            } else {
                hdr.eth_802_1q.dei = 0; // Mark as green again
                marked_green_counter.count((bit<32>)meta.ingress_md.stream_filter.flow_meter_instance_id);
            }
        }
    }
}