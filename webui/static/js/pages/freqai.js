/* ============ FreqAI 机器学习实验室（freqtrade FreqAI 移植） ============ */
App.register("freqai", (() => {
  const state = { models: [], jobs: [], activeJobId: null };
  const MODELS = [["random_forest", "随机森林"], ["extra_trees", "极端随机树"], ["gradient_boosting", "梯度提升树"], ["ridge", "岭回归（回归）"], ["logistic", "逻辑回归（分类）"], ["lightgbm", "LightGBM（若已装）"], ["xgboost", "XGBoost（若已装）"]];

  function stat(label, id, value) {
    return '<div class="card stat-card hover"><div class="stat-label">' + label + '</div><div class="stat-value sm" id="' + id + '">' + value + '</div></div>';
  }

  function render() {
    const page = document.getElementById("page-freqai");
    page.innerHTML = `
      <div class="grid grid-4" id="fq-stats">
        ${stat("🤖 已训练模型", "fq-model-count", "--")}
        ${stat("🎯 最新推理", "fq-latest", "--")}
        ${stat("🧩 特征组", "fq-features", "5 组 / 20+ 特征")}
        ${stat("🛡 防泄漏", "fq-leak", "purge+embargo")}
      </div>
      <div class="grid grid-layout-backtest" style="margin-top:16px">
        <div class="side-panel">
          <div class="card">
            <div class="card-title">🤖 FreqAI 滚动样本外回测</div>
            <div class="hint" style="margin-bottom:8px">时序机器学习：每折只用历史数据训练模型，预测未来样本外窗口，全程无泄漏（purge 剔除标签窗口 + embargo 缓冲）。预测列接入 FreqAIStrategy 生成信号并回测。</div>
            <div class="input-row">
              <div class="field"><label>模型</label>
                <select class="select" id="fq-model">${MODELS.map(([v, l]) => '<option value="' + v + '">' + l + '</option>').join("")}</select>
              </div>
              <div class="field"><label>任务类型</label>
                <select class="select" id="fq-kind"><option value="regression">回归（ATR缩放收益）</option><option value="classification">分类（涨/跌）</option></select>
              </div>
            </div>
            <div class="input-row">
              <div class="field"><label>标的</label><input class="input" id="fq-symbol" value="BTC/USDT"></div>
              <div class="field"><label>周期</label>
                <select class="select" id="fq-timeframe"><option>1m</option><option>5m</option><option>15m</option><option>1h</option><option>4h</option><option selected>1d</option></select>
              </div>
            </div>
            <div class="input-row-3">
              <div class="field"><label>预测周期</label><input class="input" id="fq-horizon" type="number" value="5"></div>
              <div class="field"><label>窗口数</label><input class="input" id="fq-windows" type="number" value="5"></div>
              <div class="field"><label>最小训练</label><input class="input" id="fq-min-train" type="number" value="100"></div>
            </div>
            <div class="divider"></div>
            <div class="card-title" style="margin-bottom:8px">📈 信号生成（FreqAIStrategy）</div>
            <div class="input-row-2">
              <div class="field"><label>方向</label>
                <select class="select" id="fq-direction"><option value="long_only">只做多</option><option value="long_short">多空都做</option></select>
              </div>
              <div class="field"><label>阈值（回归:预测值 / 分类:概率）</label><input class="input" id="fq-threshold" type="number" step="0.05" value="0"></div>
            </div>
            <div class="input-row-2">
              <div class="field"><label>仓位比例</label><input class="input" id="fq-pos" type="number" step="0.05" value="0.5"></div>
              <div class="field"><label>杠杆</label><input class="input" id="fq-lev" type="number" step="0.5" value="1"></div>
            </div>
            <button class="btn btn-primary btn-block btn-run" id="fq-run">🤖 运行 FreqAI 回测</button>
            <div id="fq-progress" style="display:none;margin-top:10px"></div>
          </div>

          <div class="card">
            <div class="card-title">🎓 训练最终模型（持久化）</div>
            <div class="input-row-2">
              <div class="field"><label>训练占比</label><input class="input" id="fq-train-ratio" type="number" step="0.05" value="0.8"></div>
              <div class="field"><label>模型名</label><input class="input" id="fq-name" placeholder="留空自动命名"></div>
            </div>
            <button class="btn btn-block" id="fq-train" style="margin-top:8px">🎓 开始训练</button>
            <div id="fq-train-result" style="margin-top:10px"></div>
          </div>

          <div class="card">
            <div class="card-title">🔁 定时重训（实盘模型漂移防护）</div>
            <div class="hint" style="margin-bottom:8px">按固定间隔用最新行情重训模型并保存为 <b>live</b>，让模型跟随市场漂移（freqtrade FreqAI 重训机制）。</div>
            <div class="input-row">
              <div class="field"><label>间隔（小时）</label><input class="input" id="fq-interval" type="number" step="1" value="6"></div>
              <div class="field"><label>状态</label><div class="hint" id="fq-retrain-status">未启动</div></div>
            </div>
            <div style="display:flex;gap:6px;margin-top:8px">
              <button class="btn btn-sm btn-block" id="fq-retrain-start">▶ 启动</button>
              <button class="btn btn-sm btn-block" id="fq-retrain-stop">⏹ 停止</button>
              <button class="btn btn-sm btn-block" id="fq-retrain-now">⚡ 立即重训</button>
            </div>
          </div>

          <div class="card">
            <div class="card-title">📦 已训练模型 <button class="btn btn-sm" id="fq-refresh-models">⟳</button></div>
            <div id="fq-model-list" style="display:flex;flex-direction:column;gap:6px"></div>
            <div class="field" style="margin-top:8px"><label>对最新 K 线推理</label>
              <div style="display:flex;gap:6px"><input class="input" id="fq-predict-name" placeholder="模型名（留空用最新）" style="flex:1"><button class="btn btn-sm" id="fq-predict">🔮 推理</button></div>
            </div>
            <div id="fq-predict-result" style="margin-top:8px"></div>
          </div>
        </div>
        <div>
          <div class="card">
            <div class="card-title">🏆 FreqAI 任务与结果 <button class="btn btn-sm" id="fq-refresh">⟳ 刷新</button></div>
            <div class="chips" id="fq-job-list" style="margin-bottom:10px"></div>
            <div id="fq-job-detail"></div>
          </div>
        </div>
      </div>
    `;
    document.getElementById("fq-run").addEventListener("click", runBacktest);
    document.getElementById("fq-train").addEventListener("click", runTrain);
    document.getElementById("fq-refresh").addEventListener("click", refresh);
    document.getElementById("fq-refresh-models").addEventListener("click", loadModels);
    document.getElementById("fq-predict").addEventListener("click", runPredict);
    document.getElementById("fq-retrain-start").addEventListener("click", () => retrainAction("start"));
    document.getElementById("fq-retrain-stop").addEventListener("click", () => retrainAction("stop"));
    document.getElementById("fq-retrain-now").addEventListener("click", () => retrainAction("train_now"));
    loadModels();
    refresh();
  }

  function refresh() {
    loadJobs();
    loadModels();
    loadRetrainStatus();
  }

  async function retrainAction(action) {
    try {
      const payload = { action };
      if (action === "start") payload.interval_hours = parseFloat(document.getElementById("fq-interval").value) || 6;
      const res = await API.post("/api/freqai/schedule", payload);
      if (action === "train_now") App.toast("重训完成：" + ((res.trained && res.trained.name) || ""), "success");
      else App.toast(action === "start" ? "定时重训已启动" : "定时重训已停止", "success");
      loadRetrainStatus();
    } catch (e) {
      App.toast("操作失败: " + e.message, "error");
    }
  }

  async function loadRetrainStatus() {
    try {
      const st = await API.get("/api/freqai/retrainer");
      const el = document.getElementById("fq-retrain-status");
      if (!el) return;
      el.textContent = (st.running ? "⏳ 运行中（每 " + (st.interval_hours || "-") + " 小时）" : "已停止")
        + (st.last_train_at ? " · 上次 " + FMT.time(st.last_train_at) : "");
    } catch (e) { /* 忽略 */ }
  }

  function setStat(id, v) {
    const el = document.getElementById(id);
    if (el) el.textContent = v;
  }

  function dataCfg() {
    return {
      source: "db",
      symbol: document.getElementById("fq-symbol").value.trim(),
      timeframe: document.getElementById("fq-timeframe").value,
      days: 730,
    };
  }

  async function runBacktest() {
    const payload = {
      model: document.getElementById("fq-model").value,
      kind: document.getElementById("fq-kind").value,
      horizon: parseInt(document.getElementById("fq-horizon").value) || 5,
      data: dataCfg(),
      n_windows: parseInt(document.getElementById("fq-windows").value) || 5,
      min_train: parseInt(document.getElementById("fq-min-train").value) || 100,
      strategy_params: {
        kind: document.getElementById("fq-kind").value,
        direction: document.getElementById("fq-direction").value,
        long_threshold: parseFloat(document.getElementById("fq-threshold").value) || 0,
        short_threshold: parseFloat(document.getElementById("fq-threshold").value) || 0,
      },
      risk: {
        max_position_pct: parseFloat(document.getElementById("fq-pos").value) || 0.5,
        leverage: parseFloat(document.getElementById("fq-lev").value) || 1,
        trade_direction: document.getElementById("fq-direction").value === "long_short" ? "long_short" : "long_only",
      },
      backtest: { initial_capital: 10000, fee_rate: 0.001, slippage: 0.0005 },
    };
    try {
      const { id } = await API.post("/api/freqai/backtest", payload);
      App.toast("FreqAI 回测已启动 (" + id + ")", "info");
      state.activeJobId = id;
      refresh();
    } catch (e) {
      App.toast("启动失败: " + e.message, "error");
    }
  }

  async function runTrain() {
    const payload = {
      model: document.getElementById("fq-model").value,
      kind: document.getElementById("fq-kind").value,
      horizon: parseInt(document.getElementById("fq-horizon").value) || 5,
      data: dataCfg(),
      train_ratio: parseFloat(document.getElementById("fq-train-ratio").value) || 0.8,
      name: document.getElementById("fq-name").value.trim() || undefined,
    };
    try {
      const { id } = await API.post("/api/freqai/train", payload);
      App.toast("FreqAI 训练已启动 (" + id + ")", "info");
      state.activeJobId = id;
      refresh();
    } catch (e) {
      App.toast("启动失败: " + e.message, "error");
    }
  }

  async function runPredict() {
    const name = document.getElementById("fq-predict-name").value.trim();
    try {
      const res = await API.post("/api/freqai/predict", { data: dataCfg(), name: name || undefined });
      const box = document.getElementById("fq-predict-result");
      const isClf = res.probability_up !== null && res.probability_up !== undefined;
      box.innerHTML = '<div class="alert success">🔮 ' + FMT.time(res.timestamp) + ' 最新推理：'
        + (isClf ? "上涨概率 <b>" + FMT.pct(res.probability_up, 1) + "</b>" : "预测收益 <b>" + FMT.num(res.prediction, 6) + "</b>")
        + '（模型 ' + res.model + '）</div>';
      setStat("fq-latest", isClf ? FMT.pct(res.probability_up, 1) + " 上涨" : FMT.num(res.prediction, 6));
    } catch (e) {
      App.toast("推理失败: " + e.message, "error");
    }
  }

  async function loadModels() {
    try {
      const st = await API.get("/api/freqai/status");
      state.models = st.models || [];
      setStat("fq-model-count", state.models.length + " 个");
      const box = document.getElementById("fq-model-list");
      if (!box) return;
      box.innerHTML = state.models.length ? state.models.map((m) =>
        '<div class="card" style="padding:8px 10px;display:flex;justify-content:space-between;align-items:center">'
        + '<div><b>' + m.name + '</b><div class="hint">' + m.model + " · " + (m.kind === "classification" ? "分类" : "回归") + " · 周期 " + m.horizon + " · " + m.created + '</div></div>'
        + '<span class="badge">' + (m.train_score !== null && m.train_score !== undefined ? FMT.num(m.train_score, 3) : "--") + '</span></div>'
      ).join("") : '<div class="hint">暂无已训练模型，点击「🎓 开始训练」。</div>';
    } catch (e) { /* 忽略 */ }
  }

  async function loadJobs() {
    try {
      const { jobs } = await API.get("/api/rigor/jobs");
      const mine = jobs.filter((j) => j.kind === "freqai_backtest" || j.kind === "freqai_train");
      const running = mine.filter((j) => j.status === "running").length;
      const list = document.getElementById("fq-job-list");
      if (!list) return;
      list.innerHTML = mine.length ? mine.map((j) =>
        '<span class="chip' + (j.id === state.activeJobId ? " active" : "") + '" data-job="' + j.id + '">'
        + (j.kind === "freqai_backtest" ? "🤖 回测" : "🎓 训练")
        + " · " + (j.status === "running" ? "⏳" : j.status === "done" ? "✅" : "❌") + " · " + FMT.time(j.finished_at || j.created_at)
        + '</span>'
      ).join("") : '<div class="hint">暂无 FreqAI 任务</div>';
      list.querySelectorAll("[data-job]").forEach((c) => c.addEventListener("click", () => {
        state.activeJobId = c.dataset.job;
        list.querySelectorAll(".chip").forEach((x) => x.classList.remove("active"));
        c.classList.add("active");
        loadJobDetail(c.dataset.job);
      }));
      if (running && state.activeJobId) setTimeout(() => { if (document.getElementById("page-freqai").classList.contains("active")) loadJobDetail(state.activeJobId); }, 2500);
      if (state.activeJobId) loadJobDetail(state.activeJobId);
      else if (mine.length) { state.activeJobId = mine[0].id; loadJobDetail(mine[0].id); }
    } catch (e) { /* 忽略 */ }
  }

  async function loadJobDetail(jobId) {
    try {
      const job = await API.get("/api/rigor/result/" + jobId);
      const box = document.getElementById("fq-job-detail");
      if (!box) return;
      if (job.status === "running") {
        box.innerHTML = '<div class="alert info">⏳ 任务运行中…（机器学习训练可能需要数十秒）</div>';
        return;
      }
      if (job.status === "error") {
        box.innerHTML = '<div class="alert error">任务失败：' + job.error + '</div>';
        return;
      }
      if (job.kind === "freqai_backtest") renderBacktest(box, job.result);
      else if (job.kind === "freqai_train") renderTrain(box, job.result);
    } catch (e) { /* 忽略 */ }
  }

  function miniMetric(label, value) {
    return '<div class="card" style="padding:8px 10px"><div class="stat-label">' + label + '</div><div class="stat-value xs">' + value + '</div></div>';
  }

  function renderBacktest(box, r) {
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
      ${predSparkline(r.predictions || [], r.id)}
      <div class="hint" style="margin-top:8px">模型 ${r.model}（${r.kind}）· 预测周期 ${r.horizon} 根；相关为样本外预测与真实前瞻收益的 Pearson 相关。</div>
      ${(r.windows || []).length ? '<div class="card-title" style="margin-top:10px">📊 各窗口训练质量</div><div class="table-wrap" style="max-height:200px"><table class="table"><thead><tr><th>窗口</th><th class="num">训练样本</th><th class="num">测试样本</th><th class="num">训练得分</th></tr></thead><tbody>' + r.windows.map((w, i) => '<tr><td>' + (i + 1) + '</td><td class="num">' + (w.train_rows || 0) + '</td><td class="num">' + (w.test_rows || 0) + '</td><td class="num">' + (w.train_score !== undefined && w.train_score !== null ? FMT.num(w.train_score, 4) : w.error || "--") + '</td></tr>').join("") + '</tbody></table></div>' : ""}
      <div class="hint" style="margin-top:8px">平仓原因分布：${(r.breakdown.by_exit_reason || []).map((b) => b.key + " ×" + b.trades).join("，") || "--"}</div>
    `;
  }

  function predSparkline(points, seed) {
    const pts = (points || []).filter((p) => p[1] !== null && p[1] !== undefined);
    if (pts.length < 2) return "";
    const w = 700, h = 100, pad = 4;
    const xs = pts.map((p) => p[0]);
    const ys = pts.map((p) => p[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const spanX = (maxX - minX) || 1, spanY = (maxY - minY) || 1;
    const coords = pts.map((p) => {
      const x = pad + (p[0] - minX) / spanX * (w - 2 * pad);
      const y = h - pad - (p[1] - minY) / spanY * (h - 2 * pad);
      return x.toFixed(1) + "," + y.toFixed(1);
    });
    const zero = h - pad - (0 - minY) / spanY * (h - 2 * pad);
    return '<div class="card" style="margin-top:10px"><div class="card-title">📉 样本外预测值（freqai_pred）</div>'
      + '<svg viewBox="0 0 ' + w + " " + h + '" style="width:100%;height:100px">'
      + '<line x1="' + pad + '" y1="' + zero.toFixed(1) + '" x2="' + (w - pad) + '" y2="' + zero.toFixed(1) + '" stroke="var(--border)" stroke-width="1" stroke-dasharray="4 4"/>'
      + '<polyline points="' + coords.join(" ") + '" fill="none" stroke="#7c5cff" stroke-width="1.5"/></svg></div>';
  }

  function renderTrain(box, r) {
    const imp = r.importance_top || {};
    box.innerHTML = `
      <div class="alert success">模型训练完成：<b>${r.name}</b>（${r.model} · ${r.kind === "classification" ? "分类" : "回归"} · 预测周期 ${r.horizon}）</div>
      <div class="grid grid-2" style="margin-top:8px;gap:8px">
        ${miniMetric("训练样本", FMT.num(r.train_rows, 0))}
        ${miniMetric("训练得分", FMT.num(r.train_score, 4))}
      </div>
      <div class="card-title" style="margin-top:10px">🔍 特征重要性 Top</div>
      <div class="table-wrap"><table class="table"><thead><tr><th>特征</th><th class="num">重要性</th></tr></thead>
      <tbody>${Object.entries(imp).map(([k, v]) => '<tr><td>' + k + '</td><td class="num">' + FMT.num(v, 4) + '</td></tr>').join("") || '<tr><td colspan="2">无</td></tr>'}</tbody></table></div>
    `;
  }

  return { render, refresh };
})());



