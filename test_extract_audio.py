import json
import wave
from array import array
import shutil
import subprocess
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import main

@pytest.fixture
def client(tmp_path, monkeypatch):
    source = tmp_path / 'source.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=96x64:duration=3','-f','lavfi','-i',r'aevalsrc=sin(2*PI*(440+440*gte(t\,1))*t):d=3','-shortest','-c:v','libx264','-c:a','aac',str(source)],check=True)
    temp=tmp_path/'temp';output=tmp_path/'output';temp.mkdir();output.mkdir()
    async def download(url,dest):shutil.copyfile(source,dest)
    scheduled=[]
    monkeypatch.setattr(main,'TEMP_DIR',str(temp));monkeypatch.setattr(main,'OUTPUT_DIR',str(output));monkeypatch.setattr(main,'API_KEY','test-key');monkeypatch.setattr(main,'download_file',download);monkeypatch.setattr(main,'schedule_file_deletion',scheduled.append)
    return TestClient(main.app),temp,output,scheduled

def post(c,**extra):
    return c.post('/extract-audio',headers={'X-API-Key':'test-key'},json={'video_url':'https://example.com/source.mp4','start_seconds':1,'end_seconds':2,**extra})

def test_exact_audio_interval(client):
    c,temp,_,scheduled=client;r=post(c);assert r.status_code==200,r.text
    data=r.json();assert data['had_audio'];assert scheduled==[data['output_path']];assert list(temp.iterdir())==[]
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',data['output_path']]))
    assert len(probe['streams'])==1;assert probe['streams'][0]['codec_name']=='pcm_s16le';assert abs(float(probe['format']['duration'])-1)<0.02
    # The source switches from 440 to 880 Hz at 1s. A wrong offset can still
    # produce a 1s file, so verify that extraction starts in the second tone.
    with wave.open(data['output_path'], 'rb') as wav:
        samples = array('h', wav.readframes(12000))
        crossings = sum(a <= 0 < b for a, b in zip(samples, samples[1:]))
        assert abs(crossings / 0.25 - 880) < 8

@pytest.mark.parametrize('overrides',[{'start_seconds':2,'end_seconds':1},{'end_seconds':31},{'end_seconds':4},{'start_seconds':-1},{'end_seconds':'NaN'}])
def test_invalid_ranges(client,overrides):
    c,temp,output,scheduled=client;assert post(c,**overrides).status_code==422;assert not list(temp.iterdir());assert not list(output.iterdir());assert not scheduled

def test_silent_and_authenticated(client,monkeypatch):
    c,temp,output,scheduled=client
    assert c.post('/extract-audio',json={'video_url':'https://example.com/source.mp4','end_seconds':2}).status_code==401
    monkeypatch.setattr(main,'has_audio_stream',lambda path:False)
    r=post(c);assert r.status_code==200;assert r.json()['had_audio'] is False;assert r.json()['output_path'] is None
    assert not list(temp.iterdir());assert not list(output.iterdir());assert not scheduled

def test_cleanup_on_encode_failure(client,monkeypatch):
    c,temp,output,scheduled=client
    def fail(_,path,*args):Path(path).write_bytes(b'partial');raise ValueError('bad audio')
    monkeypatch.setattr(main,'extract_source_audio',fail)
    assert post(c).status_code==422;assert not list(temp.iterdir());assert not list(output.iterdir());assert not scheduled


def test_delayed_audio_keeps_leading_silence(client, tmp_path, monkeypatch):
    c, _, _, _ = client
    source = tmp_path / 'delayed.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=96x64:duration=3', '-itsoffset', '1', '-f', 'lavfi', '-i', 'sine=duration=2', '-c:v', 'libx264', '-c:a', 'aac', str(source)], check=True)
    async def download(url, dest):
        shutil.copyfile(source, dest)
    monkeypatch.setattr(main, 'download_file', download)
    response = post(c, start_seconds=0, end_seconds=3)
    assert response.status_code == 200, response.text
    with wave.open(response.json()['output_path'], 'rb') as wav:
        samples = array('h', wav.readframes(wav.getnframes()))
        assert max(abs(x) for x in samples[:38400]) == 0
        assert max(abs(x) for x in samples[52800:62400]) > 1000
