"""Invented 35-target official-shaped responses, restricted to isolated rehearsals."""
from copy import deepcopy
from types import SimpleNamespace
from collector.src.election_release import UFS, canonical, digest
from test_second_round_transactions import Source


class FullSource(Source):
    def __init__(self, generation=1, totalized=50):
        super().__init__(generation=generation, totalized=totalized)
        self.config = {'f': 'o', 'pl': [{'c': 'ele2026', 'e': [
            {'cd': '6258', 't': '2', 'tp': '1', 'nm': 'Fixture federal',
             'abr': [{'cd': 'br', 'cp': [{'cd': '1', 'ds': 'Presidente'}]}]},
            {'cd': '6260', 't': '2', 'tp': '1', 'nm': 'Fixture estadual',
             'abr': [{'cd': uf, 'cp': [{'cd': '3', 'ds': 'Governador'}]} for uf in UFS[:6]]}]}]}

    def fetch_json(self, url):
        if '/comum/' in url: value = self.config
        elif '-ab.json' in url:
            scopes = ['br', *UFS, 'zz'] if '/6258/' in url else UFS[:6]
            value = {'f': 'o', 'ele': '6258' if '/6258/' in url else '6260', 't': '2',
                     'idg': '1', 'abr': [{'tpabr': 'br' if uf == 'br' else 'uf', 'cdabr': uf} for uf in scopes]}
        else:
            value = deepcopy(self.payload)
            scope = url.rsplit('/', 1)[-1].split('-c')[0]
            presidential = '-c0001-' in url
            value.update(ele='6258' if presidential else '6260', cdabr=scope, tpabr='br' if scope == 'br' else 'uf')
            value['carg'][0].update(cd='1' if presidential else '3', nmn='Presidente' if presidential else 'Governador')
        record = {'url': url, 'payload': deepcopy(value), 'sha256': digest(canonical(value))}
        self.records[url] = record
        return SimpleNamespace(payload=deepcopy(value), status_code=200)
