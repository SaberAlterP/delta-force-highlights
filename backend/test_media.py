from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from types import SimpleNamespace

from app.services import media


class Client:
    def __init__(self,path):self.path=path
    def get(self,_url,headers=None):
        r=media.video_response(self.path,SimpleNamespace(headers={k.lower():v for k,v in (headers or {}).items()}))
        if not hasattr(r,'body'):  # FileResponse
            r.body=self.path.read_bytes()
        return SimpleNamespace(status_code=r.status_code,content=r.body,headers=r.headers)


class VideoResponseTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.path=Path(self.temp.name)/'a.mp4'
        self.path.write_bytes(bytes(range(256))*40000)  # 10 MB
        self.client=Client(self.path)

    def tearDown(self):self.temp.cleanup()

    def test_open_range_is_capped_and_file_released(self):
        r=self.client.get('/v',headers={'Range':'bytes=0-'})
        self.assertEqual(r.status_code,206)
        self.assertEqual(len(r.content),media.CHUNK)
        self.assertEqual(r.headers['content-range'],f'bytes 0-{media.CHUNK-1}/{self.path.stat().st_size}')
        self.path.unlink()  # 响应结束后文件句柄已关闭，可直接删除

    def test_tail_and_bounded_ranges(self):
        size=self.path.stat().st_size
        r=self.client.get('/v',headers={'Range':'bytes=-100'})
        self.assertEqual(r.content,self.path.read_bytes()[-100:])
        r=self.client.get('/v',headers={'Range':'bytes=10-19'})
        self.assertEqual(r.content,self.path.read_bytes()[10:20])
        self.assertEqual(self.client.get('/v',headers={'Range':f'bytes={size}-'}).status_code,416)

    def test_no_range_returns_whole_file(self):
        r=self.client.get('/v')
        self.assertEqual(r.status_code,200);self.assertEqual(len(r.content),self.path.stat().st_size)
