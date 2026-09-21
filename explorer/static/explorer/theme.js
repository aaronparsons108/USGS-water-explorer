"use strict";

/* =============================================================================
   Theme handling, shared by the explorer and every wizard page.

   Three states, in priority order:
     1. an explicit choice stored in localStorage, stamped on <html>
     2. the operating system preference
     3. light

   Other scripts listen for the "themechange" event on document rather than
   polling, so charts can recolor at the same moment the CSS does.
   ============================================================================= */

window.Theme = (function () {
  const KEY = "explorer-theme";
  const media = window.matchMedia("(prefers-color-scheme: dark)");

  function current() {
    return (
      document.documentElement.getAttribute("data-theme") ||
      (media.matches ? "dark" : "light")
    );
  }

  function announce() {
    document.dispatchEvent(
      new CustomEvent("themechange", { detail: { theme: current() } })
    );
  }

  function apply(next) {
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem(KEY, next);
    } catch (e) {
      /* private mode: the choice just will not persist */
    }
    announce();
  }

  function stored() {
    try {
      return localStorage.getItem(KEY);
    } catch (e) {
      return null;
    }
  }

  /* Read a CSS custom property off :root, so JS-drawn things (Plotly) can use
     the exact same palette the stylesheet does instead of duplicating hexes. */
  function token(name, fallback) {
    const v = getComputedStyle(document.documentElement)
      .getPropertyValue(name)
      .trim();
    return v || fallback || "";
  }

  function init() {
    const btn = document.getElementById("theme-toggle");
    const label = document.getElementById("theme-toggle-label");

    function syncLabel() {
      if (label) label.textContent = current() === "dark" ? "Light" : "Dark";
    }
    syncLabel();

    if (btn) {
      btn.addEventListener("click", () => {
        apply(current() === "dark" ? "light" : "dark");
        syncLabel();
      });
    }

    // With no explicit override, follow the system preference as it changes.
    media.addEventListener("change", () => {
      if (!stored()) {
        document.documentElement.removeAttribute("data-theme");
        syncLabel();
        announce();
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  return { current, apply, token };
})();
