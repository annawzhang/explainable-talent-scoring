import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from talentscore.experiment import (INDEXES, ab_result, funnel_by_tier, layers, simulate,
                                    two_proportion_z)
from talentscore.scoring import load_config, score, ties_accuracy, tier_names
from talentscore.synth import generate


class ScoringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config()
        cls.people = generate(1500, seed=5)

    def test_contributions_sum_to_total(self):
        for c in self.people[:200]:
            s = score(c, self.cfg)
            self.assertAlmostEqual(sum(s.contributions.values()), s.total, delta=0.1)
            self.assertNotIn("citations", s.contributions)

    def test_too_many_missing_goes_to_c(self):
        c = copy.copy(self.people[0])
        c.track_overlap = c.mentor_tier = c.github_stars = None
        s = score(c, self.cfg)
        self.assertEqual(s.tier, "C")
        self.assertIn("信息不足", s.reason)

    def test_splus_requires_track_and_papers(self):
        for c in self.people:
            s = score(c, self.cfg)
            if s.tier == "S+":
                self.assertGreaterEqual(s.features["track"], 60)
                self.assertGreaterEqual(s.features["papers"], 50)

    def test_weights_must_sum_to_one(self):
        bad = Path(__file__).parent / "_bad.toml"
        text = load_config.__defaults__[0].read_text(encoding="utf-8").replace("weight = 0.22", "weight = 0.5")
        bad.write_text(text, encoding="utf-8")
        try:
            with self.assertRaises(ValueError):
                load_config(bad)
        finally:
            bad.unlink()

    def test_gradient_beats_binary(self):
        acc = ties_accuracy(self.people, self.cfg)
        self.assertGreater(acc["gradient"]["accuracy"], acc["binary"]["accuracy"] + 0.15)


class ExperimentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config()
        cls.sim = simulate(generate(1500, seed=5), cls.cfg, seed=3)
        for stmt in INDEXES:
            cls.sim.db.execute(stmt)

    def test_mixed_samples_excluded(self):
        lay = layers(self.sim.db)
        self.assertEqual(lay["mixed"], self.sim.contaminated)
        ab = ab_result(self.sim.db)
        self.assertEqual(ab["control"]["leads"], lay["control"])
        self.assertEqual(ab["treatment"]["leads"], lay["treatment"])

    def test_funnel_is_monotonic(self):
        for r in funnel_by_tier(self.sim.db, tier_names(self.cfg)):
            self.assertGreaterEqual(r["lead"], r["contacted"])
            self.assertGreaterEqual(r["contacted"], r["replied"])
            self.assertGreaterEqual(r["replied"], r["interview"])
            self.assertGreaterEqual(r["interview"], r["offer"])

    def test_higher_tier_replies_more(self):
        rows = {r["tier"]: r for r in funnel_by_tier(self.sim.db, tier_names(self.cfg))}
        rate = lambda t: rows[t]["replied"] / rows[t]["contacted"]
        self.assertGreater(rate("A"), rate("C"))

    def test_z_test(self):
        z, p = two_proportion_z(40, 100, 60, 100)
        self.assertAlmostEqual(z, 2.828, places=2)
        self.assertAlmostEqual(p, 0.0047, places=3)
        self.assertEqual(two_proportion_z(0, 10, 0, 10), (0.0, 1.0))


if __name__ == "__main__":
    unittest.main()
