"""Prepare complete source-owner/candidate pair boards; never infer visual acceptance."""
from pathlib import Path
import argparse,json
import av
from PIL import Image,ImageDraw,ImageOps
import rh_core as rh
from strict_video_frames import strict_frames
P=Path(__file__).resolve().parent

def frames(path):
 result=[]
 for im in strict_frames(path):result.append(ImageOps.contain(im,(320,181)))
 return result

def main():
 a=argparse.ArgumentParser();a.add_argument('window');a.add_argument('--map',type=Path);a.add_argument('--source-start',type=int,default=0);a.add_argument('--source-count',type=int);args=a.parse_args()
 ev=json.loads((P/'制作分析/候选复核'/(args.window+'_compact')/'evidence.json').read_text(encoding='utf-8'))
 n=args.window[:3];src=next((P/'补齐生成用').glob(n+' *.mp4'))
 if n in ('067','102') and not args.map:raise ValueError('Known internal cut/dissolve requires an observed map; no silent prefix assumption')
 keep={l.split()[0][:3]:int(l.split()[1]) for l in (P/'补齐生成用/原始帧数.txt').read_text(encoding='utf-8-sig').splitlines() if l.split() and l.split()[0].endswith('.mp4')}[n]
 source=frames(src);output=frames(ev['video']);full_keep=keep
 if args.source_start<0 or args.source_start>=keep:raise ValueError('Source start out of ownership range')
 keep=args.source_count if args.source_count is not None else keep-args.source_start
 if keep<=0 or args.source_start+keep>full_keep:raise ValueError('Source window exceeds original ownership')
 mapping=json.loads(args.map.read_text(encoding='utf-8'))['output_indices'] if args.map else list(range(keep))
 if len(mapping)!=keep or any(type(i)is not int or not 0<=i<len(output) for i in mapping):raise ValueError('Invalid actual frame selection')
 if any(b<a for a,b in zip(mapping,mapping[1:])):raise ValueError('Action mapping must not run backward')
 dest=P/'制作分析/动作对照'/args.window/('mapped-'+rh.digest_object({'indices':mapping,'start':args.source_start})[:8] if args.map else 'prefix');dest.mkdir(parents=True,exist_ok=False)
 pages=[]
 for first in range(0,keep,24):
  end=min(first+24,keep);board=Image.new('RGB',(1920,390*((end-first+5)//6)),'#202020');d=ImageDraw.Draw(board)
  for i in range(first,end):
   j=i-first;x=j%6*320;y=j//6*390
   board.paste(source[args.source_start+i],(x,y+20));board.paste(output[mapping[i]],(x,y+209))
   d.text((x+4,y+3),f'SOURCE {n}:{args.source_start+i}',fill='white');d.text((x+4,y+191),f'OUTPUT {args.window}:{mapping[i]}',fill='white')
  name=f'pairs-{first:03d}-{end-1:03d}.jpg';board.save(dest/name,quality=96);pages.append(name)
 (dest/'evidence.json').write_text(json.dumps({'window':args.window,'source':str(src),'output':ev['video'],'output_sha256':ev['video_sha256'],
  'source_owners':keep,'source_indices':list(range(args.source_start,args.source_start+keep)),'output_indices':mapping,'pages':pages,'source_action_review':'pending','actual1x':'pending'},ensure_ascii=False,indent=2),encoding='utf-8')
 print(dest)

if __name__=='__main__':main()
