/* ============ 组合回测 + 动态选币（freqtrade 移植） ============ */
App.register("portfolio", (() => {
  const state = { library: [], strategy: "ma_cross", jobs: [], activeJobId: null };

  function stat(label, id, value) {
    return '<div class="card stat-card hover"><div class="stat-label">' + label + '</div><div class="stat-value sm" id="' + id + '">' + value + '</div></div>';
  }
  function miniMetric(label, value) {
    return '<div class="card" style="padding:8px 10px"><div class="stat-label">' + label + '</div><div class="stat-value xs">' + value + '</div></div>';
  }

  function render() {
    const page = document.getElementById("page-portfolio");
    page.innerHTML = `
      <div class="grid grid-4" id="pf-stats">
        ${stat("💼 组合回测任务", "pf-jobs-count", "--")}
        ${stat("🪙 标的数量", "pf-symbols-count", "--")}
        ${stat("🔀 选币方法", "pf-method", "static")}
        ${stat("🛡 开仓上限", "pf-max-open", "--")}
      </div>
      <div class="grid grid-layout-backtest" style="margin-top:16px">
        <div class="side-panel">
          <div class="card">
            <div class="card-title">💼 多币种组合回测</div>
            <div class="hint" style="margin-bottom:8px">在统一时间轴上同时模拟多个币种，共享现金池与开仓数上限（freqtrade 组合回测），避免单标的回测高估收益。</div>
            <div class="field"><label>策略</label><select class="select" id="pf-strategy"></select></div>
            <div class="field"><label>标的（逗号分隔）</label><input class="input" id="pf-symbols" value="BTC/USDT,ETH/USDT,SOL/USDT"></div>
            <div class="input-row">
              <div class="field"><label>周期</label>
                <select class="select" id="pf-timeframe"><option>1m</option><option>5m</option><option>15m</option><option>1h</option><option>4h</option><option selected>1d</option></select>
              </div>
              <div class="field"><label>开仓上限</label><input class="input" id="pf-max-open" type="number" value="3"></div>
            </div>
            <div class="field"><label>策略参数（JSON）</label><textarea class="input" id="pf-params" rows="3" style="font-family:monospace">{&quot;fast&quot;: 10, &quot;slow&quot;: 30, &quot;direction&quot;: &quot;long_only&quot;}</textarea></div>
            <details class="ev-advanced" style="margin-bottom:8px">
              <summary style="font-size:12px;color:var(--text-dim);cursor:pointer">⚙️ 风控 / 回测参数（高级）</summary>
              <div class="input-row-3" style="margin-top:8px">
                <div class="field"><label>仓位比例</label><input class="input" id="pf-pos" type="number" step="0.05" value="0.4"></div>
                <div class="field"><label>止损%</label><input class="input" id="pf-stop" type="number" step="0.01" value="0.06"></div>
                <div class="field"><label>杠杆</label><input class="input" id="pf-lev" type="number" step="0.5" value="1"></div>
              </div>
              <div class="input-row-3" style="margin-top:8px">
                <div class="field"><label>初始资金</label><input class="input" id="pf-capital" type="number" value="10000"></div>
                <div class="field"><label>手续费率</label><input class="input" id="pf-fee" type="number" step="0.0001" value="0.001"></div>
                <div class="field"><label>滑点</label><input class="input" id="pf-slippage" type="number" step="0.0001" value="0.0005"></div>
              </div>
            </details>
            <button class="btn btn-primary btn-block btn-run" id="pf-run">💼 运行组合回测</button>
          </div>

          <div class="card">
            <div class="card-title">🔀 动态选币（pairlist 预览）</div>
            <div class="input-row">
              <div class="field"><label>方法</label>
                <select class="select" id="pf-method"><option value="static">静态列表</option><option value="volume">成交量 Top N</option></select>
              </div>
              <div class="field"><label>数量</label><input class="input" id="pf-num" type="number" value="8"></div>
            </div>
            <div class="input-row-3">
              <div class="field"><label>最小成交额</label><input class="input" id="pf-minvol" type="number" value="1000000"></div>
              <div class="field"><label>最低价</label><input class="input" id="pf-pmin" type="number" value="0.1"></div>
              <div class="field"><label>最高价</label><input class="input" id="pf-pmax" type="number" value="100000"></div>
            </div>
            <div style="display:flex;gap:6px;margin-top:8px">
              <button class="btn btn-sm btn-block" id="pf-preview">🔍 预览选币</button>
              <button class="btn btn-sm btn-block" id="pf-fill">📥 填入标的</button>
            </div>
            <div id="pf-pairlist" style="margin-top:10px"></div>
          </div>
        </div>
        <div>
          <div class="card">
            <div class="card-title">🏆 组合回测任务与结果 <button class="btn btn-sm" id="pf-refresh">⟳ 刷新</button></div>
            <div class="chips" id="pf-job-list" style="margin-bottom:10px"></div>
            <div id="pf-job-detail"></div>
          </div>
        </div>
      </div>
    `;
    document.getElementById("pf-run").addEventListener("click", runPortfolio);
    document.getElementById("pf-refresh").addEventListener("click", refresh);
    document.getElementById("pf-preview").addEventListener("click", previewPairlist);
    document.getElementById("pf-fill").addEventListener("click", fillSymbols);
    loadLibrary();
    refresh();
  }

  function refresh() {
    loadJobs();
  }

  async function loadLibrary() {
    try {
      const { library } = await API.get("/api/strategies/library");
      state.library = library.filter((s) => s.name !== "custom");
      const sel = document.getElementById("pf-strategy");
      sel.innerHTML = state.library.map((s) => '<option value="' + s.name + '">' + s.icon + " " + s.school + " · " + s.master.split("·")[0].trim() + '</option>').join("");
      sel.addEventListener("change", () => {
        state.strategy = sel.value;
        const meta = state.library.find((x) => x.name === state.strategy);
        if (meta) {
          const defaults = {};
          meta.params.forEach((p) => { defaults[p.k] = p.type === "number" ? p.def : (p.def || "long_only"); });
          const el = document.getElementById("pf-params");
          if (el) el.value = JSON.stringify(defaults);
        }
      });
    } catch (e) { /* 忽略 */ }
  }

  function riskPayload() {
    const dir = document.getElementById("pf-params").value.includes("long_short") ? "long_short" : "long_only";
    return {
      max_position_pct: parseFloat(document.getElementById("pf-pos").value) || 0.4,
      stop_loss_pct: parseFloat(document.getElementById("pf-stop").value) || null,
      leverage: parseFloat(document.getElementById("pf-lev").value) || 1,
      trade_direction: dir,
    };
  }

  async function runPortfolio() {
    let params = {};
    try { params = JSON.parse(document.getElementById("pf-params").value || "{}"); } catch (e) { App.toast("策略参数 JSON 格式错误", "error"); return; }
    const symbols = document.getElementById("pf-symbols").value.split(",").map((s) => s.trim()).filter(Boolean);
    if (!symbols.length) { App.toast("请填写至少一个标的", "error"); return; }
    const payload = {
      strategy: state.strategy,
      params,
      symbols,
      data: { source: "db", timeframe: document.getElementById("pf-timeframe").value, days: 730 },
      risk: riskPayload(),
      backtest: {
        initial_capital: parseFloat(document.getElementById("pf-capital").value) || 10000,
        fee_rate: parseFloat(document.getElementById("pf-fee").value) || 0.001,
        slippage: parseFloat(document.getElementById("pf-slippage").value) || 0.0005,
      },
      max_open_trades: parseInt(document.getElementById("pf-max-open").value) || 3,
      align: "inner",
    };
    try {
      const { id } = await API.post("/api/backtest/portfolio", payload);
      App.toast("组合回测已启动 (" + id + ")", "info");
      state.activeJobId = id;
      refresh();
    } catch (e) {
      App.toast("启动失败: " + e.message, "error");
    }
  }

  async function previewPairlist() {
    const method = document.getElementById("pf-method").value;
    const config = {
      method,
      number_assets: parseInt(document.getElementById("pf-num").value) || 8,
      min_volume: parseFloat(document.getElementById("pf-minvol").value) || 0,
      price_min: parseFloat(document.getElementById("pf-pmin").value) || null,
      price_max: parseFloat(document.getElementById("pf-pmax").value) || null,
      min_age_days: 0,
    };
    if (method === "static") config.symbols = document.getElementById("pf-symbols").value.split(",").map((s) => s.trim()).filter(Boolean);
    const box = document.getElementById("pf-pairlist");
    box.innerHTML = '<div class="hint">正在从交易所拉取行情…</div>';
    try {
      const res = await API.post("/api/pairlist/preview", { config, refresh: true });
      state.lastPairs = (res.pairs || []).map((p) => p.symbol);
      setStat("pf-method", method);
      setStat("pf-symbols-count", res.number_assets);
      box.innerHTML = '<div class="hint" style="margin-bottom:6px">' + res.method + " · 选出 " + res.number_assets + " 个标的（按 24h 成交额排序）</div>"
        + '<div class="table-wrap" style="max-height:220px"><table class="table"><thead><tr><th>#</th><th>标的</th><th class="num">24h 成交额</th><th class="num">价格</th><th class="num">24h 涨跌</th></tr></thead><tbody>'
        + (res.pairs || []).map((p) => '<tr><td>' + p.rank + '</td><td>' + p.symbol + '</td><td class="num">' + (p.volume_24h ? "$" + FMT.num(p.volume_24h, 0) : "--") + '</td><td class="num">' + FMT.price(p.price) + '</td><td class="num ' + FMT.cls(p.change_24h) + '">' + (p.change_24h !== null && p.change_24h !== undefined ? FMT.pct(p.change_24h / 100, 2) : "--") + '</td></tr>').join("")
        + '</tbody></table></div>';
    } catch (e) {
      box.innerHTML = '<div class="alert error">选币失败：' + e.message + '</div>';
    }
  }

  function fillSymbols() {
    if (!state.lastPairs || !state.lastPairs.length) { App.toast("请先点击「预览选币」", "error"); return; }
    document.getElementById("pf-symbols").value = state.lastPairs.slice(0, parseInt(document.getElementById("pf-num").value) || 8).join(",");
    setStat("pf-symbols-count", state.lastPairs.length);
    App.toast("已填入 " + state.lastPairs.length + " 个标的", "success");
  }

  function setStat(id, v) {
    const el = document.getElementById(id);
    if (el) el.textContent = v;
  }

  async function loadJobs() {
    try {
      const { jobs } = await API.get("/api/backtest/portfolio/jobs");
      state.jobs = jobs;
      const running = jobs.filter((j) => j.status === "running").length;
      setStat("pf-jobs-count", running ? running + " 个运行中" : "无运行中");
      const list = document.getElementById("pf-job-list");
      if (!list) return;
      list.innerHTML = jobs.length ? jobs.map((j) =>
        '<span class="chip' + (j.id === state.activeJobId ? " active" : "") + '" data-job="' + j.id + '">'
        + (j.status === "running" ? "⏳" : j.status === "done" ? "✅" : "❌") + " " + (j.result ? (j.result.symbols || []).length + " 币" : "") + " · " + FMT.time(j.finished_at || j.created_at) + '</span>'
      ).join("") : '<div class="hint">暂无组合回测任务</div>';
      list.querySelectorAll("[data-job]").forEach((c) => c.addEventListener("click", () => {
        state.activeJobId = c.dataset.job;
        list.querySelectorAll(".chip").forEach((x) => x.classList.remove("active"));
        c.classList.add("active");
        loadJobDetail(c.dataset.job);
      }));
      if (running && state.activeJobId) setTimeout(() => { if (document.getElementById("page-portfolio").classList.contains("active")) loadJobDetail(state.activeJobId); }, 2500);
      if (state.activeJobId) loadJobDetail(state.activeJobId);
      else if (jobs.length) { state.activeJobId = jobs[0].id; loadJobDetail(jobs[0].id); }
    } catch (e) { /* 忽略 */ }
  }

  async function loadJobDetail(jobId) {
    try {
      const job = await API.get("/api/backtest/portfolio/" + jobId);
      const box = document.getElementById("pf-job-detail");
      if (!box) return;
      if (job.status === "running") { box.innerHTML = '<div class="alert info">⏳ 组合回测运行中…</div>'; return; }
      if (job.status === "error") { box.innerHTML = '<div class="alert error">任务失败：' + job.error + '</div>'; return; }
      renderResult(box, job.result);
    } catch (e) { /* 忽略 */ }
  }

  function renderResult(box, r) {
    const m = r.metrics || {};
    const bh = m.buy_hold_return;
    const excess = (m.total_return !== undefined && bh !== undefined && bh !== null) ? m.total_return - bh : null;
    box.innerHTML = `
      <div class="grid grid-2" style="gap:8px">
        ${miniMetric("总收益", FMT.pct(m.total_return))}
        ${miniMetric("夏普", FMT.num(m.sharpe))}
        ${miniMetric("最大回撤", FMT.pct(m.max_drawdown))}
        ${miniMetric("交易数", FMT.num(m.num_trades, 0))}
        ${miniMetric("等权买入持有", bh !== undefined && bh !== null ? FMT.pct(bh) : "--")}
        ${miniMetric("超额收益", excess !== null ? FMT.pct(excess) : "--")}
      </div>
      <div style="display:flex;gap:6px;margin-top:8px">
        <button class="btn btn-sm" id="pf-export-csv">⬇ 导出交易 CSV</button>
        <span class="hint" style="align-self:center">超额收益 = 组合收益 − 等权买入持有</span>
      </div>
      ${sparkline(r.equity_curve || [], r.id)}
      <div class="card-title" style="margin-top:12px">🪙 各币种贡献</div>
      <div class="table-wrap" style="max-height:260px"><table class="table"><thead><tr><th>标的</th><th class="num">交易数</th><th class="num">盈亏</th><th class="num">胜率</th><th class="num">盈亏比</th><th class="num">平均收益%</th></tr></thead>
      <tbody>${Object.entries(r.per_symbol || {}).map(([sym, s]) =>
        '<tr><td>' + sym + '</td><td class="num">' + s.num_trades + '</td><td class="num ' + FMT.cls(s.pnl) + '">' + FMT.usd(s.pnl) + '</td><td class="num">' + FMT.pct(s.win_rate, 1) + '</td><td class="num">' + (s.profit_factor === null ? "--" : s.profit_factor === "inf" ? "∞" : FMT.num(s.profit_factor)) + '</td><td class="num ' + FMT.cls(s.avg_return_pct) + '">' + FMT.pct(s.avg_return_pct / 100, 2) + '</td></tr>'
      ).join("") || '<tr><td colspan="6">无交易</td></tr>'}</tbody></table></div>
      <div class="hint" style="margin-top:8px">平仓原因：${(r.breakdown.by_exit_reason || []).map((b) => b.key + " ×" + b.trades).join("，") || "--"}</div>
    `;
    const csvBtn = document.getElementById("pf-export-csv");
    if (csvBtn) csvBtn.addEventListener("click", () => exportCsv(r));
  }

  function exportCsv(r) {
    const trades = r.trades || [];
    const head = "方向,开仓时间,开仓价,平仓时间,平仓价,数量,手续费,盈亏,收益率%,平仓原因,标的";
    const rows = trades.map((t) => [
      t.side === "long" ? "多" : "空", t.entry_time, t.entry_price, t.exit_time, t.exit_price,
      t.quantity, t.fees, t.pnl, (t.return_pct !== null && t.return_pct !== undefined ? (t.return_pct * 100).toFixed(4) : ""), t.reason, t.symbol,
    ].map((v) => '"' + String(v).replace(/"/g, '""') + '"').join(","));
    const csv = "\ufeff" + [head].concat(rows).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    a.download = "portfolio_trades_" + (r.id || Date.now()) + ".csv";
    a.click();
    URL.revokeObjectURL(a.href);
    App.toast("已导出 " + trades.length + " 笔交易", "success");
  }

  function sparkline(points, seed) {
    if (!points || points.length < 2) return "";
    const w = 700, h = 120, pad = 4;
    const xs = points.map((p) => p[0]);
    const ys = points.map((p) => p[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const spanX = maxX - minX || 1, spanY = maxY - minY || 1;
    const coords = points.map((p) => {
      const x = pad + (p[0] - minX) / spanX * (w - 2 * pad);
      const y = h - pad - (p[1] - minY) / spanY * (h - 2 * pad);
      return x.toFixed(1) + "," + y.toFixed(1);
    });
    const color = ys[ys.length - 1] >= ys[0] ? "#22c55e" : "#ef4444";
    return '<div class="card" style="margin-top:10px"><div class="card-title">📈 组合权益曲线</div><svg viewBox="0 0 ' + w + " " + h + '" style="width:100%;height:120px"><polyline points="' + coords.join(" ") + '" fill="none" stroke="' + color + '" stroke-width="1.5"/></svg></div>';
  }

  return { render, refresh };
})());

