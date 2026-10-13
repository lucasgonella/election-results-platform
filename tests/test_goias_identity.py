"""Synthetic identity fixtures; no operational tax documents or secrets."""
import json
from pathlib import Path
import tempfile
import unittest
from tests.test_goias_finance_etl import create_zip
from tools.goias_finance_etl import build
from tools.goias_identity import document, assert_private_documents_absent

CPF_A = '12345678909'
CPF_B = '98765432100'
CNPJ = '12345678000195'


def export(candidate_rows=None, income_rows=None, extra=None):
    candidate_rows = candidate_rows or ['GO;6;101;Nome de Urna;Nome Civil;' + CPF_A + ';AAA;1234', 'GO;7;102;Destino;Outra Pessoa;' + CPF_B + ';BBB;12345']
    income_rows = income_rows if income_rows is not None else ['102;11;125,50;' + CPF_A + ';Nome Civil;01/10/2026;-1;' + CNPJ + ';7']
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        c = tmp / 'c.zip'; f = tmp / 'f.zip'
        create_zip(c, {'consulta_cand_2026_GO.csv': 'SG_UF;CD_CARGO;SQ_CANDIDATO;NM_URNA_CANDIDATO;NM_CANDIDATO;NR_CPF_CANDIDATO;SG_PARTIDO;NR_CANDIDATO\n' + '\n'.join(candidate_rows) + '\n'})
        files = {'receitas_candidatos_2026_GO.csv': 'SQ_CANDIDATO;SQ_RECEITA;VR_RECEITA;NR_CPF_CNPJ_DOADOR;NM_DOADOR;DT_RECEITA;SQ_CANDIDATO_DOADOR;NR_CNPJ_PRESTADOR_CONTA;SQ_PRESTADOR_CONTAS\n' + '\n'.join(income_rows) + '\n',
                 'despesas_contratadas_candidatos_2026_GO.csv': 'SQ_CANDIDATO;SQ_DESPESA;VR_DESPESA_CONTRATADA\n102;9;10,00\n'}
        files.update(extra or {})
        create_zip(f, files)
        return build(c, f)


def candidate(data, cid='101'):
    return next(c for c in data['candidates'] if c['id'] == cid)


def person(data, cid='101'):
    return next(e for e in data['entities'] if e['id'] == candidate(data, cid)['person_id'])


