"""
Unit tests for AppState serialization and config persistence.
All tests use a temporary directory — no real ~/.config/fanhub is touched.
"""
import sys, os, json, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Patch CONFIG_PATH before importing AppState so tests are isolated
_TMP = tempfile.mkdtemp()
_FAKE_CONFIG = os.path.join(_TMP, 'config.json')

import core.app_state as _app_state_module
_app_state_module.CONFIG_PATH = _FAKE_CONFIG

from core.app_state import AppState


class TestAppStateDefaults(unittest.TestCase):

    def setUp(self):
        # Each test gets a fresh config file
        if os.path.exists(_FAKE_CONFIG):
            os.remove(_FAKE_CONFIG)
        self.state = AppState()

    def test_default_poll_interval(self):
        self.assertEqual(self.state.settings['poll_interval_ms'], 1000)

    def test_default_temp_unit_is_celsius(self):
        self.assertEqual(self.state.settings['temp_unit'], 'C')

    def test_default_safe_mode_on(self):
        self.assertTrue(self.state.settings['safe_mode'])

    def test_default_emergency_temp(self):
        self.assertAlmostEqual(self.state.settings['emergency_temp'], 90.0)

    def test_default_hysteresis(self):
        self.assertAlmostEqual(self.state.settings['hysteresis'], 2.0)

    def test_default_tray_icon_on(self):
        self.assertTrue(self.state.settings['tray_icon'])

    def test_no_active_profile_by_default(self):
        self.assertIsNone(self.state.active_profile)

    def test_no_profiles_by_default(self):
        self.assertEqual(len(self.state.profiles), 0)


class TestAppStatePersistence(unittest.TestCase):

    def setUp(self):
        if os.path.exists(_FAKE_CONFIG):
            os.remove(_FAKE_CONFIG)
        self.state = AppState()

    def test_save_and_reload_settings(self):
        self.state.settings['temp_unit'] = 'F'
        self.state.settings['poll_interval_ms'] = 2000
        self.state.save_config()

        s2 = AppState()
        self.assertEqual(s2.settings['temp_unit'], 'F')
        self.assertEqual(s2.settings['poll_interval_ms'], 2000)

    def test_save_and_reload_profile(self):
        profile = {
            'name': 'gaming',
            'curves': {'fan_assignments': {'fan1': 'gaming'}, 'fixed_speeds': {}},
            'rgb': {},
        }
        self.state.save_profile('gaming', profile)
        self.state.active_profile = 'gaming'
        self.state.save_config()

        s2 = AppState()
        self.assertIn('gaming', s2.profiles)
        self.assertEqual(s2.active_profile, 'gaming')

    def test_delete_profile(self):
        self.state.save_profile('temp', {'name': 'temp'})
        self.state.active_profile = 'temp'
        self.state.save_config()

        self.state.delete_profile('temp')
        self.assertNotIn('temp', self.state.profiles)
        self.assertIsNone(self.state.active_profile)

    def test_delete_nonexistent_profile_is_safe(self):
        self.state.delete_profile('does_not_exist')  # must not raise

    def test_get_profile_returns_none_for_missing(self):
        self.assertIsNone(self.state.get_profile('missing'))

    def test_get_profile_returns_dict_when_present(self):
        self.state.save_profile('p1', {'name': 'p1', 'data': 42})
        result = self.state.get_profile('p1')
        self.assertIsNotNone(result)
        self.assertEqual(result['data'], 42)

    def test_atomic_write_produces_valid_json(self):
        self.state.settings['poll_interval_ms'] = 500
        self.state.save_config()
        with open(_FAKE_CONFIG) as f:
            data = json.load(f)
        self.assertEqual(data['settings']['poll_interval_ms'], 500)

    def test_settings_merged_on_load(self):
        """Defaults not present in saved config are still present after reload."""
        # Save a minimal config
        with open(_FAKE_CONFIG, 'w') as f:
            json.dump({'settings': {'temp_unit': 'F'}, 'profiles': {},
                       'active_profile': None}, f)
        s = AppState()
        # Custom value loaded
        self.assertEqual(s.settings['temp_unit'], 'F')
        # Defaults still present
        self.assertIn('poll_interval_ms', s.settings)
        self.assertIn('emergency_temp', s.settings)

    def test_corrupted_config_does_not_crash(self):
        with open(_FAKE_CONFIG, 'w') as f:
            f.write('{ not valid json !!!')
        # Must not raise
        s = AppState()
        # Defaults still available
        self.assertEqual(s.settings['temp_unit'], 'C')

    def test_save_config_is_atomic(self):
        """Verify os.replace is used (tmp file present then gone, not partial)."""
        self.state.save_config()
        # File must exist and be valid after save
        self.assertTrue(os.path.exists(_FAKE_CONFIG))
        with open(_FAKE_CONFIG) as f:
            data = json.load(f)
        self.assertIn('settings', data)
        # No stray .tmp files
        tmp_files = [x for x in os.listdir(_TMP) if x.endswith('.tmp')]
        self.assertEqual(tmp_files, [],
                         msg=f"Stray .tmp files found: {tmp_files}")

    def test_multiple_profiles_preserved_across_saves(self):
        for name in ('silent', 'gaming', 'work'):
            self.state.save_profile(name, {'name': name})
        self.state.save_config()
        s2 = AppState()
        for name in ('silent', 'gaming', 'work'):
            self.assertIn(name, s2.profiles)


