function horloge() {
  const n = new Date();
  document.getElementById("heure").textContent = n.toLocaleTimeString("fr-FR");
  document.getElementById("date").textContent = n.toLocaleDateString("fr-FR",
    { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

function texteMeteo(code) {
  if (code === 0) return "Ciel dégagé";
  if (code <= 2) return "Peu nuageux";
  if (code === 3) return "Couvert";
  if (code <= 48) return "Brouillard";
  if (code <= 57) return "Bruine";
  if (code <= 67) return "Pluie";
  if (code <= 77) return "Neige";
  if (code <= 82) return "Averses";
  if (code <= 86) return "Averses de neige";
  return "Orage";
}

async function meteo() {
  const bloc = document.getElementById("meteo");
  try {
    const rep = await fetch("/api/meteo");
    if (!rep.ok) throw new Error("meteo");
    const d = await rep.json();
    const c = d.current, j = d.daily;
    const jours = j.time.map((t, i) => `
      <div class="ligne">
        <span>${new Date(t).toLocaleDateString("fr-FR", { weekday: "short" })}</span>
        <span class="muted">${Math.round(j.temperature_2m_min[i])}° / ${Math.round(j.temperature_2m_max[i])}°
          · pluie ${j.precipitation_probability_max[i]} %</span>
      </div>`).join("");
    bloc.innerHTML = `
      <div class="grand">${Math.round(c.temperature_2m)} °C</div>
      <div class="muted">${texteMeteo(c.weather_code)} · ressenti ${Math.round(c.apparent_temperature)}°
        · vent ${Math.round(c.wind_speed_10m)} km/h</div>${jours}`;
  } catch (e) {
    bloc.textContent = "Météo indisponible";
  }
}

function barre(pct) {
  return `<div class="barre"><span style="width:${pct}%"></span></div>`;
}

function duree(s) {
  const j = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
  return (j ? j + " j " : "") + h + " h " + m + " min";
}

async function systeme() {
  const bloc = document.getElementById("systeme");
  try {
    const rep = await fetch("/api/systeme");
    const d = await rep.json();
    bloc.innerHTML = `
      <div class="ligne"><span>Processeur</span><span>${d.cpu} %</span></div>${barre(d.cpu)}
      <div class="ligne"><span>Mémoire</span><span>${d.ram_utilisee} / ${d.ram_totale} Go</span></div>${barre(d.ram)}
      <div class="ligne"><span>Disque</span><span>${d.disque_utilise} / ${d.disque_total} Go</span></div>${barre(d.disque)}
      <div class="ligne"><span class="muted">Allumé depuis</span><span>${duree(d.uptime)}</span></div>
      ${d.temperature !== null
        ? `<div class="ligne"><span class="muted">Température</span><span>${Math.round(d.temperature)} °C</span></div>`
        : ""}`;
  } catch (e) {
    bloc.textContent = "Infos indisponibles";
  }
}

function badge(ok) {
  return `<span class="badge ${ok ? "ok" : "ko"}">${ok ? "En ligne" : "Hors ligne"}</span>`;
}

async function machines() {
  const bloc = document.getElementById("machines");
  try {
    const rep = await fetch("/api/status");
    const d = await rep.json();
    bloc.innerHTML = d.machines.length
      ? d.machines.map(m => `
          <div class="ligne"><span>${m.nom}</span>
            <span>${badge(m.lan)} ${m.ts === null ? "" : badge(m.ts)}</span></div>`).join("")
      : "Premier relevé en cours…";
  } catch (e) {
    bloc.textContent = "Serveur injoignable";
  }
}

horloge(); setInterval(horloge, 1000);
meteo(); setInterval(meteo, 600000);
systeme(); setInterval(systeme, 10000);
machines(); setInterval(machines, 5000);

/* ---- Agenda et devoirs (liste manuelle + devoirs des calendriers) ---- */
function esc(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML.replace(/"/g, "&quot;");
}

function formatDate(iso) {
  return new Date(iso + "T00:00").toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
}

let manuels = [];
let calendrier = { agenda: [], taches: [], erreurs: [] };

async function chargerManuels() {
  try {
    manuels = await (await fetch("/api/devoirs")).json();
  } catch (e) { /* on garde l'ancienne liste */ }
  afficherDevoirs();
}

async function chargerAgenda() {
  try {
    calendrier = await (await fetch("/api/agenda")).json();
  } catch (e) {
    calendrier = { agenda: [], taches: [], erreurs: ["serveur injoignable"] };
  }
  afficherAgenda();
  afficherDevoirs();
}

function afficherAgenda() {
  const heure = d => d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  let html = calendrier.agenda.map(e => {
    const d = new Date(e.debut), f = new Date(e.fin);
    const jour = d.toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" });
    const quand = e.journee ? "Journée" : `${heure(d)} – ${heure(f)}`;
    return `<li><span class="quand">${jour} · ${quand}</span><span>${esc(e.titre)}</span></li>`;
  }).join("");
  if (!html) {
    html = `<li class="muted">${calendrier.erreurs.length
      ? "Calendrier illisible : " + esc(calendrier.erreurs[0])
      : "Aucun événement à venir (ou aucun calendrier configuré)."}</li>`;
  }
  document.getElementById("agenda").innerHTML = html;
}

function afficherDevoirs() {
  const liste = document.getElementById("devoirs");
  const aujourdhui = new Date().toLocaleDateString("sv-SE"); // AAAA-MM-JJ
  const items = [
    ...manuels.map(x => ({ ...x, source: "manuel" })),
    ...calendrier.taches.map(t => ({
      id: t.id, titre: t.titre, matiere: t.calendrier,
      echeance: t.date, fait: t.fait, source: "calendrier",
    })),
  ].sort((a, b) => (a.fait - b.fait) || (a.echeance || "9999").localeCompare(b.echeance || "9999"));

  document.getElementById("devoirsCompte").textContent =
    items.filter(x => !x.fait).length + " à faire";
  liste.innerHTML = items.length ? items.map(x => {
    const retard = !x.fait && x.echeance && x.echeance < aujourdhui;
    return `<li class="devoir ${x.fait ? "fait" : ""}">
      <input type="checkbox" data-id="${esc(String(x.id))}" data-source="${x.source}" ${x.fait ? "checked" : ""}>
      <span class="devoir-titre">${esc(x.titre)}</span>
      ${x.matiere ? `<span class="tag">${esc(x.matiere)}</span>` : ""}
      ${x.echeance ? `<span class="muted ${retard ? "retard" : ""}">${formatDate(x.echeance)}</span>` : ""}
      ${x.source === "manuel"
        ? `<button type="button" class="suppr" data-id="${x.id}" title="Supprimer">✕</button>` : ""}
    </li>`;
  }).join("") : `<li class="muted">Aucun devoir 🎉</li>`;
}

document.getElementById("devoirs").addEventListener("change", async ev => {
  if (!ev.target.matches("input[type=checkbox]")) return;
  const { id, source } = ev.target.dataset;
  if (source === "calendrier") {
    await fetch("/api/taches/basculer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    chargerAgenda();
  } else {
    await fetch(`/api/devoirs/${id}/basculer`, { method: "POST" });
    chargerManuels();
  }
});

document.getElementById("devoirs").addEventListener("click", async ev => {
  if (ev.target.matches(".suppr")) {
    await fetch(`/api/devoirs/${ev.target.dataset.id}`, { method: "DELETE" });
    chargerManuels();
  }
});

document.getElementById("formDevoir").addEventListener("submit", async ev => {
  ev.preventDefault();
  const f = ev.target;
  await fetch("/api/devoirs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ titre: f.titre.value, matiere: f.matiere.value, echeance: f.echeance.value }),
  });
  f.reset();
  chargerManuels();
});

chargerManuels();
chargerAgenda();
setInterval(chargerAgenda, 300000);

/* ---- Veille (RSS) ---- */
async function veille() {
  const bloc = document.getElementById("veille");
  try {
    const articles = await (await fetch("/api/articles?non_lus=1&limite=5")).json();
    bloc.innerHTML = articles.length
      ? articles.map(a => `<div class="veille-ligne"><a href="${esc(a.lien)}" target="_blank" rel="noopener noreferrer">${esc(a.titre)}</a></div>`).join("")
        + `<p class="muted"><a href="/rss">Tout voir</a></p>`
      : `<span class="muted">Rien de nouveau. <a href="/rss">Gérer les flux</a></span>`;
  } catch (e) {
    bloc.textContent = "Veille indisponible";
  }
}
veille();
setInterval(veille, 300000);
