/* Punto de venta — tienda de celulares y accesorios */
"use strict";

const S = {
  settings: {},
  categories: [],
  templates: {},
  rounding: {},
  cart: [],
  cartDiscount: 0,
  customer: { name: "", phone: "", model: "", imei: "", seller: "" },
  me: null,
  sellers: [],
  pendingId: null,      // nota pendiente que el cajero está cobrando
  pendingFolio: "",
  pendingNotes: "",
  labelQueue: [],
  labelSel: 0,
  view: "vender",
};

/* ------------------------------------------------------------------ utilidades */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v) => { const n = parseFloat(String(v ?? "").replace(/[,$\s]/g, "")); return Number.isFinite(n) ? n : 0; };
const r2 = (v) => Math.round((v + Number.EPSILON) * 100) / 100;
const money = (v) => (S.settings.currency_symbol || "$") + Number(v || 0).toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const today = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };
const WARRANTY_OPTS = [[0, "Sin garantía"], [7, "7 días"], [15, "15 días"], [30, "1 mes"], [90, "3 meses"], [180, "6 meses"], [365, "1 año"]];
function warrantyLabel(days) {
  days = Math.round(num(days));
  if (days <= 0) return "Sin garantía";
  if (days % 365 === 0) return `${days / 365} año${days > 365 ? "s" : ""}`;
  if (days % 30 === 0) return `${days / 30} mes${days > 30 ? "es" : ""}`;
  return `${days} día${days > 1 ? "s" : ""}`;
}
const warrantyOptions = (sel) => {
  // sel "" = todavía no se elige (productos nuevos): hay que escoger una, aunque sea "Sin garantía"
  if (sel === "" || sel === null || sel === undefined) return `<option value="" selected>— Elige la garantía —</option>` + warrantyOptions(-1).replace(/ selected/g, "");
  const opts = WARRANTY_OPTS.some(([d]) => d === Math.round(num(sel))) || num(sel) < 0 ? WARRANTY_OPTS : [...WARRANTY_OPTS, [Math.round(num(sel)), warrantyLabel(sel)]];
  return opts.map(([d, t]) => `<option value="${d}" ${d === Math.round(num(sel)) ? "selected" : ""}>${t}</option>`).join("");
};
const can = (...roles) => S.me && roles.includes(S.me.role);
const serialOptions = (sel) =>
  (sel === "" || sel === null || sel === undefined ? '<option value="" selected>— Elige —</option>' : "") +
  `<option value="0" ${String(sel) === "0" ? "selected" : ""}>Sin serie</option><option value="1" ${String(sel) === "1" ? "selected" : ""}>Con serie</option>`;
const branchOptions = (sel, { all = true, current = true } = {}) =>
  (current ? `<option value="">${esc(S.me.branch.name)} (esta)</option>` : "") +
  (all ? `<option value="all" ${sel === "all" ? "selected" : ""}>Todas las sucursales</option>` : "") +
  S.branches.filter((b) => b.active && (!current || b.id !== S.me.branch.id)).map((b) => `<option value="${b.id}" ${String(sel) === String(b.id) ? "selected" : ""}>${esc(b.name)}</option>`).join("");
const branchParam = (id) => { const v = $(id)?.value; return v ? `&branch=${v}` : ""; };
const sellerOnly = () => can("vendedor") && S.settings.seller_can_charge !== "1";
const changesOptions = (sel) => [0, 1, 2, 3, 4, 5, 6].map((n) => `<option value="${n}" ${n === Math.round(num(sel)) ? "selected" : ""}>${n ? n + (n > 1 ? " cambios" : " cambio") : "Sin cambios"}</option>`).join("");
const debounce = (fn, ms = 250) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const res = await fetch(url, opts);
  if (res.status === 401 && !url.includes("/api/login")) { location.href = "/login"; throw new Error("Sesión expirada"); }
  const isJson = (res.headers.get("content-type") || "").includes("json");
  const data = isJson ? await res.json() : await res.text();
  if (!res.ok) { const err = new Error((data && data.error) || `Error ${res.status}`); err.status = res.status; throw err; }
  return data;
}
const GET = (u) => api("GET", u);
const POST = (u, b = {}) => api("POST", u, b);
const PUT = (u, b = {}) => api("PUT", u, b);
const DEL = (u) => api("DELETE", u);

function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), kind === "bad" ? 6000 : 3200);
}
const fail = (e) => toast(e.message || String(e), "bad");

function beep(ok = true) {
  try {
    const ctx = beep.ctx || (beep.ctx = new (window.AudioContext || window.webkitAudioContext)());
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.frequency.value = ok ? 1250 : 220; o.type = "square"; g.gain.value = 0.04;
    o.connect(g); g.connect(ctx.destination); o.start(); o.stop(ctx.currentTime + (ok ? 0.07 : 0.25));
  } catch (_) { /* sin audio */ }
}

function download(filename, text, type = "text/plain") {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

function openTicketWindow(url) {
  const w = window.open(url, "ticket", "width=420,height=720");
  if (!w) toast("El navegador bloqueó la ventana del ticket. Permite ventanas emergentes para este sitio.", "bad");
}

/* ------------------------------------------------------------------ modales */
function modal({ title, body, foot = "", size = "", onOpen }) {
  const back = document.createElement("div");
  back.className = "modal-back";
  back.innerHTML = `<div class="modal ${size}" role="dialog" aria-modal="true">
    <div class="modal-head"><h2>${title}</h2><button class="close-x" data-close aria-label="Cerrar">×</button></div>
    <div class="modal-body">${body}</div>${foot ? `<div class="modal-foot">${foot}</div>` : ""}</div>`;
  const close = () => { back.remove(); if (S.view === "vender") focusScan(); };
  back.addEventListener("mousedown", (e) => { if (e.target === back) close(); });
  back.addEventListener("click", (e) => { if (e.target.closest("[data-close]")) close(); });
  $("#modal-root").appendChild(back);
  const m = back.querySelector(".modal");
  m.close = close;
  if (onOpen) onOpen(m, close);
  const first = m.querySelector("[autofocus]") || m.querySelector("input, select, textarea");
  if (first) setTimeout(() => first.focus(), 30);
  return m;
}
const topModal = () => { const all = $$(".modal-back"); return all.length ? all[all.length - 1].querySelector(".modal") : null; };

function confirmBox(message, okText = "Aceptar", danger = false) {
  return new Promise((resolve) => {
    modal({
      title: "Confirmar", size: "narrow", body: `<p>${message}</p>`,
      foot: `<button data-close>Cancelar</button><button class="${danger ? "danger" : "primary"}" id="cf-ok">${okText}</button>`,
      onOpen: (m, close) => {
        $("#cf-ok", m).onclick = () => { close(); resolve(true); };
        $$("[data-close]", m).forEach((b) => b.addEventListener("click", () => resolve(false)));
        setTimeout(() => $("#cf-ok", m).focus(), 40);
      },
    });
  });
}

function promptBox(title, label, value = "") {
  return new Promise((resolve) => {
    modal({
      title, size: "narrow", body: `<label class="f">${label}<input id="pb-in" value="${esc(value)}" autofocus></label>`,
      foot: `<button data-close>Cancelar</button><button class="primary" id="pb-ok">Aceptar</button>`,
      onOpen: (m, close) => {
        const done = () => { const v = $("#pb-in", m).value; close(); resolve(v); };
        $("#pb-ok", m).onclick = done;
        $("#pb-in", m).addEventListener("keydown", (e) => { if (e.key === "Enter") done(); });
        $$("[data-close]", m).forEach((b) => b.addEventListener("click", () => resolve(null)));
      },
    });
  });
}

/* ------------------------------------------------------------------ buscador de productos reutilizable */
function attachProductSearch(input, onPick, { lookupFirst = true, allowFreeEnter = false } = {}) {
  const box = input.parentElement;
  let dd = null, results = [], sel = 0;
  const closeDd = () => { if (dd) { dd.remove(); dd = null; } };
  const render = () => {
    closeDd();
    if (!results.length) return;
    dd = document.createElement("div");
    dd.className = "dropdown";
    dd.innerHTML = results.map((p, i) => `<div class="opt ${i === sel ? "sel" : ""}" data-i="${i}">
        <div class="grow"><div class="name">${esc(p.name)}</div>
        <div class="small muted mono">${esc(p.sku)} · ${esc(p.barcode || "")}${p.category_name ? " · " + esc(p.category_name) : ""}</div></div>
        <span class="badge ${p.track_stock && p.stock <= 0 ? "bad" : p.track_stock && p.stock <= p.min_stock ? "warn" : "ok"}">${p.track_stock ? "Exist. " + Number(p.stock) : "Servicio"}</span>
        <b class="nowrap">${money(p.price)}</b></div>`).join("");
    dd.addEventListener("mousedown", (e) => {
      const o = e.target.closest(".opt"); if (!o) return;
      e.preventDefault(); pick(results[+o.dataset.i], null);
    });
    box.appendChild(dd);
  };
  const pick = (p, imei) => { closeDd(); results = []; input.value = ""; onPick(p, imei); };
  const search = debounce(async () => {
    const q = input.value.trim();
    if (q.length < 2) { results = []; closeDd(); return; }
    try { results = await GET(`/api/products?limit=15&q=${encodeURIComponent(q)}`); sel = 0; render(); } catch (e) { fail(e); }
  }, 200);
  input.addEventListener("input", search);
  input.addEventListener("blur", () => setTimeout(closeDd, 150));
  input.addEventListener("keydown", async (e) => {
    if (e.key === "ArrowDown" && results.length) { e.preventDefault(); sel = (sel + 1) % results.length; render(); }
    else if (e.key === "ArrowUp" && results.length) { e.preventDefault(); sel = (sel - 1 + results.length) % results.length; render(); }
    else if (e.key === "Escape") { closeDd(); }
    else if (e.key === "Enter") {
      e.preventDefault();
      const code = input.value.trim();
      if (!code) return;
      if (dd && results[sel] && !lookupFirst) return pick(results[sel], null);
      if (lookupFirst) {
        try {
          const r = await GET(`/api/lookup?code=${encodeURIComponent(code)}`);
          beep(true);
          return pick(r.product, r.imei);
        } catch (err) {
          // 409 = IMEI ya vendido o en otra sucursal: se avisa y no se busca por nombre
          if (err.status === 409) { beep(false); fail(err); input.select(); return; }
          if (dd && results[sel]) return pick(results[sel], null);
          try {
            const list = await GET(`/api/products?limit=15&q=${encodeURIComponent(code)}`);
            if (list.length === 1) return pick(list[0], null);
            if (list.length) { results = list; sel = 0; render(); return; }
          } catch (_) { /* ignorar */ }
          beep(false);
          if (allowFreeEnter) return onPick(null, null, code);
          fail(err);
          input.select();
        }
      }
    }
  });
}

/* ------------------------------------------------------------------ navegación */
const VIEWS = {};
function go(view) {
  S.view = view;
  $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  VIEWS[view]?.();
}
$$("#nav a").forEach((a) => a.addEventListener("click", () => go(a.dataset.view)));

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { const m = topModal(); if (m) { e.preventDefault(); m.close(); } return; }
  if (e.key === "F1" && !can("matriz")) { e.preventDefault(); go("vender"); }
  if (e.key === "F3") { e.preventDefault(); go("garantias"); }
  if (S.view === "vender" && !topModal()) {
    if (e.key === "F2") { e.preventDefault(); checkout(); }
    if (e.key === "F4") { e.preventDefault(); focusScan(); }
  }
});

const ALL_ROLES = ["admin", "matriz", "cajero", "vendedor"];
const NAV_ROLES = { vender: ["admin", "cajero", "vendedor"], productos: ALL_ROLES, garantias: ALL_ROLES, etiquetas: ["admin", "matriz", "cajero"],
  inventario: ["admin", "matriz", "cajero"], ventas: ALL_ROLES, corte: ["admin", "matriz", "cajero"], config: ["admin"] };
async function loadBase() {
  S.me = await GET("/api/me");
  S.sellers = await GET("/api/sellers");
  S.branches = await GET("/api/branches");
  S.multi = S.branches.filter((b) => b.active).length > 1;
  $$("#nav a").forEach((a) => a.classList.toggle("hidden", !NAV_ROLES[a.dataset.view].includes(S.me.role)));
  $("#user-box").innerHTML = `<div><b>${esc(S.me.full_name)}</b> · ${esc(S.me.role_name)}</div>
    <div class="branch-box">📍 ${S.me.can_switch_branch && S.multi
      ? `<select id="u-branch" title="Sucursal en la que trabajas">${S.branches.filter((b) => b.active).map((b) => `<option value="${b.id}" ${b.id === S.me.branch.id ? "selected" : ""}>${esc(b.name)}</option>`).join("")}</select>`
      : `<b>${esc(S.me.branch.name)}</b>`}</div>
    <div class="row" style="margin-top:6px"><a id="u-pass" class="small">Cambiar contraseña</a><a id="u-out" class="small">Salir</a></div>`;
  const ub = $("#u-branch");
  if (ub) ub.onchange = async () => {
    if (S.cart.length && !await confirmBox("Hay un ticket en curso. ¿Cambiar de sucursal de todos modos? El ticket se vacía.", "Cambiar", true)) { ub.value = S.me.branch.id; return; }
    try { await POST("/api/branch/select", { branch_id: +ub.value }); clearCart(); location.reload(); } catch (e) { fail(e); }
  };
  $("#u-pass").onclick = () => changePassword(false);
  $("#u-out").onclick = async () => { await POST("/api/logout"); location.href = "/login"; };
  const s = await GET("/api/settings");
  S.settings = s.settings; S.templates = s.label_templates; S.rounding = s.rounding_modes;
  S.categories = await GET("/api/categories");
  $("#brand-name").textContent = S.settings.store_name || "Punto de Venta";
  document.title = `${S.settings.store_name || "Punto de Venta"} · POS`;
}
const catOptions = (selected, blank = "Sin categoría") =>
  `<option value="">${blank}</option>` + S.categories.map((c) => `<option value="${c.id}" ${String(c.id) === String(selected) ? "selected" : ""}>${esc(c.name)}</option>`).join("");
const roundingOptions = (selected) => Object.entries(S.rounding).map(([k, v]) => `<option value="${k}" ${k === String(selected) ? "selected" : ""}>${esc(v)}</option>`).join("");
const templateOptions = (selected) => Object.entries(S.templates).map(([k, v]) => `<option value="${k}" ${k === selected ? "selected" : ""}>${esc(v.name)}</option>`).join("");

/* ================================================================== VENDER */
function saveCart() { try { localStorage.setItem("pos-cart", JSON.stringify({ cart: S.cart, d: S.cartDiscount, c: S.customer, p: S.pendingId, pf: S.pendingFolio, pn: S.pendingNotes })); } catch (_) { /* */ } }
function loadCart() { try { const v = JSON.parse(localStorage.getItem("pos-cart") || "null"); if (v) { S.cart = v.cart || []; S.cartDiscount = v.d || 0; S.customer = v.c || { name: "", phone: "" }; S.pendingId = v.p || null; S.pendingFolio = v.pf || ""; S.pendingNotes = v.pn || ""; } } catch (_) { /* */ } }
const focusScan = () => setTimeout(() => $("#scan")?.focus(), 20);

function initVender() {
  const el = $("#view-vender");
  el.innerHTML = `
  <div class="pos">
    <div>
      <div class="search-box"><span class="scan-ico">🔎</span>
        <input id="scan" class="scan" autocomplete="off" placeholder="Escanea código de barras / IMEI, o escribe para buscar  (F4)">
      </div>
      <div id="pend-box" class="card pend-box hidden"></div>
      <div id="pend-banner" class="pend-banner hidden"></div>
      <div class="card cart" style="padding:0">
        <div class="table-wrap" style="max-height:calc(100vh - 190px);border:0">
          <table><thead><tr><th>Producto</th><th class="num">Precio</th><th class="center">Cant.</th><th class="num">Desc. $</th><th class="num">Importe</th><th></th></tr></thead>
          <tbody id="cart-body"></tbody></table>
        </div>
      </div>
    </div>
    <div class="card totals">
      <div class="line"><span>Artículos</span><b id="t-units">0</b></div>
      <div class="line"><span>Importe</span><span id="t-sub">$0.00</span></div>
      <div class="line"><span>Descuentos por producto</span><span id="t-ldisc">$0.00</span></div>
      <div class="line"><span>Descuento general $</span><input id="t-disc" style="width:110px;text-align:right;padding:4px 8px" value="0"></div>
      <div class="line muted small"><span id="t-tax-l">IVA incluido</span><span id="t-tax">$0.00</span></div>
      <div class="grand"><span>TOTAL</span><span id="t-total">$0.00</span></div>
      <div class="grid" style="gap:8px;margin-bottom:12px">
        <label class="f">Vendedor<select id="cust-seller"></select></label>
        <input id="cust-name" placeholder="Nombre del cliente">
        <input id="cust-phone" placeholder="Teléfono del cliente" inputmode="tel">
        <fieldset id="dev-box" class="hidden" style="margin:4px 0 0;padding:8px 10px 10px"><legend class="small">📱 Equipo del cliente (para la garantía)</legend>
          <div class="grid" style="gap:8px">
            <input id="cust-model" placeholder="Modelo, p. ej. iPhone 17 Pro Max" list="dl-models">
            <input id="cust-imei" placeholder="IMEI del equipo (*#06#)" inputmode="numeric" class="mono">
          </div></fieldset>
        <datalist id="dl-models"></datalist>
      </div>
      <button class="primary big-btn hidden" id="btn-send">📨 Enviar a caja <kbd style="border-color:#fff">F2</kbd></button>
      <button class="success big-btn" id="btn-pay">💵 Cobrar <kbd style="border-color:#fff">F2</kbd></button>
      <div class="row" style="margin-top:8px">
        <button class="danger" id="btn-clear" style="flex:1">Vaciar ticket</button>
        <button id="btn-last" style="flex:1">Último ticket</button>
      </div>
      <p class="small muted" style="margin:12px 0 0">Tip: con el lector de códigos escanea directo; Enter agrega. Los celulares se agregan escaneando su IMEI.</p>
    </div>
  </div>`;
  loadCart();
  const custFields = { name: "#cust-name", phone: "#cust-phone", model: "#cust-model", imei: "#cust-imei", seller: "#cust-seller" };
  fillSellers();
  Object.entries(custFields).forEach(([k, sel]) => {
    $(sel).value = S.customer[k] || $(sel).value || "";
    $(sel).addEventListener(sel === "#cust-seller" ? "change" : "input", (e) => { S.customer[k] = e.target.value; saveCart(); });
  });
  GET("/api/device-models").then((list) => { $("#dl-models").innerHTML = list.map((x) => `<option value="${esc(x)}">`).join(""); }).catch(() => {});
  $("#t-disc").oninput = (e) => { S.cartDiscount = num(e.target.value); saveCart(); renderTotals(); };
  $("#btn-pay").onclick = checkout;
  $("#btn-send").onclick = sendToCaja;
  $("#pend-box").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-pa]"); if (!b) return;
    const id = +b.dataset.id;
    if (b.dataset.pa === "load") return loadPending(id);
    if (b.dataset.pa === "drop" && await confirmBox(`¿Descartar la nota ${esc(b.dataset.folio)}? El cliente ya no la podrá pagar.`, "Descartar", true)) {
      try { await DEL(`/api/sales/pending/${id}`); if (S.pendingId === id) releasePending(); refreshPending(); toast("Nota descartada", "ok"); } catch (er) { fail(er); }
    }
  });
  setInterval(() => { if (S.view === "vender") refreshPending(); }, 8000);
  refreshPending();
  $("#btn-clear").onclick = async () => { if (S.cart.length && await confirmBox("¿Vaciar el ticket actual?", "Vaciar", true)) { clearCart(); } };
  $("#btn-last").onclick = async () => {
    try { const list = await GET(`/api/sales?from=2000-01-01&to=2999-12-31`); if (!list.length) return toast("Aún no hay ventas"); showSale(list[0].id); } catch (e) { fail(e); }
  };
  attachProductSearch($("#scan"), addToCart);
  renderCart();
}

