/* Small progressive enhancements for the cloud pages. Everything works without this file. */
(function () {
  "use strict";

  // Demo buttons open the floating widget that embed.js adds (it loads async, so wait for it).
  function openDemo(start) {
    var go = function () {
      var agent = document.querySelector("openfolio-agent");
      if (agent && typeof agent.open === "function") agent.open(start);
    };
    if (window.customElements && !customElements.get("openfolio-agent")) customElements.whenDefined("openfolio-agent").then(go);
    else go();
  }

  function copyFrom(button) {
    var input = document.querySelector(button.getAttribute("data-copy"));
    if (!input) return;
    var label = button.querySelector("span") || button;
    var done = function () {
      label.textContent = "Copied";
      setTimeout(function () { label.textContent = "Copy link"; }, 2000);
    };
    input.select();
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(input.value).then(done, function () {});
    else if (document.execCommand && document.execCommand("copy")) done();
  }

  document.addEventListener("click", function (event) {
    var target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    var demo = target.closest("[data-demo]");
    if (demo) {
      event.preventDefault();
      openDemo(demo.getAttribute("data-demo") === "chat" ? "chat" : "voice");
      return;
    }
    var copy = target.closest("[data-copy]");
    if (copy) copyFrom(copy);
  });

  // Destructive admin actions ask first.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    var message = form instanceof HTMLFormElement ? form.getAttribute("data-confirm") : null;
    if (message && !window.confirm(message)) event.preventDefault();
  });

  function ready() {
    // Character counter for the optional reason.
    document.querySelectorAll("[data-count-for]").forEach(function (hint) {
      var field = document.getElementById(hint.getAttribute("data-count-for"));
      var max = Number(hint.getAttribute("data-max")) || 0;
      if (!field || !max) return;
      var update = function () { hint.textContent = field.value.length + " / " + max; };
      field.addEventListener("input", update);
      update();
    });
    // Times are rendered in UTC; show the exact local time on hover.
    document.querySelectorAll("time[data-local]").forEach(function (el) {
      var when = new Date(el.getAttribute("datetime") || "");
      if (!isNaN(when.getTime())) el.title = when.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready);
  else ready();
})();
