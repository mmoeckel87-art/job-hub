import json
import os
from pathlib import Path
import tempfile
import unittest

class PublicExportTests(unittest.TestCase):
    def test_offline_workflow_and_default_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ['JOB_MONITOR_DATA_DIR'] = tmp
            os.environ['JOB_MONITOR_PROFILE'] = 'demo'
            os.environ['JOB_MONITOR_APPLY_ARMED'] = '0'
            from job_monitor import application, page, register
            register.save_profile(register.profile_template('Demo User'))
            self.assertFalse(register.profile_complete(register.load_profile()))
            self.assertFalse(register.load_profile()['application']['auto_send'])
            self.assertFalse(application.sender_status()['configured'])
            self.assertIn('Job Hub', page.render_page())
            self.assertEqual(register.state(), {})

    def test_general_contact_is_not_application_recipient(self):
        from job_monitor import contacts
        contact = {'email': 'info@example.invalid', 'kind': 'general',
                   'suitable_for_application': True, 'company_match': True}
        self.assertIsNone(contacts.best_contact({'contacts': [contact]}))

    def test_salary_upper_bound_does_not_satisfy_threshold(self):
        from job_monitor import salary
        result = salary.verdict({'fix_min': 70000, 'fix_max': 95000,
                                 'ote_min': 80000, 'ote_max': 110000},
                                {'compensation': {'fix_floor': 85000, 'tiers': {}}}, 100000)
        self.assertEqual(result['verdict'], 'overlap')

    def test_sender_has_no_external_connector_dependency(self):
        from unittest.mock import patch
        from job_monitor import application
        with patch.object(application, 'profile_smtp', return_value=None):
            with patch.dict(os.environ, {'MAIL_SMTP_HOST': 'smtp.example.invalid',
                                        'MAIL_SMTP_USER': 'demo@example.invalid',
                                        'MAIL_SMTP_PASSWORD': 'synthetic-test-value'}):
                self.assertEqual(application._smtp_config()['source'], 'environment')
                self.assertTrue(application.sender_status()['configured'])

    def test_rejection_survives_repost_and_can_be_undone(self):
        from unittest.mock import patch
        from job_monitor import register
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(register, 'DATA_DIR', tmp), patch.object(register, 'PROFILES_DIR', str(Path(tmp)/'profiles')):
                with register.profile_context('demo'):
                    posting = {'company': 'Example Ltd', 'title': 'Sales Lead', 'location': 'Example City',
                               'url': 'https://example.invalid/job/1', 'summary': 'Build a team.'}
                    jid = register.job_id(posting)
                    event = {'job_id': jid, 'at': '2026-01-01T12:00:00', 'posting': posting,
                             'evaluation': {'decision': 'NOTIFY', 'fit': 80, 'comp': {}}}
                    register._append('register.jsonl', {'event': 'upsert', **event})
                    register.set_rejected(jid, reason='aufgaben')
                    repost = {**posting, 'url': 'https://example.invalid/job/2'}
                    self.assertEqual(register.job_id(repost), jid)
                    register._append('register.jsonl', {'event': 'upsert', **event, 'posting': repost})
                    self.assertTrue(register.is_rejected(register.state()[jid]))
                    self.assertEqual(register.pending(), [])
                    register.set_rejected(jid, False)
                    self.assertFalse(register.is_rejected(register.state()[jid]))
                    self.assertEqual(len(register.pending()), 1)

    def test_research_retains_existing_summary(self):
        from job_monitor import register
        merged = register.merge_research({'company': 'Example Ltd'},
                    {'posting': {'summary': 'Original text.'}, 'summary': 'Enriched text.'}, {})
        self.assertEqual(merged['summary'], 'Enriched text.')

    def test_export_has_no_runtime_data_or_private_identifiers(self):
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / '.git').exists())
        self.assertFalse((root / 'job_monitor/data').exists())
        # Assemble deny-list tokens so the test itself contains no personal identifiers.
        forbidden = ['matt'+'hias', 'caro'+'lin', 'may'+'tze', 'moe'+'ckel',
                     'mö'+'ckel', 'tail'+'40af4c', '/'+'Users/', 'Family'+'OS']
        for p in root.rglob('*'):
            if not p.is_file() or '__pycache__' in p.parts: continue
            content = p.read_text().lower()
            for token in forbidden:
                self.assertNotIn(token.lower(), content, str(p))
            self.assertNotEqual(p.name, 'smtp.env')
        json.loads((root/'examples/profile.template.json').read_text())
        json.loads((root/'examples/posting.json').read_text())

if __name__ == '__main__': unittest.main()
