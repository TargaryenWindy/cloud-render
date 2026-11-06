# Render desk

Licensed under the [MIT License](LICENSE). Downloaded third-party programs, including Blender, FFmpeg, Python, uv, and Cloudflared, retain their respective licenses.

A private Blender render queue for Windows and Linux, with remote access through Cloudflare Tunnel.

## Start

1. Clone the repository. The launchers reuse available Python 3.10+, Blender (including Steam), FFmpeg and FFprobe. Missing programs are downloaded privately into `tools/`; app packages live in `.venv/`. Nothing is added to system PATH. Set `RENDER_PYTHON`, `FFMPEG_PATH`, or `FFPROBE_PATH` to select a particular installation.
2. On Windows run `powershell -ExecutionPolicy Bypass -File .\remote.ps1`. On Linux run `bash remote.sh`. They prepare missing dependencies, start the app if necessary, and print the tunnel URL last. For local-only use, run `powershell -ExecutionPolicy Bypass -File .\start.ps1` or `bash start.sh`.
3. The launcher prints your login password in the terminal (also stored in `data/config.json`). Remote mode prints the password immediately before the tunnel URL, leaving the URL last. Open that URL or http://127.0.0.1:7860 and sign in. Startup logs may contain the password; keep them private.
4. Keep the PC awake. Quick Tunnel addresses change on restart; use the newest URL. Closing the tunnel stops remote access, but the render app can continue locally. For a stable address, configure a named Cloudflare Tunnel.

When moving to another PC, clone this repository and run the launcher there. Do not copy `.venv`: it contains machine-specific Python paths. The launcher detects a broken copied environment and recreates it. Set `RENDER_PYTHON` to explicitly choose the base Python. `start.ps1 -SetupOnly` or `bash start.sh --setup-only` prepares dependencies without starting the server. Cloudflared is downloaded from its official release if absent.

## Queue and overrides

Pack external resources in Blender before saving and uploading. Linked libraries, simulation caches, and external media may require additional preparation. Upload multiple `.blend` files, arrange them by dragging or using the arrows, then press **Start queue**. Uploading never starts rendering by itself. **Stop queue** lets each active render finish its current frame and pauses the queue. Set **Simultaneous files** to 1–16 (default 1). Lowering it takes effect as active jobs finish. The queue rate counts newly saved frames across all jobs per elapsed second since Start, including setup and encoding. Individual jobs show the latest frame duration. Both displays switch to seconds/frame below 1 fps. The top panel reports host GPU load and VRAM when available, RAM, and free space on the job-data volume. **Start queue** resumes visible stopped projects from their saved frames in queue order. During final encoding, it waits for the encoder to exit and keeps the images for resume.

Global settings apply when a project starts. Every field resolves independently:

**Project override → global override → saved Blender file.**

Blank fields inherit. Resolution, percentage, samples and fractional FPS are supported. Cycles selects supported NVIDIA OptiX devices, then AMD HIP, falling back to CPU when neither is available. Other engines use their own device handling. The source `.blend` is never modified.

**Clear queue** and per-project **Hide** hide entries and stop active work gracefully. **Show hidden projects** makes those entries visible again. **Delete files** permanently removes the project, source, videos, frame ZIP and checkpoints immediately; active work is stopped first and deletion occurs when it releases the files. Retention is a fallback for projects you have not manually deleted. Completed videos remain available in batch downloads until their retention period expires. Removed waiting projects become inactive and are eligible for retention cleanup.

## Image rendering and final video

The renderer saves an image after every completed animation frame, then atomically updates its checkpoint. **PNG is the default lossless intermediate format.** Settings offer the installed Blender's single-layer image formats (including OpenEXR, TIFF and JPEG), plus depth, color mode and compression controls. Multilayer EXR is excluded because this pipeline imports a single image sequence for encoding. JPEG and other lossy choices can reduce quality; choose PNG or lossless EXR/TIFF to preserve detail. Not every depth/compression option applies to every image format; Blender validates combinations.

After all frames finish, a separate background Blender process encodes the sequence **once**, using Blender's own FFmpeg integration. The settings form discovers available video containers, codecs and advanced video settings from the installed Blender. These include output quality/CRF, bitrate, encoding speed, keyframe interval, B-frames, rate controls and ProRes profile where available. Use compatible container/codec combinations. Selecting constant bitrate makes the bitrate controls relevant; quality/CRF modes control bitrate themselves.

Saved FFmpeg output settings are inherited from the project unless overridden. If the project was saved for still images, the default final video is H.264 MP4 with High Quality. Blender mixes the project’s timeline audio into the finished video when the mix contains sound. Silent projects produce video-only files. The original animation's frame step is respected; selected frames are encoded consecutively at the configured FPS.

The final movie's decoded frame count must match the saved sequence before cleanup. An encoder failure retains the frames: change video settings and Resume to try encoding again without rendering them again. Video-only changes and the Keep frames preference preserve checkpoints. Changes to render/image settings invalidate checkpoints and require a fresh render. Finished videos whose intermediate frames have been deleted require rendering again to change encoding.

**Keep frames as a downloadable ZIP** defaults to No. After successful encoding:

- No: delete the individual images and intermediate render files.
- Yes: create and verify a ZIP containing the images and a frame manifest, then delete the loose images. **Download frames (ZIP)** appears beside the project.

