// StreamFilter: Identifies streams and enforces max SDU (frame size)
control StreamFilter (
    inout header_t hdr,
    inout metadata_t meta,
    inout standard_metadata_t std_md
) {
    // Counts packets and bytes for each stream identified by stream_id table
    // The number of frames that have matched the pair stream_handle specification and vlan id specification
    direct_counter(CounterType.packets_and_bytes) stream_id_counter; // Matching Frames Count

    // Counts packets and bytes for stream_id table overwrites (e.g., re-assignments)
    // This counter is used to track how many times a stream ID has been overwritten
    direct_counter(CounterType.packets_and_bytes) stream_id_overwrite_counter;

    // Counts packets and bytes for stream filter processing (Nb of frames processed)
    // This counter is used to track how many frames have been processed by the StreamFilter control
    direct_counter(CounterType.packets_and_bytes) stream_filter_counter; 

    // Counts frames (packets and bytes) that passed the Max SDU filter (Nb of frames habing length <= MaxSDUSize)
    // This counter is used to track how many frames have passed the Max SDU filter
    // (i.e., frames that have a length <= MaxSDUSize bytes and have a valid vid or stream_handle)
    direct_counter(CounterType.packets_and_bytes) max_sdu_filter_counter;

    // Counts number of frames that did not pass the Max SDU filter (Nb that don't have length <= MaxSDUSize and/or don't have stream_handle)
    counter(__STREAM_ID_SIZE__, CounterType.packets) missed_max_sdu_filter_counter;

    // Overall counter for packets and bytes
    @noWarn("unused")
    // Counts the number of frames that have been assigned a stream_gate and a flow meter
    counter(__STREAM_ID_SIZE__, CounterType.packets_and_bytes) overall_counter;

    // Register to track if a stream is blocked due to oversize frame
    register<bit<1>>(__STREAM_ID_SIZE__) reg_filter_blocked;

    action overwrite_stream_active(mac_addr_t eth_dst_addr, bit<12> vid, bit<3> pcp){
        // Used for active stream identification function 
        hdr.ethernet.dst_addr = eth_dst_addr;
        hdr.eth_802_1q.vid = vid;
        hdr.eth_802_1q.pcp = pcp;

        stream_id_overwrite_counter.count();
    }

    // Assigns a stream handle to the stream identified by the table
    action assign_stream_handle(bit<16> stream_handle, bit<1> active, 
                                    bit<1> stream_blocked_due_to_oversize_frame_enable) {

        // Assign the stream_handle to identifiy this stream
        // Sets the 'active' flag which is used to determine if fields will be overwritten

        meta.ingress_md.stream_filter.stream_handle = stream_handle; 
        meta.ingress_md.stream_filter.active_stream_identification = active;
        meta.ingress_md.stream_filter.stream_blocked_due_to_oversize_frame_enable = stream_blocked_due_to_oversize_frame_enable;

        stream_id_counter.count();
    }

    // Assigns the stream gate ID and flow meter instance ID to the stream
    action assign_gate_and_meter(bit<12> stream_gate_id, bit<16> flow_meter_instance_id, 
                                    bit<1> gate_closed_due_to_invalid_rx_enable, 
                                    bit<1> gate_closed_due_to_octets_exceeded_enable) {
        
        meta.ingress_md.stream_filter.stream_gate_id = stream_gate_id;
        meta.ingress_md.stream_filter.flow_meter_instance_id = flow_meter_instance_id;

        meta.ingress_md.stream_gate.gate_closed_due_to_invalid_rx_enable = gate_closed_due_to_invalid_rx_enable;
        meta.ingress_md.stream_gate.gate_closed_due_to_octets_exceeded_enable = gate_closed_due_to_octets_exceeded_enable;

        stream_filter_counter.count();
    }

    // If the frame has a correct length, it will not be dropped; nothing is done
    action none() {
        max_sdu_filter_counter.count();
    }

    // Null stream ID only + active ID
    table stream_id {
        key = {
            hdr.ethernet.dst_addr: exact;     // Null stream + active identification
            hdr.eth_802_1q.vid: exact;
        }
        actions = {
            assign_stream_handle;
        }
        size = __STREAM_ID_SIZE__;
        counters = stream_id_counter;
    }

    /*
    Table to do active stream identification and overwrite some fields
    */
    table stream_id_active {
        key = {
            meta.ingress_md.stream_filter.stream_handle: exact;
        }
        actions = {
            overwrite_stream_active;
        }
        size = 256;
        counters = stream_id_overwrite_counter;
    }

    /*
    Table to map from stream_handle to stream gate and flow meter
    */
    table stream_filter_instance {
        key = {
            meta.ingress_md.stream_filter.stream_handle: exact;
        }
        actions = {
            assign_gate_and_meter;
        }
        counters = stream_filter_counter;
        size = __STREAM_ID_SIZE__;
    }

    /*
    Keep SDU Filter table as separate instance, else we can not distinguish 
    if the packet does not have a stream_handle or gets rejected because of max SDU size
    */
    table max_sdu_filter {
        key = {
            meta.ingress_md.stream_filter.stream_handle: exact;
            hdr.eth_802_1q.pcp: ternary;
            std_md.packet_length : range;
        }
        actions = {
            none;
        }
        counters = max_sdu_filter_counter;
        size = 512;
    }

    apply {
        // 1. First match on stream identification --> assign stream_handle
        if (stream_id.apply().hit){
            // Stream identification successful
            // 2. Now check if the stream is blocked due to oversize frame
            if (max_sdu_filter.apply().miss){
                // a) If the frame is oversized, we will drop it
                if (meta.ingress_md.stream_filter.stream_blocked_due_to_oversize_frame_enable == 1w1){
                    // Permanently block out this stream
                    reg_filter_blocked.write((bit<32>)meta.ingress_md.stream_filter.stream_handle, 1w1);
                }
                
                // b) Drop because MAXSDU exceeded
                mark_to_drop(std_md);
                // Drop the packet by setting the egress_spec to 0
                meta.ingress_md.to_be_dropped = 1w1;

                missed_max_sdu_filter_counter.count((bit<32>) meta.ingress_md.stream_filter.stream_handle);
            } else {
                // Now the Frame is not oversize
                // 3. Get the filter state (does the stream is blocked or not?)
                reg_filter_blocked.read(meta.ingress_md.stream_filter.stream_blocked_due_to_oversize_frame, (bit<32>)meta.ingress_md.stream_filter.stream_handle);

                // 4. Match on assigned stream_handle --> assign stream_gate and flow_meter
                if (stream_filter_instance.apply().hit){
                    // Stream gate and flow meter assigned successfully

                    overall_counter.count((bit<32>)meta.ingress_md.stream_filter.stream_handle);

                    // 5. Check if the stream had been blocked due to oversize frame
                    if (meta.ingress_md.stream_filter.stream_blocked_due_to_oversize_frame_enable == 1w1 && meta.ingress_md.stream_filter.stream_blocked_due_to_oversize_frame == 1w1){
                        mark_to_drop(std_md);
                        // Drop the packet by setting the egress_spec to 0
                        meta.ingress_md.to_be_dropped = 1w1;

                        // Count the frame as missed due to oversize frame
                        missed_max_sdu_filter_counter.count((bit<32>) meta.ingress_md.stream_filter.stream_handle);

                    } else if (meta.ingress_md.stream_filter.active_stream_identification == 1w1) {
                        // Active stream identification is enabled
                        // 6. Overwrite the frame caractersitics with the stream based ones
                        stream_id_active.apply();
                    }
                }
            }
        }

        // Note : If there is a miss then the frame is forward without any traitement.
        // i.e the frame is not identified as a TSN stream frame since no stream_handle is assigned.
        // The stream don't have a vid conforming to the stream_id table.
    }
}
