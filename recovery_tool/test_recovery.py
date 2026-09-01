"""
Test suite for mrd_recovery.py — runs on Linux/Mac (mocks all Windows-specific calls).
"""

import sys
import os
import json
import time
import tempfile
import unittest
import re
import shutil
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

    @patch("mrd_recovery._run")
    def test_service_running_detected_on_spanish_windows(self, mock_run):
        mock_run.return_value = _make_completed(stdout=(
            "NOMBRE_SERVICIO: MRDToolControl\n"
            "        ESTADO             : 4  RUNNING\n"
            "        PID                : 4321\n"
        ))
        result = mrd.check_service()
        self.assertEqual(result["state"], "RUNNING")
        self.assertEqual(result["pid_from_sc"], 4321)


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
        pid = mrd.check_port(8000)
        self.assertEqual(pid, 5678)

    @patch("mrd_recovery._run")
    def test_port_free(self, mock_run):
        mock_run.return_value = _make_completed(stdout="")
        pid = mrd.check_port(8000)
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
            result = mrd.check_http("localhost", 8000, "/health")

        self.assertTrue(result["ok"])
        self.assertEqual(result["status_code"], 200)

    def test_health_check_fail(self):
        with patch("mrd_recovery.http.client.HTTPConnection") as mock_cls:
            mock_cls.return_value.request.side_effect = ConnectionRefusedError("refused")
            result = mrd.check_http("localhost", 8000, "/health")

        self.assertFalse(result["ok"])
        self.assertIsNone(result["status_code"])
        self.assertIn("refused", result["error"])

    def test_health_check_500(self):
        mock_conn = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_resp.read.return_value = b""
        mock_conn.getresponse.return_value = mock_resp

        with patch("mrd_recovery.http.client.HTTPConnection", return_value=mock_conn):
            result = mrd.check_http("localhost", 8000, "/health")

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
                "/health": {"ok": False, "status_code": None, "error": "refused",
                            "content_ok": False},
                "/": {"ok": False, "status_code": None, "error": "refused",
                      "content_ok": False},
                "/scan": {"ok": False, "status_code": None, "error": "refused",
                          "content_ok": False},
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
        d["http"]["/health"] = {"ok": True, "status_code": 200, "error": None,
                                "content_ok": True}
        d["http"]["/"] = {"ok": True, "status_code": 200, "error": None,
                          "content_ok": True}
        d["http"]["/scan"] = {"ok": True, "status_code": 200, "error": None,
                              "content_ok": True}
        return d

    @patch("mrd_recovery.time.sleep")
    @patch("mrd_recovery.check_http")
    @patch("mrd_recovery.run_diagnostics")
    @patch("mrd_recovery._run")
    def test_repair_starts_stopped_service(self, mock_run, mock_diag,
                                           mock_http, mock_sleep):
        mock_diag.side_effect = [self._diag_stopped(), self._diag_running_healthy()]
        mock_http.return_value = {"ok": True, "status_code": 200, "error": None,
                                  "content_ok": True}
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
        mock_http.return_value = {"ok": True, "status_code": 200, "error": None,
                                  "content_ok": True}
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
        mock_http.return_value = {"ok": False, "status_code": None, "error": "refused",
                                  "content_ok": False}
        mock_run.return_value = _make_completed()

        # Exhaust the restart counter via the persisted count mechanism
        with patch("mrd_recovery._get_restart_count",
                   return_value=mrd.CONFIG["max_restarts"]):
            result = mrd.run_repair()

        self.assertFalse(result["success"])
        # sc start should NOT have been called again
        calls_flat = [c.args[0] for c in mock_run.call_args_list]
        sc_starts = [c for c in calls_flat if "start" in c]
        self.assertEqual(len(sc_starts), 0,
                         "No sc start when max_restarts exceeded")


# ---------------------------------------------------------------------------
# Safety: a running tunnel is never restarted during repair
# ---------------------------------------------------------------------------

class TestCloudflareSafeRecovery(unittest.TestCase):

    def setUp(self):
        mrd._reset_restart_count()

    @patch("mrd_recovery.check_tunnels")
    @patch("mrd_recovery.time.sleep")
    @patch("mrd_recovery.check_http")
    @patch("mrd_recovery.run_diagnostics")
    @patch("mrd_recovery._run")
    def test_running_cloudflare_is_not_restarted(self, mock_run, mock_diag, mock_http,
                                                  mock_sleep, mock_tunnels):
        """run_repair may verify a tunnel, but never stop/restart one that is running."""
        diag = {
            "service": {"state": "STOPPED", "pid_from_sc": None, "raw": ""},
            "process": {"python_pids": [], "port_pid": None},
            "http": {
                "/health": {"ok": False, "status_code": None, "error": "refused",
                            "content_ok": False},
                "/": {"ok": False, "status_code": None, "error": "refused",
                      "content_ok": False},
                "/scan": {"ok": False, "status_code": None, "error": "refused",
                          "content_ok": False},
            },
            "logs": {"source": None, "last_lines": [], "error_lines": []},
            "db": {"exists": True, "readable": True, "integrity_ok": True,
                   "integrity_result": "ok"},
            "disk": {"free_gb": 50.0, "free_ok": True, "write_ok": True, "error": None},
            "commit": "abc1234",
            "timestamp": "2026-01-01T00:00:00",
        }
        mock_diag.side_effect = [diag, diag]
        mock_http.return_value = {"ok": False, "status_code": None, "error": "refused",
                                  "content_ok": False}
        mock_run.return_value = _make_completed()
        mock_tunnels.return_value = [
            {"name": "cloudflared", "exists": True, "state": "RUNNING", "raw": ""}
        ]

        mrd.run_repair()

        for c in mock_run.call_args_list:
            cmd_args = c.args[0] if c.args else []
            cmd = [str(a).lower() for a in cmd_args]
            self.assertFalse(
                "cloudflared" in cmd and any(action in cmd for action in ("stop", "restart")),
                f"A running tunnel must not be stopped/restarted: {cmd_args}",
            )


