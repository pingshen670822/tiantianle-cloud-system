import copy
import random
import unittest
from collections import Counter
from datetime import date,timedelta
from itertools import combinations
from unittest.mock import patch
import ensemble50 as engine
import module1000 as registry


class ThousandModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng=random.Random(8021)
        cls.draws=[{'draw_date':(date(2025,1,1)+timedelta(days=i)).isoformat(),
                    'numbers':sorted(rng.sample(range(1,40),5))} for i in range(160)]

    def test_registry_is_exactly_20_families_times_10_windows_times_5_blends(self):
        configs=registry.configurations()
        self.assertEqual(len(configs),1000)
        self.assertEqual(len({registry.configuration_signature(c) for c in configs}),1000)
        self.assertEqual({v for v in Counter(c['family'] for c in configs).values()},{50})
        self.assertEqual(len({c['family'] for c in configs}),20)
        self.assertEqual(configs[-1]['id'],'M1000')

    def test_frequency_module_matches_direct_counting_with_no_outcomes_supplied(self):
        modules=registry.rank_modules(self.draws[:150])
        counts=Counter(n for d in self.draws[140:150] for n in d['numbers'])
        expected=sorted(range(1,40),key=lambda n:(-counts[n],n))
        self.assertEqual(modules[0]['ranking'],expected)
        self.assertTrue(all(len(m['ranking'])==39 and set(m['ranking'])==set(range(1,40)) for m in modules))

    def test_causal_prefixes_and_per_module_hit_counts_are_replayed(self):
        original=registry.rank_modules;observed=[]
        def spy(prefix):
            observed.append(len(prefix));return original(prefix)
        with patch.object(engine,'rank_modules',side_effect=spy),patch.object(engine,'verify_exact_six',return_value={}):
            result=engine.compute(self.draws,samples=3)
        self.assertEqual(observed,[160,157,158,159,157,158,159,160])
        self.assertEqual(result['verification']['module_forecasts'],3000)
        self.assertEqual(result['verification']['replay_rounds'],2)
        expected_single=expected_five=0
        for end in range(157,160):
            ranking=original(self.draws[:end])[0]['ranking'];actual=set(self.draws[end]['numbers'])
            expected_single+=ranking[0] in actual;expected_five+=len(set(ranking[:5])&actual)
        validation=result['modules'][0]['validation']
        self.assertEqual(validation['single_hits'],expected_single)
        self.assertEqual(validation['top5_avg_hits'],round(expected_five/3,4))
        self.assertTrue(all(r['training_last_date']<r['target_date'] for r in result['backtest_manifest']))

    def test_changed_replay_cannot_claim_success(self):
        original=registry.rank_modules;calls=0
        def corrupt(prefix):
            nonlocal calls
            calls+=1;result=original(prefix)
            if calls==5:result[0]['ranking'][:2]=result[0]['ranking'][1::-1]
            return result
        with patch.object(engine,'rank_modules',side_effect=corrupt),patch.object(engine,'verify_exact_six',return_value={}):
            with self.assertRaisesRegex(RuntimeError,'replay mismatch'):engine.compute(self.draws,samples=3)

    def test_exact_six_search_agrees_with_independent_small_pool_enumeration(self):
        modules=registry.rank_modules(self.draws);pool=list(range(1,11))
        actual=engine.full39_top_six(modules,count=10,pool=pool)['groups']
        ranks={n:sum(39-m['ranking'].index(n) for m in modules) for n in pool}
        pairs={p:sum(set(p)<=set(m['ranking'][:9]) for m in modules) for p in combinations(pool,2)}
        expected=[]
        for ns in combinations(pool,6):
            score=10*sum(ranks[n] for n in ns)+39*sum(pairs[p] for p in combinations(ns,2))
            expected.append((score,tuple(-n for n in ns),list(ns)))
        self.assertEqual([(g['score_units'],g['numbers']) for g in actual],[(s,n) for s,_,n in sorted(expected,reverse=True)[:10]])


if __name__=='__main__':unittest.main()