function fillSellers() {
  const sel = $("#cust-seller");
  const current = S.customer.seller || String(S.me.id);
  sel.innerHTML = S.sellers.map((u) => `<option value="${u.id}" ${String(u.id) === current ? "selected" : ""}>${esc(u.full_name)}</option>`).join("");
  sel.disabled = S.me.role === "vendedor";
  if (S.me.role === "vendedor") sel.value = String(S.me.id);
}

function releasePending() { S.pendingId = null; S.pendingFolio = ""; S.pendingNotes = ""; saveCart(); renderPendingBanner(); }

function renderPendingBanner() {
  const el = $("#pend-banner"); if (!el) return;
  el.classList.toggle("hidden", !S.pendingId);
  el.innerHTML = S.pendingId ? `🧾 Cobrando la nota <b class="mono">${esc(S.pendingFolio)}</b>. Puedes ajustarla antes de cobrar. <button class="sm" id="pend-release">Soltar nota</button>` : "";
  const b = $("#pend-release"); if (b) b.onclick = () => { clearCart(); toast("La nota sigue pendiente en caja"); };
  $("#btn-clear").textContent = S.pendingId ? "Soltar nota" : "Vaciar ticket";
}

async function refreshPending() {
  const box = $("#pend-box"); if (!box || !S.me) return;
  let list;
  try { list = await GET("/api/sales/pending"); } catch (_) { return; }
  const staff = !sellerOnly();
  const navBadge = $('#nav a[data-view="vender"] .nav-badge');
  if (navBadge) { navBadge.textContent = list.length; navBadge.classList.toggle("hidden", !staff || !list.length); }
  if (!list.length) { box.classList.add("hidden"); box.innerHTML = ""; return; }
  box.classList.remove("hidden");
  const ago = (ts) => { const m = Math.max(0, Math.round((Date.now() - new Date(ts.replace(" ", "T")).getTime()) / 60000)); return m < 1 ? "ahora" : m < 60 ? `hace ${m} min` : `hace ${Math.round(m / 60)} h`; };
  box.innerHTML = `<div class="row" style="margin-bottom:8px"><h3 style="margin:0">${staff ? "🔔 Notas por cobrar" : "📨 Mis notas enviadas a caja"}</h3><span class="badge warn">${list.length}</span></div>
    <div class="pend-list">${list.map((p) => `<div class="pend ${p.id === S.pendingId ? "on" : ""}">
      <div class="grow"><b class="mono">${esc(p.folio)}</b> · ${esc(p.customer_name || "Sin nombre")}<div class="small muted">${esc(p.seller_name)} · ${Number(p.units || 0)} pza · ${ago(p.sent_at || "")}</div></div>
      <b>${money(p.total)}</b>
      ${staff ? `<button class="sm success" data-pa="load" data-id="${p.id}">Cobrar</button>` : ""}
      <button class="sm danger icon-btn" data-pa="drop" data-id="${p.id}" data-folio="${esc(p.folio)}" title="Descartar">✕</button></div>`).join("")}</div>`;
}

async function loadPending(id) {
  if (S.cart.length && S.pendingId !== id && !await confirmBox("Hay artículos en el ticket actual. ¿Reemplazarlos con la nota pendiente?", "Reemplazar")) return;
  let sale;
  try { sale = await GET(`/api/sales/${id}`); } catch (e) { return fail(e); }
  if (sale.status !== "pendiente") { refreshPending(); return toast("Esa nota ya no está pendiente", "bad"); }
  S.cart = sale.items.map((i) => ({ key: `${i.product_id}-${i.imei || ""}`, product_id: i.product_id, name: i.name, sku: i.sku, price: i.unit_price, qty: i.qty,
    discount: i.discount, imei: i.imei || "", serialized: i.imei ? 1 : 0, stock: Infinity, track_stock: 0, warranty: i.warranty_days, changes: i.warranty_changes, ask_device: 0 }));
  S.cartDiscount = sale.discount || 0;
  S.customer = { name: sale.customer_name || "", phone: sale.customer_phone || "", model: sale.device_model || "",
    imei: sale.device_imei || "", seller: String(sale.seller_id || "") };
  S.pendingId = sale.id; S.pendingFolio = sale.folio; S.pendingNotes = sale.notes || "";
  $("#t-disc").value = S.cartDiscount;
  [["name", "#cust-name"], ["phone", "#cust-phone"], ["model", "#cust-model"], ["imei", "#cust-imei"]].forEach(([k, sel]) => { $(sel).value = S.customer[k]; });
  fillSellers();
  saveCart(); renderCart(); renderPendingBanner(); refreshPending();
  toast(`Nota ${sale.folio} cargada. Revisa y cobra (F2).`, "ok");
}

async function sendToCaja() {
  if (!S.cart.length) return toast("El ticket está vacío");
  if (topModal()) return;
  const needsDevice = cartNeedsDevice();
  if (needsDevice && (!S.customer.model || !S.customer.imei)) {
    const ok = await confirmBox("Falta el <b>modelo</b> o el <b>IMEI</b> del equipo del cliente; se usan para la garantía y los cambios. ¿Enviar de todos modos?", "Enviar así");
    if (!ok) { $(S.customer.model ? "#cust-imei" : "#cust-model").focus(); return; }
  }
  const t = cartTotals();
  try {
    const r = await POST("/api/sales/pending", { ...salePayloadBase(), discount: t.disc, pending_id: S.pendingId || undefined });
    clearCart();
    refreshPending();
    modal({ title: "📨 Nota enviada a caja", size: "narrow",
      body: `<div class="center"><div class="muted">Folio</div><h1 class="mono">${esc(r.sale.folio)}</h1><div class="muted" style="margin-top:10px">Total a pagar en caja</div><h1>${money(r.sale.total)}</h1>
        <p class="small muted">Pasa al cliente a caja. El cajero verá la nota en “Notas por cobrar”.</p></div>`,
      foot: `<button class="primary" data-close autofocus>Nueva venta (Esc)</button>` });
  } catch (e) { fail(e); }
}

function salePayloadBase() {
  return {
    items: S.cart.map((l) => ({ product_id: l.product_id, qty: l.qty, unit_price: l.price, discount: num(l.discount), imei: l.imei, warranty_days: l.warranty || 0, warranty_changes: l.changes || 0 })),
    seller_id: $("#cust-seller").value, customer_name: S.customer.name, customer_phone: S.customer.phone,
    // el modelo e IMEI del equipo solo se guardan cuando la venta lleva garantía
    device_model: cartNeedsDevice() ? S.customer.model : "", device_imei: cartNeedsDevice() ? S.customer.imei : "",
  };
}

function clearCart() {
  S.pendingId = null; S.pendingFolio = ""; S.pendingNotes = "";
  S.cart = []; S.cartDiscount = 0; S.customer = { name: "", phone: "", model: "", imei: "", seller: S.customer.seller || "" };
  $("#t-disc").value = "0";
  ["#cust-name", "#cust-phone", "#cust-model", "#cust-imei"].forEach((x) => { $(x).value = ""; });
  fillSellers();
  renderPendingBanner();
  saveCart(); renderCart(); focusScan();
}

async function addToCart(p, imei) {
  if (!p) return;
  if (p.serialized && !imei) {
    imei = await pickImei(p);
    if (!imei) return;
  }
  if (imei) {
    if (S.cart.some((l) => l.imei === imei)) { beep(false); return toast(`El IMEI ${imei} ya está en el ticket`, "bad"); }
    S.cart.push({ key: `${p.id}-${imei}`, product_id: p.id, name: p.name, sku: p.sku, price: p.price, qty: 1, discount: 0, imei, serialized: 1, stock: 1, track_stock: 1, warranty: p.warranty_days, changes: p.warranty_changes || 0, ask_device: 0 });
  } else {
    const line = S.cart.find((l) => l.product_id === p.id && !l.imei);
    if (line) line.qty += 1;
    else S.cart.push({ key: `${p.id}`, product_id: p.id, name: p.name, sku: p.sku, price: p.price, qty: 1, discount: 0, imei: "", serialized: 0, stock: p.stock, track_stock: p.track_stock, warranty: p.warranty_days, changes: p.warranty_changes || 0, ask_device: p.ask_device });
    const l = S.cart.find((x) => x.product_id === p.id && !x.imei);
    if (p.track_stock && l.qty > p.stock && S.settings.allow_negative_stock !== "1") toast(`Atención: solo hay ${Number(p.stock)} en existencia de ${p.name}`, "bad");
  }
  saveCart(); renderCart(); focusScan();
}

function pickImei(p) {
  return new Promise(async (resolve) => {
    let detail;
    try { detail = await GET(`/api/products/${p.id}`); } catch (e) { fail(e); return resolve(null); }
    const avail = detail.serials.filter((s) => s.status === "disponible" && s.branch_id === S.me.branch.id && !S.cart.some((l) => l.imei === s.imei));
    if (!avail.length) {
      const elsewhere = detail.serials.filter((s) => s.status === "disponible" && s.branch_id !== S.me.branch.id);
      toast(elsewhere.length ? `No hay equipos de ${p.name} en ${S.me.branch.name}; hay ${elsewhere.length} en ${[...new Set(elsewhere.map((s) => s.branch_name))].join(", ")}. Pide un traspaso.`
        : `No hay equipos disponibles de ${p.name}. Registra IMEIs en Inventario.`, "bad");
      return resolve(null);
    }
    let done = false;
    modal({
      title: `Selecciona el IMEI — ${esc(p.name)}`, size: "narrow",
      body: `<label class="f">Escanea el IMEI de la caja<input id="imei-in" autofocus placeholder="IMEI"></label>
        <div class="table-wrap" style="margin-top:12px;max-height:300px"><table><tbody>
        ${avail.map((s) => `<tr><td class="mono">${esc(s.imei)}</td><td class="right"><button class="sm primary" data-imei="${esc(s.imei)}">Elegir</button></td></tr>`).join("")}
        </tbody></table></div>`,
      onOpen: (m, close) => {
        const choose = (v) => { done = true; close(); resolve(v); };
        m.addEventListener("click", (e) => { const b = e.target.closest("[data-imei]"); if (b) choose(b.dataset.imei); });
        $("#imei-in", m).addEventListener("keydown", (e) => {
          if (e.key !== "Enter") return;
          const v = e.target.value.trim();
          if (avail.some((s) => s.imei === v)) choose(v); else { beep(false); toast("Ese IMEI no está disponible para este modelo", "bad"); e.target.select(); }
        });
        const obs = new MutationObserver(() => { if (!document.body.contains(m) && !done) { obs.disconnect(); resolve(null); } });
        obs.observe($("#modal-root"), { childList: true });
      },
    });
  });
}

const cartNeedsDevice = () => S.cart.some((l) => l.ask_device || ((l.warranty > 0 || l.changes > 0) && !l.imei));

function cartTotals() {
  const gross = S.cart.reduce((a, l) => a + l.qty * l.price, 0);
  const ldisc = S.cart.reduce((a, l) => a + num(l.discount), 0);
  const sub = r2(gross - ldisc);
  const disc = Math.min(num(S.cartDiscount), sub);
  const rate = num(S.settings.tax_rate) / 100;
  let total, tax;
  if (S.settings.prices_include_tax !== "0") { total = r2(sub - disc); tax = rate ? r2(total - total / (1 + rate)) : 0; }
  else { tax = r2((sub - disc) * rate); total = r2(sub - disc + tax); }
  return { gross: r2(gross), ldisc: r2(ldisc), sub, disc, tax, total, units: S.cart.reduce((a, l) => a + l.qty, 0) };
}

function renderTotals() {
  const t = cartTotals();
  $("#t-units").textContent = t.units;
  $("#t-sub").textContent = money(t.gross);
  $("#t-ldisc").textContent = (t.ldisc ? "-" : "") + money(t.ldisc);
  $("#t-tax-l").textContent = S.settings.prices_include_tax !== "0" ? `IVA incluido (${num(S.settings.tax_rate)}%)` : `IVA ${num(S.settings.tax_rate)}%`;
  $("#t-tax").textContent = money(t.tax);
  $("#t-total").textContent = money(t.total);
  $("#btn-pay").disabled = !S.cart.length;
  $("#btn-send").disabled = !S.cart.length;
  $("#btn-send").classList.toggle("hidden", !can("vendedor"));
  $("#btn-pay").classList.toggle("hidden", sellerOnly());
}

function renderCart() {
  const body = $("#cart-body");
  if (!S.cart.length) {
    body.innerHTML = `<tr><td colspan="6" class="empty">🛒 Ticket vacío. Escanea un producto para comenzar.</td></tr>`;
  } else {
    body.innerHTML = S.cart.map((l, i) => `<tr data-i="${i}">
      <td><div class="pname">${esc(l.name)}</div><div class="small muted mono">${esc(l.sku)}${l.imei ? ` · <span class="badge info">IMEI ${esc(l.imei)}</span>` : ""}</div>
        <div class="row" style="gap:4px;margin-top:4px"><select data-f="warranty" class="small" style="width:auto;padding:2px 6px" title="Garantía">${warrantyOptions(l.warranty || 0)}</select>
        <select data-f="changes" class="small" style="width:auto;padding:2px 6px" title="Cambios incluidos">${changesOptions(l.changes || 0)}</select></div></td>
      <td class="num"><input data-f="price" value="${l.price}" style="width:96px" ${can("vendedor") ? 'disabled title="Solo administrador o cajero cambian precios"' : ""}></td>
      <td class="center"><span class="qty">${l.imei ? "1" : `<button class="sm icon-btn" data-a="dec">−</button><input data-f="qty" value="${l.qty}"><button class="sm icon-btn" data-a="inc">+</button>`}</span></td>
      <td class="num"><input data-f="discount" value="${l.discount || 0}" style="width:80px"></td>
      <td class="num"><b>${money(l.qty * l.price - num(l.discount))}</b></td>
      <td><button class="sm danger icon-btn" data-a="del" title="Quitar">✕</button></td></tr>`).join("");
  }
  renderTotals();
  $("#dev-box")?.classList.toggle("hidden", !cartNeedsDevice());
}

document.addEventListener("change", (e) => {
  const inp = e.target.closest("#cart-body input[data-f], #cart-body select[data-f]");
  if (!inp) return;
  const l = S.cart[+inp.closest("tr").dataset.i];
  const v = num(inp.value);
  if (inp.dataset.f === "qty") l.qty = Math.max(1, v);
  else if (inp.dataset.f === "warranty") l.warranty = Math.round(v);
  else if (inp.dataset.f === "changes") l.changes = Math.round(v);
  else l[inp.dataset.f] = Math.max(0, v);
  saveCart(); renderCart();
});
document.addEventListener("click", (e) => {
  const b = e.target.closest("#cart-body [data-a]");
  if (!b) return;
  const i = +b.closest("tr").dataset.i;
  if (b.dataset.a === "del") S.cart.splice(i, 1);
  if (b.dataset.a === "inc") S.cart[i].qty += 1;
  if (b.dataset.a === "dec") S.cart[i].qty = Math.max(1, S.cart[i].qty - 1);
  saveCart(); renderCart();
});

