"""生成单文件 HTML 报告。"""

from html import escape

from .experiment import AB_SQL, two_proportion_z

CSS = """
:root { --text:#0f172a; --muted:#64748b; --border:#e2e8f0; --accent:#4f46e5; --bg:#f8fafc; }
* { box-sizing:border-box; }
body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif; background:var(--bg); color:var(--text); }
.wrap { max-width:1120px; margin:0 auto; padding:30px 22px 48px; }
h1 { margin:0 0 6px; font-size:1.55rem; } h2 { font-size:1.02rem; margin:30px 0 12px; }
.meta { color:var(--muted); font-size:0.86rem; line-height:1.7; }
.badge { display:inline-block; margin-left:8px; padding:1px 8px; border-radius:999px; background:#fef3c7; color:#92400e; font-size:0.74rem; }
.grid { display:grid; gap:14px; } .g4 { grid-template-columns:repeat(4,1fr); } .g2 { grid-template-columns:1fr 1fr; } .g3 { grid-template-columns:repeat(3,1fr); }
@media (max-width:860px) { .g4,.g2,.g3 { grid-template-columns:1fr; } }
.card { background:#fff; border:1px solid var(--border); border-radius:12px; padding:16px; }
.kpi .label { color:var(--muted); font-size:0.78rem; } .kpi .value { font-size:1.45rem; font-weight:700; margin-top:4px; } .kpi .sub { color:var(--muted); font-size:0.76rem; margin-top:3px; }
table { width:100%; border-collapse:collapse; font-size:0.82rem; }
th, td { text-align:left; padding:7px 8px; border-bottom:1px solid var(--border); vertical-align:middle; }
th { color:var(--muted); font-weight:600; } td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
.bar { height:8px; border-radius:4px; background:var(--accent); }
.tier { display:inline-block; min-width:30px; text-align:center; font-weight:700; font-size:0.78rem; padding:2px 6px; border-radius:6px; color:#fff; }
.t-Sp { background:#7c3aed; } .t-S { background:#4f46e5; } .t-A { background:#0891b2; } .t-B { background:#64748b; } .t-C { background:#cbd5e1; color:#334155; }
.stack { display:flex; height:16px; border-radius:5px; overflow:hidden; background:#f1f5f9; margin:8px 0 6px; }
.legend { display:flex; flex-wrap:wrap; gap:4px 12px; font-size:0.74rem; color:var(--muted); }
.legend i { display:inline-block; width:9px; height:9px; border-radius:2px; margin-right:4px; }
.muted { color:var(--muted); font-size:0.78rem; line-height:1.6; }
.good { color:#047857; font-weight:600; } .flat { color:#b45309; font-weight:600; }
pre { background:#0f172a; color:#e2e8f0; padding:12px; border-radius:8px; font-size:0.72rem; overflow:auto; margin:10px 0 0; }
footer { margin-top:36px; color:var(--muted); font-size:0.78rem; }
"""

COLORS = ["#4f46e5", "#7c3aed", "#0891b2", "#059669", "#d97706", "#db2777", "#475569"]


def pct(v: float, digits: int = 1) -> str:
    return f"{v:.{digits}%}"


def tier_badge(t: str) -> str:
    return f'<span class="tier t-{t.replace("+", "p")}">{t}</span>'


def dims_table(cfg: dict) -> str:
    rows = []
    max_w = max(d["weight"] for d in cfg["dimensions"])
    for d in cfg["dimensions"]:
        w = d["weight"]
        bar = f'<div class="bar" style="width:{w / max_w * 100:.0f}%"></div>' if w else '<span class="muted">不计分</span>'
        rows.append(f"<tr><td><strong>{d['name']}</strong></td><td class='num'>{w:.2f}</td><td style='width:28%'>{bar}</td>"
                    f"<td class='muted'>{escape(d['note'])}</td></tr>")
    return "".join(rows)


def funnel_table(funnel: list[dict], cfg: dict) -> str:
    strategies = {t["name"]: t["strategy"] for t in cfg["tiers"]}
    rows = []
    for r in funnel:
        c = r["contacted"] or 1
        rows.append(
            f"<tr><td>{tier_badge(r['tier'])}</td><td class='muted'>{strategies[r['tier']]}</td>"
            f"<td class='num'>{r['lead']:,}</td><td class='num'>{r['contacted']:,}</td>"
            f"<td class='num'>{pct(r['replied'] / c)}</td><td class='num'>{pct(r['interview'] / c)}</td>"
            f"<td class='num'>{pct(r['offer'] / c)}</td></tr>")
    return "".join(rows)


