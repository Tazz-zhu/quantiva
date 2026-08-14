"""生成独立的 HTML 分析报告（自包含样式，可离线打开）。"""
from __future__ import annotations

import html
from datetime import datetime

REASON_LABELS = {"signal": "信号", "stop_loss": "止损", "take_profit": "止盈", "eod": "期末"}


def _fmt_pct(v, signed=False):
    if v is None:
        return "--"
    s = "+" if signed and v > 0 else ""
    return s + format(v * 100, ".2f") + "%"


def _fmt_num(v, digits=2):
    if v is None:
        return "--"
    return format(v, ",." + str(digits) + "f")


def _short_time(v):
    try:
        return str(v)[:16].replace("T", " ")
    except Exception:
        return str(v)


def _svg_line(points, width=860, height=240, color="#22d3ee", fill=None):
    if len(points) < 2:
        return '<svg viewBox="0 0 ' + str(width) + " " + str(height) + '" style="width:100%;background:#0b1220"></svg>'
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    pad = 10
    if xmax - xmin < 1e-9:
        xmax = xmin + 1
    if ymax - ymin < 1e-9:
        ymax = ymin + 1

    def map_pt(p):
        px = pad + (p[0] - xmin) / (xmax - xmin) * (width - 2 * pad)
        py = height - pad - (p[1] - ymin) / (ymax - ymin) * (height - 2 * pad)
        return format(px, ".1f") + "," + format(py, ".1f")

    pts = " ".join(map_pt(p) for p in points)
    parts = []
    if fill:
        parts.append('<polygon points="' + pts + " " + map_pt((points[-1][0], ymin)) + " " + map_pt((points[0][0], ymin)) + '" fill="' + fill + '" stroke="none"/>')
    parts.append('<polyline points="' + pts + '" fill="none" stroke="' + color + '" stroke-width="2"/>')
    return '<svg viewBox="0 0 ' + str(width) + " " + str(height) + '" style="width:100%;background:#0b1220;border-radius:8px">' + "".join(parts) + "</svg>"


def _bars_svg(values, width=860, height=180):
    if not values:
        return ""
    vmin = min(0.0, min(v for _, v in values))
    vmax = max(0.0, max(v for _, v in values))
    span = (vmax - vmin) or 1.0
    n = len(values)
    bw = max(8, (width - 40) / n - 6)
    zero_y = height - 10 - (0 - vmin) / span * (height - 20)
    parts = ['<line x1="0" y1="' + format(zero_y, ".1f") + '" x2="' + str(width) + '" y2="' + format(zero_y, ".1f") + '" stroke="#5b6478" stroke-width="1"/>']
    for i, (label, v) in enumerate(values):
        x = 20 + i * ((width - 40) / n)
        y = height - 10 - (v - vmin) / span * (height - 20)
        h = abs(y - zero_y)
        color = "#34d399" if v >= 0 else "#f87171"
        parts.append('<rect x="' + format(x, ".1f") + '" y="' + format(min(y, zero_y), ".1f") + '" width="' + format(bw, ".1f") + '" height="' + format(max(h, 1), ".1f") + '" fill="' + color + '" rx="2"/>')
    return '<svg viewBox="0 0 ' + str(width) + " " + str(height) + '" style="width:100%;background:#0b1220;border-radius:8px">' + "".join(parts) + "</svg>"


def _matrix_table(matrix):
    months = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]
    head = "<tr><th>年/月</th>" + "".join("<th>" + m + "</th>" for m in months) + "<th>年度</th></tr>"
    rows = []
    for year in sorted(matrix or {}):
        vals = matrix[year]
        cells = []
        for m in months:
            v = vals.get(m)
            if v is None:
                cells.append("<td class='dim'>-</td>")
            else:
                cls = "pos" if v > 0 else ("neg" if v < 0 else "")
                cells.append("<td class='" + cls + "'>" + format(v * 100, ".1f") + "%</td>")
        yearly = sum(v for v in vals.values() if v is not None)
        ycls = "pos" if yearly > 0 else ("neg" if yearly < 0 else "")
        rows.append("<tr><td><b>" + year + "</b></td>" + "".join(cells) + "<td class='" + ycls + "'><b>" + format(yearly * 100, ".1f") + "%</b></td></tr>")
    return "<table class='matrix'>" + head + "".join(rows) + "</table>"


def _metric(label, value, cls=""):
    return '<div class="metric"><div class="ml">' + label + '</div><div class="mv ' + cls + '">' + value + "</div></div>"


