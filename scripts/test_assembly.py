"""Offline fault regressions; synthetic media only, never finished production footage."""
from pathlib import Path
from fractions import Fraction
import copy
import importlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import av
from PIL import Image

RUNTIME = Path(__file__).resolve().parents[1] / 'assets/runtime'
sys.path.insert(0, str(RUNTIME))
assembly = importlib.import_module('assemble_verified')
strict = importlib.import_module('strict_video_frames')
review = importlib.import_module('review_contract')


def video(path, frames=24, rate=24, color=45):
    with av.open(str(path), 'w') as output:
        stream = output.add_stream('libx264', rate=rate)
        stream.width, stream.height, stream.pix_fmt = 64, 36, 'yuv420p'
        stream.options = {'preset': 'ultrafast', 'crf': '18'}
        for index in range(frames):
            image = Image.new('RGB', (64, 36), ((color + index) % 240, color, 80))
            frame = av.VideoFrame.from_image(image)
            frame.pts, frame.time_base = index, Fraction(1, rate)
            for packet in stream.encode(frame): output.mux(packet)
        for packet in stream.encode(): output.mux(packet)
    return path


class AssemblyRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='troublemaker-assembly-test-')
        self.root = Path(self.temp.name).resolve()
        self.evidence = self.root / '制作分析'
        self.evidence.mkdir()
        (self.root / '补齐生成用').mkdir()
        (self.root / '替换用参考图').mkdir()
        for role in '一二':
            Image.new('RGB', (8, 8), 'red' if role == '一' else 'green').save(self.root / f'替换用参考图/{role}号.png')
        self.context = patch.multiple(assembly, P=self.root, E=self.evidence, W=64, H=36)
        self.context.start()
        self.strict_context = patch.object(strict, 'P', self.root)
        self.strict_context.start()
        self.tool = shutil.which('ffmpeg')
        if self.tool:
            assembly.write(self.root / 'runtime.json', {'ffmpeg_path': self.tool, 'encoder_path': self.tool})

    def tearDown(self):
        self.strict_context.stop(); self.context.stop(); self.temp.cleanup()

    def selection(self, segment='001', frames=24, candidate=None, extras=None):
        source = self.root / '补齐生成用' / f'{segment} {frames}.mp4'
        if not source.exists(): source.write_bytes(b'source-fact-' + segment.encode())
        candidate = candidate or video(self.root / f'{segment}-candidate.mp4', frames)
        owners = [{'source_frame': i, 'path': str(candidate.resolve()), 'output_frame': i,
                   'sha256': assembly.sha(candidate)} for i in range(frames)]
        item = {'owners': owners}
        self.bind(item, source, extras or {})
        return {'segments': {segment: item}}, source

    def bind(self, item, source, extras=None):
        owners = item['owners']
        proof = {'schema_version': 1, 'status': 'passed', 'reviewer': 'offline-test-fixture',
                 'findings': 'Synthetic regression evidence, not an actual visual approval.',
                 'source_sha256': assembly.sha(source), 'reference_sha256_by_role': review.references(self.root),
                 'candidate_sha256_by_path': {o['path']: o['sha256'] for o in owners},
                 'owners_sha256': assembly.object_sha(owners), 'native_review': 'passed',
                 'action_review': 'passed', 'output_clock_review': 'passed', **(extras or {})}
        path = self.evidence / (source.stem[:3] + '-review.json')
        assembly.write(path, proof)
        item['review_evidence'] = {'path': str(path), 'sha256': assembly.sha(path)}

    def validate(self, selection, table):
        with patch.object(assembly, 'owner_table', return_value=table):
            return assembly.validate_selection(selection)

    def test_missing_segment_rejected(self):
        with patch.object(assembly, 'owner_table', return_value=[('001', 24), ('002', 24)]):
            with self.assertRaisesRegex(ValueError, 'Missing/extra'):
                assembly.validate_selection({'segments': {'001': {}}})

    def test_stale_reference_and_owner_map_cannot_inherit_passed(self):
        selection, _ = self.selection()
        self.assertEqual(self.validate(selection, [('001', 24)])[0]['keep'], 24)
        changed = copy.deepcopy(selection)
        changed['segments']['001']['owners'][3]['output_frame'] = 2
        with self.assertRaisesRegex(ValueError, 'mapping changed'):
            self.validate(changed, [('001', 24)])
        Image.new('RGB', (8, 8), 'blue').save(self.root / '替换用参考图/一号.png')
        with self.assertRaisesRegex(ValueError, 'current references'):
            self.validate(selection, [('001', 24)])

    def test_renamed_original_bytes_rejected_even_with_review(self):
        source = video(self.root / '补齐生成用/087 24.mp4')
        candidate = self.root / 'renamed-as-generated.mp4'; shutil.copyfile(source, candidate)
        selection, _ = self.selection('087', candidate=candidate)
        with self.assertRaisesRegex(ValueError, 'original source bytes'):
            self.validate(selection, [('087', 24)])

    def test_028_only_accepts_exact_source_owner(self):
        source = video(self.root / '补齐生成用/028 24.mp4')
        selection, _ = self.selection('028', candidate=source)
        self.assertEqual(self.validate(selection, [('028', 24)])[0]['keep'], 24)
        renamed = self.root / '028-copy.mp4'; shutil.copyfile(source, renamed)
        for owner in selection['segments']['028']['owners']: owner['path'] = str(renamed)
        with self.assertRaisesRegex(ValueError, '028 passthrough'):
            self.validate(selection, [('028', 24)])

    def test_067_cut_requires_bound_measured_pair(self):
        selection, source = self.selection('067', 124)
        item = selection['segments']['067']; candidate = item['owners'][0]['path']
        with self.assertRaisesRegex(ValueError, 'measured cut pair'):
            self.validate(selection, [('067', 124)])
        cuts = [{'path': candidate, 'source_before': 44, 'output_before': 44}]
        item['cut_pairs'] = cuts
        with self.assertRaisesRegex(ValueError, 'bound to the reviewed evidence'):
            self.validate(selection, [('067', 124)])
        self.bind(item, source, {'cut_pairs': cuts})
        self.assertEqual(self.validate(selection, [('067', 124)])[0]['keep'], 124)
        cuts[0]['output_before'] = 56
        self.bind(item, source, {'cut_pairs': cuts})
        with self.assertRaisesRegex(ValueError, 'crosses measured'):
            self.validate(selection, [('067', 124)])

    def test_067_separate_candidates_on_each_phase_allowed(self):
        selection, source = self.selection('067', 124)
        second = video(self.root / 'medium-only.mp4', 80, color=100)
        item = selection['segments']['067']
        for owner in item['owners'][44:]:
            owner.update(path=str(second), output_frame=owner['source_frame'] - 44, sha256=assembly.sha(second))
        self.bind(item, source)
        self.assertEqual(self.validate(selection, [('067', 124)])[0]['keep'], 124)

    def test_102_requires_native_transition_evidence(self):
        selection, source = self.selection('102', 135)
        with self.assertRaisesRegex(ValueError, '65-81 dissolve'):
            self.validate(selection, [('102', 135)])
        self.bind(selection['segments']['102'], source,
                  {'native_transition_review': {'status': 'passed', 'source_range': [65, 81]}})
        self.assertEqual(self.validate(selection, [('102', 135)])[0]['keep'], 135)

    def test_media_cache_avoids_decode_but_invalid_cache_rechecks(self):
        candidate = video(self.root / 'cached.mp4', 24)
        self.assertEqual(assembly.media_clock(candidate)['frames'], 24)
        with patch.object(av, 'open', side_effect=AssertionError('Should use byte-bound cache')):
            self.assertEqual(assembly.media_clock(candidate)['frames'], 24)
        cache = next((self.evidence / 'assembly-media-cache').glob('*.json'))
        data = assembly.read(cache); data['proof']['frames'] = 9; assembly.write(cache, data)
        self.assertEqual(assembly.media_clock(candidate)['frames'], 24)
        with self.assertRaisesRegex(ValueError, 'clock differs|non-24fps'):
            assembly.media_clock(video(self.root / '25fps.mp4', 25, rate=25))

    def test_partial_or_stale_silent_never_reused(self):
        candidate = video(self.root / 'silent.mp4', 24)
        clock = assembly.media_clock(candidate); binding = {'selection': 'A'}
        proof = self.evidence / 'silent-proof.json'
        assembly.write(proof, {'status': 'passed', 'binding': binding, 'silent_sha256': assembly.sha(candidate),
                              'clock': clock, 'strict_decode': 'passed'})
        self.assertEqual(assembly.reusable_silent(candidate, proof, binding, 24)['clock']['frames'], 24)
        with self.assertRaises(ValueError): assembly.reusable_silent(candidate, proof, {'selection': 'B'}, 24)
        with self.assertRaises(ValueError): assembly.reusable_silent(candidate, proof, binding, 4779)
        candidate.write_bytes(candidate.read_bytes()[:len(candidate.read_bytes()) // 2])
        with self.assertRaises(ValueError): assembly.reusable_silent(candidate, proof, binding, 24)

    def test_real_smoke_fit_pipeline_cache_and_audio_remux(self):
        if not self.tool: self.skipTest('Local FFmpeg unavailable')
        candidate = video(self.root / 'synthetic-action.mp4', 135)
        rows = [{'segment': n, 'keep': count,
                 'owners': [{'path': str(candidate), 'output_frame': i} for i in range(count)]}
                for n, count in [('001', 4), ('067', 124), ('102', 135)]]
        binding = assembly.assembly_binding({'synthetic': True}, self.tool)
        smoke = assembly.encoder_smoke(rows, binding, self.tool, self.tool)
        self.assertEqual(smoke['clock']['frames'], 263)
        with patch.object(assembly, 'encode_rows', side_effect=AssertionError('Smoke should be cached')):
            self.assertEqual(assembly.encoder_smoke(rows, binding, self.tool, self.tool)['clock']['frames'], 263)
        silent = self.evidence / 'encoder-smoke' / smoke['output_name']
        subprocess.run([self.tool, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
                        '-c:a', 'aac', str(self.root / '原片音轨.m4a')], check=True, capture_output=True)
        (self.root / 'LICENSE.txt').write_text('Made by wuwukasi', encoding='utf-8')
        final = self.root / 'synthetic-remux.mp4'
        unchanged = assembly.sha(silent)
        with patch.object(assembly.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stderr=b'injected mux failure')):
            with self.assertRaisesRegex(ValueError, 'validated silent'):
                assembly.remux(silent, final, self.tool, self.tool, 263)
        self.assertEqual(assembly.sha(silent), unchanged)
        self.assertFalse(final.exists())
        with patch.object(assembly, 'encode_rows', side_effect=AssertionError('Mux retry must not encode again')):
            result = assembly.remux(silent, final, self.tool, self.tool, 263)
        self.assertEqual(result['clock']['frames'], 263)  # Short AAC must not cut video.
        self.assertEqual(assembly.audio_payload(final), assembly.audio_payload(self.root / '原片音轨.m4a'))
        self.assertEqual(result['metadata']['artist'], 'wuwukasi')

    def test_encoder_failure_keeps_partial_but_never_passes(self):
        if not self.tool: self.skipTest('Local FFmpeg unavailable')
        output = self.root / 'broken.partial.mp4'
        progress = self.evidence / 'broken-progress.json'
        with patch.object(assembly, 'selected_frames', return_value=iter([b'truncated-pixels'])):
            with self.assertRaisesRegex(ValueError, 'unexpected dimensions'):
                assembly.encode_rows([{'segment': '001', 'keep': 1}], output, self.tool,
                                     self.evidence / 'broken.log', progress)
        record = assembly.read(progress)
        self.assertEqual(record['status'], 'failed')
        self.assertFalse(record['automatic_resume_supported'])
        with self.assertRaises(ValueError):
            assembly.reusable_silent(output, self.evidence / 'nonexistent-proof.json', {}, 1)


if __name__ == '__main__': unittest.main(verbosity=2)
