"""生成模拟线索池、评分、跑两轮跟进模拟，输出 docs/index.html 与 docs/scores.csv。"""

import csv
from collections import Counter
from pathlib import Path

from talentscore.experiment import ab_result, funnel_by_tier, index_benchmark, layers, simulate
from talentscore.report import render
from talentscore.scoring import load_config, ties_accuracy, tier_names
from talentscore.synth import generate

ROOT = Path(__file__).resolve().parent
PARAMS = {"n": 6000, "seed": 42, "sim_seed": 11}


def pick_examples(scores: dict) -> list:
    ordered = sorted(scores.values(), key=lambda s: s.candidate_id)
    top = next(s for s in ordered if s.tier == "S+")
    mid = next(s for s in ordered if s.tier == "A" and not s.missing)
    low = next(s for s in ordered if s.tier == "C" and len(s.missing) >= 3)
    return [top, mid, low]


def main() -> None:
    cfg = load_config()
    people = generate(PARAMS["n"], PARAMS["seed"])
    sim = simulate(people, cfg, PARAMS["sim_seed"])
    tiers = Counter(s.tier for s in sim.scores.values())
    ordered_tiers = {t: tiers[t] for t in tier_names(cfg)}

    print("正在测 SQL 索引前后耗时（无索引版本需要几秒）…")
    bench = index_benchmark(sim.db)
    acc = ties_accuracy(people, cfg)
    ab = ab_result(sim.db)
    lay = layers(sim.db)
    funnel = funnel_by_tier(sim.db, tier_names(cfg))

    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "index.html").write_text(render(
        n=len(people), cfg=cfg, funnel=funnel, examples=pick_examples(sim.scores), acc=acc,
        ab=ab, layers=lay, bench=bench, tiers=ordered_tiers), encoding="utf-8")

    keys = [d["key"] for d in cfg["dimensions"]]
    with open(docs / "scores.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["candidate_id", "total", "tier", "strategy", "reason", *keys])
        for s in sorted(sim.scores.values(), key=lambda s: -s.total):
            w.writerow([s.candidate_id, s.total, s.tier, s.strategy, s.reason, *(s.features[k] for k in keys)])

    c, t = ab["control"], ab["treatment"]
    print(f"分层：{ordered_tiers}")
    print(f"回流意向识别：{acc['binary']['accuracy']:.1%} → {acc['gradient']['accuracy']:.1%}")
    print(f"AB 回复率：{c['replied'] / c['contacted']:.1%} → {t['replied'] / t['contacted']:.1%}，混合样本 {lay['mixed']} 人已排除")
    print(f"SQL：{bench['before_ms']:.0f}ms → {bench['after_ms']:.1f}ms")
    print(f"报告 → {docs / 'index.html'}")


if __name__ == "__main__":
    main()
