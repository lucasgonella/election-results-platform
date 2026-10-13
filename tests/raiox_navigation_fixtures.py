"""Invented offline records. Names reproduce the navigation, not real finances."""


def navigation_fixture(extra_donors=0):
    names = [("charles", "CHARLES BENTO"), ("bia", "BIA EXEMPLO"),
             ("davi", "DAVI EXEMPLO")]
    candidates = [dict(id="registration:" + key, person_id="person:" + key,
                       name=name, civil_name=name, party="EX", number=str(1000 + i),
                       office="deputado federal" if i != 1 else "deputado estadual",
                       revenue=None, expenses=None, votes=None)
                  for i, (key, name) in enumerate(names)]
    entities = [dict(id="person:" + key, name=name, civil_name=name, kind="person",
                     roles=["candidate"], candidate_ids=["registration:" + key],
                     campaign_ids=["campaign:" + key], aliases=[])
                for key, name in names]
    entities += [dict(id="campaign:" + key, name="Campanha " + name, kind="campaign",
                      owner_person_id="person:" + key, roles=["campaign"],
                      candidate_ids=["registration:" + key], aliases=[],
                      cnpj="12.345.678/0001-00", evidence=[])
                 for key, name in names]
    for key, name in [("izaura", "IZAURA CRISTINA PERES"),
                      ("homonym", "IZAURA CRISTINA PERES"),
                      ("paulo", "PAULO EXEMPLO")]:
        entities.append(dict(id="person:" + key, name=name, kind="person",
                             roles=["donor"], candidate_ids=[], aliases=[]))

    def row(key, source, target, amount):
        return dict(id="transaction:" + key, from_id="person:" + source,
                    to_id="person:" + target, from_name=source, to_name=target,
                    amount=amount, date="01/09/2026", type="Doação sintética",
                    from_role="person", to_role="candidate",
                    to_campaign_id="campaign:" + target,
                    source_record_id="receipt:" + key, source_row=len(key),
                    source_file="fixture.csv",
                    source_url="https://dadosabertos.tse.jus.br/dataset/fixture")

    transfers = [row("ic", "izaura", "charles", 100),
                 row("ib", "izaura", "bia", 200),
                 row("id", "izaura", "davi", 300),
                 row("ib-distinct", "izaura", "bia", 200),
                 row("hc", "homonym", "charles", 40),
                 row("pb", "paulo", "bia", 50)]
    for i in range(extra_donors):
        key = "extra:" + str(i)
        entities.append(dict(id="person:" + key, name="DOADOR SINTÉTICO " + str(i),
                             kind="person", roles=["donor"], candidate_ids=[], aliases=[]))
        transfers.append(row("extra:" + str(i), key, "davi", i + 1))
    return dict(scope="GO", year=2026, identity_schema=1,
                candidates=candidates, entities=entities, transfers=transfers,
                generated_at="2026-10-13T10:00:00Z")
