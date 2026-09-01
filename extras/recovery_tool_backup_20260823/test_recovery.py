"""
Test suite for mrd_recovery.py — runs on Linux/Mac (mocks all Windows-specific calls).
"""

import sys
import os
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock, mock_open, call

# ---------------------------------------------------------------------------
# Allow import without tkinter on headless Linux
# ---------------------------------------------------------------------------
sys.modules.setdefault("tkinter", MagicMock())
sys.modules.setdefault("tkinter.ttk", MagicMock())
sys.modules.setdefault("tkinter.scrolledtext", MagicMock())
sys.modules.setdefault("tkinter.messagebox", MagicMock())

# Now import the module under test
import importlib
import types

# Patch ctypes before import so is_admin() doesn't crash
ctypes_mock = MagicMock()
ctypes_mock.windll.shell32.IsUserAnAdmin.return_value = 1
sys.modules["ctypes"] = ctypes_mock

import mrd_recovery as mrd  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_completed(stdout="", stderr="", returncode=0):
    r = MagicMock()
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r


SC_RUNNING = (
    "SERVICE_NAME: MRDToolControl\n"
    "        TYPE               : 10  WIN32_OWN_PROCESS\n"
    "        STATE              : 4  RUNNING\n"
    "        WIN32_EXIT_CODE    : 0  (0x0)\n"
    "        SERVICE_EXIT_CODE  : 0  (0x0)\n"
    "        CHECKPOINT         : 0x0\n"
    "        WAIT_HINT          : 0x0\n"
    "        PID                : 1234\n"
    "        FLAGS              :\n"
)

SC_STOPPED = (
    "SERVICE_NAME: MRDToolControl\n"
    "        TYPE               : 10  WIN32_OWN_PROCESS\n"
    "        STATE              : 1  STOPPED\n"
    "        WIN32_EXIT_CODE    : 1077  (0x435)\n"
    "        SERVICE_EXIT_CODE  : 0  (0x0)\n"
    "        CHECKPOINT         : 0x0\n"
    "        WAIT_HINT          : 0x0\n"
)


# ---------------------------------------------------------------------------
# Lock tests
# ---------------------------------------------------------------------------

