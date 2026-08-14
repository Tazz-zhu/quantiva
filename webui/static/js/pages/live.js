/* ============ 实盘 / 模拟盘 ============ */
App.register("live", (() => {
  const state = { running: false, status: null };

  function render() {
    const page = document.getElementById("page-live");
    page.innerHTML = `
      <div class="grid grid-layout-backtest">
        <div class="side-panel">
          <div class="card">
            <div class="card-title">⚙️ 交易控制</div>
            <div class="field"><label>模式</label>
              <select class="select" id="lv-mode">
                <option value="paper">模拟盘（安全）</option>
                <option value="live">实盘（需要 API 密钥）</option>
              </select>
            </div>
            <div class="field"><label>数据源</label>
              <select class="select" id="lv-source">
                <option value="exchange" selected>交易所实时行情</option>
              </select>
            </div>
            <div class="input-row">
              <div class="field"><label>标的</label><input class="input" id="lv-symbol" value="BTC/USDT"></div>
              <div class="field"><label>周期</label>
                <select class="select" id="lv-timeframe">
                  <option>1m</option><option>5m</option><option>15m</option><option>1h</option><option>4h</option><option>1d</option>
                </select>
              </div>
            </div>
            <div class="input-row">
              <div class="field"><label>轮询间隔（秒）</label><input class="input" id="lv-poll" type="number" value="5"></div>
              <div class="field"><label>初始资金</label><input class="input" id="lv-balance" type="number" value="10000"></div>
            </div>
            <div class="divider"></div>
            <div class="field"><label>策略</label>
              <select class="select" id="lv-strategy">
                <option value="ma_cross">双均线交叉</option>
                <option value="rsi_reversion">RSI 均值回归</option>
                <option value="bollinger">布林带回归</option>
                <option value="turtle">海龟交易法则</option>
                <option value="macd_cross">MACD 金叉死叉</option>
                <option value="momentum">动量突破</option>
              </select>
            </div>
            <div class="input-row-3">
              <div class="field"><label>快线</label><input class="input" id="lv-fast" type="number" value="5"></div>
              <div class="field"><label>慢线</label><input class="input" id="lv-slow" type="number" value="20"></div>
              <div class="field"><label>仓位%</label><input class="input" id="lv-pos" type="number" step="0.05" value="0.5"></div>
            </div>
            <div class="input-row">
              <div class="field"><label>杠杆</label><input class="input" id="lv-leverage" type="number" step="0.5" value="1"></div>
              <div class="field"><label>ATR 止损倍数</label><input class="input" id="lv-atr" type="number" step="0.5" value="2"></div>
            </div>
            <div class="input-row-3">
              <div class="field"><label>固定止损% (空=用ATR)</label><input class="input" id="lv-sloss" type="number" step="0.005" placeholder="如 0.02"></div>
              <div class="field"><label>固定止盈%</label><input class="input" id="lv-tp" type="number" step="0.005" placeholder="如 0.04"></div>
              <div class="field"><label>日亏损熔断%</label><input class="input" id="lv-dailyloss" type="number" step="0.005" placeholder="如 0.02"></div>
            </div>
            <div class="run-btn-row">
              <button class="btn btn-success btn-block btn-run" id="lv-start">▶ 启动交易循环</button>
              <button class="btn btn-danger btn-block btn-run" id="lv-stop" style="display:none">⏹ 停止交易循环</button>
              <button class="btn btn-danger btn-block btn-run" id="lv-flatten" style="display:none">一键平仓（市价）</button>
            </div>
            <div class="hint">模拟盘完全本地记账，不涉及真实资金。实盘模式需要设置 CCXT_API_KEY / CCXT_API_SECRET 环境变量。</div>
          </div>
        </div>
        <div>
          <div class="grid grid-4" id="lv-stats">
            ${lvStat("运行状态", "lv-status", "--")}
            ${lvStat("账户权益", "lv-equity", "--")}
            ${lvStat("最新价格", "lv-price", "--")}
            ${lvStat("当前信号", "lv-signal", "--")}
          </div>
          <div id="lv-breaker" style="display:none;margin-top:12px"></div>
          <div id="lv-session" style="display:none;margin-top:12px"></div>
          <div class="card" style="margin-top:12px">
            <div class="card-title">执行质量（本次循环）</div>
            <div class="grid grid-4" id="lv-exec">
              <div class="card stat-card"><div class="stat-label">成交率</div><div class="stat-value sm" id="lv-exec-rate">--</div></div>
              <div class="card stat-card"><div class="stat-label">平均滑点</div><div class="stat-value sm" id="lv-exec-slip">--</div></div>
              <div class="card stat-card"><div class="stat-label">平均延迟</div><div class="stat-value sm" id="lv-exec-lat">--</div></div>
              <div class="card stat-card"><div class="stat-label">拒单数</div><div class="stat-value sm" id="lv-exec-rej">--</div></div>
            </div>
          </div>
          <div class="grid grid-2" style="margin-top:16px">
            <div class="card">
              <div class="card-title">📦 持仓</div>
              <div class="table-wrap" style="max-height:240px">
                <table class="table"><thead><tr><th>标的</th><th class="num">数量</th><th class="num">入场价</th><th class="num">现价</th><th class="num">浮动盈亏</th></tr></thead><tbody id="lv-positions"></tbody></table>
              </div>
            </div>
            <div class="card">
              <div class="card-title">🧾 成交记录</div>
              <div class="table-wrap" style="max-height:240px">
                <table class="table"><thead><tr><th>方向</th><th class="num">数量</th><th class="num">成交价</th><th>状态</th></tr></thead><tbody id="lv-orders"></tbody></table>
              </div>
            </div>
          </div>
          <div class="card" style="margin-top:16px">
            <div class="card-title">📜 事件日志</div>
            <div class="log-list" id="lv-events"><div class="empty" style="padding:20px">暂无事件</div></div>
          </div>
        </div>
      </div>
    `;
    document.getElementById("lv-start").addEventListener("click", start);
    document.getElementById("lv-stop").addEventListener("click", stop);
    document.getElementById("lv-flatten").addEventListener("click", flatten);
    refresh();
    loadSession();
  }

  function lvStat(label, id, value) {
    return '<div class="card stat-card hover"><div class="stat-label">' + label + '</div><div class="stat-value sm" id="' + id + '">' + value + '</div></div>';
  }

  async function start() {
    const mode = document.getElementById("lv-mode").value;
    if (mode === "live") {
      const ok = await App.confirmDialog({
        title: "[风险提示] 即将启动实盘交易（真实资金）",
        danger: true,
        confirmText: "我已了解风险，启动实盘",
        requireText: "CONFIRM",
        message: '<div style="line-height:1.9">实盘模式将通过交易所 API <b>真实下单</b>，请确认：<br>1. 已设置 <b>CCXT_API_KEY / CCXT_API_SECRET</b> 环境变量；<br>2. 已理解市场风险、滑点与手续费；<br>3. 已核对交易对与参数，仓位/止损设置合理。<br><br>请输入 <b>CONFIRM</b> 完成确认。</div>',
      });
      if (!ok) { App.toast("已取消实盘启动", "info"); return; }
    }
    const payload = {
      mode,
      data_source: document.getElementById("lv-source").value,
      symbol: document.getElementById("lv-symbol").value.trim(),
      timeframe: document.getElementById("lv-timeframe").value,
      poll_interval_sec: parseFloat(document.getElementById("lv-poll").value) || 5,
      paper_initial_balance: parseFloat(document.getElementById("lv-balance").value) || 10000,
      strategy: { name: document.getElementById("lv-strategy").value, params: {} },
      risk: {
        max_position_pct: parseFloat(document.getElementById("lv-pos").value) || 0.5,
        leverage: parseFloat(document.getElementById("lv-leverage").value) || 1,
        atr_stop_mult: parseFloat(document.getElementById("lv-atr").value) || 2,
        stop_loss_pct: parseFloat(document.getElementById("lv-sloss").value) || null,
        take_profit_pct: parseFloat(document.getElementById("lv-tp").value) || null,
        max_daily_loss_pct: parseFloat(document.getElementById("lv-dailyloss").value) || null,
        trade_direction: "long_only",
      },
      confirm_live: mode === "live",
    };
    const strat = payload.strategy.name;
    if (strat === "ma_cross") payload.strategy.params = { fast: parseInt(document.getElementById("lv-fast").value) || 5, slow: parseInt(document.getElementById("lv-slow").value) || 20, direction: "long_only" };
    else if (strat === "rsi_reversion") payload.strategy.params = { period: 14, oversold: 30, overbought: 70 };
    else if (strat === "bollinger") payload.strategy.params = { period: 20, num_std: 2.0 };
    else if (strat === "turtle") payload.strategy.params = { entry_period: 20, exit_period: 10, direction: "long_only" };
    else if (strat === "macd_cross") payload.strategy.params = { fast: 12, slow: 26, signal: 9, direction: "long_only" };
    else payload.strategy.params = { lookback: 50, exit_ma: 20 };
    try {
      await API.post("/api/live/start", payload);
      App.toast("交易循环已启动 ✅", "success");
      refresh();
    } catch (e) {
      App.toast("启动失败: " + e.message, "error", 5000);
    }
  }

  async function flatten() {
    const ok = await App.confirmDialog({
      title: "一键平仓（市价）",
      danger: true,
      confirmText: "确认平仓",
      message: "将以最新市价立即平掉当前持仓。此操作不可撤销，是否继续？",
    });
    if (!ok) return;
    try {
      await API.post("/api/live/flatten", {});
      App.toast("平仓成功", "success");
      refresh();
    } catch (e) {
      App.toast("平仓失败: " + e.message, "error", 5000);
    }
  }

  async function stop() {
    try {
      await API.post("/api/live/stop");
      App.toast("交易循环已停止", "info");
      refresh();
    } catch (e) {
      App.toast("停止失败: " + e.message, "error");
    }
  }

  function renderStatus(d) {
    if (!d) return;
    const startBtn = document.getElementById("lv-start");
    const stopBtn = document.getElementById("lv-stop");
    const flatBtn = document.getElementById("lv-flatten");
    if (startBtn) { startBtn.style.display = d.running ? "none" : ""; startBtn.disabled = false; }
    if (stopBtn) stopBtn.style.display = d.running ? "" : "none";
    if (flatBtn) flatBtn.style.display = d.running && d.positions && d.positions.length ? "" : "none";
    setText("lv-status", d.running ? "🟢 运行中" : "⚪ 已停止");
    const eq = document.getElementById("lv-equity");
    if (d.equity !== null && d.equity !== undefined) {
      const pnl = d.equity - (d.start_equity || 0);
      eq.textContent = FMT.usd(d.equity);
      eq.className = "stat-value sm " + FMT.cls(pnl);
    }
    setText("lv-price", FMT.price(d.last_price));
    const sg = document.getElementById("lv-signal");
    if (d.running) {
      sg.textContent = d.signal > 0 ? "做多 ▲" : d.signal < 0 ? "做空 ▼" : "观望";
      sg.className = "stat-value sm " + (d.signal > 0 ? "pos" : d.signal < 0 ? "neg" : "");
    }
    const posBody = document.getElementById("lv-positions");
    if (posBody) {
      posBody.innerHTML = d.positions.length ? d.positions.map((p) => {
        const qty = Number(p.amount || 0);
        const entry = d.entry_price;
        const cur = d.last_price;
        let pnl = null;
        if (entry && cur && qty) pnl = d.entry_side === "long" ? (cur - entry) * qty : (entry - cur) * qty;
        return '<tr><td>' + p.symbol + '</td><td class="num ' + (qty > 0 ? "pos" : "neg") + '">' + qty.toFixed(6) + '</td><td class="num">' + (entry ? FMT.price(entry) : "--") + '</td><td class="num">' + (cur ? FMT.price(cur) : "--") + '</td><td class="num ' + FMT.cls(pnl) + '">' + (pnl === null ? "--" : FMT.usd(pnl)) + '</td></tr>';
      }).join("") : '<tr><td colspan="5" style="text-align:center;color:var(--text-faint)">无持仓</td></tr>';
    }
    const ordBody = document.getElementById("lv-orders");
    if (ordBody) {
      ordBody.innerHTML = d.orders.length ? d.orders.slice().reverse().map((o) => '<tr><td><span class="badge ' + (o.side === "buy" ? "badge-green" : "badge-red") + '">' + (o.side === "buy" ? "买入" : "卖出") + '</span></td><td class="num">' + Number(o.amount).toFixed(6) + '</td><td class="num">' + FMT.price(o.price) + '</td><td><span class="badge badge-gray">' + o.status + '</span></td></tr>').join("") : '<tr><td colspan="4" style="text-align:center;color:var(--text-faint)">暂无成交</td></tr>';
    }
    const evBody = document.getElementById("lv-events");
    if (evBody) {
      evBody.innerHTML = d.events.length ? d.events.map((e) => '<div class="log-item ' + e.level + '"><span class="log-time">' + FMT.time(e.ts) + '</span><span class="log-msg">' + e.message + '</span></div>').join("") : '<div class="empty" style="padding:20px">暂无事件</div>';
    }
    const br = document.getElementById("lv-breaker");
    if (br) {
      if (d.drawdown_breaker_active) {
        br.innerHTML = '<div class="alert alert-danger">[回撤熔断] 组合权益从峰值回撤超阈值 ' + FMT.pct(d.max_drawdown_pct) + '，已暂停开仓（停止并重新启动后复位）</div>';
        br.style.display = "";
      } else if (d.circuit_breaker_active) {
        br.innerHTML = '<div class="alert alert-danger">[熔断] 日亏损熔断中：今日盈亏 ' + FMT.usd(d.daily_pnl) + '，已暂停开仓（UTC 次日 0 点自动复位）</div>';
        br.style.display = "";
      } else if (d.daily_loss_limit && d.running) {
        br.innerHTML = '<div class="alert alert-info">今日盈亏 ' + FMT.usd(d.daily_pnl) + ' / 熔断阈值 ' + FMT.pct(d.daily_loss_limit) + '（' + FMT.usd((d.start_equity || 0) * d.daily_loss_limit) + '）</div>';
        br.style.display = "";
      } else {
        br.style.display = "none";
      }
    }
    const sessBox = document.getElementById("lv-session");
    if (sessBox) sessBox.style.display = d.running ? "none" : "";
    const eqx = d.exec_quality || {};
    const setExec = (id, txt) => { const el = document.getElementById(id); if (el) el.textContent = txt; };
    setExec("lv-exec-rate", eqx.fill_rate === null || eqx.fill_rate === undefined ? "--" : FMT.pct(eqx.fill_rate));
    setExec("lv-exec-slip", eqx.avg_slippage_bps ? FMT.num(eqx.avg_slippage_bps, 2) + " bps" : eqx.avg_slippage_bps === 0 && eqx.fills ? "0 bps" : "--");
    setExec("lv-exec-lat", eqx.avg_latency_ms ? FMT.num(eqx.avg_latency_ms, 1) + " ms" : eqx.avg_latency_ms === 0 && eqx.fills ? "0 ms" : "--");
    setExec("lv-exec-rej", eqx.rejects === undefined ? "--" : eqx.rejects);
  }

  async function refresh() {
    try {
      const d = await API.get("/api/live/status");
      state.status = d;
      state.running = d.running;
      renderStatus(d);
    } catch (e) {
      setText("lv-status", "[!] 状态获取失败");
      const evBody = document.getElementById("lv-events");
      if (evBody) evBody.innerHTML = '<div class="empty" style="padding:20px;color:var(--red)">无法连接服务：' + e.message + '</div>';
    }
  }

  function onStream(d) {
    if (!d || typeof d !== "object") return;
    state.status = d;
    state.running = d.running;
    renderStatus(d);
  }

  // ---------- 会话持久化 / 一键恢复 ----------
  async function loadSession() {
    const box = document.getElementById("lv-session");
    if (!box) return;
    try {
      const res = await API.get("/api/live/session");
      const s = res.session;
      if (!s) { box.style.display = "none"; box.innerHTML = ""; return; }
      const modeLabel = s.mode === "live" ? "实盘" : "模拟盘";
      box.innerHTML = '<div class="alert alert-info">上次交易会话（' + modeLabel + '）：<b>' + (s.strategy && s.strategy.name) + '</b> · ' + s.symbol + ' @ ' + s.timeframe + ' · ' + (s.saved_at ? FMT.time(s.saved_at) : "--")
        + '<div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap"><button class="btn btn-primary btn-sm" id="lv-recover">↻ 一键恢复</button><button class="btn btn-sm" id="lv-session-clear">清除会话</button></div></div>';
      box.style.display = "";
      document.getElementById("lv-recover").addEventListener("click", recoverSession);
      document.getElementById("lv-session-clear").addEventListener("click", clearSession);
    } catch (e) {
      box.style.display = "none";
    }
  }

  async function recoverSession() {
    try {
      const res = await API.get("/api/live/session");
      const s = res.session;
      if (s && s.mode === "live") {
        const ok = await App.confirmDialog({
          title: "[风险提示] 恢复实盘交易会话",
          danger: true,
          confirmText: "我已了解风险，恢复实盘",
          requireText: "CONFIRM",
          message: '将恢复上次实盘会话并通过交易所 API <b>真实下单</b>。请输入 <b>CONFIRM</b> 确认。',
        });
        if (!ok) { App.toast("已取消恢复", "info"); return; }
      }
      const rr = await API.post("/api/live/recover", { confirm_live: true });
      App.toast("会话已恢复", "success");
      refresh();
      loadSession();
    } catch (e) {
      App.toast("恢复失败: " + e.message, "error", 5000);
    }
  }

  async function clearSession() {
    try {
      await API.del("/api/live/session");
      App.toast("已清除上次会话", "info");
      loadSession();
    } catch (e) {
      App.toast("清除失败: " + e.message, "error");
    }
  }

  function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  return { render, refresh, onStream };
})());
