/* BoreHole Records — vanilla JS frontend (same-origin FastAPI backend, no frameworks, no external assets). */
"use strict";

const API = {
  list: "/boreHoleRecords",
  counts: "/boreHoleRecords/counts",
  updateStatus: "/boreHoleRecords/updateStatus",
  fetchData: "/fetchData",
  detail: (recordId) => `/boreHoleRecords/${encodeURIComponent(recordId)}`,
};
const SEARCH_DEBOUNCE_MS = 250;
const STATUS_CLEAR_MS = 6000;
const COLUMN_COUNT = 9;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const byTestId = (id) => document.querySelector(`[data-testid="${id}"]`);
const ui = {
  badges: {
    totalCount: byTestId("badge-total"),
    filteredCount: byTestId("badge-filtered"),
    verifiedCount: byTestId("badge-verified"),
    reviewCount: byTestId("badge-review"),
    averageDepth: byTestId("badge-avg-depth"),
  },
  selectState: byTestId("select-state"),
  selectDepth: byTestId("select-depth"),
  inputSearch: byTestId("input-search"),
  btnReload: byTestId("btn-reload"),
  table: byTestId("table-records"),
  rows: byTestId("rows"),
  detail: byTestId("detail-panel"),
  btnToggle: byTestId("btn-toggle-state"),
  btnClose: byTestId("btn-close-detail"),
  status: byTestId("status-message"),
};

let currentRecord = null; // record currently shown in the detail panel
let searchTimer = null;
let statusTimer = null;

// --- API helper: every request goes through here ---------------------------

/** Fetch JSON from the backend. Throws an Error carrying the server's `detail` on non-2xx. */
async function api(path, options = {}) {
  const init = { ...options, headers: { Accept: "application/json", ...(options.headers || {}) } };
  if (init.body !== undefined && typeof init.body !== "string") {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(init.body);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch (error) {
    throw new Error(`Network error while calling ${path}: ${error.message}`);
  }
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(describeError(payload, response));
  return payload;
}

function describeError(payload, response) {
  const detail = payload && payload.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{loc: ["body", "state"], msg: "..."}]
    return detail.map((item) => `${(item.loc || []).slice(1).join(".") || "request"}: ${item.msg}`).join("; ");
  }
  return `HTTP ${response.status} ${response.statusText}`.trim();
}

// --- Formatting -------------------------------------------------------------

/** "2025-07-18" -> "18 Jul 2025" (no Date parsing, so no timezone drift). */
function formatDate(isoDate) {
  const [year, month, day] = String(isoDate).split("-").map(Number);
  if (!year || !month || !day) return String(isoDate);
  return `${day} ${MONTHS[month - 1]} ${year}`;
}

/** "2025-07-18T00:00:00Z" -> "18 Jul 2025, 00:00:00 UTC". */
function formatDateTime(isoDateTime) {
  const date = new Date(isoDateTime);
  if (Number.isNaN(date.getTime())) return String(isoDateTime);
  const pad = (n) => String(n).padStart(2, "0");
  const day = `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}`;
  return `${day}, ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())} UTC`;
}

const formatDepth = (depth) => `${Number(depth).toFixed(2)} m`;

// --- DOM helpers: built with DOM APIs, never innerHTML with data ------------

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (name === "dataset") Object.assign(node.dataset, value);
    else if (name === "className") node.className = value;
    else node.setAttribute(name, value);
  }
  for (const child of [].concat(children)) node.append(child); // strings become text nodes
  return node;
}

function statePill(record) {
  return el("span", { className: `pill ${record.state ? "pill-verified" : "pill-review"}` }, record.stateLabel);
}

function setStatus(message, kind = "info") {
  clearTimeout(statusTimer);
  ui.status.textContent = message;
  ui.status.dataset.kind = kind;
  if (kind === "error") return; // errors stay until the next message
  statusTimer = setTimeout(() => setStatus(""), STATUS_CLEAR_MS);
}

/** Query string for the current state / depth / search controls (shared by list + counts). */
function currentQuery() {
  const params = new URLSearchParams();
  if (ui.selectState.value !== "all") params.set("state", ui.selectState.value);
  if (ui.selectDepth.value) params.set("depth", ui.selectDepth.value);
  const q = ui.inputSearch.value.trim();
  if (q) params.set("q", q);
  const query = params.toString();
  return query ? `?${query}` : "";
}

// --- Rendering --------------------------------------------------------------

function renderBadges(counts) {
  for (const [key, node] of Object.entries(ui.badges)) {
    node.textContent = key === "averageDepth" ? Number(counts[key]).toFixed(2) : String(counts[key]);
  }
}

