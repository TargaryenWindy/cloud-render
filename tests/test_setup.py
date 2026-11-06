import tempfile
import unittest
import zipfile
import io
from pathlib import Path
from unittest.mock import patch
import dependencies as d

class SetupTest(unittest.TestCase):
    def test_newest_working_installed_blender(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = [Path(temp)/name for name in ('steam','standalone','broken')]
            for path in paths:
                path.touch()
            results = [(True,'Blender 4.9.12'),(True,'Blender 4.10.2'),(False,'broken')]
            with patch.object(d,'candidates',return_value=paths), patch.object(d,'executable_check',side_effect=results):
                self.assertEqual(d.find('blender'),str(paths[1].resolve()))

    def test_no_download_when_all_present(self):
        with tempfile.TemporaryDirectory() as temp:
            tools=Path(temp)/'tools'
            with patch.object(d,'TOOLS',tools),patch.object(d,'MANIFEST',tools/'paths.json'),patch.object(d,'find',return_value='/installed/tool'),patch.object(d,'blender_download') as blender,patch.object(d,'ffmpeg_download') as ffmpeg,patch.object(d,'cloudflared_download') as cloud:
                d.ensure(remote=True)
                blender.assert_not_called();ffmpeg.assert_not_called();cloud.assert_not_called()

    def test_only_missing_package_downloaded(self):
        with tempfile.TemporaryDirectory() as temp:
            tools=Path(temp)/'tools'
            installed={'blender':'/installed/blender','ffmpeg':'/installed/ffmpeg'}
            def install():
                installed['ffprobe']='/private/ffprobe'
                return {'ffprobe':'tools/ffprobe'}
            with patch.object(d,'TOOLS',tools),patch.object(d,'MANIFEST',tools/'paths.json'),patch.object(d,'find',side_effect=lambda name,check=False:installed.get(name)),patch.object(d,'blender_download') as blender,patch.object(d,'ffmpeg_download',side_effect=install) as ffmpeg,patch.dict(d.os.environ,{},clear=True):
                d.ensure()
                blender.assert_not_called();ffmpeg.assert_called_once()
                self.assertEqual(installed['ffmpeg'],'/installed/ffmpeg')

    def test_archive_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);archive=root/'bad.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('../escaped','bad')
            with self.assertRaises(RuntimeError):d.extract(archive,root/'unpacked')
            self.assertFalse((root/'escaped').exists())

    def test_checksum_failure_leaves_no_download(self):
        with tempfile.TemporaryDirectory() as temp:
            dest=Path(temp)/'download'
            with patch.object(d,'read_url',return_value=io.BytesIO(b'incorrect')):
                with self.assertRaises(RuntimeError):d.download('https://example.test/tool',dest,'0'*64)
            self.assertFalse(dest.exists());self.assertFalse(dest.with_name('download.part').exists())

    def test_present_but_broken_tool_is_not_redownloaded(self):
        with tempfile.TemporaryDirectory() as temp:
            tools=Path(temp)/'tools';binary=Path(temp)/'blender';binary.write_bytes(b'not executable')
            def find(name,check=True):
                if name=='blender':return None if check else str(binary)
                return '/installed/'+name
            with patch.object(d,'TOOLS',tools),patch.object(d,'MANIFEST',tools/'paths.json'),patch.object(d,'find',side_effect=find),patch.object(d,'executable_check',return_value=(False,'missing libSM')),patch.object(d,'blender_download') as download:
                with self.assertRaisesRegex(RuntimeError,'missing libSM'):d.ensure()
                download.assert_not_called()

    def test_latest_blender_excludes_prereleases(self):
        docs=[b'<a href="Blender5.2/">5.2</a><a href="Blender4.5/">4.5</a>',
              b'blender-5.2.0-beta-linux-x64.tar.xz',
              b'blender-4.5.9-linux-x64.tar.xz blender-4.5.10-linux-x64.tar.xz',
              ('a'*64+'  blender-4.5.10-linux-x64.tar.xz').encode()]
        with patch.object(d,'WINDOWS',False),patch.object(d.platform,'machine',return_value='x86_64'),patch.dict(d.os.environ,{},clear=True),patch.object(d,'read_url',side_effect=[io.BytesIO(doc) for doc in docs]),patch.object(d,'install_archive',return_value={}) as install:
            d.blender_download()
            self.assertIn('blender-4.5.10-linux-x64.tar.xz',install.call_args.args[0])
            self.assertEqual(install.call_args.args[3],'a'*64)

if __name__=='__main__':unittest.main()
