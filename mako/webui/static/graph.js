// HestiaHealth knowledge-graph viewer — vanilla JS + Cytoscape.js, vendored
// locally at vendor/cytoscape.min.js (not a CDN — this stays same-origin
// and offline like the rest of the console, and one less thing that can
// fail mid-recording). This page is a presentation/explainer aid, not
// clinical software; it's not part of the offline-required, judged model
// runtime, but there's no reason it shouldn't work offline too.
//
// Two-level view because the raw graph (303 nodes / 529 edges across the
// Cytoscape-JSON dump) is unreadable as one hairball:
//   - Overview: 12 domain nodes, sized by agent count, connected by
//     aggregated cross-domain handoff counts.
//   - Detail: one domain's actual agents + the handoffs between them.

const DOMAIN_COLORS = {
  Cardiology: "#c0392b", EmergencyMedicine: "#d35400", LabPathology: "#8e44ad",
  Neurology: "#2980b9", Oncology: "#16a085", Orthopedics: "#7f8c8d",
  Pediatrics: "#27ae60", Pharmacy: "#f39c12", PrimaryCare: "#0e6e63",
  Psychiatry: "#8e44ad", Radiology: "#2c3e50", Surgery: "#c0392b",
};
const PREDICATE_VERBS = {
  delegatesTo: "delegates to", consults: "consults",
  escalatesTo: "escalates to", refersTo: "refers to", returnsTo: "returns case to",
};

let graphData = null;   // raw /api/kg/graph payload
let agents = {};        // id -> node.data
let handoffs = [];       // node.data for every Handoff node
let cy = null;
let currentDomain = null; // null = overview

async function boot() {
  graphData = await fetch("/api/kg/graph").then((r) => r.json());
  for (const n of graphData.nodes) {
    if (n.data.type === "Agent") agents[n.data.id] = n.data;
    if (n.data.type === "Handoff") handoffs.push(n.data);
  }
  document.getElementById("btn-overview").addEventListener("click", showOverview);
  document.getElementById("btn-all-agents").addEventListener("click", showAllAgents);
  showOverview();
}

function domainList() {
  const set = new Set(Object.values(agents).map((a) => a.domain));
  return [...set].sort();
}

function agentsInDomain(domain) {
  return Object.values(agents).filter((a) => a.domain === domain);
}

function shortLabel(agent) {
  // "Cardiology TreatmentPlanning" -> "TreatmentPlanning"
  return agent.label.replace(new RegExp("^" + agent.domain + "\\s*"), "");
}

function setActiveNav(id) {
  ["btn-overview", "btn-all-agents"].forEach((btnId) => {
    document.getElementById(btnId).classList.toggle("active", btnId === id);
  });
}

// ---------------------------------------------------------------- overview

function showOverview() {
  currentDomain = null;
  setActiveNav("btn-overview");
  document.getElementById("view-hint").textContent =
    "12 clinical domains, 71 agents, 135 possible handoffs — this is the graph MAKO's orchestrator reasons over at every routing decision. Click a domain to see its agents and handoffs.";
  document.getElementById("detail-title").textContent = "Select a node";
  document.getElementById("detail-body").innerHTML = '<p class="hint">Click any domain to see its agents here.</p>';

  const domains = domainList();
  const counts = {};
  domains.forEach((d) => (counts[d] = agentsInDomain(d).length));

  // Aggregate cross-domain handoff counts into weighted domain-pair edges.
  const pairCounts = {};
  for (const h of handoffs) {
    const fromDom = agents[h.from] && agents[h.from].domain;
    const toDom = agents[h.to] && agents[h.to].domain;
    if (!fromDom || !toDom || fromDom === toDom) continue;
    const key = [fromDom, toDom].sort().join("|");
    pairCounts[key] = (pairCounts[key] || 0) + 1;
  }

  const elements = [
    ...domains.map((d) => ({
      data: { id: "d:" + d, label: d, count: counts[d] },
      classes: "domain-node",
    })),
    ...Object.entries(pairCounts).map(([key, weight], i) => {
      const [a, b] = key.split("|");
      return { data: { id: "pe" + i, source: "d:" + a, target: "d:" + b, weight } };
    }),
  ];

  renderCy(elements, {
    nodeStyle: {
      "background-color": (n) => DOMAIN_COLORS[n.data("label")] || "#0e6e63",
      "width": (n) => 34 + n.data("count") * 3,
      "height": (n) => 34 + n.data("count") * 3,
      "label": "data(label)",
      "font-size": 11,
      "text-valign": "bottom",
      "text-margin-y": 6,
    },
    edgeStyle: {
      "width": (e) => 1 + Math.min(e.data("weight"), 8),
      "line-color": "#c7d0ce",
      "curve-style": "bezier",
      "opacity": 0.6,
    },
    layout: { name: "cose", idealEdgeLength: 120, nodeRepulsion: 9000, animate: false },
  });

  cy.on("tap", "node", (evt) => showDomainDetail(evt.target.data("label")));
  renderLegend(domains);
}

