const state = {
  filters: {
    officeId: "",
    status: "",
    insurer: "",
    insuranceType: "",
    expirationMonth: "",
  },
  masterOptions: null,
  dashboard: null,
  activeView: "expiring",
  activeListing: null,
  tableSearch: "",
  activeModule: "portfolio",
  scanner: {
    summary: null,
    currentScan: null,
    search: "",
  },
};

const viewConfig = {
  expiring: {
    title: "Pólizas que vencen el próximo mes",
    endpoint: "/api/listings/expiring-next-month",
  },
  former: {
    title: "Clientes que fueron clientes y ahora no lo son",
    endpoint: "/api/listings/former-clients",
  },
  crossSell: {
    title: "Ventas cruzadas",
    endpoint: "/api/listings/cross-sell",
  },
  insurers: {
    title: "Reporte por aseguradora",
    endpoint: "/api/listings/insurers",
  },
};

const suggestions = [
  "cuántos clientes activos hay",
  "reporte por aseguradora",
  "qué pólizas vencen en mayo",
  "cuántos autos activos hay en oficina 2",
  "dame los ex clientes con seguro de hogar",
];

const moneyFormatter = new Intl.NumberFormat("es-ES", {
  style: "currency",
  currency: "EUR",
  maximumFractionDigits: 2,
});

const numberFormatter = new Intl.NumberFormat("es-ES");
const dateFormatter = new Intl.DateTimeFormat("es-ES", {
  year: "numeric",
  month: "short",
  day: "2-digit",
});
const API_BASE = window.location.protocol === "file:" ? "http://127.0.0.1:8765" : "";
const staticApiRoutes = new Map([
  ["/api/dashboard", "static-api/dashboard.json"],
  ["/api/listings/expiring-next-month", "static-api/listings/expiring-next-month.json"],
  ["/api/listings/former-clients", "static-api/listings/former-clients.json"],
  ["/api/listings/cross-sell", "static-api/listings/cross-sell.json"],
  ["/api/listings/insurers", "static-api/listings/insurers.json"],
  ["/api/scanner/summary", "static-api/scanner/summary.json"],
]);

const kpiBand = document.getElementById("kpiBand");
const actionsRow = document.getElementById("actionsRow");
const officeSelect = document.getElementById("officeSelect");
const statusSelect = document.getElementById("statusSelect");
const insurerSelect = document.getElementById("insurerSelect");
const typeSelect = document.getElementById("typeSelect");
const expirationMonth = document.getElementById("expirationMonth");
const activeFilters = document.getElementById("activeFilters");
const portfolioInsights = document.getElementById("portfolioInsights");
const portfolioCharts = document.getElementById("portfolioCharts");
const resultsTitle = document.getElementById("resultsTitle");
const tableMeta = document.getElementById("tableMeta");
const resultsTable = document.getElementById("resultsTable");
const generatedAt = document.getElementById("generatedAt");
const sourceLabel = document.getElementById("sourceLabel");
const appTitle = document.getElementById("appTitle");
const appLede = document.getElementById("appLede");
const tableSearch = document.getElementById("tableSearch");
const chatMessages = document.getElementById("chatMessages");
const chatForm = document.getElementById("chatForm");
const chatInput = document.getElementById("chatInput");
const chatSuggestions = document.getElementById("chatSuggestions");
const resetFilters = document.getElementById("resetFilters");
const moduleTabs = document.querySelectorAll(".module-tab");
const modulePanels = document.querySelectorAll("[data-module-panel]");
const scannerForm = document.getElementById("scannerForm");
const driveUrl = document.getElementById("driveUrl");
const insurerName = document.getElementById("insurerName");
const templateSelect = document.getElementById("templateSelect");
const policyPattern = document.getElementById("policyPattern");
const holderPattern = document.getElementById("holderPattern");
const premiumPattern = document.getElementById("premiumPattern");
const datePattern = document.getElementById("datePattern");
const saveTemplate = document.getElementById("saveTemplate");
const commitScan = document.getElementById("commitScan");
const openSheetLink = document.getElementById("openSheetLink");
const sheetSyncStatus = document.getElementById("sheetSyncStatus");
const scannerStatus = document.getElementById("scannerStatus");
const scannerKpis = document.getElementById("scannerKpis");
const scanMeta = document.getElementById("scanMeta");
const scanError = document.getElementById("scanError");
const scanTable = document.getElementById("scanTable");
const scanSearch = document.getElementById("scanSearch");
const textPreview = document.getElementById("textPreview");
const historyTable = document.getElementById("historyTable");

const defaultPatterns = {
  policy: "(?:pol(?:i|í)za|n[úu]mero\\s+de\\s+p[óo]liza|certificado)\\s*[:#-]?\\s*([A-Z0-9][A-Z0-9./-]{4,})",
  holder: "(?:tomador|cliente|asegurado|contratante)\\s*[:#-]?\\s*([^\\n\\r]{3,90})",
  netPremium: "(?:prima\\s+neta|prima|neto)\\s*[:#-]?\\s*(?:EUR|€)?\\s*([0-9.,]+)",
  liquidationDate: "(?:fecha\\s+(?:de\\s+)?liquidaci(?:o|ó)n|liquidaci(?:o|ó)n\\s+fecha|fecha)\\s*[:#-]?\\s*(\\d{1,2}[/-]\\d{1,2}[/-]\\d{2,4})",
};

