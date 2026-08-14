/* ============ 数据管理（交易所真实行情抓取） ============ */
App.register("data", (() => {
  function render() {
    const page = document.getElementById("page-data");
    page.innerHTML = `
      <div class="grid grid-layout-backtest">
        <div class="side-panel">
          <div class="card">
            <div class="card-title">📥 抓取交易所行情</div>
            <div class="field"><label>数据源</label>
              <select class="select" id="dt-source">
                <option value="exchange" selected>交易所（OKX 真实行情）</option>
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
            </div>
            <button class="btn btn-primary btn-block" id="dt-fetch">⚡ 开始抓取</button>
            <div class="hint" id="dt-result"></div>
          </div>
          <div class="card">
            <div class="card-title">ℹ️ 说明</div>
            <div style="font-size:12px;color:var(--text-dim);line-height:1.8">行情数据仅来自交易所真实数据（OKX）。本地文件只作为内部缓存，不再作为独立数据源展示。</div>
          </div>
        </div>
      </div>
    `;
    document.getElementById("dt-fetch").addEventListener("click", fetchData);
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
        symbol: document.getElementById("dt-symbol").value.trim(),
        timeframe: document.getElementById("dt-timeframe").value,
        days: parseInt(document.getElementById("dt-days").value) || 730,
      });
      resultBox.textContent = "✅ 已从交易所抓取 " + res.rows + " 根 K 线（" + res.first + " ~ " + res.last + "）";
      resultBox.style.color = "var(--green)";
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

  return { render };
})());