class TestManualPowerControls(unittest.TestCase):

    @patch("mrd_recovery.check_tunnels", return_value=[
        {"name": "cloudflared", "exists": True, "state": "RUNNING", "raw": ""}
    ])
    @patch("mrd_recovery.check_service", return_value={"state": "STOPPED"})
    @patch("mrd_recovery.sc_stop", return_value=(True, "OK"))
    def test_power_off_pauses_watchdog_and_never_stops_tunnel(
            self, mock_stop, _mock_service, _mock_tunnels):
        with tempfile.TemporaryDirectory() as tmpdir:
            marker = os.path.join(tmpdir, ".maintenance_mode")
            with patch.dict(mrd.CONFIG, {"maintenance_marker": marker}):
                result = mrd.power_off()
            self.assertTrue(result["success"])
            self.assertTrue(os.path.isfile(marker))
            mock_stop.assert_called_once_with(mrd.CONFIG["service_name"])

    @patch("mrd_recovery.run_diagnostics", return_value={"service": {"state": "RUNNING"}})
    @patch("mrd_recovery.check_http", return_value={
        "ok": True, "content_ok": True, "status_code": 200, "error": None
    })
    @patch("mrd_recovery.check_service", return_value={"state": "STOPPED"})
    @patch("mrd_recovery._start_known_tunnels", return_value=[])
    @patch("mrd_recovery.sc_start", return_value=(True, "OK"))
    def test_power_on_removes_manual_shutdown_marker(
            self, mock_start, _mock_tunnels, _mock_service, _mock_http, _mock_diag):
        with tempfile.TemporaryDirectory() as tmpdir:
            marker = os.path.join(tmpdir, ".maintenance_mode")
            with open(marker, "w", encoding="utf-8") as fh:
                fh.write("off")
            with patch.dict(mrd.CONFIG, {"maintenance_marker": marker}):
                result = mrd.power_on()
            self.assertTrue(result["success"])
            self.assertFalse(os.path.exists(marker))
            mock_start.assert_called_once_with(mrd.CONFIG["service_name"])


class TestMobileControl(unittest.TestCase):

    def test_mobile_identity_persists_encrypted_between_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            identity = os.path.join(tmpdir, "identity.dat")
            with patch.dict(mrd.CONFIG, {"mobile_identity_file": identity}), \
                 patch.object(mrd, "_dpapi_transform", side_effect=lambda data, _protect: data):
                first = mrd.load_or_create_mobile_token()
                second = mrd.load_or_create_mobile_token()
            self.assertEqual(first, second)
            with open(identity, "rb") as fh:
                self.assertNotIn(first.encode("ascii"), fh.read())

    @patch("mrd_recovery.run_diagnostics", return_value={
        "service": {"state": "RUNNING"},
        "http": {"/health": {"status_code": 200, "content_ok": True}},
        "public": {"ok": True, "content_ok": True},
        "db": {"integrity_ok": True},
        "capacity": {"database_mb": 1.2, "memory": {"used_percent": 40}},
        "disk": {"used_percent": 20},
        "ollama": {"ok": True, "mode": "rescue"},
    })
    @patch("mrd_recovery.check_http", return_value={
        "ok": True, "content_ok": True, "status_code": 200, "error": None
    })
    @patch("mrd_recovery.check_service", return_value={"state": "RUNNING"})
    def test_mobile_panel_enrolls_device_and_supports_pwa(
            self, _mock_service, _mock_health, _mock_diag):
        app = MagicMock()
        app._busy = False
        with patch.dict(mrd.CONFIG, {"mobile_port": 0}), \
             patch.object(mrd, "load_or_create_mobile_token", return_value="t" * 43):
            server = mrd.MobileControlServer(app)
            ok, _url = server.start()
            self.assertTrue(ok)
            try:
                conn = mrd.http.client.HTTPConnection("127.0.0.1", server.port, timeout=3)
                conn.request("GET", "/")
                response = conn.getresponse()
                body = response.read().decode("utf-8")
                self.assertEqual(response.status, 200)
                self.assertIn("manifest.webmanifest", body)
                self.assertIn("INSTALAR MRD RESCUE", body)
                script = re.search(r"(?s)<script>(.*?)</script>", body).group(1)
                self.assertIn("join('\\n')", script)
                node = shutil.which("node")
                if node:
                    js_path = os.path.join(tempfile.gettempdir(), "mrd_mobile_syntax.js")
                    with open(js_path, "w", encoding="utf-8") as output:
                        output.write(script)
                    checked = mrd.subprocess.run(
                        [node, "--check", js_path], capture_output=True, text=True
                    )
                    self.assertEqual(checked.returncode, 0, checked.stderr)
                conn.close()

                conn = mrd.http.client.HTTPConnection("127.0.0.1", server.port, timeout=3)
                conn.request("GET", "/status")
                self.assertEqual(conn.getresponse().status, 403)
                conn.close()

                conn = mrd.http.client.HTTPConnection("127.0.0.1", server.port, timeout=3)
                conn.request("POST", "/enroll", headers={
                    "X-MRD-Rescue-Token": server.token,
                    "Origin": "https://rescue.iasmrd.com",
                })
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                cookie = response.getheader("Set-Cookie").split(";", 1)[0]
                response.read()
                conn.close()

                conn = mrd.http.client.HTTPConnection("127.0.0.1", server.port, timeout=3)
                conn.request("GET", "/status", headers={"Cookie": cookie})
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertTrue(json.loads(response.read().decode("utf-8"))["active"])
                conn.close()
            finally:
                server.stop()


