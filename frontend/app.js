/**
 * CF Compare v2 — Frontend JavaScript (with authentication)
 * Auth flow: login/register → store JWT in localStorage → attach to every API call.
 */

const API = "/api";
let currentComparisonId = null;
let ratingChartInstance = null;

/* ═══════════════════════════════════════════════════════
   AUTH
   ═══════════════════════════════════════════════════════ */

function getToken() {
    return localStorage.getItem("cf_token");
}

function setToken(tok) {
    localStorage.setItem("cf_token", tok);
}

function clearToken() {
    localStorage.removeItem("cf_token");
}

/** Attach Authorization header to fetch via a wrapper. */
async function authFetch(url, options = {}) {
    const token = getToken();
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(url, { ...options, headers });
    if (res.status === 401) {
        clearToken();
        showAuthScreen();
        throw new Error("Session expired. Please login again.");
    }
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `Request failed (${res.status})`);
    }
    return res;
}

function showAuthScreen() {
    document.getElementById("auth-screen").classList.remove("hidden");
    document.getElementById("app-screen").classList.add("hidden");
}

function showAppScreen(username) {
    document.getElementById("auth-screen").classList.add("hidden");
    document.getElementById("app-screen").classList.remove("hidden");
    document.getElementById("user-display").textContent = `👤 ${username}`;
}

/* ── Login ──────────────────────────────────────────── */