function serializeFilters() {
  const params = new URLSearchParams();
  if (state.filters.officeId) params.set("officeIds", state.filters.officeId);
  if (state.filters.status) params.set("statuses", state.filters.status);
  if (state.filters.insurer) params.set("insurers", state.filters.insurer);
  if (state.filters.insuranceType) params.set("insuranceTypes", state.filters.insuranceType);
  if (state.filters.expirationMonth) params.set("expirationMonth", state.filters.expirationMonth);
  return params.toString();
}

async function fetchJSON(path) {
  const route = path.split("?")[0];
  const candidates = [`${API_BASE}${path}`];
  const staticRoute = staticApiRoutes.get(route);
  if (staticRoute) candidates.push(staticRoute);

  let lastError = null;
  for (const candidate of candidates) {
    try {
      const response = await fetch(candidate);
      if (response.ok) return response.json();
      lastError = new Error(`Error ${response.status}`);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError ?? new Error("No se pudo cargar la información.");
}

async function postJSON(path, payload) {
  if (window.location.hostname.endsWith("github.io")) {
    throw new Error("Esta acción requiere el servidor Python local o un backend publicado.");
  }
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Error ${response.status}`);
  }
  return data;
}

function formatMaybeDate(value) {
  if (!value) return "—";
  return dateFormatter.format(new Date(`${value}T00:00:00`));
}

function formatCell(value, key) {
  if (value === null || value === undefined || value === "") return "—";
  if (key.toLowerCase().includes("date") || key.toLowerCase().includes("expiration")) return formatMaybeDate(value);
  if (key.toLowerCase().includes("premium") || key.toLowerCase().includes("prima")) return moneyFormatter.format(Number(value) || 0);
  if (["policies", "activePolicies"].includes(key)) return numberFormatter.format(Number(value) || 0);
  return value;
}

function renderKPIs(metrics) {
  const items = [
    ["Clientes activos", numberFormatter.format(metrics.activeClients), "Con al menos una póliza en vigor"],
    ["Clientes no activos", numberFormatter.format(metrics.inactiveClients), "Sin pólizas en vigor"],
    ["Pólizas", numberFormatter.format(metrics.totalPolicies), "Total del segmento actual"],
    ["Aseguradoras", numberFormatter.format(metrics.insurers), "Compañías en la cartera filtrada"],
    ["Una sola póliza activa", numberFormatter.format(metrics.singleActivePolicyClients), "Base para ventas cruzadas"],
    ["Primas", moneyFormatter.format(metrics.totalPremium), "Suma de prima neta normalizada"],
    ["Pólizas activas", numberFormatter.format(metrics.activePolicies), "Visibilidad operativa inmediata"],
  ];

  kpiBand.innerHTML = items
    .map(
      ([label, value, note]) => `
        <article class="kpi-tile">
          <div class="kpi-label">${label}</div>
          <div class="kpi-value">${value}</div>
          <div class="kpi-note">${note}</div>
        </article>
      `,
    )
    .join("");
}

function renderActionCards(highlights) {
  const cards = [
    ["expiring", "Pólizas que vencen el próximo mes", highlights.expiringNextMonth],
    ["insurers", "Reporte por aseguradora", highlights.insurerReport],
    ["former", "Ex clientes", highlights.formerClients],
    ["crossSell", "Ventas cruzadas", highlights.crossSell],
  ];

  actionsRow.innerHTML = cards
    .map(
      ([id, label, count]) => `
        <button class="action-card ${state.activeView === id ? "active" : ""}" data-view="${id}">
          <strong>${label}</strong>
          <span class="action-count">${numberFormatter.format(count)}</span>
          <span class="muted">Actualizado con los filtros globales</span>
        </button>
      `,
    )
    .join("");

  actionsRow.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeView = button.dataset.view;
      loadWorkspace();
    });
  });
}

function optionHTML(value, label, selectedValue = "") {
  return `<option value="${value}" ${value === selectedValue ? "selected" : ""}>${label}</option>`;
}

function renderFilterDropdowns() {
  const offices = state.masterOptions?.offices ?? [];
  officeSelect.innerHTML = [
    optionHTML("", "Todas las oficinas", state.filters.officeId),
    ...offices.map((office) => optionHTML(office.id, office.label, state.filters.officeId)),
  ].join("");

  const statuses = state.masterOptions?.statuses ?? [];
  statusSelect.innerHTML = [
    optionHTML("", "Todos los estados", state.filters.status),
    ...statuses.map((status) => optionHTML(status, status, state.filters.status)),
  ].join("");

  const insurers = state.masterOptions?.insurers ?? [];
  insurerSelect.innerHTML = [
    optionHTML("", "Todas las aseguradoras", state.filters.insurer),
    ...insurers.map((insurer) => optionHTML(insurer, insurer, state.filters.insurer)),
  ].join("");

  const types = state.masterOptions?.insuranceTypes ?? [];
  typeSelect.innerHTML = [
    optionHTML("", "Todos los ramos", state.filters.insuranceType),
    ...types.map((type) => optionHTML(type, type, state.filters.insuranceType)),
  ].join("");
}

function renderActiveFilters() {
  const chips = [];
  const officeMap = new Map((state.masterOptions?.offices ?? []).map((office) => [office.id, office.label]));
  if (state.filters.officeId) chips.push(officeMap.get(state.filters.officeId) ?? `Oficina ${state.filters.officeId}`);
  if (state.filters.status) chips.push(state.filters.status);
  if (state.filters.insurer) chips.push(state.filters.insurer);
  if (state.filters.insuranceType) chips.push(state.filters.insuranceType);
  if (state.filters.expirationMonth) chips.push(`Vence ${state.filters.expirationMonth}`);

  activeFilters.innerHTML = chips.length
    ? chips.map((item) => `<span class="filter-pill">${item}</span>`).join("")
    : `<span class="muted">Sin filtros activos</span>`;
}

function renderCharts(charts) {
  const monthlyPremiums = charts?.monthlyPremiums ?? [];
  const bars = charts?.insurerBars ?? [];
  const distribution = charts?.distribution ?? [];
  const localities = charts?.localities ?? [];
  const localityRows = charts?.localityRows ?? localities;
  const maxClients = Math.max(...bars.map((row) => row.clients), 1);
  const maxPremium = Math.max(...bars.map((row) => row.premium), 1);
  const clientStops = conicStops(distribution, "clientsPercent");
  const premiumStops = conicStops(distribution, "premiumPercent");
  const maxLocalityPolicies = Math.max(...localityRows.map((row) => row.policies), 1);
  const maxMonthlyPremium = Math.max(...monthlyPremiums.map((row) => row.premium), 1);
  const maxMonthlyPolicies = Math.max(...monthlyPremiums.map((row) => row.policies), 1);

  portfolioCharts.innerHTML = `
    <article class="chart-panel chart-wide">
      <div class="chart-head"><span>Primas netas por vencimiento</span><strong>Meses del año actual</strong></div>
      <div class="month-bars">
        ${monthlyPremiums
          .map(
            (row, index) => `
              <div class="month-bar-item">
                <span class="month-bar-value">${moneyFormatter.format(row.premium)}</span>
                <div class="month-bar-rail">
                  <i style="height:${Math.max((row.premium / maxMonthlyPremium) * 100, 2)}%;--c:${chartColor(index)}"></i>
                </div>
                <strong>${row.label}</strong>
              </div>
            `,
          )
          .join("")}
      </div>
    </article>
    <article class="chart-panel chart-wide">
      <div class="chart-head"><span>Número de pólizas por vencimiento</span><strong>Meses del año actual</strong></div>
      <div class="month-bars policy-bars">
        ${monthlyPremiums
          .map(
            (row, index) => `
              <div class="month-bar-item">
                <span class="month-bar-value">${numberFormatter.format(row.policies)}</span>
                <div class="month-bar-rail">
                  <i style="height:${Math.max((row.policies / maxMonthlyPolicies) * 100, 2)}%;--c:${chartColor(index + 2)}"></i>
                </div>
                <strong>${row.label}</strong>
              </div>
            `,
          )
          .join("")}
      </div>
    </article>
    <article class="chart-panel chart-wide">
      <div class="chart-head"><span>3D clientes y primas</span><strong>Por aseguradora</strong></div>
      <div class="bar3d-wrap">
        ${bars
          .map(
            (row, index) => `
              <div class="bar3d-row">
                <span>${row.name}</span>
                <div class="bar3d-track">
                  <i class="bar3d clients" style="width:${Math.max((row.clients / maxClients) * 100, 4)}%;--c:${chartColor(index)}"></i>
                  <i class="bar3d premium" style="width:${Math.max((row.premium / maxPremium) * 100, 4)}%;--c:${chartColor(index + 3)}"></i>
                </div>
                <em>${numberFormatter.format(row.clients)} · ${moneyFormatter.format(row.premium)}</em>
              </div>
            `,
          )
          .join("")}
      </div>
    </article>
    <article class="chart-panel">
      <div class="chart-head"><span>Pie 3D</span><strong>Clientes %</strong></div>
      <div class="pie3d" style="background: conic-gradient(${clientStops || "#d8dee8 0 100%"});"></div>
      <div class="chart-legend">${distribution.map((row, index) => `<span><i style="background:${chartColor(index)}"></i>${row.name}: ${row.clientsPercent}%</span>`).join("")}</div>
    </article>
    <article class="chart-panel">
      <div class="chart-head"><span>Pie 3D</span><strong>Prima %</strong></div>
      <div class="pie3d" style="background: conic-gradient(${premiumStops || "#d8dee8 0 100%"});"></div>
      <div class="chart-legend">${distribution.map((row, index) => `<span><i style="background:${chartColor(index)}"></i>${row.name}: ${row.premiumPercent}%</span>`).join("")}</div>
    </article>
    <article class="chart-panel chart-wide">
      <div class="chart-head"><span>Mapa de calor por localidad</span><strong>Número de pólizas por Cliente.Direccion.Localidad</strong></div>
      <div class="cp-map-layout">
        <div id="localityHeatMap" class="mapbox-map"></div>
        <div class="cp-table table-shell">
          <table>
            <thead>
              <tr><th>Localidad</th><th>Pólizas</th><th>Clientes</th><th>Prima neta</th><th>% clientes</th><th>% prima</th></tr>
            </thead>
            <tbody>
              ${localityRows
                .slice(0, 16)
                .map(
                  (row) => `
                    <tr>
                      <td>${row.locality}</td>
                      <td>${numberFormatter.format(row.policies)}</td>
                      <td>${numberFormatter.format(row.clients)}</td>
                      <td>${moneyFormatter.format(row.premium)}</td>
                      <td>${row.clientsPercent}%</td>
                      <td>${row.premiumPercent}%</td>
                    </tr>
                  `,
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </div>
    </article>
  `;
  renderLocalityHeatMap(localityRows);
}

function chartColor(index) {
  return ["#007aff", "#34c759", "#ff9f0a", "#af52de", "#ff375f", "#64d2ff", "#30d158", "#bf5af2"][index % 8];
}

function conicStops(rows, key) {
  let start = 0;
  const stops = rows.map((row, index) => {
    const end = Math.min(start + Number(row[key] || 0), 100);
    const stop = `${chartColor(index)} ${start}% ${end}%`;
    start = end;
    return stop;
  });
  if (start < 100) stops.push(`#d8dee8 ${start}% 100%`);
  return stops.join(", ");
}

function heatLevel(value, maxValue) {
  const ratio = maxValue ? value / maxValue : 0;
  if (ratio > 0.72) return 5;
  if (ratio > 0.48) return 4;
  if (ratio > 0.28) return 3;
  if (ratio > 0.12) return 2;
  return 1;
}

function shortLocality(value) {
  return String(value || "").split(" - ")[0].slice(0, 13);
}

let localityHeatMap = null;

function renderLocalityHeatMap(localities) {
  const container = document.getElementById("localityHeatMap");
  if (!container) return;
  const features = (localities || [])
    .filter((row) => Number.isFinite(Number(row.lon)) && Number.isFinite(Number(row.lat)))
    .map((row) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [Number(row.lon), Number(row.lat)] },
      properties: {
        locality: row.locality,
        policies: row.policies,
        clients: row.clients,
        premium: row.premium,
      },
    }));
  const geojson = { type: "FeatureCollection", features };
  if (!features.length) {
    container.innerHTML = `<div class="empty-state">No hay localidades con coordenadas para el filtro actual.</div>`;
    return;
  }
  if (!window.maplibregl) {
    container.innerHTML = `<div class="empty-state">No se pudo cargar Mapbox/MapLibre. Revisa la conexión a internet.</div>`;
    return;
  }

  if (localityHeatMap) {
    localityHeatMap.remove();
    localityHeatMap = null;
  }
  localityHeatMap = new window.maplibregl.Map({
    container,
    style: {
      version: 8,
      glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
      sources: {
        carto: {
          type: "raster",
          tiles: [
            "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
            "https://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
            "https://c.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
          ],
          tileSize: 256,
          attribution: "© OpenStreetMap © CARTO",
        },
      },
      layers: [{ id: "carto", type: "raster", source: "carto" }],
    },
    center: [-15.4, 28.2],
    zoom: 7.2,
    pitch: 46,
    bearing: -18,
    minZoom: 4,
    maxZoom: 13,
    maxBounds: [[-19.5, 26.5], [5.5, 44.7]],
    attributionControl: false,
  });
  window.localityHeatMapInstance = localityHeatMap;
  localityHeatMap.addControl(new window.maplibregl.NavigationControl({ showCompass: false }), "top-right");
  localityHeatMap.on("load", () => {
    localityHeatMap.addSource("locality-heat", { type: "geojson", data: geojson });
    localityHeatMap.addLayer({
      id: "locality-heat-layer",
      type: "heatmap",
      source: "locality-heat",
      maxzoom: 10,
      paint: {
        "heatmap-weight": ["interpolate", ["linear"], ["get", "policies"], 0, 0, 500, 0.35, 2500, 1],
        "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 4, 0.95, 9, 2.4],
        "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 4, 22, 8, 42, 11, 64],
        "heatmap-opacity": 0.84,
        "heatmap-color": [
          "interpolate",
          ["linear"],
          ["heatmap-density"],
          0,
          "rgba(0,122,255,0)",
          0.2,
          "rgba(0,122,255,0.45)",
          0.45,
          "rgba(52,199,89,0.58)",
          0.68,
          "rgba(255,204,0,0.72)",
          0.85,
          "rgba(255,149,0,0.82)",
          1,
          "rgba(255,59,48,0.92)",
        ],
      },
    });
    localityHeatMap.addLayer({
      id: "locality-point-layer",
      type: "circle",
      source: "locality-heat",
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["get", "policies"], 0, 4, 700, 10, 2500, 22, 7000, 34],
        "circle-color": "rgba(255,255,255,0.92)",
        "circle-stroke-color": ["interpolate", ["linear"], ["get", "policies"], 0, "#007aff", 900, "#ff9f0a", 2500, "#ff3b30"],
        "circle-stroke-width": ["interpolate", ["linear"], ["get", "policies"], 0, 1.4, 2500, 4],
        "circle-opacity": 0.94,
        "circle-pitch-scale": "map",
      },
    });
    localityHeatMap.addLayer({
      id: "locality-label-layer",
      type: "symbol",
      source: "locality-heat",
      filter: [">=", ["get", "policies"], 250],
      layout: {
        "text-field": ["get", "locality"],
        "text-size": ["interpolate", ["linear"], ["get", "policies"], 250, 11, 2500, 15],
        "text-offset": [0, 1.45],
        "text-anchor": "top",
      },
      paint: {
        "text-color": "#102033",
        "text-halo-color": "rgba(255,255,255,0.92)",
        "text-halo-width": 2,
      },
    });
    const bounds = weightedLocalityBounds(features);
    localityHeatMap.fitBounds(bounds, { padding: { top: 72, right: 86, bottom: 72, left: 86 }, maxZoom: 9.8, duration: 0 });
    localityHeatMap.setPitch(48);
    localityHeatMap.setBearing(-22);
  });
  localityHeatMap.on("click", "locality-point-layer", (event) => {
    const item = event.features?.[0];
    if (!item) return;
    new window.maplibregl.Popup()
      .setLngLat(item.geometry.coordinates)
      .setHTML(`<strong>${item.properties.locality}</strong><br>${numberFormatter.format(item.properties.policies)} pólizas<br>${moneyFormatter.format(item.properties.premium)}`)
      .addTo(localityHeatMap);
  });
}

