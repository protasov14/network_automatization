import os
import json
import re
import subprocess
from flask import Flask, render_template, request

app = Flask(__name__)

# Шляхи до Ansible-проєкту
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SWITCHES_DIR = os.path.join(BASE_DIR, "switches")
SWITCHES_PLAYBOOK = os.path.join(SWITCHES_DIR, "playbooks", "switches_config.yml")

ROUTERS_DIR = os.path.join(BASE_DIR, "routers")
ROUTERS_PLAYBOOK = os.path.join(ROUTERS_DIR, "playbooks", "routers_config.yml")


@app.route("/")
def index():
    return render_template("index.html")


# ====================== КОМУТАТОРИ (пер-комутаторні конфіги) ======================
@app.route("/switches", methods=["GET", "POST"])
def switches():
    output = None
    error = None

    if request.method == "POST":
        # Знаходимо всі індекси комутаторів: switch_0_*, switch_1_* ...
        indices = set()
        for key in request.form.keys():
            m = re.match(r"switch_(\d+)_", key)
            if m:
                indices.add(int(m.group(1)))
        indices = sorted(indices)

        if not indices:
            error = "Потрібно додати хоча б один комутатор."
            return render_template("switches.html", output=None, error=error)

        switches_data = []

        for idx in indices:
            prefix = f"switch_{idx}_"

            # IP цього комутатора
            device_ip = (request.form.get(prefix + "ip") or "").strip()
            if not device_ip:
                continue

            # Паролі та банер
            enable_secret = (request.form.get(prefix + "enable_secret") or "").strip()
            console_password = (request.form.get(prefix + "console_password") or "").strip()
            banner_login = (request.form.get(prefix + "banner_login") or "").strip()
            remote_access = (request.form.get(prefix + "remote_access") or "").strip() or None

            # VLAN-и
            vlan_ids = request.form.getlist(prefix + "vlan_id")
            vlan_names = request.form.getlist(prefix + "vlan_name")
            vlans = []
            for vid, vname in zip(vlan_ids, vlan_names):
                vid = (vid or "").strip()
                vname = (vname or "").strip()
                if not vid:
                    continue
                if not vname:
                    vname = f"VLAN_{vid}"
                vlans.append({"id": vid, "name": vname})

            # Access-порти
            access_ifs = request.form.getlist(prefix + "access_if")
            access_vlans = request.form.getlist(prefix + "access_vlan")
            access_ports = []
            for iface, vlan in zip(access_ifs, access_vlans):
                iface = (iface or "").strip()
                vlan = (vlan or "").strip()
                if not iface or not vlan:
                    continue
                access_ports.append({"interface": iface, "vlan": vlan})

            # Trunk-порти
            trunk_ifs = request.form.getlist(prefix + "trunk_if")
            trunk_vlans = request.form.getlist(prefix + "trunk_vlans")
            trunk_ports = []
            for iface, vlans_str in zip(trunk_ifs, trunk_vlans):
                iface = (iface or "").strip()
                vlans_str = (vlans_str or "").strip()
                if not iface or not vlans_str:
                    continue
                trunk_ports.append({"interface": iface, "vlans": vlans_str})

            # Користувачі
            user_names = request.form.getlist(prefix + "user_name")
            user_privs = request.form.getlist(prefix + "user_privilege")
            user_secrets = request.form.getlist(prefix + "user_secret")
            users = []
            for uname, priv, sec in zip(user_names, user_privs, user_secrets):
                uname = (uname or "").strip()
                sec = (sec or "").strip()
                priv = (priv or "").strip()
                if not uname or not sec:
                    continue
                if not priv:
                    priv = "15"
                users.append({"username": uname, "privilege": priv, "secret": sec})

            switches_data.append(
                {
                    "ip": device_ip,
                    "enable_secret": enable_secret or None,
                    "console_password": console_password or None,
                    "banner_login": banner_login or None,
                    "remote_access": remote_access,
                    "vlans": vlans,
                    "access_ports": access_ports,
                    "trunk_ports": trunk_ports,
                    "users": users,
                }
            )

        if not switches_data:
            error = "У всіх картках комутаторів порожні IP-адреси."
            return render_template("switches.html", output=None, error=error)

        combined_outputs = []
        errors = []

        env = os.environ.copy()
        env["ANSIBLE_HOST_KEY_CHECKING"] = "False"

        # Запускаємо плейбук окремо для кожного комутатора
        for sw in switches_data:
            ip = sw["ip"]

            extra_vars = {
                "ansible_connection": "network_cli",
                "ansible_network_os": "cisco.ios.ios",
                "ansible_user": "ansible",
                "ansible_password": "ansible",
                "ansible_become": True,
                "ansible_become_method": "enable",
                "ansible_become_password": "cisco",

                "enable_secret": sw["enable_secret"],
                "console_password": sw["console_password"],
                "banner_login": sw["banner_login"],
                "remote_access": sw["remote_access"],

                "vlans": sw["vlans"],
                "access_ports": sw["access_ports"],
                "trunk_ports": sw["trunk_ports"],
                "users": sw["users"],
            }

            try:
                cmd = [
                    "ansible-playbook",
                    SWITCHES_PLAYBOOK,
                    "-i",
                    f"{ip},",
                    "-e",
                    json.dumps(extra_vars),
                ]

                result = subprocess.run(
                    cmd,
                    cwd=SWITCHES_DIR,
                    capture_output=True,
                    text=True,
                    env=env,
                )

                header = f"===== SWITCH {ip} =====\n"
                combined_outputs.append(header + result.stdout)

                if result.returncode != 0:
                    err_text = result.stderr or "Playbook exited with non-zero return code"
                    errors.append(f"[{ip}] {err_text}")

            except Exception as e:
                errors.append(f"[{ip}] Error while running playbook: {e}")

        output = "\n\n".join(combined_outputs) if combined_outputs else None
        error = "\n".join(errors) if errors else None

    return render_template("switches.html", output=output, error=error)