async function checkout() {
  if (sellerOnly()) return sendToCaja();
  if (!S.cart.length) return toast("El ticket está vacío");
  if (topModal()) return;
  const needsDevice = cartNeedsDevice();
  if (needsDevice && (!S.customer.model || !S.customer.imei)) {
    const ok = await confirmBox("Falta el <b>modelo</b> o el <b>IMEI</b> del equipo del cliente; se usan para hacer válida la garantía y los cambios. ¿Cobrar de todos modos?", "Cobrar sin ellos");
    if (!ok) { $(S.customer.model ? "#cust-imei" : "#cust-model").focus(); return; }
  }
  const t = cartTotals();
  let method = "efectivo";
  modal({
    title: `Cobrar ${money(t.total)}`, size: "narrow",
    body: `<div class="pay-methods">
        <button data-m="efectivo" class="on">💵 Efectivo</button><button data-m="tarjeta">💳 Tarjeta</button>
        <button data-m="transferencia">🏦 Transf.</button><button data-m="mixto">➗ Mixto</button></div>
      <div id="pm-efectivo">
        <label class="f">Recibido en efectivo<input id="pay-recv" inputmode="decimal" value="${t.total}" style="font-size:22px;font-weight:700;text-align:right"></label>
        <div class="bills">${[t.total, 50, 100, 200, 500, 1000].map((b, i) => `<button class="sm" data-bill="${b}">${i === 0 ? "Exacto" : money(b).replace(".00", "")}</button>`).join("")}</div>
      </div>
      <div id="pm-mixto" class="hidden grid" style="gap:8px">
        <label class="f">Efectivo<input id="mx-cash" inputmode="decimal" value="0"></label>
        <label class="f">Tarjeta<input id="mx-card" inputmode="decimal" value="0"></label>
        <label class="f">Transferencia<input id="mx-tr" inputmode="decimal" value="0"></label>
      </div>
      <div class="change-box" id="chg"><span>Cambio</span><b id="chg-v">$0.00</b></div>
      <label class="f" style="margin-top:12px">Notas del ticket (opcional)<input id="pay-notes" value="${esc(S.pendingNotes)}" placeholder="p. ej. apartado, garantía extendida…"></label>
      <label class="chk small" style="margin-top:10px"><input type="checkbox" id="pay-print" checked> Imprimir ticket</label>`,
    foot: `<button data-close>Cancelar</button><button class="success" id="pay-ok">✔ Confirmar venta (Enter)</button>`,
    onOpen: (m, close) => {
      const recalc = () => {
        let paid = method === "efectivo" ? num($("#pay-recv", m).value) : method === "mixto" ? num($("#mx-cash", m).value) + num($("#mx-card", m).value) + num($("#mx-tr", m).value) : t.total;
        const chg = r2(paid - t.total);
        $("#chg", m).classList.toggle("bad", chg < 0);
        $("#chg", m).firstElementChild.textContent = chg < 0 ? "Falta" : "Cambio";
        $("#chg-v", m).textContent = money(Math.abs(chg));
      };
      $$("[data-m]", m).forEach((b) => b.onclick = () => {
        method = b.dataset.m;
        $$("[data-m]", m).forEach((x) => x.classList.toggle("on", x === b));
        $("#pm-efectivo", m).classList.toggle("hidden", method !== "efectivo");
        $("#pm-mixto", m).classList.toggle("hidden", method !== "mixto");
        if (method === "efectivo") $("#pay-recv", m).select();
        if (method === "mixto") $("#mx-cash", m).select();
        recalc();
      });
      $$("[data-bill]", m).forEach((b) => b.onclick = () => { $("#pay-recv", m).value = b.dataset.bill; recalc(); });
      m.addEventListener("input", recalc);
      setTimeout(() => $("#pay-recv", m).select(), 50);
      let busy = false;
      const confirm = async () => {
        if (busy) return; busy = true;
        $("#pay-ok", m).disabled = true;
        const payload = {
          ...salePayloadBase(), pending_id: S.pendingId || undefined,
          discount: t.disc, payment_method: method,
          received: method === "efectivo" ? num($("#pay-recv", m).value) : t.total,
          paid_cash: num($("#mx-cash", m).value), paid_card: num($("#mx-card", m).value), paid_transfer: num($("#mx-tr", m).value),
          notes: $("#pay-notes", m).value,
          print: $("#pay-print", m).checked,
        };
        const browserPrint = payload.print && S.settings.ticket_printer_mode === "browser";
        const win = browserPrint ? window.open("about:blank", "ticket", "width=420,height=720") : null;
        try {
          const r = await POST("/api/sales", payload);
          close();
          clearCart();
          refreshPending();
          if (win) win.location = `/tickets/${r.sale.id}?print=1`;
          if (r.print_error) toast(`Venta guardada, pero no se imprimió: ${r.print_error}`, "bad");
          else if (r.print?.message) toast(r.print.message, "ok");
          saleDone(r.sale);
        } catch (e) {
          if (win) win.close();
          fail(e); busy = false; $("#pay-ok", m).disabled = false;
        }
      };
      $("#pay-ok", m).onclick = confirm;
      m.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.id !== "pay-notes") { e.preventDefault(); confirm(); } });
      recalc();
    },
  });
}

function saleDone(sale) {
  modal({
    title: "✅ Venta registrada", size: "narrow",
    body: `<div class="center"><div class="muted">Folio</div><h1 class="mono">${esc(sale.folio)}</h1>
      <div style="margin-top:12px" class="muted">Total</div><h1>${money(sale.total)}</h1>
      ${sale.change > 0 ? `<div class="change-box" style="margin-top:14px"><span>Cambio</span><b>${money(sale.change)}</b></div>` : ""}</div>`,
    foot: `<button id="sd-print">🖨 Reimprimir</button><button id="sd-view">Ver ticket</button><button class="primary" data-close autofocus>Nueva venta (Esc)</button>`,
    onOpen: (m) => {
      $("#sd-print", m).onclick = () => printSale(sale.id);
      $("#sd-view", m).onclick = () => showSale(sale.id);
      setTimeout(() => m.querySelector(".primary").focus(), 50);
    },
  });
}

async function printSale(id) {
  if (S.settings.ticket_printer_mode === "browser") return openTicketWindow(`/tickets/${id}?print=1&reprint=1`);
  try { const r = await POST(`/api/sales/${id}/print`); toast(r.message || "Ticket enviado", "ok"); } catch (e) { fail(e); }
}

async function showSale(id) {
  let s;
  try { s = await GET(`/api/sales/${id}`); } catch (e) { return fail(e); }
  modal({
    title: `Venta ${esc(s.folio)} ${s.status === "cancelada" ? '<span class="badge bad">Cancelada</span>' : ""}`, size: "wide",
    body: `<div class="grid cols-2"><div>
        <table><tbody>
          <tr><td class="muted">Fecha</td><td>${esc(s.created_at)}</td></tr>
          <tr><td class="muted">Vendedor</td><td>${esc(s.seller_name || s.cashier || "—")}${s.cashier && s.cashier !== s.seller_name ? ` <span class="muted small">(cobró ${esc(s.cashier)})</span>` : ""}</td></tr>
          <tr><td class="muted">Cliente</td><td>${esc(s.customer_name || "—")} ${esc(s.customer_phone || "")}</td></tr>
          ${s.device_model || s.device_imei ? `<tr><td class="muted">Equipo</td><td>${esc(s.device_model || "")} <span class="mono">${esc(s.device_imei || "")}</span></td></tr>` : ""}
          <tr><td class="muted">Pago</td><td>${esc(s.payment_method)}</td></tr>
          <tr><td class="muted">Total</td><td><b>${money(s.total)}</b></td></tr>
          ${s.cost_total !== undefined ? `<tr><td class="muted">Utilidad</td><td>${money(s.total - s.cost_total)}</td></tr>` : ""}
          ${s.notes ? `<tr><td class="muted">Notas</td><td>${esc(s.notes)}</td></tr>` : ""}
        </tbody></table>
        <h3 style="margin:16px 0 6px">Artículos</h3>
        <table><thead><tr><th>Producto</th><th class="num">Cant.</th><th class="num">Importe</th></tr></thead><tbody>
          ${s.items.map((i) => `<tr><td>${esc(i.name)}<div class="small muted mono">${esc(i.sku || "")} ${i.imei ? "· IMEI " + esc(i.imei) : ""}${i.warranty_days ? " · Garantía " + warrantyLabel(i.warranty_days) : ""}${i.warranty_changes ? ` · ${i.warranty_changes} cambios` : ""}</div></td><td class="num">${i.qty}</td><td class="num">${money(i.total)}</td></tr>`).join("")}
        </tbody></table></div>
      <div><iframe class="ticket" src="/tickets/${s.id}"></iframe>
        <div class="row small" style="margin-top:6px">Descargar: <a href="/tickets/${s.id}?format=zpl">ZPL (Zebra)</a> · <a href="/tickets/${s.id}?format=escpos">ESC/POS</a> · <a href="/tickets/${s.id}?format=txt" target="_blank">Texto</a></div></div></div>`,
    foot: `${s.status === "completada" && can("admin", "matriz", "cajero") ? '<button class="danger" id="sv-cancel">Cancelar venta</button><span class="spacer"></span>' : ""}
           <button id="sv-print">🖨 Reimprimir ticket</button><button data-close class="primary">Cerrar</button>`,
    onOpen: (m, close) => {
      $("#sv-print", m).onclick = () => printSale(s.id);
      const c = $("#sv-cancel", m);
      if (c) c.onclick = async () => {
        const needsKey = !can("admin");
        modal({
          title: `Cancelar venta ${esc(s.folio)}`, size: "narrow",
          body: `<p class="small" style="margin-top:0">El producto regresa al inventario y la nota queda como cancelada.</p>
            <div class="grid" style="gap:10px"><label class="f">Motivo de la cancelación *<input id="cx-reason" autofocus></label>
            ${needsKey ? '<label class="f">Clave de cancelación *<input id="cx-pass" type="password" autocomplete="off"></label>' : ""}</div>`,
          foot: `<button data-close>Regresar</button><button class="danger" id="cx-ok">Cancelar venta</button>`,
          onOpen: (cm, cclose) => {
            $("#cx-ok", cm).onclick = async () => {
              const reason = $("#cx-reason", cm).value.trim();
              if (!reason) return toast("Escribe el motivo", "bad");
              try {
                await POST(`/api/sales/${s.id}/cancel`, { reason, password: needsKey ? $("#cx-pass", cm).value : undefined });
                toast("Venta cancelada; inventario restaurado", "ok"); cclose(); close(); if (S.view === "ventas") VIEWS.ventas();
              } catch (e) { fail(e); }
            };
          },
        });
      };
    },
  });
}

VIEWS.vender = () => {
  const bodega = S.me && !S.me.branch.sells;
  let note = $("#bodega-note");
  if (!note) { note = document.createElement("div"); note.id = "bodega-note"; $("#view-vender").prepend(note); }
  note.className = bodega ? "card bodega-note" : "hidden";
  note.innerHTML = bodega ? `<h2>🏬 ${esc(S.me.branch.name)} es bodega</h2><p>Aquí no se vende al público. Elige la sucursal donde vas a vender:</p>
    <div class="row">${S.branches.filter((b) => b.active && b.sells).map((b) => `<button class="primary" data-go-branch="${b.id}">${esc(b.name)}</button>`).join("")}</div>` : "";
  $$("[data-go-branch]", note).forEach((b) => b.onclick = async () => { await POST("/api/branch/select", { branch_id: +b.dataset.goBranch }); location.reload(); });
  $(".pos").classList.toggle("hidden", bodega);
  if (bodega) return;
  renderTotals(); renderPendingBanner(); refreshPending(); focusScan();
};

/* ================================================================== PRODUCTOS */
function initProductos() {
  $("#view-productos").innerHTML = `
    <div class="view-head"><h1>Productos</h1>
      <button id="p-quick" class="admin-only">⚡ Alta rápida (varios)</button>
      <button id="p-bulk" class="admin-only">💲 Generador de precios</button>
      <button id="p-import" class="admin-only">⬆ Importar CSV</button>
      <a class="btn admin-only" href="/api/products/export.csv">⬇ Exportar CSV</a>
      <button class="primary admin-only" id="p-new">＋ Nuevo producto</button></div>
    <div class="row" style="margin-bottom:12px">
      <input id="p-q" placeholder="Buscar por nombre, marca, SKU, código o IMEI…" style="max-width:420px">
      <select id="p-cat" style="max-width:240px"></select>
      <label class="chk"><input type="checkbox" id="p-low"> Solo existencia baja</label>
      <span class="spacer"></span><span class="muted small" id="p-count"></span>
    </div>
    <div class="table-wrap"><table><thead><tr>
      <th>SKU</th><th>Código</th><th>Producto</th><th>Categoría</th><th class="num cost-col">Costo</th><th class="num">Precio</th><th class="num cost-col">Margen</th><th class="num">Garantía</th><th class="num">Exist.</th><th class="num multi-col">Total</th><th></th>
    </tr></thead><tbody id="p-body"></tbody></table></div>`;
  $("#p-new").onclick = () => productForm();
  $("#p-bulk").onclick = bulkPricing;
  $("#p-quick").onclick = quickAdd;
  $("#p-import").onclick = importCsv;
  $("#p-q").oninput = debounce(loadProducts, 250);
  $("#p-cat").onchange = loadProducts;
  $("#p-low").onchange = loadProducts;
  $("#p-body").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-a]"); if (!b) return;
    const id = +b.closest("tr").dataset.id;
    if (b.dataset.a === "edit") productForm(id);
    if (b.dataset.a === "label") { await addToLabelQueue(id); go("etiquetas"); }
    if (b.dataset.a === "imei") imeiManager(id);
    if (b.dataset.a === "del") {
      if (!await confirmBox("¿Eliminar este producto? Si tiene ventas solo se desactiva.", "Eliminar", true)) return;
      try { const r = await DEL(`/api/products/${id}`); toast(r.message, "ok"); loadProducts(); } catch (er) { fail(er); }
    }
  });
}

async function loadProducts() {
  const q = $("#p-q").value.trim(), cat = $("#p-cat").value, low = $("#p-low").checked ? 1 : 0;
  try {
    const list = await GET(`/api/products?q=${encodeURIComponent(q)}&category=${cat}&low=${low}`);
    $("#p-count").textContent = `${list.length} producto(s)`;
    $("#p-body").innerHTML = list.length ? list.map((p) => {
      const margin = p.price ? ((p.price - p.cost) / p.price) * 100 : 0;
      const st = !p.track_stock ? '<span class="badge">N/A</span>' : `<span class="badge ${p.stock <= 0 ? "bad" : p.stock <= p.min_stock ? "warn" : "ok"}">${Number(p.stock)}</span>`;
      return `<tr data-id="${p.id}">
        <td class="mono small nowrap">${esc(p.sku)}</td><td class="mono small">${esc(p.barcode || "")}</td>
        <td><b>${esc(p.name)}</b>${p.serialized ? ' <span class="badge info">IMEI</span>' : ""}<div class="small muted">${esc([p.brand, p.model, p.ram ? p.ram + " RAM" : "", p.capacity, p.color, p.condition].filter(Boolean).join(" · "))}</div></td>
        <td>${esc(p.category_name || "—")}</td><td class="num cost-col">${money(p.cost)}</td><td class="num"><b>${money(p.price)}</b></td>
        <td class="num cost-col ${margin < 15 ? "danger" : ""}">${margin.toFixed(0)}%</td><td class="num small">${p.warranty_days ? warrantyLabel(p.warranty_days) : "—"}${p.warranty_changes ? `<div class="muted">${p.warranty_changes} cambio${p.warranty_changes > 1 ? "s" : ""}</div>` : ""}</td><td class="num">${st}</td><td class="num multi-col small muted">${p.track_stock ? Number(p.stock_total) : ""}</td>
        <td>${can("admin", "matriz") ? '<button class="sm" data-a="edit">Editar</button> ' : ""}${can("admin", "matriz", "cajero") ? '<button class="sm" data-a="label">🏷️</button> ' : ""}
          ${p.serialized && can("admin", "matriz", "cajero") ? '<button class="sm" data-a="imei">IMEI</button>' : ""} ${can("admin") ? '<button class="sm danger icon-btn" data-a="del" title="Eliminar">✕</button>' : ""}</td></tr>`;
    }).join("") : `<tr><td colspan="11" class="empty">No hay productos. Da clic en “Nuevo producto” o importa un CSV.</td></tr>`;
  } catch (e) { fail(e); }
}

VIEWS.productos = () => {
  $("#view-productos").classList.toggle("single-branch", !S.multi);
  $$(".admin-only", $("#view-productos")).forEach((x) => x.classList.toggle("hidden", !can("admin", "matriz")));
  $("#p-bulk").classList.toggle("hidden", !can("admin"));
  $("#view-productos").classList.toggle("no-costs", can("vendedor"));
  const sel = $("#p-cat"), v = sel.value;
  sel.innerHTML = catOptions(v, "Todas las categorías");
  loadProducts();
};

