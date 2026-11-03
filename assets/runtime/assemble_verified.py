"""Evidence-bound assembly. No cloud calls; only a proven complete silent file is reusable."""
from pathlib import Path
from fractions import Fraction
import argparse, hashlib, json, os, shutil, subprocess, uuid
import av
from PIL import Image
from apt_media_tools import encoder_tool, resolve_tool
from review_contract import validate_selection_evidence
from strict_video_frames import strict_frames, constrain_child

P = Path(__file__).resolve().parent
E = P / '制作分析'
FPS = Fraction(24)
W, H = 1920, 1078
VERSION = 2


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(2 ** 20), b''): digest.update(block)
    return digest.hexdigest()


def object_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def project_file(path):
    path = Path(path)
    path = (P / path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_relative_to(P.resolve()) or not path.is_file():
        raise ValueError('Selected media must exist inside this project')
    return path


def source_file(segment):
    matches = list((P / '补齐生成用').glob(segment + ' *.mp4'))
    if len(matches) != 1: raise ValueError('Missing/ambiguous source segment ' + segment)
    return matches[0].resolve()


def owner_table():
    rows = []
    for line in (P / '补齐生成用/原始帧数.txt').read_text(encoding='utf-8-sig').splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0].endswith('.mp4'): rows.append((fields[0][:3], int(fields[1])))
    if [n for n, _ in rows] != [f'{i:03d}' for i in range(1, 103)] or sum(k for _, k in rows) != 4779:
        raise ValueError('Source 102 segments and 4779 owners must remain exact')
    return rows


def media_clock(path):
    """Complete decoded PTS proof, cached by media bytes and checker/libav identity."""
    path = Path(path)
    contract = {'version': VERSION, 'checker_sha256': sha(__file__), 'video_sha256': sha(path),
                'av_version': av.__version__, 'libav_versions': {k: list(v) for k, v in av.library_versions.items()}}
    cache = E / 'assembly-media-cache' / (object_sha(contract) + '.json')
    if cache.is_file():
        try:
            saved = read(cache); result = saved['proof']
            if (saved.get('contract') == contract and saved.get('proof_sha256') == object_sha(result)
                    and result.get('status') == 'passed' and type(result.get('frames')) is int
                    and result['frames'] > 0 and result.get('fps') == '24/1'):
                return result
        except (OSError, ValueError, KeyError, TypeError): pass
    with av.open(str(path)) as container:
        if len(container.streams.video) != 1: raise ValueError('Expected one video stream')
        stream = container.streams.video[0]; stream.codec_context.thread_count = 1
        count = 0; first = None
        for count, frame in enumerate(container.decode(stream), 1):
            if frame.pts is None or frame.time_base is None: raise ValueError('Missing actual frame timestamp')
            timestamp = Fraction(frame.pts) * frame.time_base
            if first is None: first = timestamp
            if timestamp - first != Fraction(count - 1) / FPS: raise ValueError('Actual output clock differs')
        if count == 0 or stream.average_rate != FPS: raise ValueError('Empty video or non-24fps actual clock')
        result = {'status': 'passed', 'video_sha256': contract['video_sha256'], 'frames': count,
                  'fps': '24/1', 'first_pts': str(first), 'canvas': [stream.width, stream.height]}
    write(cache, {'contract': contract, 'proof': result, 'proof_sha256': object_sha(result)})
    return result