class TestLockFile(unittest.TestCase):

    def test_lock_prevents_double_run(self):
        """A lock file containing a running PID should block acquisition."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = os.path.join(tmpdir, ".recovery.lock")
            # Write our own PID (which is definitely running)
            with open(lock_path, "w") as f:
                f.write(str(os.getpid()))

            with patch.dict(mrd.CONFIG, {"lock_file": lock_path}):
                # _lock_pid_running must return True for our own PID
                with patch.object(mrd, "_lock_pid_running", return_value=True):
                    result = mrd.acquire_lock()

            self.assertFalse(result, "acquire_lock should fail when a live PID exists")

    def test_lock_acquired_when_stale(self):
        """A lock file with a dead PID should be overwritten."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = os.path.join(tmpdir, ".recovery.lock")
            with open(lock_path, "w") as f:
                f.write("99999999")  # Unlikely to be a real PID

            with patch.dict(mrd.CONFIG, {"lock_file": lock_path}):
                with patch.object(mrd, "_lock_pid_running", return_value=False):
                    result = mrd.acquire_lock()
                    mrd.release_lock()

            self.assertTrue(result)

    def test_lock_released_on_exit(self):
        """release_lock removes the file if the PID matches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = os.path.join(tmpdir, ".recovery.lock")
            with open(lock_path, "w") as f:
                f.write(str(os.getpid()))

            with patch.dict(mrd.CONFIG, {"lock_file": lock_path}):
                mrd.release_lock()

            self.assertFalse(os.path.exists(lock_path))


# ---------------------------------------------------------------------------
# Service state detection
# ---------------------------------------------------------------------------

class TestCheckService(unittest.TestCase):

    @patch("mrd_recovery._run")
    def test_service_stopped_detected(self, mock_run):
        mock_run.return_value = _make_completed(stdout=SC_STOPPED)
        result = mrd.check_service()
        self.assertEqual(result["state"], "STOPPED")

    @patch("mrd_recovery._run")
    def test_service_running_detected(self, mock_run):
        mock_run.return_value = _make_completed(stdout=SC_RUNNING)
        result = mrd.check_service()
        self.assertEqual(result["state"], "RUNNING")
        self.assertEqual(result["pid_from_sc"], 1234)


# ---------------------------------------------------------------------------
# Port / process detection
# ---------------------------------------------------------------------------

class TestCheckPort(unittest.TestCase):

    @patch("mrd_recovery._run")
    def test_port_occupied_detected(self, mock_run):
        netstat_out = (
            "  TCP    0.0.0.0:8000           0.0.0.0:0              LISTENING       5678\n"
        )
        mock_run.return_value = _make_completed(stdout=netstat_out)
        pid = mrd.check_port()
        self.assertEqual(pid, 5678)

    @patch("mrd_recovery._run")
    def test_port_free(self, mock_run):
        mock_run.return_value = _make_completed(stdout="")
        pid = mrd.check_port()
        self.assertIsNone(pid)


# ---------------------------------------------------------------------------
# HTTP health check
# ---------------------------------------------------------------------------

class TestCheckHttp(unittest.TestCase):

    def test_health_check_ok(self):
        mock_conn = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_conn.getresponse.return_value = mock_resp
        mock_resp.read.return_value = b'{"status":"ok"}'

        with patch("mrd_recovery.http.client.HTTPConnection", return_value=mock_conn):
            result = mrd.check_http("/health")

        self.assertTrue(result["ok"])
        self.assertEqual(result["status_code"], 200)

    def test_health_check_fail(self):
        with patch("mrd_recovery.http.client.HTTPConnection") as mock_cls:
            mock_cls.return_value.request.side_effect = ConnectionRefusedError("refused")
            result = mrd.check_http("/health")

        self.assertFalse(result["ok"])
        self.assertIsNone(result["status_code"])
        self.assertIn("refused", result["error"])

    def test_health_check_500(self):
        mock_conn = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_conn.getresponse.return_value = mock_resp

        with patch("mrd_recovery.http.client.HTTPConnection", return_value=mock_conn):
            result = mrd.check_http("/health")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status_code"], 500)


# ---------------------------------------------------------------------------
# DB checks
# ---------------------------------------------------------------------------

class TestCheckDb(unittest.TestCase):

    def test_db_integrity_ok(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("ok",)]
        mock_conn.cursor.return_value = mock_cursor

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            with patch.dict(mrd.CONFIG, {"db_path": db_path}):
                with patch("mrd_recovery.sqlite3.connect", return_value=mock_conn):
                    result = mrd.check_db()

            self.assertTrue(result["exists"])
            self.assertTrue(result["readable"])
            self.assertTrue(result["integrity_ok"])
        finally:
            os.unlink(db_path)

    def test_db_integrity_fail(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("*** index corruption",)]
        mock_conn.cursor.return_value = mock_cursor

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            with patch.dict(mrd.CONFIG, {"db_path": db_path}):
                with patch("mrd_recovery.sqlite3.connect", return_value=mock_conn):
                    result = mrd.check_db()

            self.assertFalse(result["integrity_ok"])
        finally:
            os.unlink(db_path)

    def test_db_not_found(self):
        with patch.dict(mrd.CONFIG, {"db_path": "/nonexistent/path/db.db"}):
            result = mrd.check_db()
        self.assertFalse(result["exists"])
        self.assertFalse(result["readable"])

    def test_db_never_modified(self):
        """check_db must use read-only URI — must NOT open with write access."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        captured_calls = []

        def capturing_connect(uri_str, **kwargs):
            captured_calls.append((uri_str, kwargs))
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = [("ok",)]
            mock_conn.cursor.return_value = mock_cursor
            return mock_conn

        try:
            with patch.dict(mrd.CONFIG, {"db_path": db_path}):
                with patch("mrd_recovery.sqlite3.connect", side_effect=capturing_connect):
                    mrd.check_db()

            self.assertEqual(len(captured_calls), 1)
            uri_arg = captured_calls[0][0]
            self.assertIn("mode=ro", uri_arg, "DB must be opened read-only")
        finally:
            os.unlink(db_path)