function weightedLocalityBounds(features) {
  const sorted = [...features].sort((a, b) => Number(b.properties.policies || 0) - Number(a.properties.policies || 0));
  const totalPolicies = sorted.reduce((sum, feature) => sum + Number(feature.properties.policies || 0), 0) || 1;
  const [topLon, topLat] = sorted[0]?.geometry?.coordinates ?? [-15.4, 28.2];
  const dominantCluster = sorted.filter((feature) => {
    const [lon, lat] = feature.geometry.coordinates;
    return Math.abs(lon - topLon) <= 3.6 && Math.abs(lat - topLat) <= 2.8;
  });
  const clusterPolicies = dominantCluster.reduce((sum, feature) => sum + Number(feature.properties.policies || 0), 0);
  const focusSource = clusterPolicies / totalPolicies >= 0.32 ? dominantCluster : sorted;
  const focusTarget = focusSource === dominantCluster ? 0.92 : 0.72;
  const focus = [];
  let running = 0;
  for (const feature of focusSource) {
    focus.push(feature);
    running += Number(feature.properties.policies || 0);
    if ((focus.length >= 8 && running / Math.max(clusterPolicies, totalPolicies) >= focusTarget) || focus.length >= 40) break;
  }
  const bounds = new window.maplibregl.LngLatBounds();
  focus.forEach((feature) => bounds.extend(feature.geometry.coordinates));
  return bounds;
}