async function productForm(id) {
  let p = { name: "", brand: "", model: "", color: "", capacity: "", category_id: "", sku: "", barcode: "", cost: "", price: "", wholesale_price: "",
    min_stock: 1, serialized: 0, track_stock: 1, warranty_days: 0, location: "", notes: "", ask_device: 0, warranty_changes: 0, ram: "", condition: "" };
  if (id) { try { p = await GET(`/api/products/${id}`); } catch (e) { return fail(e); } }
  const cat = S.categories.find((c) => String(c.id) === String(p.category_id));
  const isNew = !id;
  modal({
    title: isNew ? "Nuevo producto" : `Editar: ${esc(p.name)}`, size: "wide",
    body: `<form id="pf" class="form-grid" autocomplete="off">
      <label class="f span-2">Nombre del producto *<input name="name" value="${esc(p.name)}" required autofocus placeholder="p. ej. Funda uso rudo Galaxy A15 negra"></label>
      <label class="f">Categoría<select name="category_id">${catOptions(p.category_id)}</select></label>
      <label class="f">Marca<input name="brand" value="${esc(p.brand)}" placeholder="Samsung, Apple, Xiaomi…" list="dl-brands"></label>
      <label class="f">Modelo<input name="model" value="${esc(p.model)}" placeholder="Galaxy A15, iPhone 13…"></label>
      <label class="f">RAM (celulares)<input name="ram" value="${esc(p.ram || "")}" placeholder="4GB" list="dl-ram"></label>
      <label class="f">Almacenamiento / medida<input name="capacity" value="${esc(p.capacity)}" placeholder="128GB, 20W, 1m…" list="dl-rom"></label>
      <label class="f">Color<input name="color" value="${esc(p.color)}"></label>
      <label class="f">Condición<select name="condition">${["", "Nuevo", "Seminuevo", "Reacondicionado", "Usado"].map((c) => `<option value="${c}" ${c === (p.condition || "") ? "selected" : ""}>${c || "—"}</option>`).join("")}</select></label>
      <label class="f">Ubicación<input name="location" value="${esc(p.location)}" placeholder="Vitrina 2, bodega…"></label>
      <label class="f span-2">SKU (vacío = automático)<div class="input-group"><input name="sku" value="${esc(p.sku)}" class="mono" placeholder="Se genera: CAT-MAR-0001"><button type="button" id="gen-sku">Generar</button></div></label>
      <label class="f span-2">Código de barras (escanea el del fabricante o genera uno)<div class="input-group"><input name="barcode" value="${esc(p.barcode)}" class="mono" placeholder="Vacío = EAN-13 interno automático"><button type="button" id="gen-bc">Generar EAN-13</button></div></label>
      <fieldset class="span-all price-gen" style="grid-column:1/-1"><legend>💲 Generador de precio</legend>
        <div class="form-grid">
          <label class="f">Costo de compra<input name="cost" inputmode="decimal" value="${p.cost}"></label>
          <label class="f">% de ganancia sobre costo<input id="pg-markup" inputmode="decimal" value="${cat ? cat.markup : num(S.settings.default_markup)}"></label>
          <label class="f">Redondeo<select id="pg-round">${roundingOptions(S.settings.price_rounding)}</select></label>
          <label class="f">&nbsp;<label class="chk"><input type="checkbox" id="pg-tax" checked> El costo ya incluye IVA</label></label>
        </div>
        <div class="suggest"><span>Precio sugerido:</span><b id="pg-price">—</b><span class="muted small" id="pg-info"></span><span class="spacer"></span><button type="button" class="primary sm" id="pg-use">Usar este precio</button></div>
        <div class="form-grid" style="margin-top:12px">
          <label class="f">Precio de venta (público) *<input name="price" inputmode="decimal" value="${p.price}" style="font-weight:700;font-size:16px"></label>
          <label class="f">Precio mayoreo<input name="wholesale_price" inputmode="decimal" value="${p.wholesale_price || ""}"></label>
          <label class="f span-2">Margen real<div id="pg-real" style="padding:9px 0;font-weight:600">—</div></label>
        </div>
      </fieldset>
      <fieldset style="grid-column:1/-1"><legend>📦 Inventario y garantía</legend>
        <div class="form-grid">
          <label class="f span-2">¿Lleva serie? *<select name="serialized" class="w-required">
            ${isNew ? '<option value="" selected>— Elige: con serie o sin serie —</option>' : ""}
            <option value="0" ${!isNew && !p.serialized ? "selected" : ""}>Sin serie: se controla por cantidad</option>
            <option value="1" ${!isNew && p.serialized ? "selected" : ""}>Con serie: IMEI / número de serie por pieza</option></select></label>
          <label class="chk"><input type="checkbox" name="track_stock" ${p.track_stock ? "checked" : ""}> Controla existencia</label>
          <label class="f">Existencia mínima<input name="min_stock" inputmode="decimal" value="${p.min_stock}"></label>
          <label class="f">Garantía *<select name="warranty_days" class="w-required">${warrantyOptions(isNew ? "" : p.warranty_days)}</select></label>
          <label class="f">Cambios incluidos<select name="warranty_changes">${changesOptions(p.warranty_changes || 0)}</select></label>
          <label class="chk span-2"><input type="checkbox" name="ask_device" ${p.ask_device ? "checked" : ""}> Pedir modelo e IMEI del equipo del cliente (micas, fundas, reparaciones)</label>
          ${isNew ? `<label class="f span-2" id="f-initial">Existencia inicial<input name="initial_stock" inputmode="decimal" value="0"></label>
          <label class="f span-all hidden" id="f-imeis">Series iniciales: escanea la serie de cada pieza (IMEI / número de serie, una por renglón; déjalo vacío si aún no llega)<textarea name="imeis" class="mono" placeholder="356789012345678"></textarea></label>` : `<div class="span-2 muted small" style="grid-column:span 2;align-self:center">Existencia en ${esc(S.me.branch.name)}: <b>${Number(p.stock)}</b>${S.multi ? ` · ${(p.stock_by_branch || []).filter((b) => b.id !== S.me.branch.id).map((b) => `${esc(b.name)}: ${Number(b.stock)}`).join(" · ")}` : ""} — ajústala en Inventario.</div>`}
          <label class="f span-all">Notas<input name="notes" value="${esc(p.notes)}"></label>
        </div>
      </fieldset>
      <datalist id="dl-ram">${["2GB", "3GB", "4GB", "6GB", "8GB", "12GB", "16GB"].map((x) => `<option value="${x}">`).join("")}</datalist>
      <datalist id="dl-rom">${["32GB", "64GB", "128GB", "256GB", "512GB", "1TB"].map((x) => `<option value="${x}">`).join("")}</datalist>
      <datalist id="dl-brands">${["Samsung", "Apple", "Xiaomi", "Motorola", "Huawei", "Honor", "Oppo", "Realme", "ZTE", "Alcatel", "Nokia", "Vivo", "Infinix", "Tecno", "Genérico"].map((b) => `<option value="${b}">`).join("")}</datalist>
      </form>`,
    foot: `<button data-close>Cancelar</button>${isNew ? '<button id="pf-save-label">Guardar e imprimir etiqueta</button>' : ""}<button class="primary" id="pf-save">Guardar</button>`,
    onOpen: (m, close) => {
      const f = $("#pf", m);
      const val = (n) => f.elements[n];
      const toggleSerial = () => {
        const ser = val("serialized").value === "1";
        $("#f-initial", m)?.classList.toggle("hidden", ser);
        $("#f-imeis", m)?.classList.toggle("hidden", !ser);
        if (ser) val("track_stock").checked = true;
      };
      val("serialized").onchange = () => { toggleSerial(); if (val("serialized").value === "1" && !val("condition").value) val("condition").value = "Nuevo"; };
      toggleSerial();
      val("category_id").onchange = () => {
        const c = S.categories.find((x) => String(x.id) === val("category_id").value);
        if (c) { $("#pg-markup", m).value = c.markup; if (isNew) { val("track_stock").checked = c.prefix !== "SRV"; val("ask_device").checked = !!c.ask_device; if (c.serialized && !val("condition").value) val("condition").value = "Nuevo"; } }
        suggest();
      };
      let suggested = null;
      const suggest = debounce(async () => {
        const cost = num(val("cost").value);
        if (!cost) { $("#pg-price", m).textContent = "—"; $("#pg-info", m).textContent = "Captura el costo"; suggested = null; realMargin(); return; }
        try {
          const r = await POST("/api/pricing/suggest", { cost, markup: num($("#pg-markup", m).value), rounding: $("#pg-round", m).value, cost_includes_tax: $("#pg-tax", m).checked });
          suggested = r.price;
          $("#pg-price", m).textContent = money(r.price);
          $("#pg-info", m).textContent = `Ganancia ${money(r.profit)} · margen ${r.margin_percent}% del precio`;
          if (!num(val("price").value)) val("price").value = r.price;
        } catch (e) { fail(e); }
        realMargin();
      }, 200);
      const realMargin = () => {
        const cost = num(val("cost").value), price = num(val("price").value);
        $("#pg-real", m).innerHTML = price ? `${money(price - cost)} de ganancia · <span class="${(price - cost) / price < 0.15 ? "danger" : ""}">${(((price - cost) / price) * 100).toFixed(1)}%</span> del precio` : "—";
      };
      ["cost"].forEach((n) => val(n).addEventListener("input", suggest));
      ["pg-markup", "pg-round", "pg-tax"].forEach((idn) => $("#" + idn, m).addEventListener(idn === "pg-markup" ? "input" : "change", suggest));
      val("price").addEventListener("input", realMargin);
      $("#pg-use", m).onclick = () => { if (suggested) { val("price").value = suggested; realMargin(); } };
      $("#gen-sku", m).onclick = async () => {
        try { val("sku").value = (await GET(`/api/products/next-sku?category_id=${val("category_id").value}&brand=${encodeURIComponent(val("brand").value)}`)).sku; } catch (e) { fail(e); }
      };
      $("#gen-bc", m).onclick = async () => { try { val("barcode").value = (await GET("/api/products/new-barcode")).barcode; } catch (e) { fail(e); } };
      suggest();
      const save = async (thenLabel) => {
        const data = Object.fromEntries(new FormData(f).entries());
        if (data.serialized === "") { val("serialized").focus(); return toast("Indica si el producto lleva serie (IMEI / número de serie) o no", "bad"); }
        data.track_stock = val("track_stock").checked ? 1 : 0;
        data.ask_device = val("ask_device").checked ? 1 : 0;
        if (!data.name.trim()) return toast("Escribe el nombre del producto", "bad");
        if (data.warranty_days === "") { val("warranty_days").focus(); return toast("Elige la garantía del producto (o “Sin garantía”) para que salga correcta en la nota", "bad"); }
        if (!num(data.price) && !await confirmBox("El precio de venta está en $0. ¿Guardar así?")) return;
        try {
          const saved = isNew ? await POST("/api/products", data) : await PUT(`/api/products/${id}`, data);
          toast(`Guardado: ${saved.sku}`, "ok");
          close();
          if (S.view === "productos") loadProducts();
          if (thenLabel) {
            const qty = saved.serialized ? 1 : Math.max(1, Number(saved.stock) || 1);
            await addToLabelQueue(saved.id, qty, !!saved.serialized);
            go("etiquetas");
          }
        } catch (e) { fail(e); }
      };
      $("#pf-save", m).onclick = () => save(false);
      const sl = $("#pf-save-label", m); if (sl) sl.onclick = () => save(true);
      f.addEventListener("submit", (e) => { e.preventDefault(); save(false); });
    },
  });
}

async function imeiManager(id) {
  let p;
  try { p = await GET(`/api/products/${id}`); } catch (e) { return fail(e); }
  modal({
    title: `IMEI — ${esc(p.name)}`, size: "wide",
    body: `<div class="grid cols-2">
      <div><label class="f">Agregar IMEIs (escanea uno por renglón)<textarea id="im-new" class="mono" style="min-height:180px" autofocus></textarea></label>
        <div class="row" style="margin-top:8px"><button class="primary" id="im-add">Agregar al inventario</button>
        <label class="chk small"><input type="checkbox" id="im-print" checked> Mandar a etiquetas</label></div></div>
      <div><h3 style="margin-bottom:8px">Registrados (${p.serials.length}) — disponibles: ${p.serials.filter((s) => s.status === "disponible").length}</h3>
        <div class="table-wrap" style="max-height:320px"><table><tbody>
        ${p.serials.map((s) => `<tr data-sid="${s.id}"><td class="mono">${esc(s.imei)}</td>
          <td>${s.status === "disponible" ? `<span class="badge ok">Disponible${S.multi ? " · " + esc(s.branch_name || "") : ""}</span>` : `<span class="badge">Vendido ${esc(s.folio || "")}</span>`}</td>
          <td class="right">${s.status === "disponible" ? `<button class="sm" data-a="lbl" data-imei="${esc(s.imei)}">🏷️</button> <button class="sm danger" data-a="del">✕</button>` : ""}</td></tr>`).join("") || '<tr><td class="empty">Sin IMEIs</td></tr>'}
        </tbody></table></div></div></div>`,
    foot: `<button data-close class="primary">Cerrar</button>`,
    onOpen: (m, close) => {
      $("#im-add", m).onclick = async () => {
        try {
          const r = await POST(`/api/products/${id}/serials`, { imeis: $("#im-new", m).value });
          toast(`${r.added.length} IMEI agregado(s)${r.skipped.length ? `; repetidos: ${r.skipped.join(", ")}` : ""}`, r.skipped.length ? "bad" : "ok");
          close();
          if ($("#im-print", m).checked && r.added.length) { r.added.forEach((imei) => queueItem({ product_id: id, name: p.name, sku: p.sku, imei, qty: 1, serialized: 1 })); go("etiquetas"); }
          else { imeiManager(id); if (S.view === "productos") loadProducts(); }
        } catch (e) { fail(e); }
      };
      m.addEventListener("click", async (e) => {
        const b = e.target.closest("[data-a]"); if (!b) return;
        if (b.dataset.a === "lbl") { queueItem({ product_id: id, name: p.name, sku: p.sku, imei: b.dataset.imei, qty: 1, serialized: 1 }); close(); go("etiquetas"); }
        if (b.dataset.a === "del") {
          if (!await confirmBox("¿Dar de baja este IMEI del inventario?", "Dar de baja", true)) return;
          try { await DEL(`/api/serials/${b.closest("tr").dataset.sid}`); close(); imeiManager(id); } catch (er) { fail(er); }
        }
      });
    },
  });
}

const MICA_TYPES = ["Mica de hidrogel HD", "Mica de hidrogel mate", "Mica de hidrogel privacidad", "Mica de hidrogel anti luz azul",
  "Mica de hidrogel trasera", "Mica de hidrogel para smartwatch", "Mica cristal templado 9D", "Mica cristal templado privacidad",
  "Mica cristal templado mate", "Mica cerámica flexible", "Protector de cámara", "Protector de cámara con anillo"];

function quickAdd() {
  const hid = S.categories.find((c) => c.prefix === "HID") || S.categories.find((c) => c.prefix === "MIC");
  const row = (r = {}) => `<tr>
    <td><input data-q="name" value="${esc(r.name || "")}" placeholder="Nombre" style="min-width:250px"></td>
    <td><select data-q="category_id" style="width:150px">${catOptions(r.category_id ?? hid?.id ?? "")}</select></td>
    <td><select data-q="serialized" class="w-required" style="width:105px">${serialOptions(r.serialized ?? "")}</select></td>
    <td><input data-q="brand" value="${esc(r.brand || "")}" placeholder="Marca" style="width:90px"></td>
    <td><input data-q="cost" inputmode="decimal" style="width:80px" value="${r.cost ?? ""}"></td>
    <td><input data-q="price" inputmode="decimal" style="width:80px" value="${r.price ?? ""}"></td>
    <td><select data-q="warranty_days" class="w-required" style="width:140px">${warrantyOptions(r.warranty_days ?? "")}</select></td>
    <td><select data-q="warranty_changes" style="width:120px">${changesOptions(r.warranty_changes ?? 0)}</select></td>
    <td class="center"><input type="checkbox" data-q="track_stock" ${r.track_stock ? "checked" : ""}></td>
    <td><input data-q="initial_stock" inputmode="decimal" style="width:64px" value="${r.initial_stock ?? ""}"></td>
    <td class="center"><input type="checkbox" data-q="ask_device" ${r.ask_device ?? 1 ? "checked" : ""}></td>
    <td><button class="sm danger icon-btn" data-a="rm">✕</button></td></tr>`;
  modal({
    title: "⚡ Alta rápida de varios productos", size: "wide xl",
    body: `<p class="small muted" style="margin-top:0">Ideal para cargar todos los tipos de micas. Las micas de hidrogel que se cortan en máquina normalmente <b>no</b> controlan existencia. SKU y código de barras se generan solos.</p>
      <div class="row" style="margin-bottom:10px"><button id="qa-micas">✨ Sugerir tipos de micas</button>
        <label class="f" style="flex-direction:row;align-items:center;gap:6px">Mismo precio para todas<input id="qa-price" inputmode="decimal" style="width:90px" placeholder="259"></label>
        <label class="f" style="flex-direction:row;align-items:center;gap:6px">Garantía<select id="qa-war" style="width:150px">${warrantyOptions("")}</select></label>
        <label class="f" style="flex-direction:row;align-items:center;gap:6px">Cambios<select id="qa-chg" style="width:130px">${changesOptions(0)}</select></label>
        <button id="qa-apply" class="sm">Aplicar a todas</button></div>
      <div class="table-wrap" style="max-height:52vh"><table><thead><tr><th>Producto</th><th>Categoría</th><th>¿Serie?</th><th>Marca</th><th>Costo</th><th>Precio</th><th>Garantía</th><th>Cambios</th><th title="Controla existencia">Inventario</th><th>Cant. inicial</th><th>Pide equipo</th><th></th></tr></thead>
      <tbody id="qa-body">${row()}${row()}${row()}</tbody></table></div>
      <button id="qa-add" style="margin-top:8px">＋ Agregar renglón</button><div id="qa-res" class="small" style="margin-top:8px"></div>`,
    foot: `<button data-close>Cerrar</button><button class="primary" id="qa-save">Guardar productos</button>`,
    onOpen: (m, close) => {
      const body = $("#qa-body", m);
      $("#qa-add", m).onclick = () => body.insertAdjacentHTML("beforeend", row());
      $("#qa-micas", m).onclick = () => {
        $$("tr", body).forEach((tr) => { if (!$('[data-q="name"]', tr).value.trim()) tr.remove(); });
        const price = $("#qa-price", m).value, war = $("#qa-war", m).value === "" ? "" : num($("#qa-war", m).value);
        body.insertAdjacentHTML("beforeend", MICA_TYPES.map((name) => row({ name, price, serialized: 0, warranty_days: war, warranty_changes: num($("#qa-chg", m).value),
          category_id: (name.includes("hidrogel") ? hid : S.categories.find((c) => c.prefix === "MIC"))?.id })).join(""));
      };
      $("#qa-apply", m).onclick = () => $$("tr", body).forEach((tr) => {
        if ($("#qa-price", m).value) $('[data-q="price"]', tr).value = $("#qa-price", m).value;
        if ($("#qa-war", m).value !== "") $('[data-q="warranty_days"]', tr).innerHTML = warrantyOptions($("#qa-war", m).value);
        $('[data-q="warranty_changes"]', tr).innerHTML = changesOptions($("#qa-chg", m).value);
      });
      body.addEventListener("click", (e) => { if (e.target.closest('[data-a="rm"]')) e.target.closest("tr").remove(); });
      $("#qa-save", m).onclick = async () => {
        const rows = $$("tr", body).map((tr) => Object.fromEntries($$("[data-q]", tr).map((i) => [i.dataset.q, i.type === "checkbox" ? (i.checked ? 1 : 0) : i.value])))
          .filter((r) => r.name.trim());
        if (!rows.length) return toast("Escribe al menos un producto", "bad");
        const noSerial = rows.filter((r) => r.serialized === "");
        if (noSerial.length) return toast(`Indica si llevan serie: ${noSerial.map((r) => r.name).join(", ")}`, "bad");
        const serialWithQty = rows.filter((r) => r.serialized === "1" && num(r.initial_stock));
        if (serialWithQty.length) return toast(`${serialWithQty.map((r) => r.name).join(", ")}: llevan serie, su existencia se ingresa en Recepción de mercancía con cada serie`, "bad");
        const noWarranty = rows.filter((r) => r.warranty_days === "");
        if (noWarranty.length) return toast(`Elige la garantía de: ${noWarranty.map((r) => r.name).join(", ")}`, "bad");
        const noPrice = rows.filter((r) => !num(r.price));
        if (noPrice.length && !await confirmBox(`${noPrice.length} producto(s) sin precio. ¿Guardar así?`)) return;
        try {
          const r = await POST("/api/products/bulk", { rows });
          toast(`${r.created.length} producto(s) creados`, "ok");
          if (r.errors.length) $("#qa-res", m).innerHTML = `<div class="danger">${r.errors.map(esc).join("<br>")}</div>`;
          else close();
          loadProducts();
        } catch (e) { fail(e); }
      };
    },
  });
}

