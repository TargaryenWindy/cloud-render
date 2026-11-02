"""Retention limited to application-owned UUID job directories."""
import re
import time
import recovery

DEFAULTS = {'retention_days': 30, 'source_retention_days': 7, 'inactive_retention_days': 30}

def collect(data, state, active_id=None, now=None):
    now = time.time() if now is None else now
    settings = {**DEFAULTS, **state.get('cleanup', {})}
    deleted = 0
    kept = []
    known = {j['id'] for j in state['jobs']}
    for job in state['jobs']:
        ident = job['id']
        folder = data / ident
        if (not re.fullmatch('[a-f0-9]{32}', ident) or ident == active_id or
            job.get('preview_building') or job.get('downloads', 0) or
            job['status'] in ('queued', 'rendering', 'stopping', 'encoding') or
            folder.is_symlink() or folder.resolve().parent != data.resolve()):
            kept.append(job)
            continue
        complete = job['status'] == 'completed'
        days = settings['retention_days'] if complete else settings['inactive_retention_days']
        age = now - job.get('updated', job.get('finished', job.get('created', now)))
        try:
            if days and age > days * 86400:
                recovery.safe_remove(data, ident)
                deleted += 1
                continue
            source_days = settings['source_retention_days']
            if complete and source_days and age > source_days * 86400:
                recovery.safe_remove(folder, 'project.blend')
                job['source_removed'] = True
        except OSError:
            pass  # A download may still have an open Windows file handle; retry later.
        kept.append(job)
    state['jobs'] = kept
    for folder in data.iterdir():
        if (not re.fullmatch('[a-f0-9]{32}', folder.name) or not folder.is_dir() or
            folder.name in known or folder.is_symlink() or folder.resolve().parent != data.resolve()):
            continue
        part = folder / 'project.part'
        if part.exists() and now - part.stat().st_mtime > 86400:
            try:
                recovery.safe_remove(data, folder.name)
                deleted += 1
            except OSError:
                pass
    return deleted
