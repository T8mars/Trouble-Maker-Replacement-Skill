"""Offline template verification and isolated TroubleMaker project creation."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
TEMPLATE = SKILL / "assets" / "template"
RUNTIME = SKILL / "assets" / "runtime"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def dump(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rows(name: str) -> dict:
    result = {}
    for line in (TEMPLATE / "补齐生成用" / name).read_text(encoding="utf-8-sig").splitlines():
        fields = line.split()
        if fields and fields[0].endswith(".mp4"):
            num = fields[0][:3]
            if num in result:
                raise ValueError(f"duplicate segment: {num}")
            result[num] = fields[1:]
    return result


def probe_file(tool: str, path: Path, count: bool) -> dict:
    args = [tool, "-v", "error"]
    if count:
        args += ["-count_frames"]
    args += ["-show_streams", "-show_format", "-of", "json", str(path)]
    proc = subprocess.run(args, capture_output=True, text=True, timeout=120)
    if proc.returncode:
        raise ValueError(f"media probe failed: {path.name}")
    return json.loads(proc.stdout)


def check(probe: bool = False) -> dict:
    manifest = json.loads((SKILL / "template-manifest.json").read_text(encoding="utf-8"))
    missing_media=[name for name in manifest['files'] if Path(name).suffix.lower() in ('.mp4','.m4a','.png') and not (TEMPLATE/name).is_file()]
    if missing_media and (SKILL/'release-assets.json').is_file():
        raise ValueError('Source checkout is incomplete. Install the complete skill ZIP from this repository Releases; GitHub Code ZIP excludes required source media.')
    for relative, digest in manifest["files"].items():
        p = TEMPLATE / relative
        if not p.is_file() or sha256(p) != digest:
            raise ValueError(f"template file missing or changed: {relative}")
    actual = {p.relative_to(TEMPLATE).as_posix() for p in TEMPLATE.rglob("*") if p.is_file()}
    if actual != set(manifest["files"]):
        raise ValueError("unexpected template files; keep keys and project outputs outside the skill")
    if (TEMPLATE / "api_key.txt").is_file() and (TEMPLATE / "api_key.txt").read_text(encoding="utf-8-sig").strip():
        raise ValueError("installed template api_key.txt must stay empty")
    original, padded = rows("原始帧数.txt"), rows("补齐后帧数.txt")
    expected = {f"{i:03d}" for i in range(1, 103)}
    if set(original) != expected or set(padded) != expected:
        raise ValueError("the two frame tables must contain exactly 001 through 102")
    passthrough = {n for n, v in padded.items() if len(v) == 2 and v[1] == "原片"}
    if passthrough != {"028", "087"}:
        raise ValueError("passthrough segments must be 028 and 087")
    if sum(int(v[0]) for v in original.values()) != 4779:
        raise ValueError("original frame sum must be 4779")
    if sum(int(v[0]) for v in padded.values()) != 5569:
        raise ValueError("padded frame sum must be 5569")
    media = sorted((TEMPLATE / "补齐生成用").glob("*.mp4"))
    if len(media) != 102:
        raise ValueError("exactly 102 source mp4 files are required")
    generated = expected - passthrough
    for n in sorted(expected):
        count, *cast = padded[n]
        if int(count) < int(original[n][0]) or int(count) > 240:
            raise ValueError(f"invalid padded frame count: {n}")
        if cast not in (["一号二号"], ["一号"], ["二号"], ["原片"]):
            raise ValueError(f"invalid cast: {n}")
        path = TEMPLATE / "补齐生成用" / f"{n} {count}.mp4"
        if not path.is_file():
            raise ValueError(f"filename/table mismatch: {n}")
        if n in generated and not path.with_name(n + ".txt").is_file():
            raise ValueError(f"brief missing: {n}")
    contract=json.loads((SKILL/'references/source-contract.json').read_text(encoding='utf-8'))
    if len(contract['bound_files'])!=104:raise ValueError('Source contract must cover all 102 videos and both frame tables')
    for name,digest in contract['bound_files'].items():
        if manifest['files'].get(name)!=digest:raise ValueError('Source contract and template differ: '+name)
    bundle=json.loads((SKILL/'runtime-manifest.json').read_text(encoding='utf-8'))
    for name,digest in bundle['files'].items():
        if sha256(RUNTIME/name)!=digest:raise ValueError('Runtime bundle changed: '+name)
    if {p.relative_to(RUNTIME).as_posix() for p in RUNTIME.rglob('*') if p.is_file() and '__pycache__' not in p.parts}!=set(bundle['files']):
        raise ValueError('Unexpected runtime member')
    result = {"status": "ok", "segments": 102, "generated_segments": 101,
              "original_template_passthrough": sorted(passthrough), "passthrough": ["028"], "original_frames": 4779,
              "padded_frames": 5569, "fps": "24/1", "final_seconds": 4779 / 24,
              "max_generation_seconds": max(int(v[0]) for v in padded.values()) / 24,
              "concurrency": int((TEMPLATE / "并发数.txt").read_text().strip()),
              "template_members_verified": len(actual), "api_key_empty": True,
              "paid_calls_made": 0, "runtime_hardened": True, "media_probed": False}
    if result["concurrency"] != 3:
        raise ValueError("template concurrency must be 3")
    if probe:
        tool = shutil.which("ffprobe")
        if not tool:
            candidate = TEMPLATE / "ffmpeg" / "ffprobe.exe"
            if not candidate.is_file():
                raise ValueError("ffprobe is unavailable")
            tool = str(candidate)
        sizes = set()
        for path in media:
            info = probe_file(tool, path, True)
            streams = [s for s in info["streams"] if s.get("codec_type") == "video"]
            if len(streams) != 1:
                raise ValueError(f"expected one video stream: {path.name}")
            s = streams[0]
            n, frame_text = path.stem.split()
            if int(s["nb_read_frames"]) != int(frame_text) or s["avg_frame_rate"] != "24/1":
                raise ValueError(f"decoded frame count/fps mismatch: {n}")
            sizes.add((s["width"], s["height"]))
        audio = probe_file(tool, TEMPLATE / "原片音轨.m4a", False)
        if not any(s.get("codec_name") == "aac" and s.get("codec_type") == "audio" for s in audio["streams"]):
            raise ValueError("expected original AAC audio")
        result.update(media_probed=True, source_dimensions=sorted(sizes),
                      audio_seconds=float(audio["format"]["duration"]), ffprobe=tool)
    return result


def initialize(args: argparse.Namespace) -> dict:
    report = check()
    target = Path(args.project).expanduser().resolve()
    if target == SKILL or SKILL in target.parents or target in SKILL.parents:
        raise ValueError("project must be separate from the installed skill")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError("project directory must be new or empty; existing work will not be overwritten")
    refs = [Path(args.reference_one).expanduser().resolve(), Path(args.reference_two).expanduser().resolve()]
    for ref in refs:
        if not ref.is_file() or ref.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("reference files must be PNG; preserve originals when converting other formats")
        if target == ref or target in ref.parents:
            raise ValueError("reference originals must be outside the new project directory")
    shutil.copytree(TEMPLATE, target, dirs_exist_ok=True)
    shutil.copytree(RUNTIME, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copy2(SKILL/'references/source-contract.json',target/'source-contract.json')
    table=target/'补齐生成用/补齐后帧数.txt'
    lines=table.read_text(encoding='utf-8-sig').splitlines()
    table.write_text('\n'.join(line.replace('原片','一号') if line.split() and line.split()[0][:3]=='087' else line for line in lines)+'\n',encoding='utf-8')
    (target/'补齐生成用/087.txt').write_text('仅右画缘原男性手/袖需要替换为一号；画面主体两位伴舞保持原身份。沿源动作、照明、景别。',encoding='utf-8')
    execution_contract=json.loads((target/'source-contract.json').read_text(encoding='utf-8'))
    execution_contract['execution_frame_table_sha256']=sha256(table)
    dump(target/'source-contract.json',execution_contract)
    # The original package stays byte-identical in assets/template. Its old CLIs
    # are intentionally disabled only in the newly created execution copy.
    for old in ['rh_batch.py','assemble.py']:
        (target/old).write_text('raise SystemExit("Legacy entry disabled. Use troublemaker_runtime.py or assemble_verified.py; read CURRENT.md.")\n',encoding='utf-8')
    for folder in ["提示词", "完成分段", "制作分析"]:
        (target / folder).mkdir(exist_ok=True)
    for role, ref in zip(["一号", "二号"], refs):
        shutil.copy2(ref, target / "替换用参考图" / f"{role}.png")
    reference_hashes = {role: sha256(ref) for role, ref in zip(["一号", "二号"], refs)}
    dump(target / "meta.json", {"skill": "troublemaker-character-replacement", "skill_version":"1.1.0", "status": "initialized",
         "project": str(target), "reference_sha256": reference_hashes,
         "original_frames": 4779, "fps": "24/1", "audio_start_seconds": 0,
         "generated_segments":101,"passthrough":["028"]})
    dump(target / "features.json", {"references_received": True, "identity_checks_updated": False,
         "prompts_validated": False, "runtime_hardened": True, "generation_complete": False,
         "visual_review_complete": False, "final_review": False})
    dump(target / "runtime.json", {"production_authorized": False,"production_request":"", "concurrency": 3,
         "api_key_file": None, "ledger_file": None,"account_alias":"default",
         "installed_skill_directory":str(SKILL),"reference_selection":"provided-two",
         "reference_sha256": reference_hashes,"appearance_policy":{"style":"pending","headset":"preserve-source"},
         "approved_segments":[],"held_windows":{},"accepted_segments":{},"pilot_reviews":{},
         "ffmpeg_path":None,"ffprobe_path":None,"encoder_path":None})
    dump(target/'approved-queue.json',{'jobs':[]})
    dump(target/'identity-checks.json',{'configured':False,'remove_text':False,
         'roles':{r:{'label':'本轮'+r+'号','reference_sha256':reference_hashes[r+'号'],
                     'required':[],'forbidden':[]} for r in '一二'}})
    dump(target/'制作分析/selected-candidates.json',{'segments':{}})
    (target / "CURRENT.md").write_text(
        "# TroubleMaker 本轮制作\n\n状态：已初始化；未提交RH。\n\n"
        "已绑定本轮两张参考图，源合同校正为101生成、028直通。读取source-contract.json与安装技能references/runtime-protocol.md。\n"
        "使用troublemaker_runtime.py prepare/check/run/status；保留一个调度器，先查旧taskId再补位。\n"
        "下一步记录已有用户制作请求/风格，更新人物词检查，核对当前接口schema，做单人/双人/高风险试片再放批量。\n"
        "密钥由显式环境变量或项目外私有文件提供。审批、队列、试片和成片验收全部重新建立。\n"
        "音轨已裁过开头，直接从0开始；组装用assemble_verified.py；整片复核用stream_review.py。\n", encoding="utf-8")
    return {"project": str(target), "status": "initialized", "generation_authorized": False,
            "reference_sha256": reference_hashes, "source_check": report["status"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check", help="verify local template; makes no network calls")
    c.add_argument("--probe", action="store_true", help="decode-count every source video")
    c = sub.add_parser("init", help="copy template into a new isolated project; does not generate")
    c.add_argument("--project", required=True)
    c.add_argument("--reference-one", required=True)
    c.add_argument("--reference-two", required=True)
    args = parser.parse_args()
    try:
        report = check(args.probe) if args.command == "check" else initialize(args)
    except (ValueError, OSError, subprocess.SubprocessError, KeyError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
