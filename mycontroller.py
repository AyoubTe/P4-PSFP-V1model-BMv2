#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

import argparse
import os
import sys
from time import sleep
import threading  # Ajout pour thread stream

import grpc
from google.protobuf import text_format

# Import P4Runtime lib from parent utils dir
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../utils/'))

import p4runtime_lib.bmv2
import p4runtime_lib.helper
from p4runtime_lib.error_utils import printGrpcError
from p4runtime_lib.switch import ShutdownAllSwitchConnections

from p4.v1 import p4runtime_pb2

from datetime import datetime

def configure_meter(p4info_helper, sw, meter_name, index, cir, cburst, pir, pburst):
    meter_entry = p4runtime_pb2.MeterEntry()
    meter_entry.meter_id = p4info_helper.get_meters_id(meter_name)
    meter_entry.index.index = index

    # CIR/PIR in bytes per second, burst in bytes
    meter_entry.config.cir = cir
    meter_entry.config.cburst = cburst
    meter_entry.config.pir = pir
    meter_entry.config.pburst = pburst

    request = p4runtime_pb2.WriteRequest()
    request.device_id = sw.device_id
    request.election_id.low = 1  # or your controller election ID

    update = request.updates.add()
    update.type = p4runtime_pb2.Update.INSERT
    update.entity.meter_entry.CopyFrom(meter_entry)

    try:
        sw.client_stub.Write(request)
        print(f"Installed meter {meter_name} at index {index}")
    except grpc.RpcError as e:
        print(f"Error installing meter {meter_name}: {e}")

def configure_direct_meter(sw, p4info_helper, meter_name, index, cir, cburst, pir, pburst):
    """
    Configure a direct_meter attached to a table entry by index.
    """

    try:
        meter_id = p4info_helper.get_meters_id(meter_name)
    except Exception as e:
        print(f"Erreur récupération meter_id pour {meter_name} : {e}")
        return
    
    meter_entry = p4runtime_pb2.MeterEntry()
    meter_entry.meter_id = meter_id
    meter_entry.index.index = index

    # Define meter bands (CIR/CBS and PIR/PBS)
    meter_entry.config.cir = cir         # Committed Information Rate (bytes/sec)
    meter_entry.config.cburst = cburst   # Committed Burst Size (bytes)
    meter_entry.config.pir = pir         # Peak Information Rate (bytes/sec)
    meter_entry.config.pburst = pburst   # Peak Burst Size (bytes)

    request = p4runtime_pb2.WriteRequest()
    request.device_id = sw.device_id
    request.election_id.low = 1  # The primary controller

    update = request.updates.add()
    update.type = p4runtime_pb2.Update.INSERT
    update.entity.meter_entry.CopyFrom(meter_entry)

    try:
        sw.client_stub.Write(request)
        print(f"Mise à jour du meter index {index} réussie.")
    except grpc.RpcError as e:
        print(f"Erreur d’écriture du meter index {index} : {e}")

def read_meter(p4info_helper, sw, meter_name, index):
    meter_id = p4info_helper.get_meters_id(meter_name)
    for response in sw.ReadMeterEntries(meter_id, index):
        print(response)