def explain_cards(examples: list, cfg: dict) -> str:
    names = {d["key"]: d["name"] for d in cfg["dimensions"]}
    keys = [d["key"] for d in cfg["dimensions"] if d["weight"] > 0]
    legend = "".join(f'<span><i style="background:{COLORS[i]}"></i>{names[k]}</span>' for i, k in enumerate(keys))
    cards = []
    for s in examples:
        segs = "".join(
            f'<div style="width:{s.contributions[k]}%;background:{COLORS[i]}" title="{names[k]} +{s.contributions[k]:.1f}"></div>'
            for i, k in enumerate(keys))
        feats = " · ".join(f"{names[k]} {'缺失' if s.features[k] is None else int(s.features[k])}" for k in keys)
        cards.append(
            f"<div class='card'><div style='display:flex;justify-content:space-between;align-items:center'>"
            f"<strong>{s.candidate_id}</strong><span>{tier_badge(s.tier)} <b>{s.total:.1f}</b> 分</span></div>"
            f"<div class='stack'>{segs}</div><div class='muted'>{escape(s.reason)}</div>"
            f"<div class='muted' style='margin-top:6px'>{feats}</div>"
            f"<div class='muted' style='margin-top:6px'>跟进策略：<b>{escape(s.strategy)}</b></div></div>")
    return f"<div class='grid g3'>{''.join(cards)}</div><div class='legend' style='margin-top:10px'>{legend}</div>"


def ties_table(acc: dict) -> str:
    rows = []
    for mode, label in (("binary", "单一标签：本科是否在本地"), ("gradient", "四因子梯度打分")):
        a = acc[mode]
        tp, fp, fn, tn = a["matrix"]
        rows.append(f"<tr><td>{label}</td><td class='num'><b>{pct(a['accuracy'])}</b></td>"
                    f"<td class='num'>{pct(a['miss_rate'])}</td><td class='num'>{pct(a['false_rate'])}</td>"
                    f"<td class='num muted'>{tp} / {fp} / {fn} / {tn}</td></tr>")
    return "".join(rows)


def ab_section(ab: dict, layers: dict) -> tuple[str, dict]:
    c, t = ab["control"], ab["treatment"]
    metrics = [("回复率（回复 / 触达）", "replied"), ("面试率（面试 / 触达）", "interview"), ("Offer 率（Offer / 触达）", "offer")]
    rows, stats = [], {}
    for label, key in metrics:
        z, p = two_proportion_z(c[key], c["contacted"], t[key], t["contacted"])
        rc, rt = c[key] / c["contacted"], t[key] / t["contacted"]
        verdict = '<span class="good">显著提升</span>' if p < 0.05 and z > 0 else '<span class="flat">不显著</span>'
        rows.append(f"<tr><td>{label}</td><td class='num'>{pct(rc)}</td><td class='num'>{pct(rt)}</td>"
                    f"<td class='num'>{(rt - rc) * 100:+.1f}pp</td><td class='num'>{z:.2f}</td><td class='num'>{p:.4f}</td><td>{verdict}</td></tr>")
        stats[key] = (rc, rt, p)
    layer_line = (f"纯对照 {layers['control']:,} 人 · 纯实验 {layers['treatment']:,} 人 · "
                  f"混合样本 <b>{layers['mixed']:,}</b> 人（重复导入，同时出现在两组，不参与对比）")
    noeffect = 1 - (1 - stats["replied"][1]) / (1 - stats["replied"][0])
    html = f"""
  <div class="card">
    <div class="muted">{layer_line}</div>
    <table style="margin-top:8px">
      <thead><tr><th>指标</th><th class="num">对照组</th><th class="num">实验组</th><th class="num">差值</th><th class="num">z</th><th class="num">p</th><th>结论</th></tr></thead>
      <tbody>{rows[0]}{rows[1]}{rows[2]}</tbody></table>
    <p class="muted">两组招聘人力相同，各自只跟进组内得分前 30% 的线索；对照组触达 {c['contacted']:,} 人，实验组 {t['contacted']:,} 人。
    实验组无效跟进（触达后无回复）减少 {noeffect:.0%}。回复率显著提升，但 Offer 率差异不显著：
    Offer 主要取决于岗位匹配度而非回流意向，地域关联度只该影响「先联系谁」，不该被当成录用依据。</p>
  </div>"""
    return html, stats


