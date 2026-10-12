from collections import Counter
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from evidence_auditor.audit import audit_package, audit_world, load_members, resolve_citations
from evidence_auditor.cli import main
from evidence_auditor.grading import grade, validate_rubric
from evidence_auditor.schema import ScenarioError, canonical

ROOT = Path(__file__).resolve().parents[1]
def fixture(name='world.json'): return json.loads((ROOT/'examples'/name).read_text())

def package(root):
    world = fixture()
    root.mkdir()
    (root/'services').mkdir()
    (root/'world.json').write_bytes(canonical(world))
    for service in {r['service'] for r in world['records']}:
        (root/'services'/f'{service}.json').write_bytes(canonical({'records': [r for r in world['records'] if r['service'] == service]}))
    (root/'SOP.md').write_text('# Standard operating procedure\n\n' + '\n\n'.join(f"## {c['id']}\n\n{c['text']}" for c in world['clauses']) + '\n')
    (root/'budget.json').write_bytes(canonical({'actors': 3, 'records': 3, 'by_service': dict(Counter(r['service'] for r in world['records'])), 'declared_absences': world['absences']}))
    hashes = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    (root/'checksums.json').write_bytes(canonical(hashes))
    return root

class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_valid_world_and_package_have_no_errors(self):
        self.assertEqual([], audit_world(fixture()))
        self.assertEqual(0, audit_package(package(self.root/'pack'))['errors'])

    def test_zip_and_directory_audits_agree(self):
        directory = package(self.root/'pack')
        archive_path = self.root/'scenario.zip'
        with zipfile.ZipFile(archive_path, 'w') as archive:
            for p in directory.rglob('*'):
                if p.is_file(): archive.write(p, p.relative_to(directory).as_posix())
        self.assertEqual(audit_package(directory), audit_package(archive_path))

    def test_tampered_service_and_hash_are_detected(self):
        root = package(self.root/'pack')
        p = root/'services/tickets.json'
        data = json.loads(p.read_text())
        data['records'][0]['body']['status'] = 'closed'
        p.write_bytes(canonical(data))
        codes = {f['code'] for f in audit_package(root)['findings']}
        self.assertTrue({'service_projection_mismatch', 'hash_mismatch'} <= codes)

    def test_budget_and_sop_mismatches_are_detected(self):
        root = package(self.root/'pack')
        (root/'budget.json').write_text('{}')
        (root/'SOP.md').write_text('Different policy')
        codes = {f['code'] for f in audit_package(root)['findings']}
        self.assertTrue({'budget_mismatch', 'sop_projection_mismatch'} <= codes)

    def test_missing_hash_inventory_is_detected(self):
        root = package(self.root/'pack')
        (root/'checksums.json').write_text('{}')
        self.assertIn('checksum_inventory_mismatch', {f['code'] for f in audit_package(root)['findings']})

    def test_reviewer_material_and_credential_markers_are_flagged(self):
        root = package(self.root/'pack')
        (root/'answer_key.txt').write_text('-----BEGIN PRIVATE KEY-----')
        codes = {f['code'] for f in audit_package(root)['findings']}
        self.assertTrue({'reviewer_material_in_world', 'credential_marker'} <= codes)

    def test_future_evidence_is_a_structural_error(self):
        world = fixture()
        world['records'][0]['at'] = '2026-09-15T00:00:00Z'
        self.assertEqual('invalid_world', audit_world(world)[0]['code'])

    def test_similar_names_are_warnings_not_automatic_identity_merges(self):
        world = fixture()
        world['actors'][1]['name'] = 'Alice Bentom'
        findings = audit_world(world)
        self.assertEqual('warning', findings[0]['severity'])
        self.assertEqual('similar_actor_names', findings[0]['code'])

    def test_duplicate_record_bodies_are_review_warnings(self):
        world = fixture()
        twin = dict(world['records'][0], id='CONTACT-13')
        world['records'].append(twin)
        self.assertIn('duplicate_record_content', {f['code'] for f in audit_world(world)})

    def test_zip_traversal_and_duplicates_are_rejected(self):
        for name in ('../world.json', '/world.json', 'services\\a.json', './world.json'):
            p = self.root/'bad.zip'
            with zipfile.ZipFile(p, 'w') as archive: archive.writestr(name, '{}')
            with self.assertRaises(ScenarioError): load_members(p)
        with zipfile.ZipFile(self.root/'bad.zip', 'w') as archive:
            archive.writestr('world.json', '{}')
            archive.writestr('WORLD.json', '{}')
        with self.assertRaises(ScenarioError): load_members(self.root/'bad.zip')

    def test_high_compression_ratio_is_rejected(self):
        p = self.root/'bomb.zip'
        with zipfile.ZipFile(p, 'w', compression=zipfile.ZIP_DEFLATED) as archive: archive.writestr('world.json', '0' * 1000000)
        with self.assertRaisesRegex(ScenarioError, 'compression'): load_members(p)

    def test_symlinks_are_rejected(self):
        root = package(self.root/'pack')
        outside = self.root/'outside.txt'
        outside.write_text('private')
        (root/'link.txt').symlink_to(outside)
        with self.assertRaises(ScenarioError): audit_package(root)

    def test_citations_require_exact_source_and_substring(self):
        rows = resolve_citations(fixture(), fixture('citations.json'))
        self.assertTrue(all(r['valid'] for r in rows))
        rows = resolve_citations(fixture(), [{'source_id': 'UNKNOWN', 'quote': 'text'}, {'source_id': '4.5', 'quote': 'help desk posts'}])
        self.assertFalse(any(r['valid'] for r in rows))
        with self.assertRaises(ScenarioError): resolve_citations(fixture(), [{'source_id': '4.5', 'quote': ' '}])

    def test_good_trace_passes_all_observable_criteria(self):
        result = grade(fixture(), fixture('good-trace.json'), fixture('rubric.json'))
        self.assertEqual((True, '100.00', []), (result['passed'], result['percent'], result['required_failed']))
        self.assertEqual(['E3'], result['criteria'][4]['supporting_event_ids'])

    def test_bad_trace_fails_required_criteria(self):
        result = grade(fixture(), fixture('bad-trace.json'), fixture('rubric.json'))
        self.assertEqual((False, '28.57', ['C3', 'C4', 'C6']),
                         (result['passed'], result['percent'], result['required_failed']))

    def test_injected_acceptance_flags_cannot_change_grade(self):
        trace = fixture('bad-trace.json')
        for event in trace['events']: event['accepted'] = True
        self.assertFalse(grade(fixture(), trace, fixture('rubric.json'))['passed'])

    def test_required_failure_overrides_a_zero_threshold(self):
        rubric = fixture('rubric.json')
        rubric['pass_percent'] = 0
        self.assertFalse(grade(fixture(), fixture('bad-trace.json'), rubric)['passed'])

    def test_ordering_criterion_does_not_pass_vacuously(self):
        trace = fixture('good-trace.json')
        trace['events'] = trace['events'][:2]
        result = grade(fixture(), trace, fixture('rubric.json'))
        self.assertFalse(result['criteria'][2]['met'])

    def test_action_absent_catches_even_a_rejected_attempt(self):
        result = grade(fixture(), fixture('bad-trace.json'), fixture('rubric.json'))
        self.assertFalse(result['criteria'][-1]['met'])
        self.assertEqual(['E5'], result['criteria'][-1]['supporting_event_ids'])
        self.assertIn('1 attempt', result['criteria'][-1]['observation'])

    def test_actor_scoped_absence_does_not_forbid_authorized_helpdesk_work(self):
        trace = fixture('good-trace.json')
        trace['events'].append({'id': 'E4', 'action': 'assign', 'actor_id': 'HELPDESK', 'target_id': 'HELP-41',
                                'at': '2026-09-14T09:40:00+01:00', 'evidence_ids': []})
        criterion = fixture('rubric.json')['criteria'][-1]
        criterion['actor_id'] = 'OPS'
        self.assertTrue(grade(fixture(), trace, {'criteria': [criterion]})['passed'])

    def test_rejected_action_criterion_uses_recomputed_decisions(self):
        rubric = {'criteria': [{'id': 'R', 'kind': 'rejected_action', 'action': 'schedule', 'target_id': 'HELP-41', 'clause': '4.5'}]}
        result = grade(fixture(), fixture('bad-trace.json'), rubric)
        self.assertTrue(result['passed'])
        self.assertEqual(['E2', 'E4'], result['criteria'][0]['supporting_event_ids'])

    def test_unknown_and_unobservable_criteria_fail_validation(self):
        for field, value in (('kind', 'understood_policy'), ('clause', '99.9'), ('weight', True), ('action', 'imagined_action'), ('target_id', 'missing')):
            rubric = fixture('rubric.json')
            rubric['criteria'][0][field] = value
            with self.assertRaises(ScenarioError): validate_rubric(rubric, fixture())

    def test_duplicate_criteria_and_empty_rubrics_fail_validation(self):
        rubric = fixture('rubric.json')
        rubric['criteria'].append(rubric['criteria'][0])
        with self.assertRaises(ScenarioError): validate_rubric(rubric, fixture())
        with self.assertRaises(ScenarioError): validate_rubric({'criteria': []}, fixture())

    def test_cli_codes(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            world = str(ROOT/'examples/world.json')
            rubric = str(ROOT/'examples/rubric.json')
            self.assertEqual(0, main(['audit', world]))
            self.assertEqual(0, main(['grade', world, str(ROOT/'examples/good-trace.json'), rubric]))
            self.assertEqual(1, main(['grade', world, str(ROOT/'examples/bad-trace.json'), rubric]))
            self.assertEqual(0, main(['citations', world, str(ROOT/'examples/citations.json')]))
            self.assertEqual(2, main(['audit', str(self.root/'missing.json')]))

if __name__ == '__main__': unittest.main()
