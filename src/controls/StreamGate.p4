// StreamGate: Time-based gating for streams
control StreamGate(
    inout header_t hdr,
    inout metadata_t meta,
    inout standard_metadata_t std_md
) {
    // Holds the number of packets that passed the stream gate
    direct_counter(CounterType.packets_and_bytes) stream_gate_counter;

    // Holds the number of packets that did not pass the stream gate, counted based on the stream handle
    counter(__STREAM_ID_SIZE__, CounterType.packets) not_passed_gate_counter;

    // Holds the number of packets that did not pass the stream gate due to missed intervals
    // (i.e. the stream gate was closed)
    counter(__STREAM_ID_SIZE__, CounterType.packets) missed_interval_counter;

    // Register to hold the state of the stream gate (open/closed)
    // 1 means closed, 0 means open
    register<bit<1>>(__STREAM_GATE_SIZE__) reg_gate_blocked;

    // This register holds the octets per interval for each stream gate
    // Per interval: current remaining octets.
    register<bit<32>>(256) octets_per_interval;
    
    
    // This register holds (Per gate) last interval_identifier (initially 0 or invalid).
    register<bit<12>>(__STREAM_GATE_SIZE__) state_reset_octets;

    action set_gate_and_ipv(bit<1> gate_state, bit<4> ipv, bit<12> interval_identifier, bit<32> max_octects_interval) {
        meta.ingress_md.stream_gate.PSFPGateEnabled = gate_state;
        meta.ingress_md.stream_gate.ipv = ipv;
        meta.ingress_md.stream_gate.max_octects_interval = max_octects_interval;
        meta.ingress_md.stream_gate.interval_identifier = interval_identifier;
        

        // --- Ensure reset only at beginning of new interval ---
        bit<12> last_interval;
        state_reset_octets.read(last_interval, (bit<32>)meta.ingress_md.stream_filter.stream_gate_id);

        if (last_interval != interval_identifier) {
            // New interval → reset octet budget
            octets_per_interval.write((bit<32>)interval_identifier, max_octects_interval);
            state_reset_octets.write((bit<32>)meta.ingress_md.stream_filter.stream_gate_id, interval_identifier);
        }

        stream_gate_counter.count();
    }

    table stream_gate_instance {  
        key = {
            meta.ingress_md.stream_filter.stream_gate_id: exact;
            meta.ingress_md.diff_ts: range;
        }
        actions = {
            set_gate_and_ipv;
        }
        counters = stream_gate_counter;
        size = 256;
    }

    apply {
        // 1. First, check if the frame was not marked to drop by the stream filter
        if (meta.ingress_md.to_be_dropped != 1w1){
            // 2. check if the frame has a stream_gate_id assigned
            if (stream_gate_instance.apply().miss) {
                // No stream_gate_id assigned, so the frame does not belong to an identified stream
                // a. So mark the frame to drop
                mark_to_drop(std_md);
                // std_md.egress_spec = 0;
                meta.ingress_md.to_be_dropped = 1w1;

                // b. Count the frame as not passed for its flow type
                not_passed_gate_counter.count((bit<32>)meta.ingress_md.stream_filter.stream_handle);

                // c. Permanently block the gate if it was closed due to invalid rx
                if (meta.ingress_md.stream_gate.gate_closed_due_to_invalid_rx_enable == 1w1) {
                    
                    // Permanentlly close the gate because the frame does arrived in the wrong interval
                    reg_gate_blocked.write((bit<32>)meta.ingress_md.stream_filter.stream_gate_id, 1w1);
                }

            } else {
                // 3. Check that the gate was not permanentlly blocked
                // a. Get the state of the gate
                reg_gate_blocked.read(meta.ingress_md.stream_gate.gate_closed, (bit<32>)meta.ingress_md.stream_filter.stream_gate_id);
                // b. We need to check if the gate is permanentlly closed
                if (meta.ingress_md.stream_gate.gate_closed == 1w1) {
                    // The gate is permanentlly closed => So mark the frame to drop
                    mark_to_drop(std_md);
                    // std_md.egress_spec = 0;
                    meta.ingress_md.to_be_dropped = 1w1;
                    not_passed_gate_counter.count((bit<32>)meta.ingress_md.stream_filter.stream_handle);

                } else {
                    // 4. Check of the interval state is cloed or open
                    if (meta.ingress_md.stream_gate.PSFPGateEnabled == 1w1) {
                        // a. The gate is closed, so we need to drop the frame due to invalid rx 
                        mark_to_drop(std_md);
                        // std_md.egress_spec = 0;
                        meta.ingress_md.to_be_dropped = 1w1;

                        // Count the not passed frame for its flow type
                        missed_interval_counter.count((bit<32>)meta.ingress_md.stream_filter.stream_handle);

                        // Check of the gate cloused due to invalid rx is enabled => Permanently close the gate
                        if (meta.ingress_md.stream_gate.gate_closed_due_to_invalid_rx_enable == 1) {
                            reg_gate_blocked.write((bit<32>)meta.ingress_md.stream_filter.stream_gate_id, 1w1);
                        }

                    } else {
                        // b. The gate is open, so we need to decremente the octets and check if the octets exceeded
                        bit<32> remaining;
                        octets_per_interval.read(remaining, (bit<32>) meta.ingress_md.stream_gate.interval_identifier);
                        if (remaining >= std_md.packet_length) {
                            remaining = remaining - std_md.packet_length;
                            octets_per_interval.write((bit<32>)meta.ingress_md.stream_gate.interval_identifier, remaining);
                            meta.ingress_md.stream_gate.remaining_octets = remaining;
                        } else {
                            // The octets exceeded, so we need to drop the packet and close the gate if needed
                            mark_to_drop(std_md);
                            // std_md.egress_spec = 0;
                            meta.ingress_md.to_be_dropped = 1w1;

                            // Count the not passed frame for its flow type
                            not_passed_gate_counter.count((bit<32>)meta.ingress_md.stream_filter.stream_handle);

                            if (meta.ingress_md.stream_gate.gate_closed_due_to_octets_exceeded_enable == 1w1) {
                                // Close the gate due to octets exceeded
                                reg_gate_blocked.write((bit<32>)meta.ingress_md.stream_filter.stream_gate_id, 1w1);
                            }
                        }
                    }
                }
            }
        }
    }
}