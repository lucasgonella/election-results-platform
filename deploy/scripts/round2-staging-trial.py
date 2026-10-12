"""Opt-in synthetic FTP21/HTTPS trial, exclusively in a separate staging tree.

No production round marker, first-round service or private production state.
"""
from pathlib import Path
import json
import argparse
import secrets
import sys
import tempfile
from urllib.error import HTTPError
from urllib.request import Request, build_opener

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tests'))
from collector.src import second_round_publish as pub
from collector.src.election_release import parse
from deploy.frontend import NoRedirect, error_report
from test_second_round_transactions import package, Crash


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume',type=Path)
    args=parser.parse_args()
    if args.resume:
        directory=args.resume
        context=pub.load(directory/'context.json')
        trial=context['trial']
    else:
        trial=secrets.token_hex(8)
        directory=Path(tempfile.mkdtemp(prefix='election-round2-staging-',dir='/var/tmp'))
        pub.save(directory/'context.json',{'trial':trial})
    if not __import__('re').fullmatch('[a-f0-9]{16}',trial):raise ValueError('invalid_staging_trial')
    # Process-local fixed override; production CLI has no destination override.
    pub.SITE='/public_html/__election_round2_staging/trials/'+trial+'/data/turnos/2'
    pub.PRIVATE='/election-round2-staging-'+trial
    url='https://afgnet.com.br'+pub.SITE.removeprefix('/public_html')+'/'
    assert '/__election_round2_staging/' in pub.SITE and pub.SITE != '/public_html/data/turnos/2'
    def http(relative):
        try:
            with build_opener(NoRedirect).open(Request(url+relative,headers={
                'Cache-Control':'no-cache','Accept-Encoding':'identity'}),timeout=20) as response:
                if response.status!=200 or response.geturl()!=url+relative:raise RuntimeError('staging_https_response')
                return response.read(16777217)
        except HTTPError as error:
            if error.code==404:return None
            raise
    t=pub.connect()
    try:
        publisher=pub.Publisher(t,directory/'state',http=http)
        if args.resume:
            with pub.local_lock(directory/'state'): publisher.recover()
        first=directory/'one'
        if not first.exists(): package(first)
        with pub.local_lock(directory/'state'):
            result=publisher.publish(first)
            assert publisher.publish(first)['status']=='unchanged'
            old=publisher.marker()
            second=directory/'two'
            if not second.exists():package(second,2)
            publisher.fault=lambda point: (_ for _ in ()).throw(Crash()) if point=='before_activation' else None
            try:publisher.publish(second)
            except Crash:pass
            assert publisher.marker()==old
            publisher.fault=lambda _:None
            assert publisher.recover()['status']=='published'
            third=directory/'three'
            if not third.exists():package(third,3)
            publisher.fault=lambda point: (_ for _ in ()).throw(Crash()) if point=='after_activation' else None
            try:publisher.publish(third)
            except Crash:pass
            selected=publisher.marker()
            publisher.fault=lambda _:None
            assert publisher.recover()['snapshot_id']==parse(selected)['snapshot_id']
            status=publisher.status()
        report={'status':'staging_trial_passed','production_namespace_written':False,
            'trial':trial,'https_base':url,'checks':['FTP21 passive STOR RETR hash',
            'immutable collision protection','HTTPS all files','marker replacement',
            'unchanged','interruption before activation','interruption after activation',
            'owner-bound recovery','checkpoint reconciliation'],'final':status}
        pub.save(directory/'report.json',report)
        print(json.dumps(report,sort_keys=True))
    except Exception as error:
        print(json.dumps({'local_trial':str(directory),'trial':trial,'pending_phase':(pub.load(directory/'state/pending.json') or {}).get('phase'),'frames':[f.name for f in __import__('traceback').extract_tb(error.__traceback__)],**error_report(error)}))
        raise SystemExit(2) from None
    finally:t.ftp.close()


if __name__=='__main__':main()
