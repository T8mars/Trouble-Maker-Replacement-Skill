"""TroubleMaker production adapter; shared-ledger transport, immutable approvals."""
from pathlib import Path
from fractions import Fraction
import argparse
import json
import os
import re
import subprocess
import time
import urllib.error
import rh_core as rh
import channels
import source_config as source
from apt_media_tools import resolve_tool

P = Path(__file__).resolve().parent
TERMINAL = ('DOWNLOADED', 'VISUAL_FAILED', 'RESULTS_MISSING')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
    os.replace(temp, path)


def private_path(value):
    path = Path(value).resolve()
    skill = read(P/'runtime.json').get('installed_skill_directory')
    if path.is_relative_to(P) or skill and path.is_relative_to(Path(skill).resolve()):
        raise ValueError('Credentials and account ledger must stay outside run and skill')
    return path


def ledger_path():
    return private_path(read(P/'runtime.json').get('ledger_file') or rh.default_private()/'tasks.sqlite')


def key():
    if os.environ.get('RH_API_KEY', '').strip():
        return os.environ['RH_API_KEY'].strip()
    value = os.environ.get('RH_API_KEY_FILE') or read(P/'runtime.json').get('api_key_file')
    if not value:
        raise ValueError('Configure an explicit private RunningHub key file or RH_API_KEY')
    path = private_path(value)
    value = path.read_text(encoding='utf-8-sig').strip()
    if not value:
        raise ValueError('Private RunningHub key is empty')
    return value


def original_segment(entry):
    segment = entry.get('source_segment', entry['window_id'])
    if segment not in source.CAST:
        raise ValueError('Unknown generation segment, or passthrough segment')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', entry['window_id']):
        raise ValueError('Candidate ID must be a plain directory name')
    return segment


def edit_roles(entry):
    segment = original_segment(entry)
    project=P
    contract_path=project/'source-contract.json'
    if contract_path.is_file():
        source_contract=read(contract_path)
        original_file=next((project/'补齐生成用').glob(segment+' *.mp4'))
        relative=original_file.relative_to(project).as_posix()
        if rh.sha(original_file)!=source_contract['bound_files'].get(relative):
            raise ValueError('Source bytes changed; re-analyse instead of reusing this source contract')
        expected_risk=source_contract.get('risk_classes',{}).get(segment,'ordinary')
        if entry.get('risk_class','ordinary')!=expected_risk:
            raise ValueError('Known high-risk source requires its own reviewed pilot route')
    roles = entry.get('edit_roles', source.CAST[segment])
    if not isinstance(roles,str) or not roles or len(set(roles))!=len(roles) or any(r not in source.CAST[segment] for r in roles):
        raise ValueError('Edited roles must be a nonempty subset of the actual source CAST')
    return roles


def input_digest(project, entry):
    project = Path(project).resolve()
    segment = original_segment(entry)
    files = [entry['video_path'], entry['prompt_path'],
             *entry['reference_paths'], f'补齐生成用/{segment}.txt']
    native = channels.selected(project) == 'rh'
    if native:
        files.append(entry['schema_path'])
    files += [f'替换用参考图/{role}号.png' for role in source.CAST[segment]]
    original = list((project/'补齐生成用').glob(segment+' *.mp4'))
    if len(original) != 1:
        raise ValueError('Ambiguous source segment')
    files.append(original[0].relative_to(project).as_posix())
    if entry.get('source_contract_path'):
        contract = read(rh.asset(project, entry['source_contract_path']))
        files += [entry['source_contract_path'], *contract.get('dependency_paths', [])]
    return rh.digest_object({'files': {name: rh.sha(rh.asset(project, name)) for name in sorted(set(files))},
        'contract': {k: v for k, v in entry.items() if k not in ('input_digest', 'semantic_review', 'retry_after')},
        'cast': source.CAST[segment], 'application_config': source.app_config() if native else entry['profile'],
        'appearance_policy':read(project/'runtime.json').get('appearance_policy',{}),
        'source_contract_sha256':rh.sha(project/'source-contract.json') if (project/'source-contract.json').is_file() else None})