function renderInsights(insights) {
  const sections = [
    ["Aseguradoras", insights?.byInsurer ?? []],
    ["Oficinas comerciales", insights?.byOffice ?? []],
  ];
  portfolioInsights.innerHTML = sections
    .map(
      ([title, rows]) => `
        <article class="insight-panel">
          <div class="insight-head">
            <span>${title}</span>
            <strong>${numberFormatter.format(rows.length)}</strong>
          </div>
          <div class="insight-list">
            ${rows
              .map(
                (row) => `
                  <div class="insight-row">
                    <div>
                      <strong>${row.name}</strong>
                      <span>${numberFormatter.format(row.activePolicies)} activas de ${numberFormatter.format(row.policies)}</span>
                    </div>
                    <em>${moneyFormatter.format(row.premium)}</em>
                  </div>
                `,
              )
              .join("")}
          </div>
        </article>
      `,
    )
    .join("");
}

function filterRowsBySearch(rows, columns) {
  const term = state.tableSearch.trim().toLowerCase();
  if (!term) return rows;
  return rows.filter((row) =>
    columns.some((column) => String(row[column.key] ?? "").toLowerCase().includes(term)),
  );
}

function renderTable(listing) {
  const columns = listing.columns ?? [];
  const rows = filterRowsBySearch(listing.rows ?? [], columns);
  resultsTitle.textContent = listing.title ?? viewConfig[state.activeView].title;

  const metaBits = [];
  metaBits.push(`${numberFormatter.format(rows.length)} filas visibles`);
  if (listing.window?.from && listing.window?.to) {
    metaBits.push(`Ventana ${formatMaybeDate(listing.window.from)} a ${formatMaybeDate(listing.window.to)}`);
  }
  tableMeta.textContent = metaBits.join(" · ");

  if (!rows.length) {
    resultsTable.innerHTML = `<div class="empty-state">No hay resultados para la combinación actual de filtros.</div>`;
    return;
  }

  const head = columns.map((column) => `<th>${column.label}</th>`).join("");
  const body = rows
    .map(
      (row) => `
        <tr>
          ${columns.map((column) => `<td>${formatCell(row[column.key], column.key)}</td>`).join("")}
        </tr>
      `,
    )
    .join("");

  resultsTable.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function setModule(moduleName) {
  state.activeModule = moduleName;
  moduleTabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.module === moduleName));
  modulePanels.forEach((panel) => panel.classList.toggle("hidden", panel.dataset.modulePanel !== moduleName));
  if (window.location.hash !== `#${moduleName}`) window.history.replaceState(null, "", `#${moduleName}`);
  if (moduleName === "scanner") {
    appTitle.textContent = "Escáner de Liquidaciones";
    appLede.textContent = "Extrae pólizas, tomadores, primas netas y fecha desde PDFs de aseguradoras, valida la plantilla y graba el resultado en hoja.";
    sourceLabel.textContent = "Google Drive PDF";
    loadScannerSummary();
  } else {
    appTitle.textContent = "Radar de Pólizas";
    appLede.textContent = "Cartera conectada a Google Sheets con filtros por oficina comercial, aseguradora, ramo y vencimiento.";
    if (state.dashboard) sourceLabel.textContent = state.dashboard.sourcePath.split("/").pop();
  }
}