class TestOllamaSafeRepair(unittest.TestCase):

    @staticmethod
    def _diag(integrity_ok=True):
        return {
            "service": {"state": "RUNNING"}, "tunnels": [],
            "http": {"/health": {"ok": True, "content_ok": True}},
            "db": {"exists": True, "readable": True,
                   "integrity_ok": integrity_ok,
                   "integrity_result": "ok" if integrity_ok else "corrupt"},
            "disk": {}, "capacity": {},
            "logs": {"error_lines": []},
        }

    @patch("mrd_recovery._run")
    @patch("mrd_recovery.run_repair")
    @patch("mrd_recovery.ask_ollama", return_value={
        "ok": True, "text": "Ejecuta: comando-malicioso", "model": "test", "error": None
    })
    @patch("mrd_recovery.run_diagnostics")
    def test_model_text_is_never_executed(self, mock_diag, _mock_ai,
                                          mock_repair, mock_run):
        diag = self._diag(True)
        mock_diag.return_value = diag
        mock_repair.return_value = {"success": True, "actions": [], "final_diag": diag}
        result = mrd.run_ai_repair()
        self.assertTrue(result["success"])
        mock_run.assert_not_called()

    @patch("mrd_recovery.run_repair")
    @patch("mrd_recovery.ask_ollama", return_value={
        "ok": True, "text": "Base dañada", "model": "test", "error": None
    })
    @patch("mrd_recovery.run_diagnostics")
    def test_corrupt_database_blocks_automatic_repair(self, mock_diag, _mock_ai,
                                                       mock_repair):
        mock_diag.return_value = self._diag(False)
        result = mrd.run_ai_repair()
        self.assertFalse(result["success"])
        mock_repair.assert_not_called()


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

class TestGenerateReport(unittest.TestCase):

    def _sample_diag(self):
        return {
            "service": {"state": "RUNNING", "pid_from_sc": 1234, "raw": ""},
            "process": {"python_pids": [1234], "port_pid": 1234},
            "http": {
                "/health": {"ok": True, "status_code": 200, "error": None,
                            "content_ok": True},
                "/": {"ok": True, "status_code": 200, "error": None,
                      "content_ok": True},
                "/scan": {"ok": True, "status_code": 200, "error": None,
                          "content_ok": True},
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
                "/health": {"ok": False, "status_code": None, "error": "refused",
                            "content_ok": False},
                "/": {"ok": False, "status_code": None, "error": "refused",
                      "content_ok": False},
                "/scan": {"ok": False, "status_code": None, "error": "refused",
                          "content_ok": False},
            },
            "logs": {"source": None, "last_lines": [], "error_lines": []},
            "db": {"exists": True, "readable": True, "integrity_ok": True,
                   "integrity_result": "ok"},
            "disk": {"free_gb": 50.0, "free_ok": True, "write_ok": True, "error": None},
            "commit": "abc1234",
            "timestamp": "2026-01-01T00:00:00",
        }
        mock_diag.side_effect = [diag, diag]
        mock_http.return_value = {"ok": False, "status_code": None, "error": "refused",
                                  "content_ok": False}
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

    @patch("mrd_recovery.check_public_access", return_value={
        "ok": True, "content_ok": True, "status_code": 200, "error": None
    })
    @patch("mrd_recovery.check_ollama", return_value={
        "ok": True, "models": ["qwen2.5:1.5b"], "selected": "qwen2.5:1.5b", "error": None
    })
    @patch("mrd_recovery.check_git_commit", return_value="abc1234 Init")
    @patch("mrd_recovery.check_disk", return_value={"free_gb": 10.0, "free_ok": True,
                                                    "write_ok": True, "error": None})
    @patch("mrd_recovery.check_db", return_value={"exists": True, "readable": True,
                                                   "integrity_ok": True,
                                                   "integrity_result": "ok"})
    @patch("mrd_recovery.check_logs", return_value={"source": None, "last_lines": [],
                                                    "error_lines": []})
    @patch("mrd_recovery.check_http", return_value={"ok": True, "status_code": 200,
                                                    "error": None, "content_ok": True})
    @patch("mrd_recovery.check_port", return_value=None)
    @patch("mrd_recovery.check_process", return_value={"python_pids": [1234],
                                                       "port_pid": None})
    @patch("mrd_recovery.check_service", return_value={"state": "RUNNING",
                                                       "pid_from_sc": 1234, "raw": ""})
    def test_run_diagnostics_returns_all_keys(self, *mocks):
        result = mrd.run_diagnostics()
        for key in ("service", "process", "http", "logs", "db", "disk", "commit",
                    "ollama", "timestamp"):
            self.assertIn(key, result)
        self.assertIn("/health", result["http"])
        self.assertIn("/scan", result["http"])


