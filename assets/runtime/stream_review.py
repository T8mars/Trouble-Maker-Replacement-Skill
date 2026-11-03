"""Bounded-memory full-film overview/join evidence; no multi-GB raw RGB spool.

Pictures stay provisional until complete strict RGB reads agree. This builds
evidence only; actual 1x playback and visual acceptance remain pending.
"""
from pathlib import Path
import argparse,hashlib,json,subprocess,tempfile,threading,uuid
import av
from PIL import Image,ImageDraw
from apt_media_tools import resolve_tool
from strict_video_frames import constrain_child,sha

P=Path(__file__).resolve().parent

def stream_pass(video,decoder,consume=None):
    with av.open(str(video)) as c:
        s=c.streams.video[0];s.codec_context.thread_count=1
        width,height=s.width,s.height
        pts=[str(f.pts*f.time_base) for f in c.decode(s)]
    size=width*height*3;digest=hashlib.sha256();count=0
    with tempfile.TemporaryFile() as log:
        proc=subprocess.Popen([decoder,'-nostdin','-v','error','-xerror','-threads','1','-filter_threads','1','-i',str(video),
            '-map','0:v:0','-an','-sn','-dn','-threads','1','-pix_fmt','rgb24','-fps_mode','passthrough','-f','rawvideo','pipe:1'],stdout=subprocess.PIPE,stderr=log)
        constrain_child(proc)
        timer=threading.Timer(max(180,len(pts)/24*8),lambda:proc.kill() if proc.poll() is None else None)
        timer.start()
        try:
            while True:
                data=bytearray()
                while len(data)<size:
                    part=proc.stdout.read(size-len(data))
                    if not part:break
                    data.extend(part)
                if not data:break
                if len(data)!=size:raise ValueError('Truncated strict RGB frame')
                digest.update(data)
                if consume:consume(count,Image.frombytes('RGB',(width,height),bytes(data)))
                count+=1
            code=proc.wait();log.seek(0);error=log.read()
            if code or error.strip() or count!=len(pts) or not count:
                raise ValueError(f'Strict stream failed: exit={code}, frames={count}/{len(pts)}; '+error.decode(errors='replace')[:1000])
        finally:
            timer.cancel()
            if proc.poll() is None:proc.kill();proc.wait()
            proc.stdout.close()
    return {'rgb_sha256':digest.hexdigest(),'frames':count,'size':[width,height],'pts':pts}

def build(video,out,step=12,joins=()):
    if step<1:raise ValueError('step must be positive')
    video=Path(video).resolve();out=Path(out).resolve();decoder=resolve_tool(P,'ffmpeg')
    identity={'video_sha256':sha(video),'decoder_sha256':sha(decoder),'checker_sha256':sha(__file__),'pyav':av.__version__,'pyav_libraries':str(av.library_versions),'version':1,'step':step,'joins':sorted(set(joins)),'thumb':[240,136]}
    if out.exists():
        record=json.loads((out/'evidence.json').read_text(encoding='utf-8'))
        if record.get('identity')!=identity or any(sha(out/n)!=h for n,h in record['artifacts'].items()):
            raise ValueError('Existing review differs; use a new output directory')
        return {'cached':True,'evidence':str(out/'evidence.json')}
    out.parent.mkdir(parents=True,exist_ok=True)
    pending=out.with_name(out.name+'.pending-'+uuid.uuid4().hex[:8]);pending.mkdir()
    thumbs=[];native={i for j in joins for i in (j-1,j) if i>=0}
    def consume(i,im):
        if i in native:im.save(pending/f'join-{i:05d}.png')
        if i%step==0:
            im.thumbnail((240,136));thumbs.append((i,im))
    try:
        first=stream_pass(video,decoder,consume)
        # No intermediate full-frame RGB file: the second calibration is streamed.
        second=stream_pass(video,decoder)
        if first!=second:raise ValueError('Independent complete RGB/PTS reads disagree; local decoder issue, no cloud retry')
        if any(i>=first['frames'] for i in native):raise ValueError('Join exceeds actual full-film clock')
        for offset in range(0,len(thumbs),48):
            batch=thumbs[offset:offset+48];board=Image.new('RGB',(1920,155*((len(batch)+7)//8)),(20,20,20));draw=ImageDraw.Draw(board)
            for j,(i,im) in enumerate(batch):
                x=j%8*240;y=j//8*155;board.paste(im,(x,y));draw.text((x+2,y+137),f'frame {i}',fill='white')
            board.save(pending/f'overview-{offset//48:03d}.jpg',quality=95)
        artifacts={p.name:sha(p) for p in pending.iterdir() if p.is_file()}
        record={'identity':identity,**first,'artifacts':artifacts,'strict_rgb':'passed','independent_full_reads':2,
            'overview_sampling_frames':step,'native_joins':'pending','actual1x_full_film':'pending',
            'note':'Overview is sampled. Per-candidate full-frame identity/action review is still required.'}
        (pending/'evidence.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        pending.rename(out)
        return {'cached':False,'evidence':str(out/'evidence.json'),'frames':first['frames']}
    except BaseException as exc:
        (pending/'FAILED.txt').write_text(str(exc),encoding='utf-8');raise

def main():
    p=argparse.ArgumentParser();p.add_argument('--video',required=True);p.add_argument('--out',required=True);p.add_argument('--step',type=int,default=12);p.add_argument('--plan',type=Path)
    a=p.parse_args();joins=[]
    if a.plan:joins=[r['first_frame'] for r in json.loads(a.plan.read_text(encoding='utf-8'))['segments'][1:]]
    print(json.dumps(build(a.video,a.out,a.step,joins),ensure_ascii=False))

if __name__=='__main__':main()