def writeTableRules(p4info_helper, sw):
    """
    Installs table entries from s1-runtime.json for the sdn-psfp.p4 program.

    :param p4info_helper: the P4Info helper
    :param sw: the switch connection
    """
    # Table entries from s1-runtime.json
    table_entries = [
        # Default action for ipv4_c.ipv4
        {
            "table": "IngressImpl.ipv4_c.ipv4",
            "default_action": True,
            "action_name": "IngressImpl.ipv4_c.drop",
            "action_params": {}
        },
        # IPv4 forwarding rule for 10.0.1.1
        {
            "table": "IngressImpl.ipv4_c.ipv4",
            "match": {
                "hdr.ipv4.dstAddr": ["10.0.1.1", 32]
            },
            "action_name": "IngressImpl.ipv4_c.ipv4_forward",
            "action_params": {
                "eth_dst_addr": "08:00:00:00:01:11",
                "port": 1
            }
        },
        # IPv4 forwarding rule for 10.0.2.2
        {
            "table": "IngressImpl.ipv4_c.ipv4",
            "match": {
                "hdr.ipv4.dstAddr": ["10.0.2.2", 32]
            },
            "action_name": "IngressImpl.ipv4_c.ipv4_forward",
            "action_params": {
                "eth_dst_addr": "08:00:00:00:02:22",
                "port": 2
            }
        },
        ############################### Stream ID rules ###############################
        # Assigning stream handles based on Ethernet destination address and VLAN ID
        ## Voice stream (stream_handle 1)
        {
            "table": "IngressImpl.psfp_c.streamFilter_c.stream_id",
            "match": {
                "hdr.ethernet.dst_addr": "08:00:00:00:02:22",
                "hdr.eth_802_1q.vid": 1
            },
            "action_name": "IngressImpl.psfp_c.streamFilter_c.assign_stream_handle",
            "action_params": {
                "stream_handle": 1,
                "active": 1,
                "stream_blocked_due_to_oversize_frame_enable": 0
            }
        },
        ## Video stream (stream_handle 2)
        {
            "table": "IngressImpl.psfp_c.streamFilter_c.stream_id",
            "match": {
                "hdr.ethernet.dst_addr": "08:00:00:00:02:22",
                "hdr.eth_802_1q.vid": 2
            },
            "action_name": "IngressImpl.psfp_c.streamFilter_c.assign_stream_handle",
            "action_params": {
                "stream_handle": 2,
                "active": 1, # Stream identification is active
                "stream_blocked_due_to_oversize_frame_enable": 0
            }
        },
        ## Data (Text) stream (stream_handle 3)
        {
            "table": "IngressImpl.psfp_c.streamFilter_c.stream_id",
            "match": {
                "hdr.ethernet.dst_addr": "08:00:00:00:02:22",
                "hdr.eth_802_1q.vid": 3
            },
            "action_name": "IngressImpl.psfp_c.streamFilter_c.assign_stream_handle",
            "action_params": {
                "stream_handle": 3,
                "active": 0,  # Stream identification is inactive
                "stream_blocked_due_to_oversize_frame_enable": 1
            }
        },
        ## Streaming service Stream (stream_handle 4)
        {
            "table": "IngressImpl.psfp_c.streamFilter_c.stream_id",
            "match": {
                "hdr.ethernet.dst_addr": "08:00:00:00:01:11",
                "hdr.eth_802_1q.vid": 4
            },
            "action_name": "IngressImpl.psfp_c.streamFilter_c.assign_stream_handle",
            "action_params": {
                "stream_handle": 4,
                "active": 1,
                "stream_blocked_due_to_oversize_frame_enable": 0
            }
        },
        ## Varied Services Stream (stream_handle 5)
        {
            "table": "IngressImpl.psfp_c.streamFilter_c.stream_id",
            "match": {
                "hdr.ethernet.dst_addr": "08:00:00:00:01:11",
                "hdr.eth_802_1q.vid": 5
            },
            "action_name": "IngressImpl.psfp_c.streamFilter_c.assign_stream_handle",
            "action_params": {
                "stream_handle": 5,
                "active": 0,  # Stream identification is inactive
                "stream_blocked_due_to_oversize_frame_enable": 1
            }
        },
        ############################### Stream filter instance rules ###############################
        # Assigning stream gates and flow meters based on stream handles
        # Stream handle 1 (Audio)
        {
            "table": "IngressImpl.psfp_c.streamFilter_c.stream_filter_instance",
            "match": {
                "meta.ingress_md.stream_filter.stream_handle": 1
            },
            "action_name": "IngressImpl.psfp_c.streamFilter_c.assign_gate_and_meter",
            "action_params": {
                "stream_gate_id": 1,
                "flow_meter_instance_id": 1,
                "gate_closed_due_to_invalid_rx_enable": 1,
                "gate_closed_due_to_octets_exceeded_enable": 1
            }
        },
        # Stream handle 2 (Video)
        {
            "table": "IngressImpl.psfp_c.streamFilter_c.stream_filter_instance",
            "match": {
                "meta.ingress_md.stream_filter.stream_handle": 2
            },
            "action_name": "IngressImpl.psfp_c.streamFilter_c.assign_gate_and_meter",
            "action_params": {
                "stream_gate_id": 2,
                "flow_meter_instance_id": 2,
                "gate_closed_due_to_invalid_rx_enable": 1,
                "gate_closed_due_to_octets_exceeded_enable": 0
            }
        },
        # Stream handle 3 (Data/Text)
        {
            "table": "IngressImpl.psfp_c.streamFilter_c.stream_filter_instance",
            "match": {
                "meta.ingress_md.stream_filter.stream_handle": 3
            },
            "action_name": "IngressImpl.psfp_c.streamFilter_c.assign_gate_and_meter",
            "action_params": {
                "stream_gate_id": 3,
                "flow_meter_instance_id": 1,
                "gate_closed_due_to_invalid_rx_enable": 0,
                "gate_closed_due_to_octets_exceeded_enable": 1
            }
        },
        # Stream handle 4 (Streaming service)
        {
            "table": "IngressImpl.psfp_c.streamFilter_c.stream_filter_instance",
            "match": {
                "meta.ingress_md.stream_filter.stream_handle": 4
            },
            "action_name": "IngressImpl.psfp_c.streamFilter_c.assign_gate_and_meter",
            "action_params": {
                "stream_gate_id": 4,
                "flow_meter_instance_id": 2,
                "gate_closed_due_to_invalid_rx_enable": 0,
                "gate_closed_due_to_octets_exceeded_enable": 0
            }
        },
        # Stream handle 5 (Varied services)
        {
            "table": "IngressImpl.psfp_c.streamFilter_c.stream_filter_instance",
            "match": {
                "meta.ingress_md.stream_filter.stream_handle": 5
            },
            "action_name": "IngressImpl.psfp_c.streamFilter_c.assign_gate_and_meter",
            "action_params": {
                "stream_gate_id": 1,
                "flow_meter_instance_id": 1,
                "gate_closed_due_to_invalid_rx_enable": 1,
                "gate_closed_due_to_octets_exceeded_enable": 1
            }
        },
        ############################# Stream ID active rules #############################
        # Audio stream (stream_handle 1)
        {
            "table": "IngressImpl.psfp_c.streamFilter_c.stream_id_active",
            "match": {
                "meta.ingress_md.stream_filter.stream_handle": 1
            },
            "action_name": "IngressImpl.psfp_c.streamFilter_c.overwrite_stream_active",
            "action_params": {
                "eth_dst_addr": "08:00:00:00:02:22",
                "vid": 1,
                "pcp": 5
            }
        },
        # Video stream (stream_handle 2)
        {
            "table": "IngressImpl.psfp_c.streamFilter_c.stream_id_active",
            "match": {
                "meta.ingress_md.stream_filter.stream_handle": 2
            },
            "action_name": "IngressImpl.psfp_c.streamFilter_c.overwrite_stream_active",
            "action_params": {
                "eth_dst_addr": "08:00:00:00:02:22",
                "vid": 2,
                "pcp": 4
            }
        },
        # Data (Text) stream (stream_handle 3)
        {
            "table": "IngressImpl.psfp_c.streamFilter_c.stream_id_active",
            "match": {
                "meta.ingress_md.stream_filter.stream_handle": 3
            },
            "action_name": "IngressImpl.psfp_c.streamFilter_c.overwrite_stream_active",
            "action_params": {
                "eth_dst_addr": "08:00:00:00:02:22",
                "vid": 3,
                "pcp": 0
            }
        },
        # Streaming service Stream (stream_handle 4)
        {
            "table": "IngressImpl.psfp_c.streamFilter_c.stream_id_active",
            "match": {
                "meta.ingress_md.stream_filter.stream_handle": 4
            },
            "action_name": "IngressImpl.psfp_c.streamFilter_c.overwrite_stream_active",
            "action_params": {
                "eth_dst_addr": "08:00:00:00:01:11",
                "vid": 4,
                "pcp": 3
            }
        },
        # Varied Services Stream (stream_handle 5)
        {
            "table": "IngressImpl.psfp_c.streamFilter_c.stream_id_active",
            "match": {
                "meta.ingress_md.stream_filter.stream_handle": 5
            },
            "action_name": "IngressImpl.psfp_c.streamFilter_c.overwrite_stream_active",
            "action_params": {
                "eth_dst_addr": "08:00:00:00:01:11",
                "vid": 5,
                "pcp": 2
            }
        },
        ############################# Max SDU filter rules (TERNARY and RANGE) #############################
        {
            "table": "IngressImpl.psfp_c.streamFilter_c.max_sdu_filter",
            "match": {
                "meta.ingress_md.stream_filter.stream_handle": 1,
                "hdr.eth_802_1q.pcp": (5, 0x7),  # TERNARY: value, mask # PCP 5 for video
                "std_md.packet_length": (1, 1500)  # RANGE: min, max
            },
            "action_name": "IngressImpl.psfp_c.streamFilter_c.none",
            "action_params": {},
            "priority": 100
        },
        {
            "table": "IngressImpl.psfp_c.streamFilter_c.max_sdu_filter",
            "match": {
                "meta.ingress_md.stream_filter.stream_handle": 2,
                "hdr.eth_802_1q.pcp": (4, 0x7), # PCP 4 for video
                "std_md.packet_length": (1, 1400)
            },
            "action_name": "IngressImpl.psfp_c.streamFilter_c.none",
            "action_params": {},
            "priority": 99
        },
        {
            "table": "IngressImpl.psfp_c.streamFilter_c.max_sdu_filter",
            "match": {
                "meta.ingress_md.stream_filter.stream_handle": 3,
                "hdr.eth_802_1q.pcp": (0, 0x7), # PCP 0 for data (text)
                "std_md.packet_length": (1, 1250)
            },
            "action_name": "IngressImpl.psfp_c.streamFilter_c.none",
            "action_params": {},
            "priority": 98
        },
        {
            "table": "IngressImpl.psfp_c.streamFilter_c.max_sdu_filter",
            "match": {
                "meta.ingress_md.stream_filter.stream_handle": 4,
                "hdr.eth_802_1q.pcp": (3, 0x7), # PCP 3 for streaming service
                "std_md.packet_length": (1, 1490)
            },
            "action_name": "IngressImpl.psfp_c.streamFilter_c.none",
            "action_params": {},
            "priority": 97
        },
        {
            "table": "IngressImpl.psfp_c.streamFilter_c.max_sdu_filter",
            "match": {
                "meta.ingress_md.stream_filter.stream_handle": 5,
                "hdr.eth_802_1q.pcp": (2, 0x7), # PCP 2 for varied services
                "std_md.packet_length": (1, 1500)
            },
            "action_name": "IngressImpl.psfp_c.streamFilter_c.none",
            "action_params": {},
            "priority": 96
        },
        ############################# Stream gate instance rules #############################
        # Assigning inetrval specifications to the frame based on stream gate ID and time difference (arrival time relative to the hyperperiod)
        # Interval 1 for stream gate ID 1 ([0, 2000000 (microseconds)])
        {
            "table": "IngressImpl.psfp_c.streamGate_c.stream_gate_instance",
            "match": {
                "meta.ingress_md.stream_filter.stream_gate_id": 1,
                "meta.ingress_md.diff_ts": (0, 2000000) # RANGE: min, max
            },
            "action_name": "IngressImpl.psfp_c.streamGate_c.set_gate_and_ipv",
            "action_params": {
                "gate_state": 0,
                "ipv": 2,
                "interval_identifier": 1,
                "max_octects_interval": 180000
            },
            "priority": 99
        },
        # Interval 2 for stream gate ID 1 ([2000000, 8000000 (microseconds)])
        {
            "table": "IngressImpl.psfp_c.streamGate_c.stream_gate_instance",
            "match": {
                "meta.ingress_md.stream_filter.stream_gate_id": 1,
                "meta.ingress_md.diff_ts": (2000000, 8000000)  # RANGE: min, max , Time in microseconds
            },
            "action_name": "IngressImpl.psfp_c.streamGate_c.set_gate_and_ipv",
            "action_params": {
                "gate_state": 1,
                "ipv": 2,
                "interval_identifier": 2,
                "max_octects_interval": 0
            },
            "priority": 98
        },
        # Interval 3 for stream gate ID 1 ([8000000, 16000000 (microseconds)])
        {
            "table": "IngressImpl.psfp_c.streamGate_c.stream_gate_instance",
            "match": {
                "meta.ingress_md.stream_filter.stream_gate_id": 1,
                "meta.ingress_md.diff_ts": (8000000, 16000000)  # RANGE: min, max
            },
            "action_name": "IngressImpl.psfp_c.streamGate_c.set_gate_and_ipv",
            "action_params": {
                "gate_state": 0,
                "ipv": 2,
                "interval_identifier": 3,
                "max_octects_interval": 300000
            },
            "priority": 97
        },
        # Interval 4 for stream gate ID 1 ([16000000, 20000000 (microseconds)])
        {
            "table": "IngressImpl.psfp_c.streamGate_c.stream_gate_instance",
            "match": {
                "meta.ingress_md.stream_filter.stream_gate_id": 1,
                "meta.ingress_md.diff_ts": (16000000, 20000000)
            },
            "action_name": "IngressImpl.psfp_c.streamGate_c.set_gate_and_ipv",
            "action_params": {
                "gate_state": 1,
                "ipv": 2,
                "interval_identifier": 4,
                "max_octects_interval": 0
            },
            "priority": 96
        },
        # Interval 1 for stream gate ID 2 ([0, 6000000 (microseconds)])
        {
            "table": "IngressImpl.psfp_c.streamGate_c.stream_gate_instance",
            "match": {
                "meta.ingress_md.stream_filter.stream_gate_id": 2,
                "meta.ingress_md.diff_ts": (0, 6000000)  # RANGE: min, max
            },
            "action_name": "IngressImpl.psfp_c.streamGate_c.set_gate_and_ipv",
            "action_params": {
                "gate_state": 0,
                "ipv": 9,
                "interval_identifier": 1,
                "max_octects_interval": 55000
            },
            "priority": 100
        },
        # Interval 2 for stream gate ID 2 ([6000000, 10000000 (microseconds)])
        {
            "table": "IngressImpl.psfp_c.streamGate_c.stream_gate_instance",
            "match": {
                "meta.ingress_md.stream_filter.stream_gate_id": 2,
                "meta.ingress_md.diff_ts": (6000000, 10000000)  # RANGE: min, max
            },
            "action_name": "IngressImpl.psfp_c.streamGate_c.set_gate_and_ipv",
            "action_params": {
                "gate_state": 1,
                "ipv": 9,
                "interval_identifier": 2,
                "max_octects_interval": 0
            },
            "priority": 99
        },
        # Interval 3 for stream gate ID 2 ([10000000, 16000000 (microseconds)])
        {
            "table": "IngressImpl.psfp_c.streamGate_c.stream_gate_instance",
            "match": {
                "meta.ingress_md.stream_filter.stream_gate_id": 2,
                "meta.ingress_md.diff_ts": (10000000, 16000000)  # RANGE: min, max
            },
            "action_name": "IngressImpl.psfp_c.streamGate_c.set_gate_and_ipv",
            "action_params": {
                "gate_state": 0,
                "ipv": 9,
                "interval_identifier": 3,
                "max_octects_interval": 150000
            },
            "priority": 98
        },
        # Interval 1 for stream gate ID 3 ([0, 2000000 (microseconds)])
        {
            "table": "IngressImpl.psfp_c.streamGate_c.stream_gate_instance",
            "match": {
                "meta.ingress_md.stream_filter.stream_gate_id": 3,
                "meta.ingress_md.diff_ts": (0, 2000000)
            },
            "action_name": "IngressImpl.psfp_c.streamGate_c.set_gate_and_ipv",
            "action_params": {
                "gate_state": 1,
                "ipv": 12,
                "interval_identifier": 1,
                "max_octects_interval": 0
            },
            "priority": 99
        },
        # Interval 2 for stream gate ID 3 ([2000000, 12000000 (microseconds)])
        {
            "table": "IngressImpl.psfp_c.streamGate_c.stream_gate_instance",
            "match": {
                "meta.ingress_md.stream_filter.stream_gate_id": 3,
                "meta.ingress_md.diff_ts": (2000000, 12000000)  # RANGE: min, max
            },
            "action_name": "IngressImpl.psfp_c.streamGate_c.set_gate_and_ipv",
            "action_params": {
                "gate_state": 0,
                "ipv": 12,
                "interval_identifier": 2,
                "max_octects_interval": 40000
            },
            "priority": 98
        },
        # Interval 3 for stream gate ID 3 ([12000000, 14000000 (microseconds)])
        {
            "table": "IngressImpl.psfp_c.streamGate_c.stream_gate_instance",
            "match": {
                "meta.ingress_md.stream_filter.stream_gate_id": 3,
                "meta.ingress_md.diff_ts": (12000000, 14000000)  # RANGE: min, max
            },
            "action_name": "IngressImpl.psfp_c.streamGate_c.set_gate_and_ipv",
            "action_params": {
                "gate_state": 1,
                "ipv": 12,
                "interval_identifier": 3,
                "max_octects_interval": 0
            },
            "priority": 97
        },
        # Interval 4 for stream gate ID 3 ([14000000, 18000000 (microseconds)])
        {
            "table": "IngressImpl.psfp_c.streamGate_c.stream_gate_instance",
            "match": {
                "meta.ingress_md.stream_filter.stream_gate_id": 3,
                "meta.ingress_md.diff_ts": (14000000, 18000000)  # RANGE: min, max
            },
            "action_name": "IngressImpl.psfp_c.streamGate_c.set_gate_and_ipv",
            "action_params": {
                "gate_state": 0,
                "ipv": 12,
                "interval_identifier": 4,
                "max_octects_interval": 260000
            },
            "priority": 96
        },
        # Interval 5 for stream gate ID 3 ([18000000, 22000000 (microseconds)])
        {
            "table": "IngressImpl.psfp_c.streamGate_c.stream_gate_instance",
            "match": {
                "meta.ingress_md.stream_filter.stream_gate_id": 3,
                "meta.ingress_md.diff_ts": (18000000, 22000000)  # RANGE: min, max
            },
            "action_name": "IngressImpl.psfp_c.streamGate_c.set_gate_and_ipv",
            "action_params": {
                "gate_state": 1,
                "ipv": 12,
                "interval_identifier": 5,
                "max_octects_interval": 0
            },
            "priority": 95
        },
        # Interval 1 for stream gate ID 4 ([0, 10000000 (microseconds)])
        {
            "table": "IngressImpl.psfp_c.streamGate_c.stream_gate_instance",
            "match": {
                "meta.ingress_md.stream_filter.stream_gate_id": 4,
                "meta.ingress_md.diff_ts": (0, 10000000)  # RANGE: min, max
            },
            "action_name": "IngressImpl.psfp_c.streamGate_c.set_gate_and_ipv",
            "action_params": {
                "gate_state": 0,
                "ipv": 12,
                "interval_identifier": 1,
                "max_octects_interval": 100000
            },
            "priority": 101
        },
        # Interval 2 for stream gate ID 4 ([10000000, 20000000 (microseconds)])
        {
            "table": "IngressImpl.psfp_c.streamGate_c.stream_gate_instance",
            "match": {
                "meta.ingress_md.stream_filter.stream_gate_id": 4,
                "meta.ingress_md.diff_ts": (10000000, 20000000)  # RANGE: min, max
            },
            "action_name": "IngressImpl.psfp_c.streamGate_c.set_gate_and_ipv",
            "action_params": {
                "gate_state": 1,
                "ipv": 12,
                "interval_identifier": 2,
                "max_octects_interval": 0
            },
            "priority": 100
        },
        ############################# Flow meter config rules #############################
        # Assigning flow meter configurations based on flow meter instance IDs
        # Flow meter instance ID 1
        {
            "table": "IngressImpl.psfp_c.flowMeter_c.flow_meter_config",
            "match": {
                "meta.ingress_md.stream_filter.flow_meter_instance_id": 1
            },
            "action_name": "IngressImpl.psfp_c.flowMeter_c.set_flow_meter_config",
            "action_params": {
                "dropOnYellow": 1,
                "markAllFramesRedEnable": 1,
                "colorAware": 1
            }
        },
        # Flow meter instance ID 2
        {
            "table": "IngressImpl.psfp_c.flowMeter_c.flow_meter_config",
            "match": {
                "meta.ingress_md.stream_filter.flow_meter_instance_id": 2
            },
            "action_name": "IngressImpl.psfp_c.flowMeter_c.set_flow_meter_config",
            "action_params": {
                "dropOnYellow": 1,
                "markAllFramesRedEnable": 0,
                "colorAware": 1
            }
        },
        ############################# Flow meter instance rules #############################
        # Applying flow meter instances coloring based on stream filter instance IDs
        # Flow meter instance ID 1 (used by stream handle 1, 3 and 5)
        {
            "table": "IngressImpl.psfp_c.flowMeter_c.flow_meter_instance",
            "match": {
                "meta.ingress_md.stream_filter.flow_meter_instance_id": 1
            },
            "action_name": "IngressImpl.psfp_c.flowMeter_c.set_color_direct",
            "action_params": {}
        },
        # Flow meter instance ID 2 (used by stream handle 2 and 4)
        {
            "table": "IngressImpl.psfp_c.flowMeter_c.flow_meter_instance",
            "match": {
                "meta.ingress_md.stream_filter.flow_meter_instance_id": 2
            },
            "action_name": "IngressImpl.psfp_c.flowMeter_c.set_color_direct",
            "action_params": {}
        }
    ]

    for entry in table_entries:
        table_entry = p4info_helper.buildTableEntry(
            table_name=entry["table"],
            match_fields=entry.get("match", {}),
            default_action=entry.get("default_action", False),
            action_name=entry["action_name"],
            action_params=entry["action_params"],
            priority=entry.get("priority")
        )
        sw.WriteTableEntry(table_entry)
        print(f"Installed rule on {sw.name} for table {entry['table']}")