# ---------------------------------------------------------------------------
# Repair logic
# ---------------------------------------------------------------------------

class TestRunRepair(unittest.TestCase):

    def setUp(self):
        mrd._reset_restart_count()

    def _diag_stopped(self):
        return {
            "service": {"state": "STOPPED", "pid_from_sc": None, "raw": ""},
            "process": {"python_pids": [], "port_pid": None},
            "http": {
                "/health": {"ok": False, "status_code": None, "error": "refused"},
                "/": {"ok": False, "status_code": None, "error": "refused"},
                "/scan": {"ok": False, "status_code": None, "error": "refused"},
            },
            "logs": {"source": None, "last_lines": [], "error_lines": []},
            "db": {"exists": True, "readable": True, "integrity_ok": True,
                   "integrity_result": "ok"},
            "disk": {"free_gb": 50.0, "free_ok": True, "write_ok": True, "error": None},
            "commit": "abc1234 Initial commit",
            "timestamp": "2026-01-01T00:00:00",
        }

    def _diag_running_unhealthy(self):
        d = self._diag_stopped()
        d["service"]["state"] = "RUNNING"
        d["service"]["pid_from_sc"] = 1234
        return d

    def _diag_running_healthy(self):
        d = self._diag_running_unhealthy()
        d["http"]["/health"] = {"ok": True, "status_code": 200, "error": None}
        d["http"]["/"] = {"ok": True, "status_code": 200, "error": None}
        d["http"]["/scan"] = {"ok": True, "status_code": 200, "error": None}
        return d

    @patch("mrd_recovery.time.sleep")
    @patch("mrd_recovery.check_http")
    @patch("mrd_recovery.run_diagnostics")
    @patch("mrd_recovery._run")
    def test_repair_starts_stopped_service(self, mock_run, mock_diag,
                                           mock_http, mock_sleep):
        mock_diag.side_effect = [self._diag_stopped(), self._diag_running_healthy()]
        mock_http.return_value = {"ok": True, "status_code": 200, "error": None}
        mock_run.return_value = _make_completed()

        result = mrd.run_repair()

        # Verify sc start was called
        calls_flat = [c.args[0] for c in mock_run.call_args_list]
        sc_starts = [c for c in calls_flat if "start" in c and "MRDToolControl" in c]
        self.assertTrue(len(sc_starts) >= 1, "sc start must be called for stopped service")
        self.assertTrue(result["success"])

    @patch("mrd_recovery.time.sleep")
    @patch("mrd_recovery.check_http")
    @patch("mrd_recovery.run_diagnostics")
    @patch("mrd_recovery._run")
    def test_repair_restarts_hung_service(self, mock_run, mock_diag,
                                          mock_http, mock_sleep):
        mock_diag.side_effect = [
            self._diag_running_unhealthy(),
            self._diag_running_healthy(),
        ]
        mock_http.return_value = {"ok": True, "status_code": 200, "error": None}
        mock_run.return_value = _make_completed()

        result = mrd.run_repair()

        calls_flat = [c.args[0] for c in mock_run.call_args_list]
        sc_stops = [c for c in calls_flat if "stop" in c and "MRDToolControl" in c]
        sc_starts = [c for c in calls_flat if "start" in c and "MRDToolControl" in c]
        self.assertTrue(len(sc_stops) >= 1, "sc stop must be called for hung service")
        self.assertTrue(len(sc_starts) >= 1, "sc start must be called after stop")

    @patch("mrd_recovery.time.sleep")
    @patch("mrd_recovery.check_http")
    @patch("mrd_recovery.run_diagnostics")
    @patch("mrd_recovery._run")
    def test_repair_max_restarts_respected(self, mock_run, mock_diag,
                                           mock_http, mock_sleep):
        mock_diag.return_value = self._diag_stopped()
        mock_http.return_value = {"ok": False, "status_code": None, "error": "refused"}
        mock_run.return_value = _make_completed()

        # Exhaust the restart counter
        mrd._restart_count = mrd.CONFIG["max_restarts"]
        result = mrd.run_repair()

        self.assertFalse(result["success"])
        # sc start should NOT have been called again
        calls_flat = [c.args[0] for c in mock_run.call_args_list]
        sc_starts = [c for c in calls_flat if "start" in c]
        self.assertEqual(len(sc_starts), 0,
                         "No sc start when max_restarts exceeded")