# ====================== МАРШРУТИЗАТОРИ (як раніше) ======================
@app.route("/routers", methods=["GET", "POST"])
def routers():
    output = None
    error = None

    if request.method == "POST":
        indices = set()
        for key in request.form.keys():
            m = re.match(r"router_(\d+)_", key)
            if m:
                indices.add(int(m.group(1)))
        indices = sorted(indices)

        if not indices:
            error = "Потрібно додати хоча б один маршрутизатор."
            return render_template("routers.html", output=None, error=error)

        routers_data = []

        for idx in indices:
            prefix = f"router_{idx}_"

            device_ip = (request.form.get(prefix + "ip") or "").strip()
            if not device_ip:
                continue

            enable_secret = (request.form.get(prefix + "enable_secret") or "").strip()
            console_password = (request.form.get(prefix + "console_password") or "").strip()
            banner_login = (request.form.get(prefix + "banner_login") or "").strip()
            remote_access = (request.form.get(prefix + "remote_access") or "").strip() or None

            if_names = request.form.getlist(prefix + "if_name")
            if_ips = request.form.getlist(prefix + "if_ip")
            if_masks = request.form.getlist(prefix + "if_mask")
            interfaces = []
            for name, ip, mask in zip(if_names, if_ips, if_masks):
                name = (name or "").strip()
                ip = (ip or "").strip()
                mask = (mask or "").strip()
                if not name or not ip or not mask:
                    continue
                interfaces.append({"name": name, "ip": ip, "netmask": mask})

            dhcp_names = request.form.getlist(prefix + "dhcp_name")
            dhcp_networks = request.form.getlist(prefix + "dhcp_network")
            dhcp_masks = request.form.getlist(prefix + "dhcp_mask")
            dhcp_gateways = request.form.getlist(prefix + "dhcp_gateway")
            dhcp_dns_list = request.form.getlist(prefix + "dhcp_dns")
            dhcp_pools = []
            for name, net, mask, gw, dns in zip(
                dhcp_names, dhcp_networks, dhcp_masks, dhcp_gateways, dhcp_dns_list
            ):
                name = (name or "").strip()
                net = (net or "").strip()
                mask = (mask or "").strip()
                gw = (gw or "").strip()
                dns = (dns or "").strip()
                if not name or not net or not mask or not gw:
                    continue
                if not dns:
                    dns = gw
                dhcp_pools.append(
                    {
                        "name": name,
                        "network": net,
                        "mask": mask,
                        "gateway": gw,
                        "dns_server": dns,
                    }
                )

            static_dests = request.form.getlist(prefix + "static_dest")
            static_masks = request.form.getlist(prefix + "static_mask")
            static_next_hops = request.form.getlist(prefix + "static_next_hop")
            static_routes = []
            for dest, mask, nh in zip(static_dests, static_masks, static_next_hops):
                dest = (dest or "").strip()
                mask = (mask or "").strip()
                nh = (nh or "").strip()
                if not dest or not mask or not nh:
                    continue
                static_routes.append({"dest": dest, "mask": mask, "next_hop": nh})

            dynamic_protocol = (request.form.get(prefix + "dynamic_protocol") or "").strip() or None

            dyn_nets = request.form.getlist(prefix + "dyn_net")
            dyn_wildcards = request.form.getlist(prefix + "dyn_wildcard")
            dyn_areas = request.form.getlist(prefix + "dyn_area")
            dynamic_networks = []
            for net, wc, area in zip(dyn_nets, dyn_wildcards, dyn_areas):
                net = (net or "").strip()
                wc = (wc or "").strip()
                area = (area or "").strip()
                if not net or not wc:
                    continue
                dynamic_networks.append({"network": net, "wildcard": wc, "area": area})

            ospf_process_id = (request.form.get(prefix + "ospf_process_id") or "").strip()
            ospf_router_id = (request.form.get(prefix + "ospf_router_id") or "").strip()

            eigrp_as = (request.form.get(prefix + "eigrp_as") or "").strip()

            bgp_as = (request.form.get(prefix + "bgp_as") or "").strip()
            bgp_neighbor_ip = (request.form.get(prefix + "bgp_neighbor_ip") or "").strip()
            bgp_neighbor_remote_as = (request.form.get(prefix + "bgp_neighbor_remote_as") or "").strip()

            user_names = request.form.getlist(prefix + "user_name")
            user_privs = request.form.getlist(prefix + "user_privilege")
            user_secrets = request.form.getlist(prefix + "user_secret")
            users = []
            for uname, priv, sec in zip(user_names, user_privs, user_secrets):
                uname = (uname or "").strip()
                sec = (sec or "").strip()
                priv = (priv or "").strip()
                if not uname or not sec:
                    continue
                if not priv:
                    priv = "15"
                users.append({"username": uname, "privilege": priv, "secret": sec})

            routers_data.append(
                {
                    "ip": device_ip,
                    "enable_secret": enable_secret or None,
                    "console_password": console_password or None,
                    "banner_login": banner_login or None,
                    "remote_access": remote_access,
                    "interfaces": interfaces,
                    "dhcp_pools": dhcp_pools,
                    "static_routes": static_routes,
                    "dynamic_protocol": dynamic_protocol,
                    "dynamic_networks": dynamic_networks,
                    "ospf_process_id": ospf_process_id or None,
                    "ospf_router_id": ospf_router_id or None,
                    "eigrp_as": eigrp_as or None,
                    "bgp_as": bgp_as or None,
                    "bgp_neighbor_ip": bgp_neighbor_ip or None,
                    "bgp_neighbor_remote_as": bgp_neighbor_remote_as or None,
                    "users": users,
                }
            )

        if not routers_data:
            error = "У всіх картках маршрутизаторів порожні IP-адреси."
            return render_template("routers.html", output=None, error=error)

        combined_outputs = []
        errors = []

        env = os.environ.copy()
        env["ANSIBLE_HOST_KEY_CHECKING"] = "False"

        for r in routers_data:
            ip = r["ip"]

            extra_vars = {
                "ansible_connection": "network_cli",
                "ansible_network_os": "cisco.ios.ios",
                "ansible_user": "ansible",
                "ansible_password": "ansible",
                "ansible_become": True,
                "ansible_become_method": "enable",
                "ansible_become_password": "cisco",

                "enable_secret": r["enable_secret"],
                "console_password": r["console_password"],
                "banner_login": r["banner_login"],
                "remote_access": r["remote_access"],

                "interfaces": r["interfaces"],
                "dhcp_pools": r["dhcp_pools"],
                "static_routes": r["static_routes"],

                "dynamic_protocol": r["dynamic_protocol"],
                "dynamic_networks": r["dynamic_networks"],
                "ospf_process_id": r["ospf_process_id"],
                "ospf_router_id": r["ospf_router_id"],
                "eigrp_as": r["eigrp_as"],
                "bgp_as": r["bgp_as"],
                "bgp_neighbor_ip": r["bgp_neighbor_ip"],
                "bgp_neighbor_remote_as": r["bgp_neighbor_remote_as"],

                "users": r["users"],
            }

            try:
                cmd = [
                    "ansible-playbook",
                    ROUTERS_PLAYBOOK,
                    "-i",
                    f"{ip},",
                    "-e",
                    json.dumps(extra_vars),
                ]

                result = subprocess.run(
                    cmd,
                    cwd=ROUTERS_DIR,
                    capture_output=True,
                    text=True,
                    env=env,
                )

                header = f"===== ROUTER {ip} =====\n"
                combined_outputs.append(header + result.stdout)

                if result.returncode != 0:
                    err_text = result.stderr or "Playbook exited with non-zero return code"
                    errors.append(f"[{ip}] {err_text}")

            except Exception as e:
                errors.append(f"[{ip}] Error while running playbook: {e}")

        output = "\n\n".join(combined_outputs) if combined_outputs else None
        error = "\n".join(errors) if errors else None

    return render_template("routers.html", output=output, error=error)


if __name__ == "__main__":
    print("Starting Flask development server on http://0.0.0.0:8000 ...")
    app.run(host="0.0.0.0", port=8000, debug=True)