def get_register_width(p4info_helper, register_name):
    try:
        reg = next(r for r in p4info_helper.p4info.registers if r.preamble.name == register_name)
    except StopIteration:
        raise Exception(f"Register {register_name} not found in p4info")
    
    if reg.type_spec.HasField("bitstring") and reg.type_spec.bitstring.HasField("bit"):
        return reg.type_spec.bitstring.bit.bitwidth
    else:
        raise Exception(f"Register {register_name} has unknown bitwidth in p4info")


def write_register(sw, p4info_helper, register_name, index, value):
    request = p4runtime_pb2.WriteRequest()
    request.device_id = sw.device_id
    request.election_id.low = 1

    # Resolve register and width from P4Info
    try:
        reg = next(r for r in p4info_helper.p4info.registers if r.preamble.name == register_name)
    except StopIteration:
        print(f"[REG WRITE] Register {register_name} not found in p4info")
        return

    reg_id = reg.preamble.id
    # Default to bitstring.bit bitwidth if present; otherwise keep your fallbacks
    if reg.type_spec.HasField('bitstring') and reg.type_spec.bitstring.HasField('bit'):
        bitwidth = reg.type_spec.bitstring.bit.bitwidth
    else:
        if register_name.endswith("hyperperiod_duration_reg") or register_name.endswith("last_hyperperiod_reg"):
            bitwidth = 48
        elif register_name.endswith("hyperperiod_done_reg"):
            bitwidth = 1
        else:
            print(f"[REG WRITE] Unknown bitwidth for {register_name}; please define in P4.")
            return

    # Mask value down to bitwidth to avoid OverflowError
    if bitwidth < 64:
        mask = (1 << bitwidth) - 1
        if value >> bitwidth:
            # Informative warning so you notice truncation
            print(f"[REG WRITE] Warning: truncating value {value} to {bitwidth} bits for {register_name}[{index}]")
        value &= mask

    # Build update
    update = request.updates.add()
    update.type = p4runtime_pb2.Update.MODIFY   # MODIFY is the canonical op for registers
    entry = update.entity.register_entry
    entry.register_id = reg_id
    entry.index.index = index

    try:
        entry.data.bitstring = value.to_bytes((bitwidth + 7) // 8, byteorder='big')
    except OverflowError as e:
        print(f"[REG WRITE] OverflowError for {register_name}[{index}] (width {bitwidth}): {e}")
        return

    try:
        sw.client_stub.Write(request)
        print(f"[REG WRITE] {register_name}[{index}] = {value} (0x{value:x}) width={bitwidth}")
    except grpc.RpcError as e:
        print(f"[REG WRITE] Failed {register_name}[{index}]: {e}")


def upsert_hyperperiod_state(sw, p4info_helper, gate_id, hyperperiod_us, last_us):
    """
    Insert-or-modify the hyperperiod_state table for a given stream gate.
    Stores values in microseconds (switch timebase).
    """
    te = p4info_helper.buildTableEntry(
        table_name="IngressImpl.psfp_c.hyperperiod_state",
        match_fields={"meta.ingress_md.stream_filter.stream_gate_id": gate_id},
        action_name="IngressImpl.psfp_c.set_hyperperiod_state",
        action_params={
            "gate_id": gate_id,
            "hyperperiod_ts": hyperperiod_us,
            "last_hyperperiod": last_us
        }
    )

    req = p4runtime_pb2.WriteRequest()
    req.device_id = sw.device_id
    req.election_id.low = 1
    up = req.updates.add()
    up.type = p4runtime_pb2.Update.MODIFY  # MODIFY works for insert-or-replace on BMv2
    up.entity.table_entry.CopyFrom(te)

    try:
        sw.client_stub.Write(req)
        print(f"[HP STATE] gate {gate_id}: hyperperiod={hyperperiod_us}µs last={last_us}µs")
    except grpc.RpcError as e:
        print(f"[HP STATE] Failed to upsert for gate {gate_id}: {e}")


def program_hyperperiods(sw, p4info_helper):
    """
    Program initial hyperperiod state in SECONDS (converted to µs here).
    """
    SECONDS_TO_US = 1_000_000
    ts_us = int(datetime.now().timestamp() * SECONDS_TO_US) & ((1 << 48) - 1)

    # Configure in SECONDS (nice & readable)
    configs_seconds = {
        1: 20,   # Stream Gate 1: 20 seconds
        2: 16,    # Stream Gate 2: 16 seconds
        3: 26,   # Stream Gate 3: 23 seconds
        4: 20    # Stream Gate 4: 20 seconds
    }

    for gate_id, secs in configs_seconds.items():
        upsert_hyperperiod_state(sw, p4info_helper, gate_id, secs * SECONDS_TO_US, ts_us)

"""
def populate_hyperperiod_registers(sw, p4info_helper):

    SECONDS_TO_US = 1_000_000

    # Current time in microseconds (masked to 48 bits)
    ts_micro = int(datetime.now().timestamp() * SECONDS_TO_US)
    ts_micro &= (1 << 48) - 1

    configs = {
        1: 20,   # Stream Gate 1: 20 seconds
        2: 16,    # Stream Gate 2: 16 seconds
        3: 26,   # Stream Gate 3: 23 seconds
        4: 20    # Stream Gate 4: 20 seconds
    }

    for gate_id, secs in configs.items():
        duration_us = secs * SECONDS_TO_US
        write_register(sw, p4info_helper, "IngressImpl.psfp_c.hyperperiod_duration_reg", gate_id, duration_us)
        write_register(sw, p4info_helper, "IngressImpl.psfp_c.last_hyperperiod_reg", gate_id, ts_micro)
        write_register(sw, p4info_helper, "IngressImpl.psfp_c.hyperperiod_done_reg", gate_id, 0)
"""
def writeRegisters(p4info_helper, sw):
    """
    Writes to registers for hyperperiod configuration.

    :param sw: the switch connection
    :param p4info_helper: the P4Info helper
    """
    # Populate hyperperiod configuration registers
    program_hyperperiods(sw, p4info_helper)
    

def readTableRules(p4info_helper, sw):
    """
    Reads the table entries from all tables on the switch.

    :param p4info_helper: the P4Info helper
    :param sw: the switch connection
    """
    print(f'\n----- Reading tables rules for {sw.name} -----')
    for response in sw.ReadTableEntries():
        for entity in response.entities:
            entry = entity.table_entry
            print(entry)
            print('-----')

def printCounter(p4info_helper, sw, counter_name, index):
    """
    Reads the specified counter at the specified index from the switch.

    :param p4info_helper: the P4Info helper
    :param sw: the switch connection
    :param counter_name: the name of the counter from the P4 program
    :param index: the counter index
    """
    for response in sw.ReadCounters(p4info_helper.get_counters_id(counter_name), index):
        for entity in response.entities:
            counter = entity.counter_entry
            print(f"{sw.name} {counter_name} {index}: {counter.data.packet_count} packets ({counter.data.byte_count} bytes)")

def read_direct_counters(p4info_helper, sw, table_name):
    """
    Lit tous les compteurs directs associés à une table donnée.

    :param p4info_helper: objet helper P4Info
    :param sw: connexion au switch
    :param table_name: nom de la table avec compteur direct (ex: IngressImpl.psfp_c.streamFilter_c.stream_id)
    """

    #     print(f"Erreur lecture direct counter: {e}")
    table_id = p4info_helper.get_tables_id(table_name)
    request = p4runtime_pb2.ReadRequest()
    request.device_id = sw.device_id
    entity = request.entities.add()
    entity.table_entry.table_id = table_id
    try:
        for response in sw.client_stub.Read(request):
            for entity in response.entities:
                entry = entity.table_entry
                # print(f"Raw entry: {entry}")  # Debug: Print raw entry
                if hasattr(entry, 'direct_counter_entry') and entry.direct_counter_entry and entry.direct_counter_entry.data:
                    packet_count = entry.direct_counter_entry.data.packet_count
                    byte_count = entry.direct_counter_entry.data.byte_count
                    print(f"Entry match: {entry.match}")
                    print(f"   => {packet_count} packets, {byte_count} bytes")
                else:
                    print(f"No direct counter for entry: {entry.match}")
    except grpc.RpcError as e:
        print(f"Error reading direct counter: {e}")

def handle_stream(s1, p4info_helper):
    print("Initialisation du StreamChannel")
    def stream_requests():
        request = p4runtime_pb2.StreamMessageRequest()
        request.arbitration.device_id = s1.device_id
        request.arbitration.election_id.high = 0
        request.arbitration.election_id.low = 1
        yield request
        while True:
            yield p4runtime_pb2.StreamMessageRequest()  # Keep stream alive
            sleep(1)

    stream_channel = s1.client_stub.StreamChannel(stream_requests())
    print("Arbitration initiale envoyée")
    try:
        for response in stream_channel:
            if response.HasField('arbitration'):
                print("Arbitration response:", response.arbitration.status)
            elif response.HasField('digest'):
                print(f"Raw digest: {response.digest}")
                digest_list = response.digest
                print(f"Reçu digest ID: {digest_list.digest_id}")
                digest_id = p4info_helper.get_digests_id("digest_finished_hyperperiod_t")
                if digest_list.digest_id != digest_id:
                    print(f"Digest ID {digest_list.digest_id} inconnu, attendu {digest_id}")
                    continue
                for digest_data in digest_list.list.digests:
                    struct_members = digest_data.struct.members
                    print(f"Struct members: {len(struct_members)} fields")
                    try:
                        stream_gate_id = int.from_bytes(
                            next(f.bitstring for f in struct_members if f.field_id == p4info_helper.get_member_id("digest_finished_hyperperiod_t", "stream_gate_id")),
                            'big'
                        )
                        ingress_ts = int.from_bytes(
                            next(f.bitstring for f in struct_members if f.field_id == p4info_helper.get_member_id("digest_finished_hyperperiod_t", "ingress_ts")),
                            'big'
                        )
                        hyperperiod_ts = int.from_bytes(
                            next(f.bitstring for f in struct_members if f.field_id == p4info_helper.get_member_id("digest_finished_hyperperiod_t", "hyperperiod_ts")),
                            'big'
                        )
                        last_hyperperiod = int.from_bytes(
                            next(f.bitstring for f in struct_members if f.field_id == p4info_helper.get_member_id("digest_finished_hyperperiod_t", "last_hyperperiod")),
                            'big'
                        )
                        print(f"Digest data: gate_id={stream_gate_id}, ingress_ts={ingress_ts}, hyperperiod_ts={hyperperiod_ts}, last={last_hyperperiod}")
                        new_last = last_hyperperiod + hyperperiod_ts
                        write_register(s1, p4info_helper, "IngressImpl.psfp_c.last_hyperperiod_reg", stream_gate_id, new_last)
                        write_register(s1, p4info_helper, "IngressImpl.psfp_c.period_count", stream_gate_id, 0)
                        write_register(s1, p4info_helper, "IngressImpl.psfp_c.hyperperiod_done_reg", stream_gate_id, 0)
                        ack = p4runtime_pb2.StreamMessageRequest()
                        ack.digest_ack.digest_id = digest_list.digest_id
                        ack.digest_ack.list_id = digest_list.list.list_id
                        yield ack
                        print("Digest ack envoyé")
                    except Exception as e:
                        print(f"Erreur traitement digest: {e}")
            else:
                print("Message stream inconnu:", response)
    except grpc.RpcError as e:
        printGrpcError(e)

# Point d'entrée principal du script
def main(p4info_file_path, bmv2_file_path):
    # Instantiate a P4Runtime helper from the p4info file
    p4info_helper = p4runtime_lib.helper.P4InfoHelper(p4info_file_path)

    try:
        # Create a switch connection object for s1
        s1 = p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name='s1',
            address='127.0.0.1:50051',
            device_id=0,
            proto_dump_file='logs/s1-p4runtime-requests.txt')

        # Send master arbitration update message
        s1.MasterArbitrationUpdate()
        print("Established as master controller for s1")

        # Install the P4 program on the switch
        s1.SetForwardingPipelineConfig(p4info=p4info_helper.p4info,
                                      bmv2_json_file_path=bmv2_file_path)
        print("Installed P4 Program using SetForwardingPipelineConfig on s1")

        # Configure the meter
        # configure_meter(
        #    p4info_helper, s1,
        #    "IngressImpl.psfp_c.flowMeter_c.flow_meter",
        #    index=1,
        #    cir=100000, cburst=8000,  # CIR 100 kbps, CBS 8 KB
        #    pir=200000, pburst=16000  # PIR 200 kbps, PBS 16 KB
        #)

        # Configure Direct Meter
        configure_direct_meter(
            s1, p4info_helper,
            "IngressImpl.psfp_c.flowMeter_c.flow_meter",
            index=1, cir=100000, 
            cburst=4096, 
            pir=200000, pburst=8192
        )

        # Write table rules
        writeTableRules(p4info_helper, s1)

        # Write register values
        writeRegisters(p4info_helper, s1)

        # Read table entries
        readTableRules(p4info_helper, s1)

        # Lancer thread stream
        stream_thread = threading.Thread(target=handle_stream, args=(s1, p4info_helper))
        stream_thread.daemon = True
        stream_thread.start()
        print("Thread stream pour digests lancé")

        # Read counters periodically
        while True:
            sleep(10)
            # print('\n----- Reading direct counters -----')
            # read_direct_counters(p4info_helper, s1, "IngressImpl.ipv4_c.ipv4")
            # read_direct_counters(p4info_helper, s1, "IngressImpl.psfp_c.streamFilter_c.stream_id")
            # read_direct_counters(p4info_helper, s1, "IngressImpl.psfp_c.flowMeter_c.flow_meter_instance")
            

            print('\n----- Reading counters -----')
            for counter_name in [
                "IngressImpl.psfp_c.streamFilter_c.overall_counter",
                "IngressImpl.psfp_c.streamFilter_c.missed_max_sdu_filter_counter",
                "IngressImpl.psfp_c.streamGate_c.not_passed_gate_counter",
                "IngressImpl.psfp_c.flowMeter_c.marked_red_counter",
                "IngressImpl.psfp_c.flowMeter_c.marked_yellow_counter",
                "IngressImpl.psfp_c.flowMeter_c.marked_green_counter"
            ]:
                printCounter(p4info_helper, s1, counter_name, 0)

    except KeyboardInterrupt:
        print(" Shutting down.")
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='P4Runtime Controller for sdn-psfp')
    parser.add_argument('--p4info', help='p4info proto in text format from p4c',
                        type=str, action="store", required=False,
                        default='./build/sdn-psfp.p4.p4info.txtpb')
    parser.add_argument('--bmv2-json', help='BMv2 JSON file from p4c',
                        type=str, action="store", required=False,
                        default='./build/sdn-psfp.json')
    args = parser.parse_args()

    if not os.path.exists(args.p4info):
        parser.print_help()
        print(f"\np4info file not found: {args.p4info}\nHave you run 'make'?")
        parser.exit(1)
    if not os.path.exists(args.bmv2_json):
        parser.print_help()
        print(f"\nBMv2 JSON file not found: {args.bmv2_json}\nHave you run 'make'?")
        parser.exit(1)
    main(args.p4info, args.bmv2_json)