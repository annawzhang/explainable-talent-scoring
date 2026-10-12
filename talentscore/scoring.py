"""八维特征、加权评分与分层。每一分都能追溯到具体维度。"""

import math
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .synth import REGIONS, Candidate

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "scoring.toml"


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    scored = sum(d["weight"] for d in cfg["dimensions"])
    if abs(scored - 1) > 1e-6:
        raise ValueError(f"计分维度权重合计应为 1，当前 {scored:.3f}")
    if abs(sum(v for k, v in cfg["ties"].items() if k != "threshold") - 1) > 1e-6:
        raise ValueError("地域关联度四因子权重合计应为 1")
    return cfg


def ties_gradient(c: Candidate, cfg: dict) -> float:
    t = cfg["ties"]
    return 100 * (t["region"] * REGIONS[c.region] + t["undergrad"] * c.undergrad_local
                  + t["mentor"] * c.local_mentor + t["project"] * c.local_project)


def ties_binary(c: Candidate) -> float:
    """旧做法：只看「本科是否在本地」一个标签。"""
    return 100.0 if c.undergrad_local else 0.0


def features(c: Candidate, cfg: dict, ties_mode: str = "gradient") -> dict[str, float | None]:
    def opt(v, f):
        return None if v is None else round(min(100.0, max(0.0, f(v))), 1)

    mentor = None
    if c.mentor_tier is not None and c.mentor_links is not None:
        mentor = round(min(100.0, c.mentor_tier * 25 + min(c.mentor_links, 10) * 2.5), 1)
    return {
        "track": opt(c.track_overlap, lambda v: v * 100),
        "mentor": mentor,
        "local": opt(c.local_projects, lambda v: v / 5 * 100),
        "referral": opt(c.internal_refs, lambda v: v * 30),
        "engineering": opt(c.github_stars, lambda v: math.log10(1 + v) / math.log10(1 + 5000) * 100),
        "papers": opt(c.top_papers, lambda v: v * 22 + c.first_author * 12),
        "ties": round(ties_gradient(c, cfg) if ties_mode == "gradient" else ties_binary(c), 1),
        "citations": opt(c.citations, lambda v: math.log10(1 + v) / math.log10(1 + 20000) * 100),
    }


@dataclass
class Score:
    candidate_id: str
    total: float
    tier: str
    strategy: str
    contributions: dict[str, float]
    features: dict[str, float | None]
    missing: list[str]
    reason: str


def score(c: Candidate, cfg: dict, ties_mode: str = "gradient") -> Score:
    feats = features(c, cfg, ties_mode)
    weights = {d["key"]: d["weight"] for d in cfg["dimensions"]}
    missing = [k for k, w in weights.items() if w > 0 and feats[k] is None]
    # 缺失维度按 0 计，不做插补：宁可低估，交给「补全后复评」
    contributions = {k: round(w * (feats[k] or 0), 2) for k, w in weights.items() if w > 0}
    total = round(sum(contributions.values()), 1)

    if len(missing) >= cfg["rules"]["max_missing"]:
        c_tier = cfg["tiers"][-1]
        return Score(c.id, total, c_tier["name"], c_tier["strategy"], contributions, feats, missing,
                     f"缺失 {len(missing)} 个维度，信息不足")

    for tier in cfg["tiers"]:
        if total < tier["min"]:
            continue
        unmet = [k for k, floor in tier.get("require", {}).items() if (feats[k] or 0) < floor]
        if unmet:
            continue
        top = sorted(contributions.items(), key=lambda kv: -kv[1])[:2]
        names = {d["key"]: d["name"] for d in cfg["dimensions"]}
        reason = "主要得分来自 " + "、".join(f"{names[k]}（+{v:.1f}）" for k, v in top)
        return Score(c.id, total, tier["name"], tier["strategy"], contributions, feats, missing, reason)
    raise AssertionError("最后一档 min 应为 0")


def tier_names(cfg: dict) -> list[str]:
    return [t["name"] for t in cfg["tiers"]]


def ties_accuracy(people: list[Candidate], cfg: dict) -> dict[str, dict]:
    """两种地域关联度算法识别「回流意向」的准确率与漏判率。"""
    threshold = cfg["ties"]["threshold"]
    out = {}
    for mode, fn in (("binary", ties_binary), ("gradient", lambda c: ties_gradient(c, cfg))):
        tp = fp = tn = fn_ = 0
        for c in people:
            pred = fn(c) >= threshold
            if pred and c.intent:
                tp += 1
            elif pred:
                fp += 1
            elif c.intent:
                fn_ += 1
            else:
                tn += 1
        total = tp + fp + tn + fn_
        out[mode] = {
            "accuracy": (tp + tn) / total,
            "miss_rate": fn_ / max(1, tp + fn_),
            "false_rate": fp / max(1, fp + tn),
            "matrix": (tp, fp, fn_, tn),
        }
    return out