function currentTemplatePayload() {
  const selected = (state.scanner.summary?.templates ?? []).find((template) => template.insurer === templateSelect.value);
  const modeFromScan = state.scanner.currentScan?.template?.recordMode;
  const insurer = insurerName.value.trim();
  const recordMode = insurer.toLowerCase().includes("reale")
    ? "reale-table"
    : modeFromScan ?? selected?.recordMode ?? "line";
  return {
    insurer,
    fields: {
      policy: policyPattern.value.trim(),
      holder: holderPattern.value.trim(),
      netPremium: premiumPattern.value.trim(),
      liquidationDate: datePattern.value.trim(),
    },
    recordMode,
  };
}

function hydrateTemplate(template = null) {
  const fields = template?.fields ?? defaultPatterns;
  policyPattern.value = fields.policy ?? defaultPatterns.policy;
  holderPattern.value = fields.holder ?? defaultPatterns.holder;
  premiumPattern.value = fields.netPremium ?? defaultPatterns.netPremium;
  datePattern.value = fields.liquidationDate ?? defaultPatterns.liquidationDate;
  if (template?.insurer) insurerName.value = template.insurer;
}

function setScannerStatus(text, tone = "neutral") {
  scannerStatus.textContent = text;
  scannerStatus.dataset.tone = tone;
}