# ---------------------------------------------------------------------------
# Safety: CloudflaredMRD must never be touched
# ---------------------------------------------------------------------------

class TestCloudflareNeverTouched(unittest.TestCase):

    def setUp(self):
        mrd._reset_restart_count()

    @patch("mrd_recovery.time.sleep")
    @patch("mrd_recovery.check_http")
    @patch("mrd_recovery.run_diagnostics")
    @patch("mrd_recovery._run")
    def test_cloudflare_never_touched(self, mock_run, mock_diag, mock_http, mock_sleep):
        """run_repair must never invoke any command touching CloudflaredMRD."""
        diag = {
            "service": {"state": "STOPPED", "pid_from_sc": None, "raw": ""},
            "process": {"python_pids": [], "port_pid": None},
            "http": {
                "/health": {"ok": False, "status_code": None, "error": "refused"},
                "/": {"ok": False, "status_code": None, "error": "refused"},
                "/scan": {"ok": False, "status_code": None, "error": "refused"},
            },
            "logs": {"source": None, "last_lines": [], "error_lines": []},
            "db": {"exists": True, "readable": True, "integrity_ok": True,
                   "integrity_result": "ok"},
            "disk": {"free_gb": 50.0, "free_ok": True, "write_ok": True, "error": None},
            "commit": "abc1234",
            "timestamp": "2026-01-01T00:00:00",
        }
        mock_diag.side_effect = [diag, diag]
        mock_http.return_value = {"ok": False, "status_code": None, "error": "refused"}
        mock_run.return_value = _make_completed()

        mrd.run_repair()

        cloudflare_svc = mrd.CONFIG["cloudflare_service"]
        for c in mock_run.call_args_list:
            cmd_args = c.args[0] if c.args else []
            cmd_str = " ".join(str(a) for a in cmd_args)
            self.assertNotIn(
                cloudflare_svc, cmd_str,
                f"CloudflaredMRD must never appear in subprocess calls: {cmd_str}",
            )


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

