#!/usr/bin/env python
# Copyright 2012 Cisco Systems, Inc.
# Copyright 2022 Datto, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from oslo_log import log as logger
from neutron_lib.plugins.ml2 import api
from neutron_lib.db import api as db_api
from neutron.db import models_v2
import oslo_messaging
from oslo_config import cfg

# Setup logging
driver_logger = logger.getLogger(__name__)

# Setup RPC
transport = oslo_messaging.get_rpc_transport(cfg.CONF)
target = oslo_messaging.Target(topic="roth_agent", version="1.0")
client = oslo_messaging.RPCClient(transport, target)

# Get rw db session
session = db_api.get_writer_session()


def call_setup_tenant_vrf(
    context, client, bridge_id, vni, gateways, transit, host, segment_id,
    router_id, bgp_id, bgp_peer, router_networks
):
    driver_logger.info(
        """
        Call roth agent %s setup_tenant_vrf with:
        bridge_id %s,
        vni %s,
        gateways %s,
        transit %s,
        segment_id %s,
        router_id %s,
        bgp_id %s,
        bgp_peer %s,
        router_networks %s"""
        % (host, bridge_id, vni, gateways, transit, segment_id,
           router_id, bgp_id, bgp_peer, router_networks)
    )
    cctxt = client.prepare(server=host)
    return cctxt.call(
        context,
        "call_setup_tenant_vrf",
        bridge_id=bridge_id,
        vni=vni,
        gateways=gateways,
        transit=transit,
        segment_id=segment_id,
        router_id=router_id,
        bgp_id=bgp_id,
        bgp_peer=bgp_peer,
        router_networks=router_networks,
    )


def call_delete_tenant_vrf(context, client, segment_id):
    driver_logger.info(
        """
        Call roth agent delete_tenant_vrf for segment %s"""
        % segment_id
    )
    cctxt = client.prepare(fanout=True)
    return cctxt.cast(
        context,
        "call_delete_tenant_vrf",
        segment_id=segment_id,
    )


def get_network(session, network_id):
    network = session.query(models_v2.Network).filter_by(id=network_id).all()
    if network:
        return network[0].project_id, network[0].name
    else:
        return False, False


def get_segment(session, network_id):
    query = session.execute(
        'SELECT segmentation_id FROM networksegments WHERE network_id="%s"' % network_id
    )
    if query.rowcount != 1:
        return False
    else:
        try:
            (segmentation_id) = query.fetchall()[0]
            return segmentation_id["segmentation_id"]
        except IndexError:
            return False


def get_gateways(session, network_id):
    query = session.execute(
        'SELECT gateway_ip,cidr FROM subnets WHERE network_id="%s"' % network_id
    )
    if query.rowcount < 1:
        return False
    else:
        try:
            return [r.gateway_ip + "/" + r.cidr.split("/")[1] for r in query.fetchall()]
        except IndexError:
            return False


def get_transitsubnet(session, network_id):
    subnet = session.query(models_v2.Subnet).filter_by(network_id=network_id).all()
    if subnet:
        return subnet[0]
    else:
        return False


def get_transitroutes(session, subnet_id):
    query = session.execute(
        'SELECT destination,nexthop FROM subnetroutes WHERE subnet_id="%s"' % subnet_id
    )
    if query.rowcount != 1:
        return False, False
    else:
        try:
            (destination, nexthop) = query.fetchall()[0]
            return destination, nexthop
        except IndexError:
            return False, False


def get_router_id(session, port_id):
    query = session.execute(
        'SELECT router_id FROM routerports WHERE port_id="%s"' % port_id
    )
    if query.rowcount != 1:
        return False
    else:
        try:
            return query.fetchall()[0]["router_id"]
        except IndexError:
            return False


def get_router_gateway_info(session, router_id):
    # Determine the gateway port id for the router
    query = session.execute(
        'SELECT gw_port_id FROM routers WHERE id="%s"' % router_id
    )
    if query.rowcount < 1:
        return False
    else:
        try:
            gateway_port = query.fetchall()[0]["gw_port_id"]
        except IndexError:
            return False
    # Determine the IP address and subnet for the gateway port
    query = session.execute(
        'SELECT ip_address,subnet_id FROM ipallocations WHERE port_id="%s"' % gateway_port
    )
    if query.rowcount < 1:
        return False
    else:
        try:
            (ip_address, subnet_id) = query.fetchall()[0]
        except IndexError:
            return False
    # Confirm the subnet is part of a subnet pool
    query = session.execute(
        'SELECT subnetpool_id FROM subnets WHERE id="%s"' % subnet_id
    )
    if query.rowcount != 1:
        return False
    else:
        try:
            subnetpool_id = query.fetchall()[0]["subnetpool_id"]
        except IndexError:
            return False
    # Determine the address scope for the subnet pool
    query = session.execute(
        'SELECT address_scope_id FROM subnetpools WHERE id="%s"' % subnetpool_id
    )
    if query.rowcount != 1:
        return False
    else:
        try:
            address_scope_id = query.fetchall()[0]["address_scope_id"]
        except IndexError:
            return False
    # Confirm the address scope is shared
    query = session.execute(
        'SELECT id FROM addressscoperbacs WHERE object_id="%s" and action="access_as_shared"' % address_scope_id
    )
    if query.rowcount != 1:
        return False
    # Determine the gateway IP address for the subnet
    query = session.execute(
        'SELECT gateway_ip FROM subnets WHERE id="%s"' % subnet_id
    )
    if query.rowcount < 1:
        return False
    else:
        try:
            gateway_ip = query.fetchall()[0]["gateway_ip"]
        except IndexError:
            return False
    return {"router_ip": ip_address, "router_gw": gateway_ip, "router_scope": address_scope_id}


