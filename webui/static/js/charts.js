/* ============ 图表渲染：纯 SVG + 缩放平移（兼容所有机器，不依赖 GPU canvas） ============ */
window.CH = (() => {
  const PANEL_BG = "#10141c";
  const TEXT = "#8b94a7";
  const UP = "#22c55e";
  const DOWN = "#ef4444";
  const syncGroups = {};

  // 主题化配色：从 CSS 变量读取，切换主题后重绘自动生效
  function palette() {
    const cs = getComputedStyle(document.documentElement);
    const v = (n, d) => { const x = cs.getPropertyValue(n).trim(); return x || d; };
    return {
      bg: v("--chart-bg", PANEL_BG),
      text: v("--chart-text", TEXT),
      up: v("--chart-up", UP),
      down: v("--chart-down", DOWN),
      grid: v("--chart-grid", "rgba(148,163,184,0.1)"),
      c: [
        v("--chart-c1", "#4c8dff"),
        v("--chart-c2", "#22c55e"),
        v("--chart-c3", "#f59e0b"),
        v("--chart-c4", "#a78bfa"),
      ],
    };
  }

  // 无操作对象，兼容原有调用链
  function stub() {
    return {
      setData() {}, applyOptions() {}, setMarkers() {}, fitContent() {},
      addAreaSeries() { return stub(); }, addLineSeries() { return stub(); },
      addHistogramSeries() { return stub(); }, addCandlestickSeries() { return stub(); },
      priceScale() { return stub(); }, timeScale() { return stub(); },
      remove() {}, resize() {}, chart() { return stub(); },
    };
  }

  function measure(el) {
    const w = Math.max(el.clientWidth || 600, 200);
    const cs = getComputedStyle(el);
    let h = parseFloat(cs.height) || 300;
    if (h <= 0) h = parseFloat(el.style.height) || 300;
    return { width: Math.floor(w), height: Math.max(Math.floor(h), 100) };
  }

  function fmtNum(v) {
    if (v === null || v === undefined || Number.isNaN(v)) return "";
    if (Math.abs(v) >= 10000) return (v / 1000).toFixed(1) + "k";
    if (Math.abs(v) >= 100) return v.toFixed(0);
    return v.toFixed(2);
  }

  // 从 spec 提取统一时间轴（毫秒）
  function timeAxis(spec) {
    if (spec.kind === "candles" && spec.bars && spec.bars.length) {
      return spec.bars.map((b) => b.time);
    }
    let best = null;
    (spec.series || []).forEach((s) => {
      if (s.points && s.points.length > (best ? best.length : 0)) best = s.points.map((p) => p[0]);
    });
    return best || [];
  }

  function stateOf(el, spec) {
    if (el.__qxState && el.__qxState.spec === spec) return el.__qxState;
    const times = timeAxis(spec);
    const st = { spec, times };
    if (times.length) {
      const n = times.length;
      const def = spec.defaultRange || (spec.kind === "candles" ? 120 : 180);
      st.t1 = times[n - 1];
      st.t0 = times[Math.max(0, n - 1 - def)];
    } else {
      st.t0 = 0; st.t1 = 1;
    }
    el.__qxState = st;
    return st;
  }

  function renderSVG(el, spec) {
    if (!el || !el.isConnected) return;
    spec = spec || fallbacks.get(el);
    const pal = palette();
    const st = stateOf(el, spec);
    const dim = measure(el);
    const w = dim.width, h = dim.height;
    const volH = spec && spec.kind === "candles" ? Math.max(28, Math.floor(h * 0.16)) : 0;
    const pad = { top: 10, right: 12, bottom: 20, left: 58 };
    const plotH = h - pad.top - pad.bottom - (volH ? volH + 8 : 0);
    const iw = w - pad.left - pad.right;
    const ih = plotH;

    const t0 = st.t0, t1 = st.t1;
    const dt = t1 - t0 || 1;

    // 可见数据
    const bars = spec && spec.kind === "candles" ? (spec.bars || []) : [];
    const visBars = bars.filter((b) => b.time >= t0 && b.time <= t1);
    const series = (spec && spec.series) || [];
    const visSeries = series.map((s) => {
      const pts = (s.points || []).filter((p) => p[0] >= t0 - dt * 0.5 && p[0] <= t1 + dt * 0.5);
      return { color: s.color, area: s.area, points: pts };
    });

    // 值域
    let vmin = Infinity, vmax = -Infinity;
    if (visBars.length) {
      visBars.forEach((b) => { if (b.low < vmin) vmin = b.low; if (b.high > vmax) vmax = b.high; });
    }
    visSeries.forEach((s) => s.points.forEach((p) => { if (p[1] < vmin) vmin = p[1]; if (p[1] > vmax) vmax = p[1]; }));
    if (!isFinite(vmin)) { vmin = 0; vmax = 1; }
    if (vmin === vmax) { vmin -= 1; vmax += 1; }
    const vpad = (vmax - vmin) * 0.06;
    vmin -= vpad; vmax += vpad;

    const X = (ts) => pad.left + (ts - t0) / dt * iw;
    const Y = (v) => pad.top + (1 - (v - vmin) / (vmax - vmin)) * ih;

    let out = '<svg class="qx-svg-chart" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + " " + h + '" xmlns="http://www.w3.org/2000/svg" style="display:block;background:' + pal.bg + '">';
    out += '<rect width="' + w + '" height="' + h + '" fill="' + pal.bg + '"/>';

    if (!visBars.length && !visSeries.some((s) => s.points.length)) {
      out += '<text x="' + (w / 2) + '" y="' + (h / 2) + '" fill="' + pal.text + '" font-size="12" text-anchor="middle">暂无数据</text></svg>';
      el.innerHTML = out;
      ensureTools(el);
      return;
    }

    // 网格 + Y 轴
    for (let i = 0; i <= 4; i++) {
      const y = pad.top + ih * i / 4;
      out += '<line x1="' + pad.left + '" y1="' + y.toFixed(1) + '" x2="' + (w - pad.right) + '" y2="' + y.toFixed(1) + '" stroke="' + pal.grid + '" stroke-width="1"/>';
      out += '<text x="' + (pad.left - 7) + '" y="' + (y + 4).toFixed(1) + '" fill="' + pal.text + '" font-size="10" text-anchor="end" font-family="monospace">' + fmtNum(vmin + (vmax - vmin) * (1 - i / 4)) + '</text>';
    }
    // 竖网格 + X 轴日期（最多 6 段）
    const ticks = Math.min(6, Math.max(2, Math.floor(iw / 90)));
    for (let i = 0; i <= ticks; i++) {
      const ts = t0 + dt * i / ticks;
      const x = X(ts);
      out += '<line x1="' + x.toFixed(1) + '" y1="' + pad.top + '" x2="' + x.toFixed(1) + '" y2="' + (pad.top + ih) + '" stroke="' + pal.grid + '" stroke-width="1" opacity="0.7"/>';
      const d = new Date(ts * 1000);
      const lbl = (d.getMonth() + 1) + "/" + d.getDate() + " " + String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
      out += '<text x="' + x.toFixed(1) + '" y="' + (h - 6) + '" fill="' + pal.text + '" font-size="10" text-anchor="middle" font-family="monospace">' + lbl + '</text>';
    }

    // 成交量（K线图底部）
    if (volH && visBars.length) {
      let vmaxVol = 0;
      visBars.forEach((b) => { if (b.volume > vmaxVol) vmaxVol = b.volume; });
      const vTop = pad.top + ih + 8;
      const bw = Math.max(Math.min(iw / visBars.length * 0.7, 10), 1.5);
      visBars.forEach((b) => {
        const x = X(b.time);
        const vh = vmaxVol > 0 ? (b.volume / vmaxVol) * volH : 0;
        out += '<rect x="' + (x - bw / 2).toFixed(1) + '" y="' + (vTop + volH - vh).toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + Math.max(vh, 0.5).toFixed(1) + '" fill="' + (b.close >= b.open ? pal.up : pal.down) + '" opacity="0.45"/>';
      });
    }

    // K线
    if (visBars.length) {
      const bw = Math.max(Math.min(iw / visBars.length * 0.7, 12), 1.5);
      visBars.forEach((b) => {
        const x = X(b.time);
        const up = b.close >= b.open;
        const color = up ? pal.up : pal.down;
        const yH = Y(b.high), yL = Y(b.low), yO = Y(b.open), yC = Y(b.close);
        out += '<line x1="' + x.toFixed(1) + '" y1="' + yH.toFixed(1) + '" x2="' + x.toFixed(1) + '" y2="' + yL.toFixed(1) + '" stroke="' + color + '" stroke-width="1"/>';
        const top = Math.min(yO, yC);
        const hh = Math.max(Math.abs(yC - yO), 2);
        out += '<rect x="' + (x - bw / 2).toFixed(1) + '" y="' + top.toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + hh.toFixed(1) + '" fill="' + color + '"/>';
      });
    }

    // 折线
    visSeries.forEach((s) => {
      const pts = s.points.map((p) => X(p[0]).toFixed(1) + "," + Y(p[1]).toFixed(1)).join(" ");
      if (!pts) return;
      if (s.area) {
        out += '<polygon points="' + pad.left + "," + (pad.top + ih).toFixed(1) + " " + pts + " " + (w - pad.right) + "," + (pad.top + ih).toFixed(1) + '" fill="' + s.color + '" opacity="0.15"/>';
      }
      out += '<polyline points="' + pts + '" fill="none" stroke="' + s.color + '" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>';
    });

    out += "</svg>";
    el.innerHTML = out;
    el.style.display = "block";
    ensureTools(el);
    ensureCrosshair(el);
  }
  // ---------- 十字光标 / OHLC 读取 ----------
  function ensureCrosshair(el) {
    const st = el.__qxState;
    if (!st || !st.spec || st.spec.kind !== "candles") return;
    let xline = el.querySelector(".qx-xline");
    let tip = el.querySelector(".qx-tip");
    if (!xline) {
      xline = document.createElement("div");
      xline.className = "qx-xline";
      el.appendChild(xline);
    }
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "qx-tip";
      el.appendChild(tip);
    }
    if (el.__qxCrosshairBound) return;
    el.__qxCrosshairBound = true;
    el.addEventListener("mousemove", (e) => {
      const s = el.__qxState;
      const bars = s && s.spec && s.spec.kind === "candles" ? (s.spec.bars || []) : [];
      if (!bars.length) { xline.style.display = "none"; tip.style.display = "none"; return; }
      const dim = measure(el);
      const padL = 58, padR = 12;
      const iw = dim.width - padL - padR;
      if (iw <= 0) return;
      const rect = el.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const ts = s.t0 + (x - padL) / iw * (s.t1 - s.t0);
      let best = null, bestD = Infinity;
      for (const b of bars) {
        const d = Math.abs(b.time - ts);
        if (d < bestD) { bestD = d; best = b; }
      }
      if (!best) return;
      const px = padL + (best.time - s.t0) / (s.t1 - s.t0) * iw;
      xline.style.display = "block";
      xline.style.left = px.toFixed(1) + "px";
      const d = new Date(best.time);
      const p2 = (n) => String(n).padStart(2, "0");
      const chg = best.open ? (best.close / best.open - 1) : 0;
      tip.innerHTML = "<div class='qx-tip-time'>" + d.getFullYear() + "-" + p2(d.getMonth() + 1) + "-" + p2(d.getDate()) + " " + p2(d.getHours()) + ":" + p2(d.getMinutes()) + "</div>"
        + "<div><span>开</span><b>" + fmtNum(best.open) + "</b></div>"
        + "<div><span>高</span><b>" + fmtNum(best.high) + "</b></div>"
        + "<div><span>低</span><b>" + fmtNum(best.low) + "</b></div>"
        + "<div><span>收</span><b>" + fmtNum(best.close) + "</b></div>"
        + "<div><span>涨跌</span><b class='" + (chg >= 0 ? "pos" : "neg") + "'>" + (chg >= 0 ? "+" : "") + (chg * 100).toFixed(2) + "%</b></div>";
      tip.style.display = "block";
      tip.style.left = (px + 10) + "px";
      tip.style.top = "8px";
      const tw = tip.offsetWidth || 130;
      if (px + tw + 20 > dim.width) tip.style.left = (px - tw - 12) + "px";
    });
    el.addEventListener("mouseleave", () => {
      if (xline) xline.style.display = "none";
      if (tip) tip.style.display = "none";
    });
  }

  // ---------- 缩放 / 平移 ----------
  function applyView(el, t0, t1) {
    const st = el.__qxState;
    if (!st) return;
    const times = st.times;
    if (!times.length) return;
    const lo = times[0], hi = times[times.length - 1];
    let a = Math.max(t0, lo), b = Math.min(t1, hi);
    if (b - a < (hi - lo) / Math.max(times.length, 2)) return; // 最小可见范围
    st.t0 = a; st.t1 = b;
    renderSVG(el);
    // 同步同组图表
    const group = el.dataset ? el.dataset.sync : null;
    if (group && syncGroups[group]) {
      syncGroups[group].forEach((other) => {
        if (other !== el && other.__qxState) { other.__qxState.t0 = a; other.__qxState.t1 = b; renderSVG(other); }
      });
    }
  }

  function zoomAt(el, factor) {
    const st = el.__qxState;
    if (!st || !st.times.length) return;
    const span = st.t1 - st.t0;
    const mid = (st.t0 + st.t1) / 2;
    const newSpan = Math.max(span * factor, (st.times[st.times.length - 1] - st.times[0]) / Math.max(st.times.length, 2));
    applyView(el, mid - newSpan / 2, mid + newSpan / 2);
  }

  function panBy(el, dxPx) {
    const st = el.__qxState;
    if (!st || !st.times.length) return;
    const dim = measure(el);
    const iw = dim.width - 70;
    const span = st.t1 - st.t0;
    if (iw <= 0) return;
    const shift = dxPx / iw * span;
    applyView(el, st.t0 - shift, st.t1 - shift);
  }

  function ensureTools(el) {
    el.style.position = "relative";
    let bar = el.querySelector(".chart-tools");
    if (!bar) {
      bar = document.createElement("div");
      bar.className = "chart-tools";
      bar.innerHTML = '<button data-z="in" title="放大">＋</button><button data-z="out" title="缩小">－</button><button data-z="reset" title="恢复">复位</button><span class="chart-tools-hint">滚轮缩放 · 拖拽平移</span>';
      el.appendChild(bar);
    }
    if (el.__qxListeners) return;
    el.__qxListeners = true;
    el.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-z]");
      if (!btn) return;
      if (btn.dataset.z === "in") zoomAt(el, 0.65);
      else if (btn.dataset.z === "out") zoomAt(el, 1.5);
      else {
        const st = el.__qxState;
        if (st && st.times.length) { st.t0 = st.times[0]; st.t1 = st.times[st.times.length - 1]; renderSVG(el); }
      }
    });
    el.addEventListener("wheel", (e) => {
      e.preventDefault();
      zoomAt(el, e.deltaY < 0 ? 0.65 : 1.5);
    }, { passive: false });
    let dragging = false, lastX = 0;
    el.addEventListener("mousedown", (e) => {
      if (e.target.closest(".chart-tools")) return;
      dragging = true; lastX = e.clientX; el.style.cursor = "grabbing";
    });
    window.addEventListener("mousemove", (e) => {
      if (!dragging || !el.isConnected) return;
      const dx = e.clientX - lastX;
      lastX = e.clientX;
      if (dx) panBy(el, dx);
    });
    window.addEventListener("mouseup", () => {
      dragging = false;
      if (el.isConnected) el.style.cursor = "";
    });
  }

  const fallbacks = new Map();
  function setFallback(el, spec) {
    if (!el) return;
    fallbacks.set(el, spec);
    const group = el.dataset ? el.dataset.sync : null;
    if (group) {
      syncGroups[group] = syncGroups[group] || [];
      if (!syncGroups[group].includes(el)) syncGroups[group].push(el);
    }
  }
  function renderSVGFallback(el) { renderSVG(el, fallbacks.get(el)); }

  // ---- 对外 API：全部走纯 SVG ----
  function createCandleChart(el) { renderSVGFallback(el); return { chart: stub(), candles: stub(), volume: stub(), lines: [] }; }
  function createLineChart(el) { renderSVGFallback(el); return stub(); }
  function createChart(el) { renderSVGFallback(el); return stub(); }
  function remove() {}
  function clearRegistry() {}
  function resizeAll() {
    // 窗口变化后重绘
    document.querySelectorAll("svg.qx-svg-chart").forEach((svg) => {
      const el = svg.parentElement;
      if (el && el.__qxState) renderSVG(el);
    });
  }
  window.addEventListener("resize", () => { clearTimeout(window.__qxResizeT); window.__qxResizeT = setTimeout(resizeAll, 180); });

  function barsToCandle(bars) { return bars; }
  function volumeData(bars) { return bars; }
  function indData(bars, values) {
    const out = [];
    for (let i = 0; i < bars.length; i++) {
      const v = values[i];
      if (v !== null && v !== undefined) out.push({ time: bars[i].time, value: v });
    }
    return out;
  }
  function addLine() { return stub(); }
  function addHist() { return stub(); }
  function tradeMarkers() { return []; }

  // 主题切换后重绘所有已注册图表
  window.addEventListener("quantx:themechange", () => {
    document.querySelectorAll("svg.qx-svg-chart").forEach((svg) => {
      const el = svg.parentElement;
      if (el && el.__qxState) renderSVG(el);
    });
  });

  return { createCandleChart, createLineChart, barsToCandle, volumeData, indData, addLine, addHist, tradeMarkers, createChart, remove, clearRegistry, resizeAll, setFallback, renderSVGFallback, renderSVG, zoomAt, applyView, palette };
})();
