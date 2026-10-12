"""生成虚构的研究人才线索池。

每个候选人有可观测的原始信号，以及两个算法看不到的隐变量：
- intent：是否真的有回流意向（用来评估地域关联度识别准确率）
- fit：与岗位的真实匹配度（驱动后续转化）
"""

import math
import random
from dataclasses import dataclass, field

TRACKS = ["大模型预训练", "多模态", "强化学习", "AI 系统", "AI 安全"]
REGIONS = {"in_region": 1.0, "adjacent": 0.5, "overseas": 0.0}


@dataclass
class Candidate:
    id: str
    track: str
    track_overlap: float | None
    mentor_tier: int | None
    mentor_links: int | None
    local_projects: int | None
    internal_refs: int | None
    github_stars: int | None
    top_papers: int | None
    first_author: int | None
    citations: int | None
    region: str
    undergrad_local: bool
    local_mentor: bool
    local_project: bool
    intent: bool = field(repr=False)
    fit: float = field(repr=False)


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def _maybe(rng: random.Random, value, missing_rate: float):
    return None if rng.random() < missing_rate else value


def generate(n: int = 6000, seed: int = 42, missing_rate: float = 0.06) -> list[Candidate]:
    rng = random.Random(seed)
    people = []
    for i in range(1, n + 1):
        region = rng.choices(list(REGIONS), weights=[0.35, 0.15, 0.50])[0]
        # 本科在本地与当前常驻地相关性很弱：大量本地本科毕业后长期留在海外
        undergrad_local = rng.random() < 0.55
        local_mentor = rng.random() < (0.55 if region != "overseas" else 0.25)
        local_project = rng.random() < (0.50 if region != "overseas" else 0.20)
        logit = (-2.0 + 3.2 * REGIONS[region] + 0.9 * undergrad_local
                 + 1.6 * local_mentor + 1.3 * local_project + rng.gauss(0, 0.5))
        intent = rng.random() < _sigmoid(logit * 1.6)

        talent = rng.gauss(0, 1)
        track_overlap = min(1.0, max(0.0, rng.betavariate(2, 2.5) + 0.12 * talent))
        mentor_tier = max(0, min(3, round(1.4 + 0.7 * talent + rng.gauss(0, 0.8))))
        top_papers = max(0, round(rng.expovariate(1 / (1.2 + 0.9 * max(talent, -1)))))
        first_author = min(top_papers, max(0, round(top_papers * rng.uniform(0.2, 0.7))))
        stars = int(math.exp(rng.gauss(4.0 + 0.9 * talent, 1.6)))
        fit = _sigmoid(1.1 * talent + 2.2 * (track_overlap - 0.45) + rng.gauss(0, 0.5))

        people.append(Candidate(
            id=f"R{i:05d}",
            track=rng.choice(TRACKS),
            track_overlap=_maybe(rng, round(track_overlap, 3), missing_rate),
            mentor_tier=_maybe(rng, mentor_tier, missing_rate),
            mentor_links=_maybe(rng, max(0, int(rng.gauss(6 + 3 * talent, 4))), missing_rate),
            local_projects=_maybe(rng, max(0, int(rng.gauss(1.5 + 2 * REGIONS[region], 1.5))), missing_rate),
            internal_refs=_maybe(rng, min(4, int(rng.expovariate(1.2))), missing_rate),
            github_stars=_maybe(rng, stars, missing_rate),
            top_papers=_maybe(rng, top_papers, missing_rate),
            first_author=first_author,
            citations=_maybe(rng, int(math.exp(rng.gauss(4.5 + 0.6 * talent, 1.4))), missing_rate),
            region=region,
            undergrad_local=undergrad_local,
            local_mentor=local_mentor,
            local_project=local_project,
            intent=intent,
            fit=fit,
        ))
    return people
