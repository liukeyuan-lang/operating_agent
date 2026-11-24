"""Portable entry/config checks; real platform checks live separately in browser-probes."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import demo

ROOT=Path(__file__).resolve().parents[1]


class BrowserSetupTest(unittest.TestCase):
    def test_dependency_versions_are_locked_for_other_machines(self):
        package=json.loads((ROOT/'package.json').read_text(encoding='utf-8'))
        lock=json.loads((ROOT/'package-lock.json').read_text(encoding='utf-8'))
        for name,version in package['dependencies'].items():
            self.assertEqual(version,lock['packages']['']['dependencies'][name])
            self.assertEqual(version,lock['packages']['node_modules/'+name]['version'])
            self.assertNotIn('^',version)
    def test_blank_delivery_config_can_initialize_without_original_assets_or_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir()
            shutil.copyfile(ROOT/'config/project.example.json',root/'config/project.json')
            with patch.object(demo,'ROOT',root):
                files=demo.Files(root/'data/workspace.json')
                files.change(lambda data:{'created':True})
                state=demo.public_state(files)
                self.assertEqual(state['assets'],[])
                self.assertEqual(state['items'],[])
                self.assertEqual(state['publications'],[])
                self.assertEqual(state['runs'],[])
                self.assertEqual(state['current_project']['name'],'新探索')
    def test_server_uses_loopback_persistent_owned_profile_and_rejects_bad_settings(self):
        node=shutil.which('node')
        if not node:self.skipTest('Node required for browser transport config checks')
        code="""import assert from 'node:assert/strict';
import {settings,serverArgs,ROOT} from './browser.mjs';
const config=settings({});const args=serverArgs(config,'cli.js');
assert.equal(config.endpoint,'http://127.0.0.1:8931/mcp');
assert(!args.includes('--isolated'));assert(!args.includes('--port'));
assert.equal(args[args.indexOf('--user-data-dir')+1],config.profile);
assert(config.profile.startsWith(ROOT));assert(config.output.startsWith(ROOT));
assert(!args.includes('--no-sandbox'));assert(!args.includes('--ignore-https-errors'));
assert.throws(()=>settings({OPPORTUNITY_BROWSER_PORT:'0'}));
assert.throws(()=>settings({OPPORTUNITY_BROWSER_CHANNEL:'unknown'}));
assert.equal(settings({OPPORTUNITY_BROWSER_CHANNEL:'msedge',OPPORTUNITY_BROWSER_PORT:'8932'}).endpoint,'http://127.0.0.1:8932/mcp');"""
        result=subprocess.run([node,'--input-type=module','-e',code],cwd=ROOT,text=True,encoding='utf-8',capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
