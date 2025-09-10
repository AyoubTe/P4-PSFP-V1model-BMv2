// SPDX-License-Identifier: Apache-2.0
/* -*- P4_16 -*- */

#include <core.p4>
#include <v1model.p4>

#include "src/headers.p4"
#include "src/parser.p4"
#include "src/ingress.p4"
#include "src/egress.p4"
#include "src/checksum.p4"

// Instantiate the V1model pipeline
V1Switch(
    ParserImpl(),
    VerifyChecksumImpl(), 
    IngressImpl(), 
    EgressImpl(),
    ComputeChecksumImpl(), 
    DeparserImpl()
) main;
