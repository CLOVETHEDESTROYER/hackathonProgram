/* global L */
(function () {
  const config = window.EMBER_CONFIG || {};
  const statusEl = document.getElementById("status");
  const sourcesEl = document.getElementById("sources");
  const hottestEl = document.getElementById("hottest");
  const filterButtons = Array.from(document.querySelectorAll(".filters button"));
  const latInput = document.getElementById("lat");
  const lonInput = document.getElementById("lon");
  const assessForm = document.getElementById("assess-form");
  const assessStatus = document.getElementById("assess-status");
  const assessSummary = document.getElementById("assess-summary");
  const recsEl = document.getElementById("recs");
  const assessNote = document.getElementById("assess-note");
  const assessButton = assessForm ? assessForm.querySelector("button") : null;

  const EVIDENCE = {
    aerial: "Seen from above",
    inferred: "Inferred",
    ground_required: "Walk the site",
  };

  let map = null;
  let zoneLayer = null;
  let footprintLayer = null;
  let assessToken = 0;

  if (config.demo && latInput && lonInput) {
    latInput.value = String(config.demo.lat);
    lonInput.value = String(config.demo.lon);
  }

  const PLACES = [
    ["Albuquerque", 35.0844, -106.6504],
    ["Santa Fe", 35.687, -105.9378],
    ["Las Cruces", 32.3199, -106.7637],
    ["Roswell", 33.3943, -104.523],
    ["Farmington", 36.7281, -108.2187],
    ["Rio Rancho", 35.2328, -106.663],
    ["Hobbs", 32.7026, -103.136],
    ["Clovis", 34.4048, -103.2052],
    ["Carlsbad", 32.4207, -104.2288],
    ["Gallup", 35.5281, -108.7426],
    ["Los Alamos", 35.88, -106.3031],
    ["Taos", 36.4072, -105.5731],
    ["Silver City", 32.7701, -108.2803],
    ["Ruidoso", 33.3317, -105.673],
    ["Las Vegas", 35.5942, -105.2228],
    ["Socorro", 34.0584, -106.8914],
    ["Alamogordo", 32.8995, -105.9603],
    ["Grants", 35.1473, -107.8514],
    ["Española", 35.9914, -106.0806],
    ["Truth or Consequences", 33.1284, -107.2528],
  ];

  const LABELS = ["Albuquerque", "Santa Fe", "Las Cruces", "Farmington", "Roswell"];
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];

  let mode = "all";
  let collection = null;
  let origin = "";
  let hotspotLayer = null;

  function setStatus(text) {
    statusEl.textContent = text;
  }

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[ch]);
  }

  function haversineKm(lat1, lon1, lat2, lon2) {
    const toRad = Math.PI / 180;
    const dLat = (lat2 - lat1) * toRad;
    const dLon = (lon2 - lon1) * toRad;
    const a = Math.sin(dLat / 2) ** 2
      + Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.sin(dLon / 2) ** 2;
    return 6371 * 2 * Math.asin(Math.min(1, Math.sqrt(a)));
  }

  function bearingDeg(lat1, lon1, lat2, lon2) {
    const toRad = Math.PI / 180;
    const y = Math.sin((lon2 - lon1) * toRad) * Math.cos(lat2 * toRad);
    const x = Math.cos(lat1 * toRad) * Math.sin(lat2 * toRad)
      - Math.sin(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.cos((lon2 - lon1) * toRad);
    return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
  }

  function nearestTown(lat, lon) {
    let best = null;
    for (const [name, placeLat, placeLon] of PLACES) {
      const km = haversineKm(placeLat, placeLon, lat, lon);
      if (!best || km < best.km) {
        best = {
          name,
          km,
          bearing: bearingDeg(placeLat, placeLon, lat, lon),
        };
      }
    }
    if (!best || best.km > 120) {
      return "";
    }
    const distance = best.km < 10 ? best.km.toFixed(1) : String(Math.round(best.km));
    const direction = COMPASS[Math.round(best.bearing / 45) % 8];
    return `${distance} km ${direction} of ${best.name}`;
  }

  function formatWhen(props) {
    const stamp = props.acquired_at;
    if (!stamp || stamp.length < 16) {
      return "time unknown";
    }
    const date = stamp.slice(0, 10);
    const time = stamp.slice(11, 16);
    const month = MONTHS[Number(date.slice(5, 7)) - 1] || date.slice(5, 7);
    return `${Number(date.slice(8, 10))} ${month} ${date.slice(0, 4)} · ${time} UTC`;
  }

  function formatFrp(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return "";
    }
    return `${number < 10 ? number.toFixed(2) : number.toFixed(1)} MW`;
  }

  function passes(feature) {
    const props = feature.properties || {};
    if (mode === "day") {
      return props.daynight === "D";
    }
    if (mode === "night") {
      return props.daynight === "N";
    }
    if (mode === "hot") {
      return Number(props.frp) >= 1;
    }
    return true;
  }

  function styleFor(props) {
    const frp = Number(props.frp) || 0;
    const radius = Math.max(5, Math.min(16, 5 + Math.sqrt(frp) * 2.2));
    const label = String(props.confidence_label || "").toLowerCase();
    const score = Number(label);
    let fill = "#ff7a18";
    if (label === "low") {
      fill = "#c4a574";
    } else if (label === "high" || score >= 80) {
      fill = "#ffe08a";
    }
    return {
      radius,
      color: props.daynight === "N" ? "#9ecbff" : "#fff4e8",
      weight: 1.5,
      fillColor: fill,
      fillOpacity: 0.92,
    };
  }

  function popupHtml(feature) {
    const props = feature.properties || {};
    const [lon, lat] = feature.geometry.coordinates;
    const where = nearestTown(lat, lon);
    const bits = [formatFrp(props.frp), props.daynight_label, props.confidence_label]
      .filter(Boolean)
      .join(" · ");
    return [
      `<strong>${esc(props.source_label || props.source || "Hotspot")}</strong>`,
      `<div>${esc(formatWhen(props))}</div>`,
      bits ? `<div>${esc(bits)}</div>` : "",
      where ? `<div>${esc(where)}</div>` : "",
    ].join("");
  }

  function render() {
    if (!collection || !hotspotLayer) {
      return;
    }
    hotspotLayer.clearLayers();
    const features = (collection.features || []).filter(passes);
    L.geoJSON(
      { type: "FeatureCollection", features },
      {
        pointToLayer: (feature, latlng) => L.circleMarker(latlng, styleFor(feature.properties || {})),
        onEachFeature: (feature, layer) => {
          layer.bindPopup(popupHtml(feature));
        },
      },
    ).addTo(hotspotLayer);

    const ember = collection.ember || {};
    const shown = features.length;
    const total = ember.count ?? (collection.features || []).length;
    const when = ember.generated_at ? ember.generated_at.replace("T", " ").replace("Z", " UTC") : "";
    const whereFrom = origin === "live" ? "live feed" : origin === "snapshot" ? "S3 snapshot" : "feed";
    if (total === 0) {
      setStatus(`No hotspots in the last ${config.dayRange || 2} days. ${whereFrom}${when ? ` · ${when}` : ""}`);
    } else if (shown === total) {
      setStatus(`${total} hotspot${total === 1 ? "" : "s"} · ${whereFrom}${when ? ` · ${when}` : ""}`);
    } else {
      setStatus(`${shown} of ${total} shown · ${whereFrom}${when ? ` · ${when}` : ""}`);
    }

    const sourceLine = (ember.sources || [])
      .map((source) => `${source.label || source.id} ${source.error ? "failed" : source.count}`)
      .join(" · ");
    sourcesEl.textContent = sourceLine;

    const ranked = features
      .slice()
      .sort((a, b) => Number(b.properties.frp || 0) - Number(a.properties.frp || 0))
      .slice(0, 5);
    hottestEl.replaceChildren();
    for (const feature of ranked) {
      const props = feature.properties || {};
      const [lon, lat] = feature.geometry.coordinates;
      const item = document.createElement("li");
      const title = document.createElement("strong");
      title.textContent = [formatFrp(props.frp) || "FRP n/a", props.source_label || props.source].filter(Boolean).join(" · ");
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = [formatWhen(props), nearestTown(lat, lon)].filter(Boolean).join(" · ");
      item.append(title, meta);
      hottestEl.append(item);
    }
  }

  function show(data, nextOrigin) {
    if (!data || data.type !== "FeatureCollection") {
      throw new Error((data && data.message) || "Feed was not GeoJSON");
    }
    if (origin === "live" && nextOrigin === "snapshot") {
      return;
    }
    collection = data;
    origin = nextOrigin;
    render();
  }

  async function fetchJson(url) {
    const response = await fetch(url, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(data.message || `HTTP ${response.status}`);
      error.payload = data;
      throw error;
    }
    return data;
  }

  function initMap() {
    const bbox = config.bbox || [-109.05, 31.33, -103, 37];
    const bounds = L.latLngBounds([bbox[1], bbox[0]], [bbox[3], bbox[2]]);
    map = L.map("map", { zoomControl: false, minZoom: 5, maxZoom: 19 });
    L.control.zoom({ position: "topright" }).addTo(map);

    const imagery = L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      {
        attribution: "Tiles &copy; Esri, USDA NAIP where available",
        maxZoom: 19,
        maxNativeZoom: 19,
      },
    );
    const streets = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap",
      maxZoom: 19,
    });
    imagery.addTo(map);
    imagery.on("tileerror", () => {
      if (!map.hasLayer(streets)) {
        streets.addTo(map);
        imagery.remove();
      }
    });

    L.rectangle(bounds, {
      color: "#ffb703",
      weight: 1.25,
      fill: false,
      dashArray: "5 7",
      interactive: false,
    }).addTo(map);

    for (const [name, lat, lon] of PLACES) {
      if (!LABELS.includes(name)) {
        continue;
      }
      L.circleMarker([lat, lon], {
        radius: 2.5,
        color: "#f6efe6",
        weight: 1,
        fillOpacity: 0.9,
        interactive: false,
      })
        .bindTooltip(name, {
          permanent: true,
          direction: "right",
          className: "town",
          offset: [6, 0],
        })
        .addTo(map);
    }

    const narrow = window.innerWidth < 720;
    map.fitBounds(bounds, {
      paddingTopLeft: narrow ? [16, 16] : [410, 28],
      paddingBottomRight: narrow ? [16, 240] : [28, 28],
    });
    hotspotLayer = L.layerGroup().addTo(map);
    map.on("click", (event) => {
      const lat = event.latlng.lat;
      const lon = event.latlng.lng;
      if (latInput) latInput.value = lat.toFixed(6);
      if (lonInput) lonInput.value = lon.toFixed(6);
      runAssess(lat, lon);
    });
    return map;
  }

  function assessEndpoint(lat, lon) {
    const base = String(config.functionUrl || "").replace(/\/$/, "");
    if (!base) {
      return "";
    }
    return `${base}/assess?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`;
  }

  function drawAssessment(data) {
    if (!map) {
      return;
    }
    if (zoneLayer) {
      zoneLayer.remove();
    }
    if (footprintLayer) {
      footprintLayer.remove();
    }
    const zoneColors = { B0: "#ff3b30", B1: "#ff9f0a", B2: "#ffd60a" };
    if (data.zones) {
      zoneLayer = L.geoJSON(data.zones, {
        style: (feature) => {
          const color = zoneColors[(feature.properties || {}).band] || "#ffd60a";
          return { color, weight: 2, fillColor: color, fillOpacity: 0.14 };
        },
      }).addTo(map);
    }
    const footprint = data.footprint && data.footprint.geojson;
    if (footprint) {
      footprintLayer = L.geoJSON(footprint, {
        style: { color: "#ffffff", weight: 2, fillColor: "#ffffff", fillOpacity: 0.08 },
      }).addTo(map);
    }
    const focus = zoneLayer || footprintLayer;
    if (focus) {
      map.fitBounds(focus.getBounds(), { padding: [28, 28], maxZoom: 18 });
    }
  }

  function renderRecs(data) {
    recsEl.replaceChildren();
    for (const rec of data.recommendations || []) {
      const item = document.createElement("li");
      const title = document.createElement("strong");
      title.className = "rec-title";
      title.textContent = rec.title || "Action";
      const badges = document.createElement("div");
      badges.className = "badges";
      const chips = [
        [rec.priority, String(rec.priority || "").toLowerCase()],
        [rec.zone, ""],
        [EVIDENCE[rec.evidence] || rec.evidence, ""],
        [rec.confidence, ""],
      ];
      for (const [label, className] of chips) {
        if (!label) {
          continue;
        }
        const badge = document.createElement("span");
        badge.className = className ? `badge ${className}` : "badge";
        badge.textContent = label;
        badges.append(badge);
      }
      const detail = document.createElement("p");
      detail.className = "detail";
      detail.textContent = rec.detail || "";
      item.append(title, badges, detail);
      recsEl.append(item);
    }
  }

  async function runAssess(lat, lon) {
    if (!assessStatus || !recsEl) {
      return;
    }
    const token = ++assessToken;
    assessSummary.textContent = "";
    recsEl.replaceChildren();
    assessNote.textContent = "";
    const url = assessEndpoint(lat, lon);
    if (!url) {
      assessStatus.textContent = "The assess function URL is not in config.js yet.";
      return;
    }
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
      assessStatus.textContent = "Enter decimal degrees.";
      return;
    }
    if (assessButton) {
      assessButton.disabled = true;
    }
    assessStatus.textContent = "Reading the aerial…";
    try {
      const data = await fetchJson(url);
      if (token !== assessToken) {
        return;
      }
      if (!data || data.type !== "PropertyAssessment") {
        throw new Error((data && data.message) || "Assessment was not recognized");
      }
      const engine = data.engine === "bedrock"
        ? `Bedrock · ${data.model_id || "vision"}`
        : "Heuristic fallback";
      const count = (data.recommendations || []).length;
      assessStatus.textContent = `${engine} · ${count} action${count === 1 ? "" : "s"}`;
      assessSummary.textContent = data.summary || "";
      renderRecs(data);
      assessNote.textContent = data.disclaimer || "";
      drawAssessment(data);
    } catch (error) {
      if (token !== assessToken) {
        return;
      }
      assessStatus.textContent = error.message || "Assessment failed.";
    } finally {
      if (token === assessToken && assessButton) {
        assessButton.disabled = false;
      }
    }
  }

  filterButtons.forEach((button) => {
    button.addEventListener("click", () => {
      mode = button.dataset.mode || "all";
      filterButtons.forEach((other) => {
        other.setAttribute("aria-pressed", other === button ? "true" : "false");
      });
      render();
    });
  });

  if (!config.bbox) {
    setStatus("config.js is missing a bounding box.");
    return;
  }
  if (typeof L === "undefined") {
    setStatus("The map library did not load. The GeoJSON feed is still the Lambda Function URL.");
    return;
  }

  initMap();

  if (assessForm) {
    assessForm.addEventListener("submit", (event) => {
      event.preventDefault();
      runAssess(Number(latInput.value), Number(lonInput.value));
    });
  }

  const tasks = [];
  if (config.snapshotUrl) {
    tasks.push(
      fetchJson(config.snapshotUrl)
        .then((data) => show(data, "snapshot"))
        .catch(() => {}),
    );
  }
  if (config.functionUrl) {
    tasks.push(
      fetchJson(config.functionUrl)
        .then((data) => show(data, "live"))
        .catch((error) => {
          if (origin === "snapshot") {
            setStatus(`${statusEl.textContent} Live feed unavailable.`);
            return;
          }
          setStatus(error.message || "Live feed unavailable.");
        }),
    );
  }

  if (tasks.length === 0) {
    setStatus("No feed URL is configured.");
  }
})();