def generate_html_report(payload: dict, strategy_name: str = "", source: str = "", timeframe: str = "1h") -> str:
    """从回测结果 payload 生成独立 HTML 分析报告。"""
    analysis = payload.get("analysis") or {}
    metrics = payload.get("metrics") or {}
    perf = analysis.get("performance", {})
    tr = analysis.get("trades", {})
    ddinfo = analysis.get("drawdown", {})
    trades = payload.get("trades", [])
    symbol = payload.get("symbol", "?")
    t0 = (payload.get("equity_curve") or [[None, 0]])[0][0]
    t1 = (payload.get("equity_curve") or [[None, 0]])[-1][0]

    eq = [(ms / 1000.0, v) for ms, v in payload.get("equity_curve", [])]
    bench = [(ms / 1000.0, v) for ms, v in payload.get("benchmark", [])]
    dd_pts = [(ms / 1000.0, v) for ms, v in payload.get("drawdown", [])]
    months = [(m["month"], m["return"]) for m in analysis.get("monthly_returns", [])]

    def reason_label(r):
        return REASON_LABELS.get(r, r)

    trades_rows = "".join(
        "<tr><td>" + ("多" if t["side"] == "long" else "空") + "</td><td>" + _short_time(t["entry_time"]) + "</td>"
        + "<td>" + format(t["entry_price"], ",.4f") + "</td><td>" + _short_time(t["exit_time"]) + "</td><td>" + format(t["exit_price"], ",.4f") + "</td>"
        + "<td>" + format(t["pnl"], ",.2f") + "</td><td class='" + ("pos" if t["return_pct"] > 0 else "neg") + "'>" + format(t["return_pct"] * 100, ".2f") + "%</td>"
        + "<td>" + reason_label(t["reason"]) + "</td></tr>"
        for t in trades[-500:]
    )
    by_side_rows = "".join(
        "<tr><td>" + ("做多" if side == "long" else "做空") + "</td><td>" + str(s["count"]) + "</td><td>" + format(s["win_rate"] * 100, ".1f") + "%</td>"
        + "<td>" + format(s["total"], ",.2f") + "</td><td>" + format(s["avg"], ",.2f") + "</td></tr>"
        for side, s in (tr.get("by_side") or {}).items()
    )
    by_reason_rows = "".join(
        "<tr><td>" + reason_label(k) + "</td><td>" + str(s["count"]) + "</td><td>" + format(s["win_rate"] * 100, ".1f") + "%</td>"
        + "<td>" + format(s["total"], ",.2f") + "</td></tr>"
        for k, s in (tr.get("by_reason") or {}).items()
    )

    def d(v):
        return datetime.fromtimestamp(v / 1000).strftime("%Y-%m-%d") if v else "?"

    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>回测分析报告 · """ + html.escape(strategy_name) + """</title>
