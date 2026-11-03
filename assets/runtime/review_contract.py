"""Validate evidence provenance, not visual quality; humans/agents still inspect pixels."""
from pathlib import Path
import json
import hashlib

VERSION=1

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(2**20),b''):h.update(block)
    return h.hexdigest()

def local(root,path):
    root=Path(root).resolve();path=Path(path)
    path=(root/path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_relative_to(root):raise ValueError('Review evidence must belong to this project')
    return path

def evidence(root,record):
    path=local(root,record['path'])
    if not path.is_file() or sha(path)!=record.get('sha256'):
        raise ValueError('Evidence missing or changed')
    data=json.loads(path.read_text(encoding='utf-8-sig'))
    if data.get('schema_version')!=VERSION or data.get('status')!='passed' or not data.get('reviewer') or not data.get('findings'):
        raise ValueError('Review must name its reviewer and findings; exporting pictures is not approval')
    for item in data.get('artifacts',[]):
        p=local(root,item['path'])
        if not p.is_file() or sha(p)!=item.get('sha256'):raise ValueError('Reviewed artifact changed')
    return data

def references(root):
    return {r:sha(Path(root)/f'替换用参考图/{r}号.png') for r in '一二'}

def validate_preserved(root,contract,entry,cast):
    record=contract.get('preserved_identity_evidence')
    if not isinstance(record,dict):raise ValueError('Preserved identity needs a path+SHA evidence record')
    proof=evidence(root,record)
    preserved=''.join(r for r in cast if r not in contract['edit_roles'])
    if (proof.get('candidate_sha256')!=sha(local(root,entry['video_path']))
        or proof.get('reference_sha256_by_role')!=references(root)
        or proof.get('preserved_roles')!=preserved
        or proof.get('reviewed_frame_range')!=[0,entry['generation_frames']-1]):
        raise ValueError('Preserved identity proof does not cover these inputs and all their frames')

def validate_accepted(root,record):
    proof=evidence(root,record['evidence'])
    path=local(root,record['path']);digest=sha(path)
    if digest!=record.get('sha256') or proof.get('candidate_sha256')!=digest or proof.get('reference_sha256_by_role')!=references(root):
        raise ValueError('Accepted segment is stale; freeze only the actual reviewed current identity')
    if not proof.get('reviewed_frame_range') or proof.get('native_review')!='passed' or proof.get('action_review')!='passed':
        raise ValueError('Accepted segment needs native and action evidence')
    return proof

def validate_selection_evidence(root,item,owners,source_path):
    proof=evidence(root,item['review_evidence'])
    paths={str(Path(o['path']).resolve()):o['sha256'] for o in owners}
    if (proof.get('source_sha256')!=sha(source_path)
        or proof.get('reference_sha256_by_role')!=references(root)
        or proof.get('candidate_sha256_by_path')!=paths):
        raise ValueError('Selection evidence must bind this source, current references and actual candidate bytes')
    mapping=[{'source_frame':o['source_frame'],'path':str(Path(o['path']).resolve()),'output_frame':o['output_frame'],'sha256':o['sha256']} for o in owners]
    digest=hashlib.sha256(json.dumps(mapping,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    if proof.get('owners_sha256')!=digest:raise ValueError('Source/output mapping changed after review')
    if any(proof.get(k)!='passed' for k in ('native_review','action_review','output_clock_review')):
        raise ValueError('Selection review remains pending')
    if proof.get('camera_change'):
        approval=proof.get('user_camera_acceptance',{})
        if not approval.get('quote') or approval.get('candidate_sha256_by_path')!=paths:
            raise ValueError('A changed camera needs acceptance for these actual candidates')
    return proof
