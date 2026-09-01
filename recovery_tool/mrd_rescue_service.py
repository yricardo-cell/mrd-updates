"""Servidor remoto permanente de MRD Rescue para el túnel Cloudflare."""

import datetime
import os
import signal
import threading

from mrd_recovery import (
    CONFIG,
    MobileControlServer,
    generate_report,
    power_on,
    restore_stable_version,
    run_ai_repair,
    run_diagnostics,
    run_repair,
    sanitize_for_report,
)


class ImmediateRoot:
    """Compatibilidad mínima con root.after sin depender de una ventana."""

    @staticmethod
    def after(_delay, callback):
        callback()


class HeadlessRescueApp:
    def __init__(self):
        self.root = ImmediateRoot()
        self._busy = False
        self._lock = threading.Lock()
        self.log_path = os.path.join(CONFIG["log_dir"], "rescue_remote.log")

    def _log(self, message):
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        line = f"{datetime.datetime.now().isoformat()} {message}\n"
        with self._lock:
            with open(self.log_path, "a", encoding="utf-8") as output:
                output.write(line)

    def mobile_activity(self):
        try:
            with open(self.log_path, encoding="utf-8", errors="replace") as source:
                lines = source.readlines()[-10:]
            return [sanitize_for_report(line.strip()) for line in lines if line.strip()]
        except OSError:
            return []

    def _begin(self, target):
        with self._lock:
            if self._busy:
                return False
            self._busy = True
        threading.Thread(target=target, daemon=True).start()
        return True

    def _finish(self):
        with self._lock:
            self._busy = False

    def _on_ai_repair(self):
        self._begin(self._ai_worker)

    def _on_power_on(self):
        self._begin(self._power_worker)

    def _power_worker(self):
        try:
            result = power_on()
            self._log(f"Encendido remoto success={result['success']}")
        except Exception as exc:
            self._log(f"Encendido remoto error={exc}")
        finally:
            self._finish()

    def _on_repair(self):
        self._begin(self._basic_worker)

    def _basic_worker(self):
        try:
            result = run_repair()
            report = generate_report(result["final_diag"], result["actions"])
            self._log(f"Reparación básica success={result['success']} report={report}")
        except Exception as exc:
            self._log(f"Reparación básica error={exc}")
        finally:
            self._finish()

    def _on_diagnose(self):
        self._begin(self._diagnose_worker)

    def _diagnose_worker(self):
        try:
            diag = run_diagnostics()
            report = generate_report(diag)
            self._log(f"Diagnóstico remoto report={report}")
        except Exception as exc:
            self._log(f"Diagnóstico remoto error={exc}")
        finally:
            self._finish()

    def _ai_worker(self):
        try:
            result = run_ai_repair()
            report = generate_report(result["final_diag"], result["actions"])
            self._log(f"Reparación IA success={result['success']} report={report}")
        except Exception as exc:
            self._log(f"Reparación IA error={exc}")
        finally:
            self._finish()

    def _on_remote_restore(self):
        self._begin(self._restore_worker)

    def _restore_worker(self):
        try:
            result = restore_stable_version()
            report = generate_report(result["final_diag"], result["actions"])
            self._log(
                f"Restauración estable success={result['success']} "
                f"rolled_back={result['rolled_back']} report={report}"
            )
        except Exception as exc:
            self._log(f"Restauración estable error={exc}")
        finally:
            self._finish()


def main():
    app = HeadlessRescueApp()
    server = MobileControlServer(app)
    ok, detail = server.start()
    if not ok:
        app._log(f"No se pudo iniciar el panel remoto: {detail}")
        raise SystemExit(1)
    app._log(f"Panel remoto activo en {server.public_origin}")
    stopped = threading.Event()

    def stop_handler(*_args):
        stopped.set()

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    try:
        stopped.wait()
    finally:
        server.stop()
        app._log("Panel remoto detenido")


if __name__ == "__main__":
    main()
