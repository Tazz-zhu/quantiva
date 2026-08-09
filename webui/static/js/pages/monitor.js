/* ============ 市场监控（涨跌 / 成交量异动 / 动态榜单） ============ */
App.register("monitor", (() => {
  const state = { evFilter: "all", evOffset: 0 };
  const EVENT_BADGES = {
    volume_surge: ["badge-amber", "🔥 放量"], price_surge_1h: ["badge-green", "📈 1h急涨"],
    price_drop_1h: ["badge-red", "📉 1h急跌"], price_surge_24h: ["badge-green", "🚀 24h大涨"],
    price_drop_24h: ["badge-red", "💥 24h大跌"], vol_spike: ["badge-purple", "🌊 波动率突增"],
  };

  function render() {
    const page = document.getElementById("page-monitor");
    page.innerHTML = `
      <div class="grid grid-4" id="mo-stats">
        ${moStat("监控状态", "mo-status", "--")}
        ${moStat("监控标的", "mo-symbols", "--")}
        ${moStat("扫描次数", "mo-scans", "--")}
        ${moStat("上次扫描", "mo-last", "--")}
      </div>
      <div class="grid grid-2" style="margin-top:16px">
        <div class="card">
          <div class="card-title">📡 监控配置</div>
          <div class="input-row-3">
            <div class="field"><label>扫描间隔（秒）</label><input class="input" id="mo-interval" type="number" value="30"></div>
            <div class="field"><label>放量倍数阈值</label><input class="input" id="mo-vol" type="number" step="0.5" value="3"></div>
            <div class="field"><label>1h 涨跌阈值%</label><input class="input" id="mo-p1h" type="number" step="0.5" value="2.5"></div>
          </div>
          <div class="input-row">
            <div class="field"><label>24h 涨跌阈值%</label><input class="input" id="mo-p24" type="number" step="0.5" value="8"></div>
            <div class="field"><label>告警冷却（分钟）</label><input class="input" id="mo-cooldown" type="number" value="15"></div>
          </div>
          <div style="display:flex;gap:10px">
            <button class="btn btn-primary btn-sm" id="mo-save">💾 保存配置</button>
            <button class="btn btn-success btn-sm" id="mo-start">▶ 启动监控</button>
            <button class="btn btn-danger btn-sm" id="mo-stop">⏹ 停止监控</button>
            <button class="btn btn-sm" id="mo-refresh">⟳ 刷新</button>
          </div>
          <div class="hint" id="mo-error"></div>
        </div>
        <div class="card">
          <div class="card-title">🚨 异动事件流 <span style="margin-left:auto;display:flex;gap:6px"><button class="btn btn-sm" id="mo-ev-csv">导出 CSV</button><button class="btn btn-sm" id="mo-ev-more">加载更多</button></span></div>
          <div class="chips" id="mo-ev-filter" style="margin-bottom:8px">
            <span class="chip active" data-type="all">全部</span>
            <span class="chip" data-type="volume_surge">🔥 放量</span>
            <span class="chip" data-type="price_surge_1h">📈 1h急涨</span>
            <span class="chip" data-type="price_drop_1h">📉 1h急跌</span>
            <span class="chip" data-type="price_surge_24h">🚀 24h大涨</span>
            <span class="chip" data-type="price_drop_24h">💥 24h大跌</span>
          </div>
          <div class="log-list" id="mo-events"><div class="empty" style="padding:20px">暂无异动事件</div></div>
        </div>
      </div>
      <div class="section-title">🏆 动态榜单（实时 TOP10）</div>
      <div class="grid grid-3" id="mo-rankings" style="margin-bottom:16px">
        ${rankingCard("🔥 成交量 TOP10", "mo-rank-vol")}
        ${rankingCard("🚀 24h 涨幅 TOP10", "mo-rank-gain")}
        ${rankingCard("💥 24h 跌幅 TOP10", "mo-rank-drop")}
      </div>
      <div class="section-title">📊 市场行情快照</div>
      <div class="card" style="padding:0">
        <div class="table-wrap" style="max-height:420px">
          <table class="table">
            <thead><tr><th>币种</th><th class="num">价格</th><th class="num">1h涨跌</th><th class="num">24h涨跌</th><th class="num">成交量</th><th class="num">量比</th><th>更新时间</th></tr></thead>
            <tbody id="mo-markets"></tbody>
          </table>
        </div>
      </div>
    `;
    document.getElementById("mo-save").addEventListener("click", saveConfig);
    document.getElementById("mo-start").addEventListener("click", () => post("/api/monitor/start"));
    document.getElementById("mo-stop").addEventListener("click", () => post("/api/monitor/stop"));
    document.getElementById("mo-refresh").addEventListener("click", refresh);
    document.getElementById("mo-ev-more").addEventListener("click", () => { state.evOffset += 50; loadEvents(true); });
    document.getElementById("mo-ev-csv").addEventListener("click", () => window.open("/api/monitor/events.csv", "_blank"));
    document.getElementById("mo-ev-filter").querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
      document.getElementById("mo-ev-filter").querySelectorAll(".chip").forEach((x) => x.classList.remove("active"));
      c.classList.add("active");
      state.evFilter = c.dataset.type;
      state.evOffset = 0;
      loadEvents(false);
    }));
    refresh();
    App.state.monitorUnread = 0;
    if (window.updateMonitorBadge) window.updateMonitorBadge();
  }

  function moStat(label, id, value) {
    return '<div class="card stat-card hover"><div class="stat-label">' + label + '</div><div class="stat-value sm" id="' + id + '">' + value + '</div></div>';
  }

  function rankingCard(title, id) {
    return '<div class="card"><div class="card-title">' + title + '</div><div id="' + id + '"><div class="loading" style="padding:20px"><div class="spinner"></div></div></div></div>';
  }

  function renderRankingList(rows, mode) {
    if (!rows || !rows.length) return '<div class="empty" style="padding:14px">暂无数据</div>';
    return rows.map((r, i) => {
      const medal = ["🥇", "🥈", "🥉"][i] || String(i + 1);
      let right = mode === "vol" ? '<span class="pos">' + FMT.num(r.volume_24h, 0) + '</span>' : '<span class="' + FMT.cls(r.change_24h) + '">' + FMT.pctSigned(r.change_24h) + '</span>';
      return '<div style="display:flex;align-items:center;gap:8px;padding:6px 2px;border-bottom:1px solid rgba(255,255,255,.05);font-size:12.5px"><span style="width:26px;text-align:center">' + medal + '</span><span style="flex:1;font-family:var(--mono);font-weight:600">' + r.symbol.replace("/USDT", "") + '</span><span style="font-family:var(--mono);font-size:11.5px;color:var(--text-dim)">' + FMT.price(r.price) + '</span>' + right + '</div>';
    }).join("");
  }

  async function post(path) {
    try {
      await API.post(path, {});
      App.toast("操作成功", "success");
      refresh();
    } catch (e) {
      App.toast("操作失败: " + e.message, "error");
    }
  }

  async function saveConfig() {
    const patch = {
      interval_sec: parseFloat(document.getElementById("mo-interval").value) || 30,
      thresholds: {
        volume_ratio: parseFloat(document.getElementById("mo-vol").value) || 3,
        price_1h: (parseFloat(document.getElementById("mo-p1h").value) || 2.5) / 100,
        price_24h: (parseFloat(document.getElementById("mo-p24").value) || 8) / 100,
        alert_cooldown_min: parseFloat(document.getElementById("mo-cooldown").value) || 15,
      },
    };
    try {
      await API.post("/api/monitor/config", patch);
      App.toast("监控配置已保存", "success");
      refresh();
    } catch (e) {
      App.toast("保存失败: " + e.message, "error");
    }
  }

    function setTextIf(id, v) {
    const el = document.getElementById(id);
    if (el && el.textContent !== String(v)) el.textContent = String(v);
  }
  function setInputIf(id, v) {
    const el = document.getElementById(id);
    if (el && el.value !== String(v)) el.value = String(v);
  }
  function renderStatus(d) {
    if (!d) return;
    setTextIf("mo-status", d.running ? "🟢 运行中" : "⚪ 已停止");
    setTextIf("mo-symbols", d.symbols.length + " 个");
    setTextIf("mo-scans", d.scan_count);
    setTextIf("mo-last", d.last_scan ? FMT.time(d.last_scan) : "--");
    const errBox = document.getElementById("mo-error");
    if (errBox && errBox.textContent !== (d.source_error ? "[!] " + d.source_error : "")) errBox.textContent = d.source_error ? "[!] " + d.source_error : "";
    setInputIf("mo-interval", d.interval_sec);
    setInputIf("mo-vol", d.thresholds.volume_ratio);
    setInputIf("mo-p1h", (d.thresholds.price_1h * 100).toFixed(1));
    setInputIf("mo-p24", (d.thresholds.price_24h * 100).toFixed(1));
    setInputIf("mo-cooldown", d.thresholds.alert_cooldown_min);
    renderMarkets(d.markets, d.thresholds);
  }

  // diff 单元格更新：值没变就不碰 DOM，避免每 2 秒强制重绘造成闪烁
  function setCell(td, text, cls) {
    const t = String(text);
    if (td.textContent !== t) td.textContent = t;
    const target = cls || "num";
    if (td.className !== target) td.className = target;
  }

  // 增量更新行情表：只更新变化的单元格，避免整表重建闪烁
  function renderMarkets(markets, thresholds) {
    const tbody = document.getElementById("mo-markets");
    if (!tbody) return;
    if (!markets || !markets.length) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-faint)">等待首次扫描…</td></tr>';
      tbody.__rows = {};
      return;
    }
    if (!tbody.__rows) tbody.__rows = {};
    const rows = tbody.__rows;
    const seen = {};
    markets.forEach((m, i) => {
      seen[m.symbol] = true;
      let tr = rows[m.symbol];
      if (!tr) {
        tr = document.createElement("tr");
        tr.dataset.sym = m.symbol;
        tr.innerHTML = '<td class="mo-sym"></td><td class="num mo-price"></td><td class="num mo-c1"></td><td class="num mo-c24"></td><td class="num mo-vol"></td><td class="num mo-vr"></td><td class="mo-time"></td>';
        rows[m.symbol] = tr;
        const ref = tbody.children[i];
        if (ref) tbody.insertBefore(tr, ref); else tbody.appendChild(tr);
      }
      const c1 = m.change_1h, c24 = m.change_24h, vr = m.volume_ratio;
      const hot = (vr && vr >= thresholds.volume_ratio) || (c1 && Math.abs(c1) >= thresholds.price_1h);
      const symTd = tr.children[0];
      if (symTd.textContent !== m.symbol) symTd.textContent = m.symbol;
      const hadBadge = !!symTd.querySelector(".badge");
      if (hot && !hadBadge) {
        const sp = document.createElement("span");
        sp.className = "badge badge-amber";
        sp.textContent = "异动";
        symTd.appendChild(sp);
      } else if (!hot && hadBadge) {
        symTd.querySelectorAll(".badge").forEach((b) => b.remove());
      }
      setCell(tr.children[1], FMT.price(m.price));
      setCell(tr.children[2], FMT.pctSigned(c1), "num " + FMT.cls(c1));
      setCell(tr.children[3], FMT.pctSigned(c24), "num " + FMT.cls(c24));
      setCell(tr.children[4], FMT.num(m.volume, 0));
      setCell(tr.children[5], vr ? vr.toFixed(1) + "x" : "--", "num " + (vr >= thresholds.volume_ratio ? "pos" : ""));
      setCell(tr.children[6], FMT.time(m.updated_at));
    });
    Object.keys(rows).forEach((sym) => {
      if (!seen[sym] && rows[sym].parentNode) {
        rows[sym].parentNode.removeChild(rows[sym]);
        delete rows[sym];
      }
    });
  }

  function renderRankingBox(box, rows, mode) {
    if (!box) return;
    if (!rows || !rows.length) {
      box.innerHTML = '<div class="empty" style="padding:14px">暂无数据</div>';
      box.__rows = null;
      return;
    }
    if (!box.__rows || box.__rows.length !== rows.length) {
      box.innerHTML = renderRankingList(rows, mode);
      box.__rows = Array.from(box.children);
      return;
    }
    rows.forEach((r, i) => {
      const el = box.__rows[i];
      if (!el) return;
      const spans = el.querySelectorAll("span");
      if (spans.length < 3) return;
      const medal = ["🥇", "🥈", "🥉"][i] || String(i + 1);
      const symbol = r.symbol.replace("/USDT", "");
      const price = FMT.price(r.price);
      if (spans[0].textContent !== medal) spans[0].textContent = medal;
      if (spans[1].textContent !== symbol) spans[1].textContent = symbol;
      if (spans[2].textContent !== price) spans[2].textContent = price;
      if (spans[3]) {
        if (mode === "vol") {
          const v = FMT.num(r.volume_24h, 0);
          if (spans[3].textContent !== v) spans[3].textContent = v;
        } else {
          const v = FMT.pctSigned(r.change_24h);
          const c = FMT.cls(r.change_24h);
          if (spans[3].textContent !== v) spans[3].textContent = v;
          if (spans[3].className !== c) spans[3].className = c;
        }
      }
    });
  }

  function renderRankings(rk) {
    if (!rk) return;
    renderRankingBox(document.getElementById("mo-rank-vol"), rk.volume_top10, "vol");
    renderRankingBox(document.getElementById("mo-rank-gain"), rk.gain_top10, "gain");
    renderRankingBox(document.getElementById("mo-rank-drop"), rk.drop_top10, "drop");
  }

  function renderEvents(events) {
    const evBody = document.getElementById("mo-events");
    if (!evBody) return;
    evBody.innerHTML = events && events.length ? events.map((e) => {
      const [cls, label] = EVENT_BADGES[e.type] || ["badge-gray", e.type];
      return '<div class="log-item ' + (e.type.startsWith("price_drop") ? "error" : "info") + '"><span class="log-time">' + FMT.time(e.ts) + '</span><span class="badge ' + cls + '">' + label + '</span><span style="font-family:var(--mono);font-weight:700">' + e.symbol + '</span><span class="log-msg">' + e.detail + '</span></div>';
    }).join("") : '<div class="empty" style="padding:20px">暂无异动事件（扫描中自动检测）</div>';
  }

  // 增量合并事件流：只插入新事件，不整段重建
  function mergeEvents(events) {
    const evBody = document.getElementById("mo-events");
    if (!evBody) return;
    if (!events || !events.length) return;
    if (!state._evSeen) state._evSeen = {};
    const seen = state._evSeen;
    const empty = evBody.querySelector(".empty");
    if (empty) empty.remove();
    let added = 0;
    let firstNew = null;
    events.forEach((e) => {
      const key = e.ts + "|" + e.symbol + "|" + e.type + "|" + e.detail;
      if (seen[key]) return;
      seen[key] = true;
      if (!firstNew) firstNew = e;
      added += 1;
      const [cls, label] = EVENT_BADGES[e.type] || ["badge-gray", e.type];
      const el = document.createElement("div");
      el.className = "log-item " + (e.type.startsWith("price_drop") ? "error" : "info");
      el.innerHTML = '<span class="log-time">' + FMT.time(e.ts) + '</span><span class="badge ' + cls + '">' + label + '</span><span style="font-family:var(--mono);font-weight:700">' + e.symbol + '</span><span class="log-msg">' + e.detail + '</span>';
      evBody.insertBefore(el, evBody.firstChild);
      while (evBody.children.length > 100) evBody.lastChild.remove();
    });
    if (added > 0 && window.notifyUser) window.notifyUser("市场异动", (firstNew ? firstNew.symbol + "：" : "") + (firstNew ? firstNew.title : ""));
    if (added > 0 && App.current !== "monitor") {
      App.state.monitorUnread = (App.state.monitorUnread || 0) + added;
      if (window.updateMonitorBadge) window.updateMonitorBadge();
    }
  }

  async function refresh() {
    try {
      const d = await API.get("/api/monitor/status");
      renderStatus(d);
      const rk = await API.get("/api/monitor/rankings");
      renderRankings(rk);
      loadEvents(false);
    } catch (e) {
      setText("mo-status", "[!] 状态获取失败");
      const errBox = document.getElementById("mo-error");
      if (errBox) errBox.textContent = "[!] " + e.message;
    }
  }

  function onStream(data) {
    if (!data || typeof data !== "object") return;
    if (data.status) renderStatus(data.status);
    if (data.rankings) renderRankings(data.rankings);
    if (state.evFilter === "all" && data.status && data.status.events) {
      mergeEvents((data.status.events || []).slice(0, 50));
    }
  }

  async function loadEvents(append) {
    const evBody = document.getElementById("mo-events");
    if (!evBody) return;
    try {
      let url = "/api/monitor/events?limit=50&offset=" + state.evOffset;
      if (state.evFilter !== "all") url += "&type=" + encodeURIComponent(state.evFilter);
      const res = await API.get(url);
      const events = res.events || [];
      const html = events.length ? events.map((e) => {
        const [cls, label] = EVENT_BADGES[e.type] || ["badge-gray", e.type];
        return '<div class="log-item ' + (e.type.startsWith("price_drop") ? "error" : "info") + '"><span class="log-time">' + FMT.time(e.ts) + '</span><span class="badge ' + cls + '">' + label + '</span><span style="font-family:var(--mono);font-weight:700">' + e.symbol + '</span><span class="log-msg">' + e.detail + '</span></div>';
      }).join("") : '<div class="empty" style="padding:20px">暂无匹配事件</div>';
      if (append) evBody.innerHTML += html; else evBody.innerHTML = html;
      const moreBtn = document.getElementById("mo-ev-more");
      if (moreBtn) moreBtn.style.display = events.length >= 50 ? "" : "none";
    } catch (e) {
      evBody.innerHTML = '<div class="empty" style="padding:20px;color:var(--red)">事件加载失败：' + e.message + '</div>';
    }
  }

  function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  return { render, refresh, onStream };
})());
