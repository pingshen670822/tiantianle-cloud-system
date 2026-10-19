import copy
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import report539_style as layout
import pages_build


class Elements(HTMLParser):
    def __init__(self):
        super().__init__(); self.targets=[]; self.sixes=0; self.ids=[]
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if 'data-target-group' in a:self.targets.append(a['data-target-group'])
        if 'data-six-group' in a:self.sixes+=1
        if 'id' in a:self.ids.append(a['id'])


class StyledReportTests(unittest.TestCase):
    def setUp(self):
        # Existing fixture covers the data audit; use the actual field schema for rendering.
        import json
        self.analysis=json.loads((Path(__file__).resolve().parents[1]/'reports/latest_analysis.json').read_text(encoding='utf-8'))
    def render(self,a=None):
        return layout.render_report(a or self.analysis,'https://example.invalid/','https://example.invalid/update')
    def test_same_fusion_drives_single_five_targets_and_twenty_six_groups(self):
        page=self.render();parser=Elements();parser.feed(page)
        self.assertEqual(parser.targets,['2中2','3中3','5中5','7中5','9中5'])
        self.assertEqual(parser.sixes,20)
        e=self.analysis['ensemble50'];n=e['packs'][0]['numbers'][0]
        self.assertIn(f'data-ultimate-single="{n}"',page)
        for marker in ('ensemble50-required','top15-six-groups','full39-six-groups','verification'):
            self.assertEqual(parser.ids.count(marker),1)
        for block in ('six_number_combinations','full39_six_combinations'):
            for group in e[block]['groups']:
                self.assertIn(' '.join(f'{n:02d}' for n in group['numbers']),page)
    def test_invalid_dates_or_missing_verification_do_not_get_report(self):
        a=copy.deepcopy(self.analysis);a['target_draw_date']='1900-01-01'
        with self.assertRaises(ValueError):self.render(a)
        a=copy.deepcopy(self.analysis);a['ensemble50']['verification']['modules_verified']=49
        with self.assertRaises(ValueError):self.render(a)
    def test_539_layout_keeps_local_sync_script_without_legacy_panel(self):
        page=pages_build.inject_mobile_panel(self.render(),report_layout=True)
        self.assertIn("location.protocol === 'file:'",page)
        self.assertNotIn('sticky-launch',page)
        self.assertIn('高信心命中資格尚未通過',page)
        self.assertIn('逐期回測 <b>60期',page)
        self.assertNotIn('20／20',page)


if __name__=='__main__':unittest.main()