function bulkPricing() {
  modal({
    title: "💲 Generador de precios masivo", size: "wide",
    body: `<div class="form-grid">
      <label class="f">Categoría<select id="bp-cat">${catOptions("", "Todas")}</select></label>
      <label class="f">Filtro (marca / nombre)<input id="bp-q" placeholder="opcional"></label>
      <label class="f">Cálculo<select id="bp-mode"><option value="markup">% de ganancia sobre el costo</option><option value="percent_change">Subir/bajar % el precio actual</option></select></label>
      <label class="f">Valor %<input id="bp-val" inputmode="decimal" value="${num(S.settings.default_markup)}"></label>
      <label class="f span-2">Redondeo<select id="bp-round">${roundingOptions(S.settings.price_rounding)}</select></label>
      <label class="chk span-2"><input type="checkbox" id="bp-tax" checked> El costo ya incluye IVA</label></div>
      <div class="row" style="margin:14px 0 10px"><button id="bp-prev">Vista previa</button><span class="muted small" id="bp-info"></span></div>
      <div class="table-wrap" style="max-height:340px"><table><thead><tr><th>SKU</th><th>Producto</th><th class="num">Costo</th><th class="num">Precio actual</th><th class="num">Precio nuevo</th></tr></thead><tbody id="bp-body"><tr><td colspan="5" class="empty">Ajusta los valores y da clic en Vista previa</td></tr></tbody></table></div>`,
    foot: `<button data-close>Cerrar</button><button class="primary" id="bp-apply" disabled>Aplicar precios nuevos</button>`,
    onOpen: (m, close) => {
      $("#bp-cat", m).onchange = () => { const c = S.categories.find((x) => String(x.id) === $("#bp-cat", m).value); if (c && $("#bp-mode", m).value === "markup") $("#bp-val", m).value = c.markup; };
      const payload = (apply) => ({ category_id: $("#bp-cat", m).value, q: $("#bp-q", m).value, mode: $("#bp-mode", m).value, value: num($("#bp-val", m).value), rounding: $("#bp-round", m).value, cost_includes_tax: $("#bp-tax", m).checked, apply });
      $("#bp-prev", m).onclick = async () => {
        try {
          const r = await POST("/api/pricing/bulk", payload(false));
          const changed = r.rows.filter((x) => x.new_price !== x.old_price).length;
          $("#bp-info", m).textContent = `${r.rows.length} producto(s) con costo, ${changed} cambian de precio`;
          $("#bp-body", m).innerHTML = r.rows.map((x) => `<tr><td class="mono small">${esc(x.sku)}</td><td>${esc(x.name)}</td><td class="num">${money(x.cost)}</td><td class="num">${money(x.old_price)}</td><td class="num"><b class="${x.new_price > x.old_price ? "" : "danger"}">${money(x.new_price)}</b></td></tr>`).join("") || '<tr><td colspan="5" class="empty">Sin productos con costo capturado</td></tr>';
          $("#bp-apply", m).disabled = !changed;
        } catch (e) { fail(e); }
      };
      $("#bp-apply", m).onclick = async () => {
        if (!await confirmBox("¿Actualizar los precios mostrados?")) return;
        try { const r = await POST("/api/pricing/bulk", payload(true)); toast(`${r.rows.length} precios actualizados`, "ok"); close(); loadProducts(); } catch (e) { fail(e); }
      };
    },
  });
}

function importCsv() {
  modal({
    title: "Importar productos desde CSV / Excel", size: "narrow",
    body: `<p class="small">Guarda tu hoja de Excel como <b>CSV</b>. Columnas reconocidas: <span class="mono small">sku, barcode, name, brand, model, color, capacity, category, cost, price, wholesale_price, stock, min_stock, serialized, track_stock, warranty_days, location, notes</span>. Si el SKU o código ya existe, se actualiza. Los productos nuevos deben traer <b>serialized</b>: <b>1</b> con serie, <b>0</b> sin serie.</p>
      <p><a href="/api/products/template.csv">⬇ Descargar plantilla de ejemplo</a></p>
      <input type="file" id="csv-file" accept=".csv,text/csv"><div id="csv-res" class="small" style="margin-top:10px"></div>`,
    foot: `<button data-close>Cerrar</button><button class="primary" id="csv-go">Importar</button>`,
    onOpen: (m) => {
      $("#csv-go", m).onclick = async () => {
        const file = $("#csv-file", m).files[0];
        if (!file) return toast("Selecciona un archivo", "bad");
        const fd = new FormData(); fd.append("file", file);
        try {
          const r = await api("POST", "/api/products/import", fd);
          $("#csv-res", m).innerHTML = `<b>${r.created}</b> creados, <b>${r.updated}</b> actualizados.${(r.warnings || []).map((w) => `<div class="pend-banner" style="margin-top:8px">⚠️ ${esc(w)}</div>`).join("")}${r.errors.length ? `<div class="danger">${r.errors.map(esc).join("<br>")}</div>` : ""}`;
          await loadBase(); loadProducts();
        } catch (e) { fail(e); }
      };
    },
  });
}

/* ================================================================== GARANTÍAS */
const fmtDate = (iso) => { if (!iso) return ""; const [y, m, d] = iso.slice(0, 10).split("-"); return `${d}/${m}/${y}`; };

function initGarantias() {
  $("#view-garantias").innerHTML = `
    <div class="view-head"><h1>Garantías y cambios</h1></div>
    <div class="search-box"><span class="scan-ico">🛡️</span>
      <input id="w-q" class="scan" autocomplete="off" placeholder="Escanea el código del ticket, o escribe IMEI, teléfono o nombre del cliente"></div>
    <p class="small muted" style="margin:8px 2px 0">El cliente no necesita traer el ticket: con el IMEI de su teléfono (*#06#) o su número se encuentra la garantía.</p>
    <div id="w-list" class="w-list"></div>`;
  const search = async () => {
    const q = $("#w-q").value.trim();
    if (q.length < 3) { $("#w-list").innerHTML = ""; return; }
    try { renderWarranty(await GET(`/api/warranty?q=${encodeURIComponent(q)}`)); } catch (e) { fail(e); }
  };
  $("#w-q").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); search(); } });
  $("#w-q").addEventListener("input", debounce(search, 400));
  $("#w-list").addEventListener("click", (e) => {
    const b = e.target.closest("[data-w]"); if (!b) return;
    if (b.dataset.w === "sale") showSale(+b.dataset.id);
    if (b.dataset.w === "claim") registerChange(JSON.parse(b.closest(".w-card").dataset.item));
    if (b.dataset.w === "print") printClaim(+b.dataset.id);
  });
  S.wSearch = search;
}

function renderWarranty(items) {
  const box = $("#w-list");
  if (!items.length) { box.innerHTML = '<div class="card empty">No se encontraron artículos con garantía. Revisa el IMEI o teléfono.</div>'; return; }
  const staff = can("admin", "matriz", "cajero");
  box.innerHTML = items.map((it) => {
    const status = it.sale_status !== "completada" ? '<span class="badge bad">Venta cancelada</span>'
      : it.valid ? `<span class="badge ok">Vigente · vence ${fmtDate(it.expires)} (${it.days_left} días)</span>`
      : `<span class="badge bad">Vencida el ${fmtDate(it.expires)}</span>`;
    const total = it.warranty_changes;
    const dots = total ? Array.from({ length: Math.max(total, it.changes_used) }, (_, i) =>
      `<span class="${i < it.changes_used ? (i >= total ? "x" : "u") : ""}">${i + 1}</span>`).join("") : "";
    const cls = !it.valid ? "expired" : total && !it.changes_left ? "used" : "";
    const blocked = !it.valid || !it.changes_left;
    const btn = staff ? (blocked
      ? (can("admin") && it.sale_status === "completada" ? `<button class="danger" data-w="claim">Autorizar cambio extra</button>` : `<button disabled>Sin cambios disponibles</button>`)
      : `<button class="primary" data-w="claim">🔄 Registrar cambio</button>`) : "";
    return `<div class="w-card ${cls}" data-item='${esc(JSON.stringify(it))}'>
      <div class="w-head"><h2>${esc(it.name)}</h2>${status}</div>
      <div class="w-info">
        <div><small>Nota</small><a data-w="sale" data-id="${it.sale_id}" class="mono">${esc(it.folio)}</a> · ${fmtDate(it.sale_date)}</div>
        <div><small>Cliente</small>${esc(it.customer_name || "—")} ${it.customer_phone ? `· ${esc(it.customer_phone)}` : ""}</div>
        <div><small>Equipo</small>${esc(it.device_model || "—")}<div class="mono small">${esc(it.device_imei || it.imei || "")}</div></div>
        <div><small>Garantía</small>${esc(it.warranty_label)}${total ? ` · ${total} cambio${total > 1 ? "s" : ""}` : ""}</div>
        <div><small>Vendedor</small>${esc(it.seller_name || "—")}</div>
      </div>
      <div class="w-changes">
        ${total ? `<div class="dots">${dots}</div><b>${it.changes_used} de ${total} usados · ${it.changes_left ? `queda${it.changes_left > 1 ? "n" : ""} ${it.changes_left}` : "sin cambios restantes"}</b>`
          : '<span class="muted">Garantía sin cambios incluidos</span>'}
        <span class="spacer"></span>${btn}
      </div>
      ${it.claims.length ? `<div class="w-hist">${it.claims.map((c) => `<div><b>Cambio ${c.number}</b><span>${esc(c.created_at.slice(0, 16))}</span><span class="muted">${esc(c.user_name)}</span>
        <span>${esc(c.notes || "")}</span>${c.forced ? '<span class="badge warn">autorizado</span>' : ""}<span class="spacer"></span>
        <button class="sm" data-w="print" data-id="${c.id}" title="Reimprimir comprobante">🖨</button></div>`).join("")}</div>` : ""}
    </div>`;
  }).join("");
}

function registerChange(it) {
  const problems = [];
  if (!it.valid) problems.push(`la garantía venció el ${fmtDate(it.expires)}`);
  if (!it.changes_left) problems.push(it.warranty_changes ? "ya usó todos sus cambios" : "este artículo no incluye cambios");
  const next = it.changes_used + 1;
  modal({
    title: `🔄 Cambio ${next}${it.warranty_changes ? ` de ${it.warranty_changes}` : ""}`, size: "narrow",
    body: `<p style="margin-top:0"><b>${esc(it.name)}</b><br><span class="small muted">${esc(it.device_model || "")} ${esc(it.device_imei || "")} · nota ${esc(it.folio)}</span></p>
      ${problems.length ? `<div class="pend-banner" style="margin:0 0 12px">⚠️ No aplica: ${problems.join(" y ")}.</div>` : ""}
      <div class="grid" style="gap:10px">
        <label class="f">Motivo (opcional)<input id="cl-notes" autofocus placeholder="p. ej. se estrelló, burbujas, se despegó"></label>
        <label class="chk"><input type="checkbox" id="cl-stock" checked> Descontar 1 pieza del inventario</label>
        <label class="chk"><input type="checkbox" id="cl-print" checked> Imprimir comprobante para el cliente</label>
        ${problems.length ? '<label class="chk danger"><input type="checkbox" id="cl-force"> Autorizar de todos modos (administrador)</label>' : ""}
      </div>`,
    foot: `<button data-close>Cancelar</button><button class="primary" id="cl-ok">Registrar cambio</button>`,
    onOpen: (m, close) => {
      $("#cl-ok", m).onclick = async () => {
        const force = $("#cl-force", m)?.checked || false;
        if (problems.length && !force) return toast("Marca “Autorizar de todos modos” para continuar", "bad");
        const print = $("#cl-print", m).checked;
        const browserPrint = print && S.settings.ticket_printer_mode === "browser";
        const win = browserPrint ? window.open("about:blank", "ticket", "width=420,height=720") : null;
        try {
          const r = await POST("/api/warranty/claims", { sale_item_id: it.id, notes: $("#cl-notes", m).value, take_stock: $("#cl-stock", m).checked, force, print: print && !browserPrint });
          close();
          if (win) win.location = `/tickets/cambio/${r.claim_id}?print=1`;
          if (r.print_error) toast(`Cambio registrado, pero no se imprimió: ${r.print_error}`, "bad");
          const left = r.item.changes_left;
          toast(`Cambio ${r.item.changes_used} registrado. ${r.item.warranty_changes ? `Le quedan ${left}.` : ""}`, "ok");
          S.wSearch?.();
        } catch (e) { if (win) win.close(); fail(e); }
      };
    },
  });
}

async function printClaim(id) {
  if (S.settings.ticket_printer_mode === "browser") return openTicketWindow(`/tickets/cambio/${id}?print=1`);
  try { const r = await POST(`/api/warranty/claims/${id}/print`); toast(r.message || "Enviado", "ok"); } catch (e) { fail(e); }
}

VIEWS.garantias = () => setTimeout(() => $("#w-q").select(), 30);

/* ================================================================== ETIQUETAS */
function queueItem(item) {
  const exists = S.labelQueue.find((q) => q.product_id && q.product_id === item.product_id && (q.imei || "") === (item.imei || "") && !q.all_imeis);
  if (exists && !item.imei) exists.qty += item.qty || 1;
  else if (!exists) S.labelQueue.push({ qty: 1, ...item });
  S.labelSel = S.labelQueue.indexOf(exists || S.labelQueue[S.labelQueue.length - 1]);
  saveQueue();
}
async function addToLabelQueue(id, qty = 1, allImeis = false) {
  try {
    const p = await GET(`/api/products/${id}`);
    queueItem({ product_id: p.id, name: p.name, sku: p.sku, qty, serialized: p.serialized, all_imeis: allImeis && p.serialized ? true : false, stock: p.stock });
    toast(`Agregado a etiquetas: ${p.name}`, "ok");
  } catch (e) { fail(e); }
}
const saveQueue = () => { try { localStorage.setItem("pos-labels", JSON.stringify(S.labelQueue)); } catch (_) { /* */ } };

function initEtiquetas() {
  try { S.labelQueue = JSON.parse(localStorage.getItem("pos-labels") || "[]"); } catch (_) { S.labelQueue = []; }
  $("#view-etiquetas").innerHTML = `
    <div class="view-head"><h1>Etiquetas Zebra</h1><span class="muted small" id="lb-printer"></span></div>
    <div class="label-layout">
      <div>
        <div class="card">
          <div class="search-box"><span class="scan-ico">🏷️</span><input id="lb-scan" class="scan" autocomplete="off" placeholder="Escanea o busca productos para etiquetar"></div>
          <div class="row" style="margin-top:10px">
            <button id="lb-custom">✏️ Etiqueta libre</button>
            <button id="lb-low">Agregar productos con existencia</button>
            <span class="spacer"></span>
            <button class="danger" id="lb-clear">Vaciar lista</button>
          </div>
        </div>
        <div class="table-wrap" style="margin-top:14px"><table><thead><tr><th>Etiqueta</th><th>Detalle</th><th class="center">Copias</th><th></th></tr></thead><tbody id="lb-body"></tbody></table></div>
        <div class="card" id="lb-in-card" style="margin-top:14px">
          <div class="row" style="margin-bottom:8px"><h2 style="margin:0">📦 Mercancía recibida</h2><span class="muted small" id="lb-in-branch"></span>
            <span class="spacer"></span><select id="lb-in-days" style="width:auto"><option value="3">Últimos 3 días</option><option value="7" selected>Últimos 7 días</option><option value="30">Últimos 30 días</option></select></div>
          <div class="table-wrap" style="max-height:300px"><table><thead><tr><th>Fecha</th><th>Producto</th><th>Llegó</th><th class="num">Piezas</th><th></th></tr></thead><tbody id="lb-in"></tbody></table></div>
        </div>
      </div>
      <div class="card">
        <label class="f">Plantilla / tamaño de etiqueta<select id="lb-tpl"></select></label>
        <p class="small muted" id="lb-tpl-desc" style="margin:6px 0 12px"></p>
        <div class="preview-box" id="lb-preview"><span class="muted">Agrega productos para ver la vista previa</span></div>
        <div class="row" style="margin-top:12px"><b id="lb-total">0 etiquetas</b><span class="spacer"></span>
          <button id="lb-dl">⬇ Descargar .ZPL</button><button class="primary" id="lb-print">🖨 Imprimir en Zebra</button></div>
        <details style="margin-top:14px"><summary class="small muted" style="cursor:pointer">Ver código ZPL de la etiqueta seleccionada</summary>
          <textarea class="zpl" id="lb-zpl" readonly style="margin-top:8px"></textarea>
          <div class="row" style="margin-top:6px"><button class="sm" id="lb-copy">Copiar ZPL</button><a class="small" href="https://labelary.com/viewer.html" target="_blank" rel="noopener">Probar en Labelary ↗</a></div>
        </details>
      </div>
    </div>`;
  attachProductSearch($("#lb-scan"), (p, imei) => {
    if (!p) return;
    if (imei) queueItem({ product_id: p.id, name: p.name, sku: p.sku, imei, qty: 1, serialized: 1 });
    else queueItem({ product_id: p.id, name: p.name, sku: p.sku, qty: 1, serialized: p.serialized, stock: p.stock });
    renderQueue();
  });
  $("#lb-tpl").onchange = () => { S.labelTemplate = $("#lb-tpl").value; renderQueue(); };
  $("#lb-clear").onclick = () => { S.labelQueue = []; saveQueue(); renderQueue(); };
  $("#lb-custom").onclick = customLabel;
  $("#lb-low").onclick = async () => {
    try {
      const list = (await GET("/api/products?limit=1000")).filter((p) => p.track_stock && p.stock > 0);
      if (!await confirmBox(`Se agregarán ${list.length} productos con una etiqueta por pieza en existencia (los celulares, una por IMEI). ¿Continuar?`)) return;
      list.forEach((p) => queueItem({ product_id: p.id, name: p.name, sku: p.sku, qty: p.serialized ? 1 : Number(p.stock), serialized: p.serialized, all_imeis: !!p.serialized, stock: p.stock }));
      renderQueue();
    } catch (e) { fail(e); }
  };
  $("#lb-body").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-i]"); if (!tr) return;
    const i = +tr.dataset.i;
    const b = e.target.closest("[data-a]");
    if (b?.dataset.a === "del") { S.labelQueue.splice(i, 1); S.labelSel = Math.max(0, Math.min(S.labelSel, S.labelQueue.length - 1)); saveQueue(); return renderQueue(); }
    if (e.target.matches("input")) return;
    S.labelSel = i; renderQueue();
  });
  $("#lb-body").addEventListener("change", (e) => {
    const tr = e.target.closest("tr[data-i]"); if (!tr) return;
    const it = S.labelQueue[+tr.dataset.i];
    if (e.target.dataset.f === "qty") it.qty = Math.max(0, Math.round(num(e.target.value)));
    if (e.target.dataset.f === "all") { it.all_imeis = e.target.checked; }
    saveQueue(); renderQueue();
  });
  $("#lb-dl").onclick = async () => {
    try { const r = await POST("/api/labels/zpl", labelPayload()); download(`etiquetas_${today()}.zpl`, r.zpl); toast(`${r.count} etiqueta(s) en el archivo ZPL`, "ok"); } catch (e) { fail(e); }
  };
  $("#lb-print").onclick = async () => {
    if (S.settings.label_printer_mode === "download") return $("#lb-dl").click();
    try { const r = await POST("/api/labels/zpl", { ...labelPayload(), print: true }); toast(r.message, "ok"); } catch (e) { fail(e); }
  };
  $("#lb-in-days").onchange = loadIncoming;
  $("#lb-in").addEventListener("click", (e) => {
    const b = e.target.closest("[data-in]"); if (!b) return;
    const row = S.incoming.find((x) => x.id === +b.dataset.in); if (!row) return;
    if (row.serialized) row.imeis.forEach((imei) => queueItem({ product_id: row.product_id, name: row.name, sku: row.sku, imei, qty: 1, serialized: 1 }));
    else queueItem({ product_id: row.product_id, name: row.name, sku: row.sku, qty: Math.round(row.qty), serialized: 0 });
    toast(`${row.pending} etiqueta(s) de ${row.name} agregadas`, "ok");
    renderQueue();
  });
  $("#lb-copy").onclick = () => { navigator.clipboard?.writeText($("#lb-zpl").value); toast("ZPL copiado"); };
}

