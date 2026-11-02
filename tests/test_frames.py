import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import cleanup
import recovery
import test_app

class EncodingApiTest(unittest.TestCase):
    tearDown = test_app.AppTest.tearDown
    login = test_app.AppTest.login
    def setUp(self):
        test_app.AppTest.setUp(self)
        self.module.schema_cache = {
            'video_codec': {'type': 'ENUM', 'choices': [['H264','H.264'],['FFV1','FFV1']]},
            'video_format': {'type': 'ENUM', 'choices': [['MPEG4','MP4'],['MKV','Matroska']]},
            'frame_format': {'type': 'ENUM', 'choices': [['PNG','PNG'],['OPEN_EXR','EXR']]}}

    def test_encoding_priority_and_preserved_frames(self):
        headers = self.login()
        self.client.post('/api/settings', json={'video_codec':'H264','keep_frames':True}, headers=headers)
        folder = Path(self.temp.name)/('d'*32)
        folder.mkdir()
        job={'id':folder.name,'name':'test.blend','status':'stopped','settings':{}}
        self.module.state['jobs'].append(job)
        self.module.prepare_settings(job,folder)
        (folder/'checkpoint.json').write_text('{}')
        r=self.client.post('/api/jobs/'+folder.name+'/settings',json={'video_codec':'FFV1','video_format':'MKV','keep_frames':False},headers=headers)
        self.assertEqual(r.status_code,200)
        self.module.prepare_settings(job,folder)
        self.assertTrue((folder/'checkpoint.json').exists())
        self.assertEqual(self.module.effective_settings(job)['video_codec'],'FFV1')
        self.assertFalse(self.module.effective_settings(job)['keep_frames'])
        self.assertEqual(self.client.post('/api/jobs/'+folder.name+'/settings',json={'video_codec':'INVALID'},headers=headers).status_code,400)
        self.client.post('/api/jobs/'+folder.name+'/settings',json={'frame_format':'OPEN_EXR'},headers=headers)
        self.assertFalse((folder/'checkpoint.json').exists())

    def test_mixed_output_downloads(self):
        headers=self.login()
        for char,ext in [('a','.mp4'),('b','.mkv')]:
            folder=Path(self.temp.name)/(char*32);folder.mkdir()
            (folder/('output'+ext)).write_bytes(b'video')
            (folder/'output.json').write_text(json.dumps({'file':'output'+ext}))
            self.module.state['jobs'].append({'id':folder.name,'status':'completed','name':'same.blend'})
        self.assertEqual([f['name'] for f in self.client.get('/api/downloads').json['files']],['same.mp4','same.mkv'])
        with self.client.get('/api/jobs/'+('b'*32)+'/video?download=1') as r:
            self.assertIn('same.mkv',r.headers['Content-Disposition'])
        self.client.post('/api/settings',json={'zip_threshold':2},headers=headers)
        import io,zipfile
        with self.client.get('/api/download-all') as r:
            with zipfile.ZipFile(io.BytesIO(r.data)) as z:
                self.assertEqual({Path(n).suffix for n in z.namelist()},{'.mp4','.mkv'})

    def test_delete_immediate_and_active_deferred(self):
        headers=self.login()
        for char,status in [('e','completed'),('f','rendering')]:
            ident=char*32;folder=Path(self.temp.name)/ident;folder.mkdir()
            (folder/'project.blend').write_bytes(b'blend')
            job={'id':ident,'name':'test.blend','status':status}
            self.module.state['jobs'].append(job)
            if status=='rendering':self.module.active_id=ident
            result=self.client.post('/api/jobs/'+ident+'/delete',json={},headers=headers)
            self.assertEqual(result.status_code,200)
            if status=='completed':
                self.assertFalse(folder.exists())
                self.assertNotIn(job,self.module.state['jobs'])
            else:
                self.assertTrue(folder.exists())
                self.assertTrue((folder/'stop.request').exists())
                self.assertTrue(job['delete_requested'])
                self.module.active_id=None
                self.module.delete_job(job)
                self.assertFalse(folder.exists())

    def test_hidden_files_remain_until_deleted_or_expired(self):
        headers=self.login();ident='e'*32;folder=Path(self.temp.name)/ident;folder.mkdir()
        (folder/'output.mp4').write_bytes(b'video')
        self.module.state['jobs'].append({'id':ident,'status':'completed','name':'test.blend'})
        self.client.post('/api/jobs/'+ident+'/remove',json={},headers=headers)
        self.assertTrue(folder.exists())
        self.assertEqual(self.client.get('/api/state').json['jobs'],[])
        self.assertEqual(self.client.get('/api/state?include_hidden=1').json['jobs'][0]['id'],ident)
        self.client.post('/api/jobs/'+ident+'/delete',json={},headers=headers)
        self.assertFalse(folder.exists())

class CleanupTest(unittest.TestCase):
    def test_retention_protects_active_and_waiting_and_config(self):
        with tempfile.TemporaryDirectory() as temp:
            data=Path(temp); now=time.time();jobs=[]
            for n,status in enumerate(['completed','failed','queued','rendering','stopped']):
                ident=f'{n:032x}';folder=data/ident;folder.mkdir();(folder/'project.blend').write_bytes(b'blend')
                jobs.append(dict(id=ident,status=status,created=now-40*86400))
            jobs[-1]['preview_building']=True
            (data/'config.json').write_text('keep')
            state={'jobs':jobs,'cleanup':dict(cleanup.DEFAULTS)}
            self.assertEqual(cleanup.collect(data,state,now=now),2)
            self.assertEqual(len(state['jobs']),3)
            self.assertEqual((data/'config.json').read_text(),'keep')

    def test_sources_and_abandoned_uploads_and_disabled_retention(self):
        with tempfile.TemporaryDirectory() as temp:
            data=Path(temp);now=time.time();ident='a'*32;folder=data/ident;folder.mkdir()
            (folder/'project.blend').write_bytes(b'blend');(folder/'output.mp4').write_bytes(b'video')
            state={'jobs':[dict(id=ident,status='completed',finished=now-10*86400)],'cleanup':dict(cleanup.DEFAULTS)}
            cleanup.collect(data,state,now=now)
            self.assertFalse((folder/'project.blend').exists());self.assertTrue((folder/'output.mp4').exists())
            upload=data/('b'*32);upload.mkdir();part=upload/'project.part';part.write_bytes(b'partial')
            import os
            os.utime(part,(now-90000,now-90000))
            state['cleanup']['retention_days']=0
            cleanup.collect(data,state,now=now+100*86400)
            self.assertFalse(upload.exists());self.assertTrue((folder/'output.mp4').exists())

    def test_frames_deleted_only_after_success_and_optional_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);frames=folder/'frames';frames.mkdir();(frames/'one.png').write_bytes(b'image')
            plan={'version':2,'start':1,'end':1,'step':1,'frames':[{'frame':1,'file':'one.png','size':5}]}
            (folder/'checkpoint.json').write_text(json.dumps(plan))
            (folder/'output.mp4').write_bytes(b'video')
            with patch('recovery.subprocess.run') as run:
                run.return_value.returncode=1
                with self.assertRaises(RuntimeError): recovery.encode(folder,'blender')
            self.assertTrue((frames/'one.png').exists())
            recovery.finish_frames(folder,keep=False)
            self.assertFalse(frames.exists());self.assertFalse((folder/'frames.zip').exists())
            self.assertTrue((folder/'output.mp4').exists())

if __name__=='__main__':unittest.main()
