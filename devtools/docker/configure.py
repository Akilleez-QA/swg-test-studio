#!/usr/bin/env python3
"""Render a private, single-cluster Docker topology and its matching cfg overlays.

No Docker actions or database changes are performed here. Generated files are
deployment inputs; a prepared 32-bit runtime image and runtime.cfg are required.
"""
import argparse
import ipaddress
import json
import pathlib
import re

from zones import available_zones, save_zones, select_zones, starting_zones

ROLES = {
    "login": "LoginServer", "taskmanager": "TaskManager",
    "central": "CentralServer", "connection": "ConnectionServer",
    "database": "SwgDatabaseServer", "planet": "PlanetServer",
    "game": "SwgGameServer", "chat": "ChatServer", "log": "LogServer",
    "metrics": "MetricsServer", "commodities": "CommoditiesServer",
}
NODES = [r for r in ROLES if r != "login"]
# Only these ports are published. Internal port zero listeners are discovered
# by the original protocol and can communicate directly across the bridge.
PUBLIC = {"login": [44453, 44460], "connection": [44463, 44462]}
TCP = {
    "login": [44452, 10666], "taskmanager": [60001, 50001],
    "central": [44451, 44454, 44455, 61232, 61242, 44456, 50001],
    "connection": [50001], "database": [44457, 50001],
    "planet": [50001], "game": [50001], "chat": [50001],
    "log": [44467, 50001], "metrics": [44480, 2200, 50001],
    "commodities": [4069, 50001],
    "oracle": [1521],
}


def cfg(sections):
    return "\n".join("[" + name + "]\n" + "\n".join(
        key + "=" + str(value) for key, value in pairs) + "\n"
        for name, pairs in sections)


