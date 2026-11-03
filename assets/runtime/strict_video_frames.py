"""Canonical strict RGB decoding for evidence and final assembly, using the configured decoder."""
from pathlib import Path
import subprocess,tempfile,hashlib,json,os,ctypes
import av
from PIL import Image
from apt_media_tools import resolve_tool

P=Path(__file__).resolve().parent

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(2**20),b''):h.update(b)
 return h.hexdigest()

def constrain_child(proc):
 if os.name!='nt':return
 kernel=ctypes.windll.kernel32;current=ctypes.c_size_t();system=ctypes.c_size_t()
 kernel.GetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)]
 kernel.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
 kernel.GetCurrentProcess.restype=ctypes.c_void_p
 if kernel.GetProcessAffinityMask(kernel.GetCurrentProcess(),ctypes.byref(current),ctypes.byref(system)):
  bits=[i for i in range(ctypes.sizeof(current)*8) if current.value&(1<<i)]
  mask=sum(1<<i for i in bits[-4:])
  if mask:kernel.SetProcessAffinityMask(int(proc._handle),mask)

def strict_frames(path):
 path=Path(path)
 with av.open(str(path)) as c:
  s=c.streams.video[0];width,height=s.width,s.height
  duration_seconds=float(s.duration*s.time_base) if s.duration is not None else 0
 size=width*height*3
 tempdir=P/'制作分析/decoder-logs';tempdir.mkdir(parents=True,exist_ok=True)
 # Do not emit/save a single evidence pixel until a COMPLETE strict read passes.
 # Bind the first proof to two matching complete RGB hashes; later reads must
 # match that fingerprint. Local decoder retries never submit another cloud job.
 source_sha=sha(path);decoder=resolve_tool(P,'ffmpeg');encoder_sha=sha(decoder)
 proof_path=tempdir/(source_sha+'-'+encoder_sha[:12]+'.json')
 known=json.loads(proof_path.read_text(encoding='utf-8')) if proof_path.exists() else None
 expected=known.get('rgb_sha256') if known and known.get('status')=='passed' else None
 attempts=[];previous=None
 with tempfile.TemporaryFile(dir=tempdir) as raw,tempfile.TemporaryFile(dir=tempdir) as log:
  accepted=False
  for attempt in range(3):
   raw.seek(0);raw.truncate();log.seek(0);log.truncate()
   proc=subprocess.Popen([decoder,'-nostdin','-v','error','-xerror','-threads','1','-filter_threads','1',
    '-i',str(path),'-map','0:v:0','-an','-sn','-dn','-threads','1','-pix_fmt','rgb24','-fps_mode','passthrough','-f','rawvideo','pipe:1'],stdout=raw,stderr=log)
   constrain_child(proc)
   try:code=proc.wait(timeout=max(180,round(duration_seconds*4)))
   except BaseException:
    proc.terminate();proc.wait();raise
   log.seek(0);error=log.read();length=raw.tell()
   if code or error.strip() or length==0 or length%size:
    attempts.append({'attempt':attempt+1,'returncode':code,'bytes':length,'error':error.decode('utf-8',errors='replace')[:2000]});continue
   raw.seek(0);digest=hashlib.sha256()
   for block in iter(lambda:raw.read(2**20),b''):digest.update(block)
   fingerprint=digest.hexdigest();attempts.append({'attempt':attempt+1,'returncode':0,'frames':length//size,'rgb_sha256':fingerprint})
   if (expected and fingerprint!=expected) or (previous and fingerprint!=previous):
    (tempdir/(source_sha+'-mismatch.json')).write_text(json.dumps({'source':str(path),'attempts':attempts,'existing_proof':known},ensure_ascii=False,indent=2),encoding='utf-8')
    raise ValueError('Independent strict RGB reads disagree; inspect local decoder without re-paying: '+str(path))
   if expected or previous:
    accepted=True
    if not expected:
     proof_path.write_text(json.dumps({'status':'passed','source':str(path),'source_sha256':source_sha,'decoder_sha256':encoder_sha,
      'rgb_sha256':fingerprint,'frames':length//size,'size':[width,height],'method':'two independent complete strict RGB hashes match; own child CPU affinity limited to four allowed CPUs','attempts':attempts},ensure_ascii=False,indent=2),encoding='utf-8')
    break
   previous=fingerprint
  if not accepted:
   (tempdir/(source_sha+'-failed-read.json')).write_text(json.dumps({'source':str(path),'attempts':attempts},ensure_ascii=False,indent=2),encoding='utf-8')
   raise ValueError('No two matching complete strict RGB reads; preserve original paid candidate: '+str(path))
  if any(x['returncode']!=0 or x.get('error') for x in attempts):
   (tempdir/(source_sha+'-read-retries.json')).write_text(json.dumps(attempts,ensure_ascii=False,indent=2),encoding='utf-8')
  raw.seek(0)
  for _ in range(length//size):
   block=raw.read(size)
   if len(block)!=size:raise ValueError('Canonical local RGB stream truncated')
   yield Image.frombytes('RGB',(width,height),block)