function labelPayload() {
  return { template: $("#lb-tpl").value, items: S.labelQueue.map((q) => q.custom ? { custom: q.custom, qty: q.qty } : { product_id: q.product_id, qty: q.qty, imei: q.imei, all_imeis: q.all_imeis }) };
}

function customLabel() {
  modal({
    title: "Etiqueta libre", size: "narrow",
    body: `<div class="grid" style="gap:10px">
      <label class="f">Texto / nombre<input id="cl-name" autofocus placeholder="p. ej. OFERTA Mica 9D"></label>
      <label class="f">Precio<input id="cl-price" inputmode="decimal" placeholder="opcional"></label>
      <label class="f">Código de barras / texto del código<input id="cl-code" class="mono" placeholder="opcional"></label>
      <label class="f">Copias<input id="cl-qty" inputmode="numeric" value="1"></label></div>`,
    foot: `<button data-close>Cancelar</button><button class="primary" id="cl-ok">Agregar</button>`,
    onOpen: (m, close) => {
      $("#cl-ok", m).onclick = () => {
        const custom = { name: $("#cl-name", m).value, price: $("#cl-price", m).value, barcode: $("#cl-code", m).value.trim() };
        if (!custom.name && !custom.barcode) return toast("Escribe un texto o código", "bad");
        S.labelQueue.push({ custom, name: custom.name || custom.barcode, qty: Math.max(1, Math.round(num($("#cl-qty", m).value))) });
        S.labelSel = S.labelQueue.length - 1; saveQueue(); close(); renderQueue();
      };
    },
  });
}

const refreshPreview = debounce(async () => {
  const it = S.labelQueue[S.labelSel];
  if (!it) { $("#lb-preview").innerHTML = '<span class="muted">Agrega productos para ver la vista previa</span>'; $("#lb-zpl").value = ""; return; }
  try {
    const item = it.custom ? { custom: it.custom, qty: 1 } : { product_id: it.product_id, imei: it.imei, all_imeis: it.all_imeis, qty: 1 };
    const r = await POST("/api/labels/preview", { template: $("#lb-tpl").value, item });
    $("#lb-preview").innerHTML = r.svg;
    $("#lb-zpl").value = r.zpl;
  } catch (e) { $("#lb-preview").innerHTML = `<span class="danger">${esc(e.message)}</span>`; }
}, 120);

function renderQueue() {
  const body = $("#lb-body");
  body.innerHTML = S.labelQueue.length ? S.labelQueue.map((q, i) => `<tr data-i="${i}" class="${i === S.labelSel ? "sel-row" : ""}" style="cursor:pointer">
      <td><b>${esc(q.name)}</b><div class="small muted mono">${esc(q.custom ? "Etiqueta libre" : q.sku || "")}</div></td>
      <td class="small">${q.imei ? `<span class="badge info">IMEI ${esc(q.imei)}</span>` : q.serialized ? `<label class="chk"><input type="checkbox" data-f="all" ${q.all_imeis ? "checked" : ""}> Una por cada IMEI disponible</label>` : q.stock !== undefined ? `<span class="muted">Existencia: ${Number(q.stock)}</span>` : ""}</td>
      <td class="center"><input data-f="qty" value="${q.qty}" style="width:64px;text-align:center"></td>
      <td><button class="sm danger icon-btn" data-a="del">✕</button></td></tr>`).join("")
    : `<tr><td colspan="4" class="empty">Escanea productos, o en Productos usa el botón 🏷️.</td></tr>`;
  const total = S.labelQueue.reduce((a, q) => a + (q.all_imeis ? Math.max(1, q.qty) * Math.max(1, Number(q.stock) || 1) : q.qty), 0);
  $("#lb-total").textContent = `${total} etiqueta(s)`;
  const tpl = S.templates[$("#lb-tpl").value];
  $("#lb-tpl-desc").textContent = tpl ? `${tpl.description} · ${S.settings.label_dpi} dpi` : "";
  refreshPreview();
}

async function loadIncoming() {
  $("#lb-in-branch").textContent = S.me ? `en ${S.me.branch.name}` : "";
  try { S.incoming = await GET(`/api/inventory/incoming?days=${$("#lb-in-days").value}`); } catch (e) { S.incoming = []; }
  $("#lb-in").innerHTML = S.incoming.map((r) => `<tr><td class="small nowrap">${esc(r.created_at.slice(0, 16))}</td>
      <td><b>${esc(r.name)}</b><div class="small muted mono">${esc(r.sku)}${r.serialized ? ` · ${r.pending} con IMEI disponibles` : ""}</div></td>
      <td class="small">${r.kind === "traspaso" ? `Traspaso ${esc(r.reference)}` : "Entrada"}</td><td class="num">${Number(r.qty)}</td>
      <td>${r.pending ? `<button class="sm primary" data-in="${r.id}">🏷️ Etiquetar ${r.pending}</button>` : '<span class="small muted">Ya vendidos</span>'}</td></tr>`).join("")
    || '<tr><td colspan="5" class="empty">No ha llegado mercancía en estos días.</td></tr>';
}

VIEWS.etiquetas = () => {
  loadIncoming();
  const sel = $("#lb-tpl");
  sel.innerHTML = templateOptions(S.labelTemplate || S.settings.label_template);
  const modes = { download: "Modo: descargar archivo .ZPL", network: `Zebra en red: ${S.settings.label_printer_host}:${S.settings.label_printer_port}`, local: `Zebra USB: ${S.settings.label_printer_name}` };
  $("#lb-printer").textContent = modes[S.settings.label_printer_mode] || "";
  renderQueue();
  setTimeout(() => $("#lb-scan").focus(), 30);
};

/* ================================================================== INVENTARIO */
function initInventario() {
  $("#view-inventario").innerHTML = `
    <div class="view-head"><h1>Inventario e IMEI</h1></div>
    <div class="card" style="margin-bottom:16px"><h2>📦 Recepción de mercancía / inventario inicial</h2>
      <p class="small muted" style="margin:-4px 0 10px">Agrega los productos que llegaron. <b>Sin serie</b>: escribe la cantidad. <b>Con serie</b>: escanea la serie de cada pieza (la cantidad se cuenta sola).</p>
      <div class="search-box"><span class="scan-ico">➕</span><input id="rc-scan" class="scan" autocomplete="off" placeholder="Escanea o busca un producto del catálogo para agregarlo"></div>
      <div class="table-wrap" style="margin-top:10px;max-height:none"><table><thead><tr><th>Producto</th><th>Tipo</th><th>Cantidad / series</th><th class="num">Costo unit.</th><th></th></tr></thead><tbody id="rc-body"></tbody></table></div>
      <div class="row" style="margin-top:10px"><input id="rc-ref" placeholder="Proveedor / factura (opcional)" style="max-width:280px"><input id="rc-notes" placeholder="Nota (opcional)" style="max-width:280px">
        <label class="chk small"><input type="checkbox" id="rc-lbl" checked> Mandar a etiquetas lo recibido</label><span class="spacer"></span>
        <button class="primary" id="rc-save">Registrar recepción</button></div>
      <div id="rc-res" class="small" style="margin-top:8px;white-space:pre-line"></div>
    </div>
    <div class="grid cols-2">
      <div class="card"><h2>📥 Entrada / ajuste de mercancía</h2>
        <div class="search-box"><span class="scan-ico">🔎</span><input id="inv-scan" class="scan" autocomplete="off" placeholder="Escanea o busca el producto"></div>
        <div id="inv-form" class="muted small" style="margin-top:12px">Selecciona un producto. Para celulares, escanea sus IMEIs.</div>
      </div>
      <div class="card"><h2>⚠️ Existencia baja</h2><div class="table-wrap" style="max-height:330px"><table><thead><tr><th>Producto</th><th class="num">Exist.</th><th class="num">Mín.</th><th></th></tr></thead><tbody id="inv-low"></tbody></table></div></div>
    </div>
    <div class="card"><div class="row" style="margin-bottom:10px"><h2 style="margin:0">Movimientos recientes</h2></div>
      <div class="table-wrap" style="max-height:420px"><table><thead><tr><th>Fecha</th><th class="multi-col">Sucursal</th><th>Producto</th><th>Tipo</th><th class="num">Cantidad</th><th>Referencia / nota</th></tr></thead><tbody id="inv-moves"></tbody></table></div></div>`;
  attachProductSearch($("#inv-scan"), (p) => p && invSelect(p.id));
  S.reception = [];
  const renderRc = () => {
    $("#rc-body").innerHTML = S.reception.map((r, i) => `<tr data-i="${i}"><td><b>${esc(r.name)}</b><div class="small muted mono">${esc(r.sku)}</div></td>
      <td>${r.serialized ? '<span class="badge info">Con serie</span>' : '<span class="badge">Sin serie</span>'}</td>
      <td>${r.serialized
        ? `<textarea data-r="serials" class="mono" style="min-height:70px;min-width:240px" placeholder="Escanea una serie por renglón">${esc(r.serials || "")}</textarea><div class="small muted" data-r="count">${(r.serials || "").split(/[\s,;]+/).filter(Boolean).length} serie(s)</div>`
        : `<input data-r="qty" inputmode="decimal" value="${r.qty ?? ""}" placeholder="Piezas" style="width:110px">`}</td>
      <td class="num"><input data-r="cost" inputmode="decimal" value="${r.cost ?? ""}" placeholder="${r.cur_cost ?? ""}" style="width:100px"></td>
      <td><button class="sm danger icon-btn" data-r="rm">✕</button></td></tr>`).join("")
      || '<tr><td colspan="5" class="empty">Escanea o busca productos para agregarlos a la recepción.</td></tr>';
  };
  attachProductSearch($("#rc-scan"), (p) => {
    if (!p) return;
    if (S.reception.some((r) => r.product_id === p.id)) return toast("Ese producto ya está en la recepción", "bad");
    S.reception.push({ product_id: p.id, name: p.name, sku: p.sku, serialized: p.serialized, cur_cost: p.cost });
    renderRc();
    setTimeout(() => $(`#rc-body tr[data-i="${S.reception.length - 1}"] [data-r]`)?.focus(), 30);
  });
  $("#rc-body").addEventListener("input", (e) => {
    const tr = e.target.closest("tr[data-i]"); if (!tr) return;
    const r = S.reception[+tr.dataset.i];
    r[e.target.dataset.r] = e.target.value;
    if (e.target.dataset.r === "serials") $('[data-r="count"]', tr).textContent = `${e.target.value.split(/[\s,;]+/).filter(Boolean).length} serie(s)`;
  });
  $("#rc-body").addEventListener("click", (e) => {
    if (!e.target.closest('[data-r="rm"]')) return;
    S.reception.splice(+e.target.closest("tr").dataset.i, 1); renderRc();
  });
  $("#rc-save").onclick = async () => {
    if (!S.reception.length) return toast("Agrega al menos un producto", "bad");
    try {
      const r = await POST("/api/inventory/receive", { lines: S.reception.map((x) => ({ product_id: x.product_id, qty: x.qty, serials: x.serials, cost: x.cost })),
        reference: $("#rc-ref").value, notes: $("#rc-notes").value });
      $("#rc-res").textContent = r.message;
      toast(r.message, "ok");
      if ($("#rc-lbl").checked) r.lines.forEach((l) => {
        if (l.serialized) l.serials.forEach((imei) => queueItem({ product_id: l.product_id, name: l.name, sku: l.sku, imei, qty: 1, serialized: 1 }));
        else queueItem({ product_id: l.product_id, name: l.name, sku: l.sku, qty: Math.round(l.qty), serialized: 0 });
      });
      S.reception = []; $("#rc-ref").value = ""; $("#rc-notes").value = ""; renderRc(); VIEWS.inventario();
    } catch (e) { $("#rc-res").innerHTML = `<div class="danger">${esc(e.message)}</div>`; fail(e); }
  };
  renderRc();
  $("#inv-low").addEventListener("click", (e) => { const b = e.target.closest("[data-id]"); if (b) invSelect(+b.dataset.id); });
}

async function invSelect(id) {
  let p;
  try { p = await GET(`/api/products/${id}`); } catch (e) { return fail(e); }
  const box = $("#inv-form");
  box.classList.remove("muted", "small");
  if (p.serialized) {
    box.innerHTML = `<h3>${esc(p.name)} <span class="badge info">IMEI</span></h3><p class="small muted">${esc(p.sku)} · disponibles: <b>${Number(p.stock)}</b></p>
      <label class="f">Escanea los IMEIs que llegaron (uno por renglón)<textarea id="iv-imeis" class="mono" style="min-height:140px"></textarea></label>
      <label class="chk small" style="margin:8px 0"><input type="checkbox" id="iv-lbl" checked> Enviar a etiquetas (una por IMEI)</label>
      <div class="row"><button class="primary" id="iv-add">Registrar IMEIs</button><button id="iv-manage">Ver / dar de baja IMEIs</button></div>
      ${S.multi ? `<fieldset style="margin-top:14px"><legend>🔁 Traspasar equipos a otra sucursal</legend>
        <div class="grid" style="gap:8px"><select id="tr-dst">${branchOptions("", { all: false })}</select>
        <textarea id="tr-imeis" class="mono" placeholder="Escanea los IMEI que se envían (uno por renglón)" style="min-height:70px"></textarea>
        <div><button id="tr-go">Enviar a la sucursal</button></div></div></fieldset>` : ""}`;
    const trg = $("#tr-go");
    if (trg) {
      $("#tr-dst").firstElementChild.remove();
      trg.onclick = async () => {
        try { const r = await POST("/api/inventory/transfer", { product_id: p.id, to_branch_id: +$("#tr-dst").value, imeis: $("#tr-imeis").value }); toast(r.message, "ok"); invSelect(p.id); VIEWS.inventario(); } catch (e) { fail(e); }
      };
    }
    $("#iv-imeis").focus();
    $("#iv-manage").onclick = () => imeiManager(p.id);
    $("#iv-add").onclick = async () => {
      try {
        const r = await POST(`/api/products/${p.id}/serials`, { imeis: $("#iv-imeis").value, notes: "Entrada" });
        toast(`${r.added.length} IMEI registrados${r.skipped.length ? ` · ya existían: ${r.skipped.join(", ")}` : ""}`, r.skipped.length ? "bad" : "ok");
        if ($("#iv-lbl").checked) r.added.forEach((imei) => queueItem({ product_id: p.id, name: p.name, sku: p.sku, imei, qty: 1, serialized: 1 }));
        invSelect(p.id); VIEWS.inventario();
      } catch (e) { fail(e); }
    };
    return;
  }
  box.innerHTML = `<h3>${esc(p.name)}</h3><p class="small muted">${esc(p.sku)} · existencia actual: <b>${Number(p.stock)}</b> · costo ${money(p.cost)}</p>
    <div class="form-grid" style="grid-template-columns:repeat(3,minmax(0,1fr))">
      <label class="f">Movimiento<select id="iv-kind"><option value="entrada">Entrada (compra)</option><option value="salida">Salida (merma / uso)</option><option value="conteo">Conteo físico (fijar existencia)</option>${S.multi ? '<option value="traspaso">Traspaso a otra sucursal</option>' : ""}</select></label>
      <label class="f">Cantidad<input id="iv-qty" inputmode="decimal" value="1"></label>
      <label class="f" id="iv-cost-f">Costo unitario nuevo<input id="iv-cost" inputmode="decimal" placeholder="${p.cost ?? ""}"></label>
      <label class="f hidden" id="iv-dst-f">Enviar a<select id="iv-dst">${S.multi ? branchOptions("", { all: false }) : ""}</select></label>
      <label class="f span-all" style="grid-column:1/-1">Nota / proveedor<input id="iv-notes"></label></div>
    <label class="chk small" style="margin:8px 0"><input type="checkbox" id="iv-lbl"> Enviar etiquetas de las piezas que entran</label>
    <div class="row"><button class="primary" id="iv-save">Registrar movimiento</button></div>`;
  $("#iv-qty").select();
  if (S.multi) $("#iv-dst").firstElementChild.remove();
  $("#iv-kind").onchange = () => {
    const tr = $("#iv-kind").value === "traspaso";
    $("#iv-dst-f").classList.toggle("hidden", !tr); $("#iv-cost-f").classList.toggle("hidden", tr);
  };
  $("#iv-save").onclick = async () => {
    const kind = $("#iv-kind").value, qty = num($("#iv-qty").value);
    if (kind === "traspaso") {
      try { const r = await POST("/api/inventory/transfer", { product_id: p.id, to_branch_id: +$("#iv-dst").value, qty, notes: $("#iv-notes").value }); toast(r.message, "ok"); invSelect(p.id); VIEWS.inventario(); } catch (e) { fail(e); }
      return;
    }
    try {
      const r = await POST("/api/inventory/adjust", { product_id: p.id, kind, qty, cost: $("#iv-cost").value, notes: $("#iv-notes").value });
      toast(`Existencia de ${r.name}: ${Number(r.stock)}`, "ok");
      if ($("#iv-lbl").checked && kind === "entrada") queueItem({ product_id: p.id, name: p.name, sku: p.sku, qty: Math.round(qty), stock: r.stock });
      invSelect(p.id); VIEWS.inventario();
    } catch (e) { fail(e); }
  };
}