async function handleLogin(e) {
    e.preventDefault();
    const username = document.getElementById("login-user").value.trim();
    const password = document.getElementById("login-pass").value;
    const errEl = document.getElementById("login-error");
    errEl.classList.add("hidden");

    try {
        const res = await fetch(`${API}/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password }),
        });
        if (!res.ok) { const d = await res.json(); throw new Error(d.detail || "Login failed"); }
        const data = await res.json();
        setToken(data.access_token);
        showAppScreen(data.username);
    } catch (err) {
        errEl.textContent = err.message;
        errEl.classList.remove("hidden");
    }
}

/* ── Register ───────────────────────────────────────── */

async function handleRegister(e) {
    e.preventDefault();
    const username = document.getElementById("reg-user").value.trim();
    const password = document.getElementById("reg-pass").value;
    const errEl = document.getElementById("reg-error");
    errEl.classList.add("hidden");

    try {
        const res = await fetch(`${API}/auth/register`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password }),
        });
        if (!res.ok) { const d = await res.json(); throw new Error(d.detail || "Registration failed"); }
        const data = await res.json();
        setToken(data.access_token);
        showAppScreen(data.username);
    } catch (err) {
        errEl.textContent = err.message;
        errEl.classList.remove("hidden");
    }
}

function logout() {
    clearToken();
    showAuthScreen();
    showLogin();
}

function showLogin() {
    document.getElementById("login-form").classList.remove("hidden");
    document.getElementById("register-form").classList.add("hidden");
}

function showRegister() {
    document.getElementById("login-form").classList.add("hidden");
    document.getElementById("register-form").classList.remove("hidden");
}

/* ── Auto-login on page load ────────────────────────── */

async function tryAutoLogin() {
    const token = getToken();
    if (!token) { showAuthScreen(); return; }
    try {
        const res = await fetch(`${API}/auth/me`, {
            headers: { "Authorization": `Bearer ${token}` },
        });
        if (!res.ok) throw new Error();
        const data = await res.json();
        showAppScreen(data.username);
    } catch {
        clearToken();
        showAuthScreen();
    }
}

/* ═══════════════════════════════════════════════════════
   TABS
   ═══════════════════════════════════════════════════════ */

function switchTab(name) {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
    document.querySelector(`.tab[data-tab="${name}"]`).classList.add("active");
    document.getElementById(`tab-${name}`).classList.add("active");
    if (name === "history") loadHistory();
}

/* ═══════════════════════════════════════════════════════
   COMPARE
   ═══════════════════════════════════════════════════════ */

async function compareUsers() {
    const input = document.getElementById("handles-input").value.trim();
    if (!input) { showError("Please enter at least 2 handles."); return; }

    const handleList = input.split(",").map(h => h.trim()).filter(h => h.length > 0);
    if (handleList.length < 2) { showError("Please enter at least 2 handles separated by commas."); return; }
    if (handleList.length > 5) { showError("Maximum 5 handles allowed."); return; }

    hideError(); hideResults(); showLoading();

    try {
        const res = await authFetch(`${API}/compare?handles=${encodeURIComponent(input)}`);
        const data = await res.json();

        hideLoading();
        currentComparisonId = data.comparison_id;

        if (!data.users || !Array.isArray(data.users)) {
            showError("Unexpected server response.");
            return;
        }

        displayResults(data.users);
        drawRatingChart(data.users);
        drawTagCharts(data.users);

        const sb = document.getElementById("summary-bar");
        document.getElementById("summary-text").textContent =
            data.cached ? "📦 Cached result (DB)" : "🔄 Fresh data from Codeforces";
        sb.classList.remove("hidden");

        document.getElementById("insight-box").classList.add("hidden");
        document.getElementById("insight-box").innerHTML = "";
        showResults();
    } catch (err) { hideLoading(); showError(err.message); }
}

/* ═══════════════════════════════════════════════════════
   TABLE
   ═══════════════════════════════════════════════════════ */

function displayResults(users) {
    const thead = document.querySelector("#comparison-table thead tr");
    const tbody = document.querySelector("#comparison-table tbody");
    thead.innerHTML = "<th>Metric</th>";
    tbody.innerHTML = "";

    users.forEach(u => {
        const th = document.createElement("th");
        th.textContent = u.handle + (u.found === false ? " ❌" : "");
        thead.appendChild(th);
    });

    const metrics = [
        { key: "rating", label: "Current Rating" },
        { key: "rank", label: "Current Rank" },
        { key: "max_rating", label: "Max Rating" },
        { key: "max_rank", label: "Max Rank" },
        { key: "solved_count", label: "Solved Problems" },
    ];

    metrics.forEach(m => {
        const tr = document.createElement("tr");
        const tdL = document.createElement("td");
        tdL.textContent = m.label;
        tr.appendChild(tdL);

        const vals = users.map(u => u.found !== false ? (u[m.key] ?? -1) : -1);
        const best = Math.max(...vals.filter(v => v >= 0));

        users.forEach(u => {
            const td = document.createElement("td");
            if (u.found === false) { td.textContent = "N/A"; td.style.color = "#e74c3c"; }
            else {
                const v = u[m.key];
                td.textContent = v !== null && v !== undefined ? v : "N/A";
                if (v === best && best > 0) td.classList.add("best-value");
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

/* ═══════════════════════════════════════════════════════
   CHARTS
   ═══════════════════════════════════════════════════════ */

function drawRatingChart(users) {
    if (ratingChartInstance) { ratingChartInstance.destroy(); ratingChartInstance = null; }

    const ctx = document.getElementById("rating-chart").getContext("2d");
    const colors = ["#667eea", "#2ed573", "#ffd200", "#ff6b81", "#70a1ff"];

    const datasets = users
        .filter(u => u.found !== false && u.rating_history && u.rating_history.length > 0)
        .map((u, i) => ({
            label: u.handle,
            data: u.rating_history.map((_, idx) => ({ x: idx + 1, y: u.rating_history[idx].new_rating })),
            borderColor: colors[i % colors.length],
            backgroundColor: "transparent",
            tension: 0.25,
            pointRadius: 0,
            borderWidth: 2,
        }));

    if (datasets.length === 0) {
        document.getElementById("rating-chart").parentElement.innerHTML =
            "<p style='color:#888;'>No rating history available.</p>";
        return;
    }

    ratingChartInstance = new Chart(ctx, {
        type: "line",
        data: { datasets },
        options: {
            responsive: true,
            scales: {
                x: { type: "linear", title: { display: true, text: "Contest #" }, ticks: { color: "#aaa" } },
                y: { title: { display: true, text: "Rating" }, ticks: { color: "#aaa" } },
            },
            plugins: {
                legend: { labels: { color: "#ccc" } },
                tooltip: {
                    callbacks: {
                        title: items => `Contest #${items[0].parsed.x}`,
                        label: item => `${item.dataset.label}: ${item.parsed.y}`,
                    }
                }
            },
        },
    });
}