def get_router_networks(session, router_id, router_scope):
    cidrs = []
    query = session.execute(
        'SELECT port_id FROM routerports WHERE router_id="%s" AND port_type="network:ha_router_replicated_interface"' % router_id  # noqa
    )
    if query.rowcount < 1:
        return cidrs
    else:
        try:
            router_ports = query.fetchall()
        except IndexError:
            return False
    for router_port in router_ports:
        query = session.execute(
            'SELECT subnet_id FROM ipallocations WHERE port_id="%s"' % router_port[0]
        )
        if query.rowcount != 1:
            continue
        else:
            try:
                subnet_id = query.fetchall()[0]["subnet_id"]
            except IndexError:
                continue
        # Confirm the subnet has a cidr and is part of a subnet pool
        query = session.execute(
            'SELECT cidr,subnetpool_id FROM subnets WHERE id="%s"' % subnet_id
        )
        if query.rowcount != 1:
            continue
        else:
            try:
                (cidr, subnetpool_id) = query.fetchall()[0]
            except IndexError:
                continue
        # Confirm the subnet pool is part of an address scope
        query = session.execute(
            'SELECT address_scope_id FROM subnetpools WHERE id="%s"' % subnetpool_id
        )
        if query.rowcount != 1:
            continue
        else:
            try:
                address_scope_id = query.fetchall()[0]["address_scope_id"]
            except IndexError:
                continue
        # Confirm the address scope matches the provider network scope
        if address_scope_id != router_scope:
            continue
        cidrs.append(cidr)
    return cidrs


def get_vni(session, project_id):
    query = session.execute(
        'SELECT minimum FROM network_segment_ranges WHERE name="%s"' % project_id
    )
    if query.rowcount != 1:
        return False
    else:
        try:
            minimum = query.fetchall()[0]["minimum"]
            return minimum
        except IndexError:
            return False


def get_gw_port_vni_network(session, router_id):
    query = session.execute(
        'SELECT gw_port_id FROM routers WHERE id="%s"' % router_id
    )
    if query.rowcount < 1:
        return False
    else:
        try:
            gateway_port = query.fetchall()[0]["gw_port_id"]
        except IndexError:
            return False
    query = session.execute(
        'SELECT network_id FROM ports WHERE id="%s"' % gateway_port
    )
    if query.rowcount < 1:
        return False
    else:
        try:
            network_id = query.fetchall()[0]["network_id"]
        except IndexError:
            return False
    query = session.execute(
        'SELECT project_id FROM networks WHERE id="%s"' % network_id
    )
    if query.rowcount < 1:
        return False
    else:
        try:
            project_id = query.fetchall()[0]["project_id"]
        except IndexError:
            return False
    return get_vni(session, project_id), network_id


