"""Offline publication/tool-resolution checks; no real secrets or network."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import verify_publish as guard
import build_release

S=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(S/'assets/runtime'))
from apt_media_tools import resolve_tool


def fixture():
    license=b'Original package license by wuwukasi; retained unchanged.'
    clip=b'original synthetic media fixture, not a real video'
    name='assets/template/补齐生成用/001 22.mp4'
    digest=lambda value:hashlib.sha256(value).hexdigest()
    files={'README.md':b'English guide: wuwukasi https://space.bilibili.com/670281046; T8star https://space.bilibili.com/385085361',
        'LICENSE.txt':license,'assets/template/LICENSE.txt':license,name:clip,
        'meta.json':json.dumps({'name':guard.NAME,'version':'fixture'}).encode(),
        'publish-policy.json':json.dumps({'repository':guard.REPO}).encode()}
    assets={name:{'sha256':digest(clip),'size_bytes':len(clip)}}
    files['release-assets.json']=json.dumps({'files':assets}).encode()
    files['manifest.json']=json.dumps({'name':guard.NAME,'version':'fixture','files':{n:digest(v) for n,v in files.items()},
        'original_package_sha256':{'LICENSE.txt':digest(license),'补齐生成用/001 22.mp4':digest(clip)}}).encode()
    return files


class PublicationTests(unittest.TestCase):
    def test_complete_bundle_and_source_only_are_distinct(self):
        files=fixture();self.assertEqual(guard.check_files(files,complete=True),[])
        source={n:v for n,v in files.items() if not n.endswith('.mp4')}
        self.assertEqual(guard.check_files(source),[])
        self.assertTrue(guard.check_files(files))

    def test_roadmap_keys_executables_and_runtime_are_forbidden(self):
        for path in ['ROADMAP.MD','notes/RoAdMaP.Md','api_key.txt','private/key.txt','runtime.json','ffmpeg.exe','x/y.sqlite','.git/config','tasks.sqlite-wal','private.pfx','output.mov']:
            self.assertTrue(guard.private_path(path),path)

    def test_source_attribution_and_license_cannot_disappear(self):
        files=fixture();files['LICENSE.txt']=b'changed'
        self.assertTrue(guard.check_files(files,complete=True))
        files=fixture();files['README.md']=b'uncredited work'
        self.assertTrue(guard.check_files(files,complete=True))

    def test_personal_reference_cannot_replace_original_package_media(self):
        files=fixture();name=next(n for n in files if n.endswith('.mp4'));files[name]=b'personal output'
        self.assertTrue(guard.check_files(files,complete=True))

    def test_secret_values_are_suppressed(self):
        files=fixture();value=b'OFFLINE_ONLY_'+b'Z'*32
        files['README.md']+=b' '+value
        errors=guard.check_files(files,complete=True,keys=[value])
        self.assertTrue(errors);self.assertNotIn(value.decode(),' '.join(errors))

    def test_archive_uses_only_manifest_and_excludes_local_tools_and_key(self):
        with tempfile.TemporaryDirectory(prefix='troublemaker-release-test-') as directory:
            root=Path(directory).resolve();source=root/'source';source.mkdir()
            for name,data in fixture().items():
                p=source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
            (source/'ffmpeg.exe').write_bytes(b'local optional binary')
            (source/'api_key.txt').write_bytes(b'not a real credential')
            output=root/'release/troublemaker-character-replacement.zip'
            result=build_release.build(source,output)
            self.assertEqual(result['members'],len(fixture()))
            with zipfile.ZipFile(output) as archive:
                self.assertFalse(any(n.endswith('.exe') or n.endswith('/api_key.txt') for n in archive.namelist()))
                self.assertIn('troublemaker-character-replacement/LICENSE.txt',archive.namelist())
            with self.assertRaises(ValueError):build_release.build(source,output)


if __name__=='__main__':unittest.main(verbosity=2)
