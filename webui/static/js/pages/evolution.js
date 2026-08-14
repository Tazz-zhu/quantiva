/* ============ 策略进化实验室（参数优化 / 迭代日志 / 交易分析） ============ */
App.register("evolution", (() => {
  const state = { library: [], strategy: "ma_cross", jobs: [], activeJobId: null, pollTimer: null, lastIterations: [], lastTrades: [] };
  const TARGETS = [["sharpe", "夏普比率"], ["total_return", "总收益率"], ["annual_return", "年化收益率"], ["win_rate", "胜率"], ["profit_factor", "盈亏比"]];
  const PRESETS = { quick: { label: "快速", max: 12 }, standard: { label: "标准", max: 40 }, deep: { label: "深度", max: 120 } };
  const KIND_FILTERS = [["all", "全部"], ["optimize", "🧬 参数优化"], ["auto_analysis", "🔬 自动分析"], ["manual", "✍️ 手动"]];

  function render() {
    const page = document.getElementById("page-evolution");
    page.innerHTML = `
      <div class="grid grid-4" id="ev-stats">
        ${evStat("🧬 进化状态", "ev-status", "--")}
        ${evStat("📦 已保存交易", "ev-trades-count", "--")}
        ${evStat("💡 迭代记录", "ev-iterations-count", "--")}
        ${evStat("🕘 上次自动分析", "ev-last", "--")}
      </div>
      <div class="grid grid-layout-backtest" style="margin-top:16px">
        <div class="side-panel">
          <div class="card">
            <div class="card-title">🧬 参数优化（自我迭代）</div>
            <div class="field"><label>策略</label><select class="select" id="ev-strategy"></select></div>
            <div class="field"><label>优化目标</label>
              <select class="select" id="ev-target">${TARGETS.map(([v, l]) => '<option value="' + v + '">' + l + '</option>').join("")}</select>
            </div>
            <div class="field"><label>数据源</label>
              <select class="select" id="ev-source">
                <option value="auto">交易所真实行情</option>
              </select>
            </div>
            <div class="input-row">
              <div class="field"><label>标的</label><input class="input" id="ev-symbol" value="BTC/USDT"></div>
              <div class="field"><label>周期</label>
                <select class="select" id="ev-timeframe"><option>1m</option><option>5m</option><option>15m</option><option>1h</option><option>4h</option><option selected>1d</option></select>
              </div>
            </div>
            <div class="input-row">
              <div class="field"><label>回看天数</label><input class="input" id="ev-days" type="number" value="300"></div>
              
            </div>
            <div class="divider"></div>
            <div class="card-title" style="margin-bottom:8px">🔧 候选参数（网格搜索）</div>
            <div id="ev-ranges"></div>
            <div class="field"><label>搜索档位</label>
              <div class="chips" id="ev-preset">
                <span class="chip active" data-preset="quick">快速</span>
                <span class="chip" data-preset="standard">标准</span>
                <span class="chip" data-preset="deep">深度</span>
              </div>
              <div class="hint">档位自动控制最大组合数（快速 12 / 标准 40 / 深度 120），可手动调整。</div>
            </div>
            <div class="field"><label>最大组合数</label><input class="input" id="ev-max" type="number" value="12"></div>
            <div class="input-row-3">
              <div class="field"><label>样本外验证%</label><input class="input" id="ev-holdout" type="number" step="5" value="25"></div>
              <div class="field"><label>最小交易数</label><input class="input" id="ev-min-trades" type="number" value="5"></div>
              <div class="field"></div>
            </div>
            <div class="hint">样本外验证：后 N% 数据用于防过拟合检验（训练段选优、样本外段验证）；交易数不足的组合被过滤。</div>
            <details class="ev-advanced" style="margin-bottom:10px">
              <summary style="font-size:12px;color:var(--text-dim);cursor:pointer">⚙️ 回测 / 风控参数（高级）</summary>
              <div class="input-row-3" style="margin-top:8px">
                <div class="field"><label>初始资金</label><input class="input" id="ev-capital" type="number" value="10000"></div>
                <div class="field"><label>手续费率</label><input class="input" id="ev-fee" type="number" step="0.0001" value="0.001"></div>
                <div class="field"><label>滑点</label><input class="input" id="ev-slippage" type="number" step="0.0001" value="0.0005"></div>
              </div>
              <div class="input-row-3" style="margin-top:8px">
                <div class="field"><label>仓位比例</label><input class="input" id="ev-pos" type="number" step="0.05" value="0.5"></div>
                <div class="field"><label>杠杆</label><input class="input" id="ev-lev" type="number" step="0.5" value="2"></div>
                <div class="field"><label>ATR止损</label><input class="input" id="ev-atr" type="number" step="0.5" value="2"></div>
              </div>
            </details>
            <button class="btn btn-primary btn-block btn-run" id="ev-run">⚡ 开始参数搜索</button>
            <div id="ev-progress" style="display:none;margin-top:10px"></div>
            <div class="hint">对每个参数组合自动回测并按目标排序，最优组合自动写入迭代日志。</div>
          </div>
          <div class="card">
            <div class="card-title">📜 迭代日志 <button class="btn btn-sm" id="ev-analyze-now">🔬 立即分析交易</button></div>
            <div class="chips" id="ev-kind-filter" style="margin-bottom:8px">
              ${KIND_FILTERS.map(([v, l]) => '<span class="chip' + (v === "all" ? " active" : "") + '" data-kind="' + v + '">' + l + '</span>').join("")}
            </div>
            <div id="ev-iterations" style="max-height:360px;overflow-y:auto;display:flex;flex-direction:column;gap:8px"></div>
          </div>
        </div>
        <div>
          <div class="card">
            <div class="card-title">🏆 优化任务与结果 <button class="btn btn-sm" id="ev-refresh-jobs">⟳ 刷新</button></div>
            <div class="chips" id="ev-job-list" style="margin-bottom:10px"></div>
            <div class="table-wrap" style="max-height:380px">
              <table class="table">
                <thead><tr><th>参数组合</th><th class="num">目标值</th><th class="num">总收益</th><th class="num">夏普</th><th class="num">回撤</th><th class="num">胜率</th><th class="num">恢复因子</th><th class="num">交易数</th><th>操作</th></tr></thead>
                <tbody id="ev-results"></tbody>
              </table>
            </div>
            <div id="ev-result-empty" class="empty" style="padding:14px">暂无优化结果，运行一次参数搜索后在这里展示 Top 组合</div>
          </div>
          <div class="grid grid-2" style="margin-top:16px">
            <div class="card">
              <div class="card-title">📦 已保存交易统计</div>
              <div id="ev-trade-stats"></div>
            </div>
            <div class="card">
              <div class="card-title">🧾 最近交易记录 <button class="btn btn-sm" id="ev-export-csv" style="float:right">⬇ 导出 CSV</button></div>
              <div class="chips" id="ev-trade-filter" style="margin-bottom:8px">
                <span class="chip active" data-src="all">全部</span>
                <span class="chip" data-src="paper">模拟盘</span>
                <span class="chip" data-src="live">实盘</span>
              </div>
              <div class="table-wrap" style="max-height:320px">
                <table class="table">
                  <thead><tr><th>策略</th><th>方向</th><th class="num">收益%</th><th class="num">盈亏</th><th>原因</th><th>来源</th></tr></thead>
                  <tbody id="ev-trades-body"></tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
    document.getElementById("ev-run").addEventListener("click", runOptimize);
    document.getElementById("ev-analyze-now").addEventListener("click", analyzeNow);
    document.getElementById("ev-refresh-jobs").addEventListener("click", refresh);
    const evCsvBtn = document.getElementById("ev-export-csv");
    if (evCsvBtn) evCsvBtn.addEventListener("click", () => window.open("/api/evolution/trades.csv", "_blank"));
    document.getElementById("ev-preset").querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
      document.getElementById("ev-preset").querySelectorAll(".chip").forEach((x) => x.classList.remove("active"));
      c.classList.add("active");
      document.getElementById("ev-max").value = PRESETS[c.dataset.preset].max;
    }));
    document.getElementById("ev-kind-filter").querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
      document.getElementById("ev-kind-filter").querySelectorAll(".chip").forEach((x) => x.classList.remove("active"));
      c.classList.add("active");
      renderIterations(state.lastIterations, c.dataset.kind);
    }));
    document.getElementById("ev-trade-filter").querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
      document.getElementById("ev-trade-filter").querySelectorAll(".chip").forEach((x) => x.classList.remove("active"));
      c.classList.add("active");
      renderTrades(state.lastTrades, c.dataset.src);
    }));
    loadLibrary();
    refresh();
  }

  function evStat(label, id, value) {
    return '<div class="card stat-card hover"><div class="stat-label">' + label + '</div><div class="stat-value sm" id="' + id + '">' + value + '</div></div>';
  }

  async function loadLibrary() {
    try {
      const { library } = await API.get("/api/strategies/library");
      state.library = library.filter((s) => s.name !== "custom");
      const sel = document.getElementById("ev-strategy");
      sel.innerHTML = state.library.map((s) => '<option value="' + s.name + '">' + s.icon + " " + s.school + " · " + s.master.split("·")[0].trim() + '</option>').join("");
      sel.addEventListener("change", () => { state.strategy = sel.value; renderRanges(); });
      renderRanges();
    } catch (e) { /* 忽略 */ }
  }

  function renderRanges() {
    const meta = state.library.find((s) => s.name === state.strategy);
    const box = document.getElementById("ev-ranges");
    if (!meta || !box) return;
    const numParams = meta.params.filter((p) => p.type === "number");
    if (!numParams.length) { box.innerHTML = '<div class="hint">该策略无可搜索的数值参数。</div>'; return; }
    box.innerHTML = numParams.map((p) =>
      '<div class="ev-row" style="margin-bottom:8px"><div class="field" style="flex:1"><label>' + p.label + '（候选值，逗号分隔）</label>'
      + '<div style="display:flex;gap:6px"><input class="input ev-range" data-param="' + p.k + '" placeholder="如 10,20,30" style="flex:1">'
      + '<button class="btn btn-sm" data-gen="' + p.k + '" title="生成推荐序列">⚡</button></div></div></div>'
    ).join("") + '<div class="hint">留空使用默认参数；⚡ 一键生成围绕当前值的推荐序列。</div>';
    numParams.forEach((p) => {
      const el = box.querySelector('[data-param="' + p.k + '"]');
      if (el) el.value = String(p.def);
    });
    box.querySelectorAll("[data-gen]").forEach((btn) => btn.addEventListener("click", () => {
      const p = numParams.find((x) => x.k === btn.dataset.gen);
      if (!p) return;
      const d = p.def;
      const step = p.step !== undefined ? p.step : (d >= 10 ? 5 : 1);
      const seq = [];
      for (let v = d - step * 2; v <= d + step * 2 + 1e-9; v += step) if (v > 0) seq.push(Math.round(v * 100) / 100);
      const el = box.querySelector('[data-param="' + p.k + '"]');
      if (el) { el.value = seq.join(","); App.toast("已生成推荐序列：" + seq.join(","), "success"); }
    }));
  }
  async function runOptimize() {
    const ranges = {};
    document.querySelectorAll(".ev-range").forEach((el) => {
      const vals = el.value.split(",").map((s) => parseFloat(s.trim())).filter((v) => !Number.isNaN(v));
      if (vals.length) ranges[el.dataset.param] = vals;
    });
    const meta = state.library.find((s) => s.name === state.strategy);
    if (!meta) { App.toast("策略库未加载", "error"); return; }
    const directionParam = meta.params.find((p) => p.type === "select");
    if (directionParam) ranges[directionParam.k] = [directionParam.def || "long_only"];
    const payload = {
      strategy: state.strategy,
      param_ranges: ranges,
      data: {
        source: document.getElementById("ev-source").value,
        symbol: document.getElementById("ev-symbol").value.trim(),
        timeframe: document.getElementById("ev-timeframe").value,
        days: parseInt(document.getElementById("ev-days").value) || 300,
        backtest: {
          initial_capital: parseFloat(document.getElementById("ev-capital").value) || 10000,
          fee_rate: parseFloat(document.getElementById("ev-fee").value) || 0.001,
          slippage: parseFloat(document.getElementById("ev-slippage").value) || 0.0005,
        },
      },
      risk: {
        max_position_pct: parseFloat(document.getElementById("ev-pos").value) || 0.5,
        leverage: parseFloat(document.getElementById("ev-lev").value) || 2,
        atr_stop_mult: parseFloat(document.getElementById("ev-atr").value) || 2,
        trade_direction: "long_only",
      },
      target: document.getElementById("ev-target").value,
      max_combos: parseInt(document.getElementById("ev-max").value) || 40,
      holdout_ratio: parseFloat(document.getElementById("ev-holdout").value) / 100 || 0.25,
      min_trades: parseInt(document.getElementById("ev-min-trades").value) || 0,
    };
    try {
      const { id } = await API.post("/api/evolution/optimize", payload);
      App.toast("参数搜索已启动 (" + id + ")", "info");
      pollJob(id);
    } catch (e) {
      App.toast("启动失败: " + e.message, "error");
    }
  }

  function showProgress(progress) {
    const box = document.getElementById("ev-progress");
    if (!box) return;
    box.style.display = "block";
    let done = 0, total = 0;
    const m = String(progress || "").match(/(\d+)\/(\d+)/);
    if (m) { done = parseInt(m[1], 10); total = parseInt(m[2], 10); }
    const pct = total > 0 ? Math.round(done / total * 100) : 0;
    box.innerHTML = '<div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text-dim);margin-bottom:4px"><span>参数搜索中…</span><span>' + done + " / " + total + "（" + pct + "%）</span></div>" + '<div class="progress"><i style="width:' + pct + '%"></i></div>';
  }

  function hideProgress() {
    const box = document.getElementById("ev-progress");
    if (box) box.style.display = "none";
  }

  function pollJob(id) {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.activeJobId = id;
    const t = setInterval(async () => {
      try {
        const job = await API.get("/api/evolution/result/" + id);
        if (job.status === "running") {
          showProgress(job.progress);
          const btn = document.getElementById("ev-run");
          if (btn) btn.textContent = "⏳ 搜索中 " + (job.progress || "");
          return;
        }
        clearInterval(t);
        state.pollTimer = null;
        hideProgress();
        const btn = document.getElementById("ev-run");
        if (btn) btn.textContent = "⚡ 开始参数搜索";
        if (job.status === "error") {
          App.toast("优化失败: " + job.error, "error", 6000);
        } else {
          App.toast("参数搜索完成 ✅ 最优组合已写入迭代日志", "success");
          refresh();
        }
      } catch (e) {
        clearInterval(t);
        state.pollTimer = null;
        hideProgress();
      }
    }, 1500);
    state.pollTimer = t;
  }

  async function refresh() {
    try {
      const st = await API.get("/api/evolution/status");
      setText("ev-status", st.auto_running ? "🧬 自我进化中" : "⚪ 未运行");
      setText("ev-trades-count", st.trades_count);
      setText("ev-iterations-count", st.iterations_count);
      setText("ev-last", st.last_auto_analyze ? FMT.time(st.last_auto_analyze) : "--");
      const stats = await API.get("/api/evolution/trades/stats");
      renderTradeStats(stats);
      const trades = await API.get("/api/evolution/trades?limit=50");
      state.lastTrades = trades.trades;
      renderTrades(state.lastTrades, document.querySelector("#ev-trade-filter .chip.active") ? document.querySelector("#ev-trade-filter .chip.active").dataset.src : "all");
      const its = await API.get("/api/evolution/iterations?limit=50");
      state.lastIterations = its.iterations;
      renderIterations(state.lastIterations, document.querySelector("#ev-kind-filter .chip.active") ? document.querySelector("#ev-kind-filter .chip.active").dataset.kind : "all");
      const jobs = await API.get("/api/evolution/jobs");
      const prevStatus = state.prevJobStatus || {};
      jobs.jobs.forEach((j) => {
        if (prevStatus[j.id] === "running" && j.status === "done" && window.notifyUser) {
          window.notifyUser("策略进化完成", (j.params && j.params.strategy ? j.params.strategy : "参数搜索") + " 已完成");
        }
      });
      state.prevJobStatus = {};
      jobs.jobs.forEach((j) => { state.prevJobStatus[j.id] = j.status; });
      state.jobs = jobs.jobs;
      renderJobs();
    } catch (e) {
      const st = document.getElementById("ev-status");
      if (st) st.textContent = "[!] 状态获取失败";
      const box = document.getElementById("ev-job-list");
      if (box) box.innerHTML = '<span class="hint" style="color:var(--red)">加载失败：' + e.message + '</span>';
    }
  }

  function renderJobs() {
    const box = document.getElementById("ev-job-list");
    if (!box) return;
    if (!state.jobs.length) { box.innerHTML = '<span class="hint">暂无任务</span>'; return; }
    if (!state.activeJobId || !state.jobs.some((j) => j.id === state.activeJobId)) {
      const doneJob = state.jobs.find((j) => j.status === "done") || state.jobs[0];
      state.activeJobId = doneJob ? doneJob.id : null;
    }
    box.innerHTML = state.jobs.slice(0, 8).map((j) => {
      const cls = j.id === state.activeJobId ? "chip active job-chip" : "chip job-chip";
      const label = j.status === "running" ? "⏳ " + (j.progress || "运行中") : j.status === "error" ? "❌ 失败" : "✅ " + j.params.strategy;
      return '<span class="' + cls + '" data-job="' + j.id + '" title="' + FMT.time(j.created_at) + '">' + label + '</span>';
    }).join("");
    box.querySelectorAll("[data-job]").forEach((el) => el.addEventListener("click", async () => {
      state.activeJobId = el.dataset.job;
      renderJobs();
      const job = await API.get("/api/evolution/result/" + state.activeJobId);
      const empty = document.getElementById("ev-result-empty");
      const tbody = document.getElementById("ev-results");
      if (!empty || !tbody) return;
      if (job.status === "done" && job.result) { empty.style.display = "none"; renderResults(job.result); }
      else if (job.status === "error") { empty.style.display = ""; empty.innerHTML = '<div class="empty" style="padding:14px">❌ 任务失败：' + esc(job.error || "") + '</div>'; }
      else { empty.style.display = ""; empty.innerHTML = '<div class="empty" style="padding:14px">⏳ 任务运行中…</div>'; tbody.innerHTML = ""; }
    }));
    // auto-load active job result
    const active = state.jobs.find((j) => j.id === state.activeJobId);
    if (active && active.status === "done") {
      API.get("/api/evolution/result/" + state.activeJobId).then((job) => {
        if (job.result) { const empty = document.getElementById("ev-result-empty"); if (empty) empty.style.display = "none"; renderResults(job.result); }
      }).catch(() => {});
    } else if (active && active.status === "error") {
      const empty = document.getElementById("ev-result-empty");
      if (empty) { empty.style.display = ""; empty.innerHTML = '<div class="empty" style="padding:14px">❌ 最近任务失败</div>'; }
    } else if (active && active.status === "running") {
      const empty = document.getElementById("ev-result-empty");
      if (empty) { empty.style.display = ""; empty.innerHTML = '<div class="empty" style="padding:14px">⏳ 任务运行中，完成后自动展示结果</div>'; }
    }
  }

  function renderResults(result) {
    const tbody = document.getElementById("ev-results");
    if (!tbody || !result || !result.results) return;
    const rows = result.results || [];
    const oos = result.oos_metrics;
    const ism = result.in_sample_metrics;
    let oosRow = "";
    if (oos && ism) {
      const isSharpe = ism.sharpe || 0;
      const oosSharpe = oos.sharpe || 0;
      const warn = isSharpe > 0 && oosSharpe < isSharpe * 0.5;
      oosRow = '<tr><td colspan="9" style="font-size:12px;color:var(--text-dim);border-bottom:1px solid rgba(251,191,36,.3)">样本外验证（holdout ' + Math.round((result.holdout_ratio || 0) * 100) + '%）：收益 <b class="' + FMT.cls(oos.total_return) + '">' + FMT.pctSigned(oos.total_return) + '</b> | 夏普 <b>' + FMT.num(oos.sharpe) + '</b> | 回撤 <b class="neg">' + FMT.pct(oos.max_drawdown) + '</b> | 交易 ' + oos.num_trades + (warn ? ' <span style="color:var(--amber)">⚠️ 过拟合警示：OOS 夏普明显低于样本内</span>' : '') + '</td></tr>';
    }
    tbody.innerHTML = oosRow + rows.slice(0, 12).map((r, i) => {
      if (!r.metrics) return '<tr><td colspan="9" class="dim">' + (r.params ? JSON.stringify(r.params) : "?") + " 失败</td></tr>";
      const m = r.metrics;
      return '<tr style="' + (i === 0 ? "background:rgba(251,191,36,.06)" : "") + '">'
        + '<td style="font-size:11px;font-family:var(--mono)">' + (i === 0 ? "🏆 " : "") + JSON.stringify(r.params) + '</td>'
        + '<td class="num ' + FMT.cls(r.target_value) + '">' + FMT.num(r.target_value) + '</td>'
        + '<td class="num ' + FMT.cls(m.total_return) + '">' + FMT.pctSigned(m.total_return) + '</td>'
        + '<td class="num ' + FMT.cls(m.sharpe) + '">' + FMT.num(m.sharpe) + '</td>'
        + '<td class="num neg">' + FMT.pct(m.max_drawdown) + '</td>'
        + '<td class="num">' + FMT.pct(m.win_rate) + '</td>'
        + '<td class="num ' + FMT.cls(m.recovery_factor) + '">' + FMT.num(m.recovery_factor) + '</td>'
        + '<td class="num">' + m.num_trades + '</td>'
        + '<td><button class="btn btn-sm" data-apply="' + i + '">应用回测</button></td></tr>';
    }).join("");
    tbody.querySelectorAll("[data-apply]").forEach((el) => el.addEventListener("click", () => {
      applyToBacktest(state.strategy, rows[parseInt(el.dataset.apply, 10)].params);
    }));
  }

  function applyToBacktest(strategy, params) {
    App.state.applyParams = { strategy, params };
    App.toast("参数已应用，前往回测页验证", "success");
    App.go("backtest");
  }
  function renderTradeStats(stats) {
    const box = document.getElementById("ev-trade-stats");
    if (!box) return;
    const t = stats.total || {};
    const byStrat = stats.by_strategy || [];
    const byReason = stats.by_reason || [];
    const totalWins = byStrat.reduce((s, x) => s + (x.wins || 0), 0);
    const winRate = t.count ? totalWins / t.count : 0;
    const avgPnl = t.count ? (t.total_pnl || 0) / t.count : 0;
    const maxAbs = Math.max(1, ...byReason.map((r) => Math.abs(r.pnl || 0)));
    box.innerHTML = '<div class="metrics-grid" style="grid-template-columns:repeat(2,1fr)">'
      + '<div class="metric"><div class="metric-label">总交易</div><div class="metric-value">' + t.count + '</div></div>'
      + '<div class="metric"><div class="metric-label">净盈亏</div><div class="metric-value ' + FMT.cls(t.total_pnl) + '">' + FMT.usd(t.total_pnl) + '</div></div>'
      + '<div class="metric"><div class="metric-label">胜率</div><div class="metric-value">' + FMT.pct(winRate) + '</div></div>'
      + '<div class="metric"><div class="metric-label">平均单笔</div><div class="metric-value ' + FMT.cls(avgPnl) + '">' + FMT.usd(avgPnl) + '</div></div>'
      + '</div>';
    if (byStrat.length) {
      box.innerHTML += '<div class="section-title">按策略</div>'
        + '<div class="table-wrap" style="max-height:180px"><table class="table"><tr><th>策略</th><th class="num">笔数</th><th class="num">胜率</th><th class="num">盈亏</th></tr>'
        + byStrat.map((s) => '<tr><td>' + s.strategy + '</td><td class="num">' + s.count + '</td><td class="num">' + FMT.pct(s.win_rate) + '</td><td class="num ' + FMT.cls(s.pnl) + '">' + FMT.usd(s.pnl) + '</td></tr>').join("")
        + '</table></div>';
    }
    box.innerHTML += '<div class="section-title" style="margin-top:10px">按平仓原因</div>'
      + (byReason.length ? byReason.map((r) => {
          const pct = Math.round(Math.abs(r.pnl || 0) / maxAbs * 100);
          return '<div class="bar-row"><span class="bar-label">' + r.reason + '（' + r.count + '笔）</span>'
          + '<div class="bar-track"><div class="bar-fill ' + ((r.pnl || 0) >= 0 ? 'pos' : 'neg') + '" style="width:' + pct + '%"></div></div>'
          + '<span class="bar-val ' + FMT.cls(r.pnl) + '">' + FMT.usd(r.pnl) + '</span></div>';
        }).join("") : '<div class="hint">暂无数据</div>');
  }

  function renderTrades(trades, filter) {
    const tbody = document.getElementById("ev-trades-body");
    if (!tbody) return;
    const list = filter && filter !== "all" ? trades.filter((t) => t.source === filter) : trades;
    tbody.innerHTML = list.length ? list.map((t) => {
      const sideBadge = t.side === "long" ? '<span class="badge badge-green">多</span>' : '<span class="badge badge-red">空</span>';
      return '<tr><td style="font-size:11px">' + t.strategy + '</td><td>' + sideBadge + '</td><td class="num ' + FMT.cls(t.return_pct) + '">' + FMT.pctSigned(t.return_pct) + '</td><td class="num ' + FMT.cls(t.pnl) + '">' + FMT.usd(t.pnl) + '</td><td><span class="badge badge-gray">' + t.reason + '</span></td><td style="font-size:11px;color:var(--text-dim)">' + t.source + '</td></tr>';
    }).join("") : '<tr><td colspan="6" style="text-align:center;color:var(--text-faint)">暂无交易（实盘/模拟盘平仓后自动保存）</td></tr>';
  }

  function renderIterations(items, kind) {
    const box = document.getElementById("ev-iterations");
    if (!box) return;
    const list = kind && kind !== "all" ? items.filter((it) => it.kind === kind) : items;
    const KIND = { optimize: ["🧬", "参数优化"], auto_analysis: ["🔬", "自动分析"], manual: ["✍️", "手动记录"] };
    box.innerHTML = list.length ? list.map((it) => {
      const [icon, label] = KIND[it.kind] || ["📝", it.kind];
      const m = it.metrics || {};
      const chips = [];
      if (m.total_return !== undefined) chips.push("收益 " + (m.total_return * 100).toFixed(1) + "%");
      if (m.sharpe !== undefined) chips.push("夏普 " + FMT.num(m.sharpe));
      if (m.max_drawdown !== undefined) chips.push("回撤 " + FMT.pct(m.max_drawdown));
      return '<div class="log-item info" style="cursor:pointer" data-it="' + it.id + '">'
        + '<div style="display:flex;align-items:center;gap:8px;width:100%"><span class="log-time">' + FMT.time(it.ts) + '</span><span class="badge badge-blue">' + icon + " " + label + '</span><span style="flex:1;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + it.title + '</span></div>'
        + (chips.length ? '<div style="display:flex;gap:6px;margin-top:6px">' + chips.map((c) => '<span class="badge badge-gray" style="font-size:10px">' + c + '</span>').join("") + '</div>' : "")
        + '</div>';
    }).join("") : '<div class="empty" style="padding:16px">暂无迭代记录</div>';
    box.querySelectorAll("[data-it]").forEach((el) => el.addEventListener("click", () => showIteration(el.dataset.it)));
  }

  async function showIteration(id) {
    try {
      const it = await API.get("/api/evolution/iterations/" + id);
      const m = it.metrics || {};
      const params = it.params || {};
      const modal = EL('<div class="card" style="position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);width:680px;max-width:92vw;max-height:82vh;overflow:auto;z-index:100;box-shadow:0 20px 60px rgba(0,0,0,.6)">'
        + '<div class="card-title">' + esc(it.title || "迭代详情") + ' <button class="btn btn-sm btn-danger" id="it-close" style="margin-left:auto">×</button></div>'
        + '<div style="font-size:12px;color:var(--text-dim);margin-bottom:10px">' + FMT.time(it.ts) + " · " + it.kind + " · " + it.strategy + '</div>'
        + (Object.keys(m).length ? '<div class="section-title">指标</div><div class="metrics-grid" style="grid-template-columns:repeat(3,1fr)">' + Object.entries(m).map(([k, v]) => '<div class="metric"><div class="metric-label">' + k + '</div><div class="metric-value" style="font-size:13px">' + (typeof v === "number" ? FMT.num(v) : esc(String(v))) + '</div></div>').join("") + '</div>' : "")
        + (Object.keys(params).length ? '<div class="section-title">参数</div><div style="font-family:var(--mono);font-size:12px;background:rgba(0,0,0,.25);padding:10px;border-radius:8px;white-space:pre-wrap">' + esc(JSON.stringify(params, null, 2)) + '</div>' : "")
        + '<div class="section-title">分析结论</div><div style="white-space:pre-wrap;font-size:12.5px;line-height:1.7;background:rgba(0,0,0,.2);padding:12px;border-radius:8px">' + esc(it.conclusion || "无") + '</div>'
        + '<div class="section-title">经验沉淀</div><div style="white-space:pre-wrap;font-size:12.5px;line-height:1.7;background:rgba(124,92,255,.08);padding:12px;border-radius:8px" id="it-exp">' + esc(it.experience || "（暂无）") + '</div>'
        + '<div style="display:flex;gap:8px;margin-top:12px"><input class="input" id="it-exp-input" placeholder="添加一条经验总结…" style="flex:1"><button class="btn btn-sm btn-primary" id="it-exp-add">＋ 追加经验</button></div>'
        + (it.kind === "optimize" && Object.keys(params).length ? '<div style="margin-top:10px"><button class="btn btn-primary btn-sm btn-block" id="it-apply">🔄 应用此参数到回测验证</button></div>' : "")
        + '</div>');
      document.body.appendChild(modal);
      const close = () => modal.remove();
      modal.querySelector("#it-close").addEventListener("click", close);
      modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
      modal.querySelector("#it-exp-add").addEventListener("click", async () => {
        const text = modal.querySelector("#it-exp-input").value.trim();
        if (!text) return;
        try {
          await API.post("/api/evolution/iterations/" + id + "/experience", { text });
          const updated = await API.get("/api/evolution/iterations/" + id);
          modal.querySelector("#it-exp").textContent = updated.experience || "（暂无）";
          App.toast("经验已沉淀 ✅", "success");
        } catch (e) { App.toast("失败: " + e.message, "error"); }
      });
      const applyBtn = modal.querySelector("#it-apply");
      if (applyBtn) applyBtn.addEventListener("click", () => { close(); applyToBacktest(it.strategy, params); });
    } catch (e) { /* 忽略 */ }
  }

  async function analyzeNow() {
    const btn = document.getElementById("ev-analyze-now");
    btn.disabled = true;
    btn.textContent = "分析中…";
    try {
      const res = await API.post("/api/evolution/analyze", {});
      App.toast("分析完成，经验已写入迭代日志 ✅", "success");
      refresh();
    } catch (e) {
      App.toast("分析失败: " + e.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "🔬 立即分析交易";
    }
  }

  function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }
  function esc(s) {
    return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  }

  return { render, refresh() { if (document.getElementById("ev-results")) refresh(); } };
})());
