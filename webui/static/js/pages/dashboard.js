/* ============ 仪表盘 ============ */
App.register("dashboard", (() => {
  let equityChart = null;

  function render() {
    const page = document.getElementById("page-dashboard");
    page.innerHTML = `
      <div class="grid grid-4" id="dash-stats">
        ${statCard("模拟盘权益", "dash-equity", "--", "暂无交易循环", "sm")}
        ${statCard("当前信号", "dash-signal", "--", "长线持币", "sm")}
        ${statCard("回测总收益", "dash-ret", "--", "最新一次回测", "sm")}
        ${statCard("最大回撤", "dash-dd", "--", "最新一次回测", "sm")}
      </div>
      <div class="card" id="dash-onboard" style="margin-bottom:16px">
        <div class="card-title"><span>🚀 快速上手（4 步）</span><button class="btn btn-sm" id="dash-onboard-close">知道了，不再显示</button></div>
        <div style="display:flex;gap:12px;flex-wrap:wrap;font-size:12.5px;color:var(--text-dim)">
          <button class="btn btn-sm" data-goto="chart">① 看行情</button>
          <button class="btn btn-sm" data-goto="backtest">② 跑回测</button>
          <button class="btn btn-sm" data-goto="evolution">③ 参数搜索</button>
          <button class="btn btn-sm" data-goto="live">④ 模拟盘 → 实盘</button>
          <span style="align-self:center">建议流程：先看行情 → 经典策略回测 → 参数优化 → 模拟盘验证 → 再考虑实盘</span>
        </div>
      </div>
      <div class="section-title">实时行情</div>
      <div class="grid grid-4" id="dash-tickers">
        ${tickerSkeleton("BTC/USDT")}${tickerSkeleton("ETH/USDT")}${tickerSkeleton("SOL/USDT")}${tickerSkeleton("BNB/USDT")}
      </div>
      <div class="grid grid-2" style="margin-top:16px">
        <div class="card">
          <div class="card-title"><span>最新回测 · 权益曲线</span><span class="badge badge-blue" id="dash-equity-label">加载中…</span></div>
          <div class="chart-canvas sm" id="dash-equity-chart"></div>
        </div>
        <div class="card">
          <div class="card-title"><span>模拟盘状态</span><button class="btn btn-sm btn-primary" id="dash-go-live">前往实盘页</button></div>
          <div id="dash-live-body"><div class="loading"><div class="spinner"></div>加载中…</div></div>
        </div>
      </div>
      <div class="section-title">最近回测记录</div>
      <div class="card" style="padding:0">
        <div class="table-wrap" style="max-height:280px">
          <table class="table" id="dash-runs-table">
            <thead><tr><th>时间</th><th>策略</th><th>标的</th><th>周期</th><th class="num">总收益</th><th class="num">夏普</th><th class="num">回撤</th><th class="num">交易数</th><th></th></tr></thead>
            <tbody></tbody>
          </table>
        </div>
      </div>
    `;
    document.getElementById("dash-go-live").addEventListener("click", () => App.go("live"));
    const onboard = document.getElementById("dash-onboard");
    if (onboard) {
      if (localStorage.getItem("quantx_onboard_dismissed") === "1") onboard.style.display = "none";
      const closeBtn = document.getElementById("dash-onboard-close");
      if (closeBtn) closeBtn.addEventListener("click", () => {
        localStorage.setItem("quantx_onboard_dismissed", "1");
        onboard.style.display = "none";
      });
      onboard.querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => App.go(b.dataset.goto)));
    }
    refresh();
  }

  function statCard(label, id, value, foot, size) {
    return '<div class="card stat-card hover"><div class="stat-label">' + label + '</div><div class="stat-value ' + (size || "") + '" id="' + id + '">' + value + '</div><div class="stat-foot" id="' + id + '-foot">' + foot + '</div></div>';
  }

  function tickerSkeleton(sym) {
    return '<div class="card ticker-card hover" data-sym="' + sym + '" title="点击查看 ' + sym + ' 行情" style="cursor:pointer"><div class="ticker-symbol">' + sym + '</div><div class="ticker-price">--</div><div class="ticker-change">--</div><div class="market-tag">连接中…</div></div>';
  }

  async function refresh() {
    refreshStats();
    refreshTickers();
    refreshRuns();
    refreshLive();
  }

  async function refreshStats() {
    try {
      const live = await API.get("/api/live/status");
      const eq = document.getElementById("dash-equity");
      if (live.equity !== null && live.equity !== undefined) {
        eq.textContent = FMT.usd(live.equity);
        eq.className = "stat-value sm " + FMT.cls(live.equity - (live.start_equity || 0));
        const pnl = live.equity - (live.start_equity || 0);
        document.getElementById("dash-equity-foot").textContent = "运行中 · 盈亏 " + FMT.pctSigned(pnl / (live.start_equity || 1));
      }
      const sg = document.getElementById("dash-signal");
      if (live.running) {
        sg.textContent = live.signal > 0 ? "做多" : live.signal < 0 ? "做空" : "观望";
        sg.className = "stat-value sm " + (live.signal > 0 ? "pos" : live.signal < 0 ? "neg" : "");
        document.getElementById("dash-signal-foot").textContent = "价格 " + FMT.price(live.last_price);
      }
    } catch (e) {
      const eq = document.getElementById("dash-equity");
      if (eq) { eq.textContent = "--"; }
      const f = document.getElementById("dash-equity-foot");
      if (f) f.textContent = "[!] 状态获取失败";
    }
  }

  async function refreshTickers() {
    const symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"];
    try {
      const data = await API.get("/api/tickers?symbols=" + symbols.join(","));
      const box = document.getElementById("dash-tickers");
      if (!box) return;
      box.innerHTML = symbols.map((s) => {
        const d = data[s] || {};
        if (!d.ok) {
          return '<div class="card ticker-card hover" data-sym="' + s + '" title="点击查看 ' + s + ' 行情" style="cursor:pointer"><div class="ticker-symbol">' + s + '</div><div class="ticker-price">--</div><div class="ticker-change neg">离线（数据源不可达）</div><div class="market-tag">请使用合成数据源</div></div>';
        }
        const chg = d.change_pct !== null && d.change_pct !== undefined ? d.change_pct / 100 : null;
        return '<div class="card ticker-card hover" data-sym="' + s + '" title="点击查看 ' + s + ' 行情" style="cursor:pointer"><div class="ticker-symbol">' + s + '</div><div class="ticker-price ' + FMT.cls(chg) + '">' + FMT.price(d.last) + '</div><div class="ticker-change ' + FMT.cls(chg) + '">' + FMT.pctSigned(chg) + '</div><div class="market-tag">Bid ' + FMT.price(d.bid) + ' · Ask ' + FMT.price(d.ask) + '</div></div>';
      }).join("");
      box.querySelectorAll("[data-sym]").forEach((card) => {
        card.addEventListener("click", () => {
          App.go("chart");
          const pg = App.pages.chart;
          if (pg && pg.setSymbol) pg.setSymbol(card.dataset.sym);
        });
      });
    } catch (e) {
      const box = document.getElementById("dash-tickers");
      if (box) {
        box.innerHTML = symbols.map((s) => tickerSkeleton(s)).join("");
        box.querySelectorAll("[data-sym]").forEach((card) => {
          card.addEventListener("click", () => {
            App.go("chart");
            const pg = App.pages.chart;
            if (pg && pg.setSymbol) pg.setSymbol(card.dataset.sym);
          });
        });
      }
    }
  }

  async function refreshRuns() {
    try {
      const { jobs } = await API.get("/api/backtest/jobs");
      const tbody = document.querySelector("#dash-runs-table tbody");
      if (!tbody) return;
      if (!jobs.length) {
        tbody.innerHTML = '<tr><td colspan="9"><div class="empty"><div class="empty-icon">📊</div>还没有回测记录，去「策略回测」跑一次吧</div></td></tr>';
        return;
      }
      tbody.innerHTML = jobs.slice(0, 8).map((j) => {
        const m = j.metrics || {};
        return '<tr><td>' + FMT.time(j.created_at) + '</td><td><span class="badge badge-blue">' + (j.strategy === "custom" ? "自定义" : j.strategy) + '</span></td><td>' + j.symbol + '</td><td>' + j.timeframe + '</td><td class="num ' + FMT.cls(m.total_return) + '">' + FMT.pctSigned(m.total_return) + '</td><td class="num">' + FMT.num(m.sharpe) + '</td><td class="num ' + FMT.cls(m.max_drawdown) + '">' + FMT.pct(m.max_drawdown) + '</td><td class="num">' + (m.num_trades ?? "--") + '</td><td><button class="btn btn-sm" data-load="' + j.id + '">查看</button></td></tr>';
      }).join("");
      tbody.querySelectorAll("[data-load]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const job = await API.get("/api/backtest/result/" + btn.dataset.load);
          if (job.result) App.state.latestResult = job.result;
          App.go("backtest");
        });
      });
      const done = jobs.find((j) => j.status === "done" && j.metrics);
      if (done && done.metrics) {
        document.getElementById("dash-equity-label").textContent = done.strategy + " · " + done.symbol + " " + done.timeframe;
        const m = done.metrics;
        setStat("dash-ret", FMT.pctSigned(m.total_return), m.total_return, "买入持有 " + FMT.pctSigned(m.buy_hold_return) + " · 期末 " + FMT.usd(m.final_equity));
        setStat("dash-dd", FMT.pct(m.max_drawdown), m.max_drawdown, "最大回撤");
        const el = document.getElementById("dash-equity-chart");
        if (equityChart) { equityChart.remove(); equityChart = null; }
        const r = await API.get("/api/backtest/result/" + done.id);
        if (r.result && r.result.equity_curve && el) {
          CH.clearRegistry();
          CH.setFallback(el, { series: [{ color: CH.palette().c[0], points: r.result.equity_curve, area: true }] });
          equityChart = CH.createChart(el);
          if (!equityChart) return;
          const line = equityChart.addAreaSeries({ lineColor: CH.palette().c[0], topColor: "rgba(76,141,255,0.25)", bottomColor: "rgba(76,141,255,0)", lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
          line.setData(r.result.equity_curve.map(([ts, v]) => ({ time: Math.floor(ts / 1000), value: v })));
          equityChart.timeScale().fitContent();
        }
      }
    } catch (e) {
      const tbody = document.querySelector("#dash-runs-table tbody");
      if (tbody) tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--red)">回测记录加载失败：' + e.message + '</td></tr>';
    }
  }

  function setStat(id, text, value, foot) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.className = "stat-value sm " + FMT.cls(value);
    const f = document.getElementById(id + "-foot");
    if (f) f.textContent = foot;
  }

  async function refreshLive() {
    try {
      const d = await API.get("/api/live/status");
      const body = document.getElementById("dash-live-body");
      if (!body) return;
      if (!d.running) {
        body.innerHTML = '<div class="empty"><div class="empty-icon">⚡</div>模拟盘未运行<br><span style="font-size:11px">可在「实盘交易」页启动</span></div>';
        return;
      }
      const pnl = d.equity !== null && d.start_equity ? d.equity - d.start_equity : 0;
      const pct = d.start_equity ? pnl / d.start_equity : 0;
      body.innerHTML = '<div class="grid grid-3">'
        + '<div><div class="stat-label">权益</div><div class="stat-value sm ' + FMT.cls(pnl) + '">' + FMT.usd(d.equity) + '</div></div>'
        + '<div><div class="stat-label">盈亏</div><div class="stat-value sm ' + FMT.cls(pnl) + '">' + FMT.pctSigned(pct) + '</div></div>'
        + '<div><div class="stat-label">信号</div><div class="stat-value sm ' + (d.signal > 0 ? "pos" : d.signal < 0 ? "neg" : "") + '">' + (d.signal > 0 ? "做多" : d.signal < 0 ? "做空" : "观望") + '</div></div>'
        + '</div><div style="margin-top:12px;font-size:12px;color:var(--text-dim)">' + d.symbol + ' @ ' + d.timeframe + ' · 最新价 ' + FMT.price(d.last_price) + ' · ' + d.mode + '</div>'
        + (d.circuit_breaker_active ? '<div class="alert alert-danger" style="margin-top:10px">[熔断] 日亏损熔断中，已暂停开仓</div>' : '');
    } catch (e) {
      const body = document.getElementById("dash-live-body");
      if (body) body.innerHTML = '<div class="empty"><div class="empty-icon">!</div>状态获取失败<br><span style="font-size:11px;color:var(--red)">' + e.message + '</span></div>';
    }
  }

  return { render, refresh };
})());