class IdentityTests(unittest.TestCase):
    def test_same_full_cpf_unifies_roles_with_different_names(self):
        d = export()
        self.assertEqual(d['transfers'][0]['from_id'], person(d)['id'])
        self.assertIn('donor', person(d)['roles'])
        self.assertEqual(person(d)['civil_name'], 'Nome Civil')
        self.assertEqual(person(d)['name'], 'Nome de Urna')
        self.assertEqual(d['identity_audit']['personal_identities_confirmed'], 1)

    def test_similar_names_different_cpfs_do_not_merge(self):
        d = export(income_rows=['102;11;10,00;' + CPF_B + ';Nome Civil;01/10/2026;-1;' + CNPJ + ';7'])
        self.assertNotEqual(d['transfers'][0]['from_id'], person(d)['id'])
        self.assertNotIn('donor', person(d)['roles'])

    def test_masked_cpf_not_identity_and_not_unique_key(self):
        d = export(income_rows=['102;11;10,00;***456789**;Nome Civil;01/10/2026;-1;;', '102;12;20,00;***456789**;Nome Civil;02/10/2026;-1;;'])
        self.assertEqual(len({t['from_id'] for t in d['transfers']}), 2)
        self.assertEqual(d['identity_audit']['masked_or_missing_document_records'], 2)
        self.assertNotIn('***456789**', json.dumps(d))

    def test_empty_account_declaration_never_becomes_financial_edge(self):
        d = export(income_rows=['101;-1;0,00;-1;;;-1;;8', '102;11;10,00;' + CPF_A + ';Nome Civil;01/10/2026;-1;;7'])
        self.assertEqual(len(d['transfers']), 1)
        self.assertEqual(candidate(d)['revenue'], 0)
        self.assertEqual(d['identity_audit']['empty_revenue_declarations_excluded_from_graph'], 1)
        self.assertNotIn('beneficiary', person(d)['roles'])
        self.assertEqual(d['identity_audit']['donor_records_examined'], 1)

    def test_account_identifier_cannot_replace_transaction_sequence(self):
        with self.assertRaisesRegex(ValueError, 'official receipt sequence'):
            export(income_rows=['102;-1;10,00;' + CPF_A + ';Nome Civil;01/10/2026;-1;;7'])

    def test_zero_value_with_official_receipt_is_preserved(self):
        d = export(income_rows=['102;11;0,00;' + CPF_A + ';Nome Civil;01/10/2026;-1;;7'])
        self.assertEqual(len(d['transfers']), 1)
        self.assertEqual(d['transfers'][0]['amount'], 0)
        self.assertEqual(d['identity_audit']['empty_revenue_declarations_excluded_from_graph'], 0)

    def test_missing_cpf_preserves_anonymous_transaction(self):
        d = export(income_rows=['102;11;10,00;;Nome Civil;01/10/2026;-1;;'])
        self.assertEqual(len(d['transfers']), 1)
        self.assertEqual(d['identity_audit']['personal_identities_confirmed'], 0)
        self.assertEqual(d['transfers'][0]['identity']['status'], 'unconfirmed')

    def test_campaign_cnpj_is_ownership_not_personal_cpf(self):
        d = export(income_rows=['101;10;200,00;' + CPF_B + ';Outra Pessoa;01/10/2026;-1;' + CNPJ + ';8', '102;11;50,00;' + CNPJ + ';Nome Civil;02/10/2026;101;;'])
        row = next(t for t in d['transfers'] if t['source_record_id'] == '11')
        origin = next(e for e in d['entities'] if e['id'] == row['from_id'])
        self.assertEqual(origin['kind'], 'campaign')
        self.assertEqual(origin['owner_person_id'], person(d)['id'])
        self.assertEqual(row['from_role'], 'campaign')
        self.assertNotIn('donor', person(d)['roles'])
        self.assertIn('campaign_financier', person(d)['roles'])

    def test_distinct_campaign_documents_of_same_candidate_never_collide(self):
        other = '11222333000181'
        d = export(income_rows=['101;10;200,00;' + CPF_B + ';Outra Pessoa;01/10/2026;-1;' + CNPJ + ';8', '101;12;100,00;' + CPF_B + ';Outra Pessoa;02/10/2026;-1;' + other + ';8', '102;11;50,00;' + CNPJ + ';Nome Civil;02/10/2026;101;;', '102;13;25,00;' + other + ';Nome Civil;03/10/2026;101;;'])
        campaigns = [e for e in d['entities'] if e['kind'] == 'campaign' and e['owner_person_id'] == person(d)['id']]
        self.assertEqual(len(campaigns), 2)
        self.assertEqual(len({e['id'] for e in campaigns}), 2)
        self.assertEqual({e['cnpj'] for e in campaigns}, {CNPJ, other})
        by_id = {e['id']: e for e in campaigns}
        by_record = {t['source_record_id']: t for t in d['transfers']}
        self.assertEqual(by_id[by_record['10']['to_campaign_id']]['cnpj'], CNPJ)
        self.assertEqual(by_id[by_record['12']['to_campaign_id']]['cnpj'], other)
        self.assertEqual(len({t['from_campaign_id'] for t in d['transfers'] if t['from_role'] == 'campaign'}), 2)

    def test_campaign_cnpj_conflicting_owners_not_unified(self):
        d = export(income_rows=['101;10;200,00;' + CPF_B + ';Outra Pessoa;01/10/2026;-1;' + CNPJ + ';8', '102;11;50,00;' + CNPJ + ';Nome Civil;02/10/2026;101;' + CNPJ + ';9'])
        row = next(t for t in d['transfers'] if t['source_record_id'] == '11')
        self.assertEqual(row['from_role'], 'organization')
        self.assertEqual(d['identity_audit']['identity_conflicts'], 1)

    def test_same_person_multiple_candidacies(self):
        d = export(candidate_rows=['GO;6;101;Urna A;Nome Civil;' + CPF_A + ';AAA;1234', 'GO;7;102;Urna B;Nome Civil;' + CPF_A + ';BBB;12345'])
        self.assertEqual(candidate(d)['person_id'], candidate(d, '102')['person_id'])
        self.assertEqual(len(person(d)['candidate_ids']), 2)
        self.assertEqual(d['identity_audit']['candidate_nodes_unified'], 1)

    def test_multiple_donations_and_duplicate_transactions_preserve_totals(self):
        row = '102;11;125,50;' + CPF_A + ';Nome Civil;01/10/2026;-1;' + CNPJ + ';7'
        d = export(income_rows=[row, row, '102;12;25,25;' + CPF_A + ';Outro nome;02/10/2026;-1;' + CNPJ + ';7'])
        self.assertEqual(len(d['transfers']), 2)
        self.assertEqual(sum(t['amount'] for t in d['transfers']), 150.75)
        self.assertEqual(candidate(d, '102')['revenue'], 150.75)
        self.assertEqual(candidate(d, '102')['expenses'], 10)
        self.assertEqual(d['identity_audit']['existing_accounting_duplicates_skipped'], 1)
        self.assertEqual(len({t['from_id'] for t in d['transfers']}), 1)
        self.assertEqual({t['source_record_id'] for t in d['transfers']}, {'11', '12'})

    def test_repeated_candidate_rows_not_duplicate_people(self):
        row = 'GO;6;101;Nome de Urna;Nome Civil;' + CPF_A + ';AAA;1234'
        d = export(candidate_rows=[row, row, 'GO;7;102;Destino;Outra Pessoa;' + CPF_B + ';BBB;12345'])
        self.assertEqual(len(d['candidates']), 2)
        self.assertEqual(person(d)['candidate_ids'], ['101'])

    def test_conflicting_candidate_documents_fail_closed(self):
        d = export(candidate_rows=['GO;6;101;Urna;Civil;' + CPF_A + ';AAA;1234', 'GO;6;101;Urna;Civil;' + CPF_B + ';AAA;1234', 'GO;7;102;Destino;Outra Pessoa;' + CPF_B + ';BBB;12345'])
        self.assertNotEqual(d['transfers'][0]['from_id'], person(d)['id'])
        self.assertEqual(d['identity_audit']['identity_conflicts'], 1)

    def test_donor_sequence_conflict_prevents_link(self):
        d = export(income_rows=['102;11;10,00;' + CPF_A + ';Nome Civil;01/10/2026;102;;'])
        self.assertNotEqual(d['transfers'][0]['from_id'], person(d)['id'])
        self.assertEqual(d['transfers'][0]['identity']['status'], 'conflict')

    def test_idempotent_resolution_and_non_cpf_based_identifiers(self):
        a = export(); b = export()
        a.pop('generated_at'); b.pop('generated_at')
        a.pop('source'); b.pop('source')
        self.assertEqual(a, b)
        for entity in a['entities']:
            self.assertRegex(entity['id'], r'^(person|campaign|donor):[a-f0-9-]{36}$')

    def test_no_cpf_in_public_json_or_urls(self):
        d = export()
        text = json.dumps(d)
        self.assertNotIn(CPF_A, text); self.assertNotIn(CPF_B, text)
        self.assertNotIn('donor_document', text)
        assert_private_documents_absent(d, {CPF_A, CPF_B})
        for value in [CPF_A, '123.456.789-09', 'https://example.test/?cpf=' + CPF_A]:
            with self.assertRaises(ValueError): assert_private_documents_absent({'leaf': value}, {CPF_A})

    def test_invalid_or_partial_documents(self):
        for value in ['123456', '***456789**', '11111111111', '12345678900', None, '-1', '12345678909X']:
            self.assertIsNone(document(value, 11))
        self.assertEqual(document('123.456.789-09', 11), CPF_A)
        self.assertEqual(document(CNPJ, 14), CNPJ)

    def test_original_donor_never_becomes_direct_sender(self):
        extra = {'receitas_candidatos_2026_GO.csv': 'SQ_CANDIDATO;SQ_RECEITA;VR_RECEITA;NR_CPF_CNPJ_DOADOR;NM_DOADOR;NR_CPF_CNPJ_DOADOR_ORIGINARIO;NM_DOADOR_ORIGINARIO\n102;11;10,00;' + CPF_B + ';Outra Pessoa;' + CPF_A + ';Nome Civil\n'}
        d = export(extra=extra)
        self.assertEqual(d['transfers'][0]['from_id'], person(d, '102')['id'])
        self.assertNotIn('donor', person(d)['roles'])


if __name__ == '__main__': unittest.main()