def validate(project, entry, require_approval=True):
    project = Path(project).resolve()
    if project != P:
        raise ValueError('Run path mismatch')
    cfg = read(P/'runtime.json')
    segment = original_segment(entry)
    if cfg.get('reference_selection') != 'provided-two':
        raise ValueError('Current two identities have not been selected')
    if require_approval and cfg.get('appearance_policy',{}).get('style')=='pending':
        raise ValueError('Record the current user style instruction before paid submission')
    roles = edit_roles(entry)
    if roles != source.CAST[segment]:
        if not entry.get('source_contract_path'):
            raise ValueError('A staged single-role repair needs its reviewed identity-bearing input contract')
        staged = read(rh.asset(P,entry['source_contract_path']))
        if (staged.get('edit_roles') != roles or staged.get('preserved_roles') != ''.join(r for r in source.CAST[segment] if r not in roles)
            or staged.get('preserved_identity_review') != 'passed' or not staged.get('preserved_identity_evidence')
            or staged.get('input_candidate_sha256') != rh.sha(rh.asset(P,entry['video_path']))):
            raise ValueError('Preserved identity/source motion must be observed and bound to actual input bytes')
        from review_contract import validate_preserved
        validate_preserved(P, staged, entry, source.CAST[segment])
    expected = [f'替换用参考图/{role}号.png' for role in roles]
    if len(entry['reference_paths']) != len(expected):
        raise ValueError('Partial edge roles still require their reference slot')
    native = channels.selected(P) == 'rh'
    if native:
        if entry['profile']['kind'] != 'legacy-ai-app':
            raise ValueError('This adapter only implements the verified RunningHub AI application')
        if source.app_config()['模式'] != 'ai':
            raise ValueError('CN endpoint requires a separately verified transport; do not silently use AI')
        app = '2107845954833907713' if len(roles) == 2 else '2107844752011010050'
        if entry['profile']['app_id'] != app:
            raise ValueError('Application does not match role count')
        rh.legacy_resolution_nodes(entry['profile'])
    else:
        channels.wire_frames(P, entry, roles)
    if not entry.get('pilot'):
        route = pilot_route(entry, cfg)
        passed = cfg.get('pilot_reviews', {}).get(route, {})
        if passed.get('status') != 'passed' or not passed.get('notes') or passed.get('route') != route:
            raise ValueError('This role/backend route needs an actually reviewed pilot before batching')
        output = Path(passed.get('output', ''))
        if not output.is_file() or rh.sha(output) != passed.get('output_sha256'):
            raise ValueError('Pilot approval is not bound to its actual current output')
    if native:
        fields = {(str(x['nodeId']), x['fieldName']) for x in read(rh.asset(P, entry['schema_path']))['data']['nodeInfoList']}
        required = {('137','image'), ('138','value'), ('321','video'), ('326','value')}
        required |= {(n['nodeId'], n['fieldName']) for n in rh.legacy_resolution_nodes(entry['profile'])}
        if len(roles) == 2:
            required.add(('139','image'))
        if not required <= fields:
            raise ValueError('Public schema no longer supports required fields')
    for uploaded, full in zip(entry['reference_paths'], expected):
        if uploaded == full:
            continue
        crop = entry.get('reference_crops', {}).get(uploaded, {})
        if crop.get('source_path') != full or crop.get('source_sha256') != rh.sha(rh.asset(P, full)):
            raise ValueError('Reference crop lost original identity/order provenance')
        from PIL import Image
        with Image.open(rh.asset(P, full)) as original, Image.open(rh.asset(P, uploaded)) as actual:
            box = crop['crop']
            if len(box) != 4 or not all(type(x) is int for x in box) or not 0 <= box[0] < box[2] <= original.width or not 0 <= box[1] < box[3] <= original.height:
                raise ValueError('Invalid raw-pixel crop')
            wanted = original.convert('RGB').crop(tuple(box))
            if actual.size != wanted.size or actual.convert('RGB').tobytes() != wanted.tobytes():
                raise ValueError('Reference crop is not exact original pixels')
    frames = entry['generation_frames']
    fps = Fraction(str(entry['generation_fps']))
    if segment=='087' and frames==23:
        raise ValueError('087 source has 23 frames; use a reviewed derived 39-frame input (23 real frames + 16 final holds), then keep the 23 source owners')
    if type(frames) is not int or frames <= 0 or fps <= 0 or Fraction(frames)/fps > 10:
        raise ValueError('COMPLETE input, including context/holds, must be <=10seconds')
    original = next((P/'补齐生成用').glob(segment+' *.mp4'))
    if rh.asset(P, entry['video_path']) != original:
        if not entry.get('source_contract_path'):
            raise ValueError('Derived input requires its source/action contract')
        contract = read(rh.asset(P, entry['source_contract_path']))
        if contract.get('source_segment') != segment or not contract.get('method') or not contract.get('action_frames'):
            raise ValueError('Derived input must declare source, method and real action frames')
        if contract.get('source_action_review') != 'passed':
            raise ValueError('Context/holds/pose guides require explicit source action review')
    digest = input_digest(P, entry)
    if entry.get('input_digest') != digest:
        raise ValueError('Inputs changed; prepare and review the new immutable candidate')
    if require_approval:
        review = entry.get('semantic_review') or {}
        if cfg.get('production_authorized') is not True or not cfg.get('production_request'):
            raise ValueError('Record the existing user production request first')
        if entry['window_id'] not in cfg.get('approved_segments', []):
            raise ValueError('Candidate is not in the current approved queue')
        if review.get('status') != 'passed' or review.get('input_digest') != digest or not review.get('notes'):
            raise ValueError('Current digest-bound semantic review is missing')
    return digest


