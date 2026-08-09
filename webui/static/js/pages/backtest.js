/* ============ 策略回测（经典库 / 可视化规则 / 代码策略） ============ */
App.register("backtest", (() => {
  const state = { strategy: "ma_cross", jobId: null, polling: null, result: null, analysisShown: false, library: [], cm: null, templateCode: "", lastCode: "", optJobId: null, optPolling: null, compareJobId: null, comparePolling: null };
  const CUSTOM_DEF = { name: "🎛️ 自定义规则策略", params: [] };
  const PRESETS = {
    standard: { label: "标准", pos: 0.5, lev: 2, atr: 2, stop: "", tp: "" },
    conservative: { label: "保守", pos: 0.2, lev: 1, atr: 3, stop: "", tp: "" },
    aggressive: { label: "激进", pos: 0.8, lev: 5, atr: 1.5, stop: "", tp: 0.06 },
  };
  const DEFAULT_RULES = {
    entry: { logic: "all", conditions: [
      { indicator: "sma", params: { period: 20 }, op: ">", compare: "indicator", compare_indicator: "sma", compare_params: { period: 50 } },
      { indicator: "rsi", params: { period: 14 }, op: "<", compare: "number", value: 70 },
    ]},
    direction: "long_only",
  };
  const DEFAULT_CODE_PARAMS = { fast: 20, slow: 50 };

  function render() {
    if (state.cm) { state.lastCode = state.cm.getValue(); state.cm = null; }
    const page = document.getElementById("page-backtest");
    page.innerHTML = `
      <div class="grid grid-layout-backtest">
        <div class="side-panel">
          <div class="card">
            <div class="card-title">🧠 策略配置</div>
            <div id="bt-sync-badge" style="display:none;margin-bottom:10px"></div>
            <div class="field"><label>策略类型</label><select class="select" id="bt-strategy"></select></div>
            <div id="bt-params"></div>
          </div>
          <div class="card">
            <div class="card-title">📡 数据</div>
            <div class="field"><label>数据源</label>
              <select class="select" id="bt-source">
                <option value="synthetic">合成数据（离线可用）</option>
                <option value="auto">自动（交易所优先）</option>
                <option value="db">本地数据库</option>
              </select>
            </div>
            <div class="input-row">
              <div class="field"><label>标的</label><input class="input" id="bt-symbol" value="BTC/USDT"></div>
              <div class="field"><label>周期</label>
                <select class="select" id="bt-timeframe"><option>1m</option><option>5m</option><option>15m</option><option>1h</option><option>4h</option><option>1d</option></select>
              </div>
            </div>
            <div class="input-row">
              <div class="field"><label>回看天数</label><input class="input" id="bt-days" type="number" value="365"></div>
              <div class="field"><label>随机种子</label><input class="input" id="bt-seed" type="number" value="42"></div>
            </div>
          </div>
          <div class="card">
            <div class="card-title">🛡️ 风控</div>
            <div class="field"><label>回测预设</label>
              <div class="chips" id="bt-preset">
                <span class="chip active" data-preset="standard">标准</span>
                <span class="chip" data-preset="conservative">保守</span>
                <span class="chip" data-preset="aggressive">激进</span>
              </div>
              <div class="hint">一键应用仓位 / 杠杆 / 止损止盈组合，也可手动微调。</div>
            </div>
            <div class="input-row-3">
              <div class="field"><label>仓位比例</label><input class="input" id="bt-pos-pct" type="number" step="0.05" value="0.5"></div>
              <div class="field"><label>杠杆</label><input class="input" id="bt-leverage" type="number" step="0.5" value="2"></div>
              <div class="field"><label>ATR止损</label><input class="input" id="bt-atr" type="number" step="0.5" value="2"></div>
            </div>
            <div class="input-row-3">
              <div class="field"><label>止损% (空=ATR)</label><input class="input" id="bt-stop" type="number" step="0.01" placeholder="如 0.03"></div>
              <div class="field"><label>止盈%</label><input class="input" id="bt-tp" type="number" step="0.01" placeholder="如 0.06"></div>
              <div class="field"><label>回撤熔断%</label><input class="input" id="bt-dd-pct" type="number" step="0.01" placeholder="如 0.05"></div>
            </div>
            <div class="input-row-3">
              <div class="field"><label>单笔风险% (空=固定仓位)</label><input class="input" id="bt-risk-pct" type="number" step="0.005" placeholder="如 0.01"></div>
              <div class="field"><label>移动止损(ATR)</label><input class="input" id="bt-trail-atr" type="number" step="0.5" placeholder="如 3"></div>
              <div class="field"><label>保本触发(ATR)</label><input class="input" id="bt-be-atr" type="number" step="0.5" placeholder="如 2"></div>
            </div>
            <div class="hint">单笔风险% = 每笔最多亏损权益的百分比（配合止损距离自动计算仓位）；移动止损/保本 0=关闭。</div>
          </div>
          <div class="card">
            <div class="card-title">💵 回测参数</div>
            <div class="input-row-3">
              <div class="field"><label>初始资金</label><input class="input" id="bt-capital" type="number" value="10000"></div>
              <div class="field"><label>手续费率</label><input class="input" id="bt-fee" type="number" step="0.0001" value="0.001"></div>
              <div class="field"><label>滑点</label><input class="input" id="bt-slippage" type="number" step="0.0001" value="0.0005"></div>
            </div>
            <div class="field"><label>资金费率（8h，永续合约模拟，0 关闭）</label><input class="input" id="bt-funding" type="number" step="0.0001" value="0" placeholder="如 0.0001 = 0.01%"></div>
            <div class="input-row-3" style="align-items:flex-end">
              <div class="field"><label>我的模板</label><select class="select" id="bt-template"></select></div>
              <button class="btn btn-sm" id="bt-template-save" title="保存当前参数为模板">💾 保存</button>
              <button class="btn btn-sm" id="bt-template-load" title="载入所选模板">📂 载入</button>
            </div>
            <div class="hint">模板保存在本地浏览器，方便快速复用常用回测配置。</div>
            <button class="btn btn-sm btn-block" id="bt-opt" style="margin-top:10px">🔍 参数快速搜索</button>
            <div id="bt-opt-panel"></div>
            <button class="btn btn-sm btn-block" id="bt-compare" style="margin-top:10px">🔁 多策略同图对比</button>
            <div id="bt-compare-panel" style="display:none;margin-top:10px">
              <div class="hint">选择 2-4 个策略（可填参数 JSON），同一行情下对比权益曲线与指标。</div>
              <div id="bt-compare-rows"></div>
              <div style="display:flex;gap:8px;margin-top:8px">
                <button class="btn btn-sm" id="bt-compare-add">＋ 添加策略</button>
                <button class="btn btn-primary btn-sm" id="bt-compare-run">⚡ 开始对比</button>
              </div>
              <div id="bt-compare-status" class="hint" style="margin-top:8px"></div>
            </div>
          </div>
          <div class="run-btn-row">
            <button class="btn btn-primary btn-block btn-run" id="bt-run">⚡ 开始回测</button>
          </div>
          <div class="card">
            <div class="card-title">🕘 回测历史</div>
            <div id="bt-history" style="max-height:260px;overflow-y:auto;display:flex;flex-direction:column;gap:6px"></div>
          </div>
        </div>
        <div>
          <div id="bt-result">
            <div class="card"><div class="empty"><div class="empty-icon">📊</div>配置左侧参数，点击「开始回测」<br><span style="font-size:11px">支持经典策略 / 可视化规则 / 代码策略 · AI 优化建议 · 参数快速搜索</span></div></div>
          </div>
        </div>
      </div>
    `;
    const sel = document.getElementById("bt-strategy");
    if (App.state.useCustom) { state.strategy = "custom"; App.state.useCustom = false; }
    if (App.state.useCode) { state.strategy = "code"; App.state.useCode = false; }
    sel.innerHTML = '<option value="">加载策略库…</option>';
    sel.addEventListener("change", () => { state.strategy = sel.value; renderParams(); updateSyncBadge(); renderOptPanel(); });
    loadLibrary().then(() => {
      const ap = App.state.applyParams;
      if (ap) {
        App.state.applyParams = null;
        if (state.library.some((x) => x.name === ap.strategy)) {
          state.strategy = ap.strategy;
          state.params = ap.params || {};
          App.toast('已应用进化页参数组合，可微调后回测', 'success');
        }
      }
      if (state.strategy) sel.value = state.strategy;
      renderParams();
      updateSyncBadge();
      renderOptPanel();
    });
    document.getElementById("bt-run").addEventListener("click", run);
    document.getElementById("bt-preset").querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => applyPreset(c.dataset.preset)));
    document.getElementById("bt-opt").addEventListener("click", renderOptPanel);
    document.getElementById("bt-compare").addEventListener("click", toggleCompare);
    document.getElementById("bt-compare-add").addEventListener("click", () => {
      const rows = document.getElementById("bt-compare-rows");
      if (rows.querySelectorAll(".compare-row").length >= 4) { App.toast("最多对比 4 个策略", "info"); return; }
      const tpl = document.createElement("template");
      tpl.innerHTML = compareRowHTML("ma_cross", "{}").trim();
      rows.appendChild(tpl.content.firstElementChild);
      wireCompareRows();
    });
    document.getElementById("bt-compare-run").addEventListener("click", runCompare);
    refreshTemplateSelect();
    document.getElementById("bt-template-save").addEventListener("click", () => {
      const list = loadTemplates();
      const name = "模板 " + (list.length + 1);
      list.push({ name, ...collectTemplatePayload() });
      saveTemplates(list);
      refreshTemplateSelect();
      App.toast("已保存模板：" + name, "success");
    });
    document.getElementById("bt-template-load").addEventListener("click", () => {
      const sel = document.getElementById("bt-template");
      const list = loadTemplates();
      const t = list[sel.value];
      if (!t) { App.toast("请先选择一个模板", "info"); return; }
      applyTemplatePayload(t);
      App.toast("已载入模板：" + t.name, "success");
    });
    refreshHistory();
    if (App.state.latestResult) showResult(App.state.latestResult);
  }

  function updateSyncBadge() {
    const box = document.getElementById("bt-sync-badge");
    if (!box) return;
    if (state.strategy === "custom" || state.strategy === "code") {
      box.style.display = "";
      box.innerHTML = '<div class="hint" style="background:rgba(34,197,94,.08);border:1px solid rgba(34,197,94,.25);border-radius:8px;padding:8px 10px;color:var(--text)">✅ 策略来源：<b>策略构建</b>（已同步）<button class="btn btn-sm" id="bt-edit-builder" style="margin-left:8px">✏️ 去构建页编辑</button></div>';
      const btn = document.getElementById("bt-edit-builder");
      if (btn) btn.addEventListener("click", () => App.go("custom"));
    } else {
      box.style.display = "none";
    }
  }

  function applyPreset(name) {
    const p = PRESETS[name];
    if (!p) return;
    document.getElementById("bt-pos-pct").value = p.pos;
    document.getElementById("bt-leverage").value = p.lev;
    document.getElementById("bt-atr").value = p.atr;
    document.getElementById("bt-stop").value = p.stop;
    document.getElementById("bt-tp").value = p.tp;
    document.getElementById("bt-preset").querySelectorAll(".chip").forEach((c) => c.classList.toggle("active", c.dataset.preset === name));
    App.toast("已应用「" + p.label + "」预设", "success");
  }

  async function loadLibrary() {
    try {
      const { library } = await API.get("/api/strategies/library");
      state.library = library;
      const sel = document.getElementById("bt-strategy");
      if (sel) sel.innerHTML = '<option value="custom">🎛️ 自定义规则策略</option><option value="code">🧑‍💻 代码策略</option>' + library.map((s) => '<option value="' + s.name + '" ' + (s.name === state.strategy ? "selected" : "") + '>' + s.icon + " " + s.school + " · " + s.master.split("·")[0].trim() + '</option>').join("");
    } catch (e) { /* 忽略 */ }
  }

  function getDef() {
    if (state.strategy === "custom") return CUSTOM_DEF;
    if (state.strategy === "code") return { name: "🧑‍💻 代码策略", params: [] };
    return state.library.find((s) => s.name === state.strategy) || null;
  }

  function renderParams() {
    const box = document.getElementById("bt-params");
    if (state.strategy === "code") {
      renderCodeParams(box);
      return;
    }
    if (state.strategy === "custom") {
      const saved = state.customRules || App.state.customRules || DEFAULT_RULES;
      box.innerHTML = `
        <div class="field"><label>交易方向</label>
          <select class="select" id="bt-custom-dir">
            <option value="long_only" ${saved.direction !== "long_short" ? "selected" : ""}>只做多</option>
            <option value="long_short" ${saved.direction === "long_short" ? "selected" : ""}>多空都做</option>
          </select>
        </div>
        <div class="field"><label>规则 JSON（可在「策略构建」页可视化编辑）</label>
          <textarea id="bt-custom-rules" spellcheck="false" style="width:100%;min-height:220px;background:rgba(0,0,0,.3);color:var(--text);border:1px solid var(--border);border-radius:10px;padding:10px;font-family:var(--mono);font-size:11.5px;resize:vertical;outline:none">${JSON.stringify(saved.entry ? saved : DEFAULT_RULES, null, 2)}</textarea>
        </div>
        <div class="hint">条件支持 SMA/EMA/RSI/MACD/布林带/ATR/价格/成交量，AND/OR 组合。</div>`;
      return;
    }
    const def = getDef();
    if (!def) { box.innerHTML = '<div class="empty" style="padding:14px">策略库加载中…</div>'; return; }
    const saved = state.params || {};
    const savedVals = (key, d) => (saved[key] !== undefined ? saved[key] : d);
    box.innerHTML = `
      ${def.desc ? '<div class="hint" style="background:rgba(76,141,255,.07);border:1px solid rgba(76,141,255,.18);border-radius:8px;padding:8px 10px;margin-bottom:10px;color:var(--text)">' + def.desc + '<br><span style="color:var(--text-dim)">📖 ' + def.master + '</span></div>' : ""}
      ${def.params.map((p) => {
        if (p.type === "select") {
          return '<div class="field"><label>' + p.label + '</label><select class="select" data-param="' + p.k + '">' + p.options.map(([v, l]) => '<option value="' + v + '" ' + (String(savedVals(p.k, p.def)) === v ? "selected" : "") + '>' + l + '</option>').join("") + '</select></div>';
        }
        const step = p.step !== undefined ? 'step="' + p.step + '"' : "";
        return '<div class="field"><label>' + p.label + '</label><input class="input" type="number" ' + step + ' data-param="' + p.k + '" value="' + savedVals(p.k, p.def) + '"></div>';
      }).join("")}
    `;
  }

  function renderCodeParams(box) {
    const cc = App.state.customCode || {};
    box.innerHTML = `
      <div class="hint" style="background:rgba(124,92,255,.08);border:1px solid rgba(124,92,255,.22);border-radius:8px;padding:8px 10px;margin-bottom:10px;color:var(--text)">🧑‍💻 代码策略：直接编写 Python 定义交易信号，支持 sma/ema/rsi/macd/bollinger/atr/donchian 等指标函数。<br><span style="color:var(--text-dim)">也可在「策略构建」页的代码模式中编辑。</span></div>
      <div class="field"><label>参数 JSON（代码中通过 params 读取）</label>
        <input class="input" id="bt-code-params" spellcheck="false" value='${JSON.stringify(cc.params || DEFAULT_CODE_PARAMS)}'>
      </div>
      <div class="field"><label>Python 代码（必须定义 generate_signals(df, params)）</label>
        <textarea id="bt-code-editor" spellcheck="false"></textarea>
      </div>
      <button class="btn btn-sm" id="bt-code-template">📄 载入示例模板</button>
    `;
    const ta = document.getElementById("bt-code-editor");
    if (ta) {
      ta.value = cc.code || state.lastCode || state.templateCode || "";
      initCodeEditor(ta);
    }
    document.getElementById("bt-code-template").addEventListener("click", () => {
      if (state.cm && state.templateCode) { state.cm.setValue(state.templateCode); App.toast("示例模板已载入", "success"); }
    });
  }

  function initCodeEditor(ta) {
    if (state.cm || !window.CodeMirror) return;
    state.cm = CodeMirror.fromTextArea(ta, {
      mode: "python", lineNumbers: true, matchBrackets: true, indentUnit: 4,
      styleActiveLine: true, viewportMargin: Infinity,
    });
    state.cm.setSize("100%", 300);
  }

  function dataParams() {
    return { source: document.getElementById("bt-source").value, symbol: document.getElementById("bt-symbol").value.trim(), timeframe: document.getElementById("bt-timeframe").value, days: parseInt(document.getElementById("bt-days").value) || 365, seed: parseInt(document.getElementById("bt-seed").value) || 42 };
  }
  function riskParams(direction) {
    return { max_position_pct: parseFloat(document.getElementById("bt-pos-pct").value) || 0.5, leverage: parseFloat(document.getElementById("bt-leverage").value) || 1, atr_stop_mult: parseFloat(document.getElementById("bt-atr").value) || 2, stop_loss_pct: parseFloat(document.getElementById("bt-stop").value) || null, take_profit_pct: parseFloat(document.getElementById("bt-tp").value) || null, risk_per_trade_pct: parseFloat(document.getElementById("bt-risk-pct").value) || 0, trailing_stop_mult: parseFloat(document.getElementById("bt-trail-atr").value) || 0, break_even_after_mult: parseFloat(document.getElementById("bt-be-atr").value) || 0, max_drawdown_pct: parseFloat(document.getElementById("bt-dd-pct").value) || null, trade_direction: direction };
  }
  function btParams() {
    return { initial_capital: parseFloat(document.getElementById("bt-capital").value) || 10000, fee_rate: parseFloat(document.getElementById("bt-fee").value) || 0.001, slippage: parseFloat(document.getElementById("bt-slippage").value) || 0.0005, funding_rate_8h: parseFloat(document.getElementById("bt-funding").value) || 0 };
  }

  function collectParams() {
    if (state.strategy === "code") {
      if (!state.cm) throw new Error("代码编辑器未初始化");
      const code = state.cm.getValue();
      if (!code.includes("generate_signals")) throw new Error("代码中未找到 generate_signals(df, params) 函数");
      let params = {};
      try {
        params = JSON.parse(document.getElementById("bt-code-params").value || "{}");
      } catch (e) {
        throw new Error("参数 JSON 解析失败: " + e.message);
      }
      App.state.customCode = { code, params };
      return { strategy: { name: "code", params: { code: code, ...params } }, data: dataParams(), risk: riskParams("long_only"), backtest: btParams() };
    }
    if (state.strategy === "custom") {
      let rules;
      try { rules = JSON.parse(document.getElementById("bt-custom-rules").value); } catch (e) { throw new Error("规则 JSON 解析失败: " + e.message); }
      if (!rules.entry || !rules.entry.conditions || !rules.entry.conditions.length) throw new Error("自定义策略至少需要一个开仓条件");
      const direction = document.getElementById("bt-custom-dir").value;
      rules.direction = direction;
      state.customRules = rules;
      App.state.customRules = rules;
      return { strategy: { name: "custom", params: { rules, direction } }, data: dataParams(), risk: riskParams(direction), backtest: btParams() };
    }
    const def = getDef();
    const params = {};
    document.querySelectorAll("[data-param]").forEach((el) => { params[el.dataset.param] = el.type === "number" ? parseFloat(el.value) : el.value; });
    state.params = params;
    return { strategy: { name: state.strategy, params }, data: dataParams(), risk: riskParams(params.direction || "long_only"), backtest: btParams() };
  }

  async function run() {
    const btn = document.getElementById("bt-run");
    btn.disabled = true;
    btn.textContent = "⏳ 回测运行中…";
    try {
      const payload = collectParams();
      const { id } = await API.post("/api/backtest/run", payload);
      state.jobId = id;
      App.toast("回测任务已提交 (" + id + ")", "info");
      poll(id);
    } catch (e) {
      App.toast("提交失败: " + e.message, "error", 5000);
      btn.disabled = false;
      btn.textContent = "⚡ 开始回测";
    }
  }

  function poll(id) {
    if (state.polling) clearInterval(state.polling);
    state.polling = setInterval(async () => {
      try {
        const job = await API.get("/api/backtest/result/" + id);
        if (job.status === "running") return;
        clearInterval(state.polling);
        state.polling = null;
        const btn = document.getElementById("bt-run");
        if (btn) { btn.disabled = false; btn.textContent = "⚡ 开始回测"; }
        if (job.status === "error") {
          if (window.notifyUser) window.notifyUser("回测失败", job.error);
          App.toast("回测失败: " + job.error, "error", 6000);
          document.getElementById("bt-result").innerHTML = '<div class="card"><div class="empty"><div class="empty-icon">❌</div>回测失败<br><span style="font-size:11px;color:var(--red)">' + job.error + '</span></div></div>';
        } else {
          App.state.latestResult = job.result;
          state.result = job.result;
          state.jobId = id;
          showResult(job.result);
          if (window.notifyUser) window.notifyUser("回测完成", job.result.strategy + " · " + job.result.symbol + " " + job.result.timeframe);
          App.toast("回测完成 ✅", "success");
          refreshHistory();
        }
      } catch (e) {
        clearInterval(state.polling);
        state.polling = null;
        const btn = document.getElementById("bt-run");
        if (btn) { btn.disabled = false; btn.textContent = "⚡ 开始回测"; }
      }
    }, 1000);
  }
  function showResult(r) {
    const box = document.getElementById("bt-result");
    if (!box) return;
    const m = r.metrics;
    const stratLabel = r.strategy === "custom" ? "自定义规则" : r.strategy === "code" ? "代码策略" : r.strategy;
    const metricItems = [
      ["总收益率", FMT.pctSigned(m.total_return), FMT.cls(m.total_return)],
      ["年化收益率", FMT.pctSigned(m.annual_return), FMT.cls(m.annual_return)],
      ["买入持有", FMT.pctSigned(m.buy_hold_return), FMT.cls(m.buy_hold_return)],
      ["夏普比率", FMT.num(m.sharpe), m.sharpe > 0 ? "pos" : "neg"],
      ["索提诺", FMT.num(m.sortino), m.sortino > 0 ? "pos" : "neg"],
      ["最大回撤", FMT.pct(m.max_drawdown), "neg"],
      ["胜率", FMT.pct(m.win_rate), m.win_rate > 0.5 ? "pos" : ""],
      ["盈亏比", FMT.num(m.profit_factor), m.profit_factor > 1 ? "pos" : "neg"],
      ["期望值/笔", FMT.usd(m.expectancy), FMT.cls(m.expectancy)],
      ["平均单笔收益", FMT.pctSigned(m.avg_trade_return), FMT.cls(m.avg_trade_return)],
      ["恢复因子", FMT.num(m.recovery_factor), m.recovery_factor > 1 ? "pos" : ""],
      ["SQN 质量", FMT.num(m.sqn), m.sqn > 1 ? "pos" : ""],
      ["卡玛比率", FMT.num(m.calmar), m.calmar > 0 ? "pos" : "neg"],
      ["交易次数", m.num_trades, ""],
      ["总手续费", FMT.usd(m.total_fees), ""],
      ["资金费率", FMT.usd(m.funding_paid || 0), ""],
      ["下行波动率", FMT.pct(m.downside_dev), m.downside_dev > 0 ? "neg" : ""],
      ["VaR95", FMT.pct(m.var95), "neg"],
      ["CVaR95", FMT.pct(m.cvar95), "neg"],
      ["平均盈亏比", FMT.num(m.avg_win_loss_ratio), m.avg_win_loss_ratio > 1 ? "pos" : ""],
      ["尾部比率", FMT.num(m.tail_ratio), m.tail_ratio > 1 ? "pos" : ""],
      ["Alpha(年化)", FMT.pctSigned(m.alpha_annual), FMT.cls(m.alpha_annual)],
      ["Beta", FMT.num(m.beta), ""],
      ["超额收益", FMT.pctSigned(m.excess_return), FMT.cls(m.excess_return)],
      ["水下时间占比", FMT.pct(m.underwater_time_pct), "neg"],
      ["Ulcer 指数", FMT.num(m.ulcer), m.ulcer > 0 ? "neg" : ""],
      ["平均 R", FMT.num(m.avg_r), FMT.cls(m.avg_r)],
    ];
    box.innerHTML = `
      <div class="badge-row">
        <span class="badge badge-blue">${stratLabel}</span>
        <span class="badge badge-gray">${r.symbol} ${r.timeframe}</span>
        <span class="badge badge-gray">${r.source === "synthetic" ? "合成数据" : r.source}</span>
        <span class="badge ${m.total_return >= m.buy_hold_return ? "badge-green" : "badge-red"}">${m.total_return >= m.buy_hold_return ? "跑赢" : "跑输"}买入持有</span>
      </div>
      <div style="display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap">
        <button class="btn btn-primary btn-sm" id="bt-show-analysis">📄 分析报告</button>
        <button class="btn btn-sm" id="bt-ai-advice">🤖 AI 优化建议</button>
        <button class="btn btn-sm" id="bt-export-html">⬇ 导出 HTML 报告</button>
        <button class="btn btn-sm" id="bt-export-csv">⬇ 导出交易 CSV</button>
        <button class="btn btn-sm" id="bt-copy-summary">📋 复制摘要</button>
      </div>
      <div class="metrics-grid">
        ${metricItems.map(([l, v, c]) => '<div class="metric"><div class="metric-label">' + l + '</div><div class="metric-value ' + c + '">' + v + '</div></div>').join("")}
      </div>
      ${r.cost_sensitivity ? costSensHTML(r.cost_sensitivity, m) : ""}
      <div id="bt-ai-panel" style="display:none;margin-top:16px"></div>
      <div id="bt-analysis-panel" style="display:none;margin-top:16px"></div>
      <div class="grid grid-2" style="margin-top:16px">
        <div class="card"><div class="card-title">策略 vs 买入持有</div><div class="chart-canvas sm" id="bt-equity-chart" data-sync="bt"></div></div>
        <div class="card"><div class="card-title">回撤曲线</div><div class="chart-canvas sm" id="bt-dd-chart" data-sync="bt"></div></div>
      </div>
      <div class="section-title">交易明细 (${r.trades.length}${r.trades.length > 500 ? "，页面仅展示前 500 笔" : ""})</div>
      <div class="card" style="padding:0">
        <div class="table-wrap" style="max-height:360px">
          <table class="table">
            <thead><tr><th>方向</th><th>开仓时间</th><th class="num">开仓价</th><th>平仓时间</th><th class="num">平仓价</th><th class="num">数量</th><th class="num">手续费</th><th class="num">盈亏</th><th class="num">收益率</th><th>原因</th></tr></thead>
            <tbody>${r.trades.slice(0, 500).map((t) => '<tr><td><span class="badge ' + (t.side === "long" ? "badge-green" : "badge-red") + '">' + (t.side === "long" ? "多" : "空") + '</span></td><td>' + FMT.time(t.entry_time) + '</td><td class="num">' + FMT.price(t.entry_price) + '</td><td>' + FMT.time(t.exit_time) + '</td><td class="num">' + FMT.price(t.exit_price) + '</td><td class="num">' + t.quantity + '</td><td class="num">' + FMT.usd(t.fees) + '</td><td class="num ' + FMT.cls(t.pnl) + '">' + FMT.usd(t.pnl) + '</td><td class="num ' + FMT.cls(t.return_pct) + '">' + FMT.pctSigned(t.return_pct) + '</td><td><span class="badge badge-gray">' + t.reason + '</span></td></tr>').join("")}</tbody>
          </table>
        </div>
      </div>
    `;
    CH.clearRegistry();
    document.getElementById("bt-show-analysis").addEventListener("click", toggleAnalysis);
    document.getElementById("bt-ai-advice").addEventListener("click", aiAdvice);
    document.getElementById("bt-export-html").addEventListener("click", exportHtml);
    document.getElementById("bt-export-csv").addEventListener("click", () => {
      if (state.jobId) window.open("/api/backtest/result/" + state.jobId + "/trades.csv", "_blank");
    });
    document.getElementById("bt-copy-summary").addEventListener("click", () => copySummary(r, m));
    drawEquity(r);
    drawDrawdown(r);
  }

  function copySummary(r, m) {
    const lines = [
      "Quantiva 回测摘要",
      "策略: " + r.strategy + " | " + r.symbol + " " + r.timeframe + " | 数据源: " + r.source,
      "总收益: " + FMT.pctSigned(m.total_return) + " | 年化: " + FMT.pctSigned(m.annual_return) + " | 买入持有: " + FMT.pctSigned(m.buy_hold_return),
      "夏普: " + FMT.num(m.sharpe) + " | 索提诺: " + FMT.num(m.sortino) + " | 最大回撤: " + FMT.pct(m.max_drawdown),
      "胜率: " + FMT.pct(m.win_rate) + " | 盈亏比: " + FMT.num(m.profit_factor) + " | 交易数: " + m.num_trades,
      "期末权益: " + FMT.usd(m.final_equity) + " | 总手续费: " + FMT.usd(m.total_fees),
    ];
    const text = lines.join("\n");
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => App.toast("摘要已复制到剪贴板", "success")).catch(() => App.toast("复制失败", "error"));
    } else {
      const ta = document.createElement("textarea");
      ta.value = text; document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); App.toast("摘要已复制到剪贴板", "success"); } catch (e) { App.toast("复制失败", "error"); }
      ta.remove();
    }
  }

  // ---------- 回测参数模板（本地保存） ----------
  const TEMPLATE_KEY = "quantx_bt_templates";
  function loadTemplates() {
    try { return JSON.parse(localStorage.getItem(TEMPLATE_KEY) || "[]"); } catch (e) { return []; }
  }
  function saveTemplates(list) {
    try { localStorage.setItem(TEMPLATE_KEY, JSON.stringify(list)); } catch (e) {}
  }
  function refreshTemplateSelect() {
    const sel = document.getElementById("bt-template");
    if (!sel) return;
    const list = loadTemplates();
    sel.innerHTML = '<option value="">选择模板…</option>' + list.map((t, i) => '<option value="' + i + '">' + t.name + '</option>').join("");
  }
  function collectTemplatePayload() {
    const dirEl = document.querySelector("#bt-params [data-param=direction]");
    const direction = dirEl ? dirEl.value : "long_only";
    return { data: dataParams(), risk: riskParams(direction), backtest: btParams() };
  }
  function applyTemplatePayload(t) {
    const applyVal = (id, v) => { const el = document.getElementById(id); if (el && v !== undefined && v !== null) el.value = v; };
    if (t.data) { applyVal("bt-source", t.data.source); applyVal("bt-symbol", t.data.symbol); applyVal("bt-timeframe", t.data.timeframe); applyVal("bt-days", t.data.days); applyVal("bt-seed", t.data.seed); }
    if (t.risk) {
      applyVal("bt-pos-pct", t.risk.max_position_pct); applyVal("bt-leverage", t.risk.leverage);
      applyVal("bt-atr", t.risk.atr_stop_mult); applyVal("bt-stop", t.risk.stop_loss_pct || ""); applyVal("bt-tp", t.risk.take_profit_pct || "");
      applyVal("bt-risk-pct", t.risk.risk_per_trade_pct || ""); applyVal("bt-trail-atr", t.risk.trailing_stop_mult || "");
      applyVal("bt-be-atr", t.risk.break_even_after_mult || ""); applyVal("bt-dd-pct", t.risk.max_drawdown_pct || "");
    }
    if (t.backtest) { applyVal("bt-capital", t.backtest.initial_capital); applyVal("bt-fee", t.backtest.fee_rate); applyVal("bt-slippage", t.backtest.slippage); applyVal("bt-funding", t.backtest.funding_rate_8h || 0); }
  }

  function costSensHTML(cs, m) {
    const row = (k, label) => {
      const v = cs[k];
      if (!v) return "";
      return '<tr><td>' + label + '</td><td class="num ' + FMT.cls(v.total_return) + '">' + FMT.pctSigned(v.total_return) + '</td><td class="num ' + FMT.cls(v.sharpe) + '">' + FMT.num(v.sharpe) + '</td><td class="num">' + (v.num_trades ?? "--") + '</td></tr>';
    };
    return '<div class="card" style="margin-top:14px"><div class="card-title">成本敏感性（手续费/滑点压力测试）</div><div class="table-wrap"><table class="table"><thead><tr><th>场景</th><th class="num">总收益</th><th class="num">夏普</th><th class="num">交易数</th></tr></thead><tbody>'
      + '<tr><td>基准（1x）</td><td class="num ' + FMT.cls(m.total_return) + '">' + FMT.pctSigned(m.total_return) + '</td><td class="num ' + FMT.cls(m.sharpe) + '">' + FMT.num(m.sharpe) + '</td><td class="num">' + m.num_trades + '</td></tr>'
      + row("halved", "成本减半（0.5x）")
      + row("doubled", "成本加倍（2x）")
      + '</tbody></table></div></div>';
  }

  function toggleAnalysis() {
    const panel = document.getElementById("bt-analysis-panel");
    if (!panel) return;
    if (panel.style.display !== "none") { panel.style.display = "none"; return; }
    panel.style.display = "";
    const r = state.result;
    if (!r || !r.analysis) { panel.innerHTML = '<div class="loading"><div class="spinner"></div>加载分析…</div>'; loadAnalysis(); return; }
    renderAnalysis(r.analysis, r.metrics);
  }

  async function loadAnalysis() {
    try {
      const job = await API.get("/api/backtest/result/" + state.jobId);
      if (job.result) { state.result = job.result; App.state.latestResult = job.result; renderAnalysis(job.result.analysis, job.result.metrics); }
    } catch (e) {
      document.getElementById("bt-analysis-panel").innerHTML = '<div class="card"><div class="empty">分析加载失败: ' + e.message + '</div></div>';
    }
  }

  function rollingHTML(rs) {
    if (!rs || !rs.available) return "";
    const sh = rs.sharpe || {};
    const stability = rs.stability_score || 0;
    return '<div class="card" style="margin-top:14px"><div class="card-title">📊 滚动稳定性（窗口 ' + rs.window + ' 根 K 线）</div>'
      + '<div class="metrics-grid">'
      + '<div class="metric"><div class="metric-label">滚动夏普均值</div><div class="metric-value ' + FMT.cls(sh.mean) + '">' + FMT.num(sh.mean) + '</div></div>'
      + '<div class="metric"><div class="metric-label">滚动夏普波动</div><div class="metric-value">' + FMT.num(sh.std) + '</div></div>'
      + '<div class="metric"><div class="metric-label">夏普范围</div><div class="metric-value">' + FMT.num(sh.min) + ' ~ ' + FMT.num(sh.max) + '</div></div>'
      + '<div class="metric"><div class="metric-label">最新滚动夏普</div><div class="metric-value ' + FMT.cls(sh.last) + '">' + FMT.num(sh.last) + '</div></div>'
      + '<div class="metric"><div class="metric-label">夏普>0 占比</div><div class="metric-value">' + FMT.pct(sh.positive_pct) + '</div></div>'
      + '<div class="metric"><div class="metric-label">稳定性得分</div><div class="metric-value ' + (stability > 1 ? "pos" : stability < -1 ? "neg" : "") + '">' + FMT.num(stability) + '</div></div>'
      + '<div class="metric"><div class="metric-label">滚动波动均值</div><div class="metric-value neg">' + FMT.pct(rs.volatility_mean) + '</div></div>'
      + '<div class="metric"><div class="metric-label">滚动回撤均值</div><div class="metric-value neg">' + FMT.pct(rs.max_drawdown_mean) + '</div></div>'
      + '</div>'
      + '<div class="chart-canvas xs" id="bt-rolling-chart" style="margin-top:10px"></div>'
      + '</div>';
  }

  function drawRolling(rs) {
    const el = document.getElementById("bt-rolling-chart");
    if (!el || !rs || !rs.available || !rs.sharpe || !rs.sharpe.series || !rs.sharpe.series.length) return;
    CH.clearRegistry();
    CH.setFallback(el, { series: [{ color: CH.palette().c[0], points: rs.sharpe.series, area: true }] });
    CH.createChart(el);
  }

  function renderAnalysis(a, m) {
    const panel = document.getElementById("bt-analysis-panel");
    if (!panel) return;
    const tr = a.trades || {};
    const dd = a.drawdown || {};
    const perf = a.performance || {};
    const sideRows = Object.entries(tr.by_side || {}).map(([k, v]) => '<tr><td>' + (k === "long" ? "做多" : "做空") + '</td><td>' + v.count + '</td><td>' + (v.win_rate * 100).toFixed(1) + '%</td><td class="' + FMT.cls(v.total) + '">' + FMT.usd(v.total) + '</td></tr>').join("");
    const reasonRows = Object.entries(tr.by_reason || {}).map(([k, v]) => '<tr><td>' + k + '</td><td>' + v.count + '</td><td>' + (v.win_rate * 100).toFixed(1) + '%</td><td class="' + FMT.cls(v.total) + '">' + FMT.usd(v.total) + '</td></tr>').join("");
    const matrix = a.monthly_matrix || {};
    const months = ["01","02","03","04","05","06","07","08","09","10","11","12"];
    const matrixHead = '<tr><th>年/月</th>' + months.map((x) => '<th>' + x + '</th>').join("") + '<th>年度</th></tr>';
    const matrixRows = Object.keys(matrix).map((y) => {
      const cells = months.map((mm) => {
        const v = matrix[y][mm];
        if (v === null || v === undefined) return '<td class="dim">-</td>';
        return '<td class="' + FMT.cls(v) + '">' + (v * 100).toFixed(1) + '%</td>';
      }).join("");
      const yearly = months.reduce((s, mm) => s + (matrix[y][mm] || 0), 0);
      return '<tr><td><b>' + y + '</b></td>' + cells + '<td class="' + FMT.cls(yearly) + '"><b>' + (yearly * 100).toFixed(1) + '%</b></td></tr>';
    }).join("");
    panel.innerHTML = '<div class="card"><div class="card-title">📄 深度分析报告</div>'
      + '<div class="metrics-grid">'
      + '<div class="metric"><div class="metric-label">卡玛比率</div><div class="metric-value">' + FMT.num(perf.calmar) + '</div></div>'
      + '<div class="metric"><div class="metric-label">最大连胜</div><div class="metric-value">' + ((tr.streaks || {}).max_consecutive_wins || 0) + '</div></div>'
      + '<div class="metric"><div class="metric-label">最大连亏</div><div class="metric-value neg">' + ((tr.streaks || {}).max_consecutive_losses || 0) + '</div></div>'
      + '<div class="metric"><div class="metric-label">最大单笔盈利</div><div class="metric-value pos">' + FMT.usd(tr.max_win) + '</div></div>'
      + '<div class="metric"><div class="metric-label">最大单笔亏损</div><div class="metric-value neg">' + FMT.usd(tr.max_loss) + '</div></div>'
      + '<div class="metric"><div class="metric-label">平均持仓</div><div class="metric-value">' + FMT.num(tr.avg_holding_hours) + 'h</div></div>'
      + '<div class="metric"><div class="metric-label">回撤次数</div><div class="metric-value">' + (dd.num_drawdowns || 0) + '</div></div>'
      + '<div class="metric"><div class="metric-label">最长回撤</div><div class="metric-value neg">' + FMT.num(dd.longest_drawdown_days) + '天</div></div>'
      + '<div class="metric"><div class="metric-label">平均回撤</div><div class="metric-value neg">' + FMT.pct(dd.avg_drawdown) + '</div></div>'
      + '<div class="metric"><div class="metric-label">当前回撤</div><div class="metric-value neg">' + FMT.pct(dd.current_drawdown) + '</div></div>'
      + '</div>'
      + rollingHTML(a.rolling_stability)
      + '<div class="section-title">📅 月度收益矩阵</div>'
      + '<div class="table-wrap" style="max-height:320px"><table class="table matrix">' + matrixHead + (matrixRows || "<tr><td colspan='14' class='dim'>无数据</td></tr>") + '</table></div>'
      + '<div class="grid grid-2" style="margin-top:14px"><div><div class="section-title">📦 按方向</div><div class="table-wrap" style="max-height:200px"><table class="table"><tr><th>方向</th><th>笔数</th><th>胜率</th><th>总盈亏</th></tr>' + (sideRows || "<tr><td colspan=4 class=dim>无</td></tr>") + '</table></div></div>'
      + '<div><div class="section-title">📦 按平仓原因</div><div class="table-wrap" style="max-height:200px"><table class="table"><tr><th>原因</th><th>笔数</th><th>胜率</th><th>总盈亏</th></tr>' + (reasonRows || "<tr><td colspan=4 class=dim>无</td></tr>") + '</table></div></div></div></div>';
    drawRolling(a.rolling_stability);
  }

  async function aiAdvice() {
    const btn = document.getElementById("bt-ai-advice");
    if (!btn || !state.jobId) return;
    btn.disabled = true;
    btn.textContent = "🤖 AI 分析中…";
    const panel = document.getElementById("bt-ai-panel");
    panel.style.display = "";
    panel.innerHTML = '<div class="loading"><div class="spinner"></div>AI 正在分析策略…</div>';
    try {
      const res = await API.post("/api/ai/advice", { job_id: state.jobId });
      panel.innerHTML = '<div class="card"><div class="card-title">🤖 AI 策略优化建议</div><div style="white-space:pre-wrap;line-height:1.8;font-size:13px">' + escHtml(res.advice) + '</div></div>';
      App.toast("AI 分析完成", "success");
    } catch (e) {
      panel.innerHTML = '<div class="card"><div class="empty">⚠️ ' + escHtml(e.message) + '</div></div>';
    } finally {
      btn.disabled = false;
      btn.textContent = "🤖 AI 优化建议";
    }
  }

  function exportHtml() {
    if (!state.jobId) return;
    window.open("/api/report/" + state.jobId + "/html", "_blank");
  }
  // ---------- 参数快速搜索 ----------
  function renderOptPanel() {
    const box = document.getElementById("bt-opt-panel");
    if (!box) return;
    if (state.strategy === "custom" || state.strategy === "code") {
      box.innerHTML = '<div class="hint" style="margin-top:8px">参数搜索支持经典策略库。自定义 / 代码策略可前往「策略进化」页使用完整能力。</div>'
        + '<button class="btn btn-sm" id="bt-opt-go-evolution">🧬 前往策略进化</button>';
      const btn = document.getElementById("bt-opt-go-evolution");
      if (btn) btn.addEventListener("click", () => App.go("evolution"));
      return;
    }
    const def = getDef();
    if (!def) return;
    const numParams = (def.params || []).filter((p) => p.type !== "select");
    if (!numParams.length) { box.innerHTML = '<div class="hint" style="margin-top:8px">该策略无可搜索的数值参数。</div>'; return; }
    const paramOptions = numParams.map((p) => '<option value="' + p.k + '">' + p.label + '</option>').join("");
    box.innerHTML = `
      <div class="card" style="margin-top:12px">
        <div class="card-title">🔍 参数快速搜索（自动批量回测）</div>
        <div class="field"><label>优化目标</label>
          <select class="select" id="bt-opt-target">
            <option value="sharpe">夏普比率</option>
            <option value="total_return">总收益率</option>
            <option value="annual_return">年化收益率</option>
            <option value="win_rate">胜率</option>
            <option value="profit_factor">盈亏比</option>
          </select>
        </div>
        <div class="field"><label>参数 1</label><div style="display:flex;gap:8px;align-items:center">
          <select class="select" id="bt-opt-p1" style="flex:1">${paramOptions}</select>
          <input class="input" id="bt-opt-p1-min" type="number" placeholder="最小" style="width:80px">
          <input class="input" id="bt-opt-p1-max" type="number" placeholder="最大" style="width:80px">
          <input class="input" id="bt-opt-p1-step" type="number" placeholder="步长" style="width:70px">
        </div></div>
        <div class="field"><label>参数 2（可选）</label><div style="display:flex;gap:8px;align-items:center">
          <select class="select" id="bt-opt-p2" style="flex:1"><option value="">（不搜索）</option>${paramOptions}</select>
          <input class="input" id="bt-opt-p2-min" type="number" placeholder="最小" style="width:80px">
          <input class="input" id="bt-opt-p2-max" type="number" placeholder="最大" style="width:80px">
          <input class="input" id="bt-opt-p2-step" type="number" placeholder="步长" style="width:70px">
        </div></div>
        <div class="field"><label>最大组合数</label><input class="input" id="bt-opt-max" type="number" value="30"></div>
        <button class="btn btn-primary btn-sm btn-block" id="bt-opt-run">⚡ 开始搜索</button>
        <div class="hint" id="bt-opt-status" style="margin-top:8px"></div>
        <div id="bt-opt-results"></div>
      </div>`;
    const cur = state.params || {};
    const setRange = (prefix, p) => {
      const v = cur[p.k] !== undefined ? cur[p.k] : p.def;
      document.getElementById(prefix + "-min").value = Math.round(v * 0.6 * 100) / 100;
      document.getElementById(prefix + "-max").value = Math.round(v * 1.4 * 100) / 100;
      document.getElementById(prefix + "-step").value = p.step !== undefined ? p.step : (v >= 10 ? 5 : 1);
    };
    if (numParams[0]) setRange("bt-opt-p1", numParams[0]);
    if (numParams[1]) { document.getElementById("bt-opt-p2").value = numParams[1].k; setRange("bt-opt-p2", numParams[1]); }
    document.getElementById("bt-opt-run").addEventListener("click", runOpt);
  }

  function genRange(min, max, step) {
    const out = [];
    for (let v = min; v <= max + 1e-9; v += step) out.push(Math.round(v * 1000) / 1000);
    return out;
  }

  async function runOpt() {
    const btn = document.getElementById("bt-opt-run");
    const status = document.getElementById("bt-opt-status");
    btn.disabled = true;
    status.textContent = "⏳ 正在提交搜索任务…";
    try {
      const p1 = document.getElementById("bt-opt-p1").value;
      const min1 = parseFloat(document.getElementById("bt-opt-p1-min").value);
      const max1 = parseFloat(document.getElementById("bt-opt-p1-max").value);
      const step1 = parseFloat(document.getElementById("bt-opt-p1-step").value);
      if (!p1 || isNaN(min1) || isNaN(max1) || !(step1 > 0)) throw new Error("请填写参数 1 的最小 / 最大 / 步长");
      const ranges = { [p1]: genRange(min1, max1, step1) };
      const p2 = document.getElementById("bt-opt-p2").value;
      if (p2) {
        const min2 = parseFloat(document.getElementById("bt-opt-p2-min").value);
        const max2 = parseFloat(document.getElementById("bt-opt-p2-max").value);
        const step2 = parseFloat(document.getElementById("bt-opt-p2-step").value);
        if (isNaN(min2) || isNaN(max2) || !(step2 > 0)) throw new Error("参数 2 的最小 / 最大 / 步长无效");
        ranges[p2] = genRange(min2, max2, step2);
      }
      const maxCombos = parseInt(document.getElementById("bt-opt-max").value) || 30;
      const target = document.getElementById("bt-opt-target").value;
      const payload = {
        strategy: state.strategy,
        param_ranges: ranges,
        data: dataParams(),
        risk: riskParams("long_only"),
        target,
        max_combos: maxCombos,
      };
      const { id } = await API.post("/api/evolution/optimize", payload);
      state.optJobId = id;
      status.textContent = "⏳ 搜索中（任务 " + id + "）…";
      pollOpt(id);
    } catch (e) {
      status.textContent = "❌ " + e.message;
      btn.disabled = false;
    }
  }

  function pollOpt(id) {
    if (state.optPolling) clearInterval(state.optPolling);
    state.optPolling = setInterval(async () => {
      try {
        const job = await API.get("/api/evolution/result/" + id);
        const status = document.getElementById("bt-opt-status");
        if (job.status === "running") { if (status && job.progress) status.textContent = "⏳ 搜索中：" + job.progress; return; }
        clearInterval(state.optPolling);
        state.optPolling = null;
        const btn = document.getElementById("bt-opt-run");
        if (btn) btn.disabled = false;
        if (job.status === "error") { if (status) status.textContent = "❌ " + job.error; return; }
        if (status) status.textContent = "✅ 完成，共 " + ((job.result && job.result.total_combos) || 0) + " 组";
        renderOptResults(job.result);
      } catch (e) {
        clearInterval(state.optPolling);
        state.optPolling = null;
      }
    }, 1200);
  }

  function renderOptResults(result) {
    const box = document.getElementById("bt-opt-results");
    if (!box) return;
    const rows = (result && result.results) || [];
    if (!rows.length) { box.innerHTML = '<div class="empty" style="padding:12px">无结果</div>'; return; }
    box.innerHTML = '<div class="section-title" style="margin-top:12px">🏆 搜索结果（Top ' + Math.min(rows.length, 8) + '，目标：' + (result.target || "") + '）</div>'
      + '<div class="table-wrap" style="max-height:300px"><table class="table"><thead><tr><th>参数组合</th><th class="num">目标值</th><th class="num">总收益</th><th class="num">夏普</th><th class="num">回撤</th><th class="num">胜率</th><th class="num">交易数</th><th>操作</th></tr></thead><tbody>'
      + rows.slice(0, 8).map((r) => {
        const m = r.metrics || {};
        const pStr = Object.entries(r.params || {}).map(([k, v]) => k + "=" + v).join(" ");
        return '<tr><td style="font-size:11px;font-family:var(--mono)">' + pStr + '</td><td class="num">' + FMT.num(r.target_value) + '</td><td class="num ' + FMT.cls(m.total_return) + '">' + FMT.pctSigned(m.total_return) + '</td><td class="num">' + FMT.num(m.sharpe) + '</td><td class="num neg">' + FMT.pct(m.max_drawdown) + '</td><td class="num">' + FMT.pct(m.win_rate) + '</td><td class="num">' + (m.num_trades || 0) + '</td><td><button class="btn btn-sm" data-apply="' + rows.indexOf(r) + '">应用</button></td></tr>';
      }).join("")
      + '</tbody></table></div>'
      + '<div class="hint">点击「应用」把该参数组合填入左侧参数框，再点「开始回测」验证。</div>';
    box.querySelectorAll("[data-apply]").forEach((el) => el.addEventListener("click", () => applyOptParams(rows[parseInt(el.dataset.apply, 10)].params)));
  }

  function applyOptParams(params) {
    Object.entries(params || {}).forEach(([k, v]) => {
      const el = document.querySelector('[data-param="' + k + '"]');
      if (el) el.value = v;
    });
    App.toast("已应用参数组合，可点击「开始回测」验证", "success");
  }

  function escHtml(s) { return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }

  function drawEquity(r) {
    const el = document.getElementById("bt-equity-chart");
    if (!el) return;
    const palBT = CH.palette();
    CH.setFallback(el, { series: [{ color: palBT.c[0], points: r.equity_curve, area: true }, { color: palBT.text, points: r.benchmark }] });
    const ch = CH.createChart(el);
    if (!ch) return;
    const s = ch.addAreaSeries({ lineColor: palBT.c[0], topColor: "rgba(76,141,255,0.22)", bottomColor: "rgba(76,141,255,0)", lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
    s.setData(r.equity_curve.map(([ts, v]) => ({ time: Math.floor(ts / 1000), value: v })));
    const b = ch.addLineSeries({ color: palBT.text, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    b.setData(r.benchmark.map(([ts, v]) => ({ time: Math.floor(ts / 1000), value: v })));
    ch.timeScale().fitContent();
  }

  function drawDrawdown(r) {
    const el = document.getElementById("bt-dd-chart");
    if (!el) return;
    CH.setFallback(el, { series: [{ color: CH.palette().down, points: r.drawdown.map(([ts, v]) => [ts, v * 100]) }] });
    const ch = CH.createChart(el);
    if (!ch) return;
    const s = ch.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
    s.setData(r.drawdown.map(([ts, v]) => ({ time: Math.floor(ts / 1000), value: v * 100, color: CH.palette().down })));
    ch.timeScale().fitContent();
  }

  // ---------- 多策略同图对比 ----------
  function compareRowHTML(name, paramsJSON) {
    const opts = (state.library || []).map((s) => '<option value="' + s.name + '" ' + (s.name === name ? "selected" : "") + '>' + s.icon + " " + s.master.split("·")[0].trim() + '</option>').join("");
    return '<div class="compare-row" style="display:flex;gap:6px;align-items:center;margin-bottom:6px">'
      + '<select class="select compare-strategy" style="flex:1.3">' + opts + '</select>'
      + '<input class="input compare-params" style="flex:1" placeholder="参数 JSON，如 {\"fast\":10}" value="' + (paramsJSON || "{}") + '">'
      + '<button class="btn btn-sm btn-danger compare-del" title="移除">×</button>'
      + '</div>';
  }

  function toggleCompare() {
    const panel = document.getElementById("bt-compare-panel");
    if (!panel) return;
    const show = panel.style.display === "none";
    panel.style.display = show ? "" : "none";
    if (show && !document.querySelectorAll("#bt-compare-rows .compare-row").length) {
      document.getElementById("bt-compare-rows").innerHTML = compareRowHTML("ma_cross", "{}") + compareRowHTML("rsi_reversion", "{}");
      wireCompareRows();
    }
  }

  function wireCompareRows() {
    document.querySelectorAll("#bt-compare-rows .compare-del").forEach((btn) => {
      btn.addEventListener("click", () => {
        const rows = document.querySelectorAll("#bt-compare-rows .compare-row");
        if (rows.length <= 1) { App.toast("至少保留一个策略", "info"); return; }
        btn.closest(".compare-row").remove();
      });
    });
  }

  async function runCompare() {
    const btn = document.getElementById("bt-compare-run");
    const status = document.getElementById("bt-compare-status");
    btn.disabled = true;
    status.textContent = "对比运行中…";
    try {
      const rows = Array.from(document.querySelectorAll("#bt-compare-rows .compare-row"));
      if (!rows.length) throw new Error("请先添加策略");
      const strategies = rows.map((row, i) => {
        const name = row.querySelector(".compare-strategy").value;
        let params = {};
        try {
          params = JSON.parse(row.querySelector(".compare-params").value || "{}");
        } catch (e) {
          throw new Error("第 " + (i + 1) + " 行参数 JSON 解析失败: " + e.message);
        }
        return { name, params, label: name };
      });
      const payload = { strategies, data: dataParams(), risk: riskParams("long_only"), backtest: btParams() };
      const { id } = await API.post("/api/backtest/compare", payload);
      state.compareJobId = id;
      pollCompare(id);
    } catch (e) {
      status.textContent = "";
      App.toast("对比提交失败: " + e.message, "error", 5000);
      btn.disabled = false;
    }
  }

  function pollCompare(id) {
    if (state.comparePolling) clearInterval(state.comparePolling);
    state.comparePolling = setInterval(async () => {
      try {
        const job = await API.get("/api/backtest/compare/" + id);
        if (job.status === "running") return;
        clearInterval(state.comparePolling);
        state.comparePolling = null;
        const btn = document.getElementById("bt-compare-run");
        if (btn) btn.disabled = false;
        const status = document.getElementById("bt-compare-status");
        if (status) status.textContent = "";
        if (job.status === "error") {
          App.toast("对比失败: " + job.error, "error", 6000);
          document.getElementById("bt-result").innerHTML = '<div class="card"><div class="empty"><div class="empty-icon">❌</div>对比失败<br><span style="font-size:11px;color:var(--red)">' + escHtml(job.error || "") + '</span></div></div>';
          return;
        }
        showCompareResult(job.results || []);
        App.toast("对比完成", "success");
      } catch (e) {
        clearInterval(state.comparePolling);
        state.comparePolling = null;
        const btn = document.getElementById("bt-compare-run");
        if (btn) btn.disabled = false;
      }
    }, 1000);
  }

  function showCompareResult(results) {
    const box = document.getElementById("bt-result");
    if (!box) return;
    const COLORS = CH.palette().c;
    const symEl = document.getElementById("bt-symbol");
    const tfEl = document.getElementById("bt-timeframe");
    const sym = symEl ? symEl.value : "BTC/USDT";
    const tf = tfEl ? tfEl.value : "1h";
    const rows = results.map((r, i) => {
      const m = r.metrics;
      if (!m) {
        return '<tr><td>' + escHtml(r.label) + '</td><td colspan="7" style="color:var(--red)">失败：' + escHtml(r.error || "") + '</td></tr>';
      }
      return '<tr><td><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:' + COLORS[i % COLORS.length] + ';margin-right:6px"></span>' + escHtml(r.label) + '</td>'
        + '<td class="num ' + FMT.cls(m.total_return) + '">' + FMT.pctSigned(m.total_return) + '</td>'
        + '<td class="num ' + FMT.cls(m.annual_return) + '">' + FMT.pctSigned(m.annual_return) + '</td>'
        + '<td class="num ' + FMT.cls(m.sharpe) + '">' + FMT.num(m.sharpe) + '</td>'
        + '<td class="num neg">' + FMT.pct(m.max_drawdown) + '</td>'
        + '<td class="num">' + FMT.pct(m.win_rate) + '</td>'
        + '<td class="num">' + FMT.num(m.num_trades) + '</td>'
        + '<td class="num">' + FMT.usd(m.final_equity) + '</td></tr>';
    }).join("");
    box.innerHTML = '<div class="badge-row"><span class="badge badge-blue">多策略对比</span><span class="badge badge-gray">' + sym + ' ' + tf + '</span><span class="badge badge-gray">' + results.length + ' 个策略</span></div>'
      + '<div class="card"><div class="card-title">权益曲线对比（同图）</div><div class="chart-canvas sm" id="bt-compare-chart"></div></div>'
      + '<div class="card" style="padding:0;margin-top:14px"><div class="table-wrap" style="max-height:360px">'
      + '<table class="table"><thead><tr><th>策略</th><th class="num">总收益</th><th class="num">年化</th><th class="num">夏普</th><th class="num">最大回撤</th><th class="num">胜率</th><th class="num">交易数</th><th class="num">期末权益</th></tr></thead><tbody>'
      + rows + '</tbody></table></div></div>';
    CH.clearRegistry();
    const el = document.getElementById("bt-compare-chart");
    if (el) {
      const series = results.map((r, i) => ({ color: COLORS[i % COLORS.length], points: r.equity_curve || [], area: false }));
      CH.setFallback(el, { series });
      CH.createChart(el);
    }
  }

  async function refreshHistory() {
    const box = document.getElementById("bt-history");
    if (!box) return;
    try {
      const { jobs } = await API.get("/api/backtest/jobs");
      if (!jobs.length) { box.innerHTML = '<div class="empty" style="padding:16px">暂无历史记录</div>'; return; }
      box.innerHTML = jobs.slice(0, 15).map((j) => {
        const m = j.metrics || {};
        const label = j.strategy === "custom" ? "自定义" : j.strategy === "code" ? "代码" : j.strategy;
        const statusBadge = j.status === "running" ? '<span class="badge badge-amber">运行中</span>' : j.status === "error" ? '<span class="badge badge-red">失败</span>' : '<span class="badge badge-green">' + FMT.pctSigned(m.total_return) + '</span>';
        return '<div class="log-item info" style="cursor:pointer" data-job="' + j.id + '"><span class="badge badge-blue">' + label + '</span><span style="flex:1;font-size:12px">' + j.symbol + " " + j.timeframe + '</span>' + statusBadge + '<button class="btn btn-sm" data-rerun="' + j.id + '" title="用原参数重新回测">↻ 重跑</button></div>';
      }).join("");
      box.querySelectorAll("[data-rerun]").forEach((btn) => btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        try {
          const { id } = await API.post("/api/backtest/rerun/" + btn.dataset.rerun);
          state.jobId = id;
          App.toast("已用原参数重新提交回测", "success");
          poll(id);
        } catch (err) {
          App.toast("重跑失败: " + err.message, "error", 5000);
        }
      }));
      box.querySelectorAll("[data-job]").forEach((el) => el.addEventListener("click", async () => {
        const job = await API.get("/api/backtest/result/" + el.dataset.job);
        if (job.result) { App.state.latestResult = job.result; state.result = job.result; state.jobId = el.dataset.job; showResult(job.result); }
      }));
    } catch (e) { /* 忽略 */ }
  }

  return { render, refresh() { refreshHistory(); } };
})());
