
const API = "/api";

const pageTitles = {
    dashboard: "System Dashboard",
    network: "Network Overview",
    incidents: "Past Incidents",
    logs: "System Logs"
};


// --------------------------------------------------
// GENERAL HELPERS
// --------------------------------------------------

function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, char => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
    })[char]);
}

function formatRuntime(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;

    return [h, m, s]
        .map(value => String(value).padStart(2, "0"))
        .join(":");
}

function formatDate(value) {
    if (!value) return "—";

    return new Date(value).toLocaleString();
}

function confidence(value) {
    if (value === null || value === undefined) return "—";
    return `${(value * 100).toFixed(1)}%`;
}


// --------------------------------------------------
// NAVIGATION
// --------------------------------------------------

function switchPage(pageName) {
    document.querySelectorAll(".page").forEach(page => {
        page.classList.remove("active");
    });

    document.querySelectorAll(".nav-item").forEach(button => {
        button.classList.remove("active");
    });

    const page = document.getElementById(`page-${pageName}`);
    const button = document.querySelector(
        `.nav-item[data-page="${pageName}"]`
    );

    if (page) page.classList.add("active");
    if (button) button.classList.add("active");

    document.getElementById("page-title").textContent =
        pageTitles[pageName];

    document.getElementById("current-section").textContent =
        pageName.replace("-", " ").toUpperCase();
}

document.querySelectorAll(".nav-item").forEach(button => {
    button.addEventListener("click", () => {
        switchPage(button.dataset.page);
    });
});


// --------------------------------------------------
// SUMMARY STATISTICS
// --------------------------------------------------

function renderSummary(summary) {
    document.getElementById("active-nodes").textContent =
        summary.active_nodes;

    document.getElementById("active-incidents").textContent =
        summary.active_incidents;

    document.getElementById("total-nodes").textContent =
        summary.total_nodes;

    document.getElementById("resolved-incidents").textContent =
        summary.resolved_incidents;

    document.getElementById("runtime").textContent =
        formatRuntime(summary.runtime);
}


// --------------------------------------------------
// NODE CARDS
// --------------------------------------------------

function renderNodes(nodes) {
    const container = document.getElementById("node-grid");

    container.innerHTML = nodes.map(node => {
        const online = node.status === "online";

        const status = online
            ? (node.demo ? "ONLINE · DEMO" : "ONLINE")
            : "PLACEHOLDER";

        const detection = node.detection === "warning"
            ? "WARNING"
            : "STANDBY";

        const detectionColor = node.detection === "warning"
            ? "var(--amber)"
            : "var(--green)";

        const cameraMessage = !online
            ? "Camera not installed"
            : node.camera_status === "demo"
                ? "Camera integration pending"
                : node.camera_status === "online"
                    ? "Camera connected"
                    : "Camera unavailable";

        const gasValue = node.gas_raw !== null
            ? escapeHTML(node.gas_raw)
            : "Awaiting telemetry";

        const detectionDetail = node.detection === "warning"
            ? `${escapeHTML(node.detection_class || "Detection")} · ${confidence(node.confidence)}`
            : "No active detection";

        return `
            <article class="node-card ${online ? "online" : "placeholder"}">

                <div class="node-header">
                    <h4>${escapeHTML(node.name)}</h4>
                    <span class="node-status ${online ? "online" : "placeholder"}">
                        ${status}
                    </span>
                </div>

                <div class="node-location">
                    ${escapeHTML(node.sector)} · ${escapeHTML(node.location)}
                </div>

                <div class="camera-box">
                    <span class="camera-label">
                        ${online ? "CAMERA 01" : "NO CAMERA"}
                    </span>
                    <div class="camera-icon">▣</div>
                    <span>${cameraMessage}</span>
                </div>

                <div class="node-metrics">

                    <div class="metric">
                        <div class="metric-label">YOLO DETECTION</div>
                        <div class="metric-value" style="color:${detectionColor}">
                            ${detection}
                        </div>
                        <div class="metric-subtitle">
                            ${detectionDetail}
                        </div>
                    </div>

                    <div class="metric">
                        <div class="metric-label">MQ-2 READING</div>
                        <div class="metric-value">${gasValue}</div>
                        <div class="metric-subtitle">
                            Raw ADC value
                        </div>
                    </div>

                </div>
            </article>
        `;
    }).join("");
}


// --------------------------------------------------
// NETWORK OVERVIEW
// --------------------------------------------------