# ---------------------------------------------------------------------------
# Fix 2 — LISTENING sockets only, exact port (new tests)
# ---------------------------------------------------------------------------

class TestCheckPortListeningOnly(unittest.TestCase):

    @patch("mrd_recovery._run")
    def test_port_listening_only(self, mock_run):
        """Non-LISTENING lines with correct port are ignored."""
        netstat_out = (
            "  TCP    0.0.0.0:8000           0.0.0.0:1234           ESTABLISHED     5678\n"
            "  TCP    0.0.0.0:8000           0.0.0.0:0              LISTENING       1111\n"
        )
        mock_run.return_value = _make_completed(stdout=netstat_out)
        pid = mrd.check_port(8000)
        self.assertEqual(pid, 1111, "Only the LISTENING line should match")

    @patch("mrd_recovery._run")
    def test_port_exact_match(self, mock_run):
        """Port 18000 is NOT matched when configured port is 8000."""
        netstat_out = (
            "  TCP    0.0.0.0:18000          0.0.0.0:0              LISTENING       9999\n"
        )
        mock_run.return_value = _make_completed(stdout=netstat_out)
        pid = mrd.check_port(8000)
        self.assertIsNone(pid, "Port 18000 must not match when checking port 8000")


# ---------------------------------------------------------------------------
# Fix 3 — PID verification (new tests)
# ---------------------------------------------------------------------------

class TestKillVerification(unittest.TestCase):

    @patch("mrd_recovery._run")
    def test_kill_requires_matching_service_pid(self, mock_run):
        """Port PID != service PID → no kill."""
        def run_side_effect(args, **kwargs):
            if args[0] == "netstat":
                return _make_completed(
                    stdout="  TCP    0.0.0.0:8000    0.0.0.0:0    LISTENING    1111\n"
                )
            if args[0] == "sc" and args[1] == "queryex":
                return _make_completed(stdout="        PID                : 2222\n")
            return _make_completed()

        mock_run.side_effect = run_side_effect
        ok, msg = mrd.safe_kill_port_holder(8000, "MRDToolControl",
                                            r"C:\mrd_tool_control")
        self.assertFalse(ok)
        self.assertIn("no coincide", msg)

    @patch("mrd_recovery._run")
    def test_kill_requires_executable_verification(self, mock_run):
        """Wmic returns wrong executable path → no kill."""
        def run_side_effect(args, **kwargs):
            if args[0] == "netstat":
                return _make_completed(
                    stdout="  TCP    0.0.0.0:8000    0.0.0.0:0    LISTENING    1234\n"
                )
            if args[0] == "sc" and args[1] == "queryex":
                return _make_completed(stdout="        PID                : 1234\n")
            if args[0] == "tasklist":
                return _make_completed(stdout='"python.exe","1234","Console","1","5,000 K"')
            if args[0] == "wmic":
                return _make_completed(
                    stdout="ExecutablePath=C:\\other_app\\server.exe\n"
                )
            return _make_completed()

        mock_run.side_effect = run_side_effect
        ok, msg = mrd.safe_kill_port_holder(8000, "MRDToolControl",
                                            r"C:\mrd_tool_control")
        self.assertFalse(ok)
        self.assertIn("verificación", msg)


# ---------------------------------------------------------------------------
# Fix 8 — sc start/stop return code verification (new tests)
# ---------------------------------------------------------------------------

class TestScReturnCodes(unittest.TestCase):

    @patch("mrd_recovery._run")
    def test_sc_start_checks_returncode(self, mock_run):
        """rc=5 (Access Denied) → returns (False, msg)."""
        mock_run.return_value = _make_completed(returncode=5, stderr="Access denied")
        ok, msg = mrd.sc_start("MRDToolControl")
        self.assertFalse(ok)
        self.assertIn("rc=5", msg)

    @patch("mrd_recovery._run")
    def test_sc_stop_checks_returncode(self, mock_run):
        """rc=5 (Access Denied) → returns (False, msg)."""
        mock_run.return_value = _make_completed(returncode=5, stderr="Access denied")
        ok, msg = mrd.sc_stop("MRDToolControl")
        self.assertFalse(ok)
        self.assertIn("rc=5", msg)


# ---------------------------------------------------------------------------
# Fix 4-6 — /health body: json.loads + status=="ok" exacto
# ---------------------------------------------------------------------------

def _http_result(body: bytes, status: int = 200):
    """Helper: simula una respuesta HTTP con body dado."""
    mock_conn = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.read.return_value = body
    mock_conn.getresponse.return_value = mock_resp
    return mock_conn


