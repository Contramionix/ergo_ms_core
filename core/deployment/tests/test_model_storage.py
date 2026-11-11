from pathlib import Path
import errno
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import _bootstrap  # noqa: F401
from huggingface import snapshot
from model_index.locking import model_lock
from project_layout import huggingface_snapshot_dir, huggingface_snapshot_ready


class ModelStorageTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[3] / 'virtual_env/cache/tmp'
        base.mkdir(parents=True, exist_ok=True)
        self.work = tempfile.TemporaryDirectory(dir=base, prefix='model_storage_')
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.dest = huggingface_snapshot_dir(self.root, 'team/model')

    def ready(self):
        self.dest.mkdir(parents=True)
        (self.dest / 'config.json').write_text('{"model_type":"bert"}')
        (self.dest / 'model.safetensors').write_bytes(b'x' * 2048)

    def test_config_and_weights_are_both_required(self):
        self.ready()
        self.assertTrue(huggingface_snapshot_ready(self.dest))
        (self.dest / 'config.json').unlink()
        self.assertFalse(huggingface_snapshot_ready(self.dest))

    def test_all_indexed_shards_must_exist(self):
        self.ready()
        (self.dest / 'model.safetensors').rename(self.dest / 'model-00001-of-00002.safetensors')
        (self.dest / 'model.safetensors.index.json').write_text(json.dumps({'weight_map': {'one':'model-00001-of-00002.safetensors', 'two':'model-00002-of-00002.safetensors'}}))
        self.assertFalse(huggingface_snapshot_ready(self.dest))
        (self.dest / 'model-00002-of-00002.safetensors').write_bytes(b'y' * 2048)
        self.assertTrue(huggingface_snapshot_ready(self.dest))

    def test_unsafe_repo_identifiers_are_rejected(self):
        for name in ('../other', 'team/../../other', 'C:\\escape', '/absolute', 'team\\escape', ''):
            with self.subTest(name=name), self.assertRaises(ValueError):
                huggingface_snapshot_dir(self.root, name)

    def test_lfs_pointer_and_invalid_config_are_not_ready(self):
        self.ready()
        (self.dest / 'model.safetensors').write_bytes(b'version https://git-lfs' + b' ' * 2048)
        self.assertFalse(huggingface_snapshot_ready(self.dest))
        (self.dest / 'model.safetensors').write_bytes(b'x' * 2048)
        (self.dest / 'config.json').write_text('{broken')
        self.assertFalse(huggingface_snapshot_ready(self.dest))

    def test_failed_force_keeps_the_previous_complete_snapshot(self):
        self.ready()
        def fail(**kwargs):
            target = Path(kwargs['local_dir'])
            target.mkdir(parents=True, exist_ok=True)
            (target / 'model.safetensors').write_bytes(b'broken')
            raise OSError('source interrupted')
        hub = types.SimpleNamespace(snapshot_download=fail)
        with patch.dict('sys.modules', {'huggingface_hub':hub}), patch.dict('os.environ', {'HF_HUB_CACHE':str(self.root/'cache')}), patch.object(snapshot, 'apply_hf_home'):
            self.assertEqual(snapshot.install(self.root, 'team/model', force=True), 1)
        self.assertTrue(huggingface_snapshot_ready(self.dest))
        self.assertEqual((self.dest / 'model.safetensors').read_bytes(), b'x' * 2048)

    def test_ready_snapshot_does_not_download_or_change_files(self):
        self.ready()
        (self.dest / 'model.onnx').write_bytes(b'preserve optional format')
        before = {p.name:(p.stat().st_size,p.stat().st_mtime_ns) for p in self.dest.iterdir()}
        with patch.object(snapshot, 'apply_hf_home') as download_environment:
            self.assertEqual(snapshot.install(self.root, 'team/model'), 0)
            download_environment.assert_not_called()
        self.assertEqual(before, {p.name:(p.stat().st_size,p.stat().st_mtime_ns) for p in self.dest.iterdir()})

    def test_failed_publish_restores_the_previous_snapshot(self):
        self.ready()
        staged = self.root / 'new'
        staged.mkdir()
        (staged/'config.json').write_text('{}')
        (staged/'model.safetensors').write_bytes(b'y' * 2048)
        replace = os.replace
        def publish(source, target):
            if source == staged:
                raise OSError('publish failure')
            return replace(source, target)
        with patch.object(snapshot.os, 'replace', side_effect=publish), self.assertRaises(OSError):
            snapshot._publish_snapshot(staged, self.dest)
        self.assertTrue(huggingface_snapshot_ready(self.dest))
        self.assertEqual((self.dest/'model.safetensors').read_bytes(), b'x' * 2048)

    def staged_snapshot(self):
        staged = self.root / 'virtual_env/cache/tmp/download'
        staged.mkdir(parents=True)
        (staged / 'config.json').write_text('{}')
        (staged / 'model.safetensors').write_bytes(b'y' * 2048)
        return staged

    def test_publish_from_another_filesystem(self):
        staged = self.staged_snapshot()
        replace = os.replace
        def separate_mounts(source, target):
            if Path(source) == staged:
                raise OSError(errno.EXDEV, 'different filesystem')
            return replace(source, target)
        with patch.object(snapshot.os, 'replace', side_effect=separate_mounts):
            snapshot._publish_snapshot(staged, self.dest)
        self.assertTrue(huggingface_snapshot_ready(self.dest))
        self.assertEqual((self.dest / 'model.safetensors').read_bytes(), b'y' * 2048)

    def test_cross_filesystem_copy_keeps_previous_weights_available(self):
        self.ready()
        staged = self.staged_snapshot()
        replace, copytree = os.replace, shutil.copytree
        def separate_mounts(source, target):
            if Path(source) == staged:
                raise OSError(errno.EXDEV, 'different filesystem')
            return replace(source, target)
        def copy(source, target):
            self.assertTrue(huggingface_snapshot_ready(self.dest))
            self.assertEqual((self.dest / 'model.safetensors').read_bytes(), b'x' * 2048)
            return copytree(source, target)
        with patch.object(snapshot.os, 'replace', side_effect=separate_mounts), \
                patch.object(snapshot.shutil, 'copytree', side_effect=copy):
            snapshot._publish_snapshot(staged, self.dest)
        self.assertEqual((self.dest / 'model.safetensors').read_bytes(), b'y' * 2048)

    def test_interrupted_cross_filesystem_copy_preserves_previous_snapshot(self):
        self.ready()
        staged = self.staged_snapshot()
        replace = os.replace
        def separate_mounts(source, target):
            if Path(source) == staged:
                raise OSError(errno.EXDEV, 'different filesystem')
            return replace(source, target)
        with patch.object(snapshot.os, 'replace', side_effect=separate_mounts), \
                patch.object(snapshot.shutil, 'copytree', side_effect=OSError('copy interrupted')), \
                self.assertRaisesRegex(OSError, 'copy interrupted'):
            snapshot._publish_snapshot(staged, self.dest)
        self.assertTrue(huggingface_snapshot_ready(self.dest))
        self.assertEqual((self.dest / 'model.safetensors').read_bytes(), b'x' * 2048)
        self.assertEqual(list(self.dest.parent.iterdir()), [self.dest])

    def test_final_switch_failure_restores_previous_snapshot_after_copy(self):
        self.ready()
        staged = self.staged_snapshot()
        replace = os.replace
        failed = False
        def fail_switch(source, target):
            nonlocal failed
            if Path(source) == staged:
                raise OSError(errno.EXDEV, 'different filesystem')
            if Path(target) == self.dest and not failed:
                failed = True
                raise OSError(errno.EIO, 'publish interrupted')
            return replace(source, target)
        with patch.object(snapshot.os, 'replace', side_effect=fail_switch), \
                self.assertRaises(OSError) as caught:
            snapshot._publish_snapshot(staged, self.dest)
        self.assertEqual(caught.exception.errno, errno.EIO)
        self.assertTrue(huggingface_snapshot_ready(self.dest))
        self.assertEqual((self.dest / 'model.safetensors').read_bytes(), b'x' * 2048)
        self.assertEqual(list(self.dest.parent.iterdir()), [self.dest])

    def test_legacy_adoption_preserves_content_and_repeats_without_network(self):
        self.ready()
        legacy = self.root/'virtual_env/trained_models/model'
        self.dest.rename(legacy)
        with patch.object(snapshot, 'apply_hf_home') as download:
            self.assertEqual(snapshot.install(self.root, 'team/model'), 0)
            self.assertEqual(snapshot.install(self.root, 'team/model'), 0)
        download.assert_not_called()
        self.assertFalse(legacy.exists())
        self.assertEqual((self.dest/'model.safetensors').read_bytes(), b'x' * 2048)

    def test_model_lock_serializes_processes_and_releases_after_failure(self):
        script = "from pathlib import Path; from model_index.locking import model_lock; " \
                 "context=model_lock(Path(__import__('sys').argv[1]),'huggingface','team/model',timeout=0.2); " \
                 "context.__enter__(); context.__exit__(None,None,None)"
        env = {**os.environ, 'PYTHONPATH':str(Path(__file__).resolve().parents[1])}
        with model_lock(self.root, 'huggingface', 'team/model'):
            run = subprocess.run([sys.executable,'-c',script,str(self.root)],env=env,capture_output=True,text=True,timeout=10)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn('TimeoutError', run.stderr)
        run = subprocess.run([sys.executable,'-c',script,str(self.root)],env=env,capture_output=True,text=True,timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