def render(output, public_address, subnet="172.30.73.0/24", project="starwarsgalaxies",
           publish_address="0.0.0.0", zone_set=None, zones=None):
    zones = select_zones(output, zone_set=zone_set, zones=zones)
    public = ipaddress.IPv4Address(public_address)
    if public.is_unspecified or public.is_multicast:
        raise ValueError("public-address must be a client-reachable IPv4 address")
    ipaddress.IPv4Address(publish_address)
    network = ipaddress.IPv4Network(subnet)
    private_ranges = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    if network.prefixlen != 24 or not any(network.subnet_of(ipaddress.IPv4Network(r)) for r in private_ranges):
        raise ValueError("subnet must be an unused private IPv4 /24")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project):
        raise ValueError("project must be a lowercase Compose project name")
    output = pathlib.Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    # Keep Oracle on .19 for existing persistent deployments when adding roles.
    addresses = {role: str(network[10 + i])
                 for i, role in enumerate(r for r in ROLES if r not in ("metrics", "commodities"))}
    addresses["oracle"] = str(network[19])
    addresses["metrics"] = str(network[20])
    addresses["commodities"] = str(network[21])
    sections = [
        ("SharedNetwork", [("useTcp", 1), ("allowPortRemapping", 0)]),
        ("LoginServer", [("developmentMode", 1), ("clientServicePort", 44453),
                         ("pingServicePort", 44460), ("centralServicePort", 44452),
                         ("csToolPort", 10666)]),
        ("CentralServer", [("developmentMode", 1), ("newbieTutorialEnabled", 1),
                           ("loginServerAddress", "login"),
                           ("loginServerPort", 44452), ("taskManagerAddress", "taskmanager"),
                           ("taskManagerPort", 60001), ("gameServicePort", 44451),
                           ("connectionServicePort", 44454), ("planetServicePort", 44455),
                           ("chatServicePort", 61232), ("customerServicePort", 61242),
                           ("commodityServerServicePort", 44456),
                           ("consoleServiceBindInterface", "lo"),
                           ("dbServerHost", "node3"), ("chatServerHost", "node6"),
                           ("startConnectionServer", "node2:eth1:44463:44464"),
                           ("startPublic", 1), ("allowZeroConnectionServerPort", 0)] +
                          [("startPlanet", zone) for zone in zones] +
                          [(key + "ServiceBindInterface", "eth0") for key in
                           ("game", "connection", "planet", "chat", "customer", "commodityServer")]),
        ("ConnectionServer", [("centralServerAddress", "central"), ("centralServerPort", 44454),
                              ("clientServicePortPublic", 44463), ("clientServicePortPrivate", 44464),
                              ("clientServiceAdvertisedAddress", str(public)),
                              # CmdStartScene carries this flag to the client;
                              # true skips both snapshots and client buildouts.
                              ("disableWorldSnapshot", 0),
                              ("pingPort", 44462), ("startPublicServer", 1),
                              ("gameServicePort", 0)] +
                             [(key + "ServiceBindInterface", "eth0") for key in
                              ("game", "chat", "customer")]),
        ("dbProcess", [("centralServerAddress", "central"), ("centralServerPort", 44451),
                       ("gameServiceBindInterface", "eth0"), ("taskManagerPort", 60001),
                       ("commoditiesServerAddress", "eth0"), ("commoditiesServerPort", 44457)]),
        ("PlanetServer", [("centralServerAddress", "central"), ("centralServerPort", 44455),
                          ("sceneID", zones[0]),
                          ("loadWholePlanet", 1),
                          ("taskManagerPort", 60001), ("gameServicePort", 0),
                          ("gameServiceBindInterface", "eth0"), ("watcherServiceBindInterface", "eth0")]),
        ("GameServer", [("centralServerAddress", "central"), ("centralServerPort", 44451),
                        ("sceneID", zones[0]), ("groundScene", f"terrain/{zones[0]}.trn"),
                        ("reservedObjectIds", 1000000),
                        ("triggerVolumeSystem", 2),
                        # The original local cluster creates per-scene named objects.
                        # Falcon zone tables use this path to register available
                        # npe_space dungeon ships before tutorial travel is requested.
                        ("createZoneObjects", 1),
                        ("taskManagerPort", 60001),
                        ("commoditiesServerServiceBindInterface", "commodities"),
                        ("commoditiesServerServiceBindPort", 4069),
                        # The legacy SIGSEGV wrapper re-raises with pthread_kill,
                        # losing siginfo needed by HotSpot's safepoint handler.
                        # Leave the JVM's own handler installed.
                        ("trapScriptCrashes", 0),
                        ("javaLibPath", "/opt/whitengold/jvm/libjvm.so"), ("adminGodToAll", 0)]),
        ("ChatServer", [("centralServerAddress", "central"), ("centralServerPort", 61232),
                        ("gameServiceBindInterface", "eth0"), ("planetServiceBindInterface", "eth0")]),
        ("LogServer", [("logServicePort", 44467), ("logServiceBindInterface", "eth0")]),
        ("ServerMetrics", [("metricsServerAddress", "metrics"),
                            ("metricsServerPort", 44480)]),
        ("MetricsServer", [("clusterName", project),
                            ("metricsServicePort", 44480),
                            ("metricsListenerPort", 2200),
                            ("metricsServiceBindInterface", "eth0"),
                            ("taskManagerPort", 60001)]),
        ("CommodityServer", [("cmServerServiceBindPort", 4069),
                              ("cmServerServiceBindInterface", "eth0"),
                              ("databaseServerAddress", "database"),
                              ("databaseServerPort", 44457),
                              ("centralServerAddress", "central"),
                              ("centralServerPort", 44456)]),
    ]
    configs = output / "config"
    configs.mkdir(exist_ok=True)
    rc = "".join(f"{ROLES[role]} {addresses[role]} /opt/whitengold/launch-role {ROLES[role]} -- @/run/whitengold/runtime.cfg @/run/whitengold/container.cfg\n"
                 for role in NODES if role != "taskmanager")
    (configs / "taskmanager.rc").write_text(rc, encoding="utf-8")
    services = {}
    for role, binary in ROLES.items():
        task = [("useConfiguredProcessHosts", 1), ("autoStart", int(role == "taskmanager")),
                ("clusterName", project), ("verifyClusterName", 1),
                ("rcFileName", "/run/whitengold/taskmanager.rc"),
                ("loginServerAddress", "login"), ("taskManagerServicePort", 50001),
                ("taskManagerServiceBindInterface", "eth0"), ("gameServicePort", 60001),
                ("gameServiceBindInterface", "eth0" if role == "taskmanager" else "lo"),
                ("consoleConnectionPort", 60000), ("consoleServiceBindInterface", "lo")]
        task += [(f"node{i}", addresses[r]) for i, r in enumerate(NODES)]
        if role == "game":
            # Fixed role placement shares this host across all selected scenes.
            # TaskManager rejects spawns at (not just above) maximumLoad; each
            # GameServer costs 1.0 with the original defaults.
            task += [("maximumLoad", max(3, len(zones) + 1))]
        # Hostname equals the internal IP to avoid dual-NIC hostname ambiguity.
        role_sections = sections + [("TaskManager", task),
                                   ("CentralServer", [("clusterName", project)]),
                                   ("LogServer", [("clusterName", project)])]
        if role != "log":
            role_sections += [("SharedLog", [("logTarget", "net:log:44467")])]
        (configs / f"{role}.cfg").write_text(cfg(role_sections), encoding="utf-8")
        service = {
            "image": f"{project}/{role}:local", "pull_policy": "never",
            "build": {"context": str(pathlib.Path(__file__).resolve().parent),
                      "args": {"RUNTIME_IMAGE": "${WG_RUNTIME_IMAGE:?Set WG_RUNTIME_IMAGE to the prepared 32-bit runtime image}",
                               "ROLE": binary}},
            "hostname": addresses[role], "init": True,
            "restart": "no", "stop_grace_period": "60s",
            "networks": {"cluster": {"ipv4_address": addresses[role], "interface_name": "eth0",
                                     "aliases": [f"node{NODES.index(role)}"] if role in NODES else []}},
            "volumes": [f"{configs / (role + '.cfg')}:/run/whitengold/container.cfg:ro",
                        f"{configs / 'taskmanager.rc'}:/run/whitengold/taskmanager.rc:ro",
                        f"{output / 'runtime.cfg'}:/run/whitengold/runtime.cfg:ro",
                        f"{output / 'metricsAuthentication.cfg'}:/opt/whitengold/exe/linux/metricsAuthentication.cfg:ro"],
            "expose": [f"{port}/tcp" for port in TCP[role]],
        }
        if role in PUBLIC:
            service["networks"]["ingress"] = {"interface_name": "eth1", "gw_priority": 1}
            service["ports"] = [f"{publish_address}:{port}:{port}/udp" for port in PUBLIC[role]]
        services[role] = service
    services["oracle"] = {
        "image": "gvenzl/oracle-free:23.26.3-slim-faststart", "platform": "linux/amd64",
        "environment": {"ORACLE_PASSWORD_FILE": "/run/secrets/oracle_password"},
        "secrets": ["oracle_password"], "volumes": ["oracle_data:/opt/oracle/oradata"],
        "networks": {"cluster": {"ipv4_address": addresses["oracle"], "interface_name": "eth0"}},
        "expose": ["1521/tcp"], "restart": "no", "stop_grace_period": "120s",
    }
    # This is valid Compose YAML (JSON is a YAML subset), kept machine-readable
    # so validation does not need an additional YAML package.
    compose = {"name": project, "services": services,
               "networks": {"cluster": {"driver": "bridge", "internal": True,
                                        "ipam": {"config": [{"subnet": str(network)}]}},
                            "ingress": {"driver": "bridge"}},
               # Database storage outlives Compose, including `down --volumes`.
               # Provision it explicitly once; a missing volume must fail closed.
               "volumes": {"oracle_data": {"name": f"{project}_oracle26_data", "external": True}},
               "secrets": {"oracle_password": {"file": str(output / "oracle-password.txt")}}}
    (output / "compose.json").write_text(json.dumps(compose, indent=2) + "\n", encoding="utf-8")
    manifest = {"public_udp": PUBLIC, "internal_tcp": TCP, "addresses": addresses,
                "dynamic_tcp": ["connection", "database", "planet", "chat"]}
    (output / "ports.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    save_zones(output, zones)
    return compose


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(pathlib.Path(__file__).resolve().parents[2] / "StarWarsGalaxies"))
    parser.add_argument("--public-address")
    parser.add_argument("--publish-address", default="0.0.0.0")
    parser.add_argument("--subnet", default="172.30.73.0/24")
    parser.add_argument("--project", default="starwarsgalaxies")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--zone-set", choices=("tatooine", "live"),
                           help="replace saved selection with a preset")
    selection.add_argument("--zone", action="append", dest="zones",
                           help="exact starting list; repeat once per zone")
    selection.add_argument("--zones-file", type=pathlib.Path,
                           help="import zone=on/off toggles or a legacy one-zone-per-line list")
    parser.add_argument("--add-zone", action="append", default=[], help="add a zone to the selection; repeatable")
    parser.add_argument("--remove-zone", action="append", default=[], help="remove a selected zone; repeatable")
    parser.add_argument("--list-zones", action="store_true", help="list supported zone names without writing files")
    args = parser.parse_args()
    if args.list_zones:
        print("\n".join(available_zones()))
        parser.exit()
    if not args.public_address:
        parser.error("--public-address is required when generating a deployment")
    try:
        zones = select_zones(args.output, zone_set=args.zone_set, zones=args.zones,
                             zones_file=args.zones_file, add_zones=args.add_zone,
                             remove_zones=args.remove_zone)
        render(args.output, args.public_address, args.subnet, args.project, args.publish_address, zones=zones)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(f"Rendered {pathlib.Path(args.output).resolve()}/compose.json and cfg overlays.")
    print(f"Starting zones ({len(zones)}): {', '.join(zones)}")
    print(f"Selection saved in {pathlib.Path(args.output).resolve()}/zones.txt")
    print("Runtime image, sanitized runtime.cfg, Oracle password/schema, assets and JVM validation are required before startup.")
