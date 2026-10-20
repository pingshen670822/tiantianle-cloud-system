from test_data import current_analysis
import copy
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from html.parser import HTMLParser
import report_sections as sections
import report539_style as layout
import pages_build

ROOT=Path(__file__).resolve().parents[1]


class NavReader(HTMLParser):
    def __init__(self):super().__init__();self.inside=False;self.links=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='nav':self.inside=True
        if self.inside and tag=='a':self.links.append(a)
    def handle_endtag(self,tag):
        if tag=='nav':self.inside=False


class SectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a=current_analysis()
        cls.records=sections.history_rows(ROOT/'fantasy5_full_history.csv',cls.a)
        cls.pages=sections.render_sections(cls.a,cls.records,'https://example.invalid/','https://example.invalid/tiantianle-cloud-auto-update.yml')
    def test_all_five_destinations_share_navigation_and_current_tab(self):
        pages={'forecast':layout.render_report(self.a,'https://example.invalid/','https://example.invalid/update'),**self.pages}
        for key,page in pages.items():
            parser=NavReader();parser.feed(page)
            self.assertEqual([a['href'] for a in parser.links],['./','review/','history/','models/','system/'])
            self.assertEqual([a['href'] for a in parser.links if a.get('aria-current')=='page'],[dict((k,h) for k,h,_ in layout.NAVIGATION)[key]])
            self.assertIn(self.a['generated_at_taiwan'],page)
    def test_sections_keep_their_destination_on_refresh(self):
        for key,page in self.pages.items():
            rendered=pages_build.inject_mobile_panel(page,report_layout=True,report_path=key+'/')
            self.assertIn('const CLOUD_REPORT_URL = '+json.dumps(pages_build.cloud_links()[2]+key+'/'),rendered)
    def test_wrong_history_or_settlement_cannot_be_published(self):
        wrong=copy.deepcopy(self.a);wrong['draw_count']+=1
        with self.assertRaises(ValueError):sections.history_rows(ROOT/'fantasy5_full_history.csv',wrong)
        wrong=copy.deepcopy(self.a)
        p=next(iter(wrong['failure_review']['last_settled']['strong_pack_hits'].values()));p['hits']+=1
        with self.assertRaises(ValueError):sections.review_content(wrong)
    @unittest.skipUnless(shutil.which('node'),'JavaScript runtime unavailable')
    def test_history_search_and_paging_use_full_history(self):
        content=sections.history_content(self.records)
        script=re.search(r'<script>\s*(.*?)</script>',content,re.S).group(1)
        data=json.dumps(self.records,ensure_ascii=False)
        driver='''
const vm=require('node:vm'),assert=require('node:assert/strict');
const records=DATA,nodes={};for(const id of ['historyData','historyRows','historyDate','historySearch','historyAll','historySummary','historyPrevious','historyNext'])nodes[id]={value:'',textContent:'',innerHTML:'',disabled:false};
nodes.historyData.textContent=JSON.stringify(records);const ctx={document:{getElementById:id=>nodes[id]}};vm.createContext(ctx);vm.runInContext(SCRIPT,ctx);
assert.equal((nodes.historyRows.innerHTML.match(/<tr>/g)||[]).length,50);const first=nodes.historyRows.innerHTML;
nodes.historyNext.onclick();assert.notEqual(nodes.historyRows.innerHTML,first);nodes.historyPrevious.onclick();assert.equal(nodes.historyRows.innerHTML,first);
nodes.historyDate.value=records.at(-1).date;nodes.historySearch.onclick();assert.ok(nodes.historyRows.innerHTML.includes(records.at(-1).date));assert.equal(nodes.historyNext.disabled,true);
nodes.historyDate.value='1900-01-01';nodes.historySearch.onclick();assert.equal(nodes.historyRows.innerHTML,'');
nodes.historyAll.onclick();assert.equal(nodes.historyRows.innerHTML,first);console.log('paging and date search passed');
'''.replace('DATA',data).replace('SCRIPT',json.dumps(script))
        # Feed stdin to avoid Windows command length limits with complete history.
        result=subprocess.run(['node'],input=driver,encoding='utf-8',capture_output=True,check=True)
        self.assertIn('passed',result.stdout)


if __name__=='__main__':unittest.main()
