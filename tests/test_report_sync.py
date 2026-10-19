"""Execute the generated refresh code for online, local and offline readers."""
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pages_build


@unittest.skipUnless(shutil.which('node'), 'JavaScript runtime unavailable')
class ReportSyncTests(unittest.TestCase):
    def execute(self, protocol, online, action=''):
        page = pages_build.inject_mobile_panel('<html><head></head><body><main></main></body></html>')
        script = re.search(r'<script>(.*?)</script>', page, re.S).group(1)
        harness = '''
const vm = require('node:vm');
const calls = [], note = {hidden:true};
const context = {
 window:{addEventListener(){}}, document:{hidden:false, getElementById(){return note}, addEventListener(){}},
 location:{protocol:PROTOCOL, replace(url){calls.push(url)}},
 navigator:{onLine:ONLINE}, setInterval(){}, Date,
 sessionStorage:{getItem(){return null},setItem(){}},
 fetch:async function(url){if(PROTOCOL==='file:')throw Error('Relative fetch attempted from file');return {ok:true,json:async()=>({version:'99999999999999'})}}
};
(async()=>{vm.createContext(context);vm.runInContext(SCRIPT,context);
await vm.runInContext(ACTION || 'Promise.resolve()',context);
console.log(JSON.stringify({calls,hidden:note.hidden}));})().catch(e=>{console.error(e);process.exit(1)});
'''
        for key, value in [('PROTOCOL',protocol), ('ONLINE',online), ('SCRIPT',script), ('ACTION',action)]:
            harness = harness.replace(key,json.dumps(value))
        r = subprocess.run(['node','-e',harness],check=True,capture_output=True,text=True,encoding='utf-8')
        return json.loads(r.stdout)

    def assert_cloud(self, result):
        self.assertTrue(result['calls'])
        for url in result['calls']:
            self.assertTrue(url.startswith(pages_build.cloud_links()[2]))

    def test_open_local_online_navigates_to_live_report(self):
        result = self.execute('file:', True)
        self.assert_cloud(result)
        self.assertFalse(result['hidden'])

    def test_offline_snapshot_is_labeled_and_does_not_fetch(self):
        result = self.execute('file:',False,'autoRefreshIfStale()')
        self.assertEqual(result['calls'],[])
        self.assertFalse(result['hidden'])

    def test_local_refresh_uses_cloud_instead_of_missing_sibling(self):
        self.assert_cloud(self.execute('file:',False,'forceRefresh()'))

    def test_online_new_version_reloads_online_page(self):
        self.assert_cloud(self.execute('https:',True,'autoRefreshIfStale()'))


if __name__ == '__main__':
    unittest.main()
