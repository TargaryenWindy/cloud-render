# Render desk

A private Blender render queue for your Windows PC, with remote access through Cloudflare Tunnel.

## Start

1. Install Python 3.10+ with pip, Blender, and FFmpeg/FFprobe. Steam Blender is discovered automatically. For other installations, set `BLENDER_PATH`. FFmpeg/FFprobe are discovered on PATH or in `C:\av1`; override with `FFMPEG_PATH` and `FFPROBE_PATH`.
2. Run `powershell -ExecutionPolicy Bypass -File .\remote.ps1`. It prepares Python dependencies, starts the app if necessary, and prints the tunnel URL last. For local-only use, run `powershell -ExecutionPolicy Bypass -File .\start.ps1`.
3. Find your generated password in `data/config.json`. Open the printed URL or http://127.0.0.1:7860 and sign in.
4. Keep the PC awake. Quick Tunnel addresses change on restart; use the newest URL. Closing the tunnel stops remote access, but the render app can continue locally. For a stable address, configure a named Cloudflare Tunnel.

When moving to another PC, clone this repository and run the launcher there. Do not copy `.venv`: it contains machine-specific Python paths. The launcher detects a broken copied environment and recreates it. Set `RENDER_PYTHON` to explicitly choose the base Python. `start.ps1 -SetupOnly` installs dependencies without starting the server. Cloudflared is downloaded from its official release if absent.

## Queue and overrides

Pack external resources in Blender before saving and uploading. Linked libraries, simulation caches, and external media may require additional preparation. Upload multiple `.blend` files, arrange them by dragging or using the arrows, then press **Start queue**. Uploading never starts rendering by itself. **Pause queue** lets the current project finish before pausing. **Stop & save** stops after the current image frame. During final encoding, it waits for the encoder to exit and keeps the images for resume.

Global settings apply when a project starts. Every field resolves independently:

**Project override → global override → saved Blender file.**

Blank fields inherit. Resolution, percentage, samples and fractional FPS are supported. Cycles selects supported NVIDIA OptiX devices, then AMD HIP, falling back to CPU when neither is available. Other engines use their own device handling. The source `.blend` is never modified.

**Clear queue** and per-project **Remove** hide entries and stop active work gracefully. Completed videos remain available in batch downloads until their retention period expires. Removed waiting projects become inactive and are eligible for retention cleanup.

## Image rendering and final video

The renderer saves an image after every completed animation frame, then atomically updates its checkpoint. **PNG is the default lossless intermediate format.** Settings offer the installed Blender's single-layer image formats (including OpenEXR, TIFF and JPEG), plus depth, color mode and compression controls. Multilayer EXR is excluded because this pipeline imports a single image sequence for encoding. JPEG and other lossy choices can reduce quality; choose PNG or lossless EXR/TIFF to preserve detail. Not every depth/compression option applies to every image format; Blender validates combinations.

After all frames finish, a separate background Blender process encodes the sequence **once**, using Blender's own FFmpeg integration. The settings form discovers available video containers, codecs and advanced video settings from the installed Blender. These include output quality/CRF, bitrate, encoding speed, keyframe interval, B-frames, rate controls and ProRes profile where available. Use compatible container/codec combinations. Selecting constant bitrate makes the bitrate controls relevant; quality/CRF modes control bitrate themselves.

Saved FFmpeg output settings are inherited from the project unless overridden. If the project was saved for still images, the default final video is H.264 MP4 with High Quality. Outputs contain **video only**, consistent with this application's silent renders. Audio and automatic file splitting are excluded. The original animation's frame step is respected; selected frames are encoded consecutively at the configured FPS.

The final movie's decoded frame count must match the saved sequence before cleanup. An encoder failure retains the frames: change video settings and Resume to try encoding again without rendering them again. Video-only changes and the Keep frames preference preserve checkpoints. Changes to render/image settings invalidate checkpoints and require a fresh render. Finished videos whose intermediate frames have been deleted require rendering again to change encoding.

**Keep frames as a downloadable ZIP** defaults to No. After successful encoding:

- No: delete the individual images and intermediate render files.
- Yes: create and verify a ZIP containing the images and a frame manifest, then delete the loose images. **Download frames (ZIP)** appears beside the project.

Existing completed videos remain downloadable. Legacy interrupted video-segment jobs restart using image frames when resumed. Stopped jobs with checkpoints can generate a partial H.264 MP4 preview; generating it leaves source frames untouched. A browser may not play MKV, ProRes, or other formats; download them to use an appropriate player. Partial previews are separate from the final encode.

Use baked simulation caches for deterministic resume. A power loss can lose the frame being written, but committed frames are reused. Missing or damaged checkpoints trigger a fresh render.

## Downloads

Each completed project has an individual video download. **Download all** makes a ZIP at or above a configurable threshold (default 10 videos). Below that threshold it opens a page with individual links and a button to start all downloads. Browsers may request permission for multiple downloads. Batch ZIPs preserve each video's actual extension and do not re-encode anything.

## Storage cleanup

Cleanup runs hourly and can also be triggered with **Clean expired files now** in Global settings. Save changed retention settings before clicking that button. Default policies:

| Files | Retention |
| --- | --- |
| Completed source `.blend` | 7 days |
| Finished videos, optional frame ZIPs, and their job folders | 30 days |
| Stopped, failed, cancelled or removed projects and their checkpoints | 30 days |
| Abandoned incomplete uploads | 24 hours |

The three job retention periods are configurable from 0 to 3650 days; **0 disables that rule**. Job age is measured since its last activity, not since the last download. Queued/active renders and previews being generated are protected. Cleanup only traverses recognized job folders, never the password/configuration, Python environment or Blender installation. It does not follow redirected directories. Open Windows file handles defer deletion until a later pass.

Cleanup permanently deletes expired files. Download wanted results before expiry. When a completed source file expires, Settings is disabled for that project; upload the project again to render it. Frame deletion after a successful encode is independent of the retention periods. Test fixtures and other non-job folders are not swept automatically.

## Privacy and Git

The app binds to loopback, requires a password, and uses session authentication and CSRF protection. Only upload trusted Blender files; embedded Python autoexecution is disabled, but Blender still processes complex local resources. Uploads use 8 MiB requests and have a 100 GB per-file app limit. Startup and tunnel logs are under `data/`.

Git tracks source, tests and documentation. `data/`, `.venv`, environment backups, downloaded tools, credentials, videos and project files are ignored. Never commit `data/config.json` or upload it to GitHub. On another PC, `git clone https://github.com/TargaryenWindy/cloud-render.git`, then follow Start above. Before pulling updates, stop the app and tunnel and restart afterward.

## Verification

- `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
- `.\.venv\Scripts\python.exe tests\recovery_smoke.py`: real Blender stop/resume, non-unit frame step, partial preview, inherited MKV/FFV1 output, H.264 override without rendering again, and verified frame ZIP.
- `.\.venv\Scripts\python.exe tests\gpu_smoke.py`: real NVIDIA OptiX render with overrides, then final video validation.

The integration tests create small generated fixtures under `data/`; they do not use your uploaded projects.
