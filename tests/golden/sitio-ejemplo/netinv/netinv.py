#!/usr/bin/env python3
"""netinv — inventario de dispositivos de la red.

Cada INTERVAL segundos cruza por MAC:
  1. arp-scan de la subred (IP, MAC, fabricante OUI): ve todo lo encendido, use o no la Pi-hole.
  2. Pi-hole (las dos, API v6): nombres DHCP/DNS, fabricante, primera/última vez, nº de consultas.
  3. mDNS (zeroconf) y SSDP/UPnP: nombres y modelos que anuncian los propios aparatos.
  4. nmap ligero (puertos típicos de IoT, servicio, SO, NetBIOS) solo a MAC nuevas o cada 7 días.
  5. Huella DNS de IoT: de las consultas de cada cliente SOLO se anota con qué nube de fabricante IoT
     habla (Tuya, eWeLink, Shelly...). No se guardan dominios ni historial de navegación.
Clasificación manual: /etc/netinv/devices.yaml (del repo, network/devices.yaml).
Salida: /data/state.json, http://:9877/devices.json y /metrics (Prometheus).
"""
import json, os, re, socket, subprocess, threading, time, urllib.error, urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml
from zeroconf import ServiceBrowser, ServiceListener, Zeroconf, ZeroconfServiceTypes

SUBNET = os.environ["SUBNET"]
IFACE = os.environ.get("IFACE", "")
INTERVAL = int(os.environ.get("INTERVAL", "900"))
PORT = int(os.environ.get("PORT", "9877"))
LAN_IP = os.environ.get("LAN_IP", "")  # mDNS solo por la LAN (el host tiene decenas de redes Docker)
STATE = "/data/state.json"
CLASSIFICATION = "/etc/netinv/devices.yaml"
NMAP_EVERY = 7 * 86400
NMAP_ENABLED = os.environ.get("NMAP", "1") == "1"
KEEP_DAYS = 30
PIHOLES = list(zip(os.environ.get("PIHOLE_URLS", "").split(","),
                   os.environ.get("PIHOLE_PASSWORDS", "").split(",")))

# Nube con la que habla el aparato → pista de qué es. Solo se guarda la etiqueta, nunca el dominio.
IOT_CLOUDS = [   # expresión sobre el dominio completo; (^|\.) = principio de etiqueta
    (r"(^|\.)(tuya[a-z]*|smartlife|wgine)\.com$|(^|\.)tuya", "Tuya / Smart Life"),
    (r"(^|\.)(ewelink|coolkit|itead)\.", "eWeLink / Sonoff"),
    (r"(^|\.)shelly", "Shelly"),
    (r"(^|\.)meross\.", "Meross"),
    (r"(^|\.)(tplinkcloud|tplinknbu|tplinkra|kasasmart|tapo)", "TP-Link Kasa/Tapo"),
    (r"(^|\.)(io\.mi\.com|miot-spec\.org|xiaomi\.(com|net)|mijia|xiaomiyoupin)", "Xiaomi / Mi Home"),
    (r"(^|\.)yeelight\.", "Yeelight"),
    (r"(^|\.)(roborock|dreame|ecovacs|irobot|cecotec)", "Robot aspirador"),
    (r"(^|\.)(alexa|avs-alexa[a-z0-9-]*|device-metrics-us(-2)?|amazon-dss)\.", "Amazon Echo/Alexa"),
    (r"(^|\.)(googlecast|cast\.google)\.", "Google Cast"),
    (r"(^|\.)(nest\.com|nestlabs\.com)$", "Google Nest"),
    (r"(^|\.)(smartthings|samsungiotcloud)\.", "Samsung SmartThings"),
    (r"(^|\.)(samsungcloudsolution|samsungotn|samsungqbe|tizen)\.", "Samsung TV"),
    (r"(^|\.)(lgtvsdp|lgsmartad|lgappstv)\.", "LG TV"),
    (r"(^|\.)meethue\.com$", "Philips Hue"),
    (r"(^|\.)(ezvizlife|hik-connect|ezviz7)\.", "Cámara Ezviz/Hikvision"),
    (r"(^|\.)(imoulife|easy4ip)\.", "Cámara Imou/Dahua"),
    (r"(^|\.)(ibroadlink|broadlink)\.", "Broadlink"),
    (r"(^|\.)govee\.", "Govee"),
    (r"(^|\.)lifx\.", "LIFX"),
    (r"(^|\.)netatmo\.", "Netatmo"),
    (r"(^|\.)(msmarthome|midea)\.", "Midea (aire/electrodoméstico)"),
    (r"(^|\.)daikin", "Daikin (aire)"),
    (r"(^|\.)(ewpe|gree)\.com$|(^|\.)dis\.gree", "Gree (aire)"),
    (r"(^|\.)(vidaa|hismarttv)\.", "Hisense TV"),
    (r"(^|\.)sonos\.(com|net)$", "Sonos"),
    (r"(^|\.)roku\.com$", "Roku"),
    (r"(^|\.)ring\.com$", "Ring"),
    (r"(^|\.)(nabu\.casa|home-assistant\.io)$", "Home Assistant"),
    (r"(^|\.)(playstation\.(net|com)|sonyentertainmentnetwork\.com)$", "PlayStation"),
    (r"(^|\.)xboxlive\.com$", "Xbox"),
    (r"(^|\.)nintendo\.net$", "Nintendo"),
]
IOT_RE = [(re.compile(p, re.I), tag) for p, tag in IOT_CLOUDS]
NMAP_PORTS = ("T:21,22,23,53,80,81,443,554,1883,5000,6466,6467,6668,7000,8008,8009,8080,8443,"
              "8883,9100,9999,49152,62078,U:137,1900,5353")

