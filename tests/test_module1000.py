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

    def test_registry_is_exactly_20_families_times_10_windows_times_5_algorithm_settings(self):
        configs=registry.configurations()
        self.assertEqual(len(configs),1000)
        self.assertEqual(len({registry.configuration_signature(c) for c in configs}),1000)
        self.assertEqual({v for v in Counter(c['family'] for c in configs).values()},{50})
        self.assertEqual(len({c['family'] for c in configs}),20)
        self.assertEqual(configs[-1]['id'],'M1000')

    def test_frequency_module_matches_direct_counting_with_no_outcomes_supplied(self):
        modules=registry.rank_modules(self.draws[:150])
        counts=Counter(n for d in self.draws[140:150] for n in d['numbers'])
        older=Counter(n for d in self.draws[:140] for n in d['numbers'])
        values={n:(counts[n]+(older[n]+5/39)/141)/11 for n in range(1,40)}
        expected=sorted(range(1,40),key=lambda n:(-values[n],n))
        self.assertEqual(modules[0]['ranking'],expected)
        self.assertTrue(all(len(m['ranking'])==39 and set(m['ranking'])==set(range(1,40)) for m in modules))

    def test_algorithms_have_own_formulas_and_control_cannot_vote(self):
        modules=registry.rank_modules(self.draws)
        self.assertEqual(len(engine.voting_modules(modules)),950)
        # Direct independent AR(1) solution, not a frequency/rank blend.
        scores=registry.features(self.draws,30,2)['自迴歸最小平方法']
        for n in range(1,40):
            y=[int(n in d['numbers']) for d in self.draws[-30:]]
            mx=sum(y[:-1])/29;my=sum(y[1:])/29
            slope=sum((a-mx)*(b-my) for a,b in zip(y[:-1],y[1:]))/(sum((a-mx)**2 for a in y[:-1])+3)
            self.assertAlmostEqual(scores[n],my+slope*(y[-1]-mx))
        random_a=registry.features(self.draws,30,2)['可重現隨機對照']
        changed=copy.deepcopy(self.draws)
        for d in changed:d['numbers']=[1,2,3,4,5]
        self.assertEqual(random_a,registry.features(changed,30,2)['可重現隨機對照'])
        # Graph stationary mass is a probability distribution; regression scores are not forced into ranks.
        graph=registry.features(self.draws,30,2)['共現圖隨機漫步']
        self.assertAlmostEqual(sum(graph.values()),1)
        representatives=[m for m in modules if m['window']==90 and m['parameters']['algorithm_setting']==2]
        self.assertGreaterEqual(len({tuple(m['ranking']) for m in representatives}),15)

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
        modules=engine.voting_modules(modules)
        ranks={n:sum(39-m['ranking'].index(n) for m in modules) for n in pool}
        pairs={p:sum(set(p)<=set(m['ranking'][:9]) for m in modules) for p in combinations(pool,2)}
        expected=[]
        for ns in combinations(pool,6):
            score=10*sum(ranks[n] for n in ns)+39*sum(pairs[p] for p in combinations(ns,2))
            expected.append((score,tuple(-n for n in ns),list(ns)))
        self.assertEqual([(g['score_units'],g['numbers']) for g in actual],[(s,n) for s,_,n in sorted(expected,reverse=True)[:10]])


if __name__=='__main__':unittest.main()