Existing completed videos remain downloadable. Legacy interrupted video-segment jobs restart using image frames when resumed. Select a stopped job to view its latest saved image. Completed jobs preview the final video. A browser may not play MKV, ProRes, or other formats; download them to use an appropriate player. Global settings include independent file and queue completion sounds for this browser. Click the desk once to enable browser audio playback.

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

Manually deleted projects do not wait for retention expiry and are removed from the saved queue. The three job retention periods are configurable from 0 to 3650 days; **0 disables that rule**. Job age is measured since its last activity, not since the last download. Queued/active renders are protected. Cleanup only traverses recognized job folders, never the password/configuration, Python environment or Blender installation. It does not follow redirected directories. Open Windows file handles defer deletion until a later pass.

Cleanup permanently deletes expired files. Download wanted results before expiry. When a completed source file expires, Settings is disabled for that project; upload the project again to render it. Frame deletion after a successful encode is independent of the retention periods. Test fixtures and other non-job folders are not swept automatically.

## Privacy and Git

The app binds to loopback, requires a password, and uses session authentication and CSRF protection. Only upload trusted Blender files; embedded Python autoexecution is disabled, but Blender still processes complex local resources. Uploads use 8 MiB requests and have a 100 GB per-file app limit. Startup and tunnel logs are under `data/`.

Git tracks source, tests and documentation. `data/`, `.venv`, environment backups, downloaded tools, credentials, videos and project files are ignored. Never commit `data/config.json` or upload it to GitHub. On another PC, `git clone https://github.com/TargaryenWindy/cloud-render.git`, then follow Start above. Before pulling updates, stop the app and tunnel and restart afterward.

## Verification

- `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
- `.\.venv\Scripts\python.exe tests\recovery_smoke.py`: real Blender stop/resume (Windows or Linux), non-unit frame step, packed scene sound, inherited MKV/FFV1 output, H.264 override without rendering again, and verified frame ZIP.
- `.\.venv\Scripts\python.exe tests\gpu_smoke.py`: real NVIDIA OptiX render with overrides, then final video validation.

The integration tests create small generated fixtures under `data/`; they do not use your uploaded projects.

## Dependency downloads

Setup checks each tool separately. A machine with Python and Blender but no FFmpeg downloads only the FFmpeg/FFprobe package. If FFmpeg exists but FFprobe does not, that package is still necessary; the existing FFmpeg stays selected. A local uv setup helper is fetched only when needed to create Python's environment. Missing Python uses uv's managed CPython 3.12 in `tools/python`; if system Python exists but lacks venv, uv reuses it without downloading a replacement. Python packages and setup caches also stay in the project.

Blender comes from `download.blender.org` (the latest final release for the platform; beta/RC builds are excluded). Set `BLENDER_SERIES=4.5`, for example, to choose a release series when downloading a missing Blender. This does not replace an installed Blender. The highest reported version among discovered working installations wins, including Steam and standalone copies. Use `BLENDER_PATH` to include an additional executable in that comparison. Match Blender versions when moving projects between machines; an older Blender may not open a file made in a newer one.

FFmpeg comes from BtbN's builds linked by FFmpeg's download page; Cloudflared and uv come from their official GitHub releases. Blender and FFmpeg archives are checked against their published SHA-256 checksums. Archives are extracted with path checks and successful setup removes its download archives. Existing usable programs are not updated automatically. Portable binaries are kept under `tools/`, which Git ignores.

Full automatic dependency downloads target **Windows x86-64 and Linux x86-64 with glibc**. ARM installations can use preinstalled tools, but automatic FFmpeg installation is currently x86-64 only. Linux needs Bash, curl, tar/xz, CA certificates, and the shared libraries required by Blender. GPU drivers remain the host's responsibility. Setup does not run sudo, install drivers, or change system packages. Network access is needed only for missing dependencies and remote access; local rendering works offline after setup.

## Linux, RunPod and notebooks

For a RunPod GPU Pod, clone under persistent storage such as `/workspace/cloud-render` (confirm the mount's persistence in your Pod configuration), then run:

```bash
cd /workspace/cloud-render
bash remote.sh
```

Keep the process/session running. Ctrl+C stops the tunnel; the background render server continues. Its PID is recorded in `data/server.pid` (under `RENDER_DATA` when set). A network volume is preferable if you need the queue and renders to survive Pod termination. RunPod storage lifetimes differ; see https://www.runpod.io/blog/where-did-my-files-go-a-straight-guide-to-runpod-storage. `RENDER_DATA=/persistent/path` can move uploaded projects and output separately from the app. `PORT` selects the local Linux app port. The app stays bound to loopback; Cloudflared supplies remote access.

On a minimal Ubuntu/Debian image, a missing shared-library error from Blender means the host image needs the relevant system packages. Common requirements include `libx11-6`, `libxi6`, `libxrender1`, `libxxf86vm1`, `libxfixes3`, `libxcursor1`, `libxrandr2`, `libxinerama1`, `libegl1`, `libgl1`, `libsm6`, `libgomp1`, and `libdbus-1-3`. Use a GPU-ready image and install any missing libraries through your image/container administrator. NVIDIA drivers must expose OptiX to the container; otherwise the app logs a CPU fallback. No desktop display is required for Cycles background rendering.

The scripts are compatible with Linux notebook environments, but **Colab is not a dependable host for this web render service**. Google's FAQ warns that bypassing the notebook UI with content-generation web interfaces commonly causes free-tier runtime termination: https://research.google.com/colaboratory/faq.html. Runtime storage may disappear on reset. Use a persistent GPU Pod for this workflow rather than depending on a Colab tunnel remaining available.
