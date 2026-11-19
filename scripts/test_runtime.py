"""Offline regressions for the packaged TroubleMaker workflow. All HTTP is prohibited."""
from pathlib import Path
from fractions import Fraction
import importlib.util
import json
import subprocess
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

T=Path(__file__).resolve().parent.parent / 'assets/runtime'
sys.path.insert(0,str(T))
import rh_core as rh
import troublemaker_runtime as rt
import inspect_compact as review
import strict_video_frames as strict
import stream_review as stream
from apt_media_tools import resolve_tool


class FakeTransport:
    key='offline-fixture-not-a-real-key'
    def __init__(self):
        self.calls=[];self.submissions=0;self.uploads=0;self.fail_submit=False;self.query_busy=False;self.fail_download=False
    def upload(self,path):
        self.uploads+=1;self.calls.append('upload')
        return {'filename':f'fresh-{self.uploads}'}
    def submit(self,path,body):
        self.submissions+=1;self.calls.append('submit')
        if self.fail_submit:raise TimeoutError('Unknown response')
        return {'taskId':f'paid-{self.submissions}'}
    def query(self,task):
        self.calls.append('query')
        if self.query_busy:raise rh.ApiFailure('421')
        return {'status':'SUCCESS','results':[{'url':'https://example.invalid/result.mp4','outputType':'mp4'}]}
    def download(self,url,dest):
        self.calls.append('download')
        if self.fail_download:raise TimeoutError('Download interrupted')
        dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(b'offline downloaded result')


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.now=1000
        self.ledger=rh.Ledger(self.root/'private/tasks.sqlite',clock=lambda:self.now)
        self.transport=FakeTransport();self.runner=rt.FreshAssetRunner(self.ledger,self.transport)
        self.project=self.root/'run';self.project.mkdir()
        rt.write(self.project/'runtime.json',{})
        for name in ['video.mp4','ref.png','prompt.txt']:(self.project/name).write_text('fixture '+name,encoding='utf8')
        self.entry={'window_id':'030_A','video_path':'video.mp4','prompt_path':'prompt.txt','reference_paths':['ref.png'],
            'generation_frames':22,'generation_fps':'24','input_digest':'fixture-digest',
            'profile':{'kind':'legacy-ai-app','app_id':'2107844752011010050','resolution_selector':{
                'aspect_ratio':'16:9 (Widescreen)','megapixels':1,'aspect_node_ids':['115','214']}}}
    def tearDown(self):self.ledger.close();self.temp.cleanup()
    def submit(self,window='030_A'):
        entry={**self.entry,'window_id':window}
        return self.runner.submit_one(self.project,entry,lambda p,e:'fixture-digest')
    def test_account_cap_shared_across_runs(self):
        for index in range(3):self.assertTrue(self.ledger.reserve('default',self.root/str(index),'job','hash'))
        other=rh.Ledger(self.root/'private/tasks.sqlite',clock=lambda:self.now)
        try:self.assertIsNone(other.reserve('default',self.root/'other','new','hash'))
        finally:other.close()
    def test_accepted_task_cannot_be_resubmitted(self):
        attempt=self.submit();self.assertEqual(self.ledger.row(attempt)['task_id'],'paid-1')
        self.assertIsNone(self.submit());self.assertEqual(self.transport.submissions,1)
    def test_unknown_post_remains_reserved(self):
        self.transport.fail_submit=True;attempt=self.submit()
        self.assertEqual(self.ledger.row(attempt)['state'],'SUBMISSION_UNKNOWN')
        self.assertIsNone(self.submit());self.assertEqual(self.transport.submissions,1)
    def test_busy_query_keeps_id_waits_60(self):
        attempt=self.submit();self.now+=6;self.transport.query_busy=True;self.runner.recover(attempt)
        row=self.ledger.row(attempt);self.assertEqual(row['task_id'],'paid-1')
        self.assertEqual(row['state'],'RUNNING');self.assertGreaterEqual(row['next_poll'],self.now+60)
        self.assertEqual(self.transport.submissions,1)
    def test_busy_submit_is_not_execution_failure(self):
        attempt=self.ledger.reserve('default',self.project,'job','hash');self.runner.submission_rejected(attempt,'421')
        self.assertEqual(self.ledger.row(attempt)['state'],'DEFERRED')
        self.assertGreaterEqual(self.ledger.account('default')['cooldown'],self.now+60)
        self.assertFalse(self.ledger.db.execute('SELECT * FROM failures').fetchall())
    def test_download_recovers_original_paid_id(self):
        attempt=self.submit();self.now+=6;self.transport.fail_download=True;self.runner.recover(attempt)
        self.assertEqual(self.ledger.row(attempt)['state'],'DOWNLOAD_FAILED')
        self.now+=31;self.transport.fail_download=False;self.runner.recover(attempt)
        self.assertEqual(self.ledger.row(attempt)['state'],'DOWNLOADED');self.assertEqual(self.transport.submissions,1)
    def test_new_submission_uses_fresh_uploads(self):
        self.submit('A');self.submit('B');self.assertEqual(self.transport.uploads,4)
    def test_three_execution_failures_pause_one_input(self):
        for index in range(3):
            attempt=self.ledger.reserve('default',self.project,'job','hash')
            self.assertTrue(attempt);self.ledger.execution_failure(attempt,'805')
        self.assertIsNone(self.ledger.reserve('default',self.project,'job','hash'))
    def test_query_then_refill_then_transfer(self):
        with patch.object(rt,'P',self.project),patch.object(rt,'validate',lambda p,e:'fixture-digest'):
            attempt=self.submit('old');self.now+=6;self.transport.calls=[]
            rt.tick(self.ledger,self.runner,[{**self.entry,'window_id':'new'}])
            self.assertLess(self.transport.calls.index('query'),self.transport.calls.index('submit'))
            self.assertLess(self.transport.calls.index('submit'),self.transport.calls.index('download'))
    def test_unknown_post_stops_other_new_jobs_immediately(self):
        self.transport.fail_submit=True
        with patch.object(rt,'P',self.project),patch.object(rt,'validate',lambda p,e:'fixture-digest'):
            self.assertTrue(rt.tick(self.ledger,self.runner,[{**self.entry,'window_id':n} for n in ['A','B','C']]))
        self.assertEqual(self.transport.submissions,1)
    def test_last_slot_race_across_real_processes(self):
        self.ledger.reserve('default',self.root/'first','job','hash')
        self.ledger.reserve('default',self.root/'second','job','hash')
        code="import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import rh_core as r;l=r.Ledger(Path(sys.argv[2]));print(bool(l.reserve('default',Path(sys.argv[3]),'job','hash')));l.close()"
        processes=[subprocess.Popen([sys.executable,'-B','-X','utf8','-c',code,str(T),str(self.root/'private/tasks.sqlite'),str(self.root/('race'+str(i)))],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for i in range(4)]
        results=[p.communicate(timeout=30) for p in processes]
        self.assertTrue(all(p.returncode==0 for p in processes),results)
        self.assertEqual(sum(out.strip()=='True' for out,err in results),1)
    def test_crash_after_post_before_id_keeps_reserved_on_restart(self):
        attempt=self.ledger.reserve('default',self.project,'crashed','fixture-digest',block_uncertain=True)
        self.assertEqual(self.ledger.row(attempt)['state'],'SUBMITTING')
        # A fresh runner/process cannot know whether the already reserved POST was accepted.
        other=rh.Ledger(self.root/'private/tasks.sqlite',clock=lambda:self.now)
        try:
            restarted=rt.FreshAssetRunner(other,self.transport)
            self.assertIsNone(restarted.submit_one(self.project,{**self.entry,'window_id':'new'},lambda p,e:'fixture-digest'))
            self.assertEqual(self.transport.submissions,0)
        finally:other.close()


class InputTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.project=Path(self.temp.name).resolve()
        for name in ['补齐生成用','替换用参考图','提示词','接口快照']:(self.project/name).mkdir()
        from PIL import Image
        for role in '一二':Image.new('RGB',(16,16),'blue').save(self.project/f'替换用参考图/{role}号.png')
        (self.project/'补齐生成用/041 56.mp4').write_bytes(b'fixture')
        (self.project/'补齐生成用/041.txt').write_text('Measured source action',encoding='utf8')
        (self.project/'提示词/041.txt').write_text('Current identity and source actions',encoding='utf8')
        fields=[('137','image'),('139','image'),('138','value'),('321','video'),('326','value'),('115','megapixels'),('115','aspect_ratio'),('214','aspect_ratio')]
        rt.write(self.project/'接口快照/schema.json',{'data':{'nodeInfoList':[{'nodeId':n,'fieldName':f} for n,f in fields]}})
        rt.write(self.project/'runtime.json',{'reference_selection':'provided-two','production_authorized':True,
            'production_request':'User requested a new APT role swap','approved_segments':['041']})
        self.entry={'window_id':'041','video_path':'补齐生成用/041 56.mp4','prompt_path':'提示词/041.txt',
            'reference_paths':['替换用参考图/一号.png','替换用参考图/二号.png'],'generation_frames':56,'generation_fps':'24',
            'schema_path':'接口快照/schema.json','pilot':True,'profile':{'kind':'legacy-ai-app','app_id':'2107845954833907713',
                'resolution_selector':{'aspect_ratio':'16:9 (Widescreen)','megapixels':1,'aspect_node_ids':['115','214']}}}
        self.patches=[patch.object(rt.source,'CAST',{'041':'一二'}),patch.object(rt,'P',self.project),patch.object(rt.source,'app_config',lambda:{'模式':'ai','实例':'plus'})]
        for item in self.patches:item.start()
        self.seal()
    def seal(self):
        self.entry['input_digest']=rt.input_digest(self.project,self.entry)
        self.entry['semantic_review']={'status':'passed','input_digest':self.entry['input_digest'],'notes':'Actual current role/action review complete'}
    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()
    def test_current_hash_bound_contract_valid(self):self.assertEqual(rt.validate(self.project,self.entry),self.entry['input_digest'])
    def test_provider_queue_uses_native_roles_without_rh_schema(self):
        (self.project/self.entry.pop('schema_path')).unlink()
        with patch.object(rt.source,'app_config',side_effect=AssertionError('Unexpected RH access')):
            for provider in ('chenyu','zhenzhen'):
                rt.write(self.project/'channel.json',{'provider':provider})
                self.entry['profile'] = rt.channels.profile(provider)
                self.seal()
                self.assertEqual(rt.validate(self.project,self.entry),self.entry['input_digest'])
                self.entry['reference_paths'].reverse()
                self.seal()
                with self.assertRaises(ValueError):rt.validate(self.project,self.entry)
                self.entry['reference_paths'].reverse()

    def test_changed_prompt_invalidates_semantic_review(self):
        (self.project/'提示词/041.txt').write_text('changed',encoding='utf8')
        with self.assertRaises(ValueError):rt.validate(self.project,self.entry)
    def test_partial_role_041_requires_two_slots(self):
        self.entry['reference_paths']=self.entry['reference_paths'][1:]
        with self.assertRaises(ValueError):rt.validate(self.project,self.entry)
    def test_10_second_limit_includes_context(self):
        self.entry['generation_frames']=241;self.seal()
        with self.assertRaises(ValueError):rt.validate(self.project,self.entry)
    def test_key_inside_run_rejected(self):
        with self.assertRaises(ValueError):rt.private_path(self.project/'private/api_key.txt')
    def test_nonexact_crop_rejected(self):
        from PIL import Image
        Image.new('RGB',(8,8),'red').save(self.project/'wrong.png')
        self.entry['reference_paths'][0]='wrong.png'
        self.entry['reference_crops']={'wrong.png':{'source_path':'替换用参考图/一号.png',
            'source_sha256':rh.sha(self.project/'替换用参考图/一号.png'),'crop':[0,0,8,8]}}
        self.seal()
        with self.assertRaises(ValueError):rt.validate(self.project,self.entry)


class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name).resolve()
        cls.clip=cls.root/'actual90.mp4';cls.source=cls.root/'source21.mp4';cls.longclip=cls.root/'actual241.mp4'
        ffmpeg=resolve_tool(T,'ffmpeg')
        for path,count,audio in [(cls.clip,90,True),(cls.source,21,False),(cls.longclip,241,True)]:
            command=[ffmpeg,'-nostdin','-v','error','-f','lavfi','-i','color=c=red:s=64x36:r=24']
            if audio:command+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
            command+=['-frames:v',str(count),'-c:v','libx264','-threads','1','-pix_fmt','yuv420p']
            if audio:command+=['-c:a','aac','-shortest']
            command+=['-n',str(path)]
            subprocess.run(command,check=True,capture_output=True,timeout=30)
    @classmethod
    def tearDownClass(cls):
        # Windows executable scanners may briefly retain the already-exited binary.
        for attempt in range(10):
            try:
                cls.temp.cleanup();return
            except PermissionError:
                if attempt==9:raise
                time.sleep(0.5)
    def test_full_output_evidence_includes_89_and_keeps_pending(self):
        with patch.object(review,'P',self.root),patch.object(strict,'P',self.root):
            review.inspect_file('actual90',str(self.clip),'fixture',True,[{'box':[0,0,32,36]}])
        out=self.root/'制作分析/候选复核/actual90_compact';info=rt.read(out/'evidence.json')
        self.assertEqual(info['frames'],90)
        self.assertTrue((out/'native-089.png').is_file())
        self.assertTrue((out/'roi-00-frame-089.png').is_file())
        self.assertEqual(info['visual_review'],'pending')
        with patch.object(review,'P',self.root),patch.object(review,'strict_frames',side_effect=AssertionError('Must reuse unchanged evidence')):
            self.assertTrue(review.inspect_file('actual90',str(self.clip),'fixture',True,[{'box':[0,0,32,36]}])['cached'])
    def test_stream_evidence_cache_and_corruption(self):
        dest=self.root/'stream-review'
        with patch.object(stream,'P',self.root):
            result=stream.build(self.clip,dest,12,[45]);self.assertEqual(result['frames'],90)
            info=rt.read(dest/'evidence.json');self.assertEqual(info['actual1x_full_film'],'pending')
            with patch.object(stream,'stream_pass',side_effect=AssertionError('No repeat full decode')):
                self.assertTrue(stream.build(self.clip,dest,12,[45])['cached'])
            (dest/'join-00044.png').write_bytes(b'corrupt')
            with self.assertRaises(ValueError):stream.build(self.clip,dest,12,[45])
    def test_media_cache_survives_prompt_only_change(self):
        entry={'video_path':self.clip.name,'generation_frames':90,'generation_fps':'24','input_digest':'one'}
        with patch.object(rt,'P',self.root):
            rt.media_check(entry)
            entry['input_digest']='different-semantic-input'
            self.assertTrue(rt.current_media_proof(entry))
            entry['generation_frames']=89
            self.assertFalse(rt.current_media_proof(entry))
    def test_actual_frames_cannot_be_declared_as_input_76(self):
        entry={'video_path':self.clip.name,'generation_frames':76,'generation_fps':'24'}
        with patch.object(rt,'P',self.root),self.assertRaises(ValueError):rt.media_check(entry)
    def test_actual_over_10_seconds_cannot_hide_behind_declared_240(self):
        entry={'video_path':self.longclip.name,'generation_frames':240,'generation_fps':'24'}
        with patch.object(rt,'P',self.root),self.assertRaises(ValueError):rt.media_check(entry)
    def test_audio_missing_rejected_before_upload(self):
        entry={'video_path':self.source.name,'generation_frames':21,'generation_fps':'24'}
        with patch.object(rt,'P',self.root),self.assertRaisesRegex(ValueError,'decodable audio'):rt.media_check(entry)
    def test_complete_video_audio_preflight(self):
        entry={'video_path':self.clip.name,'generation_frames':90,'generation_fps':'24'}
        with patch.object(rt,'P',self.root):rt.media_check(entry)


