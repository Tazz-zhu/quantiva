/* ============ 应用框架：路由 / 时钟 / Toast / 认证 ============ */
window.App = (() => {
  const pages = {};
  let current = "dashboard";
  const titles = {
    dashboard: "仪表盘", chart: "行情图表", backtest: "策略回测", custom: "策略构建",
    monitor: "市场监控", evolution: "策略进化", live: "实盘交易", data: "数据管理", settings: "系统设置",
  };

  function toast(msg, type = "info", ms = 3200) {
    const el = EL('<div class="toast ' + type + '"><span class="toast-dot"></span><span>' + msg + '</span></div>');
    document.getElementById("toast-container").appendChild(el);
    setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 350); }, ms);
  }

  function register(name, module) { pages[name] = module; }

  function go(name) {
    if (!pages[name]) return;
    current = name;
    document.querySelectorAll(".nav-item").forEach((a) => a.classList.toggle("active", a.dataset.page === name));
    document.querySelectorAll(".page").forEach((s) => s.classList.toggle("active", s.id === "page-" + name));
    document.getElementById("page-title").textContent = titles[name] || name;
    document.title = "Quantiva · " + (titles[name] || name);
    if (pages[name].render) pages[name].render();
    if (pages[name].refresh) pages[name].refresh();
    const scope = STREAM_SCOPES[name];
    if (scope) {
      startStream(scope, (data) => {
        if (pages[name] && pages[name].onStream) pages[name].onStream(data);
      });
    } else {
      stopStream();
    }
    autoTips();
    professionalize();
  }

  function initClock() {
    const el = document.getElementById("clock");
    const tick = () => {
      const d = new Date();
      const p = (n) => String(n).padStart(2, "0");
      el.textContent = d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
    };
    tick();
    setInterval(tick, 1000);
  }

  async function checkHealth() {
    try {
      const h = await API.get("/api/health");
      const dot = document.getElementById("conn-dot");
      const txt = document.getElementById("conn-text");
      dot.className = "dot dot-green pulse";
      txt.textContent = "服务在线";
      document.getElementById("server-info").textContent = "Quantiva v" + (h.version || "1.0") + " · " + new Date(h.time * 1000).toLocaleTimeString();
    } catch (e) {
      document.getElementById("conn-dot").className = "dot dot-red";
      document.getElementById("conn-text").textContent = "服务离线";
    }
  }

  async function initAuth() {
    try {
      const status = await API.get("/api/auth/status");
      App.state.authStatus = status;
      if (status.enabled && !API.getToken()) {
        showLogin(status);
        return false;
      }
      hideLogin();
      return true;
    } catch (e) {
      showLogin({ enabled: true, default_password: false });
      return false;
    }
  }

  function showLogin(status) {
    const screen = document.getElementById("login-screen");
    if (!screen) return;
    screen.style.display = "flex";
    const hint = document.getElementById("login-hint");
    if (hint && status && status.default_password) {
      hint.textContent = "⚠️ 当前为默认密码 admin123，登录后请立即在「系统设置」中修改";
      hint.style.color = "var(--amber)";
    }
    const btn = document.getElementById("login-btn");
    btn.addEventListener("click", doLogin);
    const pwd = document.getElementById("login-password");
    pwd.addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });
    // 记住用户名
    try {
      const savedUser = localStorage.getItem("quantx_user");
      const userInput = document.getElementById("login-username");
      if (savedUser && userInput) { userInput.value = savedUser; pwd.focus(); }
    } catch (e) { /* 忽略 */ }
  }

  async function doLogin() {
    const btn = document.getElementById("login-btn");
    const err = document.getElementById("login-err");
    btn.disabled = true;
    btn.textContent = "登录中…";
    err.textContent = "";
    try {
      const username = document.getElementById("login-username").value.trim() || "admin";
      const password = document.getElementById("login-password").value;
      const res = await API.post("/api/auth/login", { username, password });
      try { localStorage.setItem("quantx_user", username); } catch (e) { /* 忽略 */ }
      API.setToken(res.token);
      hideLogin();
      toast("欢迎回来，" + (res.username || "admin"), "success");
      location.reload();
    } catch (e) {
      err.textContent = e.message;
      btn.disabled = false;
      btn.textContent = "登 录";
    }
  }

  // ---------- SSE 实时推送（实盘 / 监控） ----------
  const STREAM_SCOPES = { live: "live", monitor: "monitor" };
  let activeStream = null;
  let streamFailures = 0;

  function startStream(scope, onMessage) {
    stopStream();
    if (!window.EventSource) return false;
    const token = API.getToken() || "";
    const es = new EventSource("/api/stream?scope=" + encodeURIComponent(scope) + "&token=" + encodeURIComponent(token));
    activeStream = { es, scope };
    streamFailures = 0;
    es.onopen = () => { streamFailures = 0; };
    es.onmessage = (ev) => {
      if (!ev.data) return;
      streamFailures = 0;
      try { onMessage(JSON.parse(ev.data)); } catch (e) { /* 忽略 */ }
    };
    es.onerror = () => {
      streamFailures += 1;
      if (streamFailures >= 3) {
        stopStream();
        const pg = pages[current];
        if (pg && pg.refresh) pg.refresh();
      }
    };
    return true;
  }

  function stopStream() {
    if (activeStream) {
      try { activeStream.es.close(); } catch (e) { /* 忽略 */ }
      activeStream = null;
    }
  }

  function isStreaming(scope) {
    return !!(activeStream && activeStream.scope === scope && activeStream.es.readyState === 1);
  }

  // ---------- 通用确认弹窗 ----------
  function confirmDialog(opts) {
    return new Promise((resolve) => {
      const root = document.getElementById("modal-root");
      if (!root) { resolve(true); return; }
      const o = opts || {};
      const title = o.title || "确认操作";
      const message = o.message || "";
      const confirmText = o.confirmText || "确认";
      const danger = !!o.danger;
      const requireText = o.requireText || null;
      let inputHtml = "";
      if (requireText) {
        inputHtml = '<div class="modal-field"><label>请输入 <b>' + requireText + '</b> 以确认</label><input class="input" id="modal-confirm-input" placeholder="' + requireText + '"></div>';
      }
      const mask = EL('<div class="modal-mask"><div class="modal ' + (danger ? "modal-danger" : "") + '"><div class="modal-title">' + title + '</div><div class="modal-body">' + message + inputHtml + '</div><div class="modal-actions"><button class="btn" id="modal-cancel">取消</button><button class="btn ' + (danger ? "btn-danger" : "btn-primary") + '" id="modal-ok">' + confirmText + '</button></div></div></div>');
      function close(val) { root.removeChild(mask); resolve(val); }
      mask.querySelector("#modal-cancel").addEventListener("click", () => close(false));
      mask.querySelector("#modal-ok").addEventListener("click", () => {
        if (requireText) {
          const v = (mask.querySelector("#modal-confirm-input") || {}).value || "";
          if (v !== requireText) {
            const input = mask.querySelector("#modal-confirm-input");
            if (input) { input.style.borderColor = "var(--red)"; input.focus(); }
            return;
          }
        }
        close(true);
      });
      mask.addEventListener("click", (e) => { if (e.target === mask) close(false); });
      root.appendChild(mask);
      const input = mask.querySelector("#modal-confirm-input");
      if (input) input.focus();
    });
  }

  // ---------- 加入社群弹窗 ----------
  async function communityDialog() {
    const root = document.getElementById("modal-root");
    if (!root) return;
    let cfg = {};
    try {
      const res = await API.get("/api/config");
      cfg = res.community || {};
    } catch (e) { /* 忽略 */ }
    const qqUrl = cfg.qq_url || "";
    const qqGroup = cfg.qq_group || "";
    const wechatUrl = cfg.wechat_url || "";
    const wechatQr = cfg.wechat_qr || "";
    const hasAny = !!(qqUrl || qqGroup || wechatUrl || wechatQr);
    let bodyHtml = "";
    if (!hasAny) {
      bodyHtml = '<div class="empty" style="padding:18px">社群链接还未配置<br><span style="font-size:11px">可在「系统设置 → 社群」中填写 QQ / 微信入口</span></div>';
    } else {
      if (qqUrl || qqGroup) {
        bodyHtml += '<div class="community-item"><div class="community-name">QQ 群</div><div style="display:flex;gap:8px;flex-wrap:wrap">'
          + (qqUrl ? '<a class="btn btn-primary btn-sm" href="' + qqUrl + '" target="_blank" rel="noopener">加入 QQ 群</a>' : '')
          + (qqGroup ? '<button class="btn btn-sm" id="comm-copy-qq">复制群号：' + qqGroup + '</button>' : '')
          + '</div></div>';
      }
      if (wechatUrl || wechatQr) {
        bodyHtml += '<div class="community-item"><div class="community-name">微信</div>'
          + (wechatQr ? '<img class="community-qr" src="' + wechatQr + '" alt="微信二维码">' : '')
          + (wechatUrl ? '<div style="margin-top:8px"><a class="btn btn-primary btn-sm" href="' + wechatUrl + '" target="_blank" rel="noopener">打开微信</a></div>' : '')
          + '</div>';
      }
    }
    const mask = EL('<div class="modal-mask"><div class="modal"><div class="modal-title">💬 加入 Quantiva 用户社群</div><div class="modal-body">' + bodyHtml + '</div><div class="modal-actions"><button class="btn" id="comm-close">关闭</button></div></div></div>');
    function close() { root.removeChild(mask); }
    mask.querySelector("#comm-close").addEventListener("click", close);
    mask.addEventListener("click", (e) => { if (e.target === mask) close(); });
    const copyBtn = mask.querySelector("#comm-copy-qq");
    if (copyBtn) {
      copyBtn.addEventListener("click", () => {
        const group = copyBtn.textContent.replace("复制群号：", "").trim();
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(group).then(() => toast("QQ 群号已复制", "success")).catch(() => {});
        } else {
          const ta = document.createElement("textarea");
          ta.value = group; document.body.appendChild(ta); ta.select();
          try { document.execCommand("copy"); toast("QQ 群号已复制", "success"); } catch (e) {}
          ta.remove();
        }
      });
    }
    root.appendChild(mask);
  }

  function hideLogin() {
    const screen = document.getElementById("login-screen");
    if (screen) screen.style.display = "none";
  }


  // ---------- 全局参数问号悬浮提示 ----------
  const TIP_DICT = {
    "策略类型": "选择要回测的策略：经典策略库 / 自定义规则 / 代码策略",
    "策略": "选择参与回测或优化的交易策略",
    "数据源": "数据来源：合成数据（离线演示）/ 自动（优先连交易所）/ 本地数据库",
    "标的": "交易对，如 BTC/USDT",
    "周期": "K 线周期：1m/5m/15m/1h/4h/1d；周期越大，信号越慢、交易越少",
    "回看天数": "使用最近多少天的数据做回测",
    "天数": "生成或拉取多少天的历史数据",
    "随机种子": "合成数据的随机数种子；固定后每次生成的数据可复现，便于公平对比",
    "回测预设": "一键套用风险组合：标准 / 保守 / 激进，也可手动微调",
    "仓位比例": "每次开仓使用的资金比例，0.5 表示半仓",
    "仓位%": "每次开仓使用的资金比例，0.5 表示半仓",
    "杠杆": "合约杠杆倍数，1 表示无杠杆，5 表示 5 倍",
    "ATR止损": "用 ATR 波动幅度的 N 倍作为止损距离；数值越大止损越宽松",
    "ATR 止损倍数": "用 ATR 波动幅度的 N 倍作为止损距离；数值越大止损越宽松",
    "止损% (空=ATR)": "固定百分比止损，如 0.03 表示亏 3% 止损；留空则用 ATR 止损",
    "固定止损% (空=用ATR)": "固定百分比止损；留空则用 ATR 止损",
    "止盈%": "盈利达到该百分比时平仓止盈（可选，留空则只靠信号/止损离场）",
    "固定止盈%": "盈利达到该百分比时平仓止盈（可选）",
    "初始资金": "回测或模拟盘使用的起始本金",
    "手续费率": "每笔交易扣除的手续费比例（币安现货约 0.001，合约约 0.0005）",
    "滑点": "下单时价格偏离的模拟损耗，0.0005 表示万分之 5",
    "最大组合数": "本次最多回测多少组参数组合，超出会截断",
    "搜索档位": "搜索规模预设：快速 12 组 / 标准 40 组 / 深度 120 组",
    "优化目标": "用哪个指标衡量参数好坏：夏普（推荐）/ 总收益 / 年化 / 胜率 / 盈亏比",
    "参数 1": "第一个要搜索的参数（必填），填写最小 / 最大 / 步长",
    "参数 2（可选）": "第二个要搜索的参数（可留空），填写最小 / 最大 / 步长",
    "交易方向": "只做多（仅开多单）或 多空都做（双向开仓）",
    "规则 JSON（可在「策略构建」页可视化编辑）": "自定义策略的规则定义，可在此直接编辑 JSON 或回构建页可视化修改",
    "参数 JSON（代码中通过 params 读取）": "代码策略的参数字典，代码内通过 params 读取",
    "参数 JSON（可选，代码中通过 params 读取）": "代码策略的参数字典，代码内通过 params 读取；留空则使用默认参数",
    "Python 代码（必须定义 generate_signals(df, params)）": "用 Python 编写策略信号：返回 +1 做多 / -1 做空 / 0 空仓 的序列",
    "策略名称": "给策略起个名字，便于保存和管理",
    "条件逻辑": "多个条件的组合方式：AND（全部满足）或 OR（任一满足）",
    "快线周期": "短期均线长度；快线上穿慢线（金叉）做多，下穿（死叉）离场",
    "慢线周期": "长期均线长度；与快线配合判断趋势方向",
    "快线": "MACD 快线周期，默认 12",
    "慢线": "MACD 慢线周期，默认 26",
    "信号线": "MACD 信号线（DEA）周期，默认 9",
    "RSI 周期": "RSI 指标的计算周期，默认 14",
    "标准差倍数": "布林带宽度 = 中轨 ± N 倍标准差；越大通道越宽",
    "超卖阈值": "RSI 低于该值视为超卖，通常是买点",
    "超买阈值": "RSI 高于该值视为超买，通常是卖点",
    "入场突破周期": "突破近 N 根 K 线的最高价时开多",
    "离场突破周期": "跌破近 N 根 K 线的最低价时离场",
    "新高回看周期": "价格创出近 N 根 K 线新高时开仓",
    "离场均线": "价格跌破该均线时离场",
    "区间周期": "通道/区间策略的统计周期",
    "趋势快线": "趋势判断的短期均线周期",
    "趋势慢线": "趋势判断的长期均线周期",
    "模式": "模拟盘（虚拟资金练手）或实盘（真实下单）",
    "轮询间隔（秒）": "每次检查行情和信号的间隔秒数，越小越灵敏、越耗资源",
    "扫描间隔（秒）": "市场扫描频率，越小越灵敏",
    "放量倍数阈值": "成交量超过近期均量的 N 倍时视为放量异动",
    "1h 涨跌阈值%": "1 小时内涨跌幅超过该值触发异动告警",
    "24h 涨跌阈值%": "24 小时内涨跌幅超过该值触发异动告警",
    "告警冷却（分钟）": "同一币种两次告警的最小间隔，避免刷屏",
    "交易所 (ccxt)": "对接的加密货币交易所（ccxt 统一接口）",
    "测试网": "使用交易所测试网络模拟成交，不会产生真实订单",
    "API Key（测试用）": "交易所 API Key，用于行情与下单",
    "API Secret（测试用）": "交易所 API 密钥，注意保密",
    "启用 AI": "是否启用 AI 大模型生成策略优化建议",
    "接口地址 base_url": "OpenAI 兼容接口地址，如 https://api.openai.com/v1",
    "模型": "AI 模型名称，如 gpt-4o-mini / deepseek-chat",
    "温度": "AI 输出随机性（0~1），越低越严谨",
    "API Key 环境变量名": "从该环境变量读取 API Key，更安全",
    "API Key（可选，直接保存）": "直接保存 API Key（优先于环境变量）",
    "启用飞书": "是否将交易/异动信息推送到飞书机器人",
    "Webhook 地址": "飞书自定义机器人的 Webhook 地址",
    "签名密钥（可选）": "飞书机器人安全设置中的签名密钥",
    "交易推送": "开仓/平仓时推送交易信息",
    "异动推送": "市场异动（放量/大涨大跌）时推送告警",
    "原密码": "当前登录密码",
    "新密码": "设置的新密码，至少 6 位",
    "确认新密码": "再次输入新密码，保持一致",
    "模拟盘初始资金": "模拟盘的起始虚拟资金",
    "数据库路径": "本地 SQLite 数据库文件路径",
    "指标": "控制图表上显示的指标：MA 均线 / BOLL 布林带 / RSI / MACD / 交易点标记",
  };

  function autoTips() {
    const keys = Object.keys(TIP_DICT).sort((x, y) => y.length - x.length);
    document.querySelectorAll(".field label, .ctrl-label").forEach((lb) => {
      if (lb.querySelector(".tip")) return;
      const txt = (lb.textContent || "").trim();
      if (!txt) return;
      for (let i = 0; i < keys.length; i++) {
        if (txt.startsWith(keys[i])) {
          const span = document.createElement("span");
          span.className = "tip";
          span.setAttribute("data-tip", TIP_DICT[keys[i]]);
          span.textContent = "?";
          lb.appendChild(span);
          break;
        }
      }
    });
  }

  function initTips() {
    if (window.__qxTipInit) return;
    window.__qxTipInit = true;
    let tipEl = null;
    document.addEventListener("mouseover", (e) => {
      const t = e.target && e.target.closest ? e.target.closest(".tip") : null;
      if (!t) { if (tipEl) tipEl.style.display = "none"; return; }
      if (!tipEl) { tipEl = document.createElement("div"); tipEl.id = "qx-tip"; document.body.appendChild(tipEl); }
      tipEl.textContent = t.getAttribute("data-tip") || "";
      tipEl.style.display = "block";
      const r = t.getBoundingClientRect();
      const w = tipEl.offsetWidth || 260;
      let left = r.left + r.width / 2 - w / 2;
      left = Math.max(8, Math.min(left, window.innerWidth - w - 8));
      let top = r.bottom + 10;
      if (top + tipEl.offsetHeight > window.innerHeight - 8) top = r.top - tipEl.offsetHeight - 10;
      tipEl.style.left = left + "px";
      tipEl.style.top = top + "px";
    });
    document.addEventListener("mouseout", (e) => {
      if (e.target && e.target.closest && e.target.closest(".tip") && tipEl) tipEl.style.display = "none";
    });
    let timer = null;
    new MutationObserver(() => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => { try { autoTips(); professionalize(); } catch (e) {} }, 120);
    }).observe(document.body, { childList: true, subtree: true });
    autoTips();
  }


  // ---------- 专业界面：emoji 清理 + 标题图标 ----------
  const EMOJI_RE = /[\u200C-\u200D\u2190-\u21FF\u2300-\u27FF\u2B00-\u2BFF\u{1F000}-\u{1FAFF}\uFE0F]/gu;
  const ICON_SVG = {
    "🧠": '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/>',
    "🖱️": '<rect x="6" y="3" width="12" height="18" rx="6"/><path d="M12 3v6"/>',
    "📡": '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    "🛡️": '<path d="M12 3l7 3v5c0 5-3.5 8.5-7 10-3.5-1.5-7-5-7-10V6z"/>',
    "💵": '<rect x="3" y="6" width="18" height="14" rx="2"/><path d="M3 10h18"/><circle cx="16.5" cy="15" r="1"/>',
    "⚡": '<path d="M13 2L4 14h6l-1 8 9-12h-6z"/>',
    "🕘": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "📄": '<path d="M14 3H6a2 2 0 00-2 2v14a2 2 0 002 2h12a2 2 0 002-2V9z"/><path d="M14 3v6h6"/><path d="M8 13h8M8 17h5"/>',
    "🤖": '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="10" y="10" width="4" height="4"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
    "📦": '<path d="M21 8l-9-5-9 5v8l9 5 9-5z"/><path d="M3 8l9 5 9-5M12 13v8"/>',
    "🏆": '<path d="M8 4h8v5a4 4 0 01-8 0z"/><path d="M8 5H4v2a3 3 0 003 3h1M16 5h4v2a3 3 0 01-3 3h-1M12 13v3M9 20h6M10 16h4v4h-4z"/>',
    "🔍": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
    "📜": '<path d="M8 6h13M8 12h13M8 18h13"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/>',
    "✏️": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/>',
    "✏": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/>',
    "✍️": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/>',
    "✍": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/>',
    "🧬": '<path d="M8 3c3.5 5 3.5 13 0 18M16 3c-3.5 5-3.5 13 0 18M6 9h12M6 15h12"/>',
    "📊": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    "💻": '<path d="M8 9l-3 3 3 3M16 9l3 3-3 3M13 6l-2 12"/>',
    "💾": '<path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/><path d="M17 21v-8H7v8M7 3v5h8"/>',
    "📋": '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4a3 3 0 016 0M9 9h6M9 13h6M9 17h4"/>',
    "📖": '<path d="M4 19.5A2.5 2.5 0 016.5 17H20V3H6.5A2.5 2.5 0 004 5.5z"/><path d="M4 19.5A2.5 2.5 0 006.5 22H20v-5"/>',
    "🔬": '<path d="M9 3h6M10 3v6l-5.5 9.5A2 2 0 006.2 21h11.6a2 2 0 001.7-2.5L14 9V3"/><path d="M7.5 15h9"/>',
    "🧪": '<path d="M9 3h6M10 3v6l-5.5 9.5A2 2 0 006.2 21h11.6a2 2 0 001.7-2.5L14 9V3"/><path d="M7.5 15h9"/>',
    "🌐": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a15 15 0 010 18M12 3a15 15 0 000 18"/>',
    "🔐": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 018 0v4"/>',
    "📣": '<path d="M6 8a6 6 0 0112 0c0 7 2 8 2 8H4s2-1 2-8"/><path d="M10 20a2 2 0 004 0"/>',
    "⚙️": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.2 2.2M16.9 16.9l2.2 2.2M19.1 4.9l-2.2 2.2M7.1 16.9l-2.2 2.2"/>',
    "⚙": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.2 2.2M16.9 16.9l2.2 2.2M19.1 4.9l-2.2 2.2M7.1 16.9l-2.2 2.2"/>',
    "📅": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 10h18"/>',
    "🔑": '<circle cx="8" cy="15" r="4"/><path d="M11 12l8-8M16 7l3 3M14 9l2 2"/>',
    "🔌": '<path d="M9 7V3M15 7V3M6 7h12v4a6 6 0 01-12 0zM12 17v4"/>',
    "💡": '<path d="M9 18h6M10 21h4M12 3a6 6 0 00-3.5 10.9c.6.5 1 1.4 1 2.1h5c0-.7.4-1.6 1-2.1A6 6 0 0012 3z"/>',
    "⟳": '<path d="M21 12a9 9 0 11-2.6-6.3"/><path d="M21 3v6h-6"/>',
    "🚀": '<path d="M12 15c-2 0-4-1-5-3 1-4 4-7 9-9 0 5-2 9-4 12z"/><path d="M9 12c-2 1-3 3-3 6 3 0 5-1 6-3"/><circle cx="14.5" cy="9.5" r="1.5"/>',
    "🧩": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    "↔": '<path d="M8 3L4 7l4 4M4 7h16M16 21l4-4-4-4M20 17H4"/>',
    "📥": '<path d="M12 3v12M7 10l5 5 5-5M4 21h16"/>',
    "📂": '<path d="M3 7a2 2 0 012-2h4l2 3h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2z"/>',
    "🗑": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/>',
    "🧾": '<path d="M5 3h14v18l-2-1.5-2 1.5-2-1.5-2 1.5-2-1.5-2 1.5z"/><path d="M9 8h6M9 12h6M9 16h4"/>',
    "📈": '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    "📉": '<path d="M3 7l6 6 4-4 8 8"/><path d="M21 11v6h-6"/>',
    "🔥": '<path d="M12 3c1 3-3 5-3 8a3 3 0 006 0c0-1-.5-2-1-3 2 1 4 3 4 6a6 6 0 11-12 0c0-4 4-8 6-11z"/>',
    "💥": '<path d="M13 2L4 14h6l-1 8 9-12h-6z"/>',
    "🚨": '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18h.01"/>',
    "⚠️": '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18h.01"/>',
    "⚠": '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18h.01"/>',
    "🏅": '<circle cx="12" cy="15" r="5"/><path d="M9 11L6 3h12l-3 8"/>',
    "🥇": '<circle cx="12" cy="15" r="5"/><path d="M9 11L6 3h12l-3 8"/>',
    "🥈": '<circle cx="12" cy="15" r="5"/><path d="M9 11L6 3h12l-3 8"/>',
    "🥉": '<circle cx="12" cy="15" r="5"/><path d="M9 11L6 3h12l-3 8"/>',
    "📝": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/>',
    "🔔": '<path d="M6 8a6 6 0 0112 0c0 7 2 8 2 8H4s2-1 2-8"/><path d="M10 20a2 2 0 004 0"/>',
    "🛠": '<path d="M14.7 6.3a5 5 0 00-6.6 6L3 17.4V21h3.6l5.1-5.1a5 5 0 006-6.6l-3 3-2.4-.6-.6-2.4z"/>',
    "🔁": '<path d="M21 12a9 9 0 11-2.6-6.3"/><path d="M21 3v6h-6"/>',
    "🕐": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "📌": '<path d="M12 3l7 7-2 2-5-1-4 4-2 2-1-1 2-2 4-4-1-5z"/>',
    "🔎": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
    "✅": '<path d="M20 6L9 17l-5-5"/>',
    "❌": '<path d="M18 6L6 18M6 6l12 12"/>',
    "⏳": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "🟢": '<circle cx="12" cy="12" r="5" fill="currentColor" stroke="none"/>',
    "🔴": '<circle cx="12" cy="12" r="5" fill="currentColor" stroke="none"/>',
    "⚪": '<circle cx="12" cy="12" r="5" fill="currentColor" stroke="none"/>',
  };

  function stripEmoji(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(n) {
        const p = n.parentElement;
        if (!p || !p.closest) return NodeFilter.FILTER_REJECT;
        if (p.closest(".CodeMirror, textarea, input, pre, code, .tip, .ql-editor")) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((n) => {
      if (EMOJI_RE.test(n.nodeValue)) {
        n.nodeValue = n.nodeValue.replace(EMOJI_RE, "").replace(/\s{2,}/g, " ").trim();
      }
    });
  }

  function iconifyTitles(root) {
    (root.querySelectorAll ? root.querySelectorAll(".card-title, .section-title, .stat-label") : []).forEach((el) => {
      if (el.querySelector(".ti")) return;
      const first = el.firstChild;
      if (!first || first.nodeType !== 3) return;
      const m = first.nodeValue.match(EMOJI_RE);
      if (!m) return;
      const icon = ICON_SVG[m[0]];
      if (!icon) return;
      const span = document.createElement("span");
      span.className = "ti";
      span.innerHTML = icon;
      el.insertBefore(span, first);
      first.nodeValue = first.nodeValue.replace(EMOJI_RE, "").replace(/^\s+/, "");
    });
  }

  function professionalize() {
    if (!document.body) return;
    iconifyTitles(document.body);
    stripEmoji(document.body);
  }

  return { pages, register, go, toast, initClock, checkHealth, initAuth, showLogin, hideLogin, autoTips, initTips, professionalize, confirmDialog, isStreaming, communityDialog, get current() { return current; } };
})();