lock = threading.Lock()
state = {"devices": {}, "queries_since": {}}


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def norm_mac(m):
    return m.lower().replace("-", ":") if m else m


def random_mac(mac):
    return int(mac.split(":")[0], 16) & 0x02 != 0


def dev(mac):
    d = state["devices"].setdefault(mac, {"mac": mac, "aleatoria": random_mac(mac)})
    if d["aleatoria"]:          # MAC privada (móviles): el OUI no dice nada del fabricante
        d["fabricante"] = "(MAC aleatoria)"
    return d


def add(d, key, value):
    if value:
        s = set(d.get(key, []))
        s.add(value)
        d[key] = sorted(s)


# --- 1. arp-scan ---------------------------------------------------------------------------
def arp_scan(now):
    cmd = ["arp-scan", "--plain", "--retry=2", "--format=${ip}\t${mac}\t${vendor}"]
    cmd += ["--interface", IFACE] if IFACE else []
    out = subprocess.run(cmd + [SUBNET], capture_output=True, text=True, timeout=120).stdout
    seen = {}
    for line in out.splitlines():
        p = line.split("\t")
        if len(p) >= 2 and re.match(r"\d+\.\d+\.\d+\.\d+$", p[0]):
            mac = norm_mac(p[1])
            d = dev(mac)
            d["ip"] = p[0]
            if not d["aleatoria"] and len(p) > 2 and p[2] and "Unknown" not in p[2]:
                d["fabricante"] = p[2].strip()
            d["visto_ultima"] = now
            d.setdefault("visto_primera", now)
            seen[p[0]] = mac
    return seen


# --- 2. Pi-hole ------------------------------------------------------------------------------
class PiHole:
    def __init__(self, url, password):
        self.url, self.password, self.sid = url.rstrip("/"), password, None

    def get(self, path):
        for _ in range(2):
            if not self.sid:
                req = urllib.request.Request(self.url + "/api/auth", method="POST",
                                             data=json.dumps({"password": self.password}).encode(),
                                             headers={"Content-Type": "application/json"})
                self.sid = json.loads(urllib.request.urlopen(req, timeout=15).read())["session"]["sid"]
            try:
                req = urllib.request.Request(self.url + path, headers={"X-FTL-SID": self.sid})
                return json.loads(urllib.request.urlopen(req, timeout=60).read())
            except urllib.error.HTTPError as e:
                if e.code != 401:
                    raise
                self.sid = None
        raise RuntimeError("Pi-hole: no se pudo autenticar")


piholes = [PiHole(u, p) for u, p in PIHOLES if u and p]