function drawTagCharts(users) {
    const container = document.getElementById("tag-charts");
    container.innerHTML = "";
    const palette = ["#667eea", "#2ed573", "#ffd200", "#ff6b81", "#70a1ff"];
    const validUsers = users.filter(u => u.found !== false && u.tag_stats && Object.keys(u.tag_stats).length > 0);

    if (validUsers.length === 0) {
        container.innerHTML = "<p style='color:#888;'>No tag data available.</p>";
        return;
    }

    validUsers.forEach((u, idx) => {
        const card = document.createElement("div");
        card.className = "tag-card";
        const h3 = document.createElement("h3");
        h3.textContent = u.handle;
        card.appendChild(h3);
        const canvas = document.createElement("canvas");
        canvas.id = `tag-canvas-${idx}`;
        canvas.height = 220;
        card.appendChild(canvas);
        container.appendChild(card);

        const entries = Object.entries(u.tag_stats).sort((a, b) => b[1] - a[1]).slice(0, 8);
        new Chart(canvas.getContext("2d"), {
            type: "bar",
            data: {
                labels: entries.map(e => e[0]),
                datasets: [{
                    data: entries.map(e => e[1]),
                    backgroundColor: palette[idx % palette.length] + "99",
                    borderColor: palette[idx % palette.length],
                    borderWidth: 1,
                }],
            },
            options: {
                indexAxis: "y", responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { color: "#aaa" }, grid: { color: "rgba(255,255,255,.06)" } },
                    y: { ticks: { color: "#ccc" } },
                },
            },
        });
    });
}

/* ═══════════════════════════════════════════════════════
   INSIGHT
   ═══════════════════════════════════════════════════════ */

async function generateInsight() {
    if (!currentComparisonId) return;
    const box = document.getElementById("insight-box");
    box.innerHTML = "⏳ Generating insight…";
    box.classList.remove("hidden");
    try {
        const res = await authFetch(`${API}/comparison/${currentComparisonId}/insight`);
        const data = await res.json();
        box.textContent = data.content;
    } catch { box.textContent = "⚠️ Could not generate insight."; }
}

/* ═══════════════════════════════════════════════════════
   HISTORY
   ═══════════════════════════════════════════════════════ */

async function loadHistory() {
    const listEl = document.getElementById("history-list");
    const loadEl = document.getElementById("history-loading");
    listEl.innerHTML = "";
    loadEl.classList.remove("hidden");

    try {
        const res = await authFetch(`${API}/history?limit=20`);
        const data = await res.json();
        loadEl.classList.add("hidden");

        if (data.length === 0) {
            listEl.innerHTML = "<p style='color:#888;text-align:center;'>No comparisons yet.</p>";
            return;
        }

        data.forEach(entry => {
            const div = document.createElement("div");
            div.className = "history-item";
            div.innerHTML = `
                <div class="history-info">
                    <div class="handles">${entry.handles}</div>
                    <div class="date">${new Date(entry.created_at).toLocaleString()} · ${entry.users.length} users</div>
                </div>
                <button class="history-load" onclick="loadComparison(${entry.id})">Load</button>
            `;
            listEl.appendChild(div);
        });
    } catch (err) {
        loadEl.classList.add("hidden");
        listEl.innerHTML = `<p style='color:#e74c3c;'>${err.message}</p>`;
    }
}

async function loadComparison(id) {
    showLoading(); hideResults(); hideError();
    switchTab("compare");
    try {
        const res = await authFetch(`${API}/comparison/${id}`);
        const data = await res.json();
        currentComparisonId = data.id;
        displayResults(data.users);
        drawRatingChart(data.users);
        drawTagCharts(data.users);

        const box = document.getElementById("insight-box");
        if (data.insight) { box.textContent = data.insight; box.classList.remove("hidden"); }
        else { box.classList.add("hidden"); box.innerHTML = ""; }

        document.getElementById("summary-text").textContent = "📦 Loaded from history";
        document.getElementById("summary-bar").classList.remove("hidden");
        hideLoading(); showResults();
    } catch (err) { hideLoading(); showError(err.message); }
}

/* ═══════════════════════════════════════════════════════
   HELPERS
   ═══════════════════════════════════════════════════════ */

function showLoading()   { document.getElementById("loading").classList.remove("hidden"); }
function hideLoading()   { document.getElementById("loading").classList.add("hidden"); }
function showResults()   { document.getElementById("results-container").classList.remove("hidden"); }
function hideResults()   { document.getElementById("results-container").classList.add("hidden"); }
function showError(msg)  { const d = document.getElementById("error-message"); d.textContent = msg; d.classList.remove("hidden"); }
function hideError()     { document.getElementById("error-message").classList.add("hidden"); }

/* ═══════════════════════════════════════════════════════
   INIT
   ═══════════════════════════════════════════════════════ */

document.addEventListener("DOMContentLoaded", () => {
    tryAutoLogin();
    document.getElementById("handles-input").addEventListener("keypress", e => {
        if (e.key === "Enter") compareUsers();
    });
});
