from pathlib import Path
import json,sqlite3,argparse
from concurrent.futures import ThreadPoolExecutor
import av
from fractions import Fraction
from PIL import Image,ImageDraw
import rh_core as rh
from strict_video_frames import strict_frames

P=Path(__file__).resolve().parent

def inspect(wid,native_all=False,rois=None):
 cfg=json.loads((P/'runtime.json').read_text(encoding='utf-8'))
 db=sqlite3.connect(Path(cfg['ledger_file']).as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
 row=db.execute('SELECT id,output,state FROM attempts WHERE project=? AND window=? AND output IS NOT NULL ORDER BY created DESC LIMIT 1',(str(P),wid)).fetchone();db.close()
 if not row or not Path(row['output']).is_file():return {'window':wid,'state':row['state'] if row else 'not-ready'}
 return inspect_file(wid,row['output'],row['id'],native_all,rois)

def inspect_file(wid,video,attempt,native_all=False,rois=None):
 if not wid or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in wid):raise ValueError('Invalid candidate name')
 rois=rois or []
 config={'video_sha256':rh.sha(video),'script_sha256':rh.sha(__file__),'native_all':native_all,'rois':rois,'version':2}
 out=P/'制作分析'/'候选复核'/(wid+'_compact')
 if (out/'evidence.json').exists():
  old=json.loads((out/'evidence.json').read_text(encoding='utf-8'))
  if old.get('review_configuration')==config and all(rh.sha(out/n)==h for n,h in old.get('artifacts',{}).items()):return {'window':wid,'cached':True,'evidence':str(out/'evidence.json')}
  raise ValueError('Existing evidence differs; use a new candidate/review name, preserve prior evidence')
 out.mkdir(parents=True,exist_ok=True)
 images=[];pts=[];sizes=set()
 with av.open(video) as c:
  s=c.streams.video[0];s.codec_context.thread_count=1
  for i,f in enumerate(c.decode(s)):
   pts.append(str(f.pts*f.time_base))
 if not pts or Fraction(pts[-1])-Fraction(pts[0])+1/Fraction(s.average_rate)>10:raise ValueError('Actual candidate output exceeds ten seconds or is empty')
 anchors={0,len(pts)-1,len(pts)//4,len(pts)//2,len(pts)*3//4}
 for i,im in enumerate(strict_frames(video)):
  sizes.add(im.size)
  if native_all or i in anchors:im.save(out/f'native-{i:03d}.png')
  for r,roi in enumerate(rois):
   box=roi['box']
   if len(box)!=4 or not all(type(x)is int for x in box) or not 0<=box[0]<box[2]<=im.width or not 0<=box[1]<box[3]<=im.height:raise ValueError('ROI outside actual output canvas')
   im.crop(box).save(out/f'roi-{r:02d}-frame-{i:03d}.png')
  im.thumbnail((240,136));images.append(im)
 if len(images)!=len(pts):raise ValueError('Independent RGB/PTS count mismatch')
 pages=[]
 for first in range(0,len(images),48):
  subset=images[first:first+48];board=Image.new('RGB',(1920,155*((len(subset)+7)//8)),(20,20,20));d=ImageDraw.Draw(board)
  for j,im in enumerate(subset):
   x=j%8*240;y=j//8*155;board.paste(im,(x,y));d.text((x+2,y+137),f'{wid} frame{first+j} t={pts[first+j]}',fill='white')
  name=f'frames-{first:03d}-{first+len(subset)-1:03d}.jpg';board.save(out/name,quality=95);pages.append(name)
 report={'window':wid,'attempt':attempt,'video':str(video),'video_sha256':rh.sha(video),'frames':len(images),'sizes':sorted(sizes),'pts':pts,'pages':pages,'visual_review':'pending','pixel_decoder':'strict configured decoder; independent PyAV timestamp count',
  'review_configuration':config,'native_frame_indices':list(range(len(images))) if native_all else sorted(anchors),
  'native_rois':rois,'artifacts':{p.name:rh.sha(p) for p in out.iterdir() if p.is_file() and p.name!='evidence.json'}}
 (out/'evidence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 return {k:v for k,v in report.items() if k not in ['pts','video_sha256']}

if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('windows',nargs='+');a.add_argument('--native-all',action='store_true');a.add_argument('--roi-file',type=Path);args=a.parse_args()
 rois=json.loads(args.roi_file.read_text(encoding='utf-8')) if args.roi_file else []
 for wid in args.windows:print(json.dumps(inspect(wid,args.native_all,rois),ensure_ascii=False),flush=True)
