/* ============ 行情图表 ============ */
App.register("chart", (() => {
  const state = {
    symbol: "BTC/USDT", timeframe: "1h", source: "auto", limit: 500,
    showMA: true, showBOLL: true, showRSI: true, showMACD: true, showMarkers: false, auto: true, data: null,
  };
  // 记住上次的图表偏好
  try {
    const saved = JSON.parse(localStorage.getItem("quantx_chart_prefs") || "{}");
    if (saved.symbol) state.symbol = saved.symbol;
    if (saved.timeframe) state.timeframe = saved.timeframe;
    if (saved.source) state.source = saved.source;
    if (typeof saved.auto === "boolean") state.auto = saved.auto;
  } catch (e) { /* 忽略 */ }
  function savePrefs() {
    try { localStorage.setItem("quantx_chart_prefs", JSON.stringify({ symbol: state.symbol, timeframe: state.timeframe, source: state.source, auto: state.auto })); } catch (e) {}
  }
  const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"];
  const SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT"];
  const SOURCES = [["auto", "交易所真实行情"], ["exchange", "仅交易所"]];
  let charts = [];

  function clearCharts() {
    charts.forEach((c) => { try { CH.remove(c); } catch (e) {} });
    charts = [];
  }

  function render() {
    const page = document.getElementById("page-chart");
    page.innerHTML = `
      <div class="card" style="margin-bottom:16px">
        <div class="ctrl-bar" style="margin-bottom:0">
          <div class="ctrl-group"><span class="ctrl-label">标的</span>
            <input class="input" id="ch-symbol" list="ch-symbol-list" style="width:180px" placeholder="如 BTC/USDT" autocomplete="off">
            <datalist id="ch-symbol-list"></datalist>
          </div>
          <div class="ctrl-group"><span class="ctrl-label">周期</span><div class="chips" id="ch-timeframes"></div></div>
          <div class="ctrl-group"><span class="ctrl-label">数据源</span>
            <select class="select" id="ch-source" style="width:180px"></select>
          </div>
          <div class="ctrl-group"><span class="ctrl-label">指标</span>
            <div class="chips" id="ch-indicators">
              <span class="chip active" data-ind="MA">MA</span>
              <span class="chip active" data-ind="BOLL">BOLL</span>
              <span class="chip active" data-ind="RSI">RSI</span>
              <span class="chip active" data-ind="MACD">MACD</span>
              <span class="chip" data-ind="markers">交易点</span>
              <span class="chip${state.auto ? " active" : ""}" data-ind="auto" title="每 10 秒自动刷新">自动刷新</span>
            </div>
          </div>
          <button class="btn btn-primary btn-sm" id="ch-reload">⟳ 刷新</button>
        </div>
      </div>
      <div class="chart-box"><div class="chart-title"><span id="ch-title">--</span><span id="ch-price" style="font-family:var(--mono)">--</span></div><div class="chart-canvas" id="ch-candle" data-sync="main"></div></div>
      <div class="chart-box" id="ch-rsi-box" style="margin-top:14px"><div class="chart-title"><span>RSI (14)</span></div><div class="chart-canvas xs" id="ch-rsi" data-sync="main"></div></div>
      <div class="chart-box" id="ch-macd-box" style="margin-top:14px"><div class="chart-title"><span>MACD (12,26,9)</span></div><div class="chart-canvas xs" id="ch-macd" data-sync="main"></div></div>
    `;
    const symSel = document.getElementById("ch-symbol");
    symSel.value = state.symbol;
    document.getElementById("ch-symbol-list").innerHTML = SYMBOLS.map((s) => '<option value="' + s + '">').join("");
    symSel.addEventListener("change", () => { state.symbol = symSel.value.trim().toUpperCase(); savePrefs(); load(); });
    symSel.addEventListener("keydown", (e) => { if (e.key === "Enter") { state.symbol = symSel.value.trim().toUpperCase(); savePrefs(); load(); } });
    const tfBox = document.getElementById("ch-timeframes");
    tfBox.innerHTML = TIMEFRAMES.map((t) => '<span class="chip ' + (t === state.timeframe ? "active" : "") + '" data-tf="' + t + '">' + t + '</span>').join("");
    tfBox.querySelectorAll("[data-tf]").forEach((c) => c.addEventListener("click", () => {
      tfBox.querySelectorAll("[data-tf]").forEach((x) => x.classList.remove("active"));
      c.classList.add("active");
      state.timeframe = c.dataset.tf;
      load();
    }));
    const srcSel = document.getElementById("ch-source");
    srcSel.innerHTML = SOURCES.map(([v, l]) => '<option value="' + v + '" ' + (v === state.source ? "selected" : "") + '>' + l + '</option>').join("");
    srcSel.addEventListener("change", () => { state.source = srcSel.value; savePrefs(); load(); });
    document.getElementById("ch-indicators").querySelectorAll("[data-ind]").forEach((c) => {
      c.addEventListener("click", () => {
        c.classList.toggle("active");
        const ind = c.dataset.ind;
        if (ind === "auto") { state.auto = c.classList.contains("active"); savePrefs(); return; }
        const key = ind === "MA" ? "showMA" : ind === "BOLL" ? "showBOLL" : ind === "RSI" ? "showRSI" : ind === "MACD" ? "showMACD" : "showMarkers";
        state[key] = c.classList.contains("active");
        draw();
      });
    });
    document.getElementById("ch-reload").addEventListener("click", load);
    load();
  }

  async function load() {
    const candleBox = document.getElementById("ch-candle");
    if (!candleBox) return;
    const titleEl = candleBox.closest(".chart-box").querySelector(".chart-title #ch-title");
    if (titleEl) titleEl.textContent = state.symbol + " · " + state.timeframe + " · 加载中…";
    try {
      const data = await API.get("/api/ohlcv?symbol=" + encodeURIComponent(state.symbol) + "&timeframe=" + state.timeframe + "&limit=" + state.limit + "&source=" + state.source);
      state.data = data;
      const srcLabel = { auto: "交易所", db: "交易所", exchange: "OKX" }[data.source] || data.source;
      if (titleEl) titleEl.textContent = state.symbol + " · " + state.timeframe + " · " + srcLabel;
      const priceEl = document.getElementById("ch-price");
      const lastBar = data.bars && data.bars.length ? data.bars[data.bars.length - 1] : null;
      if (priceEl && lastBar) priceEl.textContent = FMT.price(lastBar.close) + " · " + FMT.time(lastBar.time);
      draw();
    } catch (e) {
      App.toast("行情加载失败: " + e.message, "error");
    }
  }

  function draw() {
    const palCH = CH.palette();
    const data = state.data;
    if (!data) return;
    clearCharts();
    const title = document.getElementById("ch-title");
    const priceEl = document.getElementById("ch-price");
    const last = data.bars[data.bars.length - 1];
    const srcLabel = data.source === "exchange" ? "OKX" : "交易所";
    title.textContent = data.symbol + " · " + data.timeframe + " · " + srcLabel;
    if (priceEl) {
      const prev = data.bars[data.bars.length - 2];
      const chg = prev ? (last.close - prev.close) / prev.close : 0;
      priceEl.textContent = FMT.price(last.close) + "  " + FMT.pctSigned(chg);
      priceEl.style.color = chg >= 0 ? "var(--green)" : "var(--red)";
    }
    // 先注册 SVG 兜底数据（canvas 创建失败时立即接管）
    {
      const fb = [];
      if (state.showMA) {
        fb.push({ color: palCH.c[2], points: CH.indData(data.bars, data.indicators.sma20).map((p) => [p.time, p.value]) });
        fb.push({ color: palCH.text, points: CH.indData(data.bars, data.indicators.sma50).map((p) => [p.time, p.value]) });
      }
      if (state.showBOLL) {
        fb.push({ color: palCH.c[0], points: CH.indData(data.bars, data.indicators.boll_upper).map((p) => [p.time, p.value]) });
        fb.push({ color: palCH.text, points: CH.indData(data.bars, data.indicators.boll_mid).map((p) => [p.time, p.value]) });
        fb.push({ color: palCH.c[0], points: CH.indData(data.bars, data.indicators.boll_lower).map((p) => [p.time, p.value]) });
      }
      CH.setFallback(document.getElementById("ch-candle"), { kind: "candles", bars: data.bars, series: fb });
    }
    CH.setFallback(document.getElementById("ch-rsi"), { series: [{ color: palCH.c[3], points: CH.indData(data.bars, data.indicators.rsi14).map((p) => [p.time, p.value]) }] });
    CH.setFallback(document.getElementById("ch-macd"), { series: [{ color: palCH.c[0], points: CH.indData(data.bars, data.indicators.macd_dif).map((p) => [p.time, p.value]) }, { color: palCH.c[2], points: CH.indData(data.bars, data.indicators.macd_dea).map((p) => [p.time, p.value]) }] });

    const main = CH.createCandleChart(document.getElementById("ch-candle"));
    if (main) {
      charts.push(main.chart);
      main.candles.setData(CH.barsToCandle(data.bars));
      main.volume.setData(CH.volumeData(data.bars));
      if (state.showMA) {
        const l1 = CH.addLine(main.chart, palCH.c[2], 1);
        const l2 = CH.addLine(main.chart, palCH.c[0], 1);
        l1.setData(CH.indData(data.bars, data.indicators.sma20));
        l2.setData(CH.indData(data.bars, data.indicators.sma50));
      }
      if (state.showBOLL) {
        CH.addLine(main.chart, palCH.c[0], 1).setData(CH.indData(data.bars, data.indicators.boll_upper));
        CH.addLine(main.chart, palCH.text, 1).setData(CH.indData(data.bars, data.indicators.boll_mid));
        CH.addLine(main.chart, palCH.c[0], 1).setData(CH.indData(data.bars, data.indicators.boll_lower));
      }
      if (state.showMarkers && App.state.latestResult) {
        main.candles.setMarkers(CH.tradeMarkers(App.state.latestResult.trades || []));
      }
      main.chart.timeScale().fitContent();
    }
    const rsiBox = document.getElementById("ch-rsi-box");
    const macdBox = document.getElementById("ch-macd-box");
    if (rsiBox) rsiBox.style.display = state.showRSI ? "" : "none";
    if (macdBox) macdBox.style.display = state.showMACD ? "" : "none";
    if (state.showRSI) {
      const r = CH.createLineChart(document.getElementById("ch-rsi"));
      if (r) {
        charts.push(r);
        CH.addLine(r, palCH.c[3], 2).setData(CH.indData(data.bars, data.indicators.rsi14));
        CH.addLine(r, palCH.down, 1).setData(data.bars.map((b) => ({ time: Math.floor(b.time / 1000), value: 30 })));
        CH.addLine(r, palCH.up, 1).setData(data.bars.map((b) => ({ time: Math.floor(b.time / 1000), value: 70 })));
        r.timeScale().fitContent();
      }
    }
    if (state.showMACD) {
      const m = CH.createLineChart(document.getElementById("ch-macd"));
      if (m) {
        charts.push(m);
        const histData = data.bars.map((b, k) => {
          const v = data.indicators.macd_hist[k];
          return v === null || v === undefined ? null : { time: Math.floor(b.time / 1000), value: v, color: v >= 0 ? palCH.up : palCH.down };
        }).filter(Boolean);
        CH.addHist(m, { priceLineVisible: false, lastValueVisible: false }).setData(histData);
        CH.addLine(m, palCH.c[0], 2).setData(CH.indData(data.bars, data.indicators.macd_dif));
        CH.addLine(m, palCH.c[2], 2).setData(CH.indData(data.bars, data.indicators.macd_dea));
        m.timeScale().fitContent();
      }
    }
  }

  // 自动刷新（默认关闭，10 秒一次，仅当前页可见时）
  setInterval(() => {
    if (!state.auto || document.visibilityState !== "visible") return;
    if (document.getElementById("ch-candle") && document.querySelector("#page-chart.active")) load();
  }, 10000);

  function setSymbol(sym) {
    state.symbol = String(sym || "").trim().toUpperCase() || "BTC/USDT";
    const input = document.getElementById("ch-symbol");
    if (input) input.value = state.symbol;
    load();
  }

  return { render, refresh() { if (document.getElementById("ch-candle")) load(); }, setSymbol };
})());