function driveDocumentIdFromUrl(url) {
  const match = url.match(/\/file\/d\/([^/]+)/) || url.match(/[?&]id=([^&]+)/);
  return match ? decodeURIComponent(match[1]) : "No detectado";
}

function clearScanError() {
  scanError.classList.add("hidden");
  scanError.innerHTML = "";
}

function renderScanError(message, url = driveUrl.value) {
  const documentId = driveDocumentIdFromUrl(url);
  const lowerMessage = String(message || "").toLowerCase();
  const isOcrError = lowerMessage.includes("ocr") || lowerMessage.includes("no contiene texto") || lowerMessage.includes("escaneado como imagen");
  const probableCause = isOcrError
    ? "El archivo sí se descargó, pero sus páginas son imágenes escaneadas y no traen texto seleccionable."
    : "Google Drive no entregó una descarga PDF directa al servidor.";
  const nextStep = isOcrError
    ? "Sube una versión PDF con texto seleccionable o procesa el documento con OCR antes de escanearlo."
    : "Comparte el archivo con permiso de lectura mediante enlace o descarga el PDF y cachea el archivo para ese ID.";
  scanError.classList.remove("hidden");
  scanError.innerHTML = `
    <div class="scan-error-title">No se pudo escanear este PDF</div>
    <div class="scan-error-message">${message}</div>
    <dl class="scan-error-details">
      <div><dt>ID detectado</dt><dd>${documentId}</dd></div>
      <div><dt>Causa probable</dt><dd>${probableCause}</dd></div>
      <div><dt>Qué hacer</dt><dd>${nextStep}</dd></div>
    </dl>
  `;
}

function renderScannerKpis(scan = state.scanner.currentScan, summary = state.scanner.summary) {
  const totals = scan?.totals ?? summary?.totals ?? { policies: 0, netPremium: 0, templates: 0, scans: 0 };
  const items = scan
    ? [
        ["Total pólizas", numberFormatter.format(totals.policies), "En el documento probado"],
        ["Prima neta", moneyFormatter.format(totals.netPremium), "Suma extraída"],
        ["Fecha liquidación", scan.liquidationDate || "—", "Normalizada para la hoja"],
        ["Confianza", `${Math.round((scan.confidence ?? 0) * 100)}%`, "Revisar antes de grabar"],
      ]
    : [
        ["Plantillas", numberFormatter.format(totals.templates), "Aseguradoras entrenadas"],
        ["Escaneos", numberFormatter.format(totals.scans), "Documentos confirmados"],
        ["Pólizas", numberFormatter.format(totals.policies), "Filas acumuladas"],
        ["Prima neta", moneyFormatter.format(totals.netPremium), "Monto acumulado"],
      ];

  scannerKpis.innerHTML = items
    .map(
      ([label, value, note]) => `
        <article class="scanner-kpi">
          <span>${label}</span>
          <strong>${value}</strong>
          <small>${note}</small>
        </article>
      `,
    )
    .join("");
}

function renderTemplates() {
  const templates = state.scanner.summary?.templates ?? [];
  templateSelect.innerHTML = [
    `<option value="">Plantilla automática</option>`,
    ...templates.map((template) => `<option value="${template.insurer}">${template.insurer}</option>`),
  ].join("");
}

function renderSheetLink(summary = state.scanner.summary) {
  const url = summary?.googleSheetUrl || "";
  if (!url) {
    openSheetLink.classList.add("hidden");
    openSheetLink.removeAttribute("href");
    sheetSyncStatus.textContent = "No hay hoja de Google Sheet vinculada.";
    return;
  }
  openSheetLink.href = url;
  openSheetLink.classList.remove("hidden");
  if (!sheetSyncStatus.textContent || sheetSyncStatus.textContent.includes("No hay hoja")) {
    sheetSyncStatus.textContent = "Presiona “Grabar en hoja” para guardar el escaneo y abrir la hoja vinculada.";
  }
}