def from_pihole(now, ip2mac):
    for ph in piholes:
        name = ph.url.split("//")[1]
        try:
            for nd in ph.get("/api/network/devices?max_devices=1000&max_addresses=10")["devices"]:
                mac = norm_mac(nd["hwaddr"])
                if not re.match(r"([0-9a-f]{2}:){5}[0-9a-f]{2}$", mac or "") or mac == "00:00:00:00:00:00":
                    continue
                if now - (nd.get("lastQuery") or 0) > KEEP_DAYS * 86400 and mac not in state["devices"]:
                    continue
                d = dev(mac)
                if nd.get("macVendor") and not d.get("fabricante") and not d["aleatoria"]:
                    d["fabricante"] = nd["macVendor"]
                if nd.get("lastQuery"):
                    d["pihole_ultima"] = max(d.get("pihole_ultima", 0), nd["lastQuery"])
                if nd.get("firstSeen"):
                    d["visto_primera"] = min(d.get("visto_primera", now), nd["firstSeen"])
                # La tabla de red de Pi-hole da para cada IP su nombre DNS ACTUAL, que puede ser de otro
                # aparato que tuvo esa IP: de aquí solo se toma la IP más reciente (24 h), no el nombre.
                recent = sorted((a for a in nd.get("ips", []) if a.get("ip") and ":" not in a["ip"]
                                 and a.get("lastSeen", 0) >= now - 86400), key=lambda a: -a.get("lastSeen", 0))
                if recent:
                    ip2mac.setdefault(recent[0]["ip"], mac)
                    d.setdefault("ip", recent[0]["ip"])
            for l in ph.get("/api/dhcp/leases").get("leases", []):
                mac = norm_mac(l.get("hwaddr"))
                # Las concesiones DHCP van por MAC: su nombre es el que anuncia el propio aparato.
                if mac and mac in state["devices"] and l.get("name") not in (None, "", "*"):
                    add(state["devices"][mac], "n_dhcp", l["name"])
            # consultas DNS de cada cliente en las últimas 24 h (cuenta de la propia Pi-hole)
            for c in ph.get("/api/stats/top_clients?count=500").get("clients", []):
                mac = ip2mac.get(c.get("ip"))
                if mac:
                    state["devices"][mac].setdefault("dns24", {})[name] = c.get("count", 0)
            iot_from_queries(ph, name, now, ip2mac)
        except Exception as e:  # una Pi-hole caída no debe parar el inventario
            log("Pi-hole", name, "error:", e)


def iot_from_queries(ph, name, now, ip2mac):
    since = state["queries_since"].get(name, now - 86400)
    data = ph.get(f"/api/queries?from={int(since)}&until={int(now)}&length=100000")
    for q in data.get("queries", []):
        dom, ip = q.get("domain") or "", (q.get("client") or {}).get("ip")
        mac = ip2mac.get(ip)
        if not mac:
            continue
        for rx, tag in IOT_RE:
            if rx.search(dom):
                add(state["devices"][mac], "nubes_iot", tag)
    state["queries_since"][name] = now


# --- 3. mDNS y SSDP -------------------------------------------------------------------------
class Collector(ServiceListener):
    def __init__(self, zc):
        self.zc, self.found = zc, []

    def add_service(self, zc, type_, name):
        info = zc.get_service_info(type_, name, timeout=1500)
        if info:
            props = {k.decode(errors="ignore"): (v or b"").decode(errors="ignore")
                     for k, v in (info.properties or {}).items() if k}
            for ip in info.parsed_addresses():
                self.found.append((ip, type_, name, info.server, props))

    update_service = remove_service = lambda *a: None


def mdns(ip2mac):
    zc = Zeroconf(interfaces=[LAN_IP]) if LAN_IP else Zeroconf()
    try:
        types = ZeroconfServiceTypes.find(zc=zc, timeout=4)
        col = Collector(zc)
        browsers = [ServiceBrowser(zc, t, col) for t in types]
        time.sleep(8)
        for b in browsers:
            b.cancel()
    finally:
        zc.close()
    for ip, type_, name, server, props in col.found:
        mac = ip2mac.get(ip)
        if not mac:
            continue
        d = state["devices"][mac]
        add(d, "mdns", type_.replace("._tcp.local.", "").replace("._udp.local.", "").lstrip("_"))
        add(d, "n_mdns", (server or "").rstrip(".").replace(".local", ""))
        add(d, "n_mdns", name.split("._")[0])
        for k in ("md", "model", "ty", "fn", "am", "product", "manufacturer", "vendor", "rpMd"):
            if props.get(k):
                add(d, "modelo", f"{k}={props[k][:60]}")


