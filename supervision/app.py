import sqlite3
import json
import os
import urllib.request
import subprocess
import platform
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import calendar
import html
import re
import glob
import bbox

import feedparser
import psutil

import icalendar
import recurring_ical_events

from flask import Flask, jsonify, redirect, render_template, request, url_for

# nom: (IP locale, IP Tailscale)
MACHINES = {
    "Serveur HP":          ("192.168.1.182", "100.105.134.35"),
    "Répéteur TP-Link":    ("192.168.1.253",None),
    "Samsung GalaxyBook4": ("192.168.1.210", "100.107.4.31"),
    "PC MSI":              ("192.168.1.211",  "100.127.128.7"),
    "Oppo de Luna":        ("192.168.1.212", "100.77.47.123"),
}

# (nom affiché, adresse)
RACCOURCIS = [
    ("GitHub", "https://github.com"),
    ("Claude", "https://claude.ai"),
    ("Tailscale", "https://login.tailscale.com/admin/machines"),
]

CONFIG = os.environ.get("CONFIG_PATH", "config.json")
TZ = ZoneInfo("Europe/Paris")


def charger_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print("Config illisible :", e)
        return {}


def raccourcis():
    liens = [(s["label"], s["target"]) for s in charger_config().get("shortcuts", [])
             if isinstance(s, dict) and s.get("label")
             and str(s.get("target", "")).startswith(("http://", "https://"))]
    return liens or RACCOURCIS


def calendriers_embed():
    return [(c.get("name", ""), c["embedUrl"]) for c in charger_config().get("calendars", [])
            if str(c.get("embedUrl", "")).startswith("https://calendar.google.com/")]

INTERVALLE = 10  # secondes entre deux relevés

app = Flask(__name__)

DB = os.environ.get("DB_PATH", "supervision.db")
app.register_blueprint(bbox.bp)
bbox.DB = os.path.join(os.path.dirname(os.path.abspath(DB)), "bbox.db")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

def alerte(message) -> bool:
    print(message)
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data=json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": message}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception as e:
        print("Alerte non envoyée :", e)
        return False


def alerte_demarrage():
    # Au démarrage du serveur, le réseau peut ne pas être prêt : on réessaie
    # toutes les 10 secondes, pendant 2 minutes au maximum.
    for _ in range(12):
        if alerte("🔄 Moniteur démarré sur le serveur HP"):
            return
        time.sleep(10)