function renderScanTable() {
  clearScanError();
  const scan = state.scanner.currentScan;
  if (!scan) {
    scanTable.innerHTML = `<div class="empty-state">Prueba un PDF para revisar pólizas, tomadores y primas netas.</div>`;
    return;
  }
  const term = state.scanner.search.trim().toLowerCase();
  const rows = (scan.rows ?? []).filter((row) =>
    [row.poliza, row.tomador, row.primaNeta, row.PMP].some((value) => String(value ?? "").toLowerCase().includes(term)),
  );
  scanMeta.textContent = `${numberFormatter.format(rows.length)} filas visibles · Documento ${scan.documentId} · ${scan.pageCount} páginas`;
  if (!rows.length) {
    scanTable.innerHTML = `<div class="empty-state">No hay filas que coincidan con la búsqueda.</div>`;
    return;
  }
  scanTable.innerHTML = `
    <table>
      <thead>
        <tr><th>Póliza</th><th>Tomador / cliente</th><th>Prima neta</th><th>PMP</th></tr>
      </thead>
      <tbody>
        ${rows
          .map(
            (row) => `
              <tr>
                <td>${row.poliza || "—"}</td>
                <td>${row.tomador || "—"}</td>
                <td>${moneyFormatter.format(row.primaNeta || 0)}</td>
                <td><span class="row-status">${row.PMP || "No"}</span></td>
              </tr>
            `,
          )
          .join("")}
      </tbody>
    </table>
  `;
}

