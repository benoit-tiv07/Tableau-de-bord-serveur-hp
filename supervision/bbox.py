import os, time, sqlite3, threading, requests, urllib3
from flask import Blueprint, jsonify, render_template, request

urllib3.disable_warnings()

BASE = os.environ.get("BBOX_URL", "https://mabbox.bytel.fr")
PWD = os.environ.get("BBOX_PASSWORD", "")
DB = os.environ.get("BBOX_DB", "data/bbox.db")
INTERVAL = 5          # secondes entre deux relevés
KEEP_DAYS = 7         # durée de conservation de l'historique

bp = Blueprint("bbox", __name__)
_session = None
_lock = threading.Lock()
_last = {}
_hosts_cache = {"t": 0, "data": []}


def _public(path):
    """Endpoints qui ne demandent pas de connexion (débit, état de la ligne)."""
    r = requests.get(BASE + path, timeout=8, verify=False)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.json()


def _login():
    global _session
    s = requests.Session()
    r = s.post(f"{BASE}/api/v1/login", data={"password": PWD},
               timeout=8, verify=False)
    if r.status_code != 200:
        raise RuntimeError(f"Connexion Bbox refusée ({r.status_code})")
    _session = s


def _private(path):
    """Endpoints protégés (liste des appareils) : se reconnecte si besoin."""
    global _session
    with _lock:
        for _ in range(2):
            if _session is None:
                _login()
            r = _session.get(BASE + path, timeout=8, verify=False)
            if r.status_code == 401:
                _session = None
                continue
            r.raise_for_status()
            r.encoding = "utf-8"
            return r.json()
    raise RuntimeError("Authentification Bbox impossible")


def _db():
    os.makedirs(os.path.dirname(DB) or ".", exist_ok=True)
    return sqlite3.connect(DB)


def _init_db():
    con = _db()
    con.execute("CREATE TABLE IF NOT EXISTS bbox_traffic "
                "(ts INTEGER PRIMARY KEY, rx REAL, tx REAL)")
    con.commit()
    con.close()


def _loop():
    prev = None
    n = 0
    while True:
        try:
            st = _public("/api/v1/wan/ip/stats")[0]["wan"]["ip"]["stats"]
            now = time.time()
            rxb, txb = int(st["rx"]["bytes"]), int(st["tx"]["bytes"])
            if prev:
                dt = now - prev[0]
                rx = max(0, (rxb - prev[1]) * 8 / dt)   # bits/s
                tx = max(0, (txb - prev[2]) * 8 / dt)
                con = _db()
                con.execute("INSERT OR REPLACE INTO bbox_traffic VALUES (?,?,?)",
                            (int(now), rx, tx))
                con.commit()
                con.close()
                _last.update(ts=int(now), rx=rx, tx=tx)
            prev = (now, rxb, txb)
            _last.update(
                rx_occ=st["rx"].get("occupation"),
                tx_occ=st["tx"].get("occupation"),
                rx_contract=st["rx"].get("contractualBandwidth"),   # kb/s
                tx_contract=st["tx"].get("contractualBandwidth"),
                error=None,
            )
            if n % 12 == 0:
                wan = _public("/api/v1/wan/ip")[0]["wan"]
                _last.update(ip=wan["ip"].get("address"),
                             state=wan["ip"].get("state"),
                             link=wan["link"].get("state"))
            if n % 720 == 0:
                con = _db()
                con.execute("DELETE FROM bbox_traffic WHERE ts < ?",
                            (int(now) - KEEP_DAYS * 86400,))
                con.commit()
                con.close()
        except Exception as e:
            _last["error"] = str(e)
        n += 1
        time.sleep(INTERVAL)


def start():
    _init_db()
    if not any(t.name == "bbox-sampler" for t in threading.enumerate()):
        threading.Thread(target=_loop, name="bbox-sampler", daemon=True).start()

def _fix(texte):
    """Répare le texte encodé deux fois par la Bbox (ex. 'DÃ©codeur' -> 'Décodeur')."""
    if not isinstance(texte, str):
        return texte
    for codec in ("latin-1", "cp1252"):
        try:
            return texte.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return texte

@bp.route("/bbox")
def page():
    return render_template("bbox.html", page="bbox")


@bp.route("/api/bbox/live")
def api_live():
    return jsonify(_last)


@bp.route("/api/bbox/history")
def api_history():
    minutes = max(1, min(int(request.args.get("minutes", 60)), KEEP_DAYS * 1440))
    step = max(1, minutes * 60 // 300)        # ~300 points maximum
    since = int(time.time()) - minutes * 60
    con = _db()
    rows = con.execute(
        "SELECT CAST(ts/? AS INTEGER)*? AS t, AVG(rx), AVG(tx) "
        "FROM bbox_traffic WHERE ts >= ? GROUP BY t ORDER BY t",
        (step, step, since)).fetchall()
    con.close()
    return jsonify([{"ts": t, "rx": rx, "tx": tx} for t, rx, tx in rows])


@bp.route("/api/bbox/hosts")
def api_hosts():
    try:
        now = time.time()
        if now - _hosts_cache["t"] > 10:
            _hosts_cache["data"] = _private("/api/v1/hosts")[0]["hosts"]["list"]
            _hosts_cache["t"] = now
        out = []
        for h in _hosts_cache["data"]:
            if not h.get("active"):
                continue
            info = h.get("informations") or {}
            w = h.get("wireless") or {}
            out.append({
                "name": _fix(h.get("hostname")) or "(sans nom)",
                "ip": h.get("ipaddress"),
                "mac": h.get("macaddress"),
                "link": h.get("link"),
                "band": w.get("band"),
                "rssi": w.get("rssi0"),
                "type": _fix(info.get("type")),
                "maker": _fix(info.get("manufacturer")),
            })
        return jsonify({"hosts": out, "total": len(_hosts_cache["data"])})
    except Exception as e:
        return jsonify({"hosts": [], "error": str(e)}), 502