function renderNetwork(nodes) {
    const container = document.getElementById("network-table");

    container.innerHTML = nodes.map(node => {
        const online = node.status === "online";

        return `
            <tr>
                <td><strong>${escapeHTML(node.name)}</strong></td>
                <td>${escapeHTML(node.sector)}</td>
                <td>${escapeHTML(node.location)}</td>

                <td>
                    <span class="table-status ${online ? "" : "planned"}">
                        ${online ? (node.demo ? "ONLINE · DEMO" : "ONLINE") : "PLANNED"}
                    </span>
                </td>

                <td>
                    ${escapeHTML(node.camera_status.toUpperCase())}
                </td>

                <td>
                    ${node.gas_raw === null
                        ? "—"
                        : escapeHTML(node.gas_raw)}
                </td>
            </tr>
        `;
    }).join("");
}


// --------------------------------------------------
// INCIDENT HISTORY
// --------------------------------------------------

function renderIncidents(incidents) {
    const container = document.getElementById("incident-table");

    if (incidents.length === 0) {
        container.innerHTML = `
            <tr>
                <td colspan="7" class="empty-row">
                    No incidents recorded.
                </td>
            </tr>
        `;
        return;
    }

    container.innerHTML = incidents.map(incident => {
        const active = incident.status === "active";

        return `
            <tr>
                <td>${formatDate(incident.time)}</td>
                <td>${escapeHTML(incident.node_name)}</td>
                <td>${escapeHTML(incident.sector)}</td>
                <td>${escapeHTML(incident.detection_class || "Unknown")}</td>
                <td>${confidence(incident.confidence)}</td>
                <td>${incident.gas_raw ?? "—"}</td>

                <td>
                    ${active
                        ? `<button class="resolve-button"
                             data-resolve="${incident.id}">
                             Mark resolved
                           </button>`
                        : `<span class="table-status planned">RESOLVED</span>`
                    }
                </td>
            </tr>
        `;
    }).join("");
}


// --------------------------------------------------
// SYSTEM LOGS
// --------------------------------------------------

function renderLogs(logs) {
    const container = document.getElementById("logs-list");

    container.className = "logs-list";

    if (logs.length === 0) {
        container.innerHTML = `
            <div class="empty-row">No system logs available.</div>
        `;
        return;
    }

    container.innerHTML = logs.map(log => `
        <div class="log-entry">
            <div class="log-time">${formatDate(log.time)}</div>
            <div class="log-level ${escapeHTML(log.level)}">
                ${escapeHTML(log.level)}
            </div>
            <div class="log-message">
                ${escapeHTML(log.message)}
                ${log.node_id
                    ? `<span style="color:var(--muted)">
                        · ${escapeHTML(log.node_id)}
                       </span>`
                    : ""}
            </div>
        </div>
    `).join("");
}


// --------------------------------------------------
// INCIDENT RESOLUTION
// --------------------------------------------------

document.addEventListener("click", async event => {
    const button = event.target.closest("[data-resolve]");

    if (!button) return;

    const incidentId = button.dataset.resolve;

    button.disabled = true;
    button.textContent = "Updating...";

    try {
        const response = await fetch(
            `${API}/incidents/${incidentId}/resolve`,
            { method: "POST" }
        );

        if (!response.ok) {
            throw new Error("Could not resolve incident");
        }

        await loadDashboard();

    } catch (error) {
        console.error(error);
        button.disabled = false;
        button.textContent = "Retry";
    }
});


// --------------------------------------------------
// SERVER CONNECTION AND DATA UPDATES
// --------------------------------------------------

async function loadDashboard() {
    try {
        const response = await fetch(`${API}/state`, {
            cache: "no-store"
        });

        if (!response.ok) {
            throw new Error("Server returned an error");
        }

        const data = await response.json();

        renderSummary(data.summary);
        renderNodes(data.nodes);
        renderNetwork(data.nodes);
        renderIncidents(data.incidents);
        renderLogs(data.logs);

        document.getElementById("server-status").textContent =
            "SERVER ONLINE";

        document.querySelector(
            ".connection-indicator .status-dot"
        ).className = "status-dot green";

    } catch (error) {
        console.error("Dashboard update failed:", error);

        document.getElementById("server-status").textContent =
            "SERVER OFFLINE";

        document.querySelector(
            ".connection-indicator .status-dot"
        ).className = "status-dot red-dot";
    }
}


// --------------------------------------------------
// CLOCK
// --------------------------------------------------

function updateClock() {
    document.getElementById("clock").textContent =
        new Date().toLocaleTimeString();
}


// --------------------------------------------------
// INITIALIZE
// --------------------------------------------------

updateClock();
loadDashboard();

setInterval(updateClock, 1000);
setInterval(loadDashboard, 1000);
