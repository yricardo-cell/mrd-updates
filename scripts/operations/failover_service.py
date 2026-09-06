"""
MRD TOOL CONTROL — Servicio Windows del vigilante de failover de tunel (Fase 1)
Continuidad 24x7 — app.iasmrd.com

Registra scripts/operations/failover.py como servicio SCM real
'MRDFailoverWatchdog', siguiendo el mismo patron pywin32 que windows_service.py
usa para el servicio principal MRDToolControl: gestion via el Service Control
Manager de Windows (arranque automatico, recuperacion ante fallos, logs de
Event Viewer), en vez de una tarea programada.

Uso (como Administrador):
  python failover_service.py install    # Registrar servicio en Windows
  python failover_service.py start      # Iniciar servicio
  python failover_service.py stop       # Detener servicio
  python failover_service.py restart    # Reiniciar servicio
  python failover_service.py remove     # Desinstalar servicio
  python failover_service.py status     # Ver estado
  python failover_service.py run        # Modo standalone (sin Windows Service)
  python failover_service.py debug      # Debug interactivo (consola)

Todos los argumentos de comprobacion (umbrales, URLs, IDs de tunel) usan los
valores por defecto de failover.py. Este wrapper no anade configuracion propia
a proposito, para que solo exista un lugar donde tocar esos parametros.
"""
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import failover  # scripts/operations/failover.py

SERVICE_NAME = "MRDFailoverWatchdog"
SERVICE_DISPLAY = "MRD Failover Watchdog"
SERVICE_DESCRIPTION = (
    "Vigila app.iasmrd.com y conmuta el tunel Cloudflare activo (A/B) si el "
    "tunel A pierde conexion con el edge mientras la app local sigue sana."
)


class FailoverRunner:
    """Ejecuta el bucle principal de failover.py en un hilo, con parada limpia."""

    def __init__(self, argv: list[str] | None = None):
        self._argv = argv or []
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._exit_code: int | None = None

    def run(self) -> None:
        """Punto de entrada principal. Bloquea hasta que se llame a stop()."""
        self._thread = threading.Thread(
            target=self._run_failover, daemon=True, name="mrd-failover-watchdog",
        )
        self._thread.start()
        self._stop_event.wait()
        # Espera breve a que el bucle de failover.py note el stop_event y
        # cierre el lock file limpiamente antes de que el proceso termine.
        if self._thread.is_alive():
            self._thread.join(timeout=15)

    def stop(self) -> None:
        """Solicita parada del runner (llamado desde SvcStop o senal del SO)."""
        self._stop_event.set()

    def _run_failover(self) -> None:
        try:
            self._exit_code = failover.main(self._argv, stop_event=self._stop_event)
        except Exception:
            logging.exception("Excepcion no controlada en el bucle de failover.")
        finally:
            # Si el bucle termina por su cuenta (p.ej. error irrecuperable),
            # que el servicio se detenga en vez de quedar "corriendo" sin vigilar nada.
            self._stop_event.set()


# ─── Modo standalone (sin Windows Service) ───────────────────────────────────

def run_standalone() -> None:
    """Arranca el runner directamente en la consola (desarrollo / fallback)."""
    import signal

    runner = FailoverRunner()

    def _handle_signal(sig, _frame):
        runner.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    runner.run()


# ─── Windows Service (pywin32) ────────────────────────────────────────────────

try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager

    class MRDFailoverWindowsService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = SERVICE_DISPLAY
        _svc_description_ = SERVICE_DESCRIPTION

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self._stop_event = win32event.CreateEvent(None, 0, 0, None)
            self._runner = FailoverRunner()

        def SvcStop(self):
            """Llamado por el SCM para detener el servicio."""
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            servicemanager.LogInfoMsg(f"{SERVICE_NAME}: Solicitud de parada recibida.")
            self._runner.stop()
            win32event.SetEvent(self._stop_event)

        def SvcDoRun(self):
            """Punto de entrada del servicio Windows."""
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )
            try:
                self._runner.run()
            except Exception as exc:
                servicemanager.LogErrorMsg(f"{SERVICE_NAME}: excepcion critica: {exc}")
            finally:
                win32event.SetEvent(self._stop_event)

    WINDOWS_SERVICE_AVAILABLE = True

except ImportError:
    WINDOWS_SERVICE_AVAILABLE = False
    MRDFailoverWindowsService = None  # type: ignore


# ─── CLI principal ────────────────────────────────────────────────────────────

def _print_status() -> None:
    if WINDOWS_SERVICE_AVAILABLE:
        try:
            status = win32serviceutil.QueryServiceStatus(SERVICE_NAME)
            svc_state = {1: "STOPPED", 2: "START_PENDING", 3: "STOP_PENDING",
                        4: "RUNNING", 5: "CONTINUE_PENDING", 6: "PAUSE_PENDING",
                        7: "PAUSED"}.get(status[1], "UNKNOWN")
            print(f"  Servicio Windows: {svc_state}")
        except Exception:
            print("  Servicio Windows: no instalado")
    else:
        print("  pywin32 no disponible en este interprete.")


if __name__ == "__main__":
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else ""

    if cmd == "run":
        print(f"Iniciando {SERVICE_NAME} en modo standalone...")
        run_standalone()

    elif cmd == "status":
        print(f"\n{SERVICE_NAME} — Estado:")
        _print_status()

    elif cmd in ("install", "update", "remove", "start", "stop",
                 "restart", "debug", "queryex"):
        if not WINDOWS_SERVICE_AVAILABLE:
            print("ERROR: pywin32 no instalado. Instala con: pip install pywin32")
            sys.exit(1)
        win32serviceutil.HandleCommandLine(MRDFailoverWindowsService)

    else:
        print(f"""
MRD FAILOVER WATCHDOG — Servicio Windows
Uso: python failover_service.py <comando>

Comandos:
  install    Registrar el servicio en Windows (requiere admin)
  start      Iniciar el servicio
  stop       Detener el servicio
  restart    Reiniciar el servicio
  remove     Desinstalar el servicio
  status     Ver estado actual
  run        Modo standalone (sin Windows Service)
  debug      Modo debug interactivo
""")
        sys.exit(1)