// ------------------------------------------------------------ domain detail

function showDomainDetail(domain) {
  currentDomain = domain;
  setActiveNav("btn-overview");
  document.getElementById("view-hint").textContent =
    `${domain} — ${agentsInDomain(domain).length} agents. Click an agent to see its capabilities, tools, and handoffs.`;

  const domAgents = agentsInDomain(domain);
  const withinHandoffs = handoffs.filter(
    (h) => agents[h.from] && agents[h.from].domain === domain &&
           agents[h.to] && agents[h.to].domain === domain
  );
  const crossOut = handoffs.filter(
    (h) => agents[h.from] && agents[h.from].domain === domain &&
           agents[h.to] && agents[h.to].domain !== domain
  );
  const crossIn = handoffs.filter(
    (h) => agents[h.to] && agents[h.to].domain === domain &&
           agents[h.from] && agents[h.from].domain !== domain
  );

  const elements = [
    ...domAgents.map((a) => ({
      data: { id: a.id, label: shortLabel(a) },
      classes: "agent-node",
    })),
    ...withinHandoffs.map((h, i) => ({
      data: {
        id: "h" + i, source: h.from, target: h.to,
        label: PREDICATE_VERBS[h.predicate] || h.predicate,
      },
    })),
  ];

  renderCy(elements, {
    nodeStyle: {
      "background-color": DOMAIN_COLORS[domain] || "#0e6e63",
      "width": 46, "height": 46,
      "label": "data(label)",
      "font-size": 10,
      "text-valign": "bottom",
      "text-margin-y": 6,
      "text-wrap": "wrap",
      "text-max-width": 70,
    },
    edgeStyle: {
      "width": 2,
      "line-color": "#0e6e63",
      "target-arrow-color": "#0e6e63",
      "target-arrow-shape": "triangle",
      "curve-style": "bezier",
      "opacity": 0.55,
      "label": "data(label)",
      "font-size": 8,
      "color": "#4b5a57",
      "text-background-color": "#f4f6f5",
      "text-background-opacity": 1,
      "text-background-padding": 2,
    },
    layout: { name: "cose", idealEdgeLength: 110, nodeRepulsion: 6000, animate: false },
  });

  cy.on("tap", "node", (evt) => showAgentDetail(agents[evt.target.id()]));

  renderDomainSidebar(domain, domAgents, crossOut, crossIn);
  renderLegend([domain]);
}

function renderDomainSidebar(domain, domAgents, crossOut, crossIn) {
  document.getElementById("detail-title").textContent = domain;
  const body = document.getElementById("detail-body");
  let html = `<p class="hint">${domAgents.length} agents in this domain. Click one (in the list or the graph) for its full detail.</p>`;
  html += domAgents.map((a) => `
    <div class="detail-agent" data-agent="${a.id}">
      <div class="detail-agent-name">${shortLabel(a)}</div>
      <div class="detail-agent-caps">${(a.capabilities || []).map((c) => c.replace(/^cap_/, "")).join(", ") || "no capabilities listed"}</div>
    </div>
  `).join("");

  if (crossOut.length) {
    html += `<h2 class="panel-title" style="margin-top:16px">Refers out to</h2>`;
    html += crossOut.map((h) => `
      <div class="detail-handoff">
        <span class="predicate-tag">${PREDICATE_VERBS[h.predicate] || h.predicate}</span><br/>
        ${shortLabel(agents[h.from])} &rarr; <b>${h.toLabel}</b>
      </div>
    `).join("");
  }
  if (crossIn.length) {
    html += `<h2 class="panel-title" style="margin-top:16px">Receives from</h2>`;
    html += crossIn.map((h) => `
      <div class="detail-handoff">
        <span class="predicate-tag">${PREDICATE_VERBS[h.predicate] || h.predicate}</span><br/>
        ${h.fromLabel} &rarr; <b>${shortLabel(agents[h.to])}</b>
      </div>
    `).join("");
  }
  body.innerHTML = html;
  body.querySelectorAll(".detail-agent").forEach((el) => {
    el.addEventListener("click", () => {
      showAgentDetail(agents[el.dataset.agent]);
      cy.$id(el.dataset.agent).select();
    });
  });
}

// ---------------------------------------------------------- all agents