def render(*, n: int, cfg: dict, funnel: list[dict], examples: list, acc: dict,
           ab: dict, layers: dict, bench: dict, tiers: dict) -> str:
    ab_html, stats = ab_section(ab, layers)
    rc, rt, p = stats["replied"]
    tier_line = " · ".join(f"{k} {v:,}" for k, v in tiers.items())
    plan = "\n".join(bench["plan"])
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Explainable Talent Scoring · 可解释的八维人才评估</title><style>{CSS}</style></head>
<body><div class="wrap">
  <h1>Explainable Talent Scoring · 可解释的八维人才评估</h1>
  <div class="meta">线索池 → 八维特征 → 可配置加权评分 → S+/S/A/B/C 分层 → 差异化跟进 → AB 实验验证
    <span class="badge">模拟数据，全部虚构</span></div>

  <div class="grid g4" style="margin-top:20px">
    <div class="card kpi"><div class="label">量化评分</div><div class="value">{n:,} 人</div><div class="sub">{tier_line}</div></div>
    <div class="card kpi"><div class="label">回流意向识别准确率</div><div class="value">{pct(acc['binary']['accuracy'])} → {pct(acc['gradient']['accuracy'])}</div><div class="sub">单一标签 → 四因子梯度</div></div>
    <div class="card kpi"><div class="label">AB 实验 · 回复率</div><div class="value">{pct(rc)} → {pct(rt)}</div><div class="sub">双比例 z 检验 p = {p:.4f}</div></div>
    <div class="card kpi"><div class="label">AB 分析查询耗时</div><div class="value">{bench['before_ms'] / 1000:.1f}s → {bench['after_ms']:.0f}ms</div><div class="sub">补联合索引后（本机实测）</div></div>
  </div>

  <h2>八维度 · 专家加权（config/scoring.toml）</h2>
  <div class="card"><table>
    <thead><tr><th>维度</th><th class="num">权重</th><th></th><th>说明</th></tr></thead>
    <tbody>{dims_table(cfg)}</tbody></table>
    <p class="muted">不用机器学习黑盒：每个候选人的总分都能拆回到维度贡献，业务方可以直接改权重和分层阈值。
    S+ 除总分外还要求赛道关联度 ≥ 60、顶会论文 ≥ 50；缺失 ≥ {cfg['rules']['max_missing']} 个维度直接判 C，补全信息后复评。</p>
  </div>

  <h2>每个分数都能解释</h2>
  {explain_cards(examples, cfg)}

  <h2>分层漏斗（第 1 轮：按分层策略跟进全量线索）</h2>
  <div class="card"><table>
    <thead><tr><th>层级</th><th>跟进策略</th><th class="num">线索</th><th class="num">触达</th><th class="num">回复率</th><th class="num">面试率</th><th class="num">Offer 率</th></tr></thead>
    <tbody>{funnel_table(funnel, cfg)}</tbody></table>
    <p class="muted">转化率均以「触达」为分母。层级越高转化越好，说明分层对跟进优先级有区分度。</p>
  </div>

  <h2 id="ties">地域关联度：单一标签 vs 四因子梯度</h2>
  <div class="grid g2">
    <div class="card"><table>
      <thead><tr><th>算法</th><th class="num">准确率</th><th class="num">漏判率</th><th class="num">误判率</th><th class="num">TP / FP / FN / TN</th></tr></thead>
      <tbody>{ties_table(acc)}</tbody></table></div>
    <div class="card muted">
      旧做法只看一个 0/1 标签（本科是否在本地），大量「本地本科、长期在海外」和「海外本科、已回本地」的人被判错。
      梯度打分把常驻地区（{cfg['ties']['region']}）、本科院校（{cfg['ties']['undergrad']}）、本地导师（{cfg['ties']['mentor']}）、
      本地项目（{cfg['ties']['project']}）加权成 0–100 分，≥ {cfg['ties']['threshold']} 视为有回流意向。<br/><br/>
      准确率用模拟数据里的真实意向离线评估，算法本身看不到这个标签。
    </div>
  </div>

  <h2>AB 实验（第 2 轮：地域关联度换成梯度打分，其余维度不变）</h2>
  {ab_html}

  <h2>SQL：NOT EXISTS 排他分组 + 联合索引</h2>
  <div class="card">
    <div class="muted">AB 分析需要对每个人做「是否同时在两组」和「各阶段是否发生」的关联子查询。关闭 SQLite 自动索引时全表扫描耗时
    <b>{bench['before_ms'] / 1000:.1f}s</b>；补上 assignments(candidate_id, round, grp) 与 events(candidate_id, round, stage)
    两个覆盖索引后降到 <b>{bench['after_ms']:.1f}ms</b>。</div>
    <pre>{escape(AB_SQL.strip())}</pre>
    <pre>-- EXPLAIN QUERY PLAN（建索引后）
{escape(plan)}</pre>
  </div>

  <footer>由 run.py 生成 · 权重与阈值见 config/scoring.toml</footer>
</div></body></html>
"""
