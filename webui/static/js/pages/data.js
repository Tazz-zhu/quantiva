/* ============ 数据管理 ============ */
App.register("data", (() => {
  function render() {
    const page = document.getElementById("page-data");
    page.innerHTML = `
      <div class="grid grid-layout-backtest">
        <div class="side-panel">
          <div class="card">
            <div class="card-title">📥 抓取行情数据</div>
            <div class="field"><label>数据源</label>
              <select class="select" id="dt-source">
                <option value="synthetic">合成数据（离线）</option>
                <option value="exchange">交易所（真实行情）</option>
              </select>
            </div>
            <div class="input-row">
              <div class="field"><label>标的</label><input class="input" id="dt-symbol" value="BTC/USDT"></div>
              <div class="field"><label>周期</label>
                <select class="select" id="dt-timeframe">
                  <option>1m</option><option>5m</option><option>15m</option><option>1h</option><option>4h</option><option>1d</option>
                </select>
              </div>
            </div>
            <div class="input-row">
              <div class="field"><label>天数</label><input class="input" id="dt-days" type="number" value="730"></div>
              <div class="field"><label>随机种子</label><input class="input" id="dt-seed" type="number" value="42"></div>
            </div>
            <button class="btn btn-primary btn-block" id="dt-fetch">⚡ 开始抓取</button>
            <div class="hint" id="dt-result"></div>
          </div>
          <div class="card">
            <div class="card-title">💾 存储位置</div>
            <div style="font-family:var(--mono);font-size:12px;color:var(--text-dim)" id="dt-dbpath">--</div>
          </div>
        </div>
        <div>
          <div class="card">
            <div class="card-title">🗄️ 本地数据库统计 <button class="btn btn-sm" id="dt-refresh">⟳ 刷新</button></div>
            <div class="table-wrap" style="max-height:420px">
              <table class="table">
                <thead><tr><th>标的</th><th>周期</th><th class="num">K线数</th><th class="num">缺失率</th><th class="num">最新距今</th><th>起始时间</th><th>结束时间</th><th></th></tr></thead>
                <tbody id="dt-stats"></tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    `;
    document.getElementById("dt-fetch").addEventListener("click", fetchData);
    document.getElementById("dt-refresh").addEventListener("click", loadStats);
    loadStats();
    loadDbPath();
  }

  async function fetchData() {
    const btn = document.getElementById("dt-fetch");
    btn.disabled = true;
    btn.textContent = "⏳ 抓取中…";
    const resultBox = document.getElementById("dt-result");
    const daysNum = parseInt(document.getElementById("dt-days").value) || 730;
    resultBox.textContent = daysNum >= 60 ? "数据量较大（" + daysNum + " 天），可能需要几分钟，请勿关闭页面…" : "抓取中…";
    resultBox.style.color = "var(--text-dim)";
    try {
      const res = await API.post("/api/data/fetch", {
        synthetic: document.getElementById("dt-source").value === "synthetic",
        symbol: document.getElementById("dt-symbol").value.trim(),
        timeframe: document.getElementById("dt-timeframe").value,
        days: parseInt(document.getElementById("dt-days").value) || 730,
        seed: parseInt(document.getElementById("dt-seed").value) || 42,
      });
      resultBox.textContent = "✅ 已保存 " + res.rows + " 根 K 线（" + res.first + " ~ " + res.last + "）";
      resultBox.style.color = "var(--green)";
      loadStats();
      App.toast("数据抓取完成：" + res.rows + " 根 K 线", "success");
    } catch (e) {
      resultBox.textContent = "❌ " + e.message;
      resultBox.style.color = "var(--red)";
      App.toast("抓取失败: " + e.message, "error", 5000);
    } finally {
      btn.disabled = false;
      btn.textContent = "⚡ 开始抓取";
    }
  }

  async function loadStats() {
    const tbody = document.getElementById("dt-stats");
    if (!tbody) return;
    try {
      const rows = await API.get("/api/data/stats");
      tbody.innerHTML = rows.length ? rows.map((r) => {
        const gap = r.gap_ratio === null || r.gap_ratio === undefined ? "--" : '<span class="' + (r.gap_ratio > 0.05 ? "neg" : "pos") + '">' + FMT.pct(r.gap_ratio) + '</span>';
        const fresh = r.freshness_hours === null || r.freshness_hours === undefined ? "--" : FMT.num(r.freshness_hours, 1) + "h";
        return '<tr><td>' + r.symbol + '</td><td>' + r.timeframe + '</td><td class="num">' + r.rows + '</td><td class="num">' + gap + '</td><td class="num">' + fresh + '</td><td>' + FMT.time(r.first) + '</td><td>' + FMT.time(r.last) + '</td><td><button class="btn btn-sm btn-danger" data-del="' + encodeURIComponent(r.symbol) + '|' + r.timeframe + '">删除</button></td></tr>';
      }).join("") : '<tr><td colspan="8" style="text-align:center;color:var(--text-faint)">数据库为空，先抓取一些数据吧</td></tr>';
      tbody.querySelectorAll("[data-del]").forEach((btn) => btn.addEventListener("click", async () => {
        const [sym, tf] = btn.dataset.del.split("|").map(decodeURIComponent);
        const ok = await App.confirmDialog({
          title: "删除本地数据",
          danger: true,
          confirmText: "确认删除",
          requireText: "DELETE",
          message: '将删除 <b>' + sym + ' ' + tf + '</b> 的全部本地 K 线数据，此操作不可恢复。请输入 <b>DELETE</b> 确认。',
        });
        if (!ok) return;
        try {
          const res = await API.del("/api/data?symbol=" + encodeURIComponent(sym) + "&timeframe=" + encodeURIComponent(tf));
          App.toast("已删除 " + res.deleted + " 根 K 线", "success");
          loadStats();
        } catch (e) {
          App.toast("删除失败: " + e.message, "error", 5000);
        }
      }));
    } catch (e) {
      tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--red)">加载失败</td></tr>';
    }
  }

  async function loadDbPath() {
    try {
      const cfg = await API.get("/api/config");
      const el = document.getElementById("dt-dbpath");
      if (el) el.textContent = cfg.data.storage_db || "data/ohlcv.db";
    } catch (e) { /* 忽略 */ }
  }

  return { render, refresh() { loadStats(); } };
})());