function showAllAgents() {
  currentDomain = null;
  setActiveNav("btn-all-agents");
  document.getElementById("view-hint").textContent =
    "All 71 agents at once, colour-coded by domain, with every handoff edge — cross-domain handoffs (referrals, escalations) are dashed, within-domain ones solid. Click any agent for its detail.";
  document.getElementById("detail-title").textContent = "All agents";

  const domains = domainList();
  const all = Object.values(agents);

  const elements = [
    ...all.map((a) => ({
      data: { id: a.id, label: shortLabel(a), domain: a.domain },
    })),
    ...handoffs.map((h, i) => ({
      data: {
        id: "h" + i, source: h.from, target: h.to,
        cross: agents[h.from] && agents[h.to] && agents[h.from].domain !== agents[h.to].domain,
      },
    })),
  ];

  renderCy(elements, {
    nodeStyle: {
      "background-color": (n) => DOMAIN_COLORS[n.data("domain")] || "#0e6e63",
      "width": 22, "height": 22,
      "label": "data(label)",
      "font-size": 7.5,
      "text-valign": "bottom",
      "text-margin-y": 4,
      "text-wrap": "wrap",
      "text-max-width": 55,
    },
    edgeStyle: {
      "width": 1.3,
      "line-color": (e) => (e.data("cross") ? "#c0392b" : "#0e6e63"),
      "line-style": (e) => (e.data("cross") ? "dashed" : "solid"),
      "curve-style": "bezier",
      "opacity": (e) => (e.data("cross") ? 0.35 : 0.45),
      "target-arrow-shape": "triangle",
      "target-arrow-color": (e) => (e.data("cross") ? "#c0392b" : "#0e6e63"),
      "arrow-scale": 0.6,
    },
    layout: { name: "cose", idealEdgeLength: 55, nodeRepulsion: 3200, animate: false, numIter: 2000 },
  });

  cy.on("tap", "node", (evt) => {
    showAgentDetail(agents[evt.target.id()]);
  });

  renderAllAgentsSidebar(domains);
  renderLegend(domains);
}

function renderAllAgentsSidebar(domains) {
  const body = document.getElementById("detail-body");
  body.innerHTML = domains.map((d) => {
    const list = agentsInDomain(d);
    return `
      <h2 class="panel-title" style="margin-top:12px">${d} (${list.length})</h2>
      ${list.map((a) => `<div class="detail-agent" data-agent="${a.id}"><div class="detail-agent-name">${shortLabel(a)}</div></div>`).join("")}
    `;
  }).join("");
  body.querySelectorAll(".detail-agent").forEach((el) => {
    el.addEventListener("click", () => {
      showAgentDetail(agents[el.dataset.agent]);
      cy.$id(el.dataset.agent).select();
      cy.animate({ center: { eles: cy.$id(el.dataset.agent) } }, { duration: 200 });
    });
  });
}

function showAgentDetail(agent) {
  if (!agent) return;
  document.getElementById("detail-title").textContent = shortLabel(agent);
  const outEdges = handoffs.filter((h) => h.from === agent.id);
  const inEdges = handoffs.filter((h) => h.to === agent.id);
  let html = `<p class="hint">${agent.domain}</p>`;
  html += `<h2 class="panel-title" style="margin-top:10px">Capabilities</h2>`;
  html += `<p class="hint">${(agent.capabilities || []).map((c) => c.replace(/^cap_/, "")).join(", ") || "none"}</p>`;
  html += `<h2 class="panel-title" style="margin-top:10px">Tools</h2>`;
  html += `<p class="hint">${(agent.tools || []).map((t) => t.replace(/^tool_/, "")).join(", ") || "none"}</p>`;
  if (outEdges.length) {
    html += `<h2 class="panel-title" style="margin-top:10px">Can hand off to</h2>`;
    html += outEdges.map((h) => `<div class="detail-handoff"><span class="predicate-tag">${PREDICATE_VERBS[h.predicate] || h.predicate}</span><br/>${h.toLabel}</div>`).join("");
  }
  if (inEdges.length) {
    html += `<h2 class="panel-title" style="margin-top:10px">Receives from</h2>`;
    html += inEdges.map((h) => `<div class="detail-handoff"><span class="predicate-tag">${PREDICATE_VERBS[h.predicate] || h.predicate}</span><br/>${h.fromLabel}</div>`).join("");
  }
  if (!outEdges.length && !inEdges.length) {
    html += `<p class="hint" style="margin-top:10px">No handoffs in either direction — a terminal agent in this pathway.</p>`;
  }
  document.getElementById("detail-body").innerHTML = html;
}

// -------------------------------------------------------------- rendering

function renderCy(elements, { nodeStyle, edgeStyle, layout }) {
  if (cy) cy.destroy();
  cy = cytoscape({
    container: document.getElementById("cy"),
    elements,
    style: [
      { selector: "node", style: nodeStyle },
      { selector: "edge", style: edgeStyle },
      { selector: "node:selected", style: { "border-width": 3, "border-color": "#0e6e63" } },
    ],
    layout,
    wheelSensitivity: 0.25,
  });
}

function renderLegend(domains) {
  const el = document.getElementById("legend");
  el.innerHTML = domains.map((d) => `
    <span class="legend-item">
      <span class="legend-dot" style="background:${DOMAIN_COLORS[d] || "#0e6e63"}"></span>${d}
    </span>
  `).join("");
}

boot();
