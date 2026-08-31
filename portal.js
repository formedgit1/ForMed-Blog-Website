"use strict";

// Role portals. script.js calls Portal.render(user) after login and
// Portal.teardown() on logout; everything else lives here.
window.Portal = (function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  const state = { user: null, careers: null };

  const TABS = {
    student: [
      { id: "saved", label: "Saved Articles", render: renderSaved },
      { id: "activity", label: "Reading Activity", render: renderActivity },
    ],
    author: [
      { id: "articles", label: "My Articles", render: renderAuthorArticles },
      { id: "request", label: "Request Upload", render: renderRequestForm },
    ],
    admin: [
      { id: "students", label: "Students", render: renderStudents },
      { id: "requests", label: "Upload Requests", render: renderRequests },
    ],
  };

  // --- small helpers -------------------------------------------------

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  async function api(path, opts = {}) {
    let res;
    try {
      res = await fetch(path, opts);
    } catch (_) {
      return { ok: false, data: { ok: false, error: "Could not reach the server." } };
    }
    let data = {};
    try {
      data = JSON.parse(await res.text());
    } catch (_) {
      data = { ok: false, error: `Unexpected response (HTTP ${res.status}).` };
    }
    return { ok: res.ok, data };
  }

  function fmtDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    return isNaN(d) ? "—" : d.toLocaleDateString();
  }

  function fmtDay(ymd) {
    const d = new Date(ymd + "T00:00:00");
    return `${d.getMonth() + 1}/${d.getDate()}`;
  }

  function statusBadge(status) {
    const label = { pending: "Pending", published: "In Library", denied: "Denied" };
    return `<span class="status status-${status}">${label[status] || status}</span>`;
  }

  function flash(message, kind = "info") {
    const bar = $("#portal-flash");
    if (!bar) return;
    bar.className = "portal-flash " + kind;
    bar.textContent = message;
    bar.hidden = false;
    clearTimeout(flash._t);
    flash._t = setTimeout(() => { bar.hidden = true; }, 4500);
  }

  async function ensureCareers() {
    if (!state.careers) {
      const { data } = await api("/api/careers");
      state.careers = data.career_paths || [];
    }
    return state.careers;
  }

  // --- inline SVG line chart --------------------------------------

  function lineChart(series) {
    const W = 580, H = 220, pad = { t: 16, r: 18, b: 34, l: 34 };
    const iw = W - pad.l - pad.r;
    const ih = H - pad.t - pad.b;
    const n = series.length;
    const maxCount = Math.max(1, ...series.map((d) => d.count));
    const xAt = (i) => pad.l + (n <= 1 ? iw / 2 : (i / (n - 1)) * iw);
    const yAt = (c) => pad.t + ih - (c / maxCount) * ih;

    const steps = Math.min(maxCount, 4);
    let gridlines = "";
    for (let s = 0; s <= steps; s++) {
      const val = Math.round((maxCount / steps) * s);
      const y = yAt(val);
      gridlines +=
        `<line class="ch-grid" x1="${pad.l}" y1="${y}" x2="${W - pad.r}" y2="${y}"></line>` +
        `<text class="ch-axis" x="${pad.l - 6}" y="${y + 3}" text-anchor="end">${val}</text>`;
    }

    const labelIdx = n <= 1 ? [0] : [0, Math.floor((n - 1) / 2), n - 1];
    const xLabels = labelIdx
      .map((i) => `<text class="ch-axis" x="${xAt(i)}" y="${H - 12}" text-anchor="middle">${fmtDay(series[i].date)}</text>`)
      .join("");

    const points = series.map((d, i) => `${xAt(i)},${yAt(d.count)}`).join(" ");
    const dots = series
      .map((d, i) => `<circle class="ch-dot" cx="${xAt(i)}" cy="${yAt(d.count)}" r="3"></circle>`)
      .join("");

    return `<svg viewBox="0 0 ${W} ${H}" class="chart" role="img" aria-label="Articles read per day">
      ${gridlines}
      <polyline class="ch-series" fill="none" points="${points}"></polyline>
      ${dots}
      ${xLabels}
    </svg>`;
  }

  // --- student panels -------------------------------------------

  async function renderSaved(main) {
    const { data } = await api("/api/student/saved-articles");
    const articles = data.articles || [];

    if (!articles.length) {
      main.innerHTML = `<section class="panel"><h2>Saved Articles</h2>
        <p class="empty">no saved articles</p></section>`;
      return;
    }

    main.innerHTML = `<section class="panel">
      <h2>Saved Articles</h2>
      <div class="table-scroll"><table class="grid">
        <thead><tr>
          <th>Title</th><th>Career Path</th><th>Career</th><th>Author</th><th></th>
        </tr></thead>
        <tbody>${articles.map((a) => `<tr>
          <td>${esc(a.title)}</td>
          <td>${esc(a.career_path_name || "—")}</td>
          <td>${esc(a.career_name || "—")}</td>
          <td>${esc(a.author_name)}</td>
          <td><button class="btn-link" data-unsave="${a.id}">Remove</button></td>
        </tr>`).join("")}</tbody>
      </table></div>
    </section>`;

    main.querySelector("tbody").addEventListener("click", async (e) => {
      const btn = e.target.closest("[data-unsave]");
      if (!btn) return;
      await api(`/api/student/saved-articles/${btn.dataset.unsave}`, { method: "DELETE" });
      renderSaved(main);
    });
  }

  async function renderActivity(main) {
    const { data } = await api("/api/student/reading-activity?days=14");
    const activity = data.activity || [];
    const total = activity.reduce((sum, d) => sum + d.count, 0);

    main.innerHTML = `<section class="panel">
      <h2>Reading Activity</h2>
      <p class="muted">Articles read per day over the last 14 days &mdash; ${total} total.</p>
      <div class="chart-wrap">${lineChart(activity)}</div>
      ${total === 0 ? '<p class="empty">No reading activity yet.</p>' : ""}
    </section>`;
  }

  // --- author panels -------------------------------------------

  async function renderAuthorArticles(main) {
    const { data } = await api("/api/author/articles");
    const articles = data.articles || [];

    if (!articles.length) {
      main.innerHTML = `<section class="panel"><h2>My Articles</h2>
        <p class="empty">You haven't written any articles yet. Use the Request Upload tab to submit one.</p>
      </section>`;
      return;
    }

    main.innerHTML = `<section class="panel">
      <h2>My Articles</h2>
      <div class="table-scroll"><table class="grid">
        <thead><tr>
          <th>Title</th><th>Career Path</th><th>Career</th><th>Status</th><th>Submitted</th>
        </tr></thead>
        <tbody>${articles.map((a) => `<tr>
          <td>${esc(a.title)}</td>
          <td>${esc(a.career_path_name || "—")}</td>
          <td>${esc(a.career_name || "—")}</td>
          <td>${statusBadge(a.status)}</td>
          <td>${fmtDate(a.created_at)}</td>
        </tr>`).join("")}</tbody>
      </table></div>
    </section>`;
  }

  async function renderRequestForm(main) {
    const paths = await ensureCareers();

    main.innerHTML = `<section class="panel">
      <h2>Request an Article Upload</h2>
      <p class="muted">Your request is sent to the admin team for review before it enters the library.</p>
      <form id="request-form" class="stack">
        <label class="field"><span>Article name</span>
          <input type="text" name="title" required />
        </label>
        <label class="field"><span>Short description</span>
          <textarea name="description" rows="3" required></textarea>
        </label>
        <div class="row">
          <label class="field"><span>Career path</span>
            <select name="career_path" required>
              <option value="">Select a career path…</option>
              ${paths.map((p) => `<option value="${p.path_id}">${esc(p.path_name)}</option>`).join("")}
            </select>
          </label>
          <label class="field"><span>Career</span>
            <select name="career_id" required disabled>
              <option value="">Select a career path first…</option>
            </select>
          </label>
        </div>
        <label class="field"><span>File</span>
          <input type="file" name="file" accept=".pdf,.doc,.docx,.txt,.md,.rtf,.odt" required />
          <small>PDF, Word, text, or Markdown. 10 MB max.</small>
        </label>
        <button type="submit" class="submit">Submit Request</button>
      </form>
    </section>`;

    const form = $("#request-form", main);
    const careerSel = form.career_id;

    form.career_path.addEventListener("change", (e) => {
      const path = paths.find((p) => String(p.path_id) === e.target.value);
      careerSel.innerHTML = path
        ? '<option value="">Select a career…</option>' +
          path.careers.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")
        : '<option value="">Select a career path first…</option>';
      careerSel.disabled = !path;
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = new FormData(form);
      body.delete("career_path"); // server only needs career_id
      const submit = form.querySelector("button[type=submit]");
      submit.disabled = true;
      const { data } = await api("/api/author/article-requests", { method: "POST", body });
      submit.disabled = false;
      if (!data.ok) {
        flash(data.error || "Could not submit the request.", "error");
        return;
      }
      form.reset();
      careerSel.disabled = true;
      flash("Upload request sent to the admin team.", "success");
    });
  }

  // --- admin panels -------------------------------------------

  async function renderStudents(main) {
    const { data } = await api("/api/admin/students");
    const students = data.students || [];

    if (!students.length) {
      main.innerHTML = `<section class="panel"><h2>Students</h2>
        <p class="empty">No students have signed up yet.</p></section>`;
      return;
    }

    main.innerHTML = `<section class="panel">
      <h2>Students</h2>
      <p class="muted">${students.length} student${students.length === 1 ? "" : "s"}. Select a row to view their portal.</p>
      <div class="table-scroll"><table class="grid rows-link">
        <thead><tr>
          <th>Name</th><th>Email</th><th>Phone</th><th>Joined</th><th>Saved</th><th>Reads</th>
        </tr></thead>
        <tbody>${students.map((s) => `<tr data-student="${s.id}">
          <td>${esc(s.last_name)}, ${esc(s.first_name)}</td>
          <td>${esc(s.email)}</td>
          <td>${esc(s.phone)}</td>
          <td>${fmtDate(s.created_at)}</td>
          <td>${s.saved_count}</td>
          <td>${s.reads_count}</td>
        </tr>`).join("")}</tbody>
      </table></div>
    </section>`;

    main.querySelector("tbody").addEventListener("click", (e) => {
      const row = e.target.closest("[data-student]");
      if (row) renderStudentDetail(main, row.dataset.student);
    });
  }

  async function renderStudentDetail(main, studentId) {
    const { data } = await api(`/api/admin/students/${studentId}`);
    if (!data.ok) {
      flash(data.error || "Could not load that student.", "error");
      return renderStudents(main);
    }

    const p = data.profile;
    const saved = data.saved_articles || [];
    const activity = data.reading_activity || [];
    const total = activity.reduce((sum, d) => sum + d.count, 0);

    main.innerHTML = `<section class="panel">
      <button class="btn-link back" id="back-to-students">&larr; Back to students</button>
      <h2>${esc(p.first_name)} ${esc(p.last_name)}</h2>
      <dl class="profile">
        <div><dt>Email</dt><dd>${esc(p.email)}</dd></div>
        <div><dt>Phone</dt><dd>${esc(p.phone)}</dd></div>
        <div><dt>Joined</dt><dd>${fmtDate(p.created_at)}</dd></div>
      </dl>

      <h3>Saved Articles</h3>
      ${saved.length
        ? `<div class="table-scroll"><table class="grid">
            <thead><tr><th>Title</th><th>Career Path</th><th>Career</th><th>Author</th></tr></thead>
            <tbody>${saved.map((a) => `<tr>
              <td>${esc(a.title)}</td>
              <td>${esc(a.career_path_name || "—")}</td>
              <td>${esc(a.career_name || "—")}</td>
              <td>${esc(a.author_name)}</td>
            </tr>`).join("")}</tbody>
          </table></div>`
        : '<p class="empty">no saved articles</p>'}

      <h3>Reading Activity</h3>
      <p class="muted">Last 14 days &mdash; ${total} total.</p>
      <div class="chart-wrap">${lineChart(activity)}</div>
    </section>`;

    $("#back-to-students", main).addEventListener("click", () => renderStudents(main));
  }

  async function renderRequests(main) {
    const { data } = await api("/api/admin/article-requests");
    const requests = data.requests || [];

    if (!requests.length) {
      main.innerHTML = `<section class="panel"><h2>Upload Requests</h2>
        <p class="empty">No pending upload requests.</p></section>`;
      return;
    }

    main.innerHTML = `<section class="panel">
      <h2>Upload Requests</h2>
      <p class="muted">${requests.length} awaiting review. Approving moves the article into the library.</p>
      <ul class="request-list">${requests.map((r) => `<li class="request">
        <div class="request-head">
          <strong>${esc(r.title)}</strong>
          <span class="muted">by ${esc(r.author_name)} &middot; ${fmtDate(r.created_at)}</span>
        </div>
        <p class="request-meta">${esc(r.career_path_name || "—")} &rsaquo; ${esc(r.career_name || "—")}</p>
        <p class="request-desc">${esc(r.description)}</p>
        <div class="request-actions">
          <a class="btn-link" href="/api/admin/article-requests/${r.id}/file">Download file${r.original_file_name ? " (" + esc(r.original_file_name) + ")" : ""}</a>
          <span class="spacer"></span>
          <button class="btn-approve" data-approve="${r.id}">Approve</button>
          <button class="btn-deny" data-deny="${r.id}">Deny</button>
        </div>
      </li>`).join("")}</ul>
    </section>`;

    main.querySelector(".request-list").addEventListener("click", async (e) => {
      const approve = e.target.closest("[data-approve]");
      const deny = e.target.closest("[data-deny]");
      if (!approve && !deny) return;
      const id = (approve || deny).dataset.approve || (approve || deny).dataset.deny;
      const action = approve ? "approve" : "deny";
      const { data: res } = await api(`/api/admin/article-requests/${id}/${action}`, { method: "POST" });
      if (!res.ok) {
        flash(res.error || "Could not update that request.", "error");
        return;
      }
      flash(approve ? "Approved and moved to the library." : "Request denied.", "success");
      renderRequests(main);
    });
  }

  // --- shell ----------------------------------------------------

  function setActiveTab(tabId) {
    const tabs = TABS[state.user.role];
    const tab = tabs.find((t) => t.id === tabId) || tabs[0];
    $$("#portal-tabs .ptab").forEach((b) =>
      b.classList.toggle("active", b.dataset.tab === tab.id));

    const main = $("#portal-main");
    main.innerHTML = '<p class="loading">Loading…</p>';
    Promise.resolve(tab.render(main)).catch((err) => {
      console.error(err);
      main.innerHTML = '<p class="empty">Something went wrong loading this tab.</p>';
    });
  }

  function render(user) {
    state.user = user;
    state.careers = null;

    $("#portal-who").textContent = `${user.first_name} ${user.last_name}`;
    const badge = $("#portal-role");
    badge.textContent = user.role;
    badge.className = "role-badge role-" + user.role;

    const tabsEl = $("#portal-tabs");
    tabsEl.innerHTML = TABS[user.role]
      .map((t) => `<button type="button" class="ptab" data-tab="${t.id}">${esc(t.label)}</button>`)
      .join("");
    tabsEl.onclick = (e) => {
      const btn = e.target.closest(".ptab");
      if (btn) setActiveTab(btn.dataset.tab);
    };

    if (!$("#portal-flash")) {
      const f = document.createElement("div");
      f.id = "portal-flash";
      f.className = "portal-flash";
      f.hidden = true;
      $("#portal-main").before(f);
    }

    setActiveTab(TABS[user.role][0].id);
  }

  function teardown() {
    $("#portal-tabs").innerHTML = "";
    $("#portal-main").innerHTML = "";
    state.user = null;
    state.careers = null;
  }

  return { render, teardown };
})();
