#include "StreamFilter.p4"
#include "StreamGate.p4"
#include "FlowMeter.p4"

// PSFP: Per-Stream Filtering and Policing (TSN/802.1Qci)
control PSFP(
    inout header_t hdr,
    inout metadata_t meta,
    inout standard_metadata_t std_md
) {
    // Register to hold the hyperperiod duration
    // Populated by the control plane
    register<bit<48>>(__STREAM_ID_SIZE__) hyperperiod_duration_reg;

    // Register to hold the last hyperperiod timestamp
    // Populated by the control plane
    register<bit<48>>(__STREAM_ID_SIZE__) last_hyperperiod_reg;

    // Register to indicate if a hyperperiod is done or not
    // 1 means done, 0 means not done
    // Populated by the control plane
    register<bit<1>>(__STREAM_ID_SIZE__) hyperperiod_done_reg;

    @noWarn("unused")
    // Register to hold the period count
    // This register is used to count the number of periods of stream's hyperperiod
    register<bit<32>>(__STREAM_ID_SIZE__) period_count; // Counts the number of periods

    // @noWarn("unused")
    // register<bit<64>>(__STREAM_ID_SIZE__) delta_adjustment_reg; // Ajustement Δ pour la synchronisation temporelle

    @noWarn("unused")
    // Calcule la position relative dans l'hyperpériode avec gestion des débordements
    action calc_diff_ts(){
        /*
        Calculates the relative position in the hyperperiod by subtracting ingress ts from hyperperiod ts
        */
        // Gestion de l’underflow
        if ((bit<64>)std_md.ingress_global_timestamp > MAXIMUM_48_BIT_TS) {
            meta.ingress_md.diff_ts = MAXIMUM_48_BIT_TS - (bit<64>)meta.last_hyperperiod + (bit<64>)std_md.ingress_global_timestamp;
            meta.last_hyperperiod = meta.last_hyperperiod + meta.hyperperiod.hyperperiod_ts;
        } else {
            // Calcul de la position relative dans l’hyperpériode
            meta.ingress_md.diff_ts = (bit<64>)(std_md.ingress_global_timestamp - meta.last_hyperperiod);
        }

        // Applique l'ajustement Δ pour la synchronisation
        // meta.ingress_md.diff_ts = (meta.ingress_md.diff_ts + meta.delta) % meta.hyperperiod.hyperperiod_ts;
    }

    // Action: push hyperperiod state into metadata (no registers)
    action set_hyperperiod_state(bit<32> gate_id, bit<48> hyperperiod_ts, bit<48> last_hyperperiod) {
        meta.hyperperiod.hyperperiod_ts = hyperperiod_ts;
        hyperperiod_duration_reg.write(gate_id, hyperperiod_ts);  // Set the hyperperiod duration in the register
        meta.last_hyperperiod           = last_hyperperiod;
        last_hyperperiod_reg.write(gate_id, last_hyperperiod);  // Set the last hyperperiod in the register
    }

    table hyperperiod_state {
        key = {
            meta.ingress_md.stream_filter.stream_gate_id : exact;
        }
        actions = { set_hyperperiod_state; }
        size = __STREAM_ID_SIZE__;
    }


    StreamFilter() streamFilter_c;
    StreamGate() streamGate_c;
    FlowMeter() flowMeter_c;

    apply {
        // Do PSFP processing directly
        // No need to recirculate packet to get the length
        // 1. Stream identification and filtering
        streamFilter_c.apply(hdr, meta, std_md);

        // Load hyperperiod state from table (control-plane managed)
        hyperperiod_state.apply();

        // Set the hyperperiod timestamp and last hyperperiod timestamp in metadata
        // This is done before applying the stream gate and flow meter controls

        // Set the ingress timestamp in the metadata
        meta.ingress_ts = std_md.ingress_global_timestamp;

        // Set the hyperperiod timestamp in the metadata
        hyperperiod_duration_reg.read(meta.hyperperiod.hyperperiod_ts, (bit<32>)meta.ingress_md.stream_filter.stream_gate_id);

        // Set the last hyperperiod timestamp in the metadata
        last_hyperperiod_reg.read(meta.last_hyperperiod, (bit<32>)meta.ingress_md.stream_filter.stream_gate_id);

        // delta_adjustment_reg.read(meta.delta, index);

        // Chech if the ingress timestamp of the actual frame is greater than the last hyperperiod timestamp plus the hyperperiod duration
        // => This means that a new hyperperiod has started
        if (std_md.ingress_global_timestamp > (meta.last_hyperperiod + meta.hyperperiod.hyperperiod_ts)) {
            // set hyperperiod as done
            hyperperiod_done_reg.write((bit<32>)meta.ingress_md.stream_filter.stream_gate_id, 1);

            // Reset the packet count for the hyperperiod
            meta.hyperperiod.pkt_count_hyperperiod = 0;
            hyperperiod_done_reg.write((bit<32>)meta.ingress_md.stream_filter.stream_gate_id, 0);  // Reset flag

            // Send digest to the control plane to handle hyperperiod done
            digest<digest_finished_hyperperiod_t>( (bit<32>)0, {  // receiver=0 pour CP
                meta.ingress_md.stream_filter.stream_gate_id,  // ID gate
                meta.ingress_ts,  // Current TS
                meta.hyperperiod.hyperperiod_ts,  // Durée
                meta.last_hyperperiod  // Ancien last
            });

        } else {
            // Hyperperiod not done, continue processing
            
            // Calculate the diff_ts
            meta.ingress_md.diff_ts = (bit<64>)meta.ingress_ts - (bit<64>)meta.last_hyperperiod;

            // 2. Stream gating (time-based admission)
            streamGate_c.apply(hdr, meta, std_md);

            // 3. Flow metering (bandwidth policing)
            flowMeter_c.apply(hdr, meta, std_md);
        } 
    }
}