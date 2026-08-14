/* ============ 主入口 ============ */
(async function () {
  App.state = App.state || { latestResult: null };

  App.initTips();

  window.addEventListener("quantx:unauthorized", () => {
    App.showLogin({ enabled: true, default_password: false });
  });

  // 导航
  document.querySelectorAll(".nav-item").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      App.go(a.dataset.page);
      if (window.innerWidth <= 720) document.body.classList.remove("sidebar-open");
    });
  });

  // 快速启动模拟盘
  document.getElementById("btn-quick-live").addEventListener("click", () => {
    App.go("live");
    const btn = document.getElementById("lv-start");
    if (btn) btn.click();
  });

  // 页面自动刷新
  setInterval(() => {
    const cur = App.current;
    if (cur === "dashboard" && App.pages.dashboard.refresh) App.pages.dashboard.refresh();
    if (cur === "live" && App.pages.live.refresh && !App.isStreaming("live")) App.pages.live.refresh();
    if (cur === "monitor" && App.pages.monitor.refresh && !App.isStreaming("monitor")) App.pages.monitor.refresh();
    if (cur === "evolution" && App.pages.evolution.refresh) App.pages.evolution.refresh();
  }, 4000);

  // ---------- 后台任务全局监控（回测 / 参数优化在后台持续运行） ----------
  const bgBtRunning = new Set();
  const bgEvRunning = new Set();
  function updateNavBadge(id, count) {
    const b = document.getElementById(id);
    if (!b) return;
    b.style.display = count > 0 ? "" : "none";
    b.textContent = count > 99 ? "99+" : String(count);
  }
  async function pollBackgroundJobs() {
    try {
      const jobs = (await API.get("/api/backtest/jobs")).jobs || [];
      const runningIds = jobs.filter((j) => j.status === "running").map((j) => j.id);
      const doneIds = [...bgBtRunning].filter((id) => !runningIds.includes(id));
      bgBtRunning.clear();
      runningIds.forEach((id) => bgBtRunning.add(id));
      updateNavBadge("nav-backtest-badge", runningIds.length);
      if (doneIds.length && App.current !== "backtest") {
        const j = jobs.find((x) => doneIds.includes(x.id));
        if (j) notifyUser("回测完成", (j.strategy || "策略") + " · " + (j.symbol || "") + " " + (j.timeframe || ""));
      }
    } catch (e) { /* 忽略 */ }
    try {
      const jobs = (await API.get("/api/evolution/jobs")).jobs || [];
      const runningIds = jobs.filter((j) => j.status === "running").map((j) => j.id);
      const doneIds = [...bgEvRunning].filter((id) => !runningIds.includes(id));
      bgEvRunning.clear();
      runningIds.forEach((id) => bgEvRunning.add(id));
      updateNavBadge("nav-evolution-badge", runningIds.length);
      if (doneIds.length && App.current !== "evolution") {
        notifyUser("参数优化完成", "最优参数组合已写入迭代日志");
      }
    } catch (e) { /* 忽略 */ }
  }
  setInterval(pollBackgroundJobs, 4000);

  App.initClock();
  App.checkHealth();
  setInterval(App.checkHealth, 15000);

  // 路由 hash
  window.addEventListener("hashchange", () => {
    const name = location.hash.replace("#", "") || "dashboard";
    if (App.pages[name]) App.go(name);
  });
  const authed = await App.initAuth();
  if (authed) {
    // 默认密码安全提醒（全局常驻，改密后自动消失）
    const status = App.state.authStatus || {};
    const banner = document.getElementById("default-pwd-banner");
    if (banner && status.default_password) {
      banner.style.display = "flex";
      document.getElementById("btn-goto-settings").addEventListener("click", () => App.go("settings"));
    }
    const initial = location.hash.replace("#", "") || "dashboard";
    App.go(App.pages[initial] ? initial : "dashboard");
  }

  // ---------- 主题：深色 / 浅色 / 跟随系统 ----------
  function resolveTheme(pref) {
    if (pref === "system") return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
    return pref;
  }
  function applyTheme(pref) {
    const t = resolveTheme(pref);
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("quantx_theme", pref); } catch (e) {}
    const meta = document.querySelector("meta[name=theme-color]");
    if (meta) meta.setAttribute("content", t === "light" ? "#f1f4f9" : "#0a0d13");
    window.dispatchEvent(new CustomEvent("quantx:themechange"));
    const cur = App.current;
    if (App.pages[cur] && App.pages[cur].refresh) App.pages[cur].refresh();
  }
  const themeLabels = { dark: "深色", light: "浅色", system: "跟随系统" };
  const themeBtn = document.getElementById("btn-theme");
  if (themeBtn) {
    themeBtn.addEventListener("click", () => {
      const cur = (() => { try { return localStorage.getItem("quantx_theme") || "dark"; } catch (e) { return "dark"; } })();
      const next = cur === "dark" ? "light" : cur === "light" ? "system" : "dark";
      applyTheme(next);
      App.toast("主题： " + themeLabels[next], "info");
      themeBtn.title = "主题：" + themeLabels[next] + "（点击切换）";
    });
    themeBtn.title = "主题（深色 / 浅色 / 跟随系统）";
  }
  window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => {
    try { if ((localStorage.getItem("quantx_theme") || "dark") === "system") applyTheme("system"); } catch (e) {}
  });

  // ---------- Logo 返回仪表盘 ----------
  const logoHome = document.getElementById("logo-home");
  if (logoHome) logoHome.addEventListener("click", () => App.go("dashboard"));
  const commBtn = document.getElementById("btn-community");
  if (commBtn) commBtn.addEventListener("click", () => App.communityDialog());

  // ---------- 回到顶部 ----------
  const topBtn = document.getElementById("btn-top");
  const contentEl = document.querySelector(".content");
  if (topBtn && contentEl) {
    contentEl.addEventListener("scroll", () => {
      topBtn.style.display = contentEl.scrollTop > 300 ? "" : "none";
    });
    topBtn.addEventListener("click", () => contentEl.scrollTo({ top: 0, behavior: "smooth" }));
  }

  // ---------- 浏览器通知 ----------
  function notifyEnabled() {
    try { return localStorage.getItem("quantx_notify") !== "0"; } catch (e) { return true; }
  }
  function notifyUser(title, body) {
    if (!notifyEnabled() || !("Notification" in window)) return;
    if (Notification.permission === "granted") {
      try { new Notification(title, { body: body, icon: "/static/favicon.svg" }); } catch (e) {}
    }
  }
  document.addEventListener("click", function onceNotify() {
    if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
    document.removeEventListener("click", onceNotify);
  });

  // ---------- 监控未读红点 ----------
  function updateMonitorBadge() {
    const b = document.getElementById("nav-monitor-badge");
    if (!b) return;
    const n = App.state.monitorUnread || 0;
    b.style.display = n > 0 ? "" : "none";
    b.textContent = n > 99 ? "99+" : String(n);
  }
  App.state.monitorUnread = 0;

  // ---------- 全局快速搜索 ----------
  const SEARCH_PAGES = [
    ["仪表盘", "dashboard"], ["行情图表", "chart"], ["策略回测", "backtest"],
    ["策略构建", "custom"], ["市场监控", "monitor"], ["策略进化", "evolution"],
    ["实盘交易", "live"], ["数据管理", "data"], ["系统设置", "settings"],
  ];
  const SEARCH_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT"];
  const searchInput = document.getElementById("global-search");
  const searchResults = document.getElementById("global-search-results");
  if (searchInput && searchResults) {
    function renderSearch(q) {
      const s = (q || "").trim().toLowerCase();
      if (!s) { searchResults.style.display = "none"; return; }
      const items = [];
      SEARCH_PAGES.forEach(([label, page]) => {
        if (label.toLowerCase().includes(s) || page.includes(s)) items.push({ kind: "page", label: "页面 · " + label, value: page });
      });
      SEARCH_SYMBOLS.forEach((sym) => {
        if (sym.toLowerCase().includes(s)) items.push({ kind: "symbol", label: "行情 · " + sym, value: sym });
      });
      if (/^[a-z0-9/-]+$/i.test(s) && s.length >= 3) items.push({ kind: "symbol", label: "行情 · " + s.toUpperCase().replace(/\s+/g, "") + "（自定义）", value: s.toUpperCase().replace(/\s+/g, "") });
      items.splice(8);
      searchResults.innerHTML = items.length ? items.map((it) =>
        '<div class="qs-item" data-kind="' + it.kind + '" data-value="' + it.value + '">' + it.label + '</div>').join("")
        : '<div class="qs-item qs-empty">无匹配结果</div>';
      searchResults.style.display = "block";
    }
    searchInput.addEventListener("input", () => renderSearch(searchInput.value));
    searchInput.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      const first = searchResults.querySelector(".qs-item[data-value]");
      if (first) { first.click(); } else if (searchInput.value.trim()) {
        const sym = searchInput.value.trim().toUpperCase().replace(/\s+/g, "");
        if (sym.includes("/") || sym.length <= 12) { openSearchItem("symbol", sym); }
      }
    });
    searchResults.addEventListener("click", (e) => {
      const item = e.target.closest(".qs-item[data-value]");
      if (item) openSearchItem(item.dataset.kind, item.dataset.value);
    });
    document.addEventListener("click", (e) => {
      if (!e.target.closest("#quick-search")) searchResults.style.display = "none";
    });
    function openSearchItem(kind, value) {
      searchResults.style.display = "none";
      searchInput.value = "";
      if (kind === "page") { App.go(value); return; }
      App.go("chart");
      const pg = App.pages.chart;
      if (pg && pg.setSymbol) pg.setSymbol(value);
    }
  }
})();
