/* ============ API 客户端与格式化工具 ============ */
window.API = (() => {
  const TOKEN_KEY = "quantx_token";
  function getToken() { return localStorage.getItem(TOKEN_KEY); }
  function setToken(token) {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  }
  async function request(method, path, body) {
    const opts = { method, headers: { "Content-Type": "application/json" } };
    const token = getToken();
    if (token) opts.headers["Authorization"] = "Bearer " + token;
    if (body !== undefined) opts.body = JSON.stringify(body);
    const res = await fetch(path, opts);
    let data = null;
    try { data = await res.json(); } catch (e) { /* 非 JSON */ }
    if (res.status === 401 && path !== "/api/auth/login" && path !== "/api/auth/status") {
      setToken(null);
      window.dispatchEvent(new CustomEvent("quantx:unauthorized"));
      const msg = (data && data.detail) || "登录已过期，请重新登录";
      throw new Error(msg);
    }
    if (!res.ok) {
      const msg = (data && (data.detail || data.message)) || "请求失败 (" + res.status + ")";
      throw new Error(msg);
    }
    return data;
  }
  return {
    get: (p) => request("GET", p),
    post: (p, b) => request("POST", p, b),
    del: (p) => request("DELETE", p),
    getToken,
    setToken,
  };
})();

window.FMT = {
  price(v, digits) {
    if (v === null || v === undefined || Number.isNaN(v)) return "--";
    const d = digits ?? (v >= 1000 ? 2 : v >= 1 ? 4 : 6);
    return Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  },
  num(v, digits = 2) {
    if (v === null || v === undefined || Number.isNaN(v)) return "--";
    return Number(v).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  },
  pct(v, digits = 2) {
    if (v === null || v === undefined || Number.isNaN(v)) return "--";
    return (v * 100).toFixed(digits) + "%";
  },
  pctSigned(v, digits = 2) {
    if (v === null || v === undefined || Number.isNaN(v)) return "--";
    const s = v >= 0 ? "+" : "";
    return s + (v * 100).toFixed(digits) + "%";
  },
  usd(v) {
    if (v === null || v === undefined || Number.isNaN(v)) return "--";
    return "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  },
  cls(v) { return v > 0 ? "pos" : v < 0 ? "neg" : ""; },
  time(ts) {
    if (!ts) return "--";
    const d = new Date(ts);
    const p = (n) => String(n).padStart(2, "0");
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
  },
  shortId(id) { return id ? id.slice(0, 8) : "--"; },
};

window.EL = (html) => {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
};
