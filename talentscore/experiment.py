"""线索跟进模拟、SQLite 落库、漏斗与 AB 实验分析。

第 1 轮：全量线索按分层策略跟进，得到分层漏斗。
第 2 轮：AB 实验。对照组用「本科是否本地」单一标签算地域关联度，实验组用四因子梯度；
两组招聘人力相同，都只跟进组内得分前 contact_share 的线索。
线索重复导入会让少量候选人同时落入两组，分析时用 NOT EXISTS 排除。
"""

import math
import random
import sqlite3
import time
from dataclasses import dataclass

from .scoring import Score, score
from .synth import Candidate

STAGES = ["contacted", "replied", "interview", "offer"]
STAGE_NAMES = {"lead": "线索", "contacted": "触达", "replied": "回复", "interview": "面试", "offer": "Offer"}
TIER_CONTACT = {"S+": 1.0, "S": 0.95, "A": 0.8, "B": 0.45, "C": 0.12}

SCHEMA = """
CREATE TABLE candidates (id TEXT PRIMARY KEY, track TEXT, region TEXT, total REAL, tier TEXT);
CREATE TABLE assignments (candidate_id TEXT, round INTEGER, grp TEXT);
CREATE TABLE events (candidate_id TEXT, round INTEGER, stage TEXT);
"""

AB_SQL = """
WITH pure AS (
  SELECT a.candidate_id, a.grp
  FROM assignments a
  WHERE a.round = 2
    AND NOT EXISTS (
      SELECT 1 FROM assignments b
      WHERE b.candidate_id = a.candidate_id AND b.round = a.round AND b.grp <> a.grp)
)
SELECT p.grp,
       COUNT(*) AS leads,
       SUM(EXISTS (SELECT 1 FROM events e WHERE e.candidate_id = p.candidate_id AND e.round = 2 AND e.stage = 'contacted')) AS contacted,
       SUM(EXISTS (SELECT 1 FROM events e WHERE e.candidate_id = p.candidate_id AND e.round = 2 AND e.stage = 'replied')) AS replied,
       SUM(EXISTS (SELECT 1 FROM events e WHERE e.candidate_id = p.candidate_id AND e.round = 2 AND e.stage = 'interview')) AS interview,
       SUM(EXISTS (SELECT 1 FROM events e WHERE e.candidate_id = p.candidate_id AND e.round = 2 AND e.stage = 'offer')) AS offer
FROM pure p
GROUP BY p.grp
ORDER BY p.grp
"""

LAYER_SQL = """
SELECT CASE WHEN COUNT(DISTINCT grp) > 1 THEN 'mixed' ELSE MIN(grp) END AS layer, COUNT(*) AS n
FROM (SELECT candidate_id, grp FROM assignments WHERE round = 2)
GROUP BY candidate_id
"""

FUNNEL_SQL = """
SELECT c.tier,
       COUNT(DISTINCT c.id) AS lead,
       SUM(e.stage = 'contacted') AS contacted,
       SUM(e.stage = 'replied') AS replied,
       SUM(e.stage = 'interview') AS interview,
       SUM(e.stage = 'offer') AS offer
FROM candidates c
LEFT JOIN events e ON e.candidate_id = c.id AND e.round = 1
GROUP BY c.tier
"""

INDEXES = [
    "CREATE INDEX idx_assign ON assignments (candidate_id, round, grp)",
    "CREATE INDEX idx_events ON events (candidate_id, round, stage)",
]


def outcome(c: Candidate, rng: random.Random) -> list[str]:
    """一次跟进的结果。回复主要取决于真实回流意向，后续环节取决于匹配度。"""
    stages = ["contacted"]
    if rng.random() < (0.10 + 0.50 * c.intent) * (0.6 + 0.6 * c.fit):
        stages.append("replied")
        if rng.random() < 0.30 + 0.45 * c.fit:
            stages.append("interview")
            if rng.random() < 0.20 + 0.40 * c.fit:
                stages.append("offer")
    return stages