def pilot_route(entry, cfg=None):
    cfg = cfg or read(P/'runtime.json')
    return rh.digest_object({'profile':entry['profile'], 'roles':edit_roles(entry),
        'references':{r:rh.sha(P/f'替换用参考图/{r}号.png') for r in '一二'},
        'appearance_policy':cfg.get('appearance_policy',{}),
        'risk_class':entry.get('risk_class','ordinary'),
        'source_contract':rh.sha(P/'source-contract.json') if (P/'source-contract.json').is_file() else None, 'version':2})


def media_identity(entry):
    import av
    import sys
    # Semantic edits do not force another decode. The media checker/tool do.
    return {'video_sha256':rh.sha(rh.asset(P,entry['video_path'])),
        'frames':entry['generation_frames'], 'fps':str(Fraction(str(entry['generation_fps']))),
        'decoder_sha256':rh.sha(resolve_tool(P,'ffmpeg')), 'pyav':av.__version__,
        'pyav_libraries':str(av.library_versions), 'python':sys.version,
        'checker_sha256':rh.sha(Path(__file__)), 'version':2}


def media_proof_path(entry):
    return P/'制作分析/input-media-checks'/(rh.digest_object(media_identity(entry))+'.json')


def media_check(entry):
    import av
    path = rh.asset(P, entry['video_path'])
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        stream.codec_context.thread_count = 1
        timestamps = [Fraction(frame.pts)*frame.time_base if frame.pts is not None else None for frame in container.decode(stream)]
        fps = Fraction(str(entry['generation_fps']))
        if len(timestamps) != entry['generation_frames'] or stream.average_rate != fps:
            raise ValueError('Actual full input frame clock differs from declared clock')
        if not timestamps or any(t is None for t in timestamps) or any(t-timestamps[0] != Fraction(i)/fps for i,t in enumerate(timestamps)):
            raise ValueError('Complete input PTS must follow its declared constant frame clock')
        if timestamps[-1]-timestamps[0]+1/fps > 10:
            raise ValueError('Actual input duration exceeds10seconds')
    with av.open(str(path)) as container:
        if not container.streams.audio or next(container.decode(audio=0), None) is None:
            raise ValueError('Input must have decodable audio, including derived/cropped inputs')
    # Native decoder process faults are local read failures, never paid visual retries.
    # Preserve each strict failure and retry the same bytes on the known stable CPU set.
    from strict_video_frames import constrain_child
    decode_attempts=[]
    for local_attempt in range(3):
        proc=subprocess.Popen([resolve_tool(P,'ffmpeg'), '-nostdin','-v','error','-xerror','-threads','1','-filter_threads','1',
            '-i',str(path),'-map','0:v:0','-map','0:a:0','-threads','1','-f','null','-'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        constrain_child(proc)
        try: _,error=proc.communicate(timeout=180)
        except BaseException:
            proc.kill();proc.communicate();raise
        decode_attempts.append({'attempt':local_attempt+1,'returncode':proc.returncode,'error':error.decode('utf8',errors='replace')[:2000]})
        if proc.returncode==0 and not error.strip():break
    if len(decode_attempts)>1 or proc.returncode or error.strip():
        logs=P/'制作分析'/'decoder-logs';logs.mkdir(exist_ok=True)
        write(logs/(rh.sha(path)+'-media-check-attempts.json'),decode_attempts)
    if proc.returncode or error.strip():raise ValueError('Complete input strict decode failed after preserved local reads')
    if entry.get('input_digest'):
        cache = P/'制作分析'/'input-media-checks'
        cache.mkdir(parents=True,exist_ok=True)
        write(media_proof_path(entry), {**media_identity(entry),
            'constant_pts':'passed', 'decodable_audio':'passed', 'complete_strict_decode':'passed'})


def current_media_proof(entry):
    cache = media_proof_path(entry)
    if not cache.is_file():
        return False
    proof = read(cache)
    return (all(proof.get(k)==v for k,v in media_identity(entry).items())
        and all(proof.get(k)=='passed' for k in ('constant_pts','decodable_audio','complete_strict_decode')))


class StrictTransport(rh.Transport):
    @staticmethod
    def _verify_download(path):
        for _ in range(3):
            result = subprocess.run([resolve_tool(P,'ffmpeg'),'-nostdin','-v','error','-xerror',
                '-threads','1','-i',str(path),'-map','0:v:0','-threads','1','-f','null','-'], capture_output=True, timeout=180)
            if result.returncode == 0 and not result.stderr.strip():
                return
        raise ValueError('Strict download decode failed; preserve original paid task ID')


class FreshAssetRunner(rh.Runner):
    def upload(self, path, semantics):
        # Temporary node321 handles have expired before the old six-hour TTL.
        # Only NEW submissions upload fresh bytes. recover() never submits.
        return self.transport.upload(path)


def latest(ledger, account, window):
    return ledger.db.execute('SELECT * FROM attempts WHERE account=? AND project=? AND window=? ORDER BY created DESC,rowid DESC LIMIT 1',
        (account, str(P), window)).fetchone()


def tick(ledger, runner, entries, account='default'):
    # Query -> refill paid execution slots -> transfer. Large downloads do not starve generation.
    rows = ledger.db.execute('SELECT id FROM attempts WHERE account=? AND project=? AND state IN (?,?,?,?,?,?)',
        (account, str(P), *rh.POLLABLE)).fetchall()
    for row in rows:
        runner.recover(row['id'], defer_download=True)
    unknown = ledger.db.execute("SELECT 1 FROM attempts WHERE account=? AND state IN ('SUBMITTING','SUBMISSION_UNKNOWN')", (account,)).fetchone()
    if not unknown:
        cfg = read(P/'runtime.json')
        held = cfg.get('held_windows', {})
        accepted = cfg.get('accepted_segments', {})
        checked_accepted=set()
        # Keep the persisted queue immutable; priority only changes which NEW
        # candidate takes the next free account slot. Accepted task IDs recover above.
        for entry in sorted(entries, key=lambda item: item.get('priority', 100)):
            if entry['window_id'] in held:
                continue
            segment = entry.get('source_segment', entry['window_id'])
            if segment in accepted:
                from review_contract import validate_accepted
                if segment not in checked_accepted:
                    validate_accepted(P, accepted[segment])
                    checked_accepted.add(segment)
                continue
            a = ledger.account(account)
            if a['stopped'] or a['cooldown'] > ledger.clock() or ledger.summary(account)['active'] >= 3:
                break
            prior = latest(ledger, account, entry['window_id'])
            if prior and prior['digest'] != entry['input_digest']:
                raise ValueError('Never mutate an existing candidate ID; use a new candidate revision')
            if prior and prior['state'] in (*rh.ACTIVE, *rh.POLLABLE, *TERMINAL):
                continue
            try:
                aid = runner.submit_one(P, entry, validate)
                if aid and ledger.row(aid)['state'] in ('SUBMITTING','SUBMISSION_UNKNOWN'):
                    unknown = True
                    break
            except rh.ApiFailure as error:
                if error.code in rh.DEFERRED_CODES:
                    ledger.cooldown(account)
                    break
                if error.code in ('401','402','403','1913'):
                    ledger.stop(account)
                raise
            except (urllib.error.URLError, TimeoutError):
                ledger.cooldown(account)
                break
    rows = ledger.db.execute("SELECT id FROM attempts WHERE account=? AND project=? AND state IN ('RESULTS_READY','DOWNLOAD_FAILED') AND next_poll<=?",
        (account, str(P), ledger.clock())).fetchall()
    for row in rows:
        runner.recover(row['id'])
    return bool(unknown)


def snapshot(ledger, account='default'):
    rows = ledger.db.execute('SELECT id,window,state,task_id,output,digest,query_errors,download_errors FROM attempts WHERE account=? AND project=? ORDER BY created,rowid', (account,str(P))).fetchall()
    tasks = {r['window']: dict(r) for r in rows}
    a = ledger.account(account)
    state = {'tasks': tasks, 'account_cap': a['cap'], 'account_active': ledger.summary(account)['active'],
        'account_stopped': bool(a['stopped']), 'cooldown_seconds': max(0,int(a['cooldown']-ledger.clock())),
        'updated_epoch': ledger.clock()}
    cfg=read(P/'runtime.json')
    state['counts']={'submitted_candidates':sum(bool(r['task_id']) for r in tasks.values()),
        'downloaded_candidates':sum(r['state']=='DOWNLOADED' for r in tasks.values()),
        'registered_accepted_source_segments':len(cfg.get('accepted_segments',{})),
        'generation_source_segments':101,'passthrough_source_segments':1,
        'held_candidates':len(cfg.get('held_windows',{}))}
    write(P/'production-status.json', state)
    return state


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command', choices=['prepare','check','status','run'])
    ap.add_argument('--once', action='store_true')
    args = ap.parse_args(argv)
    if args.command in ('prepare','check'):
        queue = read(P/'approved-queue.json')
        ids = [entry['window_id'] for entry in queue['jobs']]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate candidate ID')
        for entry in queue['jobs']:
            if args.command == 'prepare':
                provider = channels.selected(P)
                if provider != 'rh' and (not entry.get('profile') or entry['profile']['kind'] == 'legacy-ai-app'):
                    entry['profile'] = channels.profile(provider)
                    entry.pop('schema_path', None)
                digest = input_digest(P, entry)
                if entry.get('input_digest') != digest:
                    entry['input_digest'] = digest
                    entry['semantic_review'] = {'status':'pending', 'input_digest':digest}
            validate(P, entry, require_approval=args.command == 'check')
            if not current_media_proof(entry):
                media_check(entry)
        if args.command == 'prepare':
            write(P/'approved-queue.json', queue)
        print(json.dumps({'jobs':len(ids), 'cloud_calls':0,
            'semantic_reviews_pending':sum(e.get('semantic_review',{}).get('status')!='passed' for e in queue['jobs'])}))
        return
    cfg = read(P/'runtime.json')
    provider = channels.selected(P)
    account = channels.account_for(provider, cfg.get('account_alias', 'default'))
    ledger = rh.Ledger(ledger_path() if provider == 'rh' else channels.ledger_path(P, provider))
    try:
        if ledger.account(account)['cap'] != 3:
            raise ValueError('Shared account concurrency must be exactly three')
        if args.command == 'status':
            print(json.dumps(snapshot(ledger, account), ensure_ascii=False))
            return
        # Queue may only grow by appending complete, independently reviewed candidates.
        import msvcrt
        with (P/'.dispatcher.lock').open('a+b') as lock:
            lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            if provider == 'rh':
                runner = FreshAssetRunner(ledger, StrictTransport(key()), account)
            else:
                runner = channels.make_runner(P, ledger, account, StrictTransport._verify_download)
            loaded = []
            while True:
                entries = read(P/'approved-queue.json')['jobs']
                if entries[:len(loaded)] != loaded:
                    raise ValueError('Loaded queue entries changed; keep accepted inputs immutable')
                for entry in entries[len(loaded):]:
                    digest = validate(P, entry)
                    prior = latest(ledger, account, entry['window_id'])
                    if prior and prior['digest'] != digest:
                        raise ValueError('Accepted candidate inputs changed')
                    # Unchanged accepted inputs already passed the complete media check.
                    # Restarts rehash them, then recover the same paid task promptly.
                    if (not prior or not prior['task_id']) and not current_media_proof(entry):
                        media_check(entry)
                    if any(old['window_id'] == entry['window_id'] for old in loaded):
                        raise ValueError('Duplicate candidate ID')
                    loaded.append(entry)
                unknown = tick(ledger, runner, entries, account)
                state = snapshot(ledger, account)
                print(json.dumps({'active':state['account_active'], 'cap':3, 'cooldown':state['cooldown_seconds'],
                    'states':{n:r['state'] for n,r in state['tasks'].items()}}, ensure_ascii=False), flush=True)
                if args.once or unknown or state['account_stopped'] or not entries:
                    return
                cfg = read(P/'runtime.json')
                eligible = [e for e in entries if e['window_id'] not in cfg.get('held_windows', {}) and e.get('source_segment',e['window_id']) not in cfg.get('accepted_segments', {})]
                if all(state['tasks'].get(e['window_id'], {}).get('state') in TERMINAL for e in eligible):
                    return
                # Three repeated execution failures call for inspection, not a visual retry limit.
                if any(ledger.db.execute('SELECT 1 FROM failures WHERE account=? AND project=? AND window=? AND count>=3',
                    (account,str(P),e['window_id'])).fetchone() for e in entries):
                    return
                time.sleep(12)
    finally:
        ledger.close()


if __name__ == '__main__':
    main()