function renderRows(records) {
  ui.rows.replaceChildren();
  if (records.length === 0) {
    ui.rows.append(el("tr", { className: "empty-row" }, el("td", { colspan: COLUMN_COUNT }, "No records match.")));
    return;
  }
  for (const record of records) {
    ui.rows.append(
      el("tr", { dataset: { recordId: record.recordId }, tabindex: "0" }, [
        el("td", { className: "mono" }, record.recordId),
        el("td", {}, formatDate(record.dateCreated)),
        el("td", {}, record.machine),
        el("td", {}, record.operator),
        el("td", {}, record.position),
        el("td", { className: "num" }, formatDepth(record.depth)),
        el("td", {}, record.plumb),
        el("td", {}, statePill(record)),
        el("td", {}, el("button", { type: "button", className: "btn btn-small", dataset: { action: "open" } }, "Open")),
      ]),
    );
  }
}

function renderDetail(record) {
  currentRecord = record;
  const values = {
    recordId: record.recordId,
    machine: record.machine,
    operator: record.operator,
    position: record.position,
    depth: formatDepth(record.depth),
    plumb: record.plumb,
    dateCreated: formatDate(record.dateCreated),
    lastUpdated: formatDateTime(record.lastUpdated),
  };
  for (const [field, value] of Object.entries(values)) {
    for (const node of ui.detail.querySelectorAll(`[data-field="${field}"]`)) node.textContent = value;
  }
  ui.detail.querySelector('[data-field="state"]').replaceChildren(statePill(record));
  ui.btnToggle.textContent = record.state ? "Mark as Review" : "Mark as Verified";
}

// --- Actions ----------------------------------------------------------------

/** Reload table + badges for the current controls. Resolves to true on success. */
async function refresh() {
  const query = currentQuery();
  ui.table.setAttribute("aria-busy", "true");
  try {
    const [records, counts] = await Promise.all([api(API.list + query), api(API.counts + query)]);
    renderRows(records);
    renderBadges(counts);
    return true;
  } catch (error) {
    setStatus(`Could not load records: ${error.message}`, "error");
    return false;
  } finally {
    ui.table.setAttribute("aria-busy", "false");
  }
}

async function openDetail(recordId) {
  try {
    renderDetail(await api(API.detail(recordId)));
    if (!ui.detail.open) ui.detail.showModal();
  } catch (error) {
    setStatus(`Could not open ${recordId}: ${error.message}`, "error");
  }
}

async function toggleState() {
  if (!currentRecord) return;
  const { recordId, state } = currentRecord;
  ui.btnToggle.disabled = true;
  try {
    const updated = await api(API.updateStatus, { method: "PUT", body: { recordId, state: !state } });
    renderDetail(updated);
    if (await refresh()) setStatus(`${updated.recordId} marked as ${updated.stateLabel}.`, "success");
  } catch (error) {
    setStatus(`Could not update ${recordId}: ${error.message}`, "error");
  } finally {
    ui.btnToggle.disabled = false;
  }
}

async function reloadFromCsv() {
  ui.btnReload.disabled = true;
  try {
    const result = await api(API.fetchData, { method: "POST" });
    const refreshed = await refresh();
    if (currentRecord && ui.detail.open) await openDetail(currentRecord.recordId);
    if (refreshed) setStatus(`Reloaded ${result.count} record(s) from CSV; in-memory status changes were discarded.`, "success");
  } catch (error) {
    setStatus(`Reload failed: ${error.message}`, "error");
  } finally {
    ui.btnReload.disabled = false;
  }
}

// --- Wiring: every listener attached exactly once; rows use delegation ------

function bindEvents() {
  ui.selectState.addEventListener("change", refresh);
  ui.selectDepth.addEventListener("change", refresh);
  ui.inputSearch.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(refresh, SEARCH_DEBOUNCE_MS);
  });
  ui.btnReload.addEventListener("click", reloadFromCsv);

  // A click on the "Open" button or anywhere on the row opens the detail panel.
  ui.rows.addEventListener("click", (event) => {
    const row = event.target.closest("tr[data-record-id]");
    if (row) openDetail(row.dataset.recordId);
  });
  ui.rows.addEventListener("keydown", (event) => {
    const row = event.target.closest("tr[data-record-id]");
    if (!row || event.target !== row || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    openDetail(row.dataset.recordId);
  });

  ui.btnToggle.addEventListener("click", toggleState);
  ui.btnClose.addEventListener("click", () => ui.detail.close());
  // Escape closes a modal <dialog> natively (its "cancel" event); just forget the record afterwards.
  ui.detail.addEventListener("close", () => {
    currentRecord = null;
  });
}

bindEvents();
refresh();
