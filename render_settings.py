"""Apply job-only overrides and select supported Cycles GPU devices."""
def apply(scene, options):
    for field in ('resolution_x', 'resolution_y', 'resolution_percentage'):
        if field in options:
            setattr(scene.render, field, options[field])
    if 'fps' in options:
        scene.render.fps = round(options['fps'])
        scene.render.fps_base = scene.render.fps / options['fps']
    if 'samples' in options:
        if scene.render.engine == 'CYCLES':
            scene.cycles.samples = options['samples']
        elif hasattr(scene, 'eevee') and hasattr(scene.eevee, 'taa_render_samples'):
            scene.eevee.taa_render_samples = options['samples']
        else:
            print('CLOUD_SETTINGS: Samples override is unavailable for this render engine.', flush=True)

def select_gpu(bpy, scene):
    if scene.render.engine != 'CYCLES':
        print(f'CLOUD_DEVICE: {scene.render.engine} uses its own GPU selection.', flush=True)
        return 'ENGINE'
    preferences = bpy.context.preferences.addons['cycles'].preferences
    for backend in ('OPTIX', 'HIP'):
        try:
            preferences.compute_device_type = backend
            preferences.refresh_devices()
            devices = [d for d in preferences.devices if d.type == backend]
            if not devices:
                continue
            for device in preferences.devices:
                device.use = device.type == backend
            scene.cycles.device = 'GPU'
            print(f'CLOUD_DEVICE: {backend} | ' + ', '.join(d.name for d in devices), flush=True)
            return backend
        except Exception as exc:
            print(f'CLOUD_DEVICE: {backend} unavailable: {exc}', flush=True)
    scene.cycles.device = 'CPU'
    print('CLOUD_DEVICE: No compatible OptiX/HIP GPU available; using CPU.', flush=True)
    return 'CPU'
