/**
 * notifications.js - shared notification bell, loaded by every page.
 * Each page provides the same markup (#notif-bell-wrap, #notif-dropdown,
 * #notif-list, #notif-badge) - this file just fetches and renders into it.
 */

async function loadNotifications() {
  try {
    const data = await fetch("/api/notifications").then(r => r.json());
    renderNotifications(data);
  } catch (e) {
    // Server not reachable yet - stay quiet, next load will retry.
  }
}

function renderNotifications(data) {
  const badge = document.getElementById("notif-badge");
  if (!badge) return; // page doesn't have the bell (shouldn't happen, but stay safe)

  if (data.unread_count > 0) {
    badge.textContent = data.unread_count;
    badge.style.display = "inline-block";
  } else {
    badge.style.display = "none";
  }

  const lowStockHtml = data.low_stock.map(p => `
    <div class="notif-item notif-warn">
      <div>Stock faible : ${p.name}</div>
      <div class="notif-sub">${p.stock_qty} restant(s)</div>
    </div>
  `).join("");

  const expiringSoonHtml = (data.expiring_soon || []).map(p => `
    <div class="notif-item notif-warn">
      <div>Expire bientot : ${p.name}</div>
      <div class="notif-sub">${new Date(p.expiry_date).toLocaleDateString("fr-FR")}</div>
    </div>
  `).join("");

  const eventsHtml = data.events.map(e => `
    <div class="notif-item ${e.read ? "" : "notif-unread"}">
      <div>${e.message}</div>
      <div class="notif-sub">${new Date(e.created_at).toLocaleString("fr-FR")}</div>
    </div>
  `).join("");

  const list = document.getElementById("notif-list");
  list.innerHTML = (lowStockHtml + expiringSoonHtml + eventsHtml) || `<div class="notif-empty">Aucune notification</div>`;
}

function toggleNotifDropdown() {
  document.getElementById("notif-dropdown").classList.toggle("show");
}

async function markAllNotificationsRead() {
  await fetch("/api/notifications/read-all", { method: "POST" });
  await loadNotifications();
}

document.addEventListener("click", (event) => {
  const wrap = document.getElementById("notif-bell-wrap");
  const dropdown = document.getElementById("notif-dropdown");
  if (wrap && dropdown && !wrap.contains(event.target)) {
    dropdown.classList.remove("show");
  }
});

loadNotifications();
