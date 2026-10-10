"""Local PHP HTTP authentication tests, disposable keys and no external network."""
import hashlib
import hmac
import json
from pathlib import Path
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parents[1]
KEY = b'r' * 32


def test_route_http_auth_and_read_only_scope(tmp_path):
    private = tmp_path/'ftp-staging-pr75/private';private.mkdir(parents=True)
    public = tmp_path/'public_html/eleicoes/__staging_pr75';public.mkdir(parents=True)
    shutil.copyfile(ROOT/'deploy/locaweb/ftp-staging-probe.php',public/'probe.php')
    shutil.copyfile(ROOT/'deploy/locaweb/ftp-publication.php',private/'ftp-publication.php')
    (public/'probe-marker.json').write_text('{"fixture":"replace_a"}')
    config = {'fixture_only':True,'environment':'fixture','root':str(private.parent.resolve()),
              'public_root':str(public.resolve()),'fixture_key':KEY.hex(),
              'allowed_actions':['runtime','read'],'activation_host':''}
    # Simulate the web server's HTTPS flag, only on this localhost test server.
    router = tmp_path/'router.php'
    router.write_text('<?php $_SERVER["HTTPS"]="on"; require ' + json.dumps(str(public/'probe.php')) + ';')
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
    process = subprocess.Popen(['php','-S',f'127.0.0.1:{port}',str(router)],
                               stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    url=f'http://127.0.0.1:{port}/probe.php'
    try:
        deadline=time.monotonic()+5
        while True:
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=0.1):break
            except OSError:
                if process.poll() is not None or time.monotonic()>deadline:
                    pytest.fail('local_php_server_unavailable')
                time.sleep(0.05)
        def request(action=None, signature=True, stamp=None):
            raw=json.dumps({'action':action},separators=(',',':')).encode() if action else None
            headers={}
            if raw is not None:
                timestamp=str(stamp if stamp is not None else int(time.time()))
                headers={'X-Timestamp':timestamp,'X-Signature':hmac.new(KEY,timestamp.encode()+b'\n'+raw,'sha256').hexdigest() if signature else '0'*64}
            try:response=urllib.request.urlopen(urllib.request.Request(url,data=raw,headers=headers),timeout=3)
            except urllib.error.HTTPError as error:response=error
            with response:return response.status,json.loads(response.read()),response.headers
        # No configuration exists yet: anonymous requests must still be generic.
        status,value,headers=request()
        assert status==401 and value=={'error':'invalid_fixture_auth'}
        assert headers['Cache-Control']=='no-store'
        (private/'staging-config.json').write_text(json.dumps(config))
        before=sorted(p.name for p in private.iterdir())
        for action,signature,stamp in [('runtime',False,None),('runtime',True,int(time.time())-120)]:
            status,value,_=request(action,signature,stamp)
            assert status==401 and value=={'error':'invalid_fixture_auth'}
        status,value,_=request('runtime')
        assert status==200 and value['sapi']=='cli-server'
        assert value['fixture_root']==str(private.parent.resolve()) and 'fixture_key' not in value
        assert request('read')[1]['marker']=={'fixture':'replace_a'}
        for action in ['lock','replace_b']:
            status,value,_=request(action)
            assert status==409 and value=={'error':'fixture_action_not_approved'}
        assert sorted(p.name for p in private.iterdir())==before
        assert json.loads((public/'probe-marker.json').read_text())=={'fixture':'replace_a'}
    finally:
        process.terminate()
        process.wait(timeout=5)
