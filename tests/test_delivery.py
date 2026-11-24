"""Inspect the actual delivery ZIP without touching live project records."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from 打包项目 import build


class DeliveryTest(unittest.TestCase):
    def test_clean_bundle_has_blank_config_complete_manifest_and_shortened_doc(self):
        with tempfile.TemporaryDirectory() as directory:
            target=build(Path(directory)/'delivery.zip')
            with ZipFile(target) as bundle:
                self.assertIsNone(bundle.testzip())
                names={name.removeprefix('operating_agent/') for name in bundle.namelist()}
                for name in names:
                    self.assertFalse(set(Path(name).parts)&{'data','node_modules','.venv','archive','tmp','__pycache__'})
                    self.assertNotIn('.env',name)
                def read(name):return bundle.read('operating_agent/'+name)
                config=json.loads(read('config/project.json'))
                initial=json.loads(read('config/initial-leads.json'))
                self.assertIn('https://jimeng.jianying.com/ai-tool/explore',[r['target'] for r in initial])
                self.assertEqual(config['assets'],[])
                self.assertEqual(config['project']['id'],'my-creative-project')
                self.assertEqual(read('config/project.json'),read('config/project.example.json'))
                self.assertIn('operating_agent',read('README.md').decode('utf-8'))
                self.assertNotIn('交付说明.md',names)
                self.assertFalse(any(n.endswith('.cmd') for n in names))
                for entry in ('launcher.py','启动界面.py','启动浏览器.py','verification.py','opportunities.py','access_links.py','file_picker.py',
                              'material_understanding.py','material_media.py','material_formats.py','requirements-media.txt','file_store.py','project_workspaces.py','relay_llm.py','discovery.py','material_library.py','ui/discovery.js','ui/home.html','ui/publish.html','ui/materials.js',
                              'skills/search-opportunity/SKILL.md','skills/prepare-publication/SKILL.md'):
                    self.assertIn(entry,names)
                self.assertFalse(any(n.startswith(('skills/xhs-opportunity-demo/','skills/xhs-publishing/')) for n in names))
                document=read('部署与安装.md').decode('utf-8')
                self.assertIn('## 6.',document)
                self.assertNotIn('## 7.',document)
                self.assertNotIn('## 8.',document)
                manifest=json.loads(read('交付清单.json'))
                self.assertFalse(manifest['runtime_data_included'])
                self.assertEqual({r['path'] for r in manifest['files']},names-{'交付清单.json'})
                for entry in manifest['files']:
                    body=read(entry['path'])
                    self.assertEqual(hashlib.sha256(body).hexdigest(),entry['sha256'])
                    self.assertEqual(len(body),entry['bytes'])