VIEWS.inventario = async () => {
  try {
    const [low, moves] = await Promise.all([GET("/api/products?low=1"), GET("/api/inventory/moves")]);
    $("#inv-low").innerHTML = low.map((p) => `<tr><td>${esc(p.name)}<div class="small muted mono">${esc(p.sku)}</div></td><td class="num"><span class="badge ${p.stock <= 0 ? "bad" : "warn"}">${Number(p.stock)}</span></td><td class="num">${Number(p.min_stock)}</td><td><button class="sm" data-id="${p.id}">Surtir</button></td></tr>`).join("") || '<tr><td colspan="4" class="empty">Todo en orden 👍</td></tr>';
    $("#view-inventario").classList.toggle("single-branch", !S.multi);
    $("#inv-moves").innerHTML = moves.map((m) => `<tr><td class="small nowrap">${esc(m.created_at)}</td><td class="small multi-col">${esc(m.branch_name || "")}</td><td>${esc(m.name)}<div class="small muted mono">${esc(m.sku)}</div></td>
      <td><span class="badge ${m.qty > 0 ? "ok" : "warn"}">${esc(m.kind)}</span></td><td class="num">${m.qty > 0 ? "+" : ""}${Number(m.qty)}</td><td class="small">${esc(m.reference || "")} ${esc(m.notes || "")}</td></tr>`).join("") || '<tr><td colspan="5" class="empty">Sin movimientos</td></tr>';
  } catch (e) { fail(e); }
  setTimeout(() => $("#inv-scan").focus(), 30);
};

/* ================================================================== VENTAS */
function initVentas() {
  $("#view-ventas").innerHTML = `
    <div class="view-head"><h1>Ventas y tickets</h1></div>
    <div class="row" style="margin-bottom:12px">
      <label class="f">Desde<input type="date" id="v-from"></label><label class="f">Hasta<input type="date" id="v-to"></label>
      <label class="f" style="flex:1;max-width:380px">Buscar (garantías)<input id="v-q" placeholder="Folio, cliente, teléfono, IMEI, modelo, producto…"></label>
      <label class="chk small" style="align-self:flex-end;margin-bottom:10px"><input type="checkbox" id="v-all" checked> Buscar en todas las fechas</label>
      <label class="f admin-branch">Sucursal<select id="v-branch"></select></label>
      <span class="spacer"></span><div id="v-sum" class="muted"></div></div>
    <div class="table-wrap"><table><thead><tr><th>Folio</th><th>Fecha</th><th class="multi-col">Sucursal</th><th>Vendedor</th><th>Cliente</th><th>Equipo</th><th class="num">Piezas</th><th>Pago</th><th class="num">Total</th><th>Estado</th><th></th></tr></thead><tbody id="v-body"></tbody></table></div>`;
  $("#v-from").value = today(); $("#v-to").value = today();
  ["v-from", "v-to"].forEach((i) => $("#" + i).onchange = VIEWS.ventas);
  $("#v-q").oninput = debounce(VIEWS.ventas, 250);
  $("#v-all").onchange = VIEWS.ventas;
  $("#v-branch").onchange = VIEWS.ventas;
  $("#v-body").addEventListener("click", (e) => {
    const b = e.target.closest("[data-a]"); if (!b) return;
    const id = +b.closest("tr").dataset.id;
    if (b.dataset.a === "view") showSale(id);
    if (b.dataset.a === "print") printSale(id);
  });
}
VIEWS.ventas = async () => {
  try {
    if (!$("#v-branch").options.length) $("#v-branch").innerHTML = branchOptions(S.me.can_switch_branch ? "all" : "");
    $("#view-ventas").classList.toggle("single-branch", !S.multi);
    $("#view-ventas").classList.toggle("no-branch-pick", !(S.multi && S.me.can_switch_branch));
    const list = await GET(`/api/sales?from=${$("#v-from").value}&to=${$("#v-to").value}&q=${encodeURIComponent($("#v-q").value)}&all=${$("#v-all").checked ? 1 : 0}${branchParam("#v-branch")}`);
    const ok = list.filter((s) => s.status === "completada");
    $("#v-sum").innerHTML = `${ok.length} venta(s) · <b>${money(ok.reduce((a, s) => a + s.total, 0))}</b>`;
    $("#v-body").innerHTML = list.map((s) => `<tr data-id="${s.id}"><td class="mono"><a data-a="view">${esc(s.folio)}</a></td><td class="small">${esc(s.created_at)}</td><td class="small multi-col">${esc(s.branch_name || "")}</td><td>${esc(s.seller_name || s.cashier || "—")}</td>
      <td>${esc(s.customer_name || "—")}<div class="small muted">${esc(s.customer_phone || "")}</div></td><td class="small">${esc(s.device_model || "")}<div class="mono muted">${esc(s.device_imei || "")}</div></td><td class="num">${Number(s.units || 0)}</td>
      <td>${esc(s.payment_method)}</td><td class="num"><b>${money(s.total)}</b></td>
      <td>${s.status === "completada" ? '<span class="badge ok">Completada</span>' : s.status === "pendiente" ? '<span class="badge warn">Por cobrar</span>' : '<span class="badge bad">Cancelada</span>'}</td>
      <td><button class="sm" data-a="view">Ver</button> <button class="sm" data-a="print">🖨</button></td></tr>`).join("") || '<tr><td colspan="11" class="empty">Sin ventas</td></tr>';
  } catch (e) { fail(e); }
};

/* ================================================================== CORTE Y REPORTES */
function initCorte() {
  $("#view-corte").innerHTML = `
    <div class="view-head"><h1>Corte de caja y reportes</h1>
      <button id="c-print">🖨 Imprimir corte</button></div>
    <div class="row" style="margin-bottom:14px">
      <label class="f">Desde<input type="date" id="c-from"></label><label class="f">Hasta<input type="date" id="c-to"></label>
      <div class="row" style="align-self:flex-end"><button class="sm" data-r="0">Hoy</button><button class="sm" data-r="1">Ayer</button><button class="sm" data-r="7">7 días</button><button class="sm" data-r="30">30 días</button><button class="sm" data-r="m">Este mes</button></div>
      <label class="f admin-branch">Sucursal<select id="c-branch"></select></label></div>
    <div class="kpis" id="c-kpis"></div>
    <div class="grid cols-2">
      <div class="card"><h2>Formas de pago y caja</h2><table><tbody id="c-pay"></tbody></table>
        <h3 style="margin:18px 0 8px">Movimiento de efectivo</h3>
        <div class="row"><select id="c-kind" style="max-width:190px"><option value="entrada">Entrada / fondo de caja</option><option value="salida">Salida / gasto / retiro</option></select>
          <input id="c-amt" inputmode="decimal" placeholder="Monto" style="max-width:120px"><input id="c-note" placeholder="Concepto" style="flex:1;min-width:120px"><button class="primary" id="c-add">Registrar</button></div>
        <table style="margin-top:8px"><tbody id="c-cash"></tbody></table></div>
      <div class="card"><h2>Ventas por categoría</h2><table><thead><tr><th>Categoría</th><th class="num">Piezas</th><th class="num">Venta</th><th class="num">Utilidad</th></tr></thead><tbody id="c-cat"></tbody></table></div>
    </div>
    <div class="card multi-col" id="c-branch-card"><h2>Ventas por sucursal</h2><table><thead><tr><th>Sucursal</th><th class="num">Ventas</th><th class="num">Total</th><th class="num">Efectivo</th><th class="num">Utilidad</th></tr></thead><tbody id="c-bybranch"></tbody></table></div>
    <div class="card"><h2>Ventas por vendedor</h2><table><thead><tr><th>Vendedor</th><th class="num">Ventas</th><th class="num">Total</th><th class="num">Utilidad</th></tr></thead><tbody id="c-seller"></tbody></table></div>
    <div class="card"><h2>Productos más vendidos</h2><table><thead><tr><th>Producto</th><th>SKU</th><th class="num">Piezas</th><th class="num">Venta</th></tr></thead><tbody id="c-top"></tbody></table></div>`;
  $("#c-from").value = today(); $("#c-to").value = today();
  ["c-from", "c-to"].forEach((i) => $("#" + i).onchange = VIEWS.corte);
  $$("[data-r]", $("#view-corte")).forEach((b) => b.onclick = () => {
    const r = b.dataset.r, d = new Date(today() + "T12:00:00");
    const fmt = (x) => x.toISOString().slice(0, 10);
    let from = new Date(d), to = new Date(d);
    if (r === "1") { from.setDate(d.getDate() - 1); to = new Date(from); }
    else if (r === "m") from.setDate(1);
    else from.setDate(d.getDate() - (+r ? +r - 1 : 0));
    $("#c-from").value = fmt(from); $("#c-to").value = fmt(to); VIEWS.corte();
  });
  $("#c-add").onclick = async () => {
    try { await POST("/api/cash", { kind: $("#c-kind").value, amount: $("#c-amt").value, notes: $("#c-note").value }); $("#c-amt").value = ""; $("#c-note").value = ""; toast("Movimiento registrado", "ok"); VIEWS.corte(); } catch (e) { fail(e); }
  };
  $("#c-print").onclick = async () => {
    const q = `from=${$("#c-from").value}&to=${$("#c-to").value}${branchParam("#c-branch")}`;
    if (S.settings.ticket_printer_mode === "browser") return openTicketWindow(`/reports/corte?${q}&print=1`);
    try { const r = await POST(`/api/reports/corte/print?${q}`); toast(r.message, "ok"); } catch (e) { fail(e); }
  };
}
VIEWS.corte = async () => {
  if (!$("#c-branch").options.length) { $("#c-branch").innerHTML = branchOptions(S.me.can_switch_branch ? "all" : ""); $("#c-branch").onchange = VIEWS.corte; }
  $("#view-corte").classList.toggle("single-branch", !S.multi);
  $("#view-corte").classList.toggle("no-branch-pick", !(S.multi && S.me.can_switch_branch));
  const q = `from=${$("#c-from").value}&to=${$("#c-to").value}${branchParam("#c-branch")}`;
  try {
    const [r, cash] = await Promise.all([GET(`/api/reports/summary?${q}`), GET(`/api/cash?${q}`)]);
    const k = (label, v) => `<div class="kpi"><small>${label}</small><b>${v}</b></div>`;
    $("#c-kpis").innerHTML = k("Total vendido", money(r.total)) + k("Ventas", r.sales_count) + k("Ticket promedio", money(r.average_ticket)) +
      k("Piezas", r.units) + k("Utilidad bruta", money(r.profit)) + k("Efectivo esperado", money(r.expected_cash));
    const row = (a, b, strong) => `<tr><td>${a}</td><td class="num">${strong ? `<b>${b}</b>` : b}</td></tr>`;
    $("#c-pay").innerHTML = row("💵 Efectivo", money(r.cash)) + row("💳 Tarjeta", money(r.card)) + row("🏦 Transferencia", money(r.transfer)) +
      row("Total", money(r.total), 1) + row("Fondo / entradas de efectivo", money(r.cash_in)) + row("Retiros / gastos", (r.cash_out ? "-" : "") + money(r.cash_out)) +
      row("Efectivo que debe haber en caja", money(r.expected_cash), 1) + row("Descuentos otorgados", money(r.discounts)) +
      row(`IVA incluido`, money(r.tax)) + row("Ventas canceladas", r.cancelled_count);
    $("#c-cash").innerHTML = cash.map((c) => `<tr><td class="small">${esc(c.created_at.slice(11, 16))}</td><td><span class="badge ${c.kind === "entrada" ? "ok" : "warn"}">${c.kind}</span></td><td>${esc(c.notes)}</td><td class="num">${money(c.amount)}</td></tr>`).join("");
    $("#c-cat").innerHTML = r.by_category.map((c) => `<tr><td>${esc(c.category)}</td><td class="num">${c.units}</td><td class="num">${money(c.total)}</td><td class="num">${money(c.profit)}</td></tr>`).join("") || '<tr><td colspan="4" class="empty">Sin ventas</td></tr>';
    $("#c-branch-card").classList.toggle("hidden", r.by_branch.length < 2);
    $("#c-bybranch").innerHTML = r.by_branch.map((b) => `<tr><td>${esc(b.branch)}</td><td class="num">${b.n}</td><td class="num">${money(b.total)}</td><td class="num">${money(b.cash)}</td><td class="num">${money(b.profit)}</td></tr>`).join("");
    $("#c-seller").innerHTML = r.by_seller.map((v) => `<tr><td>${esc(v.seller)}</td><td class="num">${v.n}</td><td class="num">${money(v.total)}</td><td class="num">${money(v.profit)}</td></tr>`).join("") || '<tr><td colspan="4" class="empty">Sin ventas</td></tr>';
    $("#c-top").innerHTML = r.top_products.map((t) => `<tr><td>${esc(t.name)}</td><td class="mono small">${esc(t.sku || "")}</td><td class="num">${t.units}</td><td class="num">${money(t.total)}</td></tr>`).join("") || '<tr><td colspan="4" class="empty">Sin ventas</td></tr>';
  } catch (e) { fail(e); }
};

