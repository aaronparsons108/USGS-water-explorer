"use strict";

/* =============================================================================
   One Plotly rendering path for every figure in the app.

   The server sends figure JSON with all the geometry already decided (heights,
   margins, legend position, colorbar shape) and no colors at all. This module
   supplies the colors from the live CSS tokens, so a figure repaints correctly
   the instant the theme flips and never hardcodes a hex that the stylesheet
   might later disagree with.

   Charts.render(divId, figure) draws or updates one figure.
   Charts.resizeAll() relayouts every figure this module has drawn.

   One hard-won rule, see setIfPresent() below: never hand Plotly a layout key
   whose value is undefined.
   ============================================================================= */

window.Charts = (function () {
  const CONFIG = {
    responsive: true,
    displaylogo: false,
    modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d", "toggleSpikelines"],
    toImageButtonOptions: { format: "png", scale: 3 },
  };

  // Every figure drawn so far, so a theme change can repaint all of them.
  const drawn = new Map();

  function palette() {
    const t = window.Theme;
    const dark = t.current() === "dark";
    return {
      ink: t.token("--ink", dark ? "#e8eef5" : "#16202c"),
      muted: t.token("--muted", dark ? "#93a1b3" : "#5a6674"),
      line: t.token("--line", dark ? "#2a3542" : "#dde3ea"),
      grid: dark ? "rgba(255,255,255,0.09)" : "rgba(15,32,52,0.09)",
      zero: dark ? "rgba(255,255,255,0.22)" : "rgba(15,32,52,0.20)",
      land: dark ? "#1b2530" : "#eef1f4",
      lake: dark ? "#141d27" : "#dce7f1",
      subunit: dark ? "#3a4756" : "#9aa5b1",
      surface: t.token("--panel", dark ? "#151d27" : "#ffffff"),
      markerEdge: dark ? "rgba(0,0,0,0.65)" : "rgba(255,255,255,0.75)",
    };
  }

  /* Assign a key only when the value is defined.
   *
   * Plotly walks layout with Object.keys, so a key that merely *exists* with an
   * undefined value is not the same as an absent key. Writing
   * `{xaxis: layout.xaxis ? {...} : undefined}` put an `xaxis` key on the geo
   * map's layout; Plotly's cartesian defaults then matched it as an axis and
   * threw "Cannot read properties of undefined (reading 'anchor')", which
   * aborted the whole results render, table included.
   */
  function setIfPresent(target, key, source, build) {
    if (source) target[key] = build(source);
  }

  /* Colors, and only colors. Anything that moves an element belongs on the
     server so the layout is identical between the browser and the PNG. */
  function themedLayout(layout) {
    const p = palette();
    const axis = {
      gridcolor: p.grid,
      zerolinecolor: p.zero,
      linecolor: p.line,
      tickcolor: p.line,
      tickfont: { color: p.muted },
    };

    const out = Object.assign({}, layout, {
      font: Object.assign({}, layout.font, { color: p.ink }),
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      legend: Object.assign({}, layout.legend, {
        font: { color: p.ink, size: 12 },
        bgcolor: "rgba(0,0,0,0)",
      }),
      hoverlabel: Object.assign({}, layout.hoverlabel, {
        bgcolor: p.surface,
        bordercolor: p.line,
        font: Object.assign({}, (layout.hoverlabel || {}).font, { color: p.ink }),
      }),
    });

    setIfPresent(out, "title", layout.title, (t) =>
      Object.assign({}, t, { font: Object.assign({}, t.font, { color: p.ink }) })
    );

    // Cartesian axes exist on the scatter and not on the geo map.
    ["xaxis", "yaxis"].forEach((name) => {
      setIfPresent(out, name, layout[name], (a) =>
        Object.assign({}, a, axis, {
          title: Object.assign({}, a.title, { font: { color: p.ink } }),
        })
      );
    });

    setIfPresent(out, "geo", layout.geo, (g) =>
      Object.assign({}, g, {
        bgcolor: "rgba(0,0,0,0)",
        landcolor: p.land,
        lakecolor: p.lake,
        subunitcolor: p.subunit,
        coastlinecolor: p.subunit,
      })
    );

    setIfPresent(out, "coloraxis", layout.coloraxis, (c) =>
      Object.assign({}, c, {
        colorbar: Object.assign({}, c.colorbar, {
          tickfont: { color: p.muted, size: 11 },
          title: Object.assign({}, (c.colorbar || {}).title, {
            font: { color: p.ink, size: 12 },
          }),
        }),
      })
    );

    // Annotations carry the empty-state message; it has to stay readable.
    if (Array.isArray(layout.annotations)) {
      out.annotations = layout.annotations.map((a) =>
        Object.assign({}, a, { font: Object.assign({}, a.font, { color: p.muted }) })
      );
    }

    return out;
  }

  function themedData(data) {
    const p = palette();
    return data.map((trace) => {
      if (!trace.marker) return trace;
      const marker = Object.assign({}, trace.marker);
      if (marker.line) {
        marker.line = Object.assign({}, marker.line, { color: p.markerEdge });
      }
      return Object.assign({}, trace, { marker });
    });
  }

  function render(divId, figure) {
    const el = document.getElementById(divId);
    if (!el || !figure) return;
    drawn.set(divId, figure);
    Plotly.react(divId, themedData(figure.data || []), themedLayout(figure.layout || {}), CONFIG);
  }

  /* A theme flip re-runs the same render path rather than patching the live
     figure. relayout/restyle would need to know which attributes each trace
     type actually has, and getting that wrong is what caused the render crash
     this module now guards against. */
  function repaint() {
    drawn.forEach((figure, divId) => {
      if (document.getElementById(divId)) render(divId, figure);
    });
  }

  function resizeAll() {
    drawn.forEach((_, divId) => {
      const el = document.getElementById(divId);
      if (el && el.offsetParent !== null) Plotly.Plots.resize(divId);
    });
  }

  function setLoading(divId, loading) {
    const el = document.getElementById(divId);
    if (el) el.classList.toggle("is-loading", !!loading);
  }

  document.addEventListener("themechange", repaint);
  window.addEventListener("resize", () => {
    clearTimeout(window.__chartResize);
    window.__chartResize = setTimeout(resizeAll, 120);
  });

  return { render, repaint, resizeAll, setLoading, CONFIG, palette };
})();