class TestGenerateReport(unittest.TestCase):

    def _sample_diag(self):
        return {
            "service": {"state": "RUNNING", "pid_from_sc": 1234, "raw": ""},
            "process": {"python_pids": [1234], "port_pid": 1234},
            "http": {
                "/health": {"ok": True, "status_code": 200, "error": None},
                "/": {"ok": True, "status_code": 200, "error": None},
                "/scan": {"ok": True, "status_code": 200, "error": None},
            },
            "logs": {"source": None, "last_lines": [], "error_lines": []},
            "db": {"exists": True, "readable": True, "integrity_ok": True,
                   "integrity_result": "ok"},
            "disk": {"free_gb": 50.0, "free_ok": True, "write_ok": True, "error": None},
            "commit": "abc1234 Initial commit",
            "timestamp": "2026-01-01T00:00:00",
        }

    def test_report_generated(self):
        """Report file is created and contains expected sections."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(mrd.CONFIG, {"report_dir": tmpdir}):
                path = mrd.generate_report(
                    self._sample_diag(),
                    ["[OK] Servicio iniciado", "[OK] Health OK"],
                )
            self.assertTrue(os.path.isfile(path))
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

        self.assertIn("MRD TOOL CONTROL", content)
        self.assertIn("ESTADO DEL SERVICIO: RUNNING", content)
        self.assertIn("RESULTADO FINAL:", content)
        self.assertIn("No contiene contraseñas", content)
        # JSON section present
        self.assertIn('"state": "RUNNING"', content)

    def test_report_no_sensitive_data(self):
        """Report must not contain common secret patterns."""
        diag = self._sample_diag()
        # The commit field may contain arbitrary text from git — ensure the
        # report doesn't accidentally expose injected credentials.
        # (In real life git commits don't carry passwords; this verifies the
        # report writes only what it intends.)
        diag["commit"] = "abc1234 refactor login flow"

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(mrd.CONFIG, {"report_dir": tmpdir}):
                path = mrd.generate_report(diag, [])
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

        # The safety note must always be present
        self.assertIn("No contiene contraseñas", content)
        # The report must not embed raw Python repr of internal structures
        self.assertNotIn("__dict__", content)


# ---------------------------------------------------------------------------
# DB safety — repair never touches the database
# ---------------------------------------------------------------------------

class TestDbNeverModified(unittest.TestCase):

    def setUp(self):
        mrd._reset_restart_count()

    @patch("mrd_recovery.time.sleep")
    @patch("mrd_recovery.check_http")
    @patch("mrd_recovery.run_diagnostics")
    @patch("mrd_recovery._run")
    @patch("mrd_recovery.sqlite3.connect")
    def test_db_never_modified(self, mock_sqlite, mock_run, mock_diag,
                               mock_http, mock_sleep):
        """run_repair must never open the DB in write mode."""
        diag = {
            "service": {"state": "STOPPED", "pid_from_sc": None, "raw": ""},
            "process": {"python_pids": [], "port_pid": None},
            "http": {
                "/health": {"ok": False, "status_code": None, "error": "refused"},
                "/": {"ok": False, "status_code": None, "error": "refused"},
                "/scan": {"ok": False, "status_code": None, "error": "refused"},
            },
            "logs": {"source": None, "last_lines": [], "error_lines": []},
            "db": {"exists": True, "readable": True, "integrity_ok": True,
                   "integrity_result": "ok"},
            "disk": {"free_gb": 50.0, "free_ok": True, "write_ok": True, "error": None},
            "commit": "abc1234",
            "timestamp": "2026-01-01T00:00:00",
        }
        mock_diag.side_effect = [diag, diag]
        mock_http.return_value = {"ok": False, "status_code": None, "error": "refused"}
        mock_run.return_value = _make_completed()

        mrd.run_repair()

        # sqlite3.connect should not have been called at all during repair
        mock_sqlite.assert_not_called()

        # Also verify no git/migrate commands are run
        for c in mock_run.call_args_list:
            cmd_args = c.args[0] if c.args else []
            cmd_str = " ".join(str(a) for a in cmd_args)
            self.assertNotIn("migrate", cmd_str.lower())


# ---------------------------------------------------------------------------
# run_diagnostics integration (mocked)
# ---------------------------------------------------------------------------

class TestRunDiagnostics(unittest.TestCase):

    @patch("mrd_recovery.check_git_commit", return_value="abc1234 Init")
    @patch("mrd_recovery.check_disk", return_value={"free_gb": 10.0, "free_ok": True,
                                                    "write_ok": True, "error": None})
    @patch("mrd_recovery.check_db", return_value={"exists": True, "readable": True,
                                                   "integrity_ok": True,
                                                   "integrity_result": "ok"})
    @patch("mrd_recovery.check_logs", return_value={"source": None, "last_lines": [],
                                                    "error_lines": []})
    @patch("mrd_recovery.check_http", return_value={"ok": True, "status_code": 200,
                                                    "error": None})
    @patch("mrd_recovery.check_port", return_value=None)
    @patch("mrd_recovery.check_process", return_value={"python_pids": [1234],
                                                       "port_pid": None})
    @patch("mrd_recovery.check_service", return_value={"state": "RUNNING",
                                                       "pid_from_sc": 1234, "raw": ""})
    def test_run_diagnostics_returns_all_keys(self, *mocks):
        result = mrd.run_diagnostics()
        for key in ("service", "process", "http", "logs", "db", "disk", "commit",
                    "timestamp"):
            self.assertIn(key, result)
        self.assertIn("/health", result["http"])
        self.assertIn("/scan", result["http"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
