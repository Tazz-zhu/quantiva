/* ============ 抗过拟合实验室（freqtrade rigor 移植）：滚动样本外 / 前视 / 递归 / 显著性 ============ */
App.register("rigor", (() => {
  const state = { library: [], strategy: "ma_cross", jobs: [], pollTimer: null, activeJobId: null };
  const LOSSES = [
    ["sharpe", "夏普比率"], ["sortino", "索提诺比率"], ["calmar", "卡玛比率"],
    ["profit_factor", "盈亏比"], ["multi_metric", "多指标组合"], ["max_drawdown", "最小回撤"],
    ["expectancy", "期望 R"], ["total_profit", "总收益"], ["sqn", "SQN"],
  ];

  function stat(label, id, value) {
    return '<div class="card stat-card hover"><div class="stat-label">' + label + '</div><div class="stat-value sm" id="' + id + '">' + value + '</div></div>';
  }

  function render() {
    const page = document.getElementById("page-rigor");
    page.innerHTML = `
      <div class="grid grid-4" id="rg-stats">
        ${stat("🛡 滚动样本外任务", "rg-jobs-count", "--")}
        ${stat("🎯 前视偏差检测", "rg-lookahead", "未检测")}
        ${stat("🔁 递归漂移检测", "rg-recursive", "未检测")}
        ${stat("📊 统计显著性", "rg-significance", "未检测")}
      </div>
      <div class="grid grid-layout-backtest" style="margin-top:16px">
        <div class="side-panel">
          <div class="card">
            <div class="card-title">🛡 滚动样本外（Walk-Forward）验证</div>
            <div class="hint" style="margin-bottom:8px">把数据切成多段「训练→样本外」折叠，每折只用训练段选参、紧邻样本外验证，多折一致好才算数 —— freqtrade 社区最严谨的抗过拟合流程。</div>
            <div class="field"><label>策略</label><select class="select" id="rg-strategy"></select></div>
            <div class="input-row">
              <div class="field"><label>标的</label><input class="input" id="rg-symbol" value="BTC/USDT"></div>
              <div class="field"><label>周期</label>
                <select class="select" id="rg-timeframe"><option>1m</option><option>5m</option><option>15m</option><option>1h</option><option>4h</option><option selected>1d</option></select>
              </div>
            </div>
            <div class="field"><label>优化损失函数（越小越优）</label>
              <select class="select" id="rg-loss">${LOSSES.map(([v, l]) => '<option value="' + v + '">' + l + '</option>').join("")}</select>
            </div>
            <div class="divider"></div>
            <div class="card-title" style="margin-bottom:8px">🔧 候选参数（网格搜索）</div>
            <div id="rg-ranges"></div>
            <div class="input-row-3">
              <div class="field"><label>折叠数</label><input class="input" id="rg-splits" type="number" value="4"></div>
              <div class="field"><label>训练占比%</label><input class="input" id="rg-train" type="number" step="5" value="60"></div>
              <div class="field"><label>最小交易数</label><input class="input" id="rg-min-trades" type="number" value="5"></div>
            </div>
            <div class="field"><label>训练窗口</label>
              <div class="chips" id="rg-expanding">
                <span class="chip active" data-exp="0">滚动（固定长度）</span>
                <span class="chip" data-exp="1">扩展（逐步变长）</span>
              </div>
            </div>
            <div class="input-row-2">
              <div class="field"><label>最大组合数</label><input class="input" id="rg-max" type="number" value="60"></div>
              <div class="field"><label>并行线程</label><input class="input" id="rg-workers" type="number" value="4"></div>
            </div>
            <details class="ev-advanced" style="margin-bottom:10px">
              <summary style="font-size:12px;color:var(--text-dim);cursor:pointer">⚙️ 回测 / 风控参数（高级）</summary>
              <div class="input-row-3" style="margin-top:8px">
                <div class="field"><label>初始资金</label><input class="input" id="rg-capital" type="number" value="10000"></div>
                <div class="field"><label>手续费率</label><input class="input" id="rg-fee" type="number" step="0.0001" value="0.001"></div>
                <div class="field"><label>滑点</label><input class="input" id="rg-slippage" type="number" step="0.0001" value="0.0005"></div>
              </div>
              <div class="input-row-3" style="margin-top:8px">
                <div class="field"><label>仓位比例</label><input class="input" id="rg-pos" type="number" step="0.05" value="0.5"></div>
                <div class="field"><label>杠杆</label><input class="input" id="rg-lev" type="number" step="0.5" value="1"></div>
                <div class="field"><label>ATR止损</label><input class="input" id="rg-atr" type="number" step="0.5" value="2"></div>
              </div>
            </details>
            <button class="btn btn-primary btn-block btn-run" id="rg-run">🛡 开始滚动样本外验证</button>
            <div id="rg-progress" style="display:none;margin-top:10px"></div>
          </div>

          <div class="card">
            <div class="card-title">🔬 单次回测快速体检（前视 / 递归 / 显著性）</div>
            <div class="field"><label>策略参数（JSON，可选）</label><textarea class="input" id="rg-params" rows="2" style="font-family:monospace">{&quot;fast&quot;: 20, &quot;slow&quot;: 50, &quot;direction&quot;: &quot;long_only&quot;}</textarea></div>
            <div class="input-row-3">
              <div class="field"><label>数据源</label>
                <select class="select" id="rg-source"><option value="db">本地数据库</option><option value="exchange">交易所实时</option></select>
              </div>
              <div class="field"><label>回看天数</label><input class="input" id="rg-days" type="number" value="300"></div>
              <div class="field"></div>
            </div>
            <div class="btn-row" style="display:flex;gap:6px;margin-top:8px">
              <button class="btn btn-sm btn-block" id="rg-lookahead">👁 前视检测</button>
              <button class="btn btn-sm btn-block" id="rg-recursive">🔁 递归检测</button>
              <button class="btn btn-sm btn-block" id="rg-sig">📊 显著性检验</button>
            </div>
            <div id="rg-quick-result" style="margin-top:10px"></div>
          </div>
        </div>
        <div>
          <div class="card">
            <div class="card-title">🏆 验证任务与结果 <button class="btn btn-sm" id="rg-refresh">⟳ 刷新</button></div>
            <div class="chips" id="rg-job-list" style="margin-bottom:10px"></div>
            <div id="rg-job-detail"></div>
          </div>
        </div>
      </div>
    `;
    document.getElementById("rg-run").addEventListener("click", runWalkforward);
    document.getElementById("rg-refresh").addEventListener("click", refresh);
    document.getElementById("rg-lookahead").addEventListener("click", () => quickCheck("lookahead"));
    document.getElementById("rg-recursive").addEventListener("click", () => quickCheck("recursive"));
    document.getElementById("rg-sig").addEventListener("click", () => quickCheck("significance"));
    document.getElementById("rg-expanding").querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
      document.getElementById("rg-expanding").querySelectorAll(".chip").forEach((x) => x.classList.remove("active"));
      c.classList.add("active");
    }));
    loadLibrary();
    refresh();
  }

  function refresh() {
    loadJobs();
  }

  function setStat(id, v) {
    const el = document.getElementById(id);
    if (el) el.textContent = v;
  }

  async function loadLibrary() {
    try {
      const { library } = await API.get("/api/strategies/library");
      state.library = library.filter((s) => s.name !== "custom");
      const sel = document.getElementById("rg-strategy");
      sel.innerHTML = state.library.map((s) => '<option value="' + s.name + '">' + s.icon + " " + s.school + " · " + s.master.split("·")[0].trim() + '</option>').join("");
      sel.addEventListener("change", () => { state.strategy = sel.value; renderRanges(); });
      renderRanges();
    } catch (e) { /* 忽略 */ }
  }

  function renderRanges() {
    const meta = state.library.find((s) => s.name === state.strategy);
    const box = document.getElementById("rg-ranges");
    if (!meta || !box) return;
    const numParams = meta.params.filter((p) => p.type === "number");
    if (!numParams.length) { box.innerHTML = '<div class="hint">该策略无可搜索的数值参数。</div>'; return; }
    box.innerHTML = numParams.map((p) =>
      '<div style="margin-bottom:8px"><label>' + p.label + '（候选值，逗号分隔）</label>'
      + '<input class="input rg-range" data-param="' + p.k + '" placeholder="如 10,20,30">'
    ).join("");
    numParams.forEach((p) => {
      const el = box.querySelector('[data-param="' + p.k + '"]');
      if (el) el.value = String(p.def);
    });
  }

  function buildDataCfg() {
    return {
      source: document.getElementById("rg-source") ? document.getElementById("rg-source").value : "db",
      symbol: document.getElementById("rg-symbol").value.trim(),
      timeframe: document.getElementById("rg-timeframe").value,
      days: parseInt(document.getElementById("rg-days") ? document.getElementById("rg-days").value : "300") || 300,
    };
  }

  function buildRiskCfg() {
    return {
      max_position_pct: parseFloat(document.getElementById("rg-pos").value) || 0.5,
      leverage: parseFloat(document.getElementById("rg-lev").value) || 1,
      atr_stop_mult: parseFloat(document.getElementById("rg-atr").value) || 2,
      trade_direction: "long_only",
    };
  }

  async function runWalkforward() {
    const ranges = {};
    document.querySelectorAll(".rg-range").forEach((el) => {
      const vals = el.value.split(",").map((s) => parseFloat(s.trim())).filter((v) => !Number.isNaN(v));
      if (vals.length) ranges[el.dataset.param] = vals;
    });
    const meta = state.library.find((s) => s.name === state.strategy);
    if (meta) {
      const directionParam = meta.params.find((p) => p.type === "select");
      if (directionParam) ranges[directionParam.k] = [directionParam.def || "long_only"];
    }
    if (!Object.keys(ranges).length) { App.toast("请至少填写一个候选参数范围", "error"); return; }
    const payload = {
      strategy: state.strategy,
      param_ranges: ranges,
      data: buildDataCfg(),
      risk: buildRiskCfg(),
      backtest: {
        initial_capital: parseFloat(document.getElementById("rg-capital").value) || 10000,
        fee_rate: parseFloat(document.getElementById("rg-fee").value) || 0.001,
        slippage: parseFloat(document.getElementById("rg-slippage").value) || 0.0005,
      },
      loss: document.getElementById("rg-loss").value,
      n_splits: parseInt(document.getElementById("rg-splits").value) || 4,
      train_ratio: (parseInt(document.getElementById("rg-train").value) || 60) / 100,
      expanding: document.querySelector("#rg-expanding .chip.active").dataset.exp === "1",
      min_trades: parseInt(document.getElementById("rg-min-trades").value) || 0,
      max_combos: parseInt(document.getElementById("rg-max").value) || 60,
      workers: parseInt(document.getElementById("rg-workers").value) || 4,
    };
    try {
      const { id } = await API.post("/api/rigor/walkforward", payload);
      App.toast("滚动样本外验证已启动 (" + id + ")", "info");
      state.activeJobId = id;
      refresh();
    } catch (e) {
      App.toast("启动失败: " + e.message, "error");
    }
  }

  async function quickCheck(kind) {
    let params = {};
    try { params = JSON.parse(document.getElementById("rg-params").value || "{}"); } catch (e) { App.toast("策略参数 JSON 格式错误", "error"); return; }
    const payload = { strategy: state.strategy, params, data: buildDataCfg() };
    if (kind === "recursive") payload.warmup = 200;
    if (kind === "significance") { payload.risk = buildRiskCfg(); payload.backtest = { initial_capital: 10000, fee_rate: 0.001, slippage: 0.0005 }; payload.n_trials = 24; payload.n_boot = 500; payload.n_perm = 500; }
    const box = document.getElementById("rg-quick-result");
    box.innerHTML = '<div class="hint">正在运行 ' + { lookahead: "前视检测", recursive: "递归检测", significance: "显著性检验" }[kind] + ' …</div>';
    try {
      const res = await API.post("/api/rigor/" + kind, payload);
      renderQuick(kind, res);
      setStat(kind === "lookahead" ? "rg-lookahead" : kind === "recursive" ? "rg-recursive" : "rg-significance", res.verdict && res.verdict.summary ? (res.verdict.passed ? "✅ 通过" : "⚠️ 未通过") : (res.has_bias ? "❌ 有前视" : res.has_drift ? "⚠️ 有漂移" : "✅ 正常"));
    } catch (e) {
      box.innerHTML = '<div class="alert error">检测失败：' + e.message + '</div>';
    }
  }

  function renderQuick(kind, res) {
    const box = document.getElementById("rg-quick-result");
    if (kind === "lookahead") {
      box.innerHTML = '<div class="alert ' + (res.has_bias ? "error" : "success") + '">' + res.verdict + '<div class="hint" style="margin-top:4px">抽样 ' + res.total_checks + ' 个时点，偏差 ' + res.biased_checks + ' 个（' + FMT.pct(res.bias_rate, 1) + '）</div></div>';
    } else if (kind === "recursive") {
      box.innerHTML = '<div class="alert ' + (res.has_drift ? "error" : "success") + '">' + res.verdict + '<div class="hint" style="margin-top:4px">预热 ' + res.warmup + ' 根，抽样 ' + res.total_checks + ' 个时点，漂移 ' + res.drifted_checks + ' 个（' + FMT.pct(res.drift_rate, 1) + '）</div></div>';
    } else {
      const m = res.metrics || {};
      const dsr = res.deflated_sharpe || {};
      const boot = res.bootstrap || {};
      const perm = res.permutation || {};
      box.innerHTML = '<div class="alert ' + (res.verdict.passed ? "success" : "error") + '">' + res.verdict.summary + '</div>'
        + '<div class="grid grid-2" style="margin-top:8px;gap:8px">'
        + miniMetric("总收益", FMT.pct(m.total_return)) + miniMetric("夏普", FMT.num(m.sharpe))
        + miniMetric("最大回撤", FMT.pct(m.max_drawdown)) + miniMetric("交易数", FMT.num(m.num_trades, 0))
        + miniMetric("缩水夏普(24次试验)", FMT.num(dsr.deflated_sharpe)) + miniMetric("bootstrap p", FMT.num(boot.p_value, 4))
        + miniMetric("置换检验 p", FMT.num(perm.p_value, 4)) + miniMetric("胜率", FMT.pct(m.win_rate))
        + '</div>';
    }
  }

  function miniMetric(label, value) {
    return '<div class="card" style="padding:8px 10px"><div class="stat-label">' + label + '</div><div class="stat-value xs">' + value + '</div></div>';
  }

  async function loadJobs() {
    try {
      const { jobs } = await API.get("/api/rigor/jobs");
      state.jobs = jobs;
      const running = jobs.filter((j) => j.status === "running").length;
      setStat("rg-jobs-count", running > 0 ? running + " 个运行中" : "无运行中");
      const list = document.getElementById("rg-job-list");
      if (!list) return;
      list.innerHTML = jobs.length ? jobs.map((j) =>
        '<span class="chip' + (j.id === state.activeJobId ? " active" : "") + '" data-job="' + j.id + '" title="' + (j.error || "") + '">'
        + (j.kind === "walkforward" ? "🛡 滚动样本外" : j.kind === "freqai_backtest" ? "🤖 FreqAI回测" : j.kind === "freqai_train" ? "🎓 FreqAI训练" : j.kind)
        + " · " + (j.status === "running" ? "⏳" : j.status === "done" ? "✅" : "❌") + " · " + FMT.time(j.finished_at || j.created_at)
        + '</span>'
      ).join("") : '<div class="hint">暂无验证任务</div>';
      list.querySelectorAll("[data-job]").forEach((c) => c.addEventListener("click", () => {
        state.activeJobId = c.dataset.job;
        list.querySelectorAll(".chip").forEach((x) => x.classList.remove("active"));
        c.classList.add("active");
        loadJobDetail(c.dataset.job);
      }));
      if (running && state.activeJobId) setTimeout(() => { if (document.getElementById("page-rigor").classList.contains("active")) loadJobDetail(state.activeJobId); }, 2500);
      if (state.activeJobId) loadJobDetail(state.activeJobId);
      else if (jobs.length) { state.activeJobId = jobs[0].id; loadJobDetail(jobs[0].id); }
    } catch (e) { /* 忽略 */ }
  }

  async function loadJobDetail(jobId) {
    try {
      const job = await API.get("/api/rigor/result/" + jobId);
      const box = document.getElementById("rg-job-detail");
      if (!box) return;
      if (job.status === "running") {
        box.innerHTML = '<div class="alert info">⏳ 任务运行中… 请稍候，页面每 4 秒自动刷新。</div>';
        return;
      }
      if (job.status === "error") {
        box.innerHTML = '<div class="alert error">任务失败：' + job.error + '</div>';
        return;
      }
      if (job.kind === "walkforward") renderWalkforward(box, job.result);
      else if (job.kind === "freqai_backtest") renderFreqaiBacktest(box, job.result);
      else if (job.kind === "freqai_train") renderFreqaiTrain(box, job.result);
      else box.innerHTML = '<pre class="pre">' + JSON.stringify(job.result, null, 2) + '</pre>';
    } catch (e) { /* 忽略 */ }
  }

  function renderWalkforward(box, r) {
    const v = r.verdict || {};
    const oos = r.oos_metrics_combined || {};
    const sig = r.significance || {};
    const stab = r.stability || {};
    box.innerHTML = `
      <div class="alert ${v.passed ? "success" : "error"}">${v.summary || ""}</div>
      <div class="grid grid-2" style="margin-top:10px;gap:8px">
        ${miniMetric("样本外总收益", FMT.pct(oos.total_return))}
        ${miniMetric("样本外夏普", FMT.num(oos.sharpe))}
        ${miniMetric("样本外回撤", FMT.pct(oos.max_drawdown))}
        ${miniMetric("样本外交易数", FMT.num(oos.num_trades, 0))}
        ${miniMetric("bootstrap p 值", FMT.num(sig.p_value, 4))}
        ${miniMetric("参数一致性", FMT.pct(stab.param_consistency, 1))}
      </div>
      <div class="hint" style="margin-top:8px">${stab.verdict || ""}</div>
      <div class="table-wrap" style="max-height:300px;margin-top:10px">
        <table class="table"><thead><tr><th>折叠</th><th>训练段</th><th>样本外段</th><th>最优参数</th><th>样本外收益</th><th>样本外夏普</th><th>交易数</th></tr></thead>
        <tbody>${(r.folds || []).map((f, i) => {
          const om = f.oos_metrics || {};
          return '<tr><td>' + (i + 1) + '</td><td>' + FMT.time(f.train[0]) + " → " + FMT.time(f.train[1]) + '</td>'
            + '<td>' + FMT.time(f.test[0]) + " → " + FMT.time(f.test[1]) + '</td>'
            + '<td>' + JSON.stringify(f.best_params) + '</td>'
            + '<td class="' + FMT.cls(om.total_return) + '">' + FMT.pct(om.total_return) + '</td>'
            + '<td class="' + FMT.cls(om.sharpe) + '">' + FMT.num(om.sharpe) + '</td>'
            + '<td>' + FMT.num(om.num_trades, 0) + '</td></tr>';
        }).join("") || '<tr><td colspan="7">无折叠结果</td></tr>'}</tbody></table>
      </div>
    `;
  }

  function renderFreqaiBacktest(box, r) {
    const m = r.metrics || {};
    box.innerHTML = `
      <div class="grid grid-2" style="gap:8px">
        ${miniMetric("预测覆盖率", FMT.pct(r.prediction_coverage, 1))}
        ${miniMetric("预测-实际相关", FMT.num(r.correlation))}
        ${miniMetric("总收益", FMT.pct(m.total_return))}
        ${miniMetric("夏普", FMT.num(m.sharpe))}
        ${miniMetric("最大回撤", FMT.pct(m.max_drawdown))}
        ${miniMetric("交易数", FMT.num(m.num_trades, 0))}
      </div>
      <div class="hint" style="margin-top:8px">模型 ${r.model}（${r.kind}），预测周期 ${r.horizon} 根 K 线；相关为样本外预测与真实前瞻收益的 Pearson 相关。</div>
      <div class="hint" style="margin-top:4px">相关 &gt; 0 说明模型有一定预测力；&lt; 0 说明当前特征对后市无信息（可尝试换模型/特征）。</div>
    `;
  }

  function renderFreqaiTrain(box, r) {
    const imp = (r.importance_top || {});
    box.innerHTML = `
      <div class="alert success">模型训练完成：${r.name}（${r.model} · ${r.kind} · 预测周期 ${r.horizon}）</div>
      <div class="grid grid-2" style="margin-top:8px;gap:8px">
        ${miniMetric("训练样本", FMT.num(r.train_rows, 0))}
        ${miniMetric("训练 R²/准确率", FMT.num(r.train_score, 4))}
      </div>
      <div class="card-title" style="margin-top:10px">🔍 特征重要性 Top</div>
      <div class="table-wrap"><table class="table"><thead><tr><th>特征</th><th>重要性</th></tr></thead>
      <tbody>${Object.entries(imp).map(([k, v]) => '<tr><td>' + k + '</td><td class="num">' + FMT.num(v, 4) + '</td></tr>').join("") || '<tr><td colspan="2">无</td></tr>'}</tbody></table></div>
    `;
  }

  return { render, refresh };
})());
