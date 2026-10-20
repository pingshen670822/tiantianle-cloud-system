from test_data import current_analysis
import copy
import json
import unittest
from pathlib import Path
from html.parser import HTMLParser
from ensemble50 import number_percentages, voting_modules
from module1000 import MODULE_COUNT
import report539_style as layout
import report_sections

ROOT=Path(__file__).resolve().parents[1]


class ScoredNumbers(HTMLParser):
    def __init__(self):super().__init__();self.values=[];self.groups=[];self.current=None
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='article' and 'data-six-group' in a:
            self.current=[];self.groups.append(self.current)
        if 'data-scored-number' in a:
            value=(int(a['data-scored-number']),float(a['data-ranking-percent']))
            self.values.append(value)
            if self.current is not None:self.current.append(value)
    def handle_endtag(self,tag):
        if tag=='article':self.current=None


class NumberPercentageTests(unittest.TestCase):
    def setUp(self):
        self.a=current_analysis()
        self.e=self.a['ensemble50']
    def test_percentages_match_independent_rank_arithmetic_and_fusion_order(self):
        values=number_percentages(self.e['modules'])['numbers']
        self.assertEqual([r['number'] for r in values],self.e['ranking'])
        self.assertEqual({r['number'] for r in values},set(range(1,40)))
        for row in values:
            points=sum(40-(m['ranking'].index(row['number'])+1) for m in voting_modules(self.e['modules']))
            self.assertEqual(row['ranking_points'],points)
            self.assertAlmostEqual(row['ranking_score_percent'],round(100*points/(39*len(voting_modules(self.e['modules']))),4))
    def test_known_opposite_rankings_have_same_score_and_deterministic_ties(self):
        modules=[{'id':str(i),'ranking':list(range(1,40)) if i%2==0 else list(range(39,0,-1))} for i in range(MODULE_COUNT)]
        rows=number_percentages(modules)['numbers']
        self.assertEqual([r['number'] for r in rows],list(range(1,40)))
        self.assertEqual({r['ranking_points'] for r in rows},{20*MODULE_COUNT})
        self.assertEqual({r['ranking_score_percent'] for r in rows},{round(100*20/39,4)})
    def test_all_prediction_chips_and_six_groups_keep_exact_same_percent(self):
        page=layout.render_report(self.a,'https://example.invalid/','https://example.invalid/update')
        parsed=ScoredNumbers();parsed.feed(page)
        values={r['number']:r['ranking_score_percent'] for r in number_percentages(self.e['modules'])['numbers']}
        self.assertEqual(len(parsed.groups),20)
        expected=self.e['six_number_combinations']['groups']+self.e['full39_six_combinations']['groups']
        self.assertEqual([[n for n,p in group] for group in parsed.groups],[g['numbers'] for g in expected])
        for number,percent in parsed.values:self.assertEqual(percent,values[number])
        self.assertIn('不是開出機率',page)
        self.assertIn('1–39全號碼運算百分比',page)
    def test_tampered_percentage_is_rejected(self):
        self.e['number_percentages']=number_percentages(self.e['modules'])
        self.e['number_percentages']['numbers'][0]['ranking_score_percent']+=1
        with self.assertRaises(ValueError):layout.percentage_map(self.e)
    def test_invalid_rankings_or_duplicate_modules_cannot_generate_percentages(self):
        modules=copy.deepcopy(self.e['modules']);modules[0]['ranking'][0]=modules[0]['ranking'][1]
        with self.assertRaises(ValueError):number_percentages(modules)
        modules=copy.deepcopy(self.e['modules']);modules[0]['id']=modules[1]['id']
        with self.assertRaises(ValueError):number_percentages(modules)
    def test_candidates_include_percent_for_each_selected_number(self):
        page=report_sections.models_content(self.a)
        for module in self.e['modules']:
            for n in module['ranking'][:5]:
                expected=round(sum(39-m['ranking'].index(n) for m in voting_modules(self.e['modules']))/(39*len(voting_modules(self.e['modules'])))*100,2)
                self.assertIn(f'{n:02d}（{expected:.2f}％）',page)


if __name__=='__main__':unittest.main()
