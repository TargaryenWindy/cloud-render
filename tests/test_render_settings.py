import unittest
from types import SimpleNamespace as NS
from render_settings import apply, select_gpu

class SettingsTest(unittest.TestCase):
    def test_overrides_and_fractional_fps(self):
        scene = NS(render=NS(engine='CYCLES', resolution_x=1920, resolution_y=1080, fps=24, fps_base=1), cycles=NS(samples=128))
        apply(scene, {'resolution_x': 640, 'samples': 8, 'fps': 23.976})
        self.assertEqual(scene.render.resolution_x, 640)
        self.assertEqual(scene.render.resolution_y, 1080)
        self.assertEqual(scene.cycles.samples, 8)
        self.assertAlmostEqual(scene.render.fps/scene.render.fps_base, 23.976)

    def test_nvidia_amd_and_cpu(self):
        for available, expected in [('OPTIX','OPTIX'), ('HIP','HIP'), ('NONE','CPU')]:
            class Preferences:
                devices = []
                compute_device_type = ''
                def refresh_devices(self):
                    self.devices = [NS(type=available, name='Test GPU', use=False), NS(type='CPU', name='CPU', use=True)] if self.compute_device_type == available else []
            prefs = Preferences()
            bpy = NS(context=NS(preferences=NS(addons={'cycles': NS(preferences=prefs)})))
            scene = NS(render=NS(engine='CYCLES'), cycles=NS(device='CPU'))
            self.assertEqual(select_gpu(bpy, scene), expected)
            self.assertEqual(scene.cycles.device, 'CPU' if expected=='CPU' else 'GPU')
            if expected != 'CPU':
                self.assertTrue(prefs.devices[0].use)
                self.assertFalse(prefs.devices[1].use)

if __name__ == '__main__':
    unittest.main()