def init_db():
    with sqlite3.connect(DB) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS evenements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, machine TEXT, reseau TEXT, en_ligne INTEGER)""")
        c.execute("""CREATE TABLE IF NOT EXISTS devoirs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titre TEXT NOT NULL, matiere TEXT, echeance TEXT,
            fait INTEGER DEFAULT 0)""")
        c.execute("CREATE TABLE IF NOT EXISTS taches_faites (id TEXT PRIMARY KEY)")
        c.execute("""CREATE TABLE IF NOT EXISTS flux (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL, url TEXT NOT NULL UNIQUE, categorie TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flux_id INTEGER NOT NULL, titre TEXT, lien TEXT NOT NULL UNIQUE,
            resume TEXT, date_pub REAL, lu INTEGER DEFAULT 0)""")

def enregistrer(machine, reseau, en_ligne):
    with sqlite3.connect(DB) as c:
        c.execute(
            "INSERT INTO evenements (date, machine, reseau, en_ligne) VALUES (?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), machine, reseau, int(en_ligne)),
        )

# Dernier état connu, partagé entre le thread de ping et le serveur web
etat = {"maj": None, "machines": []}
verrou = threading.Lock()


def ping_une_fois(host: str) -> bool:
    if platform.system() == "Windows":
        cmd = ["ping", "-n", "1", "-w", "1000", host]
    else:
        cmd = ["ping", "-c", "1", "-W", "1", host]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


def ping(host: str) -> bool:
    return ping_une_fois(host) or ping_une_fois(host)


def boucle_surveillance():
    precedent = {}  # (machine, réseau) -> dernier état connu
    while True:
        with ThreadPoolExecutor(max_workers=len(MACHINES) * 2) as pool:
            futures = {
                nom: (pool.submit(ping, lan), pool.submit(ping, ts) if ts else None)
                for nom, (lan, ts) in MACHINES.items()
            }
            resultats = [
                {
                    "nom": nom,
                    "ip_lan": MACHINES[nom][0],
                    "ip_ts": MACHINES[nom][1],
                    "lan": f_lan.result(),
                    "ts": f_ts.result() if f_ts else None,
                }
                for nom, (f_lan, f_ts) in futures.items()
            ]

        # Détection des changements d'état
        for m in resultats:
            for reseau, libelle in (("lan", "local"), ("ts", "Tailscale")):
                cle = (m["nom"], reseau)
                actuel = m[reseau]
                if actuel is None:
                    continue
                if cle not in precedent:
                    enregistrer(m["nom"], reseau, actuel)  # état initial, sans alerte
                elif precedent[cle] != actuel:
                    enregistrer(m["nom"], reseau, actuel)
                    if actuel:
                        alerte(f"🟢 {m['nom']} est revenu en ligne ({libelle})")
                    else:
                        alerte(f"🔴 {m['nom']} est hors ligne ({libelle})")
                precedent[cle] = actuel

        with verrou:
            etat["machines"] = resultats
            etat["maj"] = datetime.now().strftime("%H:%M:%S")
        time.sleep(INTERVALLE)

@app.route("/")
def accueil():
    return render_template("accueil.html", page="accueil", raccourcis=raccourcis(), calendriers=calendriers_embed())

@app.route("/machines")
def page_machines():
    return render_template("machines.html", page="machines")

@app.route("/api/historique")
def api_historique():
    with sqlite3.connect(DB) as c:
        lignes = c.execute(
            "SELECT date, machine, reseau, en_ligne FROM evenements "
            "ORDER BY id DESC LIMIT 30"
        ).fetchall()
    return jsonify([
        {"date": d, "machine": m, "reseau": "local" if r == "lan" else "Tailscale", "en_ligne": bool(e)}
        for d, m, r, e in lignes
    ])

@app.route("/api/status")
def api_status():
    with verrou:
        return jsonify(etat)

# Météo (Open-Meteo, sans clé), mise en cache 30 minutes
LATITUDE, LONGITUDE = 46.82, 0.55   # Châtellerault, à adapter si besoin
_meteo = {"t": 0, "data": None}

@app.route("/api/meteo")
def api_meteo():
    if _meteo["data"] is None or time.time() - _meteo["t"] > 1800:
        url = ("https://api.open-meteo.com/v1/forecast"
               f"?latitude={LATITUDE}&longitude={LONGITUDE}"
               "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
               "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
               "&timezone=Europe%2FParis&forecast_days=3")
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                _meteo["data"] = json.loads(r.read())
                _meteo["t"] = time.time()
        except Exception as e:
            print("Météo indisponible :", e)
            if _meteo["data"] is None:
                return jsonify({"erreur": "Météo indisponible"}), 503
    return jsonify(_meteo["data"])


@app.route("/api/systeme")
def api_systeme():
    mem = psutil.virtual_memory()
    disque = psutil.disk_usage("/")
    temperature = None
    try:
        for capteurs in psutil.sensors_temperatures().values():
            if capteurs:
                temperature = capteurs[0].current
                break
    except Exception:
        pass
    return jsonify({
        "cpu": psutil.cpu_percent(interval=0.2),
        "ram": mem.percent,
        "ram_utilisee": round(mem.used / 1e9, 1),
        "ram_totale": round(mem.total / 1e9, 1),
        "disque": disque.percent,
        "disque_utilise": round(disque.used / 1e9),
        "disque_total": round(disque.total / 1e9),
        "uptime": int(time.time() - psutil.boot_time()),
        "temperature": temperature,
    })

@app.route("/api/devoirs", methods=["GET"])
def api_devoirs():
    with sqlite3.connect(DB) as c:
        lignes = c.execute(
            "SELECT id, titre, matiere, echeance, fait FROM devoirs "
            "ORDER BY fait, echeance IS NULL, echeance, id"
        ).fetchall()
    return jsonify([
        {"id": i, "titre": t, "matiere": m, "echeance": e, "fait": bool(f)}
        for i, t, m, e, f in lignes
    ])


@app.route("/api/devoirs", methods=["POST"])
def api_devoir_ajouter():
    d = request.get_json(silent=True) or {}
    titre = (d.get("titre") or "").strip()[:200]
    if not titre:
        return jsonify({"erreur": "titre manquant"}), 400
    matiere = (d.get("matiere") or "").strip()[:50] or None
    echeance = (d.get("echeance") or "").strip()[:10] or None
    with sqlite3.connect(DB) as c:
        c.execute("INSERT INTO devoirs (titre, matiere, echeance) VALUES (?,?,?)",
                  (titre, matiere, echeance))
    return jsonify({"ok": True}), 201


@app.route("/api/devoirs/<int:id_>/basculer", methods=["POST"])
def api_devoir_basculer(id_):
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE devoirs SET fait = 1 - fait WHERE id = ?", (id_,))
    return jsonify({"ok": True})


@app.route("/api/devoirs/<int:id_>", methods=["DELETE"])
def api_devoir_supprimer(id_):
    with sqlite3.connect(DB) as c:
        c.execute("DELETE FROM devoirs WHERE id = ?", (id_,))
    return jsonify({"ok": True})

def vers_datetime(v):
    """date ou datetime (naïf ou avec fuseau) -> datetime avec fuseau de Paris."""
    if isinstance(v, datetime):
        return v.replace(tzinfo=TZ) if v.tzinfo is None else v.astimezone(TZ)
    return datetime(v.year, v.month, v.day, tzinfo=TZ)  # date seule : journée entière


def lire_calendrier(cal, debut, fin):
    with urllib.request.urlopen(cal["icsUrl"], timeout=20) as r:
        agenda = icalendar.Calendar.from_ical(r.read())
    resultat = []
    for ev in recurring_ical_events.of(agenda).between(debut, fin):
        d = ev["DTSTART"].dt
        f = ev["DTEND"].dt if "DTEND" in ev else d
        journee = not isinstance(d, datetime)
        d, f = vers_datetime(d), vers_datetime(f)
        resultat.append({
            "id": f"{ev.get('UID', '')}|{d.isoformat()}",
            "titre": str(ev.get("SUMMARY", "(sans titre)")),
            "debut": d.isoformat(), "fin": f.isoformat(),
            "debut_ts": d.timestamp(), "fin_ts": f.timestamp(),
            "journee": journee,
            "calendrier": cal.get("name", ""), "tache": bool(cal.get("todo")),
        })
    return resultat


_agenda = {"t": 0, "evenements": [], "erreurs": []}
verrou_agenda = threading.Lock()


def rafraichir_agenda():
    cals = [c for c in charger_config().get("calendars", []) if c.get("icsUrl")]
    maintenant = datetime.now(TZ)
    debut, fin = maintenant - timedelta(days=7), maintenant + timedelta(days=30)
    evenements, erreurs = [], []
    with ThreadPoolExecutor(max_workers=max(1, len(cals))) as pool:
        futures = [(c, pool.submit(lire_calendrier, c, debut, fin)) for c in cals]
        for c, fut in futures:
            try:
                evenements += fut.result()
            except Exception as e:
                erreurs.append(f"{c.get('name', '?')} : {e}")
    t = time.time() - 600 if (erreurs and not evenements) else time.time()  # nouvel essai dans 5 min
    _agenda.update(t=t, evenements=evenements, erreurs=erreurs)


@app.route("/api/agenda")
def api_agenda():
    with verrou_agenda:
        if time.time() - _agenda["t"] > 900:  # cache de 15 minutes
            rafraichir_agenda()
        evenements, erreurs = list(_agenda["evenements"]), list(_agenda["erreurs"])
    with sqlite3.connect(DB) as c:
        faites = {r[0] for r in c.execute("SELECT id FROM taches_faites")}
    taches = [{"id": e["id"], "titre": e["titre"], "calendrier": e["calendrier"],
               "date": e["debut"][:10], "fait": e["id"] in faites}
              for e in evenements if e["tache"]]
    prochains = sorted((e for e in evenements if not e["tache"] and e["fin_ts"] >= time.time()),
                       key=lambda e: e["debut_ts"])[:10]
    return jsonify({"agenda": prochains, "taches": taches, "erreurs": erreurs})


@app.route("/api/taches/basculer", methods=["POST"])
def api_tache_basculer():
    id_ = ((request.get_json(silent=True) or {}).get("id") or "")[:500]
    if not id_:
        return jsonify({"erreur": "id manquant"}), 400
    with sqlite3.connect(DB) as c:
        if c.execute("DELETE FROM taches_faites WHERE id = ?", (id_,)).rowcount == 0:
            c.execute("INSERT INTO taches_faites (id) VALUES (?)", (id_,))
    return jsonify({"ok": True})

# ---------- Lecteur RSS ----------

def nettoyer(texte, limite=300):
    texte = re.sub(r"<[^>]+>", " ", texte or "")
    texte = re.sub(r"\s+", " ", html.unescape(texte)).strip()
    return texte[:limite]


def lien_valide(url):
    return isinstance(url, str) and url.startswith(("http://", "https://")) and len(url) < 1000


def actualiser_flux(flux_id, url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (lecteur RSS maison)"})
    with urllib.request.urlopen(req, timeout=15) as r:
        contenu = r.read(5_000_000)
    d = feedparser.parse(contenu)
    limite_age = time.time() - 60 * 86400
    with sqlite3.connect(DB) as c:
        for e in d.entries[:50]:
            lien = e.get("link", "")
            if not lien_valide(lien):
                continue
            t = e.get("published_parsed") or e.get("updated_parsed")
            date_pub = calendar.timegm(t) if t else time.time()
            if date_pub < limite_age:
                continue
            c.execute(
                "INSERT OR IGNORE INTO articles (flux_id, titre, lien, resume, date_pub) "
                "VALUES (?,?,?,?,?)",
                (flux_id, nettoyer(e.get("title", ""), 200) or "(sans titre)",
                 lien, nettoyer(e.get("summary", "")), date_pub),
            )


verrou_rss = threading.Lock()


def actualiser_tout():
    if not verrou_rss.acquire(blocking=False):  # déjà en cours
        return
    try:
        with sqlite3.connect(DB) as c:
            flux = c.execute("SELECT id, url FROM flux").fetchall()
        for flux_id, url in flux:
            try:
                actualiser_flux(flux_id, url)
            except Exception as e:
                print(f"RSS {url} : {e}")
        with sqlite3.connect(DB) as c:
            c.execute("DELETE FROM articles WHERE date_pub < ?", (time.time() - 60 * 86400,))
    finally:
        verrou_rss.release()


def boucle_rss():
    time.sleep(10)
    while True:
        actualiser_tout()
        time.sleep(1800)


@app.route("/rss")
def page_rss():
    return render_template("rss.html", page="rss")


@app.route("/api/flux", methods=["GET"])
def api_flux():
    with sqlite3.connect(DB) as c:
        lignes = c.execute(
            "SELECT f.id, f.nom, f.url, f.categorie, "
            "(SELECT COUNT(*) FROM articles a WHERE a.flux_id = f.id AND a.lu = 0) "
            "FROM flux f ORDER BY f.nom"
        ).fetchall()
    return jsonify([{"id": i, "nom": n, "url": u, "categorie": cat, "non_lus": nl}
                    for i, n, u, cat, nl in lignes])


@app.route("/api/flux", methods=["POST"])
def api_flux_ajouter():
    d = request.get_json(silent=True) or {}
    url = (d.get("url") or "").strip()
    nom = (d.get("nom") or "").strip()[:80] or url[:80]
    categorie = (d.get("categorie") or "").strip()[:40] or None
    if not lien_valide(url):
        return jsonify({"erreur": "Adresse invalide (http ou https)."}), 400
    try:
        with sqlite3.connect(DB) as c:
            flux_id = c.execute("INSERT INTO flux (nom, url, categorie) VALUES (?,?,?)",
                                (nom, url, categorie)).lastrowid
    except sqlite3.IntegrityError:
        return jsonify({"erreur": "Ce flux est déjà ajouté."}), 409
    try:
        actualiser_flux(flux_id, url)
    except Exception as e:
        return jsonify({"ok": True, "avertissement": f"Flux ajouté, mais illisible pour l'instant : {e}"}), 201
    return jsonify({"ok": True}), 201


@app.route("/api/flux/<int:id_>", methods=["DELETE"])
def api_flux_supprimer(id_):
    with sqlite3.connect(DB) as c:
        c.execute("DELETE FROM articles WHERE flux_id = ?", (id_,))
        c.execute("DELETE FROM flux WHERE id = ?", (id_,))
    return jsonify({"ok": True})


@app.route("/api/articles")
def api_articles():
    flux_id = request.args.get("flux", type=int)
    limite = min(request.args.get("limite", 50, type=int), 200)
    sql = ("SELECT a.id, a.titre, a.lien, a.resume, a.date_pub, a.lu, f.nom, f.categorie "
           "FROM articles a JOIN flux f ON f.id = a.flux_id WHERE 1=1")
    params = []
    if request.args.get("non_lus") == "1":
        sql += " AND a.lu = 0"
    if flux_id:
        sql += " AND a.flux_id = ?"
        params.append(flux_id)
    sql += " ORDER BY a.date_pub DESC LIMIT ?"
    params.append(limite)
    with sqlite3.connect(DB) as c:
        lignes = c.execute(sql, params).fetchall()
    return jsonify([{"id": i, "titre": t, "lien": l, "resume": r, "date_pub": d,
                     "lu": bool(lu), "flux": n, "categorie": cat}
                    for i, t, l, r, d, lu, n, cat in lignes])


@app.route("/api/articles/<int:id_>/lu", methods=["POST"])
def api_article_lu(id_):
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE articles SET lu = 1 WHERE id = ?", (id_,))
    return jsonify({"ok": True})


@app.route("/api/articles/tout-lu", methods=["POST"])
def api_articles_tout_lu():
    flux_id = (request.get_json(silent=True) or {}).get("flux")
    with sqlite3.connect(DB) as c:
        if isinstance(flux_id, int):
            c.execute("UPDATE articles SET lu = 1 WHERE flux_id = ?", (flux_id,))
        else:
            c.execute("UPDATE articles SET lu = 1")
    return jsonify({"ok": True})


@app.route("/api/rss/actualiser", methods=["POST"])
def api_rss_actualiser():
    threading.Thread(target=actualiser_tout, daemon=True).start()
    return jsonify({"ok": True})

# ---------- Sauvegarde de la base ----------
DOSSIER_SAUVEGARDES = os.path.join(os.path.dirname(os.path.abspath(DB)), "sauvegardes")
SAUVEGARDES_GARDEES = 7


def sauvegarder_base():
    """Une copie par jour. Renvoie True si une nouvelle sauvegarde a été créée."""
    os.makedirs(DOSSIER_SAUVEGARDES, exist_ok=True)
    chemin = os.path.join(DOSSIER_SAUVEGARDES,
                          f"supervision-{datetime.now().strftime('%Y-%m-%d')}.db")
    if os.path.exists(chemin):
        return False
    tmp = chemin + ".tmp"
    src, dst = sqlite3.connect(DB), sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.replace(tmp, chemin)
    for ancienne in sorted(glob.glob(os.path.join(DOSSIER_SAUVEGARDES, "supervision-*.db")))[:-SAUVEGARDES_GARDEES]:
        os.remove(ancienne)
    print("Sauvegarde créée :", chemin)
    return True


def boucle_sauvegarde():
    time.sleep(60)
    while True:
        try:
            sauvegarder_base()
        except Exception as e:
            alerte(f"⚠️ Échec de la sauvegarde de la base : {e}")
        time.sleep(6 * 3600)

if __name__ == "__main__":
    init_db()
    threading.Thread(target=alerte_demarrage, daemon=True).start()
    threading.Thread(target=boucle_surveillance, daemon=True).start()
    threading.Thread(target=boucle_rss, daemon=True).start()
    threading.Thread(target=boucle_sauvegarde, daemon=True).start()
    bbox.start()
    # debug=False : sinon le rechargeur lancerait deux threads de ping
    app.run(host="0.0.0.0", port=5000, debug=False)