class RotHPortMechanismDriver(api.MechanismDriver):
    def initialize(self):
        driver_logger.info("Inside roth Port Mech Driver!")

    def update_port_postcommit(self, context):
        driver_logger.info("Do this upon post commit when updating a new port")
        driver_logger.info("ROTHPORT: %s", dir(context))
        driver_logger.info("ROTHPORT: update_port_postcommit: %s", context.current)

        # Do not run on DOWN ports
        if context.current["status"] in ["DOWN"]:
            driver_logger.info(
                "ROTHPORT: Detected port down state. No action taken."
            )
            return

        # Instantiate variables
        router_id = bgp_id = bgp_peer = router_networks = transit = network_id = False

        # Get the network name and project id
        try:
            network_pid, network_name = get_network(
                session, context.current["network_id"]
            )
            if not network_pid or not network_name:
                driver_logger.info(
                    "ROTHPORT: No network project_id or network name found"
                )
                return
            elif network_name.startswith("transit"):
                transit = True
        except Exception as e:
            driver_logger.error("ROTHPORT: Error fetching network details: %s" % e)
            return

        # Lookup the vni using the network_segment_ranges table.
        # Abort if no vni is found
        try:
            vni = get_vni(session, network_pid)
        except Exception as e:
            driver_logger.error("ROTHPORT: Error fetching vni: %s" % e)
            return
        if not vni:
            try:
                router_id = get_router_id(session, context.current["id"])
                if not router_id:
                    driver_logger.info(
                        "ROTHPORT: No vni or router_id found for port: %s" % context.current["id"]
                    )
                    return
            except Exception as e:
                driver_logger.error("ROTHPORT: Error fetching router_id in vni lookup: %s" % e)
                return
            try:
                vni, network_id = get_gw_port_vni_network(session, router_id)
                if not vni:
                    driver_logger.info(
                        "ROTHPORT: No vni associated with this port request: %s" % context.current["id"]
                    )
                    return
            except Exception as e:
                driver_logger.error("ROTHPORT: Error fetching vni for router gw_port_id: %s" % e)
                return

        # If this is not a router port, use the network_id
        # from the commit message
        if not network_id:
            network_id = context.current["network_id"]

        # Get the segment id for the network
        # Abort if the network does not have a segment_id
        try:
            segment_id = get_segment(
                session, network_id
            )
            if not segment_id:
                driver_logger.error("ROTHPORT: No segment_id found")
                return
        except Exception as e:
            driver_logger.error("ROTHPORT: Error fetching the segment_id: %s" % e)
            return

        # Get the gateway ips for the network
        # Abort if there are no gateway ips
        try:
            gateways = get_gateways(
                session, network_id
            )
            if not gateways:
                driver_logger.error(
                    "ROTHPORT: No gateways found for network: %s"
                    % network_id
                )
                return
        except Exception as e:
            driver_logger.error("ROTHPORT: Error fetching network gateways: %s" % e)
            return

        # Check for a transit subnet route if we are
        # handling a transit network
        if transit:
            try:
                transit_subnet = get_transitsubnet(
                    session, network_id
                )
                if not transit_subnet:
                    driver_logger.error(
                        "ROTHPORT: No subnet found for transit network: %s"
                        % network_id
                    )
                    return
                transit_dst, transit_nh = get_transitroutes(session, transit_subnet.id)
                if not transit_dst or not transit_nh:
                    driver_logger.error(
                        "ROTHPORT: Improper route configuration for transit subnet: %s"
                        % transit_subnet.id
                    )
                    return
                transit = {"destination": transit_dst, "nexthop": transit_nh}
            except Exception as e:
                driver_logger.error(
                    "ROTHPORT: Error fetching transit subnet routes: %s" % e
                )
                return

        # Check for a network router port
        if "router" in context.current["device_owner"] or router_id:
            try:
                if not router_id:
                    router_id = get_router_id(session, context.current["id"])
                    if not router_id:
                        driver_logger.error(
                            "ROTHPORT: No router_id found for port: %s" % context.current["id"]
                        )
                        return
            except Exception as e:
                driver_logger.error("ROTHPORT: Error fetching router id: %s" % e)
                return
            try:
                router_gateway_info = get_router_gateway_info(session, router_id)
                if not router_gateway_info:
                    driver_logger.error(
                        "ROTHPORT: The router is not fit for dynamic routing: %s" % router_id
                    )
                    return
                bgp_id = router_gateway_info["router_ip"]
                bgp_peer = router_gateway_info["router_gw"]
                router_scope = router_gateway_info["router_scope"]
            except Exception as e:
                driver_logger.error("ROTHPORT: Error fetching network gateway for router: %s" % e)
                return
            try:
                router_networks = get_router_networks(session, router_id, router_scope)
                if not isinstance(router_networks, list):
                    driver_logger.error(
                        "ROTHPORT: Error determining router ha replicated interfaces: %s" % router_id
                    )
                    return
            except Exception as e:
                driver_logger.error("ROTHPORT: Error fetching tenant cidrs for router: %s" % e)
                return

        # Call setup_tenant_vrf via roth_agent
        try:
            bridge_id = "brq" + network_id[0:11]
            result = call_setup_tenant_vrf(
                context.current,
                client,
                bridge_id,
                vni,
                gateways,
                transit,
                context.current["binding:host_id"],
                segment_id,
                router_id,
                bgp_id,
                bgp_peer,
                router_networks,
            )
            driver_logger.info("ROTHPORT: Result: %s", result)
        except Exception as e:
            driver_logger.error(
                "ROTHPORT: Error in setup_tenant_vrf rpc call: %s", e
            )

    def delete_network_precommit(self, context):
        driver_logger.info("Do this upon pre commit when deleting a network")
        driver_logger.info("ROTHPORT: %s", dir(context))
        driver_logger.info("ROTHPORT: delete_network_precommit: %s", context.current)
        try:
            segment_id = get_segment(
                session, context.current["id"]
            )
            if not segment_id:
                driver_logger.error("ROTHPORT: No segment_id found")
                return
        except Exception as e:
            driver_logger.error("ROTHPORT: Error fetching the segment_id: %s" % e)
            return

        try:
            call_delete_tenant_vrf(
                context.current,
                client,
                segment_id,
            )
        except Exception as e:
            driver_logger.error(
                "ROTHPORT: Error in delete_tenant_vrf rpc call: %s", e
            )


class RotHMechanismDriver(RotHPortMechanismDriver):
    def initialize(self):
        driver_logger.info("Inside roth Mech Driver!")