@dataclass
class Simulation:
    db: sqlite3.Connection
    scores: dict[str, Score]
    contaminated: int


def simulate(people: list[Candidate], cfg: dict, seed: int = 11,
             contact_share: float = 0.3, contamination: float = 0.05) -> Simulation:
    rng = random.Random(seed)
    db = sqlite3.connect(":memory:")
    db.executescript(SCHEMA)
    scores = {c.id: score(c, cfg) for c in people}
    db.executemany("INSERT INTO candidates VALUES (?,?,?,?,?)",
                   [(c.id, c.track, c.region, scores[c.id].total, scores[c.id].tier) for c in people])

    events = []
    for c in people:
        if rng.random() < TIER_CONTACT[scores[c.id].tier]:
            events += [(c.id, 1, s) for s in outcome(c, rng)]

    groups = {"control": [], "treatment": []}
    assignments, mixed = [], set()
    for c in people:
        grp = "treatment" if rng.random() < 0.5 else "control"
        groups[grp].append(c)
        assignments.append((c.id, 2, grp))
        if rng.random() < contamination:
            other = "control" if grp == "treatment" else "treatment"
            assignments.append((c.id, 2, other))
            mixed.add(c.id)

    for grp, members in groups.items():
        mode = "gradient" if grp == "treatment" else "binary"
        ranked = sorted(members, key=lambda c: -score(c, cfg, mode).total)
        for c in ranked[:int(len(ranked) * contact_share)]:
            events += [(c.id, 2, s) for s in outcome(c, rng)]

    db.executemany("INSERT INTO assignments VALUES (?,?,?)", assignments)
    db.executemany("INSERT INTO events VALUES (?,?,?)", events)
    db.commit()
    return Simulation(db, scores, len(mixed))


def funnel_by_tier(db: sqlite3.Connection, tiers: list[str]) -> list[dict]:
    rows = {r[0]: r for r in db.execute(FUNNEL_SQL)}
    out = []
    for t in tiers:
        if t not in rows:
            continue
        _, lead, contacted, replied, interview, offer = rows[t]
        out.append({"tier": t, "lead": lead, "contacted": contacted, "replied": replied,
                    "interview": interview, "offer": offer})
    return out


def layers(db: sqlite3.Connection) -> dict[str, int]:
    counts = {"control": 0, "treatment": 0, "mixed": 0}
    for layer, _ in db.execute(LAYER_SQL):
        counts[layer] += 1
    return counts


def ab_result(db: sqlite3.Connection) -> dict[str, dict]:
    cols = ["leads", "contacted", "replied", "interview", "offer"]
    return {row[0]: dict(zip(cols, row[1:])) for row in db.execute(AB_SQL)}


def two_proportion_z(x1: int, n1: int, x2: int, n2: int) -> tuple[float, float]:
    """双比例 z 检验（双尾）。返回 (z, p)。"""
    p1, p2 = x1 / n1, x2 / n2
    pooled = (x1 + x2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return 0.0, 1.0
    z = (p2 - p1) / se
    return z, math.erfc(abs(z) / math.sqrt(2))


def time_query(db: sqlite3.Connection, sql: str, repeat: int = 3) -> float:
    best = float("inf")
    for _ in range(repeat):
        t0 = time.perf_counter()
        db.execute(sql).fetchall()
        best = min(best, time.perf_counter() - t0)
    return best * 1000


def index_benchmark(db: sqlite3.Connection) -> dict[str, float]:
    """关闭 SQLite 自动索引，对比建索引前后 AB 查询耗时（毫秒）。"""
    db.execute("PRAGMA automatic_index = OFF")
    before = time_query(db, AB_SQL, repeat=1)
    for stmt in INDEXES:
        db.execute(stmt)
    after = time_query(db, AB_SQL)
    plan = [row[-1] for row in db.execute("EXPLAIN QUERY PLAN " + AB_SQL)]
    return {"before_ms": before, "after_ms": after, "plan": plan}
