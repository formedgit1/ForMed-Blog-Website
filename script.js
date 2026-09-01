"use strict";

// Roles that must supply a security code to sign up or log in.
const SECURITY_ROLES = ["author", "admin"];

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

// --- Messaging ------------------------------------------------------------

function showMessage(text, kind = "error") {
  const el = $("#message");
  el.textContent = text;
  el.className = "message " + kind;
  el.hidden = false;
}

function clearMessage() {
  const el = $("#message");
  el.hidden = true;
  el.textContent = "";
}

// --- Form helpers -------------------------------------------------------

function selectedRole(view) {
  const checked = $(`input[name="${view}-role"]:checked`);
  return checked ? checked.value : "student";
}

// Show/hide the security-code input depending on the chosen role.
function syncCodeField(view) {
  const role = selectedRole(view);
  const needsCode = SECURITY_ROLES.includes(role);
  const field = $(`#${view}-code-field`);
  const input = $("input[name='security_code']", field);

  field.hidden = !needsCode;
  if (input) input.required = needsCode;

  if (view === "signup") {
    $("#signup-code-hint").textContent = needsCode
      ? `Required to register as ${role === "admin" ? "an admin" : "an author"}.`
      : "";
  }
}

function switchView(view) {
  clearMessage();
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === view));
  $("#login-form").hidden = view !== "login";
  $("#signup-form").hidden = view !== "signup";
}

function formValues(form) {
  const values = {};
  new FormData(form).forEach((v, k) => {
    values[k] = typeof v === "string" ? v.trim() : v;
  });
  return values;
}

// Always resolves to a { data } shape whose data.ok / data.error the caller
// can trust, turning network and non-JSON failures into readable messages.
async function postJSON(url, body) {
  let res;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (_) {
    return {
      data: {
        ok: false,
        error: "Could not reach the server. Is the Flask app running, and are you opening the page through it (e.g. http://localhost:5000) rather than as a file?",
      },
    };
  }

  const text = await res.text();
  try {
    return { data: JSON.parse(text) };
  } catch (_) {
    return {
      data: {
        ok: false,
        error: `Unexpected response from ${url} (HTTP ${res.status}). The request did not reach the auth API.`,
      },
    };
  }
}

// --- Auth <-> portal swap ------------------------------------------------

function enterPortal(user) {
  $("#auth-view").hidden = true;
  $("#portal-view").hidden = false;
  // portal.js owns everything past this point.
  window.Portal.render(user);
}

function exitPortal() {
  if (window.Portal) window.Portal.teardown();
  $("#portal-view").hidden = true;
  $("#auth-view").hidden = false;
  switchView("login");
}

// --- Handlers ----------------------------------------------------------

async function handleLogin(e) {
  e.preventDefault();
  clearMessage();
  const form = e.target;
  const values = formValues(form);
  values.role = selectedRole("login");

  const { data } = await postJSON("/api/login", values);
  if (!data.ok) {
    showMessage(data.error || "Unable to log in.");
    return;
  }
  form.reset();
  enterPortal(data.user);
}

async function handleSignup(e) {
  e.preventDefault();
  clearMessage();
  const form = e.target;
  const values = formValues(form);
  values.role = selectedRole("signup");

  const { data } = await postJSON("/api/signup", values);
  if (!data.ok) {
    showMessage(data.error || "Unable to create account.");
    return;
  }
  form.reset();
  syncCodeField("signup");
  switchView("login");
  showMessage("Account created. You can now log in.", "success");
}

async function handleLogout() {
  await postJSON("/api/logout", {});
  exitPortal();
  showMessage("You have been logged out.", "success");
}

async function checkSession() {
  try {
    const res = await fetch("/api/me");
    if (!res.ok) return;
    const data = await res.json();
    if (data.ok) enterPortal(data.user);
  } catch (_) {
    /* not logged in */
  }
}

// --- Wire-up ----------------------------------------------------------

function init() {
  $$(".tab").forEach((tab) =>
    tab.addEventListener("click", () => switchView(tab.dataset.view))
  );

  $$("input[name='login-role']").forEach((r) =>
    r.addEventListener("change", () => syncCodeField("login"))
  );
  $$("input[name='signup-role']").forEach((r) =>
    r.addEventListener("change", () => syncCodeField("signup"))
  );

  $("#login-form").addEventListener("submit", handleLogin);
  $("#signup-form").addEventListener("submit", handleSignup);
  $("#portal-logout").addEventListener("click", handleLogout);

  syncCodeField("login");
  syncCodeField("signup");
  checkSession();
}

document.addEventListener("DOMContentLoaded", init);