/* ================================================================== CONFIGURACIÓN */
function field(key, label, opts = {}) {
  const v = S.settings[key] ?? "";
  const cls = `f ${opts.span ? "span-" + opts.span : ""}`;
  if (opts.type === "check") return `<label class="chk ${opts.span ? "span-" + opts.span : ""}"><input type="checkbox" data-k="${key}" ${v === "1" ? "checked" : ""}> ${label}</label>`;
  if (opts.options) return `<label class="${cls}">${label}<select data-k="${key}">${Object.entries(opts.options).map(([k, t]) => `<option value="${k}" ${String(v) === k ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></label>`;
  if (opts.type === "area") return `<label class="${cls}">${label}<textarea data-k="${key}">${esc(v)}</textarea></label>`;
  return `<label class="${cls}">${label}<input data-k="${key}" value="${esc(v)}" ${opts.ph ? `placeholder="${esc(opts.ph)}"` : ""}></label>`;
}

function initConfig() { /* se dibuja al entrar */ }

const userBranchOptions = (sel) => `<option value="">Todas (Administración)</option>` +
  S.branches.map((b) => `<option value="${b.id}" ${String(b.id) === String(sel ?? "") ? "selected" : ""}>${esc(b.name)}</option>`).join("");

async function loadBranches() {
  const body = $("#br-body"); if (!body) return;
  let list;
  try { list = await GET("/api/branches"); } catch (e) { return fail(e); }
  const agentState = (b) => {
    if (!b.agent_last_seen) return '<span class="badge">Sin conectar</span>';
    const mins = (Date.now() - new Date(b.agent_last_seen.replace(" ", "T")).getTime()) / 60000;
    return mins < 1 ? '<span class="badge ok">Conectado</span>' : `<span class="badge warn">Última vez ${esc(b.agent_last_seen.slice(5, 16))}</span>`;
  };
  body.innerHTML = list.map((b) => `<tr data-id="${b.id}"><td><input data-b="name" value="${esc(b.name)}"></td>
      <td><input data-b="code" value="${esc(b.code)}" class="mono" style="width:70px"></td><td><input data-b="address" value="${esc(b.address || "")}"></td>
      <td><input data-b="phone" value="${esc(b.phone || "")}" style="width:130px"></td>
      <td class="center"><input type="checkbox" data-b="sells" ${b.sells ? "checked" : ""}>${b.sells ? "" : '<div class="small muted">Bodega</div>'}</td>
      <td class="center"><input type="checkbox" data-b="active" ${b.active ? "checked" : ""}></td>
      <td>${agentState(b)}${b.pending_jobs ? ` <span class="badge warn">${b.pending_jobs} en cola</span>` : ""}<div><a class="small" href="/api/branches/${b.id}/agente.json">⬇ Descargar agente.json</a></div></td>
      <td><button class="sm" data-a="save">Guardar</button></td></tr>`).join("") +
    `<tr><td><input id="nb-name" placeholder="Nueva sucursal"></td><td><input id="nb-code" class="mono" placeholder="Clave" style="width:70px"></td>
      <td><input id="nb-address" placeholder="Dirección (sale en el ticket)"></td><td><input id="nb-phone" placeholder="Teléfono" style="width:130px"></td><td class="center"><input type="checkbox" id="nb-sells" checked></td><td></td><td></td>
      <td><button class="sm primary" id="nb-add">Agregar</button></td></tr>`;
  body.onclick = async (e) => {
    const b = e.target.closest("button"); if (!b) return;
    try {
      if (b.id === "nb-add") {
        await POST("/api/branches", { name: $("#nb-name").value, code: $("#nb-code").value, address: $("#nb-address").value, phone: $("#nb-phone").value, sells: $("#nb-sells").checked ? 1 : 0 });
        toast("Sucursal agregada", "ok");
      } else {
        const tr = b.closest("tr"), v = (k) => tr.querySelector(`[data-b="${k}"]`);
        await PUT(`/api/branches/${tr.dataset.id}`, { name: v("name").value, code: v("code").value, address: v("address").value, phone: v("phone").value, sells: v("sells").checked ? 1 : 0, active: v("active").checked ? 1 : 0 });
        toast("Sucursal guardada", "ok");
      }
      await loadBase(); loadBranches(); loadUsers();
    } catch (er) { fail(er); }
  };
}

async function loadUsers() {
  let data;
  try { data = await GET("/api/users"); } catch (e) { return fail(e); }
  const roleSel = (r) => Object.entries(data.roles).map(([k, v]) => `<option value="${k}" ${k === r ? "selected" : ""}>${v}</option>`).join("");
  const body = $("#usr-body");
  body.innerHTML = data.users.map((u) => `<tr data-id="${u.id}"><td><input data-u="username" value="${esc(u.username)}" style="width:130px"></td>
      <td><input data-u="full_name" value="${esc(u.full_name)}"></td><td><select data-u="role">${roleSel(u.role)}</select></td>
      <td><select data-u="branch_id">${userBranchOptions(u.branch_id)}</select></td>
      <td><input data-u="password" type="password" placeholder="(sin cambio)" style="width:140px"></td>
      <td class="center"><input type="checkbox" data-u="active" ${u.active ? "checked" : ""}></td><td><button class="sm" data-a="save">Guardar</button></td></tr>`).join("") +
    `<tr><td><input id="nu-user" placeholder="usuario" style="width:130px"></td><td><input id="nu-name" placeholder="Nombre completo"></td>
      <td><select id="nu-role">${roleSel("vendedor")}</select></td><td><select id="nu-branch">${userBranchOptions(S.me.branch.id)}</select></td><td><input id="nu-pass" type="password" placeholder="contraseña" style="width:140px"></td><td></td>
      <td><button class="sm primary" id="nu-add">Agregar</button></td></tr>`;
  body.onclick = async (e) => {
    const b = e.target.closest("button"); if (!b) return;
    try {
      if (b.id === "nu-add") {
        await POST("/api/users", { username: $("#nu-user").value, full_name: $("#nu-name").value, role: $("#nu-role").value, password: $("#nu-pass").value, branch_id: $("#nu-branch").value });
        toast("Usuario creado", "ok");
      } else {
        const tr = b.closest("tr"), v = (k) => tr.querySelector(`[data-u="${k}"]`);
        await PUT(`/api/users/${tr.dataset.id}`, { username: v("username").value, full_name: v("full_name").value, role: v("role").value, password: v("password").value, branch_id: v("branch_id").value, active: v("active").checked ? 1 : 0 });
        toast("Usuario guardado", "ok");
      }
      S.sellers = await GET("/api/sellers"); fillSellers(); loadUsers();
    } catch (er) { fail(er); }
  };
}
VIEWS.config = async () => {
  await loadBase();
  const printers = await GET("/api/printers").then((r) => r.printers).catch(() => []);
  const tplOpts = Object.fromEntries(Object.entries(S.templates).map(([k, v]) => [k, v.name]));
  const el = $("#view-config");
  el.innerHTML = `
    <div class="view-head"><h1>Configuración</h1><a class="btn" href="/api/backup">💾 Descargar respaldo</a><button class="primary" id="cfg-save">Guardar cambios</button></div>
    <div class="tabs"><button data-t="tienda" class="on">Tienda</button><button data-t="tickets">Tickets</button><button data-t="zebra">Etiquetas Zebra</button><button data-t="precios">Precios e IVA</button><button data-t="cats">Categorías</button><button data-t="users">👤 Usuarios</button><button data-t="branches">🏬 Sucursales</button></div>
    <div data-p="tienda" class="card"><div class="form-grid">
      ${field("store_name", "Nombre comercial", { span: 2 })}${field("store_legal_name", "Razón social", { span: 2 })}
      ${field("store_rfc", "RFC")}${field("store_phone", "Teléfono")}${field("store_whatsapp", "WhatsApp")}
      ${field("store_address", "Dirección", { span: "all" })}</div>
      <fieldset><legend>Logo</legend><div class="row" style="align-items:flex-start;gap:16px">
        <div style="background:#fff;border:1px solid var(--line);border-radius:10px;padding:8px"><img id="cfg-logo" src="/logo.png?${Date.now()}" style="height:110px;display:block"></div>
        <div style="background:#fff;border:1px dashed var(--line);border-radius:10px;padding:8px" title="Así sale en la impresora térmica"><img src="/logo-ticket.png?${Date.now()}" style="height:110px;display:block"><div class="small muted center">En el ticket</div></div>
        <div class="grid" style="gap:8px;max-width:340px"><input type="file" id="logo-file" accept="image/*">
          <div class="row"><button class="sm primary" id="logo-up">Subir logo nuevo</button><button class="sm" id="logo-reset">Usar logo original</button></div>
          ${field("ticket_logo", "Imprimir el logo en tickets y corte de caja", { type: "check" })}</div></div></fieldset></div>
    <div data-p="tickets" class="card hidden"><p class="small muted" style="margin-top:0">Impresora de tickets de la sucursal <b>${esc(S.me.branch.name)}</b>${S.multi ? " (cada sucursal tiene la suya)" : ""}.</p><div class="form-grid">
      ${field("ticket_printer_mode", "Imprimir tickets en", { span: 2, options: { browser: "Navegador (cualquier impresora instalada)", network: "Impresora térmica en red (ESC/POS, puerto 9100)", local: "Impresora térmica USB instalada (ESC/POS crudo)", zebra: "Impresora Zebra (ZPL)", agent: "Agente de impresión de la sucursal (otra computadora)" } })}
      ${field("ticket_width", "Ancho de papel", { options: { 80: "80 mm (48 caracteres)", 58: "58 mm (32 caracteres)" } })}
      ${field("ticket_copies", "Copias")}
      ${field("ticket_printer_host", "IP impresora de tickets", { ph: "192.168.1.50" })}${field("ticket_printer_port", "Puerto")}
      <label class="f span-2">Nombre impresora USB (sistema)<input data-k="ticket_printer_name" list="dl-printers" value="${esc(S.settings.ticket_printer_name)}"></label>
      ${field("ticket_open_drawer", "Abrir cajón de dinero al imprimir", { type: "check", span: 2 })}
      ${field("ticket_zebra_width_mm", "Ancho del ticket en Zebra (mm)", { ph: "76" })}
      ${field("folio_prefix", "Prefijo de folio")}
      ${field("ticket_header", "Leyenda superior", { type: "area", span: 2 })}${field("ticket_footer", "Pie del ticket", { type: "area", span: 2 })}
      ${field("warranty_text", "Políticas de garantía (texto corto al final de la nota)", { type: "area", span: "all" })}
      ${field("warranty_policy", "Póliza de garantía completa (al final de la nota, con firma del cliente)", { type: "area", span: "all" })}
      ${field("warranty_policy_print", "Imprimir las políticas de garantía", { span: 2, options: { siempre: "En todas las notas", garantia: "Solo en notas con garantía", nunca: "Nunca" } })}
      ${field("ticket_change_boxes", "Imprimir recuadro “Control de cambios” con renglones de fecha y firma", { type: "check", span: "all" })}
      </div><div class="row" style="margin-top:12px"><button id="t-test">🖨 Ticket de prueba</button><span class="small muted">Guarda antes de probar.</span></div></div>
    <div data-p="zebra" class="card hidden"><p class="small muted" style="margin-top:0">Zebra de la sucursal <b>${esc(S.me.branch.name)}</b>${S.multi ? " (cada sucursal tiene la suya)" : ""}.</p><div class="form-grid">
      ${field("label_printer_mode", "Conexión de la Zebra", { span: 2, options: { download: "Descargar archivo .ZPL (enviar manualmente)", network: "Zebra en red (IP, puerto 9100)", local: "Zebra USB instalada en este equipo", agent: "Agente de impresión de la sucursal (otra computadora)" } })}
      ${field("label_printer_host", "IP de la Zebra", { ph: "192.168.1.60" })}${field("label_printer_port", "Puerto")}
      <label class="f span-2">Nombre de la Zebra USB<input data-k="label_printer_name" list="dl-printers" value="${esc(S.settings.label_printer_name)}" placeholder="ZDesigner GC420t"></label>
      ${field("label_dpi", "Resolución", { options: { 203: "203 dpi (8 puntos/mm) — GC420, ZD220, ZD410, GK420", 300: "300 dpi (12 puntos/mm) — ZD421-300, ZT230-300", 600: "600 dpi" } })}
      ${field("label_template", "Plantilla predeterminada", { options: tplOpts })}
      ${field("label_darkness", "Oscuridad (0–30)")}${field("label_speed", "Velocidad (pulg/seg)")}
      ${field("label_offset_x", "Desplazamiento X (mm)")}${field("label_offset_y", "Desplazamiento Y (mm)")}
      ${field("label_show_store", "Imprimir nombre de la tienda en la etiqueta", { type: "check", span: 2 })}
      </div><div class="row" style="margin-top:12px"><button id="z-test">🏷️ Etiqueta de prueba</button><span class="small muted">Para USB en Windows instala el driver ZDesigner y <span class="mono">pip install pywin32</span>.</span></div></div>
    <div data-p="precios" class="card hidden"><div class="form-grid">
      ${field("currency_symbol", "Símbolo de moneda")}${field("tax_rate", "IVA %")}
      ${field("prices_include_tax", "Los precios al público ya incluyen IVA", { type: "check", span: 2 })}
      ${field("show_tax_breakdown", "Desglosar IVA en el ticket", { type: "check", span: 2 })}
      ${field("allow_negative_stock", "Permitir vender sin existencia", { type: "check", span: 2 })}
      ${field("price_rounding", "Redondeo de precios", { span: 2, options: S.rounding })}
      ${field("default_markup", "% de ganancia predeterminado")}${field("barcode_prefix", "Prefijo de códigos internos (EAN-13)")}
      </div></div>
    <div data-p="cats" class="card hidden">
      <p class="small muted" style="margin-top:0">El <b>prefijo</b> forma el SKU (p. ej. FUN-SAM-0001). El <b>% de ganancia</b> se usa en el generador de precios.</p>
      <table><thead><tr><th>Categoría</th><th>Prefijo SKU</th><th>Maneja IMEI</th><th>Pide equipo cliente</th><th>% ganancia</th><th class="num">Productos</th><th></th></tr></thead><tbody id="cat-body">
      ${S.categories.map((c) => `<tr data-id="${c.id}"><td><input data-c="name" value="${esc(c.name)}"></td><td><input data-c="prefix" value="${esc(c.prefix)}" class="mono" style="width:90px"></td>
        <td class="center"><input type="checkbox" data-c="serialized" ${c.serialized ? "checked" : ""}></td><td class="center"><input type="checkbox" data-c="ask_device" ${c.ask_device ? "checked" : ""}></td><td><input data-c="markup" value="${c.markup}" style="width:90px"></td><td class="num">${c.products}</td>
        <td><button class="sm" data-a="save">Guardar</button> <button class="sm danger" data-a="del">✕</button></td></tr>`).join("")}
      <tr><td><input id="nc-name" placeholder="Nueva categoría"></td><td><input id="nc-prefix" class="mono" placeholder="ABC" style="width:90px"></td><td class="center"><input type="checkbox" id="nc-ser"></td><td class="center"><input type="checkbox" id="nc-dev"></td><td><input id="nc-markup" value="100" style="width:90px"></td><td></td><td><button class="sm primary" id="nc-add">Agregar</button></td></tr>
      </tbody></table></div>
    <div data-p="branches" class="card hidden">
      <p class="small muted" style="margin-top:0">Todas las sucursales comparten productos y precios; cada una tiene su existencia, sus IMEI, sus folios (<span class="mono">CLAVE-000123</span>), su caja y sus impresoras.
      En la computadora de cada sucursal corre el <b>agente de impresión</b> (<span class="mono">iniciar_agente.bat</span>) con su <span class="mono">agente.json</span>.</p>
      <table><thead><tr><th>Sucursal</th><th>Clave folio</th><th>Dirección</th><th>Teléfono</th><th>Vende al público</th><th>Activa</th><th>Agente de impresión</th><th></th></tr></thead><tbody id="br-body"></tbody></table></div>
    <div data-p="users" class="card hidden">
      <p class="small muted" style="margin-top:0"><b>Administración</b>: todo, en todas las sucursales. <b>Matriz (supervisor)</b>: revisa todas las sucursales, da de alta productos y sube inventario a cualquiera (entradas, IMEI, traspasos, etiquetas) y ve sus ventas y cortes; no configura ni cancela ventas. <b>Cajero</b>: cobra las notas de los vendedores, hace notas, registra cambios por garantía, etiquetas, inventario, corte de caja. <b>Vendedor</b>: arma la venta y la envía a caja, consulta garantías (no ve costos, no cambia precios, no cancela ventas).</p>
      <fieldset style="margin:0 0 14px"><legend>🔑 Clave de cancelación</legend>
        <p class="small muted" style="margin-top:0">Los cajeros pueden cancelar notas de su sucursal escribiendo esta clave (Administración cancela sin clave). Estado: <b id="cx-state">${S.settings.cancel_password_set === "1" ? "definida" : "sin definir"}</b></p>
        <div class="row"><input id="cx-new" type="password" placeholder="Nueva clave" style="max-width:200px" autocomplete="new-password"><button class="sm primary" id="cx-save">Guardar clave</button></div></fieldset>
      <div style="margin-bottom:12px">${field("seller_can_charge", "Permitir que los vendedores también cobren (si no, solo envían la nota a caja)", { type: "check" })}</div>
      <table><thead><tr><th>Usuario</th><th>Nombre (sale en el ticket)</th><th>Rol</th><th>Sucursal</th><th>Nueva contraseña</th><th>Activo</th><th></th></tr></thead><tbody id="usr-body"></tbody></table></div>
    <datalist id="dl-printers">${printers.map((p) => `<option value="${esc(p)}">`).join("")}</datalist>`;
  loadUsers();
  loadBranches();
  $("#cx-save").onclick = async () => {
    try { await PUT("/api/cancel-password", { password: $("#cx-new").value }); $("#cx-new").value = ""; $("#cx-state").textContent = "definida"; toast("Clave de cancelación guardada", "ok"); } catch (e) { fail(e); }
  };
  $("#logo-up").onclick = async () => {
    const f = $("#logo-file").files[0]; if (!f) return toast("Selecciona una imagen", "bad");
    const fd = new FormData(); fd.append("file", f);
    try { await api("POST", "/api/logo", fd); toast("Logo actualizado", "ok"); VIEWS.config(); $("#brand-logo").src = "/logo.png?" + Date.now(); } catch (e) { fail(e); }
  };
  $("#logo-reset").onclick = async () => { try { await DEL("/api/logo"); VIEWS.config(); $("#brand-logo").src = "/logo.png?" + Date.now(); } catch (e) { fail(e); } };
  $$(".tabs button", el).forEach((b) => b.onclick = () => {
    $$(".tabs button", el).forEach((x) => x.classList.toggle("on", x === b));
    $$("[data-p]", el).forEach((p) => p.classList.toggle("hidden", p.dataset.p !== b.dataset.t));
  });
  const save = async (quiet) => {
    const data = {};
    $$("[data-k]", el).forEach((i) => { data[i.dataset.k] = i.type === "checkbox" ? (i.checked ? "1" : "0") : i.value; });
    try { await PUT("/api/settings", data); await loadBase(); if (!quiet) toast("Configuración guardada", "ok"); } catch (e) { fail(e); }
  };
  $("#cfg-save").onclick = () => save(false);
  $("#t-test").onclick = async () => {
    await save(true);
    if (S.settings.ticket_printer_mode === "browser") { const w = window.open("", "ticket", "width=420,height=600"); if (w) { w.document.write("<p style='font-family:monospace'>Prueba de impresión del navegador.<br>Si ves esto, imprime con Ctrl+P.</p>"); w.print(); } return; }
    try { const r = await POST("/api/print/test", { target: "ticket" }); toast(r.message || "Enviado", "ok"); } catch (e) { fail(e); }
  };
  $("#z-test").onclick = async () => {
    await save(true);
    try { const r = await POST("/api/print/test", { target: "label" }); if (r.zpl) download("prueba.zpl", r.zpl); toast(r.message, "ok"); } catch (e) { fail(e); }
  };
  $("#cat-body").addEventListener("click", async (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.id === "nc-add") {
      try { await POST("/api/categories", { name: $("#nc-name").value, prefix: $("#nc-prefix").value, serialized: $("#nc-ser").checked, ask_device: $("#nc-dev").checked, markup: $("#nc-markup").value }); toast("Categoría agregada", "ok"); VIEWS.config().then(() => $('[data-t="cats"]').click()); } catch (er) { fail(er); }
      return;
    }
    const tr = b.closest("tr"), id = tr.dataset.id;
    const v = (k) => tr.querySelector(`[data-c="${k}"]`);
    try {
      if (b.dataset.a === "save") { await PUT(`/api/categories/${id}`, { name: v("name").value, prefix: v("prefix").value, serialized: v("serialized").checked, ask_device: v("ask_device").checked, markup: v("markup").value }); toast("Categoría guardada", "ok"); await loadBase(); }
      if (b.dataset.a === "del" && await confirmBox("¿Eliminar la categoría?", "Eliminar", true)) { await DEL(`/api/categories/${id}`); VIEWS.config().then(() => $('[data-t="cats"]').click()); }
    } catch (er) { fail(er); }
  });
};

function changePassword(forced) {
  modal({
    title: forced ? "Crea tu contraseña" : "Cambiar contraseña", size: "narrow",
    body: `${forced ? '<p class="small">Por seguridad cambia la contraseña inicial antes de continuar.</p>' : ""}
      <div class="grid" style="gap:10px"><label class="f">Contraseña actual<input type="password" id="cp-cur" autofocus></label>
      <label class="f">Contraseña nueva<input type="password" id="cp-new"></label><label class="f">Repite la nueva<input type="password" id="cp-new2"></label></div>`,
    foot: `${forced ? "" : "<button data-close>Cancelar</button>"}<button class="primary" id="cp-ok">Guardar</button>`,
    onOpen: (m, close) => {
      if (forced) { m.querySelector(".close-x").remove(); m.closest(".modal-back").addEventListener("mousedown", (e) => e.stopImmediatePropagation(), true); m.close = () => {}; }
      $("#cp-ok", m).onclick = async () => {
        if ($("#cp-new", m).value !== $("#cp-new2", m).value) return toast("Las contraseñas no coinciden", "bad");
        try { await POST("/api/me/password", { current: $("#cp-cur", m).value, new: $("#cp-new", m).value }); toast("Contraseña actualizada", "ok"); m.closest(".modal-back").remove(); focusScan(); } catch (e) { fail(e); }
      };
    },
  });
}

/* ------------------------------------------------------------------ inicio */
function tick() { $("#clock").textContent = new Date().toLocaleString("es-MX", { weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }); }

(async function start() {
  try { await loadBase(); } catch (e) { fail(e); }
  initVender(); initProductos(); initGarantias(); initEtiquetas(); initInventario(); initVentas(); initCorte(); initConfig();
  tick(); setInterval(tick, 20000);
  go(can("matriz") ? "inventario" : "vender");  // la Matriz es bodega: entra directo a Inventario
  if (S.me?.must_change) changePassword(true);
})();
