/* ============ 系统设置（交易所 / AI / 飞书 / 安全运维） ============ */
App.register("settings", (() => {
  let cfg = null;

  async function render() {
    const page = document.getElementById("page-settings");
    page.innerHTML = '<div class="loading"><div class="spinner"></div>加载配置…</div>';
    try {
      cfg = await API.get("/api/config");
    } catch (e) {
      page.innerHTML = '<div class="card"><div class="empty">配置加载失败: ' + e.message + '</div></div>';
      return;
    }
    const ai = cfg.ai || {};
    const fs = (cfg.notify || {}).feishu || {};
    const nt = cfg.notify || {};
    const cm = cfg.community || {};
    page.innerHTML = `
      <div class="grid grid-layout-backtest">
        <div class="side-panel">
          <div class="card">
            <div class="card-title">🌐 交易所</div>
            <div class="field"><label>交易所 (ccxt)</label>
              <select class="select" id="st-exchange">
                ${["binance", "okx", "bybit", "gateio", "bitget", "kraken", "coinbase", "mexc", "huobi"].map((x) => '<option value="' + x + '" ' + (cfg.exchange.id === x ? "selected" : "") + '>' + x + '</option>').join("")}
              </select>
            </div>
            <div class="field"><label>测试网</label>
              <select class="select" id="st-sandbox">
                <option value="false" ${cfg.exchange.sandbox ? "" : "selected"}>否</option>
                <option value="true" ${cfg.exchange.sandbox ? "selected" : ""}>是</option>
              </select>
            </div>
            <div class="input-row">
              <div class="field"><label>API Key（测试用）</label><input class="input" id="st-api-key" placeholder="可选"></div>
              <div class="field"><label>API Secret（测试用）</label><input class="input" id="st-api-secret" placeholder="可选"></div>
            </div>
            <button class="btn btn-sm" id="st-ex-test">🔌 测试交易所连接</button>
            <span id="st-ex-result" style="font-size:12px;margin-left:8px"></span>
            <div class="hint" style="margin-top:8px">🔗 获取 API Key（点击前往）：
              <a href="https://www.binance.com/zh-CN/support/faq/how-to-create-api-keys-on-binance-360002502072" target="_blank" rel="noopener">Binance</a> ·
              <a href="https://www.okx.com/zh-hans/account/my-api" target="_blank" rel="noopener">OKX</a> ·
              <a href="https://www.bybit.com/zh-CN/app/user/api-management" target="_blank" rel="noopener">Bybit</a> ·
              <a href="https://www.gate.io/zh/account/api_keys" target="_blank" rel="noopener">Gate.io</a> ·
              <a href="https://www.bitget.com/zh-CN/account/newapi" target="_blank" rel="noopener">Bitget</a>
            </div>
          </div>
          <div class="card">
            <div class="card-title">🤖 AI 大模型（策略优化建议）</div>
            <div class="field"><label>启用 AI</label>
              <select class="select" id="st-ai-enabled">
                <option value="false" ${ai.enabled ? "" : "selected"}>关闭</option>
                <option value="true" ${ai.enabled ? "selected" : ""}>开启</option>
              </select>
            </div>
            <div class="field"><label>接口地址 base_url</label><input class="input" id="st-ai-url" value="${ai.base_url || ""}" placeholder="https://api.openai.com/v1"></div>
            <div class="input-row">
              <div class="field"><label>模型</label><input class="input" id="st-ai-model" value="${ai.model || "gpt-4o-mini"}" placeholder="gpt-4o-mini / deepseek-chat"></div>
              <div class="field"><label>温度</label><input class="input" id="st-ai-temp" type="number" step="0.1" value="${ai.temperature ?? 0.4}"></div>
            </div>
            <div class="field"><label>API Key 环境变量名</label><input class="input" id="st-ai-env" value="${ai.api_key_env || "OPENAI_API_KEY"}"></div>
            <div class="field"><label>API Key（可选，直接保存）</label><input class="input" id="st-ai-key" type="password" value="${ai.api_key || ""}" placeholder="留空则读取环境变量"></div>
            <div class="hint">支持 OpenAI / DeepSeek / 通义千问 / Ollama 等任何 OpenAI 兼容接口</div>
            <div class="hint" style="margin-top:6px">🔗 获取 API Key（点击前往）：
              <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener">OpenAI</a> ·
              <a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noopener">DeepSeek</a> ·
              <a href="https://dashscope.console.aliyun.com/apiKey" target="_blank" rel="noopener">通义千问</a> ·
              <a href="https://ollama.com/library" target="_blank" rel="noopener">Ollama（本地免费）</a>
            </div>
          </div>
          <div class="card">
            <div class="card-title">📣 飞书推送</div>
            <div class="field"><label>启用飞书</label>
              <select class="select" id="st-fs-enabled">
                <option value="false" ${fs.enabled ? "" : "selected"}>关闭</option>
                <option value="true" ${fs.enabled ? "selected" : ""}>开启</option>
              </select>
            </div>
            <div class="field"><label>Webhook 地址</label><input class="input" id="st-fs-webhook" value="${fs.webhook || ""}" placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..."></div>
            <div class="field"><label>签名密钥（可选）</label><input class="input" id="st-fs-secret" value="${fs.secret || ""}" placeholder="机器人安全设置中的签名密钥"></div>
            <div class="input-row">
              <div class="field"><label>交易推送</label>
                <select class="select" id="st-fs-trade"><option value="true" ${nt.on_trade !== false ? "selected" : ""}>开</option><option value="false" ${nt.on_trade === false ? "selected" : ""}>关</option></select>
              </div>
              <div class="field"><label>异动推送</label>
                <select class="select" id="st-fs-alert"><option value="true" ${nt.on_alert !== false ? "selected" : ""}>开</option><option value="false" ${nt.on_alert === false ? "selected" : ""}>关</option></select>
              </div>
            </div>
            <button class="btn btn-sm" id="st-fs-test">🧪 发送测试消息</button>
            <span id="st-fs-test-result" style="font-size:12px;margin-left:8px"></span>
            <div class="hint" style="margin-top:8px">🔗 创建飞书自定义机器人 / 获取 Webhook：<a href="https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot" target="_blank" rel="noopener">飞书开放平台官方文档</a></div>
          </div>
          <div class="card">
            <div class="card-title">💬 用户社群</div>
            <div class="field"><label>QQ 群一键加群链接</label><input class="input" id="st-qq-url" placeholder="如 https://qm.qq.com/q/xxxxxx" value="${cm.qq_url || ''}"></div>
            <div class="field"><label>QQ 群号（无链接时用户可复制）</label><input class="input" id="st-qq-group" placeholder="如 123456789" value="${cm.qq_group || ''}"></div>
            <div class="field"><label>微信链接（群 / 客服）</label><input class="input" id="st-wechat-url" placeholder="可选" value="${cm.wechat_url || ''}"></div>
            <div class="field"><label>微信二维码图片地址</label><input class="input" id="st-wechat-qr" placeholder="/static/community/wechat.png 或 https://…" value="${cm.wechat_qr || ''}"></div>
            <div class="hint">配置后，侧栏「加入社群」按钮会展示对应入口；留空则不显示。</div>
          </div>
          <div class="card">
            <div class="card-title">🔐 安全与运维</div>
            <div class="field"><label>原密码</label><input class="input" id="st-oldpwd" type="password" placeholder="当前密码"></div>
            <div class="input-row">
              <div class="field"><label>新密码</label><input class="input" id="st-newpwd" type="password" placeholder="至少 6 位"></div>
              <div class="field"><label>确认新密码</label><input class="input" id="st-newpwd2" type="password"></div>
            </div>
            <button class="btn btn-sm" id="st-chpwd">🔑 修改密码</button>
            <span id="st-chpwd-result" style="font-size:12px;margin-left:8px"></span>
            <div class="divider"></div>
            <div id="st-sysinfo" style="font-size:12px;color:var(--text-dim);line-height:1.9;font-family:var(--mono)"></div>
            <button class="btn btn-sm" id="st-backup" style="margin-top:10px">💾 立即备份数据</button>
            <span id="st-backup-result" style="font-size:12px;margin-left:8px"></span>
            <div class="divider"></div>
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
              <span style="font-size:12px;color:var(--text-dim);font-weight:600">📜 操作审计日志</span>
              <span style="display:flex;gap:6px"><button class="btn btn-sm" id="st-audit-csv">导出 CSV</button><button class="btn btn-sm" id="st-audit-refresh">⟳ 刷新</button></span>
            </div>
            <div class="table-wrap" style="max-height:260px">
              <table class="table">
                <thead><tr><th>时间</th><th>用户</th><th>操作</th><th>路径</th><th>IP</th><th>状态</th></tr></thead>
                <tbody id="st-audit-body"></tbody>
              </table>
            </div>
          </div>
          <div class="card">
            <div class="card-title">💵 交易成本与实盘</div>
            <div class="input-row">
              <div class="field"><label>手续费率</label><input class="input" id="st-fee" type="number" step="0.0001" value="${cfg.backtest.fee_rate}"></div>
              <div class="field"><label>滑点</label><input class="input" id="st-slip" type="number" step="0.0001" value="${cfg.backtest.slippage}"></div>
            </div>
            <div class="input-row">
              <div class="field"><label>轮询间隔（秒）</label><input class="input" id="st-poll" type="number" value="${cfg.live.poll_interval_sec}"></div>
              <div class="field"><label>模拟盘初始资金</label><input class="input" id="st-balance" type="number" value="${cfg.live.paper_initial_balance}"></div>
            </div>
            <div class="field"><label>数据库路径</label><input class="input" id="st-db" value="${cfg.data.storage_db}"></div>
          </div>
          <div class="field" style="margin-top:4px"><label>浏览器通知（回测/进化/异动）</label>
            <select class="select" id="st-notify">
              <option value="1">开启</option>
              <option value="0">关闭</option>
            </select>
          </div>
          <button class="btn btn-primary btn-block btn-run" id="st-save">💾 保存全部配置</button>
          <button class="btn btn-block" id="st-reset-config" style="margin-top:8px">♻️ 恢复默认配置</button>
        </div>
        <div>
          <div class="card">
            <div class="card-title">📋 当前配置预览</div>
            <pre id="st-preview" style="font-family:var(--mono);font-size:12px;color:var(--text-dim);max-height:620px;overflow:auto;white-space:pre-wrap;background:rgba(0,0,0,0.25);padding:16px;border-radius:10px">${JSON.stringify(cfg, null, 2)}</pre>
          </div>
        </div>
      </div>
    `;
    document.getElementById("st-save").addEventListener("click", save);
    document.getElementById("st-audit-csv").addEventListener("click", () => window.open("/api/audit/logs.csv", "_blank"));
    const notifySel = document.getElementById("st-notify");
    if (notifySel) {
      notifySel.value = (() => { try { return localStorage.getItem("quantx_notify") !== "0" ? "1" : "0"; } catch (e) { return "1"; } })();
      notifySel.addEventListener("change", () => { try { localStorage.setItem("quantx_notify", notifySel.value); } catch (e) {} App.toast("通知设置已保存", "success"); });
    }
    document.getElementById("st-reset-config").addEventListener("click", async () => {
      const ok = await App.confirmDialog({
        title: "恢复默认配置",
        danger: true,
        confirmText: "确认恢复",
        requireText: "RESET",
        message: "将把 config/config.yaml 恢复为内置默认值（环境变量密钥不受影响）。请输入 <b>RESET</b> 确认。",
      });
      if (!ok) return;
      try {
        await API.post("/api/config/reset", {});
        App.toast("已恢复默认配置，正在刷新…", "success");
        setTimeout(() => location.reload(), 800);
      } catch (e) {
        App.toast("恢复失败: " + e.message, "error", 5000);
      }
    });
    document.getElementById("st-fs-test").addEventListener("click", testFeishu);
    document.getElementById("st-ex-test").addEventListener("click", testExchange);
    document.getElementById("st-chpwd").addEventListener("click", changePassword);
    document.getElementById("st-backup").addEventListener("click", backupNow);
    document.getElementById("st-audit-refresh").addEventListener("click", loadAudit);
    loadSystemInfo();
  }

  async function testExchange() {
    const btn = document.getElementById("st-ex-test");
    const result = document.getElementById("st-ex-result");
    btn.disabled = true;
    result.textContent = "测试中…";
    try {
      const res = await API.post("/api/exchange/test", {
        exchange_id: document.getElementById("st-exchange").value,
        api_key: document.getElementById("st-api-key").value.trim(),
        api_secret: document.getElementById("st-api-secret").value.trim(),
      });
      result.textContent = res.ok ? "✅ " + res.detail : "❌ " + res.detail;
      result.style.color = res.ok ? "var(--green)" : "var(--red)";
    } catch (e) {
      result.textContent = "❌ " + e.message;
      result.style.color = "var(--red)";
    } finally {
      btn.disabled = false;
    }
  }

  async function testFeishu() {
    const btn = document.getElementById("st-fs-test");
    const result = document.getElementById("st-fs-test-result");
    btn.disabled = true;
    result.textContent = "发送中…";
    try {
      const res = await API.post("/api/notify/test", { message: "🧪 Quantiva 测试消息：飞书推送已接通！" });
      result.textContent = "✅ " + res.message;
      result.style.color = "var(--green)";
    } catch (e) {
      result.textContent = "❌ " + e.message;
      result.style.color = "var(--red)";
    } finally {
      btn.disabled = false;
    }
  }

  async function loadSystemInfo() {
    const box = document.getElementById("st-sysinfo");
    if (!box) return;
    try {
      const s = await API.get("/api/system/status");
      const dbs = Object.entries(s.dbs || {}).map(([k, v]) => k + "=" + (v / 1024).toFixed(0) + "KB").join(" · ");
      const node = s.node || {};
      box.innerHTML = '<div>版本 <b>v' + s.version + '</b> · 节点 <b>' + (node.node_id || "--") + '</b>（角色 ' + (node.role || "all") + '）· 已运行 ' + fmtUptime(s.uptime_seconds) + '</div>'
        + '<div>数据库：' + (dbs || "无") + '</div>'
        + '<div>日志 ' + (s.log_size / 1024).toFixed(0) + 'KB · 备份 ' + s.backup_count + ' 次（最近 ' + (s.last_backup || "--") + '）· 审计 ' + ((s.audit || {}).count || 0) + ' 条</div>'
        + '<div>监控 ' + (s.monitor && s.monitor.running ? "运行中" : "停止") + ' · ' + (s.monitor ? s.monitor.scans + " 次扫描" : "") + ' · 进化 ' + (s.evolution && s.evolution.auto_running ? "自动分析中" : "未启动") + '</div>';
      loadAudit();
    } catch (e) { /* 忽略 */ }
  }

  async function loadAudit() {
    const tbody = document.getElementById("st-audit-body");
    if (!tbody) return;
    try {
      const { logs } = await API.get("/api/audit/logs?limit=50");
      tbody.innerHTML = logs.length ? logs.map((l) => '<tr><td>' + FMT.time(l.ts) + '</td><td><span class="badge badge-blue">' + l.username + '</span></td><td>' + l.action + '</td><td style="font-size:11px;color:var(--text-dim)">' + l.method + " " + l.path + '</td><td>' + l.ip + '</td><td><span class="badge ' + (l.status < 300 ? "badge-green" : "badge-red") + '">' + l.status + '</span></td></tr>').join("") : '<tr><td colspan="6" style="text-align:center;color:var(--text-faint)">暂无审计记录</td></tr>';
    } catch (e) { /* 忽略 */ }
  }

  function fmtUptime(sec) {
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    return h > 0 ? h + "小时" + m + "分" : m + "分钟";
  }

  async function changePassword() {
    const oldP = document.getElementById("st-oldpwd").value;
    const newP = document.getElementById("st-newpwd").value;
    const newP2 = document.getElementById("st-newpwd2").value;
    const result = document.getElementById("st-chpwd-result");
    if (!oldP) { result.textContent = "请输入原密码"; result.style.color = "var(--red)"; return; }
    if (newP !== newP2) { result.textContent = "两次新密码不一致"; result.style.color = "var(--red)"; return; }
    try {
      await API.post("/api/auth/change-password", { old_password: oldP, new_password: newP });
      result.textContent = "✅ 密码已更新";
      result.style.color = "var(--green)";
      document.getElementById("st-oldpwd").value = "";
      document.getElementById("st-newpwd").value = "";
      document.getElementById("st-newpwd2").value = "";
      App.toast("密码修改成功，请重新登录", "success");
      const banner = document.getElementById("default-pwd-banner");
      if (banner) banner.style.display = "none";
      setTimeout(() => { API.setToken(null); location.reload(); }, 1200);
    } catch (e) {
      result.textContent = "❌ " + e.message;
      result.style.color = "var(--red)";
    }
  }

  async function backupNow() {
    const btn = document.getElementById("st-backup");
    const result = document.getElementById("st-backup-result");
    btn.disabled = true;
    result.textContent = "备份中…";
    try {
      const res = await API.post("/api/system/backup", {});
      result.textContent = "✅ 已备份 " + res.files.length + " 个数据库";
      result.style.color = "var(--green)";
      loadSystemInfo();
    } catch (e) {
      result.textContent = "❌ " + e.message;
      result.style.color = "var(--red)";
    } finally {
      btn.disabled = false;
    }
  }

  async function save() {
    const patch = {
      exchange: { id: document.getElementById("st-exchange").value.trim(), sandbox: document.getElementById("st-sandbox").value === "true" },
      ai: { enabled: document.getElementById("st-ai-enabled").value === "true", base_url: document.getElementById("st-ai-url").value.trim(), model: document.getElementById("st-ai-model").value.trim(), temperature: parseFloat(document.getElementById("st-ai-temp").value) || 0.4, api_key_env: document.getElementById("st-ai-env").value.trim(), api_key: document.getElementById("st-ai-key").value.trim() },
      notify: { feishu: { enabled: document.getElementById("st-fs-enabled").value === "true", webhook: document.getElementById("st-fs-webhook").value.trim(), secret: document.getElementById("st-fs-secret").value.trim() }, on_trade: document.getElementById("st-fs-trade").value === "true", on_alert: document.getElementById("st-fs-alert").value === "true" },
      backtest: { fee_rate: parseFloat(document.getElementById("st-fee").value) || 0.001, slippage: parseFloat(document.getElementById("st-slip").value) || 0.0005 },
      live: { poll_interval_sec: parseFloat(document.getElementById("st-poll").value) || 60, paper_initial_balance: parseFloat(document.getElementById("st-balance").value) || 10000 },
      data: { storage_db: document.getElementById("st-db").value.trim() },
      community: {
        enabled: true,
        qq_url: document.getElementById("st-qq-url").value.trim(),
        qq_group: document.getElementById("st-qq-group").value.trim(),
        wechat_url: document.getElementById("st-wechat-url").value.trim(),
        wechat_qr: document.getElementById("st-wechat-qr").value.trim(),
      },
    };
    try {
      const res = await API.post("/api/config", patch);
      cfg = res.config;
      document.getElementById("st-preview").textContent = JSON.stringify(cfg, null, 2);
      App.toast("配置已保存 ✅", "success");
    } catch (e) {
      App.toast("保存失败: " + e.message, "error");
    }
  }

  return { render, refresh() {} };
})());