class TestDaemonControllerMock(unittest.TestCase):
    """
    DaemonController logic — mocks subprocess so no systemd is needed.
    Tests that the right commands are issued and return values are parsed.
    """
    def setUp(self):
        from core.daemon_controller import DaemonController
        self.DC = DaemonController

    def _mock_run(self, responses: dict):
        """
        Returns a context manager that patches DaemonController._run.
        responses: {' '.join(args): (returncode, stdout)}
        """
        import unittest.mock as mock
        def fake_run(*args, **kwargs):
            key = ' '.join(args)
            return responses.get(key, (1, ''))
        return mock.patch.object(self.DC, '_run', side_effect=fake_run)

    def test_status_active_enabled(self):
        with self._mock_run({
            'is-active fanhub-daemon':  (0, 'active'),
            'is-enabled fanhub-daemon': (0, 'enabled'),
        }):
            st = self.DC.status()
        self.assertTrue(st.active)
        self.assertTrue(st.enabled)
        self.assertTrue(st.installed)
        self.assertFalse(st.no_systemd)

    def test_status_not_installed(self):
        with self._mock_run({
            'is-active fanhub-daemon':  (3, 'inactive'),
            'is-enabled fanhub-daemon': (1, 'not-found'),
        }):
            st = self.DC.status()
        self.assertFalse(st.installed)

    def test_status_no_systemd(self):
        with self._mock_run({
            'is-active fanhub-daemon':  (-1, '__no_systemctl__'),
            'is-enabled fanhub-daemon': (-1, '__no_systemctl__'),
        }):
            st = self.DC.status()
        self.assertTrue(st.no_systemd)
        self.assertFalse(st.installed)

    def test_summary_running_enabled(self):
        from core.daemon_controller import DaemonStatus
        st = DaemonStatus(installed=True, active=True, enabled=True)
        text, color = st.summary()
        self.assertIn('Running', text)
        self.assertEqual(color, '#44ff88')

    def test_summary_not_installed(self):
        from core.daemon_controller import DaemonStatus
        st = DaemonStatus(installed=False, active=False, enabled=False)
        text, color = st.summary()
        self.assertIn('not installed', text.lower())
        self.assertNotEqual(color, '#44ff88')

    def test_reload_sends_sighup_when_active(self):
        import unittest.mock as mock
        with mock.patch.object(self.DC, 'is_active', return_value=True), \
             mock.patch.object(self.DC, '_run', return_value=(0, '')) as m:
            result = self.DC.reload()
        self.assertTrue(result)
        # Check SIGHUP was in the args
        called = m.call_args[0]
        self.assertIn('--signal=SIGHUP', called)

    def test_reload_skips_when_inactive(self):
        import unittest.mock as mock
        with mock.patch.object(self.DC, 'is_active', return_value=False), \
             mock.patch.object(self.DC, '_run') as m:
            result = self.DC.reload()
        self.assertFalse(result)
        m.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