function renderHistory() {
  const rows = state.scanner.summary?.historyRows ?? [];
  if (!rows.length) {
    historyTable.innerHTML = `<div class="empty-state">Aún no hay documentos grabados.</div>`;
    return;
  }
  historyTable.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Última fecha</th><th>ID documento</th><th>Pólizas</th><th>Prima neta</th><th>Aseguradora</th><th>Mes/año</th>
        </tr>
      </thead>
      <tbody>
        ${rows
          .map(
            (row) => `
              <tr>
                <td>${String(row["ultima fecha de escaneo"] || "").replace("T", " ")}</td>
                <td>${row["id del documento"] || "—"}</td>
                <td>${numberFormatter.format(row["total polizas"] || 0)}</td>
                <td>${moneyFormatter.format(row["total monto prima neta"] || 0)}</td>
                <td>${row["nombre de la aseguradora"] || "—"}</td>
                <td>${row["mes y año del documento escaneado"] || "—"}</td>
              </tr>
            `,
          )
          .join("")}
      </tbody>
    </table>
  `;
}

async function loadScannerSummary() {
  state.scanner.summary = await fetchJSON("/api/scanner/summary");
  if (
    state.scanner.summary.lastScan &&
    (!state.scanner.currentScan || state.scanner.currentScan.documentId === state.scanner.summary.lastScan.documentId)
  ) {
    state.scanner.currentScan = {
      ...(state.scanner.currentScan ?? {}),
      ...state.scanner.summary.lastScan,
      pageCount: state.scanner.summary.lastScan.pageCount ?? "—",
      confidence: 0.98,
    };
  }
  renderTemplates();
  renderSheetLink();
  renderScannerKpis(state.scanner.currentScan);
  renderScanTable();
  renderHistory();
}

async function runScan() {
  const url = driveUrl.value.trim();
  if (!url) throw new Error("Agrega una URL de Google Drive.");
  clearScanError();
  setScannerStatus("Escaneando", "working");
  const selected = (state.scanner.summary?.templates ?? []).find((template) => template.insurer === templateSelect.value);
  const payload = {
    driveUrl: url,
    insurer: insurerName.value.trim(),
    template: selected ? selected : currentTemplatePayload(),
  };
  const scan = await postJSON("/api/scanner/scan", payload);
  state.scanner.currentScan = scan;
  insurerName.value = scan.insurer;
  hydrateTemplate(scan.template);
  textPreview.textContent = scan.textPreview || "El PDF no devolvió texto extraíble.";
  renderScannerKpis(scan);
  renderScanTable();
  setScannerStatus("Prueba lista", "ok");
}

async function saveCurrentTemplate() {
  if (!insurerName.value.trim()) throw new Error("Indica la aseguradora antes de guardar.");
  setScannerStatus("Guardando", "working");
  const result = await postJSON("/api/scanner/templates", {
    insurer: insurerName.value.trim(),
    template: currentTemplatePayload(),
  });
  state.scanner.summary = { ...(state.scanner.summary ?? {}), templates: result.templates };
  renderTemplates();
  renderSheetLink();
  templateSelect.value = insurerName.value.trim();
  setScannerStatus("Plantilla guardada", "ok");
  sheetSyncStatus.textContent = `Plantilla guardada para ${insurerName.value.trim()}.`;
}

async function commitCurrentScan() {
  const scan = state.scanner.currentScan;
  if (!scan) throw new Error("Primero prueba un PDF.");
  setScannerStatus("Grabando", "working");
  const result = await postJSON("/api/scanner/commit", {
    documentId: scan.documentId,
    insurer: insurerName.value.trim() || scan.insurer,
    liquidationDate: scan.liquidationDate,
    pageCount: scan.pageCount,
    rows: scan.rows,
  });
  state.scanner.summary = result.summary;
  renderScannerKpis(scan, result.summary);
  renderSheetLink(result.summary);
  renderHistory();
  const syncMode = result.sync?.mode;
  const syncMessage = result.sync?.message || "";
  if (syncMode === "webhook" || syncMode === "google-api") {
    setScannerStatus("Google Sheet actualizado", "ok");
    sheetSyncStatus.textContent = syncMessage || "Datos enviados a Google Sheet.";
    return;
  }
  setScannerStatus("Google Sheet no actualizado", "error");
  sheetSyncStatus.textContent =
    syncMessage || "El escaneo quedó guardado localmente, pero Google Sheet no se actualizó.";
}

function renderChatMessage(role, text, columns = [], rows = []) {
  const wrapper = document.createElement("div");
  wrapper.className = `message ${role}`;
  let html = `<p>${text}</p>`;

  if (rows.length && columns.length) {
    const head = columns.map((column) => `<th>${column.label}</th>`).join("");
    const body = rows
      .map(
        (row) => `
          <tr>
            ${columns.map((column) => `<td>${formatCell(row[column.key], column.key)}</td>`).join("")}
          </tr>
        `,
      )
      .join("");
    html += `<div class="table-shell"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  wrapper.innerHTML = html;
  chatMessages.appendChild(wrapper);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

async function askChat(question) {
  renderChatMessage("user", question);
  chatInput.value = "";
  const filters = serializeFilters();
  const query = new URLSearchParams(filters);
  query.set("q", question);
  const payload = await fetchJSON(`/api/chat?${query.toString()}`);
  renderChatMessage("assistant", payload.answer, payload.columns, payload.rows);
}

function renderChatSuggestions() {
  chatSuggestions.innerHTML = suggestions
    .map((text) => `<button class="suggestion" data-question="${text}">${text}</button>`)
    .join("");
  chatSuggestions.querySelectorAll("[data-question]").forEach((button) => {
    button.addEventListener("click", () => askChat(button.dataset.question));
  });
}

async function loadWorkspace() {
  const filters = serializeFilters();
  const dashboardPath = `/api/dashboard${filters ? `?${filters}` : ""}`;
  const listingPath = `${viewConfig[state.activeView].endpoint}${filters ? `?${filters}` : ""}`;
  const [dashboard, listing] = await Promise.all([fetchJSON(dashboardPath), fetchJSON(listingPath)]);

  state.dashboard = dashboard;
  state.activeListing = listing;
  if (!state.masterOptions) state.masterOptions = dashboard.options;

  renderKPIs(dashboard.metrics);
  renderActionCards(dashboard.highlights);
  renderFilterDropdowns();
  renderActiveFilters();
  renderInsights(dashboard.insights);
  renderCharts(dashboard.charts);
  renderTable(listing);

  generatedAt.textContent = dashboard.generatedAt.replace("T", " ");
  if (state.activeModule === "portfolio") sourceLabel.textContent = dashboard.sourcePath.split("/").pop();
}

function bindEvents() {
  moduleTabs.forEach((tab) => {
    tab.addEventListener("click", () => setModule(tab.dataset.module));
  });

  officeSelect.addEventListener("change", () => {
    state.filters.officeId = officeSelect.value;
    loadWorkspace();
  });

  statusSelect.addEventListener("change", () => {
    state.filters.status = statusSelect.value;
    loadWorkspace();
  });

  insurerSelect.addEventListener("change", () => {
    state.filters.insurer = insurerSelect.value;
    loadWorkspace();
  });

  typeSelect.addEventListener("change", () => {
    state.filters.insuranceType = typeSelect.value;
    loadWorkspace();
  });

  expirationMonth.addEventListener("change", () => {
    state.filters.expirationMonth = expirationMonth.value;
    loadWorkspace();
  });

  tableSearch.addEventListener("input", () => {
    state.tableSearch = tableSearch.value;
    renderTable(state.activeListing);
  });

  resetFilters.addEventListener("click", () => {
    state.filters.officeId = "";
    state.filters.status = "";
    state.filters.insurer = "";
    state.filters.insuranceType = "";
    state.filters.expirationMonth = "";
    officeSelect.value = "";
    statusSelect.value = "";
    insurerSelect.value = "";
    typeSelect.value = "";
    expirationMonth.value = "";
    loadWorkspace();
  });

  chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = chatInput.value.trim();
    if (!question) return;
    await askChat(question);
  });

  hydrateTemplate();

  templateSelect.addEventListener("change", () => {
    const selected = (state.scanner.summary?.templates ?? []).find((template) => template.insurer === templateSelect.value);
    hydrateTemplate(selected);
  });

  scanSearch.addEventListener("input", () => {
    state.scanner.search = scanSearch.value;
    renderScanTable();
  });

  scannerForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await runScan();
    } catch (error) {
      setScannerStatus("Error", "error");
      scanMeta.textContent = "El documento no pudo procesarse.";
      renderScanError(error.message);
      scanTable.innerHTML = "";
    }
  });

  saveTemplate.addEventListener("click", async () => {
    try {
      await saveCurrentTemplate();
    } catch (error) {
      setScannerStatus("Error", "error");
      scanMeta.textContent = error.message;
    }
  });

  commitScan.addEventListener("click", async () => {
    try {
      await commitCurrentScan();
    } catch (error) {
      setScannerStatus("Error", "error");
      scanMeta.textContent = error.message;
    }
  });

  openSheetLink.addEventListener("click", (event) => {
    const href = openSheetLink.getAttribute("href");
    if (!href || href === "#") return;
    event.preventDefault();
    window.location.assign(href);
  });
}

async function boot() {
  renderChatSuggestions();
  bindEvents();
  renderChatMessage(
    "assistant",
    "Puedo responder preguntas sobre clientes activos, primas, vencimientos, oficinas, tipos de seguro, ex clientes y ventas cruzadas.",
  );
  await loadWorkspace();
  await loadScannerSummary();
  setModule(window.location.hash === "#scanner" ? "scanner" : "portfolio");
}

boot().catch((error) => {
  renderChatMessage("assistant", `No pude cargar el dashboard: ${error.message}`);
});