def validate_selection(selection):
    table = owner_table()
    if set(selection['segments']) != {n for n, _ in table}: raise ValueError('Missing/extra source segment')
    sources = {n: source_file(n) for n, _ in table}
    source_hashes = {sha(path) for path in sources.values()}
    rows, clocks, start = [], {}, 0
    for segment, keep in table:
        item = selection['segments'][segment]; owners = item.get('owners', [])
        if (len(owners) != keep or any(type(o.get('source_frame')) is not int for o in owners)
                or [o['source_frame'] for o in owners] != list(range(keep))):
            raise ValueError('Every source frame must have exactly one owner ' + segment)
        for owner in owners:
            if str(project_file(owner['path'])) != owner['path']:
                raise ValueError('Owner paths must be canonical absolute project paths')
        if segment == '028':
            if any(Path(o['path']) != sources[segment] or o['output_frame'] != o['source_frame'] for o in owners):
                raise ValueError('028 passthrough identity changed')
            proof = None
        else:
            proof = validate_selection_evidence(P, item, owners, sources[segment])
        cuts = item.get('cut_pairs', [])
        if not isinstance(cuts, list): raise ValueError('cut_pairs must be a list')
        if cuts and (proof is None or proof.get('cut_pairs') != cuts):
            raise ValueError('Measured cuts must be bound to the reviewed evidence')
        paths = {o['path'] for o in owners}
        for cut in cuts:
            if (cut.get('path') not in paths or type(cut.get('source_before')) is not int
                    or type(cut.get('output_before')) is not int
                    or not 0 < cut['source_before'] < keep or cut['output_before'] <= 0):
                raise ValueError('Invalid measured internal cut')
        if segment == '067':
            if keep != 124: raise ValueError('067 source ownership must be 44 + 80 frames')
            for path in paths:
                phases = {o['source_frame'] >= 44 for o in owners if o['path'] == path}
                if len(phases) == 2 and sum(c['path'] == path and c['source_before'] == 44 for c in cuts) != 1:
                    raise ValueError('067 candidate spanning source frame 44 needs one measured cut pair')
        if segment == '102':
            transition = proof.get('native_transition_review', {})
            if keep != 135 or transition.get('status') != 'passed' or transition.get('source_range') != [65, 81]:
                raise ValueError('102 original 65-81 dissolve needs bound native review and all 135 owners')
        last = {}
        for owner in owners:
            key = owner['path']
            if key not in clocks: clocks[key] = media_clock(key)
            clock = clocks[key]
            if clock['video_sha256'] != owner['sha256']: raise ValueError('Selected output bytes changed')
            if segment != '028' and clock['video_sha256'] in source_hashes:
                raise ValueError('Generated segment cannot use original source bytes, including renamed copies')
            frame = owner['output_frame']
            if type(frame) is not int or not 0 <= frame < clock['frames']:
                raise ValueError('Outside actual output clock ' + segment)
            if key in last and frame < last[key]: raise ValueError('Reverse source action ' + segment)
            last[key] = frame
            for cut in cuts:
                if key == cut['path']:
                    if cut['output_before'] >= clock['frames']: raise ValueError('Measured cut lies outside actual output')
                    if (owner['source_frame'] >= cut['source_before']) != (frame >= cut['output_before']):
                        raise ValueError('Mapping crosses measured internal cut ' + segment)
        rows.append({'segment': segment, 'first_frame': start, 'end_exclusive': start + keep,
                     'keep': keep, 'owners': owners, 'actual1x': 'pending'})
        start += keep
    return rows