class TestHealthCheckContent(unittest.TestCase):

    def _call(self, body: bytes, status: int = 200) -> dict:
        with patch("mrd_recovery.http.client.HTTPConnection",
                   return_value=_http_result(body, status)):
            return mrd.check_http("localhost", 8000, "/health")

    def test_health_json_status_ok(self):
        """JSON {"status": "ok"} → content_ok=True."""
        r = self._call(b'{"status": "ok"}')
        self.assertTrue(r["ok"])
        self.assertTrue(r["content_ok"])

    def test_health_json_status_error(self):
        """JSON {"status": "error"} → content_ok=False."""
        r = self._call(b'{"status": "error"}')
        self.assertTrue(r["ok"])          # 200 sigue siendo ok HTTP
        self.assertFalse(r["content_ok"])

    def test_health_text_status_error(self):
        """Texto plano 'status error' → content_ok=False (no es JSON válido)."""
        r = self._call(b"status error")
        self.assertFalse(r["content_ok"])

    def test_health_html_response(self):
        """Respuesta HTML → JSON inválido → content_ok=False."""
        r = self._call(b"<html><body>OK</body></html>")
        self.assertFalse(r["content_ok"])

    def test_health_empty_body(self):
        """Cuerpo vacío → content_ok=False."""
        r = self._call(b"")
        self.assertFalse(r["content_ok"])

    def test_health_checks_content(self):
        """'Hello World' → JSON inválido → content_ok=False."""
        r = self._call(b"Hello World")
        self.assertTrue(r["ok"])
        self.assertFalse(r["content_ok"])


# ---------------------------------------------------------------------------
# Fix 6 — Restart count persistence (new tests)
# ---------------------------------------------------------------------------

class TestRestartCountPersistence(unittest.TestCase):

    def test_restart_count_persisted(self):
        """Write restart_count.json, verify next call reads it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, ".restart_count.json")
            data = {"count": 2, "ts": time.time()}
            with open(log_path, "w") as f:
                json.dump(data, f)
            with patch("mrd_recovery.RESTART_LOG_PATH", log_path):
                count = mrd._get_restart_count()
        self.assertEqual(count, 2)

    def test_restart_window_expires(self):
        """Old timestamp → count resets to 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, ".restart_count.json")
            # Timestamp well outside the 300s window
            data = {"count": 5, "ts": time.time() - 400}
            with open(log_path, "w") as f:
                json.dump(data, f)
            with patch("mrd_recovery.RESTART_LOG_PATH", log_path):
                count = mrd._get_restart_count()
        self.assertEqual(count, 0)


# ---------------------------------------------------------------------------
# Fix 9 — Secrets stripped from report (new test)
# ---------------------------------------------------------------------------

