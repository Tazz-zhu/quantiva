/* ============ 策略构建器（可视化规则 / 代码策略 双模式） ============ */
App.register("custom", (() => {
  const state = { schema: null, direction: "long_only", mode: "visual", cm: null, templateCode: "", savedCode: "", lastCode: "" };
  let uid = 0;
  const STORE_KEY = "qx_saved_strategies";
  const PARAM_SPEC = {
    sma: [{ k: "period", label: "周期", def: 20 }],
    ema: [{ k: "period", label: "周期", def: 20 }],
    rsi: [{ k: "period", label: "周期", def: 14 }],
    atr: [{ k: "period", label: "周期", def: 14 }],
    boll_upper: [{ k: "period", label: "周期", def: 20 }, { k: "num_std", label: "倍数", def: 2, step: 0.1 }],
    boll_mid: [{ k: "period", label: "周期", def: 20 }, { k: "num_std", label: "倍数", def: 2, step: 0.1 }],
    boll_lower: [{ k: "period", label: "周期", def: 20 }, { k: "num_std", label: "倍数", def: 2, step: 0.1 }],
    macd_dif: [], macd_dea: [], macd_hist: [], close: [], open: [], high: [], low: [], volume: [],
  };
  // 经典可视化策略模板：一键载入后自由微调
  const VISUAL_TEMPLATES = [
    { name: "双均线交叉", desc: "快线上穿慢线做多，下穿离场", direction: "long_only",
      entry: { logic: "all", conditions: [{ indicator: "sma", params: { period: 20 }, op: ">", compare: "indicator", compare_indicator: "sma", compare_params: { period: 50 } }] },
      exit: { logic: "any", conditions: [{ indicator: "sma", params: { period: 20 }, op: "<", compare: "indicator", compare_indicator: "sma", compare_params: { period: 50 } }] } },
    { name: "RSI 超卖反转", desc: "RSI 低于 30 买入，高于 70 卖出", direction: "long_only",
      entry: { logic: "all", conditions: [{ indicator: "rsi", params: { period: 14 }, op: "<", compare: "number", value: 30 }] },
      exit: { logic: "any", conditions: [{ indicator: "rsi", params: { period: 14 }, op: ">", compare: "number", value: 70 }] } },
    { name: "MACD 金叉死叉", desc: "DIF 上穿 DEA 做多，下穿离场", direction: "long_only",
      entry: { logic: "all", conditions: [{ indicator: "macd_dif", params: {}, op: ">", compare: "indicator", compare_indicator: "macd_dea", compare_params: {} }] },
      exit: { logic: "any", conditions: [{ indicator: "macd_dif", params: {}, op: "<", compare: "indicator", compare_indicator: "macd_dea", compare_params: {} }] } },
    { name: "布林带突破", desc: "收盘突破上轨做多，跌破中轨离场", direction: "long_only",
      entry: { logic: "all", conditions: [{ indicator: "close", params: {}, op: ">", compare: "indicator", compare_indicator: "boll_upper", compare_params: { period: 20, num_std: 2 } }] },
      exit: { logic: "any", conditions: [{ indicator: "close", params: {}, op: "<", compare: "indicator", compare_indicator: "boll_mid", compare_params: { period: 20, num_std: 2 } }] } },
    { name: "双指标共振", desc: "均线多头 + RSI 不过热同时满足", direction: "long_only",
      entry: { logic: "all", conditions: [{ indicator: "sma", params: { period: 20 }, op: ">", compare: "indicator", compare_indicator: "sma", compare_params: { period: 50 } }, { indicator: "rsi", params: { period: 14 }, op: "<", compare: "number", value: 70 }] },
      exit: { logic: "any", conditions: [{ indicator: "sma", params: { period: 20 }, op: "<", compare: "indicator", compare_indicator: "sma", compare_params: { period: 50 } }] } },
    { name: "ATR 波动趋势", desc: "收盘站上均线且 ATR 放大确认趋势", direction: "long_only",
      entry: { logic: "all", conditions: [{ indicator: "close", params: {}, op: ">", compare: "indicator", compare_indicator: "sma", compare_params: { period: 20 } }, { indicator: "atr", params: { period: 14 }, op: ">", compare: "number", value: 50 }] },
      exit: { logic: "any", conditions: [{ indicator: "close", params: {}, op: "<", compare: "indicator", compare_indicator: "sma", compare_params: { period: 20 } }] } },
    { name: "多空双向通道", desc: "突破上轨做多，跌破下轨做空", direction: "long_short",
      entry: { logic: "all", conditions: [{ indicator: "close", params: {}, op: ">", compare: "indicator", compare_indicator: "boll_upper", compare_params: { period: 20, num_std: 2 } }] },
      exit: { logic: "all", conditions: [{ indicator: "close", params: {}, op: "<", compare: "indicator", compare_indicator: "boll_mid", compare_params: { period: 20, num_std: 2 } }] } },
  ];

  function savedStrategies() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY) || "[]"); } catch (e) { return []; }
  }
  function persistSaved(list) { localStorage.setItem(STORE_KEY, JSON.stringify(list)); }

  function render() {
    if (state.cm) { state.lastCode = state.cm.getValue(); state.cm = null; }
    const page = document.getElementById("page-custom");
    page.innerHTML = `
      <div class="chips" id="cu-mode" style="margin-bottom:16px">
        <span class="chip active" data-mode="visual">🖱️ 可视化规则</span>
        <span class="chip" data-mode="code">🧑‍💻 代码策略（TradingView 风格）</span>
      </div>
      <div id="cu-visual">
        <div class="card" style="margin-bottom:16px">
          <div class="card-title">🧩 经典策略模板</div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
            <select class="select" id="cu-template" style="flex:1;min-width:220px">
              ${VISUAL_TEMPLATES.map((t, i) => '<option value="' + i + '">' + t.name + ' · ' + t.desc + '</option>').join("")}
            </select>
            <button class="btn btn-sm" id="cu-template-load">📥 载入模板</button>
            <button class="btn btn-sm" id="cu-visual-to-code">↔ 转为代码策略</button>
          </div>
          <div class="hint">一键载入经典交易流派策略，再增删条件微调成自己的策略；点「用此策略回测」自动同步到回测页。</div>
        </div>
        <div class="grid grid-layout-backtest">
          <div class="side-panel">
            <div class="card">
              <div class="card-title">🧠 可视化策略构建器</div>
              <div class="field"><label>策略名称</label><input class="input" id="cu-name" value="我的自定义策略" placeholder="用于保存与识别"></div>
              <div class="field"><label>交易方向</label>
                <div class="chips" id="cu-direction">
                  <span class="chip active" data-dir="long_only">只做多</span>
                  <span class="chip" data-dir="long_short">多空都做</span>
                </div>
              </div>
              <div class="divider"></div>
              <div class="card-title" style="margin-bottom:8px">🟢 开仓条件（满足时买入）</div>
              <div class="field"><label>条件逻辑</label>
                <select class="select" id="cu-entry-logic">
                  <option value="all">全部满足 (AND)</option>
                  <option value="any">任一满足 (OR)</option>
                </select>
              </div>
              <div id="cu-entry-conds"></div>
              <button class="btn btn-sm btn-block" id="cu-add-entry" style="margin-top:8px">＋ 添加开仓条件</button>
              <div class="divider"></div>
              <div class="card-title" style="margin-bottom:8px">🔴 平仓条件（可选）</div>
              <div class="field"><label>条件逻辑</label>
                <select class="select" id="cu-exit-logic">
                  <option value="any">任一满足 (OR)</option>
                  <option value="all">全部满足 (AND)</option>
                </select>
              </div>
              <div id="cu-exit-conds"></div>
              <button class="btn btn-sm btn-block" id="cu-add-exit" style="margin-top:8px">＋ 添加平仓条件</button>
            </div>
            <div class="card" style="margin-top:14px">
              <div class="card-title">💾 我的策略库（本地保存）</div>
              <div style="display:flex;gap:8px;flex-wrap:wrap">
                <select class="select" id="cu-saved" style="flex:1;min-width:150px"><option value="">（选择已保存策略）</option></select>
                <button class="btn btn-sm" id="cu-save">💾 保存</button>
                <button class="btn btn-sm" id="cu-saved-load">📂 载入</button>
                <button class="btn btn-sm btn-danger" id="cu-saved-del">🗑 删除</button>
              </div>
              <div class="hint">策略保存在浏览器本地，刷新不丢失；保存后可随时载入继续编辑。</div>
            </div>
            <button class="btn btn-primary btn-block btn-run" id="cu-run" style="margin-top:14px">🚀 用此策略回测</button>
            <div class="hint">支持指标：SMA / EMA / RSI / MACD / 布林带 / ATR / 价格 / 成交量。构建后回测页自动同步使用。</div>
          </div>
          <div>
            <div class="card">
              <div class="card-title">📋 规则 JSON（可手动编辑）</div>
              <textarea id="cu-json" spellcheck="false" style="width:100%;min-height:300px;background:rgba(0,0,0,.3);color:var(--text);border:1px solid var(--border);border-radius:10px;padding:12px;font-family:var(--mono);font-size:12px;resize:vertical;outline:none"></textarea>
              <div style="display:flex;gap:10px;margin-top:10px;flex-wrap:wrap">
                <button class="btn btn-sm" id="cu-load-json">从 JSON 加载</button>
                <button class="btn btn-sm" id="cu-copy">📄 复制 JSON</button>
                <button class="btn btn-sm" id="cu-clear">清空条件</button>
              </div>
            </div>
            <div class="card" style="margin-top:16px">
              <div class="card-title">📖 可用指标</div>
              <div class="chips" id="cu-ind-list"></div>
            </div>
          </div>
        </div>
      </div>
      <div id="cu-code" style="display:none">
        <div class="grid grid-layout-backtest">
          <div class="side-panel">
            <div class="card">
              <div class="card-title">🧑‍💻 代码策略</div>
              <div class="field"><label>策略名称</label>
                <input class="input" id="cu-code-name" value="my_code_strategy">
              </div>
              <div class="field"><label>参数 JSON（可选，代码中通过 params 读取）</label>
                <input class="input" id="cu-code-params" spellcheck="false" value='{"fast": 20, "slow": 50}'>
              </div>
              <button class="btn btn-primary btn-block btn-run" id="cu-code-run">🚀 用代码策略回测</button>
              <button class="btn btn-sm btn-block" id="cu-code-template" style="margin-top:8px">📄 载入示例模板</button>
              <button class="btn btn-sm btn-block" id="cu-code-save" style="margin-top:8px">💾 保存到我的策略库</button>
              <div class="hint">代码中必须定义 generate_signals(df, params) 函数，返回 +1/-1/0 信号序列。回测页自动同步使用。</div>
            </div>
          </div>
          <div>
            <div class="card">
              <div class="card-title">✍️ 代码编辑器（Python · TradingView 风格）</div>
              <textarea id="cu-code-editor"></textarea>
              <div class="hint" id="cu-code-doc" style="margin-top:10px"></div>
            </div>
          </div>
        </div>
      </div>
    `;
    wire();
    refreshSaved();
    loadSchema();
    loadCodeTemplate();
  }

  function wire() {
    // 模式切换
    document.getElementById("cu-mode").querySelectorAll(".chip").forEach((c) => {
      c.addEventListener("click", () => {
        document.getElementById("cu-mode").querySelectorAll(".chip").forEach((x) => x.classList.remove("active"));
        c.classList.add("active");
        state.mode = c.dataset.mode;
        document.getElementById("cu-visual").style.display = state.mode === "visual" ? "" : "none";
        document.getElementById("cu-code").style.display = state.mode === "code" ? "" : "none";
        if (state.mode === "code") initCodeEditor();
      });
    });
    // 可视化构建器
    document.getElementById("cu-direction").querySelectorAll(".chip").forEach((c) => {
      c.addEventListener("click", () => {
        document.getElementById("cu-direction").querySelectorAll(".chip").forEach((x) => x.classList.remove("active"));
        c.classList.add("active");
        state.direction = c.dataset.dir;
        updateJson();
      });
    });
    document.getElementById("cu-add-entry").addEventListener("click", () => addCond("cu-entry-conds", {}));
    document.getElementById("cu-add-exit").addEventListener("click", () => addCond("cu-exit-conds", {}));
    document.getElementById("cu-load-json").addEventListener("click", loadFromJson);
    document.getElementById("cu-copy").addEventListener("click", () => {
      navigator.clipboard.writeText(document.getElementById("cu-json").value).then(() => App.toast("JSON 已复制", "success"));
    });
    document.getElementById("cu-clear").addEventListener("click", () => {
      document.getElementById("cu-entry-conds").innerHTML = "";
      document.getElementById("cu-exit-conds").innerHTML = "";
      updateJson();
    });
    // 模板
    document.getElementById("cu-template-load").addEventListener("click", loadTemplate);
    document.getElementById("cu-visual-to-code").addEventListener("click", visualToCode);
    // 策略库
    document.getElementById("cu-save").addEventListener("click", saveStrategy);
    document.getElementById("cu-saved-load").addEventListener("click", loadSaved);
    document.getElementById("cu-saved-del").addEventListener("click", deleteSaved);
    // 运行回测
    document.getElementById("cu-run").addEventListener("click", () => {
      try {
        const rules = collectRules();
        if (!rules.entry.conditions.length) throw new Error("请至少添加一个开仓条件");
        App.state.customRules = rules;
        App.state.useCustom = true;
        App.toast("已载入自定义策略，开始回测", "success");
        App.go("backtest");
      } catch (e) {
        App.toast(e.message, "error");
      }
    });
    // 代码模式
    document.getElementById("cu-code-run").addEventListener("click", runCodeStrategy);
    document.getElementById("cu-code-save").addEventListener("click", saveCodeStrategy);
    document.getElementById("cu-code-template").addEventListener("click", () => {
      if (state.cm && state.templateCode) {
        state.cm.setValue(state.templateCode);
        App.toast("示例模板已载入", "success");
      }
    });
    ["cu-entry-logic", "cu-exit-logic"].forEach((id) => document.getElementById(id).addEventListener("change", updateJson));
    document.getElementById("cu-name").addEventListener("input", () => {});
  }

  function loadTemplate() {
    const idx = parseInt(document.getElementById("cu-template").value, 10);
    const t = VISUAL_TEMPLATES[idx];
    if (!t) return;
    state.direction = t.direction;
    document.getElementById("cu-direction").querySelectorAll(".chip").forEach((c) => c.classList.toggle("active", c.dataset.dir === state.direction));
    document.getElementById("cu-entry-logic").value = t.entry.logic || "all";
    document.getElementById("cu-exit-logic").value = (t.exit && t.exit.logic) || "any";
    document.getElementById("cu-entry-conds").innerHTML = "";
    document.getElementById("cu-exit-conds").innerHTML = "";
    (t.entry.conditions || []).forEach((c) => addCond("cu-entry-conds", c));
    if (t.exit) (t.exit.conditions || []).forEach((c) => addCond("cu-exit-conds", c));
    document.getElementById("cu-name").value = t.name;
    updateJson();
    App.toast("已载入模板：「" + t.name + "」，可继续微调", "success");
  }

  function visualToCode() {
    try {
      const rules = collectRules();
      if (!rules.entry.conditions.length) throw new Error("请先添加开仓条件");
      const code = rulesToCode(rules);
      state.mode = "code";
      document.getElementById("cu-mode").querySelectorAll(".chip").forEach((x) => x.classList.toggle("active", x.dataset.mode === "code"));
      document.getElementById("cu-visual").style.display = "none";
      document.getElementById("cu-code").style.display = "";
      const name = document.getElementById("cu-name").value.trim() || "converted_strategy";
      document.getElementById("cu-code-name").value = name.replace(/\s+/g, "_");
      initCodeEditor();
      if (state.cm) state.cm.setValue(code);
      App.toast("已转换为代码策略，可继续修改后回测", "success");
    } catch (e) {
      App.toast(e.message, "error");
    }
  }

  // 可视化规则 → Python 代码
  function indExpr(ind, p) {
    p = p || {};
    const num = (v, d) => (v !== undefined && v !== null ? v : d);
    switch (ind) {
      case "close": return 'df["close"]';
      case "open": return 'df["open"]';
      case "high": return 'df["high"]';
      case "low": return 'df["low"]';
      case "volume": return 'df["volume"]';
      case "sma": return 'sma(df["close"], ' + num(p.period, 20) + ')';
      case "ema": return 'ema(df["close"], ' + num(p.period, 20) + ')';
      case "rsi": return 'rsi(df["close"], ' + num(p.period, 14) + ')';
      case "atr": return 'atr(df, ' + num(p.period, 14) + ')';
      case "macd_dif": return 'macd(df["close"], ' + num(p.fast, 12) + ', ' + num(p.slow, 26) + ', ' + num(p.signal, 9) + ')[0]';
      case "macd_dea": return 'macd(df["close"], ' + num(p.fast, 12) + ', ' + num(p.slow, 26) + ', ' + num(p.signal, 9) + ')[1]';
      case "macd_hist": return 'macd(df["close"], ' + num(p.fast, 12) + ', ' + num(p.slow, 26) + ', ' + num(p.signal, 9) + ')[2]';
      case "boll_upper": return 'bollinger(df["close"], ' + num(p.period, 20) + ', ' + num(p.num_std, 2) + ')[1]';
      case "boll_mid": return 'bollinger(df["close"], ' + num(p.period, 20) + ', ' + num(p.num_std, 2) + ')[0]';
      case "boll_lower": return 'bollinger(df["close"], ' + num(p.period, 20) + ', ' + num(p.num_std, 2) + ')[2]';
      default: return 'df["close"]';
    }
  }
  function condExpr(cond) {
    const left = indExpr(cond.indicator, cond.params);
    const op = cond.op || ">";
    if (cond.compare === "indicator") {
      return "(" + left + " " + op + " " + indExpr(cond.compare_indicator, cond.compare_params) + ")";
    }
    return "(" + left + " " + op + " " + (cond.value !== undefined && cond.value !== null ? cond.value : 0) + ")";
  }
  function rulesToCode(rules) {
    const entry = rules.entry || {};
    const exit = rules.exit || {};
    const eLogic = entry.logic === "any" ? " | " : " & ";
    const xLogic = (exit.logic === "any" ? " | " : " & ");
    const eConds = (entry.conditions || []).map(condExpr);
    const xConds = (exit.conditions || []).map(condExpr);
    let code = '"""由可视化规则自动生成的代码策略（可自由修改）"""\n';
    code += 'def generate_signals(df, params):\n';
    code += '    # 开仓条件\n';
    code += '    entry = ' + (eConds.length ? eConds.join(eLogic) : "False") + '\n';
    if (xConds.length) {
      code += '    # 平仓条件\n';
      code += '    exit = ' + xConds.join(xLogic) + '\n';
    }
    code += '    signal = pd.Series(0.0, index=df.index)\n';
    if (rules.direction === "long_short") {
      code += '    signal[entry.fillna(False)] = 1.0\n';
      if (xConds.length) code += '    signal[exit.fillna(False)] = -1.0\n';
    } else {
      code += '    signal[entry.fillna(False)] = 1.0\n';
      if (xConds.length) code += '    signal[exit.fillna(False) & (signal == 1.0)] = 0.0\n';
    }
    code += '    return signal\n';
    return code;
  }

  // ---- 本地策略库 ----
  function refreshSaved() {
    const sel = document.getElementById("cu-saved");
    if (!sel) return;
    const list = savedStrategies();
    sel.innerHTML = '<option value="">（选择已保存策略）</option>' + list.map((s, i) => '<option value="' + i + '">' + s.name + '（' + (s.mode === "code" ? "代码" : "可视化") + '）</option>').join("");
  }
  function saveStrategy() {
    try {
      const rules = collectRules();
      if (!rules.entry.conditions.length) throw new Error("请至少添加一个开仓条件");
      const name = document.getElementById("cu-name").value.trim() || "我的自定义策略";
      const list = savedStrategies();
      list.push({ name, mode: "visual", rules, direction: state.direction, savedAt: new Date().toISOString() });
      persistSaved(list);
      refreshSaved();
      App.toast("策略已保存到本地策略库", "success");
    } catch (e) {
      App.toast(e.message, "error");
    }
  }
  function saveCodeStrategy() {
    if (!state.cm) { App.toast("代码编辑器未初始化", "error"); return; }
    const code = state.cm.getValue();
    if (!code.includes("generate_signals")) { App.toast("代码中未找到 generate_signals 函数", "error"); return; }
    let params = {};
    try { params = JSON.parse(document.getElementById("cu-code-params").value || "{}"); } catch (e) { App.toast("参数 JSON 解析失败: " + e.message, "error"); return; }
    const name = document.getElementById("cu-code-name").value.trim() || "my_code_strategy";
    const list = savedStrategies();
    list.push({ name, mode: "code", code, params, savedAt: new Date().toISOString() });
    persistSaved(list);
    refreshSaved();
    App.toast("代码策略已保存到本地策略库", "success");
  }
  function loadSaved() {
    const idx = parseInt(document.getElementById("cu-saved").value, 10);
    const list = savedStrategies();
    if (isNaN(idx) || !list[idx]) { App.toast("请先选择要载入的策略", "error"); return; }
    const s = list[idx];
    if (s.mode === "code") {
      state.mode = "code";
      document.getElementById("cu-mode").querySelectorAll(".chip").forEach((x) => x.classList.toggle("active", x.dataset.mode === "code"));
      document.getElementById("cu-visual").style.display = "none";
      document.getElementById("cu-code").style.display = "";
      document.getElementById("cu-code-name").value = s.name;
      document.getElementById("cu-code-params").value = JSON.stringify(s.params || {});
      initCodeEditor();
      if (state.cm) state.cm.setValue(s.code || "");
      App.toast("已载入代码策略：" + s.name, "success");
    } else {
      loadRules(s.rules);
      document.getElementById("cu-name").value = s.name;
      App.toast("已载入可视化策略：" + s.name, "success");
    }
  }
  function deleteSaved() {
    const idx = parseInt(document.getElementById("cu-saved").value, 10);
    const list = savedStrategies();
    if (isNaN(idx) || !list[idx]) { App.toast("请先选择要删除的策略", "error"); return; }
    list.splice(idx, 1);
    persistSaved(list);
    refreshSaved();
    App.toast("已删除", "success");
  }

  function loadRules(rules) {
    state.direction = rules.direction || "long_only";
    document.getElementById("cu-direction").querySelectorAll(".chip").forEach((c) => c.classList.toggle("active", c.dataset.dir === state.direction));
    document.getElementById("cu-entry-logic").value = rules.entry.logic || "all";
    document.getElementById("cu-exit-logic").value = (rules.exit && rules.exit.logic) || "any";
    document.getElementById("cu-entry-conds").innerHTML = "";
    document.getElementById("cu-exit-conds").innerHTML = "";
    (rules.entry.conditions || []).forEach((c) => addCond("cu-entry-conds", c));
    if (rules.exit) (rules.exit.conditions || []).forEach((c) => addCond("cu-exit-conds", c));
    updateJson();
  }

  async function loadSchema() {
    try {
      const schema = await API.get("/api/strategies/custom-schema");
      state.schema = schema;
      const indList = document.getElementById("cu-ind-list");
      if (indList) indList.innerHTML = schema.indicators.map((i) => '<span class="chip" title="' + i.name + '">' + i.label + '</span>').join("");
      if (!document.querySelector("#cu-entry-conds .cond-row")) {
        if (App.state.customRules && App.state.customRules.entry) {
          loadRules(App.state.customRules);
        } else {
          addCond("cu-entry-conds", { indicator: "sma", params: { period: 20 }, op: ">", compare: "indicator", compare_indicator: "sma", compare_params: { period: 50 } });
        }
      }
      if (!document.querySelector("#cu-exit-conds .cond-row")) {
        addCond("cu-exit-conds", { indicator: "rsi", params: { period: 14 }, op: ">", compare: "number", value: 70 });
      }
      updateJson();
    } catch (e) {
      App.toast("指标列表加载失败: " + e.message, "error");
    }
  }

  async function loadCodeTemplate() {
    try {
      const tpl = await API.get("/api/strategies/code-template");
      state.templateCode = tpl.code;
      const doc = document.getElementById("cu-code-doc");
      if (doc) doc.innerHTML = tpl.doc.split("\n").join("<br>").replace(/`/g, "");
      const ta = document.getElementById("cu-code-editor");
      if (ta && !state.cm) {
        ta.value = App.state.customCode && App.state.customCode.code ? App.state.customCode.code : (state.lastCode || tpl.code);
        initCodeEditor();
      }
    } catch (e) { /* 忽略 */ }
  }

  function initCodeEditor() {
    const ta = document.getElementById("cu-code-editor");
    if (!ta || state.cm || !window.CodeMirror) return;
    state.cm = CodeMirror.fromTextArea(ta, {
      mode: "python",
      lineNumbers: true,
      matchBrackets: true,
      indentUnit: 4,
      styleActiveLine: true,
      viewportMargin: Infinity,
    });
    state.cm.setSize("100%", 380);
  }

  function runCodeStrategy() {
    if (!state.cm) { App.toast("代码编辑器未初始化", "error"); return; }
    const code = state.cm.getValue();
    if (!code.includes("generate_signals")) { App.toast("代码中未找到 generate_signals 函数", "error"); return; }
    let params = {};
    try {
      params = JSON.parse(document.getElementById("cu-code-params").value || "{}");
    } catch (e) {
      App.toast("参数 JSON 解析失败: " + e.message, "error");
      return;
    }
    const name = document.getElementById("cu-code-name").value.trim() || "my_code_strategy";
    App.state.customCode = { code, params, name };
    App.state.useCode = true;
    App.toast("代码策略已载入，开始回测", "success");
    App.go("backtest");
  }

  function indOptions(selected) {
    if (!state.schema) return "";
    return state.schema.indicators.map((i) => '<option value="' + i.name + '" ' + (i.name === selected ? "selected" : "") + '>' + i.label + '</option>').join("");
  }

  function paramInputs(indicator, values) {
    const spec = PARAM_SPEC[indicator] || [];
    return spec.map((p) => {
      const v = values && values[p.k] !== undefined ? values[p.k] : p.def;
      const step = p.step ? 'step="' + p.step + '"' : "";
      return '<div style="display:flex;align-items:center;gap:4px"><span style="font-size:10px;color:var(--text-faint)">' + p.label + '</span><input class="input c-param" data-k="' + p.k + '" type="number" ' + step + ' value="' + v + '" style="width:58px;padding:5px 8px;font-size:12px"></div>';
    }).join("");
  }

  function condRowHTML(cond, uid) {
    cond = cond || {};
    const cmpMode = cond.compare === "indicator" ? "indicator" : "number";
    return `
      <div class="cond-row" data-uid="${uid}" style="display:flex;flex-direction:column;gap:6px;background:rgba(255,255,255,.03);border:1px solid var(--border);border-radius:10px;padding:10px;margin-bottom:8px">
        <div style="display:flex;gap:6px;align-items:center">
          <select class="select c-ind" style="flex:1;padding:6px 10px;font-size:12px">${indOptions(cond.indicator)}</select>
          <div style="display:flex;gap:6px" class="c-params">${paramInputs(cond.indicator, cond.params)}</div>
          <button class="btn btn-sm btn-danger c-del" style="padding:4px 9px">×</button>
        </div>
        <div style="display:flex;gap:6px;align-items:center">
          <select class="select c-op" style="width:70px;padding:6px 8px;font-size:12px">${(state.schema ? state.schema.ops : [">", ">=", "<", "<=", "==", "!="]).map((o) => '<option ' + (o === cond.op ? "selected" : "") + '>' + o + '</option>').join("")}</select>
          <select class="select c-cmp-mode" style="width:76px;padding:6px 8px;font-size:12px">
            <option value="number" ${cmpMode === "number" ? "selected" : ""}>数值</option>
            <option value="indicator" ${cmpMode === "indicator" ? "selected" : ""}>指标</option>
          </select>
          <input class="input c-val" type="number" value="${cond.value ?? 70}" style="width:90px;padding:6px 8px;font-size:12px;display:${cmpMode === "number" ? "" : "none"}">
          <select class="select c-cmp-ind" style="flex:1;padding:6px 10px;font-size:12px;display:${cmpMode === "indicator" ? "" : "none"}">${indOptions(cond.compare_indicator)}</select>
          <div style="display:flex;gap:6px" class="c-cmp-params">${cmpMode === "indicator" ? paramInputs(cond.compare_indicator, cond.compare_params) : ""}</div>
        </div>
      </div>`;
  }

  function addCond(containerId, cond) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const id = ++uid;
    container.insertAdjacentHTML("beforeend", condRowHTML(cond, id));
    wireRow(container.querySelector('[data-uid="' + id + '"]'));
  }

  function wireRow(row) {
    row.querySelector(".c-del").addEventListener("click", () => { row.remove(); updateJson(); });
    row.querySelector(".c-ind").addEventListener("change", () => { row.querySelector(".c-params").innerHTML = paramInputs(row.querySelector(".c-ind").value, {}); updateJson(); });
    row.querySelector(".c-cmp-mode").addEventListener("change", () => {
      const mode = row.querySelector(".c-cmp-mode").value;
      row.querySelector(".c-val").style.display = mode === "number" ? "" : "none";
      row.querySelector(".c-cmp-ind").style.display = mode === "indicator" ? "" : "none";
      row.querySelector(".c-cmp-params").innerHTML = mode === "indicator" ? paramInputs(row.querySelector(".c-cmp-ind").value, {}) : "";
      updateJson();
    });
    row.querySelector(".c-cmp-ind").addEventListener("change", () => { row.querySelector(".c-cmp-params").innerHTML = paramInputs(row.querySelector(".c-cmp-ind").value, {}); updateJson(); });
    row.querySelectorAll(".c-param").forEach((p) => p.addEventListener("input", updateJson));
    row.querySelectorAll(".c-val, .c-op").forEach((el) => el.addEventListener("change", updateJson));
  }

  function readConds(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return [];
    return [...container.querySelectorAll(".cond-row")].map((row) => {
      const cond = { indicator: row.querySelector(".c-ind").value, op: row.querySelector(".c-op").value };
      const mode = row.querySelector(".c-cmp-mode").value;
      cond.params = readParams(row.querySelector(".c-params"));
      if (mode === "number") {
        cond.compare = "number";
        cond.value = parseFloat(row.querySelector(".c-val").value) || 0;
      } else {
        cond.compare = "indicator";
        cond.compare_indicator = row.querySelector(".c-cmp-ind").value;
        cond.compare_params = readParams(row.querySelector(".c-cmp-params"));
      }
      return cond;
    });
  }

  function readParams(box) {
    const out = {};
    box.querySelectorAll(".c-param").forEach((el) => { out[el.dataset.k] = parseFloat(el.value) || 0; });
    return Object.keys(out).length ? out : {};
  }

  function collectRules() {
    const entryConds = readConds("cu-entry-conds");
    const exitConds = readConds("cu-exit-conds");
    const rules = { entry: { logic: document.getElementById("cu-entry-logic").value, conditions: entryConds }, direction: state.direction };
    if (exitConds.length) rules.exit = { logic: document.getElementById("cu-exit-logic").value, conditions: exitConds };
    return rules;
  }

  function updateJson() {
    const box = document.getElementById("cu-json");
    if (!box) return;
    box.value = JSON.stringify(collectRules(), null, 2);
  }

  function loadFromJson() {
    try {
      const rules = JSON.parse(document.getElementById("cu-json").value);
      if (!rules.entry || !rules.entry.conditions) throw new Error("缺少 entry 规则");
      loadRules(rules);
      App.toast("JSON 加载成功", "success");
    } catch (e) {
      App.toast("JSON 解析失败: " + e.message, "error");
    }
  }

  return { render, refresh() { if (document.getElementById("cu-json")) updateJson(); } };
})());
