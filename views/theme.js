/**
 * theme.js - shared appearance engine for all pages.
 * Served at /theme.js (Flask serves views/ as static root).
 *
 * Deliberately scoped to ONE customizable color (the brand/primary accent)
 * plus light/dark/auto mode - not a full 9-token design system. This is
 * what actually matters for a real business; anything more is speculative
 * design-system infrastructure with no current payoff.
 */

/**
 * License gate: every /api/* route except /api/license/* is protected
 * server-side (see controllers/license_routes.py). If the license expires,
 * gets revoked, or the device check fails while the app is already open,
 * those calls start returning 403 with a license_error field. Catch that
 * globally so the user gets bounced to the activation screen instead of
 * every page silently breaking.
 */
(function installLicenseGate() {
  const originalFetch = window.fetch;
  window.fetch = async function (...args) {
    const response = await originalFetch(...args);
    if (response.status === 403) {
      const clone = response.clone();
      clone.json().then((data) => {
        if (data && data.license_error) {
          window.location.href = "/license.html";
        }
      }).catch(() => {});
    }
    return response;
  };
})();

function hexToRgba(hex, alpha) {
  const clean = (hex || "#1F4B3F").replace("#", "");
  const r = parseInt(clean.slice(0, 2), 16);
  const g = parseInt(clean.slice(2, 4), 16);
  const b = parseInt(clean.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function applyTheme(mode, accentColor) {
  const effectiveMode = mode === "auto"
    ? (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    : mode;
  const isDark = effectiveMode === "dark";
  const accent = accentColor || "#1F4B3F";

  const palette = isDark
    ? { bg: "#17181C", surface: "#1F2126", border: "#33353B", text: "#EDEDEE", textMuted: "#9B9DA3" }
    : { bg: "#F7F6F2", surface: "#FFFFFF", border: "#DEDBD1", text: "#1C1B18", textMuted: "#78766C" };

  const root = document.documentElement.style;
  root.setProperty("--bg", palette.bg);
  root.setProperty("--surface", palette.surface);
  root.setProperty("--border", palette.border);
  root.setProperty("--text", palette.text);
  root.setProperty("--text-muted", palette.textMuted);
  root.setProperty("--accent", accent);
  root.setProperty("--accent-light", hexToRgba(accent, isDark ? 0.22 : 0.14));
  root.setProperty("--danger", "#B23A2E");
  root.setProperty("--danger-light", hexToRgba("#B23A2E", isDark ? 0.24 : 0.1));
  root.setProperty("--warn", "#B98A2E");
  root.setProperty("--warn-light", hexToRgba("#B98A2E", isDark ? 0.24 : 0.1));

  // Cache the raw (unresolved) mode/accent, not the computed isDark - so
  // "auto" mode gets re-evaluated against the OS preference on next load
  // rather than getting stuck on whatever it resolved to this time.
  try {
    localStorage.setItem("cm_theme", JSON.stringify({ mode, accent }));
  } catch (e) {
    // localStorage unavailable (rare) - falls back to the async fetch
    // path in initTheme(), just without the instant pre-paint benefit.
  }
}

function applyBrandFont(fontId) {
  if (!fontId || fontId === "Inter") return; // Inter-ish default is already the page's base font stack, skip the network fetch
  if (!document.getElementById("google-font-link")) {
    const link = document.createElement("link");
    link.id = "google-font-link";
    link.rel = "stylesheet";
    document.head.appendChild(link);
  }
  document.getElementById("google-font-link").href =
    `https://fonts.googleapis.com/css2?family=${fontId.replace(/ /g, "+")}:wght@400;500;600;700&display=swap`;
  document.documentElement.style.setProperty("--font-family", `'${fontId}', -apple-system, "Segoe UI", Roboto, sans-serif`);
  document.body.style.fontFamily = "var(--font-family)";
}

function applyBrandChrome(settings) {
  document.documentElement.style.setProperty("--brand-secondary", settings.brand_secondary_color || "#78766C");
  applyBrandFont(settings.brand_font);

  // Show the uploaded logo (if any) next to the "Commerce manager" text in
  // every page's sidebar, without needing each page to implement this itself.
  const brandEl = document.querySelector(".sidebar .brand");
  if (brandEl && settings.company_logo_filename && !brandEl.dataset.logoApplied) {
    brandEl.dataset.logoApplied = "1";
    const img = document.createElement("img");
    img.src = `/uploads/company/${settings.company_logo_filename}`;
    img.alt = "";
    img.style.cssText = "height:22px;max-width:100%;object-fit:contain;display:block;margin-bottom:4px;";
    brandEl.prepend(img);
  }
}

async function initTheme() {
  try {
    const settings = await fetch("/api/settings").then(r => r.json());
    const mode = settings.theme_mode || "light";
    const accent = settings.theme_accent || "#1F4B3F";
    applyTheme(mode, accent);
    applyBrandChrome(settings);

    if (mode === "auto" && window.matchMedia) {
      window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => applyTheme("auto", accent));
    }
  } catch (e) {
    // Server not reachable yet - keep the page's built-in default light theme.
  }
}

initTheme();

/**
 * Staff PIN session ("Changer d'utilisateur").
 *
 * Optional, owner-triggered layer on top of the existing full-access
 * default (see controllers/staff_session.py for the server-side half).
 * When no staff session is active, nothing here changes anything - every
 * page and sidebar link behaves exactly as before. Once the owner hands
 * off to an employee via PIN, this hides sidebar links their role can't
 * use and bounces them off any page they navigate to directly.
 */
const PAGE_KEY_BY_HREF = {
  "dashboard.html": "dashboard", "index.html": "pos", "management.html": "management",
  "staff.html": "staff", "documents.html": "documents", "branding.html": "branding",
  "settings.html": "settings",
};
const PAGE_LABELS = {
  dashboard: "Accueil", pos: "Caisse", management: "Gestion", staff: "Personnel",
  documents: "Documents", branding: "Branding", settings: "Parametres",
};

function injectStaffSessionStyles() {
  const style = document.createElement("style");
  style.textContent = `
    .staff-session-row { padding: 10px 12px; border-top: 1px solid var(--border); margin-top: 8px; font-size: 12px; color: var(--text-muted); cursor: pointer; }
    .staff-session-row:hover { color: var(--accent); }
    .staff-session-row .name { font-weight: 600; color: var(--text); display: block; }
    .staff-modal-overlay { display: none; position: fixed; inset: 0; background: rgba(28,27,24,0.5); align-items: center; justify-content: center; z-index: 500; }
    .staff-modal-overlay.show { display: flex; }
    .staff-modal { background: var(--surface); border-radius: 14px; padding: 24px; width: 320px; max-height: 80vh; overflow-y: auto; }
    .staff-modal h3 { margin: 0 0 14px; font-size: 15px; }
    .staff-emp-btn { display: block; width: 100%; text-align: left; padding: 10px 12px; border-radius: 8px; border: 1px solid var(--border); background: var(--bg); margin-bottom: 6px; cursor: pointer; font-size: 13px; font-family: inherit; color: var(--text); }
    .staff-emp-btn:hover { border-color: var(--accent); }
    .staff-owner-btn { display: block; width: 100%; text-align: center; padding: 10px 12px; border-radius: 8px; border: none; background: var(--accent-light); color: var(--accent); margin-bottom: 6px; cursor: pointer; font-size: 13px; font-weight: 600; font-family: inherit; }
    .staff-pin-dots { display: flex; justify-content: center; gap: 10px; margin: 16px 0; }
    .staff-pin-dot { width: 12px; height: 12px; border-radius: 50%; border: 1.5px solid var(--border); }
    .staff-pin-dot.filled { background: var(--accent); border-color: var(--accent); }
    .staff-pin-pad { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
    .staff-pin-pad button { padding: 14px; border-radius: 8px; border: 1px solid var(--border); background: var(--bg); font-size: 16px; cursor: pointer; color: var(--text); }
    .staff-pin-pad button:hover { border-color: var(--accent); }
    .staff-pin-error { color: var(--danger); font-size: 12px; text-align: center; min-height: 16px; margin-top: 6px; }
    .staff-back-link { display: block; text-align: center; font-size: 12px; color: var(--text-muted); margin-top: 12px; cursor: pointer; }
  `;
  document.head.appendChild(style);
}

function injectStaffModal() {
  const overlay = document.createElement("div");
  overlay.className = "staff-modal-overlay";
  overlay.id = "staff-modal-overlay";
  overlay.innerHTML = `<div class="staff-modal" id="staff-modal-content"></div>`;
  document.body.appendChild(overlay);
}

let staffEmployees = [];
let staffPinBuffer = "";
let staffPinTargetId = null;

function openStaffModal() {
  document.getElementById("staff-modal-overlay").classList.add("show");
  renderStaffPicker();
}
function closeStaffModal() {
  document.getElementById("staff-modal-overlay").classList.remove("show");
}

async function renderStaffPicker() {
  if (!staffEmployees.length) {
    staffEmployees = await fetch("/api/staff-session/employees").then(r => r.json()).catch(() => []);
  }
  const current = await fetch("/api/staff-session/current").then(r => r.json()).catch(() => ({ active: false }));

  const el = document.getElementById("staff-modal-content");
  el.innerHTML = `
    <h3>Changer d'utilisateur</h3>
    ${current.active ? `<button class="staff-owner-btn" onclick="staffLogout()">Revenir en mode Proprietaire</button>` : ""}
    ${staffEmployees
      .filter(e => !current.active || e.id !== current.employee_id)
      .map(e => `<button class="staff-emp-btn" onclick="startPinEntry('${e.id}', '${e.name.replace(/'/g, "\\'")}')">${e.name}</button>`)
      .join("") || `<div style="font-size:12px;color:var(--text-muted)">Aucun employe avec code PIN configure.</div>`}
    <div class="staff-back-link" onclick="closeStaffModal()">Fermer</div>
  `;
}

function startPinEntry(employeeId, name) {
  staffPinTargetId = employeeId;
  staffPinBuffer = "";
  const el = document.getElementById("staff-modal-content");
  el.innerHTML = `
    <h3>${name}</h3>
    <div class="staff-pin-dots" id="staff-pin-dots"></div>
    <div class="staff-pin-pad">
      ${[1,2,3,4,5,6,7,8,9].map(n => `<button onclick="staffPinPress('${n}')">${n}</button>`).join("")}
      <button onclick="staffPinClear()">Effacer</button>
      <button onclick="staffPinPress('0')">0</button>
      <button onclick="staffPinBackspace()">&larr;</button>
    </div>
    <div class="staff-pin-error" id="staff-pin-error"></div>
    <div class="staff-back-link" onclick="renderStaffPicker()">Retour</div>
  `;
  renderPinDots();
}

function renderPinDots() {
  const el = document.getElementById("staff-pin-dots");
  if (!el) return;
  el.innerHTML = [0, 1, 2, 3].map(i =>
    `<div class="staff-pin-dot ${i < staffPinBuffer.length ? "filled" : ""}"></div>`
  ).join("");
}

async function staffPinPress(digit) {
  if (staffPinBuffer.length >= 4) return;
  staffPinBuffer += digit;
  renderPinDots();
  if (staffPinBuffer.length === 4) {
    const res = await fetch("/api/staff-session/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ employee_id: staffPinTargetId, pin: staffPinBuffer }),
    });
    const data = await res.json();
    if (!res.ok) {
      document.getElementById("staff-pin-error").textContent = data.error || "Code incorrect";
      staffPinBuffer = "";
      renderPinDots();
      return;
    }
    closeStaffModal();
    applyStaffSessionUI(data);
    redirectIfPageNotPermitted(data.permitted_pages);
  }
}
function staffPinBackspace() { staffPinBuffer = staffPinBuffer.slice(0, -1); renderPinDots(); }
function staffPinClear() { staffPinBuffer = ""; renderPinDots(); }

async function staffLogout() {
  await fetch("/api/staff-session/logout", { method: "POST" });
  closeStaffModal();
  window.location.href = "dashboard.html";
}

function applyStaffSessionUI(current) {
  const wrap = document.getElementById("staff-session-row");
  if (!wrap) return;
  wrap.innerHTML = current.active
    ? `<span class="name">${current.name}</span>${current.role_name || "Employe"} - changer`
    : `<span class="name">Mode Proprietaire</span>Acces complet - changer d'utilisateur`;

  // Hide sidebar links the current session isn't permitted to see.
  document.querySelectorAll(".sidebar a[href]").forEach(a => {
    const href = a.getAttribute("href");
    const pageKey = PAGE_KEY_BY_HREF[href];
    if (!pageKey) return; // not a page link (e.g. none here, but safe)
    a.style.display = current.permitted_pages.includes(pageKey) ? "" : "none";
  });
}

function redirectIfPageNotPermitted(permittedPages) {
  const currentFile = location.pathname.split("/").pop();
  const pageKey = PAGE_KEY_BY_HREF[currentFile];
  if (pageKey && !permittedPages.includes(pageKey)) {
    const fallback = permittedPages[0] ? Object.keys(PAGE_KEY_BY_HREF).find(f => PAGE_KEY_BY_HREF[f] === permittedPages[0]) : null;
    window.location.href = fallback || "index.html";
  }
}

async function initStaffSession() {
  const brandEl = document.querySelector(".sidebar .notif-bell-wrap");
  if (!brandEl) return; // page without the shared sidebar (e.g. license.html)

  injectStaffSessionStyles();
  injectStaffModal();

  const row = document.createElement("div");
  row.className = "staff-session-row";
  row.id = "staff-session-row";
  row.onclick = openStaffModal;
  brandEl.insertAdjacentElement("beforebegin", row);

  try {
    const current = await fetch("/api/staff-session/current").then(r => r.json());
    applyStaffSessionUI(current);
    redirectIfPageNotPermitted(current.permitted_pages);
  } catch (e) {
    // Server not reachable yet - leave full access in place, nothing to restrict.
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initStaffSession);
} else {
  initStaffSession();
}
