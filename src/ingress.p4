#include "controls/IPv4.p4"

#include "controls/PSFP.p4"


control IngressImpl(
    inout header_t hdr,
    inout metadata_t meta,
    inout standard_metadata_t std_md
) {
    PSFP() psfp_c;

    IPv4() ipv4_c;

    
    apply {

        // Initialize the to_be_dropped field to 0
        meta.ingress_md.to_be_dropped = 1w0;

        if (hdr.eth_802_1q.isValid()){
            // Apply the PSFP control to handle PSFP-related processing
            psfp_c.apply(hdr, meta, std_md);
        }

        if (hdr.ipv4.isValid() && meta.ingress_md.to_be_dropped != 1w1) {
            ipv4_c.apply(hdr, meta, std_md);
        }
    }
}
