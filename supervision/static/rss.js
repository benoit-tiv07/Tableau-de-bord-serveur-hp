const $ = s => document.querySelector(s);

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML.replace(/"/g, "&quot;");
}

function quand(ts) {
  const diff = Date.now() / 1000 - ts;
  if (diff < 3600) return Math.max(1, Math.round(diff / 60)) + " min";
  if (diff < 86400) return Math.round(diff / 3600) + " h";
  return Math.round(diff / 86400) + " j";
}

async function chargerFlux() {
  const flux = await (await fetch("/api/flux")).json();
  const sel = $("#filtreFlux");
  const courant = sel.value;
  sel.innerHTML = `<option value="">Tous les flux</option>` +
    flux.map(f => `<option value="${f.id}">${esc(f.nom)} (${f.non_lus})</option>`).join("");
  sel.value = courant;
  $("#listeFlux").innerHTML = flux.length ? flux.map(f => `
    <li class="devoir">
      <span class="devoir-titre">${esc(f.nom)}</span>
      ${f.categorie ? `<span class="tag">${esc(f.categorie)}</span>` : ""}
      <span class="muted">${f.non_lus} non lu${f.non_lus > 1 ? "s" : ""}</span>
      <button type="button" class="suppr" data-id="${f.id}" title="Retirer ce flux">✕</button>
    </li>`).join("") : `<li class="muted">Aucun flux pour l'instant.</li>`;
}

async function chargerArticles() {
  const params = new URLSearchParams({ limite: 100 });
  if ($("#nonLus").checked) params.set("non_lus", "1");
  if ($("#filtreFlux").value) params.set("flux", $("#filtreFlux").value);
  const articles = await (await fetch("/api/articles?" + params)).json();
  $("#articles").innerHTML = articles.length ? articles.map(a => `
    <li class="article ${a.lu ? "lu" : ""}">
      <a href="${esc(a.lien)}" target="_blank" rel="noopener noreferrer" data-id="${a.id}">${esc(a.titre)}</a>
      <div class="muted">${esc(a.flux)}${a.categorie ? " · " + esc(a.categorie) : ""} · il y a ${quand(a.date_pub)}</div>
      ${a.resume ? `<p class="resume">${esc(a.resume)}</p>` : ""}
    </li>`).join("") : `<li class="muted">Aucun article.</li>`;
}

async function toutRecharger() {
  try {
    await chargerFlux();
    await chargerArticles();
  } catch (e) {
    $("#articles").innerHTML = `<li class="muted">Serveur injoignable</li>`;
  }
}

function marquerLu(ev) {
  const lien = ev.target.closest("a[data-id]");
  if (!lien) return;
  fetch(`/api/articles/${lien.dataset.id}/lu`, { method: "POST", keepalive: true });
  lien.closest("li").classList.add("lu");
}
$("#articles").addEventListener("click", marquerLu);
$("#articles").addEventListener("auxclick", marquerLu);

$("#formFlux").addEventListener("submit", async ev => {
  ev.preventDefault();
  const f = ev.target;
  $("#messageFlux").textContent = "Ajout en cours…";
  const rep = await fetch("/api/flux", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nom: f.nom.value, url: f.url.value, categorie: f.categorie.value }),
  });
  const d = await rep.json();
  $("#messageFlux").textContent = d.erreur || d.avertissement || "Flux ajouté.";
  if (rep.ok) f.reset();
  toutRecharger();
});

$("#listeFlux").addEventListener("click", async ev => {
  if (!ev.target.matches(".suppr")) return;
  if (!confirm("Retirer ce flux et ses articles ?")) return;
  await fetch(`/api/flux/${ev.target.dataset.id}`, { method: "DELETE" });
  toutRecharger();
});

$("#filtreFlux").addEventListener("change", chargerArticles);
$("#nonLus").addEventListener("change", chargerArticles);

$("#btnToutLu").addEventListener("click", async () => {
  const flux = parseInt($("#filtreFlux").value, 10);
  await fetch("/api/articles/tout-lu", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(Number.isInteger(flux) ? { flux } : {}),
  });
  toutRecharger();
});

$("#btnActualiser").addEventListener("click", async () => {
  $("#btnActualiser").disabled = true;
  $("#messageFlux").textContent = "Actualisation en cours…";
  await fetch("/api/rss/actualiser", { method: "POST" });
  setTimeout(() => {
    $("#btnActualiser").disabled = false;
    $("#messageFlux").textContent = "";
    toutRecharger();
  }, 8000);
});

toutRecharger();
setInterval(toutRecharger, 300000);