class TestSecretsStripped(unittest.TestCase):

    def test_secrets_stripped_from_report(self):
        """Inject password, Bearer token, JWT → verify none appear in sanitized output."""
        jwt = ("eyJhbGciOiJIUzI1NiJ9"
               ".eyJzdWIiOiJ1c2VyIn0"
               ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")
        text = f"password=hunter2 Authorization: Bearer abc123 {jwt}"
        result = mrd.sanitize_for_report(text)
        self.assertNotIn("hunter2", result)
        self.assertNotIn("Bearer abc123", result)
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9", result)


# ---------------------------------------------------------------------------
# Recuperación segura de versión estable
# ---------------------------------------------------------------------------

class TestStableRestore(unittest.TestCase):

    def _make_app(self, root, content):
        os.makedirs(os.path.join(root, "templates"), exist_ok=True)
        with open(os.path.join(root, "main.py"), "w", encoding="utf-8") as fh:
            fh.write(content)
        with open(os.path.join(root, "templates", "index.html"),
                  "w", encoding="utf-8") as fh:
            fh.write(f"<h1>{content}</h1>")

    def test_snapshot_excludes_data_secrets_and_uploads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_app(tmpdir, "stable")
            os.makedirs(os.path.join(tmpdir, "data"))
            os.makedirs(os.path.join(tmpdir, "uploads"))
            with open(os.path.join(tmpdir, ".env"), "w") as fh:
                fh.write("SECRET=never-copy")
            with open(os.path.join(tmpdir, "data", "mrd.db"), "w") as fh:
                fh.write("inventory")
            with open(os.path.join(tmpdir, "uploads", "photo.jpg"), "w") as fh:
                fh.write("photo")
            snapshot = os.path.join(tmpdir, "safe", "stable.zip")
            manifest = mrd.create_code_snapshot(tmpdir, snapshot)
            verified = mrd.verify_code_snapshot(snapshot)
            self.assertEqual(manifest["files"], verified["files"])
            self.assertIn("main.py", manifest["files"])
            self.assertIn("templates/index.html", manifest["files"])
            self.assertFalse(any("data/" in p or "uploads/" in p or ".env" in p
                                 for p in manifest["files"]))

    def test_restore_keeps_inventory_and_uploads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = os.path.join(tmpdir, "app")
            stable_dir = os.path.join(tmpdir, "stable_source")
            backups = os.path.join(tmpdir, "backups")
            self._make_app(app_dir, "broken")
            self._make_app(stable_dir, "known-good")
            os.makedirs(os.path.join(app_dir, "data"))
            os.makedirs(os.path.join(app_dir, "uploads"))
            db_path = os.path.join(app_dir, "data", "mrd_tool.db")
            conn = mrd.sqlite3.connect(db_path)
            conn.execute("CREATE TABLE stock (value TEXT)")
            conn.execute("INSERT INTO stock VALUES ('intacto')")
            conn.commit()
            conn.close()
            photo = os.path.join(app_dir, "uploads", "photo.txt")
            with open(photo, "w") as fh:
                fh.write("intacta")
            snapshot = os.path.join(tmpdir, "stable.zip")
            mrd.create_code_snapshot(stable_dir, snapshot)
            config = {
                "app_dir": app_dir, "stable_snapshot_path": snapshot,
                "safety_backup_dir": backups,
                "maintenance_marker": os.path.join(tmpdir, ".maintenance"),
                "health_wait_sec": 1,
            }
            final_diag = {"service": {"state": "RUNNING"}}
            with patch.dict(mrd.CONFIG, config), \
                 patch.object(mrd, "sc_stop", return_value=(True, "ok")), \
                 patch.object(mrd, "sc_start", return_value=(True, "ok")), \
                 patch.object(mrd, "_wait_healthy", return_value=True), \
                 patch.object(mrd, "run_diagnostics", return_value=final_diag):
                result = mrd.restore_stable_version()
            self.assertTrue(result["success"])
            with open(os.path.join(app_dir, "main.py"), encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "known-good")
            conn = mrd.sqlite3.connect(db_path)
            self.assertEqual(conn.execute("SELECT value FROM stock").fetchone()[0], "intacto")
            conn.close()
            with open(photo) as fh:
                self.assertEqual(fh.read(), "intacta")
            self.assertTrue(os.path.isfile(result["backup"]["database"]))

    def test_failed_stable_restore_recovers_previous_code(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = os.path.join(tmpdir, "app")
            stable_dir = os.path.join(tmpdir, "stable_source")
            self._make_app(app_dir, "current-code")
            self._make_app(stable_dir, "stable-code")
            snapshot = os.path.join(tmpdir, "stable.zip")
            mrd.create_code_snapshot(stable_dir, snapshot)
            config = {
                "app_dir": app_dir, "stable_snapshot_path": snapshot,
                "safety_backup_dir": os.path.join(tmpdir, "backups"),
                "maintenance_marker": os.path.join(tmpdir, ".maintenance"),
            }
            with patch.dict(mrd.CONFIG, config), \
                 patch.object(mrd, "sc_stop", return_value=(True, "ok")), \
                 patch.object(mrd, "sc_start", return_value=(True, "ok")), \
                 patch.object(mrd, "_wait_healthy", side_effect=[False, True]), \
                 patch.object(mrd, "run_diagnostics", return_value={}):
                result = mrd.restore_stable_version()
            self.assertFalse(result["success"])
            self.assertTrue(result["rolled_back"])
            with open(os.path.join(app_dir, "main.py"), encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "current-code")

    def test_stop_denied_never_writes_application_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = os.path.join(tmpdir, "app")
            stable_dir = os.path.join(tmpdir, "stable_source")
            self._make_app(app_dir, "current-code")
            self._make_app(stable_dir, "stable-code")
            snapshot = os.path.join(tmpdir, "stable.zip")
            mrd.create_code_snapshot(stable_dir, snapshot)
            config = {
                "app_dir": app_dir, "stable_snapshot_path": snapshot,
                "safety_backup_dir": os.path.join(tmpdir, "backups"),
                "maintenance_marker": os.path.join(tmpdir, ".maintenance"),
            }
            with patch.dict(mrd.CONFIG, config), \
                 patch.object(mrd, "sc_stop", return_value=(False, "denegado")), \
                 patch.object(mrd, "check_service", return_value={"state": "RUNNING"}), \
                 patch.object(mrd, "_restore_code_snapshot") as restore_mock, \
                 patch.object(mrd, "run_diagnostics", return_value={}):
                result = mrd.restore_stable_version()
            self.assertFalse(result["success"])
            self.assertFalse(result["rolled_back"])
            restore_mock.assert_not_called()
            with open(os.path.join(app_dir, "main.py"), encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "current-code")


# ---------------------------------------------------------------------------
# Fix 5 — Atomic lock (new test)
# ---------------------------------------------------------------------------

class TestLockIsAtomic(unittest.TestCase):

    def test_lock_is_atomic(self):
        """FileExistsError on O_CREAT|O_EXCL with live PID → returns False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = os.path.join(tmpdir, ".recovery.lock")
            # Write a live PID to the lock (simulate existing lock)
            with open(lock_path, "w") as f:
                f.write(str(os.getpid()))
            # Patch _lock_pid_running to say it's alive
            with patch.object(mrd, "_lock_pid_running", return_value=True):
                result = mrd._acquire_lock(lock_path)
        self.assertFalse(result, "_acquire_lock must return False when PID is live")


# ---------------------------------------------------------------------------
# Fix 1, 3, 4, 5 — DB path discovery (nuevas pruebas)
# ---------------------------------------------------------------------------

class TestDbPathDiscovery(unittest.TestCase):

    def test_db_path_from_local_env(self):
        """config/local.env con MRD_DATABASE_URL → ruta resuelta (normpath para Windows)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_dir = os.path.join(tmpdir, "config")
            os.makedirs(cfg_dir)
            with open(os.path.join(cfg_dir, "local.env"), "w") as f:
                f.write("MRD_DATABASE_URL=sqlite:///data/mrd_tool.db\n")
            result = mrd._resolve_db_path(tmpdir)
            expected = os.path.normpath(os.path.join(tmpdir, "data", "mrd_tool.db"))
            self.assertEqual(result, expected)

    def test_db_default_when_no_config(self):
        """Sin config → ruta predeterminada data/mrd_tool.db."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = mrd._resolve_db_path(tmpdir)
            expected = os.path.join(tmpdir, "data", "mrd_tool.db")
            self.assertEqual(result, expected)

    def test_db_indeterminate_when_conflict(self):
        """
        Conflicto real sin mockear _resolve_db_path:
        config/local.env y config.py tienen MRD_DATABASE_URL distintas
        → 'base indeterminada'.
        Prioridad documentada: env (local.env > .env) se compara con config.py;
        si difieren → indeterminada.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_dir = os.path.join(tmpdir, "config")
            os.makedirs(cfg_dir)
            with open(os.path.join(cfg_dir, "local.env"), "w") as f:
                f.write("MRD_DATABASE_URL=sqlite:///data/db_a.db\n")
            with open(os.path.join(tmpdir, "config.py"), "w") as f:
                f.write('MRD_DATABASE_URL = "sqlite:///data/db_b.db"\n')
            result = mrd._resolve_db_path(tmpdir)
        self.assertEqual(result, mrd._DB_INDETERMINATE,
                         "Rutas distintas en env vs config.py deben dar 'base indeterminada'")

    def test_db_same_path_both_sources_not_conflict(self):
        """
        Misma ruta en local.env y config.py → sin conflicto, retorna la ruta.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_dir = os.path.join(tmpdir, "config")
            os.makedirs(cfg_dir)
            with open(os.path.join(cfg_dir, "local.env"), "w") as f:
                f.write("MRD_DATABASE_URL=sqlite:///data/mrd_tool.db\n")
            with open(os.path.join(tmpdir, "config.py"), "w") as f:
                f.write('MRD_DATABASE_URL = "sqlite:///data/mrd_tool.db"\n')
            result = mrd._resolve_db_path(tmpdir)
        expected = os.path.normpath(os.path.join(tmpdir, "data", "mrd_tool.db"))
        self.assertEqual(result, expected)

    def test_db_no_dotdb_guessing(self):
        """Con .db sueltos en raíz (sin config) → retorna ruta predeterminada, no adivina."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Crea un .db suelto en la raíz
            with open(os.path.join(tmpdir, "other.db"), "w") as f:
                f.write("")
            result = mrd._resolve_db_path(tmpdir)
            # Debe devolver la ruta predeterminada, NO other.db
            expected = os.path.join(tmpdir, "data", "mrd_tool.db")
            self.assertEqual(result, expected)

    def test_check_db_indeterminate(self):
        """check_db con 'base indeterminada' → informa sin intentar abrir archivo."""
        with patch.dict(mrd.CONFIG, {"db_path": mrd._DB_INDETERMINATE}):
            with patch("mrd_recovery.sqlite3.connect") as mock_conn:
                result = mrd.check_db()
        mock_conn.assert_not_called()
        self.assertEqual(result["integrity_result"], mrd._DB_INDETERMINATE)
        self.assertFalse(result["exists"])


# ---------------------------------------------------------------------------
# Fix 6, 7, 8, 9 — Pruebas integradas de run_repair()
# ---------------------------------------------------------------------------

class TestRunRepairIntegrated(unittest.TestCase):
    """Pruebas integradas de run_repair() según correcciones 6-9."""

    def setUp(self):
        mrd._reset_restart_count()

    def _base_diag(self, svc_state="STOPPED", health_ok=False, health_content=False):
        return {
            "service": {"state": svc_state, "pid_from_sc": 1234 if svc_state != "STOPPED" else None, "raw": ""},
            "process": {"python_pids": [], "port_pid": None},
            "http": {
                "/health": {"ok": health_ok, "status_code": 200 if health_ok else None,
                            "error": None, "content_ok": health_content},
                "/": {"ok": False, "status_code": None, "error": "refused", "content_ok": False},
                "/scan": {"ok": False, "status_code": None, "error": "refused", "content_ok": False},
            },
            "logs": {"source": None, "last_lines": [], "error_lines": []},
            "db": {"exists": True, "readable": True, "integrity_ok": True, "integrity_result": "ok"},
            "disk": {"free_gb": 50.0, "free_ok": True, "write_ok": True, "error": None},
            "commit": "abc1234",
            "timestamp": "2026-01-01T00:00:00",
        }

    @patch("mrd_recovery.time.sleep")
    @patch("mrd_recovery.check_http")
    @patch("mrd_recovery.run_diagnostics")
    @patch("mrd_recovery._run")
    def test_repair_health_200_fake_body_fails(self, mock_run, mock_diag, mock_http, mock_sleep):
        """HTTP 200 pero body sin 'ok'/'status'/'running' → content_ok=False → falla."""
        # El diagnóstico inicial muestra servicio parado
        mock_diag.side_effect = [
            self._base_diag("STOPPED"),
            self._base_diag("RUNNING", health_ok=True, health_content=False),
        ]
        # El polling de health recibe ok=True pero content_ok=False (cuerpo falso)
        mock_http.return_value = {
            "ok": True, "status_code": 200, "error": None, "content_ok": False
        }
        mock_run.return_value = _make_completed()

        result = mrd.run_repair()

        # health_up debe ser False porque content_ok=False
        self.assertFalse(result["success"],
                         "HTTP 200 con cuerpo falso no debe considerarse /health válido")

    @patch("mrd_recovery.time.sleep")
    @patch("mrd_recovery.check_http")
    @patch("mrd_recovery.run_diagnostics")
    @patch("mrd_recovery._run")
    def test_repair_uses_configured_data_db_not_root(self, mock_run, mock_diag,
                                                      mock_http, mock_sleep):
        """BD raíz vacía frente a BD configurada en data → usa la de config."""
        # Prepara directorio temporal con config/local.env apuntando a data/
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_dir = os.path.join(tmpdir, "config")
            os.makedirs(cfg_dir)
            with open(os.path.join(cfg_dir, "local.env"), "w") as f:
                f.write(f"MRD_DATABASE_URL=sqlite:///{tmpdir}/data/mrd_tool.db\n")
            # .db suelto en raíz (NO debe ser elegido)
            with open(os.path.join(tmpdir, "root.db"), "w") as f:
                f.write("")

            resolved = mrd._resolve_db_path(tmpdir)

        self.assertIn("data", resolved, "Debe usar ruta de config, no .db suelto en raíz")
        self.assertNotIn("root.db", resolved)

    @patch("mrd_recovery._run")
    def test_kill_empty_executable_rejected(self, mock_run):
        """Wmic devuelve ExecutablePath vacío → _verify_pid_is_service retorna False."""
        def run_side(args, **kwargs):
            if args[0] == "tasklist":
                return _make_completed(stdout='"python.exe","1234","Console","1","4 K"')
            if args[0] == "wmic":
                # ExecutablePath vacío
                return _make_completed(stdout="ExecutablePath=\n")
            return _make_completed()

        mock_run.side_effect = run_side
        result = mrd._verify_pid_is_service(1234, "MRDToolControl", r"C:\mrd_tool_control")
        self.assertFalse(result, "Ejecutable vacío debe rechazar la verificación")

    @patch("mrd_recovery._run")
    def test_kill_other_python_process_rejected(self, mock_run):
        """Otro python.exe fuera de C:\\mrd_tool_control → no mata."""
        def run_side(args, **kwargs):
            if args[0] == "netstat":
                return _make_completed(
                    stdout="  TCP    0.0.0.0:8000    0.0.0.0:0    LISTENING    1234\n"
                )
            if args[0] == "sc" and args[1] == "queryex":
                return _make_completed(stdout="        PID                : 1234\n")
            if args[0] == "tasklist":
                return _make_completed(stdout='"python.exe","1234","Console","1","4 K"')
            if args[0] == "wmic":
                # Python de otro proyecto — fuera de mrd_tool_control
                return _make_completed(
                    stdout="ExecutablePath=C:\\other_project\\venv\\python.exe\n"
                )
            return _make_completed()

        mock_run.side_effect = run_side
        ok, msg = mrd.safe_kill_port_holder(8000, "MRDToolControl", r"C:\mrd_tool_control")
        self.assertFalse(ok, "Python ajeno no debe ser eliminado")

    def test_auth_bearer_value_completely_removed(self):
        """Authorization: Bearer abc123 → 'abc123' no aparece en salida."""
        text = "Authorization: Bearer abc123"
        result = mrd.sanitize_for_report(text)
        self.assertNotIn("abc123", result,
                         f"El valor del token debe desaparecer completamente. Salida: {result!r}")
        # El campo Authorization debe seguir presente pero con valor redactado
        self.assertIn("Authorization", result)

    @patch("mrd_recovery.time.sleep")
    @patch("mrd_recovery.check_http")
    @patch("mrd_recovery.run_diagnostics")
    @patch("mrd_recovery._run")
    def test_repair_health_json_ok_body_succeeds(self, mock_run, mock_diag,
                                                  mock_http, mock_sleep):
        """run_repair con body JSON {'status':'ok'} real → content_ok=True → success."""
        healthy = self._base_diag("RUNNING", health_ok=True, health_content=True)
        healthy["http"]["/scan"] = {"ok": True, "status_code": 200,
                                    "error": None, "content_ok": True}
        mock_diag.side_effect = [
            self._base_diag("STOPPED"),
            healthy,
        ]
        # El polling devuelve ok=True y content_ok=True (JSON {"status":"ok"})
        mock_http.return_value = {
            "ok": True, "status_code": 200, "error": None, "content_ok": True
        }
        mock_run.return_value = _make_completed()

        result = mrd.run_repair()

        self.assertTrue(result["success"],
                        "JSON {'status':'ok'} debe considerarse /health válido")


if __name__ == "__main__":
    unittest.main(verbosity=2)
