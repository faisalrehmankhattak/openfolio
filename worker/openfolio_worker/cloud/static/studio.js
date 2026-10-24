/* Openfolio Studio: small progressive enhancements. Every page works without this file. */
(function () {
  "use strict";

  function $all(selector, root) { return Array.prototype.slice.call((root || document).querySelectorAll(selector)); }

  // Draft progress: poll the job and move to the profile when it's ready.
  function pollDraft(panel) {
    var url = panel.getAttribute("data-draft-status");
    var order = ["reading", "drafting", "checking", "done"];
    var label = panel.querySelector("[data-draft-label]");
    function tick() {
      fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" })
        .then(function (r) { return r.json(); })
        .then(function (job) {
          if (job.state === "done") { window.location.href = "/studio/profile?m=drafted"; return; }
          if (job.state !== "running") { window.location.reload(); return; }
          var at = order.indexOf(job.step);
          $all("[data-step]", panel).forEach(function (li) {
            var i = order.indexOf(li.getAttribute("data-step"));
            li.classList.toggle("is-done", i < at);
            li.classList.toggle("is-current", i === at);
          });
          if (label && job.label) label.textContent = job.label + ". This usually takes 15 to 40 seconds.";
          window.setTimeout(tick, 1500);
        })
        .catch(function () { window.setTimeout(tick, 4000); });
    }
    // The meta refresh is the no-JavaScript fallback; polling replaces it.
    $all('meta[http-equiv="refresh"]').forEach(function (m) { m.parentNode.removeChild(m); });
    window.setTimeout(tick, 1200);
  }

  // File pickers: show the chosen file and highlight drag-over.
  function enhanceDropzone(zone) {
    var input = zone.querySelector("input[type=file]");
    var name = zone.querySelector("[data-file-name]");
    if (!input) return;
    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      if (!file) return;
      zone.classList.add("has-file");
      if (name) name.textContent = file.name + " · " + (file.size >= 1048576 ? (file.size / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(file.size / 1024)) + " KB");
    });
    ["dragenter", "dragover"].forEach(function (t) { zone.addEventListener(t, function () { zone.classList.add("is-over"); }); });
    ["dragleave", "drop"].forEach(function (t) { zone.addEventListener(t, function () { zone.classList.remove("is-over"); }); });
  }

  // Repeating groups in the profile form.
  function addRow(group) {
    var rows = document.querySelector('[data-rows="' + group + '"]');
    var tpl = document.getElementById("tpl-" + group);
    if (!rows || !tpl) return;
    var limit = parseInt(rows.getAttribute("data-limit") || "50", 10);
    if (rows.querySelectorAll("[data-row]").length >= limit) return;
    var next = parseInt(rows.getAttribute("data-next") || "0", 10);
    rows.setAttribute("data-next", String(next + 1));
    var holder = document.createElement("div");
    holder.innerHTML = tpl.innerHTML.replace(/__i__/g, String(next));
    var row = holder.firstElementChild;
    rows.appendChild(row);
    var first = row.querySelector("input, textarea");
    if (first) first.focus();
    updateAddButtons();
    markDirty();
  }
  function updateAddButtons() {
    $all("[data-add-row]").forEach(function (btn) {
      var rows = document.querySelector('[data-rows="' + btn.getAttribute("data-add-row") + '"]');
      var limit = parseInt((rows && rows.getAttribute("data-limit")) || "50", 10);
      btn.hidden = false;
      btn.disabled = !!rows && rows.querySelectorAll("[data-row]").length >= limit;
    });
  }

  // Unsaved changes in the profile form.
  var dirty = false;
  var submitting = false;
  function markDirty() {
    var form = document.querySelector("[data-profile-form]");
    if (!form || dirty) return;
    dirty = true;
    var note = document.querySelector("[data-dirty-note]");
    if (note) { note.classList.add("is-dirty"); note.textContent = "You have unsaved changes."; }
  }

  function copyFrom(button) {
    var source = document.querySelector(button.getAttribute("data-copy-from"));
    if (!source) return;
    var label = button.querySelector("span");
    function done() { if (label) { label.textContent = "Copied"; window.setTimeout(function () { label.textContent = "Copy"; }, 1800); } }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(source.value).then(done, function () { source.select(); });
    } else {
      source.select();
      try { document.execCommand("copy"); done(); } catch (e) { /* the text stays selected for a manual copy */ }
    }
  }

  document.addEventListener("click", function (event) {
    var target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    var add = target.closest("[data-add-row]");
    if (add) { addRow(add.getAttribute("data-add-row")); return; }
    var remove = target.closest("[data-remove-row]");
    if (remove) {
      var row = remove.closest("[data-row]");
      if (row) { row.parentNode.removeChild(row); updateAddButtons(); markDirty(); }
      return;
    }
    var copy = target.closest("[data-copy-from]");
    if (copy) { copyFrom(copy); return; }
    var reveal = target.closest("[data-reveal]");
    if (reveal) {
      var input = document.querySelector(reveal.getAttribute("data-reveal"));
      if (input) {
        var show = input.type === "password";
        input.type = show ? "text" : "password";
        reveal.setAttribute("aria-label", show ? "Hide password" : "Show password");
      }
    }
  });

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || event.defaultPrevented) return;
    submitting = true;
    var busy = form.querySelector("[data-busy]");
    if (busy) {
      // After the browser has taken the form data, so the button's own value still submits.
      window.setTimeout(function () {
        busy.classList.add("is-busy");
        busy.setAttribute("aria-busy", "true");
        busy.textContent = busy.getAttribute("data-busy");
      }, 0);
    }
  });

  document.addEventListener("change", function (event) {
    var target = event.target;
    if (target instanceof HTMLInputElement && target.hasAttribute("data-autosubmit") && target.form) {
      if (target.form.requestSubmit) target.form.requestSubmit(); else target.form.submit();
    }
  });

  document.addEventListener("DOMContentLoaded", function () {
    $all("[data-draft-status]").forEach(pollDraft);
    $all(".dropzone").forEach(enhanceDropzone);
    updateAddButtons();
    var form = document.querySelector("[data-profile-form]");
    if (form) {
      form.addEventListener("input", markDirty);
      window.addEventListener("beforeunload", function (e) {
        if (dirty && !submitting) { e.preventDefault(); e.returnValue = ""; }
      });
    }
    var handle = document.getElementById("handle");
    var echo = document.querySelector("[data-handle-echo]");
    if (handle && echo) {
      handle.addEventListener("input", function () {
        handle.value = handle.value.toLowerCase().replace(/[^a-z0-9-]/g, "");
        echo.textContent = handle.value || "you";
      });
    }
  });
})();
