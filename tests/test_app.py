import importlib.util
import os
import tempfile
import unittest
import io
import zipfile
from pathlib import Path

class AppTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parents[1])
        os.environ['RENDER_DATA'] = self.temp.name
        spec = importlib.util.spec_from_file_location('render_test_app', Path(__file__).parents[1] / 'app.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.client = self.module.app.test_client()

    def tearDown(self):
        self.temp.cleanup()
        os.environ.pop('RENDER_DATA', None)

    def login(self):
        r = self.client.post('/api/login', json={'password': self.module.config['password']})
        return {'X-CSRF-Token': r.json['csrf']}

    def test_auth_and_csrf(self):
        self.assertEqual(self.client.get('/api/state').status_code, 401)
        self.assertEqual(self.client.post('/api/login', json={'password': 'wrong'}).status_code, 401)
        headers = self.login()
        self.assertEqual(self.client.post('/api/queue', json={'paused': True}).status_code, 403)
        self.client.post('/api/queue', json={'paused': True}, headers=headers)
        self.assertTrue(self.client.get('/api/state').json['paused'])

    def test_upload_queue_cancel_retry(self):
        headers = self.login()
        r = self.client.post('/api/uploads', json={'name': '<test>.blend', 'size': 12}, headers=headers)
        ident = r.json['id']
        self.assertEqual(self.client.post(f'/api/uploads/{ident}/finish', headers=headers).status_code, 400)
        self.assertEqual(self.client.put(f'/api/uploads/{ident}?offset=1', data=b'BLENDER12345', headers=headers).status_code, 409)
        self.assertEqual(self.client.put(f'/api/uploads/{ident}?offset=0', data=b'BLENDER12345', headers=headers).status_code, 200)
        self.assertEqual(self.client.post(f'/api/uploads/{ident}/finish', headers=headers).status_code, 200)
        self.assertEqual(self.client.get(f'/api/jobs/{ident}/video').status_code, 404)
        for action, status in [('cancel', 'stopped'), ('retry', 'queued')]:
            self.assertEqual(self.client.post(f'/api/jobs/{ident}/{action}', headers=headers).status_code, 200)
            self.assertEqual(self.client.get('/api/state').json['jobs'][0]['status'], status)
        self.assertTrue(self.module.STATE.exists())

    def test_pause_active_job_and_resume_queue(self):
        m = self.module
        headers = self.login()
        ident = 'c' * 32
        folder = Path(self.temp.name) / ident
        folder.mkdir()
        job = dict(id=ident, status='rendering', name='scene.blend')
        waiting = dict(id='d'*32, status='queued')
        hidden = dict(id='e'*32, status='stopped', hidden=True)
        m.state['jobs'] = [job, waiting, hidden]
        m.active_id = ident
        def queue(paused):
            return self.client.post('/api/queue', json={'paused': paused}, headers=headers)
        self.assertEqual(queue(True).status_code, 200)
        self.assertTrue((folder/'stop.request').exists())
        self.assertEqual(job['status'], 'stopping')
        self.assertEqual(queue(False).status_code, 409)
        job['status'] = 'stopped'
        m.active_id = None
        (folder/'checkpoint.json').write_text('{}')
        self.assertEqual(self.client.get(f'/api/jobs/{ident}/video').status_code, 404)
        self.assertEqual(queue(False).status_code, 200)
        self.assertEqual([j['status'] for j in m.state['jobs']], ['queued', 'queued', 'stopped'])

    def test_video_range(self):
        self.login()
        ident = 'a' * 32
        folder = Path(self.temp.name) / ident
        folder.mkdir()
        (folder / 'output.mp4').write_bytes(b'0123456789')
        self.module.state['jobs'].append({'id': ident, 'status': 'completed', 'name': 'test.blend'})
        with self.client.get(f'/api/jobs/{ident}/video', headers={'Range': 'bytes=2-5'}) as r:
            self.assertEqual(r.status_code, 206)
            self.assertEqual(r.data, b'2345')

    def test_manual_start_reorder_clear(self):
        headers = self.login()
        self.assertTrue(self.client.get('/api/state').json['paused'])
        self.module.state['jobs'] = [{'id': str(i), 'status': status} for i, status in enumerate(['queued', 'completed', 'queued', 'rendering'])]
        self.assertEqual(self.client.post('/api/queue/order', json={'ids': ['2', '0']}, headers=headers).status_code, 200)
        self.assertEqual([j['id'] for j in self.module.state['jobs'] if j['status'] == 'queued'], ['2', '0'])
        self.assertEqual(self.client.post('/api/queue/order', json={'ids': ['0']}, headers=headers).status_code, 409)
        self.client.post('/api/queue/clear', json={}, headers=headers)
        self.assertFalse(any(j['status'] == 'queued' for j in self.module.state['jobs']))
        self.assertTrue(all(j.get('hidden') for j in self.module.state['jobs']))
        self.assertEqual(self.client.get('/api/state').json['jobs'], [])

    def test_remove_settings_and_bulk_download(self):
        headers = self.login()
        for char in ('a', 'b'):
            ident = char * 32
            folder = Path(self.temp.name) / ident
            folder.mkdir()
            (folder / 'output.mp4').write_bytes(b'video-' + char.encode())
            self.module.state['jobs'].append({'id': ident, 'status': 'completed', 'name': 'same.blend'})
        ident = 'a' * 32
        self.client.post(f'/api/jobs/{ident}/remove', json={}, headers=headers)
        self.assertEqual(len(self.client.get('/api/state').json['jobs']), 1)
        self.assertEqual(self.client.get('/api/download-all').status_code, 302)
        self.assertEqual(len(self.client.get('/api/downloads').json['files']), 2)
        self.client.post('/api/settings', json={'zip_threshold': 2}, headers=headers)
        with self.client.get('/api/download-all') as r:
            self.assertEqual(r.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(r.data)) as archive:
                self.assertEqual(len(archive.namelist()), 2)
                self.assertEqual(len(set(archive.namelist())), 2)
        ident = 'b' * 32
        folder = Path(self.temp.name) / ident
        (folder / 'checkpoint.json').write_text('{}')
        for invalid in ({'samples': -1}, {'fps': 'nan'}, {'resolution_x': 10.5}, {'engine': 'arbitrary'}):
            self.assertEqual(self.client.post(f'/api/jobs/{ident}/settings', json=invalid, headers=headers).status_code, 400)
        self.assertEqual(self.client.post(f'/api/jobs/{ident}/settings', json={'resolution_x': 640, 'samples': 32, 'fps': 23.976}, headers=headers).status_code, 200)
        self.assertFalse((folder / 'checkpoint.json').exists())
        self.assertEqual(self.module.state['jobs'][1]['status'], 'stopped')
        self.assertEqual(__import__('json').loads((folder/'settings.json').read_text())['fps'], 23.976)
        self.module.state['jobs'][1]['status'] = 'rendering'
        self.assertEqual(self.client.post(f'/api/jobs/{ident}/settings', json={}, headers=headers).status_code, 409)

    def test_zip_threshold(self):
        headers = self.login()
        self.assertEqual(self.client.get('/api/state').json['zip_threshold'], 10)
        for invalid in (0, -1, 1.5, 1001, None, True):
            self.assertEqual(self.client.post('/api/settings', json={'zip_threshold': invalid}, headers=headers).status_code, 400)
        self.assertEqual(self.client.post('/api/settings', json={'zip_threshold': 15, 'fps': 30}, headers=headers).status_code, 200)
        self.assertEqual(self.client.get('/api/state').json['zip_threshold'], 15)
        self.assertEqual(self.module.state['global_settings'], {'fps': 30})

    def test_global_priority_and_checkpoint_invalidation(self):
        headers = self.login()
        self.assertEqual(self.client.post('/api/settings', json={'fps': 0}, headers=headers).status_code, 400)
        self.assertEqual(self.client.post('/api/settings', json={'fps': 30, 'samples': 64}, headers=headers).status_code, 200)
        self.assertEqual(self.client.get('/api/state').json['global_settings'], {'fps': 30, 'samples': 64})
        ident = 'c' * 32
        folder = Path(self.temp.name) / ident
        folder.mkdir()
        job = {'id': ident, 'name': 'test.blend', 'status': 'stopped', 'settings': {'samples': 8}, 'frame': 10}
        self.module.state['jobs'].append(job)
        effective = self.module.prepare_settings(job, folder)
        self.assertEqual(effective, {'fps': 30, 'samples': 8})
        (folder / 'checkpoint.json').write_text('{}')
        # A masked global change must preserve this project's checkpoints.
        self.client.post('/api/settings', json={'fps': 30, 'samples': 128}, headers=headers)
        self.module.prepare_settings(job, folder)
        self.assertTrue((folder / 'checkpoint.json').exists())
        # An inherited change requires a new render.
        self.client.post('/api/settings', json={'fps': 60, 'samples': 128}, headers=headers)
        self.assertEqual(self.module.prepare_settings(job, folder), {'fps': 60, 'samples': 8})
        self.assertFalse((folder / 'checkpoint.json').exists())
        self.assertIsNone(job['frame'])
        # Clearing the project field returns it to global inheritance.
        self.client.post(f'/api/jobs/{ident}/settings', json={'samples': None}, headers=headers)
        self.assertEqual(self.module.effective_settings(job), {'fps': 60, 'samples': 128})
        self.client.post('/api/settings', json={}, headers=headers)
        self.assertEqual(self.module.effective_settings(job), {})

if __name__ == '__main__':
    unittest.main()