def ssdp(ip2mac):
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\n"
           "MX: 3\r\nST: ssdp:all\r\n\r\n").encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(1)
    s.sendto(msg, ("239.255.255.250", 1900))
    locs, end = {}, time.time() + 5
    while time.time() < end:
        try:
            data, (ip, _) = s.recvfrom(4096)
        except socket.timeout:
            continue
        h = {l.split(":", 1)[0].lower(): l.split(":", 1)[1].strip()
             for l in data.decode(errors="ignore").splitlines() if ":" in l}
        mac = ip2mac.get(ip)
        if mac:
            add(state["devices"][mac], "ssdp", h.get("server", "")[:80])
            if h.get("location"):
                locs.setdefault(mac, h["location"])
    s.close()
    for mac, url in locs.items():
        try:
            root = ET.fromstring(urllib.request.urlopen(url, timeout=3).read())
            for tag in ("friendlyName", "manufacturer", "modelName", "modelDescription"):
                el = root.find(f".//{{*}}{tag}")
                if el is not None and el.text:
                    add(state["devices"][mac], "modelo", f"{tag}={el.text.strip()[:60]}")
        except Exception:
            pass  # descripción UPnP opcional


# --- 4. nmap --------------------------------------------------------------------------------
def nmap_new(now):
    for mac, d in list(state["devices"].items()):
        if not d.get("ip") or d.get("visto_ultima", 0) < now - 3600:
            continue
        if now - d.get("nmap_fecha", 0) < NMAP_EVERY:
            continue
        try:
            xml = subprocess.run(["nmap", "-Pn", "-sS", "-sU", "-p", NMAP_PORTS, "-sV", "--version-light",
                                  "-O", "--osscan-limit", "--script", "nbstat,http-title", "-T4",
                                  "--host-timeout", "120s", "-oX", "-", d["ip"]],
                                 capture_output=True, text=True, timeout=200).stdout
            root = ET.fromstring(xml)
            ports = []
            for p in root.iter("port"):
                st = p.find("state")
                if st is None or st.get("state") != "open":
                    continue
                sv = p.find("service")
                desc = " ".join(x for x in ((sv.get("name"), sv.get("product"), sv.get("version"))
                                            if sv is not None else ()) if x)
                ports.append(f'{p.get("portid")}/{p.get("protocol")} {desc}'.strip())
                for sc in p.findall("script"):
                    if sc.get("id") == "http-title":
                        add(d, "modelo", "web=" + sc.get("output", "")[:60])
            d["puertos"] = ports
            om = root.find(".//osmatch")
            d["so"] = om.get("name")[:60] if om is not None else None
            for sc in root.iter("script"):
                if sc.get("id") == "nbstat":
                    m = re.search(r"NetBIOS name: ([^,]+)", sc.get("output", ""))
                    if m:
                        add(d, "n_netbios", m.group(1).strip())
            d["nmap_fecha"] = now
            log("nmap", d["ip"], mac, len(ports), "puertos")
            save()          # nmap es lento: no perder lo analizado si el contenedor se reinicia
        except Exception as e:
            log("nmap", d.get("ip"), "error:", e)


# --- clasificación manual y salida -------------------------------------------------------------
def norm_name(n):
    return re.sub(r"[^a-z0-9]", "", (n or "").lower())


def classification():
    """Fichas manuales por MAC y, para los móviles con MAC aleatoria, por su nombre DHCP (nombre_dhcp)."""
    try:
        doc = yaml.safe_load(open(CLASSIFICATION)) or {}
    except FileNotFoundError:
        return {}, {}
    devs = doc.get("dispositivos", [])
    return ({norm_mac(x["mac"]): x for x in devs if x.get("mac")},
            {norm_name(x["nombre_dhcp"]): x for x in devs if x.get("nombre_dhcp")})


def names(d):
    out = []
    for k in ("n_dhcp", "n_netbios", "n_mdns"):
        for n in d.get(k, []):
            if n and n.lower() not in (x.lower() for x in out):
                out.append(n)
    return out


def esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def metrics():
    by_mac, by_name = classification()
    now = time.time()
    out = ["# HELP netinv_device_info Dispositivo de la red (1 = visto en las últimas 24 h).",
           "# TYPE netinv_device_info gauge"]
    last, first = ["# TYPE netinv_device_last_seen_seconds gauge"], ["# TYPE netinv_device_first_seen_seconds gauge"]
    dns = ["# HELP netinv_device_dns_queries_24h Consultas DNS del dispositivo en 24 h (suma de las dos Pi-hole).",
           "# TYPE netinv_device_dns_queries_24h gauge"]
    with lock:
        devs = list(state["devices"].values())
    for d in devs:
        seen = max(d.get("visto_ultima", 0), d.get("pihole_ultima", 0))
        if now - seen > KEEP_DAYS * 86400:
            continue
        c = by_mac.get(d["mac"]) or next((by_name[norm_name(n)] for n in d.get("n_dhcp", [])
                                          if norm_name(n) in by_name), {})
        ip = d.get("ip", "")
        lab = {"orden": "%03d" % int(ip.split(".")[-1]) if ip else "999", "mac": d["mac"], "ip": ip, "nombre": c.get("nombre", ""), "tipo": c.get("tipo", ""),
               "ubicacion": c.get("ubicacion", ""), "clasificado": "sí" if c.get("tipo") else "no",
               "fabricante": d.get("fabricante", ""), "nombres": ", ".join(names(d)[:4]),
               "nubes_iot": ", ".join(d.get("nubes_iot", [])), "mdns": ", ".join(d.get("mdns", [])[:5]),
               "modelo": ", ".join(d.get("modelo", [])[:3]), "puertos": ", ".join(p.split()[0] for p in d.get("puertos", [])),
               "so": d.get("so") or "", "aleatoria": "sí" if d.get("aleatoria") else "no"}
        # nombre para mostrar: el manual; si no, lo que anuncia el aparato o su fabricante, marcado con «¿?»
        lab["mostrar"] = c.get("nombre") or f'{(names(d) or [d.get("fabricante") or d["mac"]])[0]} ¿?'
        lab["encendido"] = "●" if now - seen < 1800 else "○"
        l = ",".join(f'{k}="{esc(v)}"' for k, v in lab.items())
        out.append(f"netinv_device_info{{{l}}} {1 if now - seen < 86400 else 0}")
        last.append(f'netinv_device_last_seen_seconds{{mac="{d["mac"]}"}} {int(seen)}')
        first.append(f'netinv_device_first_seen_seconds{{mac="{d["mac"]}"}} {int(d.get("visto_primera", seen))}')
        if d.get("dns24"):
            dns.append(f'netinv_device_dns_queries_24h{{mac="{d["mac"]}"}} {sum(d["dns24"].values())}')
    return "\n".join(out + last + first + dns) + "\n"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/metrics"):
            body, ctype = metrics().encode(), "text/plain; version=0.0.4"
        elif self.path.startswith("/devices.json"):
            with lock:
                body = json.dumps({m: {**d, "nombres": names(d)} for m, d in state["devices"].items()},
                                  ensure_ascii=False, indent=1).encode()
            ctype = "application/json"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def save():
    with lock:
        json.dump(state, open(STATE + ".tmp", "w"), ensure_ascii=False)
        os.replace(STATE + ".tmp", STATE)


def cycle():
    now = time.time()
    ip2mac = arp_scan(now)
    from_pihole(now, ip2mac)
    for name, fn in (("mDNS", mdns), ("SSDP", ssdp)):
        try:
            fn(ip2mac)
        except Exception as e:
            log(name, "error:", e)
    if NMAP_ENABLED:
        nmap_new(now)
    save()
    log("ciclo:", len(ip2mac), "encendidos,", len(state["devices"]), "en inventario")


if __name__ == "__main__":
    if os.path.exists(STATE):
        state.update(json.load(open(STATE)))
    if state.get("version", 1) < 3:   # v1/v2 mezclaban nombres de IPs antiguas y patrones IoT amplios
        state["devices"].pop("00:00:00:00:00:00", None)
        for d in state["devices"].values():
            for k in ("nombres", "nubes_iot", "n_pihole"):
                d.pop(k, None)
        state["queries_since"] = {}
        state["version"] = 3
    threading.Thread(target=ThreadingHTTPServer(("", PORT), Handler).serve_forever, daemon=True).start()
    while True:
        try:
            cycle()
        except Exception as e:
            log("ciclo error:", e)
        time.sleep(INTERVAL)
