"""Presidential round-two BU counters, private checkpoints and public aggregates.

The three counters are BU-wide. They are attributable to President only when
the presidential attendance agrees with the BU attendance. No voter identities
or association between authentication and a candidate are collected.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
import sqlite3
import zlib

ELECTION = {'year': 2026, 'round': 2, 'code': 6258, 'pleito': 3221, 'office': 1}
UFS = 'ac al am ap ba ce df es go ma mg ms mt pa pb pe pi pr rj rn ro rr rs sc se sp to zz'.split()
SOURCE = 'https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3221'
FIELDS = ('attendance', 'biometric', 'biographic', 'no_registration', 'unknown')


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class Node:
    tag: int
    value: bytes

    def children(self):
        if not self.tag & 32:
            raise ValueError('biometry_expected_sequence')
        return nodes(self.value)

    def integer(self, tags=(2,)):
        if self.tag not in tags or not 1 <= len(self.value) <= 5 or self.value[0] & 128:
            raise ValueError('biometry_invalid_integer')
        return int.from_bytes(self.value, 'big')


def nodes(raw):
    """Bounded definite-length BER as emitted by the 2026 official BU reader."""
    result, offset = [], 0
    while offset < len(raw):
        if offset + 2 > len(raw):
            raise ValueError('biometry_truncated_ber')
        tag, length = raw[offset:offset + 2]
        offset += 2
        if tag & 31 == 31:
            raise ValueError('biometry_unsupported_ber_tag')
        if length & 128:
            width = length & 127
            if not 1 <= width <= 4 or offset + width > len(raw):
                raise ValueError('biometry_invalid_ber_length')
            length = int.from_bytes(raw[offset:offset + width], 'big')
            offset += width
        if offset + length > len(raw):
            raise ValueError('biometry_truncated_ber')
        result.append(Node(tag, raw[offset:offset + length]))
        offset += length
        if len(result) > 10000:
            raise ValueError('biometry_oversized_ber_sequence')
    return result


def sequence(raw):
    parsed = nodes(raw)
    if len(parsed) != 1 or parsed[0].tag != 48:
        raise ValueError('biometry_invalid_root')
    return parsed[0].children()


def identity(node):
    children = node.children()
    if len(children) != 3:
        raise ValueError('biometry_invalid_section_identity')
    place = children[0].children()
    if len(place) != 2:
        raise ValueError('biometry_invalid_section_identity')
    return (f'{place[0].integer():05d}', f'{place[1].integer():04d}',
            f'{children[2].integer():04d}')


def header(node):
    fields = node.children()
    if len(fields) != 2 or fields[0].tag != 27:
        raise ValueError('biometry_wrong_voting_date')
    datetime.strptime(fields[0].value.decode('ascii'), '%Y%m%dT%H%M%S')
    if fields[1].integer((130,)) != ELECTION['pleito']:
        raise ValueError('biometry_wrong_pleito')


def parse_bu(raw, target):
    if not 32 < len(raw) <= 2 * 1024 * 1024:
        raise ValueError('biometry_invalid_bu_size')
    envelope = sequence(raw)
    if len(envelope) != 5 or envelope[4].tag != 4:
        raise ValueError('biometry_invalid_envelope')
    header(envelope[0])
    if envelope[1].integer((10,)) != 2 or envelope[3].integer((10,)) != 1:
        raise ValueError('biometry_not_official_bu')
    expected = tuple(target[key] for key in ('municipality', 'zone', 'section'))
    body = sequence(envelope[4].value)
    if len(body) < 9:
        raise ValueError('biometry_unsupported_bu_layout')
    header(body[0])
    if envelope[2].tag == 161:
        board = envelope[2].children()
        place = board[0].children() if len(board) == 1 else []
        envelope_matches = (len(place) == 2 and
                            (f'{place[0].integer():05d}', f'{place[1].integer():04d}') == expected[:2])
    else:
        envelope_matches = envelope[2].tag == 160 and identity(envelope[2]) == expected
    if body[1].integer((10,)) != 2 or not envelope_matches or identity(body[3]) != expected:
        raise ValueError('biometry_bu_identity_mismatch')
    attendance = body[6].integer()
    offset = 8 if body[7].tag == 161 else 7
    if body[offset].tag != 48:
        raise ValueError('biometry_missing_election_results')
    presidents = [entry.children() for entry in body[offset].children()
                  if entry.tag == 48 and entry.children()[0].integer() == ELECTION['code']]
    if len(presidents) != 1:
        raise ValueError('biometry_missing_presidential_election')
    president = presidents[0]
    if len(president) < 5 or attendance > president[1].integer():
        raise ValueError('biometry_attendance_exceeds_electorate')
    groups = president[4].children()
    if len(groups) != 1:
        raise ValueError('biometry_ambiguous_presidential_attendance')
    group = groups[0].children()
    presidential_attendance = group[1].integer()
    if presidential_attendance != attendance:
        if body[5].tag == 161 and offset == 7 and attendance == 0:
            # Paper/SA bulletins can leave BU-wide authentication attendance
            # unset. Their presidential turnout remains known, authentication
            # remains unavailable, and is never inferred as manual or biometric.
            attendance = presidential_attendance
        else:
            raise ValueError('biometry_presidential_attendance_mismatch')
    if attendance > president[1].integer():
        raise ValueError('biometry_attendance_exceeds_electorate')
    cargos = group[2].children()
    if len(cargos) != 1 or cargos[0].children()[0].integer((129,)) != 1:
        raise ValueError('biometry_wrong_office')
    votes = cargos[0].children()[2].children()
    if sum(vote.children()[1].integer((130,)) for vote in votes) != attendance:
        raise ValueError('biometry_presidential_votes_mismatch')
    result = {**dict(zip(('municipality', 'zone', 'section'), expected)),
              'uf': target['uf'], 'attendance': attendance, 'biometric': 0,
              'biographic': 0, 'no_registration': 0, 'unknown': attendance,
              'generated_at': body[0].children()[0].value.decode('ascii')}
    if offset == 8:
        counts = [value.integer() for value in body[7].children()]
        if len(counts) != 3 or sum(counts) != attendance:
            raise ValueError('biometry_counter_balance_mismatch')
        # Official 2026 BU reader: biographical, biometrical, without registration.
        result.update(biographic=counts[0], biometric=counts[1], no_registration=counts[2], unknown=0)
    return result


def database(state):
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(state / 'biometry.sqlite3')
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=FULL')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sections(
            uf TEXT, municipality TEXT, zone TEXT, section TEXT, name TEXT NOT NULL,
            stamp TEXT NOT NULL, collected_stamp TEXT, priority INTEGER NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0,
            attendance INTEGER, biometric INTEGER, biographic INTEGER, no_registration INTEGER,
            unknown INTEGER, source_url TEXT, source_sha256 TEXT, captured_at TEXT, raw BLOB,
            error TEXT, PRIMARY KEY(uf,municipality,zone,section),
            CHECK(attendance IS NULL OR (attendance>=0 AND biometric>=0 AND biographic>=0
                AND no_registration>=0 AND unknown>=0
                AND attendance=biometric+biographic+no_registration+unknown)));
        CREATE INDEX IF NOT EXISTS biometry_queue ON sections(retry_at,attempts,priority);
    ''')
    return db


def set_meta(db, key, value):
    db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', (key, json.dumps(value)))


def meta(db, key, default=None):
    row = db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def store(db, target, raw, source_url):
    parsed = parse_bu(raw, target)
    db.execute('''UPDATE sections SET collected_stamp=?, attendance=?,biometric=?,biographic=?,
        no_registration=?,unknown=?,source_url=?,source_sha256=?,captured_at=?,raw=?,error=NULL,
        retry_at=0,attempts=attempts+1 WHERE uf=? AND municipality=? AND zone=? AND section=?''',
        (target['stamp'], *(parsed[key] for key in FIELDS), source_url, sha(raw), now(),
         zlib.compress(raw), *(target[key] for key in ('uf', 'municipality', 'zone', 'section'))))
    db.commit()
    return parsed


def aggregate(db):
    expected = meta(db, 'inventory')
    if not expected or expected['sections'] != db.execute('SELECT COUNT(*) FROM sections').fetchone()[0]:
        raise ValueError('biometry_inventory_not_ready')
    municipalities = []
    for row in db.execute('''SELECT uf,municipality,name,COUNT(*) expected,
        SUM(CASE WHEN collected_stamp=stamp THEN 1 ELSE 0 END) processed,
        SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) failures,
        MAX(captured_at) captured_at,
        ''' + ','.join(f'SUM(CASE WHEN collected_stamp=stamp THEN {key} ELSE 0 END) {key}' for key in FIELDS)
        + ' FROM sections GROUP BY uf,municipality,name ORDER BY uf,name,municipality'):
        value = dict(row)
        for key in FIELDS:
            value[key] = value[key] or 0
        municipalities.append(value)
    fields = ('expected', 'processed', 'failures', *FIELDS)
    def sum_rows(rows):
        return {key: sum(row[key] for row in rows) for key in fields}
    states = [{**sum_rows([row for row in municipalities if row['uf'] == uf]),
               'uf': uf, 'name': expected['ufs'][uf]['name']} for uf in UFS]
    totals = sum_rows(states)
    value = {'schema': 1, 'environment': 'oficial', 'election': ELECTION,
             'generated_at': meta(db, 'last_source_success_at') or now(),
             'last_source_success_at': meta(db, 'last_source_success_at'),
             'complete': totals['processed'] == totals['expected'],
             'national_reference': expected['national'], 'totals': totals,
             'states': states, 'municipalities': municipalities,
             'source_inventories': expected['ufs'], 'exterior_included': True,
             'samples': [dict(row) for row in db.execute('''SELECT uf,municipality,zone,section,
                source_url,source_sha256,attendance,biometric,biographic,no_registration,unknown
                FROM sections WHERE collected_stamp=stamp ORDER BY captured_at DESC LIMIT 8''')]}
    validate(value)
    return value


def validate(value):
    if value.get('schema') != 1 or value.get('environment') != 'oficial' or value.get('election') != ELECTION:
        raise ValueError('biometry_wrong_dataset')
    if {row['uf'] for row in value['states']} != set(UFS) or len(value['states']) != len(UFS):
        raise ValueError('biometry_incomplete_uf_inventory')
    if len({(row['uf'], row['municipality']) for row in value['municipalities']}) != len(value['municipalities']):
        raise ValueError('biometry_duplicate_municipality')
    if any(row['uf'] not in UFS or not re.fullmatch(r'\d{5}', row['municipality'])
           for row in value['municipalities']):
        raise ValueError('biometry_invalid_municipality')
    for row in [value['totals'], *value['states'], *value['municipalities']]:
        for key in ('expected', 'processed', 'failures', *FIELDS):
            if type(row.get(key)) is not int or row[key] < 0:
                raise ValueError('biometry_invalid_aggregate')
        if row['processed'] > row['expected'] or row['attendance'] != sum(row[key] for key in FIELDS[1:]):
            raise ValueError('biometry_invalid_aggregate_balance')
    for state in value['states']:
        rows = [row for row in value['municipalities'] if row['uf'] == state['uf']]
        for key in ('expected', 'processed', 'failures', *FIELDS):
            if state[key] != sum(row[key] for row in rows):
                raise ValueError('biometry_state_aggregate_mismatch')
    for key in ('expected', 'processed', 'failures', *FIELDS):
        if value['totals'][key] != sum(row[key] for row in value['states']):
            raise ValueError('biometry_national_aggregate_mismatch')
    if type(value['complete']) is not bool or value['complete'] != (value['totals']['expected'] == value['totals']['processed']):
        raise ValueError('biometry_invalid_completeness')
    if value['totals']['expected'] != value['national_reference']['sections']:
        raise ValueError('biometry_national_inventory_mismatch')
    if value['totals']['attendance'] > value['national_reference']['attendance']:
        raise ValueError('biometry_national_attendance_exceeded')
    if value['complete'] and value['totals']['attendance'] != value['national_reference']['attendance']:
        raise ValueError('biometry_national_attendance_mismatch')
    return value
