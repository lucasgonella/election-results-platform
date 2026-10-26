"""Invented BU structures and counts. Never an operational/public dataset."""
from collector.src.biometry import ELECTION, UFS, FIELDS


def tlv(tag, raw):
    size = len(raw)
    length = bytes([size]) if size < 128 else bytes([128 + (size.bit_length()+7)//8]) + size.to_bytes((size.bit_length()+7)//8, 'big')
    return bytes([tag]) + length + raw


def integer(value, tag=2):
    return tlv(tag, value.to_bytes(max(1, (value.bit_length()+8)//8), 'big'))


def seq(*parts, tag=48):
    return tlv(tag, b''.join(parts))


TARGET = dict(uf='ac', municipality='01074', zone='0004', section='0175', stamp='synthetic')


def bu(*, counters=(10, 163, 10), code=6258, pleito=3221, phase=2, section=175,
       attendance=183, presidential=183, votes=183, manual=False):
    header = seq(tlv(27, b'20261025T190000'), integer(pleito, 130))
    place = seq(integer(1074), integer(4))
    identity = seq(place, integer(1), integer(section))
    envelope_identity = seq(place, tag=161) if manual else seq(place, integer(1), integer(section), tag=160)
    vote = seq(integer(1, 129), integer(votes, 130))
    office = seq(integer(1, 129), integer(0), seq(vote))
    election = seq(integer(code), integer(400), integer(400), integer(0),
                   seq(seq(integer(1, 10), integer(presidential), seq(office))))
    body = seq(header, integer(phase, 10), seq(), identity, tlv(27, b'20261025T190000'),
               seq(tag=161 if manual else 160), integer(attendance),
               *( [seq(*(integer(x) for x in counters), tag=161)] if counters is not None else []),
               seq(election), seq())
    return seq(header, integer(2, 10), envelope_identity, integer(1, 10), tlv(4, body))


def dataset():
    cities = []
    for index, uf in enumerate(UFS):
        processed = uf in {'ac', 'zz'}
        cities.append(dict(uf=uf, municipality=f'{index+1:05d}', name='Localidade sintética '+uf,
                           expected=2, processed=int(processed), failures=0,
                           attendance=183 if processed else 0,
                           biometric=163 if uf=='ac' else 0, biographic=10 if uf=='ac' else 0,
                           no_registration=10 if uf=='ac' else 0, unknown=183 if uf=='zz' else 0))
    states = [{key:value for key,value in row.items() if key!='municipality'} for row in cities]
    totals = {key:sum(row[key] for row in states) for key in ('expected','processed','failures',*FIELDS)}
    return dict(schema=1,environment='oficial',election=ELECTION.copy(),generated_at='2026-10-26T15:00:00+00:00',
                last_source_success_at='2026-10-26T15:00:00+00:00',complete=False, totals=totals,
                national_reference=dict(sections=56,attendance=20000),states=states,municipalities=cities)
