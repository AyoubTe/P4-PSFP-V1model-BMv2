control EgressImpl(
    inout header_t hdr,
    inout metadata_t meta,
    inout standard_metadata_t standard_metadata
) {
    
    apply {
        /* 
        // Egress control plane implementation
        // Nothing to do here, just pass the packet through
        // Because there is no recirculation from egress to ingress needed
        // The packet will be sent to the egress port directly
        */
    }
}
