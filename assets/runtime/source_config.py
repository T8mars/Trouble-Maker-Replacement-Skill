"""Source CAST/config reader only; no legacy network entry point."""
from pathlib import Path
import hashlib,json
P=Path(__file__).resolve().parent
def read_text(name):return (P/name).read_text(encoding='utf-8-sig')
def load_cast():
    contract_path=P/'source-contract.json'
    if contract_path.is_file():
        contract=json.loads(contract_path.read_text(encoding='utf-8-sig'))
        for relative,expected in [('补齐生成用/补齐后帧数.txt',contract['execution_frame_table_sha256']),('补齐生成用/原始帧数.txt',contract['bound_files']['补齐生成用/原始帧数.txt'])]:
            if hashlib.sha256((P/relative).read_bytes()).hexdigest()!=expected:raise ValueError('Source frame/CAST table changed; re-analyse the execution contract')
    labels={'一号':'一','二号':'二','一号二号':'一二'}
    return {a[0][:3]:labels[a[2]] for line in read_text('补齐生成用/补齐后帧数.txt').splitlines() if len(a:=line.split())>=3 and a[2] in labels}
CAST=load_cast() if (P/'补齐生成用/补齐后帧数.txt').is_file() else {}
MODES={'ai':{'站点':'https://www.runninghub.ai','单人':'2107844752011010050','双人':'2107845954833907713'},'cn':{'站点':'https://www.runninghub.cn','单人':'2109234869904695297','双人':'2109238926799101954'}}
def app_config():
    """ai应用.txt：模式 <ai 或 cn，可省略，默认 ai> / 实例 <规格> / 一采分辨率 <数值，可省略，默认 2>。"""
    cfg = {}
    for line in read_text("ai应用.txt").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in ("模式", "实例", "一采分辨率"):
            cfg[parts[0]] = parts[1]
    if not cfg.get("实例"):
        raise SystemExit("ai应用.txt 缺少：实例")
    mode = cfg.setdefault("模式", "ai")
    if mode not in MODES:
        raise SystemExit(f"ai应用.txt 的模式只能是 ai 或 cn：{mode}")
    cfg["站点"] = MODES[mode]["站点"]
    cfg["单人"] = MODES[mode]["单人"]
    cfg["双人"] = MODES[mode]["双人"]
    cfg.setdefault("一采分辨率", "2")
    return cfg

