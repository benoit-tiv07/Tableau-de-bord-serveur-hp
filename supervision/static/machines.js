function badge(ok) {
  return `<span class="badge ${ok ? "ok" : "ko"}">${ok ? "En ligne" : "Hors ligne"}</span>`;
}

async function rafraichir() {
  try {
    const rep = await fetch("/api/status");
    const data = await rep.json();
    document.getElementById("maj").textContent =
      data.maj ? "Dernier relevé : " + data.maj : "Premier relevé en cours…";
    document.getElementById("liste").innerHTML = data.machines.map(m => `
      <div class="carte">
        <h2>${m.nom}</h2>
        <div class="ligne">
          <span>Local <span class="ip">${m.ip_lan}</span></span>${badge(m.lan)}
        </div>
        ${m.ip_ts ? `
        <div class="ligne">
          <span>Tailscale <span class="ip">${m.ip_ts}</span></span>${badge(m.ts)}
        </div>` : ""}
      </div>`).join("");
  } catch (e) {
    document.getElementById("maj").textContent = "Serveur injoignable";
  }
}

async function historique() {
  const rep = await fetch("/api/historique");
  const data = await rep.json();
  document.getElementById("histo").innerHTML = data.map(e =>
    `<div>${e.date} · ${e.machine} (${e.reseau}) : ${e.en_ligne ? "🟢 en ligne" : "🔴 hors ligne"}</div>`
  ).join("");
}

historique();
setInterval(historique, 15000);

rafraichir();
setInterval(rafraichir, 5000);