class UpgradeTests(unittest.TestCase):
    setUp=InputTests.setUp
    tearDown=InputTests.tearDown
    seal=InputTests.seal
    def test_087_raw_23_frame_submission_rejected(self):
        self.entry.update(source_segment='087',generation_frames=23)
        rt.source.CAST['087']='一'
        self.entry['reference_paths']=self.entry['reference_paths'][:1]
        self.entry['profile']['app_id']='2107844752011010050'
        with self.assertRaisesRegex(ValueError,'23 real frames'):rt.validate(self.project,self.entry)
    def test_pilot_is_invalidated_by_reference_swap(self):
        self.entry['pilot']=False;self.seal()
        output=self.project/'pilot.mp4';output.write_bytes(b'old pilot')
        cfg=rt.read(self.project/'runtime.json');route=rt.pilot_route(self.entry,cfg)
        cfg['pilot_reviews']={route:{'route':route,'status':'passed','notes':'reviewed fixture',
            'output':str(output),'output_sha256':rh.sha(output)}}
        rt.write(self.project/'runtime.json',cfg);self.seal();rt.validate(self.project,self.entry)
        from PIL import Image
        Image.new('RGB',(16,16),'red').save(self.project/'替换用参考图/一号.png')
        self.seal()
        with self.assertRaisesRegex(ValueError,'reviewed pilot'):rt.validate(self.project,self.entry)
    def test_appearance_change_invalidates_semantic_approval(self):
        cfg=rt.read(self.project/'runtime.json');cfg['appearance_policy']={'style':'smooth'}
        rt.write(self.project/'runtime.json',cfg)
        with self.assertRaisesRegex(ValueError,'Inputs changed'):rt.validate(self.project,self.entry)
    def test_prepare_preserves_unchanged_semantic_review(self):
        rt.write(self.project/'approved-queue.json',{'jobs':[self.entry]})
        old=self.entry['semantic_review']
        with patch.object(rt,'current_media_proof',return_value=True):rt.main(['prepare'])
        self.assertEqual(rt.read(self.project/'approved-queue.json')['jobs'][0]['semantic_review'],old)
    def test_partial_stage_without_hashed_evidence_rejected(self):
        self.entry['edit_roles']='一';self.entry['reference_paths']=self.entry['reference_paths'][:1]
        self.entry['profile']['app_id']='2107844752011010050'
        with self.assertRaisesRegex(ValueError,'staged single-role'):rt.validate(self.project,self.entry)


if __name__=='__main__':
    with patch('urllib.request.urlopen',side_effect=AssertionError('Offline tests must not access the network')):
        unittest.main(verbosity=2)
