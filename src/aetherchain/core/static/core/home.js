(function () {
  const form = document.getElementById("scenario-form");
  if (!form) return;

  const locationGroup = document.getElementById("location-group");
  const supplierGroup = document.getElementById("supplier-group");
  const locationInput = document.getElementById("location-input");
  const supplierInput = document.getElementById("supplier-input");
  const eventTypeInput = document.getElementById("event-type");
  const horizonInput = document.getElementById("horizon-days");
  const priorityInput = document.getElementById("business-priority");
  const contextInput = document.getElementById("context-input");
  const runButton = document.getElementById("run-button");
  const catalogSource = document.getElementById("catalog-source");

  const skuEntry = document.getElementById("sku-entry");
  const routeEntry = document.getElementById("route-entry");
  const skuAddButton = document.getElementById("sku-add");
  const routeAddButton = document.getElementById("route-add");
  const skuChipContainer = document.getElementById("sku-chips");
  const routeChipContainer = document.getElementById("route-chips");

  const emptyState = document.getElementById("result-empty");
  const loadingState = document.getElementById("result-loading");
  const errorState = document.getElementById("result-error");
  const errorText = document.getElementById("error-text");
  const contentState = document.getElementById("result-content");
  const loadingMessage = document.getElementById("loading-message");

  const resultTitle = document.getElementById("result-title");
  const resultImpact = document.getElementById("result-impact");
  const resultAction = document.getElementById("result-action");
  const metricRisk = document.getElementById("metric-risk");
  const metricConfidence = document.getElementById("metric-confidence");
  const metricDelay = document.getElementById("metric-delay");
  const metricCost = document.getElementById("metric-cost");
  const evidenceList = document.getElementById("evidence-list");
  const assetTableBody = document.getElementById("asset-table-body");
  const metaTarget = document.getElementById("meta-target");
  const metaScope = document.getElementById("meta-scope");

  const selectedSkus = [];
  const selectedRoutes = [];

  const loadingMessages = [
    "Mapping impacted routes and assets...",
    "Reviewing supporting evidence...",
    "Crafting the clearest next action...",
  ];

  let loadingMessageTimer = null;
  let abortController = null;
  let catalogTimer = null;
  let lastPayload = null;

  function showState(state) {
    emptyState.classList.add("is-hidden");
    loadingState.classList.add("is-hidden");
    errorState.classList.add("is-hidden");
    contentState.classList.add("is-hidden");
    state.classList.remove("is-hidden");
  }

  function toggleTargetInputs() {
    const targetType = new FormData(form).get("target_type");
    const isLocation = targetType !== "supplier";
    locationGroup.classList.toggle("is-hidden", !isLocation);
    supplierGroup.classList.toggle("is-hidden", isLocation);
    if (isLocation) {
      supplierInput.value = "";
    } else {
      locationInput.value = "";
    }
  }

  function startLoadingMessages() {
    let index = 0;
    loadingMessage.textContent = loadingMessages[index];
    loadingMessageTimer = window.setInterval(() => {
      index = (index + 1) % loadingMessages.length;
      loadingMessage.textContent = loadingMessages[index];
    }, 1350);
  }

  function stopLoadingMessages() {
    if (loadingMessageTimer) {
      window.clearInterval(loadingMessageTimer);
      loadingMessageTimer = null;
    }
  }

  function formatPercent(value) {
    const safe = Number.isFinite(value) ? value : 0;
    return `${Math.round(safe * 100)}%`;
  }

  function formatMoney(value) {
    const safe = Number.isFinite(value) ? value : 0;
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0,
    }).format(safe);
  }

  function normalizeToken(value) {
    return String(value || "")
      .trim()
      .replace(/\s+/g, " ")
      .slice(0, 64);
  }

  function parseTokenInput(raw) {
    return String(raw || "")
      .split(/[,\n]/)
      .map((item) => normalizeToken(item))
      .filter(Boolean);
  }

  function pushUniqueToken(targetList, value) {
    const normalized = normalizeToken(value);
    if (!normalized) return;
    const exists = targetList.some((item) => item.toLowerCase() === normalized.toLowerCase());
    if (exists || targetList.length >= 12) return;
    targetList.push(normalized);
  }

  function removeToken(targetList, value) {
    const index = targetList.findIndex((item) => item.toLowerCase() === value.toLowerCase());
    if (index >= 0) {
      targetList.splice(index, 1);
    }
  }

  function renderTokenChips(targetList, container, label) {
    container.innerHTML = "";
    if (!targetList.length) {
      const placeholder = document.createElement("p");
      placeholder.className = "token-placeholder";
      placeholder.textContent = `No ${label.toLowerCase()} selected`;
      container.appendChild(placeholder);
      return;
    }

    targetList.forEach((token) => {
      const chip = document.createElement("span");
      chip.className = "token-chip";
      chip.textContent = token;

      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "token-remove";
      removeButton.setAttribute("aria-label", `Remove ${token}`);
      removeButton.textContent = "×";
      removeButton.addEventListener("click", () => {
        removeToken(targetList, token);
        renderTokenChips(targetList, container, label);
      });

      chip.appendChild(removeButton);
      container.appendChild(chip);
    });
  }

  function commitTokenInput(kind) {
    const isSku = kind === "sku";
    const input = isSku ? skuEntry : routeEntry;
    const targetList = isSku ? selectedSkus : selectedRoutes;
    parseTokenInput(input.value).forEach((token) => pushUniqueToken(targetList, token));
    input.value = "";
    renderTokenChips(targetList, isSku ? skuChipContainer : routeChipContainer, isSku ? "SKUs" : "Routes");
  }

  function populateDatalist(id, values) {
    const list = document.getElementById(id);
    if (!list) return;
    list.innerHTML = "";
    (values || []).forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      list.appendChild(option);
    });
  }

  function updateCatalogSource(source) {
    if (!catalogSource) return;
    if (!source) {
      catalogSource.textContent = "not available";
      return;
    }
    catalogSource.textContent = source === "neo4j" ? "live graph" : "fallback catalog";
  }

  async function fetchCatalog(extraParams) {
    const params = new URLSearchParams({ kind: "all", limit: "20" });
    const merged = {
      q: "",
      location: locationInput.value.trim(),
      supplier_name: supplierInput.value.trim(),
      ...(extraParams || {}),
    };

    Object.entries(merged).forEach(([key, value]) => {
      if (value) params.set(key, String(value));
    });

    try {
      const response = await fetch(`/experience/catalog/?${params.toString()}`);
      if (!response.ok) return;
      const data = await response.json();
      populateDatalist("location-options", data.ports || []);
      populateDatalist("supplier-options", data.suppliers || []);
      populateDatalist("sku-options", data.skus || []);
      populateDatalist("route-options", data.routes || []);
      updateCatalogSource(data.source || "");
    } catch (error) {
      updateCatalogSource("");
    }
  }

  function scheduleCatalogFetch(extraParams) {
    if (catalogTimer) {
      clearTimeout(catalogTimer);
    }
    catalogTimer = window.setTimeout(() => {
      fetchCatalog(extraParams);
    }, 220);
  }

  function renderEvidence(items) {
    evidenceList.innerHTML = "";
    if (!Array.isArray(items) || !items.length) {
      const fallback = document.createElement("li");
      fallback.textContent = "No external evidence snippet returned for this scenario.";
      evidenceList.appendChild(fallback);
      return;
    }

    items.slice(0, 4).forEach((item) => {
      const li = document.createElement("li");
      const title = item.title || "Evidence item";
      const snippet = item.snippet || "";
      const uri = item.uri || "";

      if (uri) {
        const link = document.createElement("a");
        link.href = uri;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = title;
        li.appendChild(link);
      } else {
        const heading = document.createElement("strong");
        heading.textContent = title;
        li.appendChild(heading);
      }

      if (snippet) {
        const text = document.createElement("p");
        text.textContent = snippet;
        text.style.margin = "6px 0 0";
        li.appendChild(text);
      }
      evidenceList.appendChild(li);
    });
  }

  function renderAssets(items) {
    assetTableBody.innerHTML = "";
    if (!Array.isArray(items) || !items.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 4;
      cell.textContent = "No impacted asset rows were returned for this scenario.";
      row.appendChild(cell);
      assetTableBody.appendChild(row);
      return;
    }

    items.slice(0, 12).forEach((asset) => {
      const row = document.createElement("tr");
      [
        asset.product_sku || "-",
        asset.route_id || "-",
        asset.supplier_name || "-",
        asset.port_name || "-",
      ].forEach((value) => {
        const cell = document.createElement("td");
        cell.textContent = value;
        row.appendChild(cell);
      });
      assetTableBody.appendChild(row);
    });
  }

  function renderScope(data) {
    const scenarioInputs = (data && data.raw_context && data.raw_context.scenario_inputs) || {};
    const payload = lastPayload || {};

    const target =
      data.event_target ||
      scenarioInputs.location ||
      scenarioInputs.supplier_name ||
      payload.location ||
      payload.supplier_name ||
      "Custom asset scope";

    const skuCount = Array.isArray(scenarioInputs.product_skus)
      ? scenarioInputs.product_skus.length
      : selectedSkus.length;
    const routeCount = Array.isArray(scenarioInputs.route_ids)
      ? scenarioInputs.route_ids.length
      : selectedRoutes.length;

    const fragments = [];
    if (skuCount) fragments.push(`${skuCount} SKU${skuCount === 1 ? "" : "s"}`);
    if (routeCount) fragments.push(`${routeCount} route${routeCount === 1 ? "" : "s"}`);
    if (scenarioInputs.horizon_days || payload.horizon_days) {
      fragments.push(`${scenarioInputs.horizon_days || payload.horizon_days} day horizon`);
    }

    metaTarget.textContent = target;
    metaScope.textContent = fragments.length ? fragments.join(" • ") : "Network-wide default scope";
  }

  function payloadFromForm() {
    const targetType = new FormData(form).get("target_type");
    const payload = {
      event_type: eventTypeInput.value,
      product_skus: [...selectedSkus],
      route_ids: [...selectedRoutes],
    };

    if (targetType === "supplier") {
      payload.supplier_name = supplierInput.value.trim();
    } else {
      payload.location = locationInput.value.trim();
    }

    const horizonValue = Number.parseInt(horizonInput.value, 10);
    if (Number.isFinite(horizonValue) && horizonValue > 0) {
      payload.horizon_days = horizonValue;
    }

    const priority = priorityInput.value.trim();
    if (priority) {
      payload.business_priority = priority;
    }

    const note = contextInput.value.trim();
    if (note) {
      payload.context_note = note;
    }

    return payload;
  }

  function isValidPayload(payload) {
    return Boolean(
      payload.location ||
      payload.supplier_name ||
      (Array.isArray(payload.product_skus) && payload.product_skus.length) ||
      (Array.isArray(payload.route_ids) && payload.route_ids.length)
    );
  }

  async function runScenario(event) {
    event.preventDefault();
    commitTokenInput("sku");
    commitTokenInput("route");

    const payload = payloadFromForm();
    lastPayload = payload;

    if (!isValidPayload(payload)) {
      showState(errorState);
      errorText.textContent = "Choose a location, supplier, SKU, or route before running the scenario.";
      return;
    }

    if (abortController) {
      abortController.abort();
    }
    abortController = new AbortController();

    runButton.disabled = true;
    showState(loadingState);
    startLoadingMessages();

    try {
      const response = await fetch("/experience/simulate/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
        signal: abortController.signal,
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || data.message || "Scenario run failed.");
      }

      resultTitle.textContent = data.summary_description || "Scenario Complete";
      resultImpact.textContent = data.impact_analysis || "No impact details returned.";
      resultAction.textContent = data.recommended_action || "No action recommendation returned.";
      metricRisk.textContent = formatPercent(data.risk_score);
      metricConfidence.textContent = formatPercent(data.confidence_score);
      metricDelay.textContent = Number.isFinite(data.estimated_delay_days)
        ? `${data.estimated_delay_days.toFixed(1)} days`
        : "Unknown";
      metricCost.textContent = formatMoney(data.estimated_cost_impact_usd);

      renderScope(data);
      renderAssets(data.raw_context && data.raw_context.impacted_assets ? data.raw_context.impacted_assets : []);
      renderEvidence(data.evidence_summary || []);

      showState(contentState);
    } catch (err) {
      if (err.name === "AbortError") return;
      showState(errorState);
      errorText.textContent = err.message || "Unexpected error while running this scenario.";
    } finally {
      runButton.disabled = false;
      stopLoadingMessages();
    }
  }

  form.addEventListener("submit", runScenario);
  form.addEventListener("change", (event) => {
    if (event.target.name === "target_type") {
      toggleTargetInputs();
      scheduleCatalogFetch();
    }
  });

  skuAddButton.addEventListener("click", () => commitTokenInput("sku"));
  routeAddButton.addEventListener("click", () => commitTokenInput("route"));

  [
    { input: skuEntry, kind: "sku" },
    { input: routeEntry, kind: "route" },
  ].forEach(({ input, kind }) => {
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === ",") {
        event.preventDefault();
        commitTokenInput(kind);
      }
    });
    input.addEventListener("blur", () => {
      if (input.value.trim()) {
        commitTokenInput(kind);
      }
    });
    input.addEventListener("input", () => {
      scheduleCatalogFetch({ q: input.value.trim() });
    });
  });

  [locationInput, supplierInput].forEach((input) => {
    input.addEventListener("input", () => scheduleCatalogFetch({ q: input.value.trim() }));
    input.addEventListener("focus", () => scheduleCatalogFetch({ q: input.value.trim() }));
  });

  const revealItems = document.querySelectorAll("[data-reveal]");
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.14 }
  );
  revealItems.forEach((item) => observer.observe(item));

  renderTokenChips(selectedSkus, skuChipContainer, "SKUs");
  renderTokenChips(selectedRoutes, routeChipContainer, "Routes");
  toggleTargetInputs();
  fetchCatalog();
})();