def fit(image):
    if image.size == (W, H): return image
    scale = min(W / image.width, H / image.height)
    width = max(2, int(image.width * scale) // 2 * 2); height = max(2, int(image.height * scale) // 2 * 2)
    result = Image.new('RGB', (W, H), 'black')
    result.paste(image.resize((width, height), Image.Resampling.LANCZOS), ((W - width) // 2, (H - height) // 2))
    return result


def selected_frames(row):
    wanted = {}
    for owner in row['owners']: wanted.setdefault(owner['path'], set()).add(owner['output_frame'])
    frames = {}
    for path, indices in wanted.items():
        for index, image in enumerate(strict_frames(path)):
            if index in indices: frames[(path, index)] = fit(image).tobytes()
        if any((path, index) not in frames for index in indices): raise ValueError('Missing actual selected frame')
    for owner in row['owners']: yield frames[(owner['path'], owner['output_frame'])]


def settings():
    return {'canvas': [W, H], 'fps': '24/1', 'codec': 'libx264', 'crf': 10, 'preset': 'slow',
            'threads': 4, 'pixel_format': 'yuv420p', 'timescale': 24000,
            'movflags': '+frag_keyframe+empty_moov+default_base_moof+negative_cts_offsets',
            'fit': 'aspect-preserving complete-frame fit, black padding', 'version': VERSION}


def tool_identity(tool):
    tool = Path(tool).resolve()
    if not tool.is_file(): raise ValueError('Encoder executable is missing')
    version = subprocess.run([str(tool), '-version'], capture_output=True, check=True, timeout=30)
    return {'path': str(tool), 'sha256': sha(tool), 'version_sha256': hashlib.sha256(version.stdout).hexdigest()}


def encode_rows(rows, output, encoder, log_path, progress_path):
    sent = 0; expected = sum(row['keep'] for row in rows); output = Path(output)
    if output.exists(): raise ValueError('Encoder output exists; partial files are not resumable')
    with Path(log_path).open('wb') as log:
        proc = subprocess.Popen([str(encoder), '-nostdin', '-v', 'error', '-n', '-filter_threads', '1',
            '-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', f'{W}x{H}', '-framerate', '24',
            '-i', 'pipe:0', '-an', '-c:v', 'libx264', '-threads', '4', '-preset', 'slow', '-crf', '10',
            '-pix_fmt', 'yuv420p', '-fps_mode', 'passthrough', '-video_track_timescale', '24000',
            '-movflags', '+frag_keyframe+empty_moov+default_base_moof+negative_cts_offsets', str(output)], stdin=subprocess.PIPE, stderr=log)
        constrain_child(proc)
        try:
            for row in rows:
                before = sent
                for pixels in selected_frames(row):
                    if len(pixels) != W * H * 3: raise ValueError('Selected frame has unexpected dimensions')
                    proc.stdin.write(pixels); sent += 1
                if sent - before != row['keep']: raise ValueError('Owner count changed during encode')
                write(progress_path, {'status': 'encoding', 'sent_frames': sent, 'expected_frames': expected,
                    'last_complete_segment': row['segment'], 'partial': str(output), 'automatic_resume_supported': False})
            proc.stdin.close(); code = proc.wait()
            if code != 0 or sent != expected: raise ValueError('Incomplete local encode')
        except BaseException:
            try:
                if not proc.stdin.closed: proc.stdin.close()
            except (BrokenPipeError, OSError): pass
            if proc.poll() is None: proc.terminate()
            code = proc.wait()
            write(progress_path, {'status': 'failed', 'sent_frames': sent, 'expected_frames': expected,
                'encoder_returncode': code, 'partial': str(output), 'automatic_resume_supported': False})
            raise
    write(progress_path, {'status': 'encoded', 'sent_frames': sent, 'expected_frames': expected,
                         'encoder_returncode': code, 'partial': str(output)})


def strict_decode(path, decoder):
    with subprocess.Popen([str(decoder), '-nostdin', '-v', 'error', '-xerror', '-threads', '1',
        '-i', str(path), '-map', '0:v:0', '-map', '0:a:0?', '-threads', '1', '-f', 'null', '-'],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE) as proc:
        constrain_child(proc); _, error = proc.communicate()
        if proc.returncode or error.strip(): raise ValueError('Strict local decode failed; do not regenerate cloud media')


def verify_encoded(path, count, decoder, zero_start=False):
    clock = media_clock(path)
    # Fragmented silent MP4 can have a B-frame decode lead-in. Remux normalizes
    # presentation zero without another encode; final output must start at zero.
    if (clock['frames'] != count or clock['canvas'] != [W, H]
            or zero_start and Fraction(clock['first_pts']) != 0):
        raise ValueError('Encoded frame count/clock/canvas mismatch: ' + json.dumps(clock))
    strict_decode(path, decoder)
    return clock


def smoke_rows(rows):
    by_id = {row['segment']: row for row in rows}; picked = []
    for segment in [rows[0]['segment'], '067', rows[-1]['segment']]:
        if segment not in by_id: raise ValueError('Smoke test needs first, 067 and last source segments')
        if segment not in picked: picked.append(segment)
    for row in reversed(rows):
        if sum(by_id[n]['keep'] for n in picked) >= 260: break
        if row['segment'] not in picked: picked.append(row['segment'])
    if sum(by_id[n]['keep'] for n in picked) < 260: raise ValueError('Smoke test needs at least 260 selected frames')
    return [row for row in rows if row['segment'] in picked]


def assembly_binding(selection, encoder):
    return {'selection_sha256': object_sha(selection), 'encoder': tool_identity(encoder),
            'settings': settings(), 'assembler_sha256': sha(__file__)}


def encoder_smoke(rows, binding, encoder, decoder):
    sample = smoke_rows(rows); count = sum(row['keep'] for row in sample)
    contract = {'binding': binding, 'segments': [r['segment'] for r in sample], 'frames': count, 'decoder': tool_identity(decoder)}
    directory = E / 'encoder-smoke'; directory.mkdir(parents=True, exist_ok=True)
    key = object_sha(contract); proof_path = directory / (key + '.json')
    if proof_path.is_file():
        try:
            proof = read(proof_path); output = directory / proof['output_name']
            if (proof.get('contract') == contract and proof.get('status') == 'passed' and output.is_file()
                    and sha(output) == proof.get('output_sha256') and proof.get('clock', {}).get('frames') == count): return proof
        except (ValueError, KeyError, OSError, TypeError): pass
    output = directory / (key + '.' + uuid.uuid4().hex + '.mp4')
    encode_rows(sample, output, encoder, output.with_suffix('.log'), output.with_suffix('.progress.json'))
    clock = verify_encoded(output, count, decoder)
    proof = {'status': 'passed', 'contract': contract, 'output_name': output.name, 'output_sha256': sha(output), 'clock': clock}
    write(proof_path, proof)
    return proof


def reusable_silent(path, proof_path, binding, expected_count):
    path, proof_path = Path(path), Path(proof_path)
    if not path.is_file() or not proof_path.is_file(): raise ValueError('Complete silent file and validation proof are required')
    proof = read(proof_path); clock = proof.get('clock', {}); current_sha = sha(path)
    if (proof.get('status') != 'passed' or proof.get('binding') != binding or proof.get('silent_sha256') != current_sha
            or clock.get('video_sha256') != current_sha
            or proof.get('strict_decode') != 'passed' or clock.get('frames') != expected_count
            or clock.get('canvas') != [W, H] or clock.get('fps') != '24/1'
            or not isinstance(clock.get('first_pts'), str)):
        raise ValueError('Silent encode is incomplete, changed or belongs to another selection/settings')
    try: Fraction(clock['first_pts'])
    except (ValueError, ZeroDivisionError): raise ValueError('Silent timestamp proof is invalid')
    return proof


def audio_payload(path):
    digest = hashlib.sha256(); count = 0
    with av.open(str(path)) as container:
        if len(container.streams.audio) != 1: raise ValueError('Expected exactly one original AAC stream')
        stream = container.streams.audio[0]
        if stream.codec_context.name != 'aac': raise ValueError('Original audio must remain AAC')
        for packet in container.demux(stream):
            data = bytes(packet)
            if not data: continue
            digest.update(len(data).to_bytes(8, 'big')); digest.update(data); count += 1
    if count == 0: raise ValueError('Empty AAC payload')
    return {'packets': count, 'ordered_payload_sha256': digest.hexdigest()}


def remux(silent, final, encoder, decoder, count):
    final = Path(final)
    if final.exists(): raise ValueError('Preserve previous final; use a new version name')
    audio = P / '原片音轨.m4a'; before = audio_payload(audio)
    license_text = (P / 'LICENSE.txt').read_text(encoding='utf-8-sig').strip()
    partial = final.with_name(final.stem + '-mux.' + uuid.uuid4().hex + '.partial.mp4')
    metadata = {'title': 'TroubleMaker replacement (Made by wuwukasi)', 'artist': 'wuwukasi',
                'comment': 'Made by wuwukasi; character replacement T8star',
                'copyright': 'Made by wuwukasi', 'description': license_text}
    command = [str(encoder), '-nostdin', '-v', 'error', '-n', '-i', str(silent), '-i', str(audio),
               '-map', '0:v:0', '-map', '1:a:0', '-c', 'copy']
    for field, value in metadata.items(): command += ['-metadata', field + '=' + value]
    # Already aligned audio: no -shortest, no second trim.
    command += ['-movflags', '+faststart', str(partial)]
    result = subprocess.run(command, capture_output=True)
    if result.returncode:
        (E / (final.stem + '-mux-failure.log')).write_bytes(result.stderr)
        raise ValueError('Local mux failed; validated silent video remains reusable')
    clock = verify_encoded(partial, count, decoder, zero_start=True); after = audio_payload(partial)
    if after != before: raise ValueError('Final AAC packet payload differs from original')
    with av.open(str(partial)) as container:
        if any(container.metadata.get(k) != v for k, v in metadata.items()): raise ValueError('Author/license metadata differs')
    partial.replace(final)
    return {'clock': clock, 'audio_payload': after, 'metadata': metadata}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', type=Path, default=E / 'selected-candidates.json')
    parser.add_argument('--name', default='TroubleMaker_换角_v1'); parser.add_argument('--plan-only', action='store_true')
    parser.add_argument('--encoder', type=Path); args = parser.parse_args()
    if not args.name or Path(args.name).name != args.name or any(c in args.name for c in '/\\:'):
        raise ValueError('Output name must be a filename, not a path')
    E.mkdir(parents=True, exist_ok=True); selection = read(args.selection); rows = validate_selection(selection)
    count = sum(row['keep'] for row in rows)
    write(E / (args.name + '-frame-plan.json'), {'segments': rows, 'source_frames': count, 'fps': 24,
        'duration_seconds': count / 24, 'canvas': [W, H], 'settings': settings(), 'video_encodes': 1, 'actual1x_full_film': 'pending'})
    if args.plan_only:
        print('Validated 102 segments and 4779 exact source owners. No encode or network call.'); return
    encoder = str(args.encoder.resolve()) if args.encoder else encoder_tool(P); decoder = resolve_tool(P, 'ffmpeg')
    binding = assembly_binding(selection, encoder); out = P / '成片'; out.mkdir(exist_ok=True)
    silent = out / (args.name + '-silent.mp4'); silent_proof = E / (args.name + '-silent-proof.json'); final = out / (args.name + '.mp4')
    if final.exists(): raise ValueError('Preserve existing final; use a new version name')
    if silent.exists(): reusable_silent(silent, silent_proof, binding, count)
    else:
        encoder_smoke(rows, binding, encoder, decoder)
        partial = out / (args.name + '-silent.' + uuid.uuid4().hex + '.partial.mp4')
        encode_rows(rows, partial, encoder, E / (args.name + '-encoder.log'), E / (args.name + '-progress.json'))
        clock = verify_encoded(partial, count, decoder); partial.replace(silent)
        write(silent_proof, {'status': 'passed', 'binding': binding, 'silent_sha256': sha(silent),
                            'clock': clock, 'strict_decode': 'passed', 'decoder': tool_identity(decoder)})
    result = remux(silent, final, encoder, decoder, count)
    shutil.copy2(P / 'LICENSE.txt', out / 'LICENSE.txt')
    write(E / (args.name + '-verification.json'), {'path': str(final), 'sha256': sha(final), 'frames': count,
        'fps': 24, 'duration_seconds': count / 24, 'strict_decode': 'passed', 'exact_pts': 'passed', 'canvas': [W, H],
        'video_encodes': 1, 'audio': 'original ordered AAC payload copied from zero and compared', **result,
        'native_joins': 'pending', 'actual1x_full_film': 'pending', 'binding': binding})
    print(str(final), flush=True)


if __name__ == '__main__': main()
