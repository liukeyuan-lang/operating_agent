"""Real FFmpeg cuts: full timeline, correct colours, audio and unchanged source."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from material_media import analysis_clip,duration_seconds,ffmpeg_path,ranges,upload_media,video_compression_enabled
from media import inspect_mp4
from material_formats import MIMES
from PIL import Image


class MediaSegmentsTest(unittest.TestCase):
    def test_new_container_and_audio_formats_normalize_with_duration_and_audio(self):
        try:binary=ffmpeg_path()
        except ValueError as error:self.skipTest(str(error))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for suffix,codec in [('.mkv','libx264'),('.avi','mpeg4'),('.webm','libvpx-vp9')]:
                source=root/('video'+suffix)
                subprocess.run([binary,'-loglevel','error','-y','-f','lavfi','-i','color=c=blue:s=64x48:r=8:d=2',
                                '-f','lavfi','-i','sine=frequency=440:sample_rate=16000:duration=2',
                                '-c:v',codec,'-c:a','libopus' if suffix=='.webm' else 'aac','-shortest',str(source)],capture_output=True,check=True,timeout=30)
                entry={'path':str(source),'relative_path':source.name,'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'mime':MIMES[suffix]}
                self.assertAlmostEqual(duration_seconds(entry),2,delta=.2)
                with analysis_clip(entry,.5,1.5,root/'clips') as clip:
                    specs=inspect_mp4(clip['path'])['specs'];self.assertEqual(clip['mime'],'video/mp4')
                    self.assertTrue(specs['audio_track']);self.assertAlmostEqual(specs['duration_seconds'],1,delta=.2)
            for suffix,codec in [('.m4a','aac'),('.flac','flac'),('.ogg','libvorbis')]:
                source=root/('audio'+suffix)
                subprocess.run([binary,'-loglevel','error','-y','-f','lavfi','-i','sine=frequency=440:duration=2','-c:a',codec,str(source)],capture_output=True,check=True,timeout=30)
                entry={'path':str(source),'relative_path':source.name,'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'mime':MIMES[suffix]}
                self.assertAlmostEqual(duration_seconds(entry),2,delta=.2)
                with analysis_clip(entry,0,2,root/'clips') as clip:
                    self.assertEqual(clip['mime'],'audio/mp3');self.assertAlmostEqual(duration_seconds(clip),2,delta=.2)

    def test_animated_gif_becomes_full_video_instead_of_only_first_frame(self):
        try:ffmpeg_path()
        except ValueError as error:self.skipTest(str(error))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'animation.gif'
            Image.new('RGB',(64,48),'red').save(source,save_all=True,append_images=[Image.new('RGB',(64,48),'blue')],duration=500,loop=0)
            entry={'path':str(source),'relative_path':source.name,'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'mime':'image/gif'}
            duration=duration_seconds(entry);self.assertAlmostEqual(duration,1,delta=.1)
            with analysis_clip(entry,0,duration,root/'clips') as clip:
                self.assertEqual(clip['mime'],'video/mp4');self.assertAlmostEqual(inspect_mp4(clip['path'])['specs']['duration_seconds'],1,delta=.2)
                binary=ffmpeg_path()
                frames=subprocess.run([binary,'-loglevel','error','-i',clip['path'],'-f','rawvideo','-pix_fmt','rgb24','pipe:1'],capture_output=True,check=True,timeout=30).stdout
                self.assertGreaterEqual(len(frames),64*48*3*2);frame=frames[-64*48*3:]
                self.assertGreater(sum(frame[2::3]),sum(frame[0::3])*2)

    def test_compression_is_off_by_default_and_can_be_enabled(self):
        with patch.dict(os.environ,{},clear=True):self.assertFalse(video_compression_enabled())
        with patch.dict(os.environ,{'MATERIAL_COMPRESS_VIDEO':'1'}):self.assertTrue(video_compression_enabled())
        with patch.dict(os.environ,{'MATERIAL_COMPRESS_VIDEO':'0'}):self.assertFalse(video_compression_enabled())

    def test_disabled_compression_sends_same_large_file_bytes_without_encoder(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'large.mp4';source.write_bytes(b'original-not-reencoded'*(1024*64))
            body=source.read_bytes();entry={'path':str(source),'relative_path':source.name,'sha256':hashlib.sha256(body).hexdigest(),'mime':'video/mp4'}
            with patch.dict(os.environ,{'MATERIAL_COMPRESS_VIDEO':'0'}),patch('material_media.INLINE_VIDEO_BYTES',1024),patch('material_media.ffmpeg_path',side_effect=AssertionError('must not encode')):
                with upload_media(entry,None,root/'copies') as upload:
                    self.assertIs(upload,entry);self.assertEqual(Path(upload['path']).read_bytes(),body)
            self.assertFalse((root/'copies').exists())

    def test_large_video_copy_keeps_duration_audio_and_original_and_is_cleaned(self):
        try:binary=ffmpeg_path()
        except ValueError as error:self.skipTest(str(error))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'large.mp4'
            subprocess.run([binary,'-loglevel','error','-y','-f','lavfi','-i','color=c=blue:s=320x180:r=12:d=2',
                            '-f','lavfi','-i','sine=frequency=440:sample_rate=8000:duration=2',
                            '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(source)],capture_output=True,check=True,timeout=30)
            # Valid trailing MP4 padding creates an oversized source without large test media.
            with source.open('ab') as stream:stream.write(b'\0'*(2*1024*1024))
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            entry={'path':str(source),'relative_path':source.name,'sha256':digest,'mime':'video/mp4'}
            with patch.dict(os.environ,{'MATERIAL_COMPRESS_VIDEO':'1'}),patch('material_media.INLINE_VIDEO_BYTES',1024*1024):
                with upload_media(entry,2,root/'copies') as prepared:
                    self.assertNotEqual(prepared['path'],str(source));self.assertLess(prepared['size'],1024*1024)
                    self.assertEqual(prepared['preparation']['method'],'compressed_video')
                    specs=inspect_mp4(prepared['path'])['specs']
                    self.assertAlmostEqual(specs['duration_seconds'],2,delta=.2);self.assertTrue(specs['audio_track'])
                    self.assertEqual((specs['width'],specs['height']),(320,180))
                self.assertFalse(Path(prepared['path']).exists())
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),digest)

    def test_real_eleven_minute_video_covers_all_three_segments_and_keeps_audio(self):
        try:binary=ffmpeg_path()
        except ValueError as error:self.skipTest(str(error))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'timeline.mp4'
            command=[binary,'-hide_banner','-loglevel','error','-y']
            for colour,duration in [('blue',300),('red',300),('green',60)]:
                command+=['-f','lavfi','-i',f'color=c={colour}:s=96x64:r=1:d={duration}']
            command+=['-f','lavfi','-i','sine=frequency=440:sample_rate=8000:duration=660',
                      '-filter_complex','[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]','-map','[v]','-map','3:a',
                      '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(source)]
            subprocess.run(command,capture_output=True,check=True,timeout=60)
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            entry={'path':str(source),'relative_path':source.name,'sha256':digest,'mime':'video/mp4'}
            self.assertAlmostEqual(duration_seconds(entry),660,delta=.2)
            intervals=ranges(duration_seconds(entry));self.assertEqual(intervals,[(0,300),(300,600),(600,660)])
            for (start,end),channel in zip(intervals,[2,0,1]):
                with analysis_clip(entry,start,end,root/'clips') as clip:
                    specs=inspect_mp4(clip['path'])['specs']
                    self.assertAlmostEqual(specs['duration_seconds'],end-start,delta=.2)
                    self.assertTrue(specs['audio_track'])
                    frame=subprocess.run([binary,'-loglevel','error','-ss','1','-i',clip['path'],'-frames:v','1',
                                          '-f','rawvideo','-pix_fmt','rgb24','pipe:1'],capture_output=True,check=True,timeout=30).stdout
                    self.assertEqual(len(frame),96*64*3)
                    averages=[sum(frame[i::3])/(96*64) for i in range(3)]
                    self.assertGreater(averages[channel],max(v for i,v in enumerate(averages) if i!=channel)+60)
                self.assertFalse(Path(clip['path']).exists())
            self.assertEqual(list((root/'clips').iterdir()),[])
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),digest)