<style>
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; background:#070b14; color:#e6ebf5; margin:0; padding:24px; }
  .wrap { max-width: 980px; margin: 0 auto; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  .sub { color:#8b94a7; font-size: 13px; margin-bottom: 20px; }
  .badges span { display:inline-block; padding:4px 12px; border-radius:999px; background:rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.12); font-size:12px; margin-right:8px; }
  .cards { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:18px 0; }
  .metric { background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.08); border-radius:12px; padding:12px 14px; }
  .ml { font-size:11px; color:#8b94a7; margin-bottom:6px; }
  .mv { font-family:Consolas,monospace; font-size:18px; font-weight:700; }
  .pos { color:#34d399; } .neg { color:#f87171; } .dim { color:#5b6478; }
  h2 { font-size:15px; margin:26px 0 12px; color:#8b94a7; letter-spacing:1px; }
  table { width:100%; border-collapse:collapse; font-size:12.5px; margin:10px 0; }
  th, td { padding:8px 10px; border-bottom:1px solid rgba(255,255,255,.07); text-align:left; font-family:Consolas,monospace; }
  th { color:#8b94a7; font-size:11px; background:rgba(255,255,255,.03); }
  table.matrix td { text-align:center; }
  .box { background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.08); border-radius:12px; padding:14px; margin:10px 0; }
  .footer { color:#5b6478; font-size:11px; margin-top:30px; text-align:center; }
</style></head><body><div class="wrap">
  <h1>📊 回测分析报告</h1>
  <div class="sub">生成时间 """ + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + """</div>
  <div class="badges">
    <span>策略 """ + html.escape(strategy_name) + """</span><span>标的 """ + html.escape(symbol) + """</span>
    <span>周期 """ + timeframe + """</span><span>数据源 """ + html.escape(source or "exchange") + """</span>
    <span>回测区间 """ + d(t0) + " ~ " + d(t1) + """</span>
  </div>

  <div class="cards">
    """ + _metric("总收益率", _fmt_pct(perf.get("total_return"), True), "pos" if (perf.get("total_return") or 0) > 0 else "neg") + """
    """ + _metric("年化收益率", _fmt_pct(perf.get("annual_return"), True), "pos" if (perf.get("annual_return") or 0) > 0 else "neg") + """
    """ + _metric("买入持有", _fmt_pct(perf.get("buy_hold_return"), True)) + """
    """ + _metric("夏普比率", _fmt_num(perf.get("sharpe"))) + """
    """ + _metric("索提诺", _fmt_num(perf.get("sortino"))) + """
    """ + _metric("最大回撤", _fmt_pct(perf.get("max_drawdown")), "neg") + """
    """ + _metric("卡玛比率", _fmt_num(perf.get("calmar"))) + """
    """ + _metric("年化波动", _fmt_pct(perf.get("volatility"))) + """
    """ + _metric("胜率", _fmt_pct(tr.get("win_rate"))) + """
    """ + _metric("盈亏比", _fmt_num(tr.get("profit_factor"))) + """
    """ + _metric("交易次数", str(tr.get("total", 0))) + """
    """ + _metric("仓位暴露", _fmt_pct(analysis.get("exposure"))) + """
  </div>

  <h2>📈 权益曲线（策略 vs 买入持有）</h2>
  <div class="box">""" + _svg_line(eq, fill="rgba(34,211,238,0.15)") + """
    <div style="margin-top:8px">""" + _svg_line(bench, color="#8b94a7") + """</div>
  </div>

  <h2>📉 回撤曲线</h2>
  <div class="box">""" + _svg_line(dd_pts, color="#f87171", height=160) + """</div>

  <h2>📅 月度收益</h2>
  <div class="box">""" + _bars_svg(months) + """</div>
  """ + _matrix_table(analysis.get("monthly_matrix")) + """

  <h2>🧾 交易统计</h2>
  <div class="box">
    <table>
      <tr><th>指标</th><th>数值</th><th>指标</th><th>数值</th></tr>
      <tr><td>平均盈利</td><td class="pos">""" + _fmt_num(tr.get("avg_win")) + """</td><td>平均亏损</td><td class="neg">""" + _fmt_num(tr.get("avg_loss")) + """</td></tr>
      <tr><td>最大单笔盈利</td><td class="pos">""" + _fmt_num(tr.get("max_win")) + """</td><td>最大单笔亏损</td><td class="neg">""" + _fmt_num(tr.get("max_loss")) + """</td></tr>
      <tr><td>平均持仓时长</td><td>""" + _fmt_num(tr.get("avg_holding_hours")) + """ 小时</td><td>总手续费</td><td>""" + _fmt_num(tr.get("total_fees")) + """</td></tr>
      <tr><td>最大连胜</td><td>""" + str(tr.get("streaks", {}).get("max_consecutive_wins", 0)) + """ 笔</td><td>最大连亏</td><td>""" + str(tr.get("streaks", {}).get("max_consecutive_losses", 0)) + """ 笔</td></tr>
    </table>
  </div>

  <h2>📦 按方向 / 按平仓原因</h2>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
    <div class="box"><table><tr><th>方向</th><th>笔数</th><th>胜率</th><th>总盈亏</th><th>平均</th></tr>""" + (by_side_rows or "<tr><td colspan=5 class=dim>无交易</td></tr>") + """</table></div>
    <div class="box"><table><tr><th>原因</th><th>笔数</th><th>胜率</th><th>总盈亏</th></tr>""" + (by_reason_rows or "<tr><td colspan=4 class=dim>无交易</td></tr>") + """</table></div>
  </div>

  <h2>🌊 回撤分析</h2>
  <div class="box">
    <table>
      <tr><th>最大回撤</th><th>回撤次数</th><th>平均回撤</th><th>最长回撤（天）</th><th>当前回撤</th></tr>
      <tr><td class="neg">""" + _fmt_pct(ddinfo.get("max_drawdown")) + """</td><td>""" + str(ddinfo.get("num_drawdowns", 0)) + """</td>
      <td>""" + _fmt_pct(ddinfo.get("avg_drawdown")) + """</td><td>""" + _fmt_num(ddinfo.get("longest_drawdown_days")) + """</td>
      <td>""" + _fmt_pct(ddinfo.get("current_drawdown")) + """</td></tr>
    </table>
  </div>

  <h2>📋 交易明细（最近 """ + str(min(len(trades), 500)) + """ 笔 / 共 """ + str(len(trades)) + """ 笔）</h2>
  <div class="box" style="max-height:420px;overflow:auto">
    <table><tr><th>方向</th><th>开仓时间</th><th>开仓价</th><th>平仓时间</th><th>平仓价</th><th>盈亏</th><th>收益率</th><th>原因</th></tr>
    """ + (trades_rows or "<tr><td colspan=8 class=dim>无交易</td></tr>") + """
    </table>
  </div>

  <div class="footer">Generated by Quantiva · 仅供学习研究，不构成投资建议</div>
</div></body></html>"""
