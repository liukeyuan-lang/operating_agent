"""Portable interpreter selection, arguments and foreground process lifecycle."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch,Mock

import launcher


class LauncherTest(unittest.TestCase):
    def test_native_venv_and_explicit_interpreter_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for system,relative in [('nt','.venv/Scripts/python.exe'),('posix','.venv/bin/python')]:
                self.assertEqual(launcher.python_path(root,system,{}),sys.executable)
                binary=root/relative;binary.parent.mkdir(parents=True,exist_ok=True);binary.touch()
                self.assertEqual(launcher.python_path(root,system,{}),str(binary.resolve()))
            self.assertEqual(launcher.python_path(root,'posix',{'OPPORTUNITY_PYTHON':sys.executable}),str(Path(sys.executable).resolve()))
            with self.assertRaises(ValueError):launcher.python_path(root,env={'OPPORTUNITY_PYTHON':str(root/'missing')})
    def test_ui_and_browser_keep_arguments_cwd_and_same_python_environment(self):
        with patch.object(launcher,'run',return_value=7) as run,patch.object(launcher,'python_path',return_value=sys.executable):
            self.assertEqual(launcher.launch('ui',['--port','8766']),7)
            command,env=run.call_args.args
            self.assertEqual(command[-2:],['--port','8766'])
            self.assertEqual(command[3],str(launcher.ROOT/'demo.py'))
            self.assertEqual(env['OPPORTUNITY_PYTHON'],sys.executable)
            with patch.object(launcher.shutil,'which',return_value='/node path/node'):
                launcher.launch('browser',[])
                self.assertEqual(run.call_args.args[0],['/node path/node',str(launcher.ROOT/'browser.mjs'),'serve'])
                launcher.launch('browser',['open','https://example.test/a?x=1&y=2'])
                self.assertEqual(run.call_args.args[0][-2:],['open','https://example.test/a?x=1&y=2'])
            with patch.object(launcher.shutil,'which',return_value=None):
                self.assertEqual(launcher.launch('browser',[]),1)
    def test_child_runs_in_project_and_exits_or_cleans_up_on_interrupt(self):
        process=Mock();process.wait.return_value=9
        with patch.object(launcher.subprocess,'Popen',return_value=process) as popen:
            self.assertEqual(launcher.run(['binary','a path'],{'PYTHONUTF8':'1'}),9)
            self.assertEqual(popen.call_args.kwargs['cwd'],launcher.ROOT)
            self.assertNotIn('shell',popen.call_args.kwargs)
            process.wait.side_effect=[KeyboardInterrupt,subprocess.TimeoutExpired('binary',5),0]
            self.assertEqual(launcher.run(['binary'],{}),130)
            process.terminate.assert_called_once()

    def test_compression_switch_is_explicit_and_preserves_environment_override(self):
        with patch.object(launcher,'run',return_value=0) as run,patch.object(launcher,'python_path',return_value=sys.executable):
            with patch.dict(os.environ,{'MATERIAL_COMPRESS_VIDEO':'1'}):
                launcher.launch('ui',['--no-compress-videos']);self.assertEqual(run.call_args.args[1]['MATERIAL_COMPRESS_VIDEO'],'0')
                launcher.launch('ui',[]);self.assertEqual(run.call_args.args[1]['MATERIAL_COMPRESS_VIDEO'],'1')
            launcher.launch('ui',['--compress-videos']);self.assertEqual(run.call_args.args[1]['MATERIAL_COMPRESS_VIDEO'],'1')
    def test_material_timeout_flag_preserves_env_unless_explicitly_set(self):
        with patch.object(launcher,'run',return_value=0) as run,patch.object(launcher,'python_path',return_value=sys.executable):
            with patch.dict(os.environ,{'MATERIAL_REQUEST_TIMEOUT_SECONDS':'900'}):
                launcher.launch('ui',[]);self.assertEqual(run.call_args.args[1]['MATERIAL_REQUEST_TIMEOUT_SECONDS'],'900')
                launcher.launch('ui',['--material-timeout','1200']);self.assertEqual(float(run.call_args.args[1]['MATERIAL_REQUEST_TIMEOUT_SECONDS']),1200)
            count=run.call_count
            self.assertEqual(launcher.launch('ui',['--material-timeout','0']),1)
            self.assertEqual(run.call_count,count)
    def test_real_entrypoint_help_from_another_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            env={k:v for k,v in os.environ.items() if k!='OPPORTUNITY_PYTHON'}
            result=subprocess.run([sys.executable,str(launcher.ROOT/'启动界面.py'),'--help'],cwd=directory,
                env=env,capture_output=True,text=True,encoding='utf-8',timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('--port',result.stdout)
