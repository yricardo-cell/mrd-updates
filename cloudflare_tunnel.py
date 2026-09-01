"""
MRD TOOL CONTROL — Módulo Cloudflare Named Tunnel
Sprint 5.4 — Cloudflare Production

Gestiona Named Tunnels: estado, versión, métricas, diagnóstico, restart.
NO expone tokens, credenciales ni rutas de configuración sensibles.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time as _time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional

CREATE_NO_WINDOW = 0x08000000  # Windows: no abrir ventana CMD

# Puerto por defecto de métricas de cloudflared
CF_METRICS_PORT = 20241
CF_METRICS_URL  = f"http://localhost:{CF_METRICS_PORT}"

# ─── Sanitización ─────────────────────────────────────────────────────────────

def _sanitize_service_name(name: str) -> str:
    """Solo caracteres seguros para nombre de servicio Windows."""
    if not name:
        return "cloudflared"
    return re.sub(r"[^a-zA-Z0-9_\-]", "", str(name))[:64] or "cloudflared"


def _sanitize_exe_path(path: str) -> str:
    """Valida que sea un path de archivo (no comandos shell)."""
    if not path:
        return "cloudflared.exe"
    p = str(path).strip()
    # No permitir caracteres de shell
    if re.search(r'[;&|<>`$\n\r]', p):
        return "cloudflared.exe"
    if len(p) > 512:
        return "cloudflared.exe"
    return p


def _validate_hostname(hostname: str) -> Optional[str]:
    """Valida hostname/dominio (sin esquema)."""
    if not hostname:
        return None
    h = str(hostname).strip().lower()
    if not re.match(r'^[a-z0-9][a-z0-9\.\-]{1,252}$', h):
        return None
    return h


def _validate_url(url: str) -> Optional[str]:
    """Valida URL: solo http/https."""
    if not url:
        return None
    url = str(url).strip().rstrip("/")
    if not re.match(r'^https?://', url):
        return None
    if re.search(r'[\s;<>&\'"]', url):
        return None
    if len(url) > 512:
        return None
    return url


# ─── Versión de cloudflared ───────────────────────────────────────────────────

def get_cloudflared_version(exe_path: str = "cloudflared.exe") -> Optional[str]:
    """Obtiene la versión de cloudflared. Devuelve None si no está instalado."""
    exe = _sanitize_exe_path(exe_path)
    try:
        result = subprocess.run(
            [exe, "--version"],
            capture_output=True, text=True, timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
        # Formato: "cloudflared version 2024.x.x (built ...)"
        match = re.search(r'cloudflared version ([\d\.]+)', result.stdout + result.stderr)
        if match:
            return match.group(1)
        # Alternativa: solo la línea de version
        out = (result.stdout or result.stderr or "").strip()
        return out[:60] if out else None
    except FileNotFoundError:
        return None
    except Exception:
        return None


# ─── Estado del servicio Windows ─────────────────────────────────────────────

def get_service_status(service_name: str = "cloudflared") -> dict:
    """
    Consulta el estado del servicio Windows de cloudflared.
    Devuelve dict con: installed, running, start_type, display_name.
    """
    svc = _sanitize_service_name(service_name)
    result = {
        "installed": False,
        "running": False,
        "start_type": None,
        "display_name": None,
        "state": "NOT_INSTALLED",
    }
    try:
        r = subprocess.run(
            ["sc", "query", svc],
            capture_output=True, text=True, timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode == 0:
            result["installed"] = True
            if "RUNNING" in r.stdout:
                result["running"] = True
                result["state"] = "RUNNING"
            elif "STOPPED" in r.stdout:
                result["state"] = "STOPPED"
            elif "START_PENDING" in r.stdout:
                result["state"] = "STARTING"
            elif "STOP_PENDING" in r.stdout:
                result["state"] = "STOPPING"

        # Consultar tipo de inicio
        r2 = subprocess.run(
            ["sc", "qc", svc],
            capture_output=True, text=True, timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
        if r2.returncode == 0:
            m = re.search(r'START_TYPE\s*:\s*\d+\s+(\S+)', r2.stdout)
            if m:
                result["start_type"] = m.group(1)
            m2 = re.search(r'DISPLAY_NAME\s*:\s*(.+)', r2.stdout)
            if m2:
                result["display_name"] = m2.group(1).strip()
    except Exception:
        pass
    return result


def restart_service(service_name: str = "cloudflared") -> dict:
    """
    Reinicia el servicio Windows cloudflared.
    Devuelve: {ok, message}
    """
    svc = _sanitize_service_name(service_name)
    try:
        # Stop
        subprocess.run(
            ["sc", "stop", svc],
            capture_output=True, timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
        _time.sleep(3)
        # Start
        r = subprocess.run(
            ["sc", "start", svc],
            capture_output=True, text=True, timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode == 0 or "START_PENDING" in r.stdout:
            return {"ok": True, "message": f"Servicio '{svc}' reiniciado."}
        return {"ok": False, "message": f"Error al reiniciar '{svc}': {r.stderr.strip()[:100]}"}
    except Exception as e:
        return {"ok": False, "message": f"Excepción: {str(e)[:100]}"}


# ─── Métricas de cloudflared ──────────────────────────────────────────────────

def get_metrics() -> dict:
    """
    Lee las métricas de cloudflared desde su endpoint local (puerto 20241).
    Devuelve dict con: available, connections, tunnelID, etc.
    Nunca expone credenciales ni tokens.
    """
    result = {
        "available": False,
        "connections": 0,
        "tunnel_id": None,
        "connector_id": None,
        "metrics_url": CF_METRICS_URL,
    }
    try:
        req = urllib.request.Request(
            f"{CF_METRICS_URL}/healthz",
            headers={"User-Agent": "MRD-TOOL/1.0"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                result["available"] = True
    except Exception:
        pass

    if not result["available"]:
        return result

    # Leer métricas en formato Prometheus
    try:
        req2 = urllib.request.Request(
            f"{CF_METRICS_URL}/metrics",
            headers={"User-Agent": "MRD-TOOL/1.0"},
        )
        with urllib.request.urlopen(req2, timeout=3) as resp:
            body = resp.read().decode("utf-8", errors="ignore")

        # Extraer número de conexiones activas
        m = re.search(r'cloudflared_tunnel_active_streams\{[^}]*\}\s+(\d+)', body)
        if m:
            result["connections"] = int(m.group(1))

        # Extraer tunnel ID (no es un token, es un UUID público)
        m2 = re.search(r'tunnel_id="([0-9a-f\-]{36})"', body)
        if m2:
            result["tunnel_id"] = m2.group(1)

        # Extraer connector ID
        m3 = re.search(r'connector_id="([^"]+)"', body)
        if m3:
            result["connector_id"] = m3.group(1)[:36]

    except Exception:
        pass

    return result


# ─── Config del Named Tunnel ──────────────────────────────────────────────────

def read_tunnel_config(config_file: str) -> dict:
    """
    Lee el config.yml de cloudflared.
    Extrae: tunnel (name/id), credentials-file (solo existencia), ingress rules (hostname).
    NO expone el contenido del credentials-file.
    """
    result = {
        "tunnel": None,
        "credentials_file_exists": False,
        "hostname": None,
        "ingress_count": 0,
        "error": None,
    }
    if not config_file:
        return result

    path = Path(config_file)
    if not path.exists():
        result["error"] = "Archivo de configuración no encontrado"
        return result

    try:
        try:
            import yaml  # type: ignore
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except ImportError:
            # Parseo manual básico si no hay pyyaml
            data = {}
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if ":" in line and not line.startswith("#"):
                        k, _, v = line.partition(":")
                        data[k.strip()] = v.strip()

        if not isinstance(data, dict):
            result["error"] = "Formato de configuración inválido"
            return result

        # Nombre/ID del túnel (no sensible)
        result["tunnel"] = str(data.get("tunnel", ""))[:64] or None

        # Credentials file: solo comprobar existencia
        creds = data.get("credentials-file", "")
        if creds and Path(creds).exists():
            result["credentials_file_exists"] = True

        # Hostname del primer ingress rule
        ingress = data.get("ingress", [])
        if isinstance(ingress, list):
            result["ingress_count"] = len(ingress)
            for rule in ingress:
                if isinstance(rule, dict) and rule.get("hostname"):
                    result["hostname"] = str(rule["hostname"])[:128]
                    break

    except Exception as e:
        result["error"] = str(e)[:100]

    return result


# ─── Diagnóstico completo ─────────────────────────────────────────────────────

def run_diagnostics(config: dict, port: int = 8000) -> list:
    """
    Ejecuta 8 pruebas de diagnóstico y devuelve lista de resultados.
    Cada resultado: {name, label, ok, detail, ms}
    """
    checks = []

    def add(name: str, label: str, ok: bool, detail: str, ms: Optional[int] = None):
        checks.append({"name": name, "label": label, "ok": ok,
                        "detail": detail, "ms": ms,
                        "status": "ok" if ok else "error"})

    # 1. Servidor local
    ms_local = _check_port_latency("localhost", port)
    add("local_server", "Servidor interno",
        ms_local is not None,
        f"http://localhost:{port} — {ms_local} ms" if ms_local else f"Puerto {port} no responde",
        ms_local)

    # 2. Servicio cloudflared Windows
    svc_name = config.get("cloudflared_service", "cloudflared")
    svc = get_service_status(svc_name)
    add("cf_service", "Servicio cloudflared",
        svc["running"],
        f"Estado: {svc['state']}" + (f" | Inicio: {svc['start_type']}" if svc.get("start_type") else ""))

    # 3. Métricas cloudflared (endpoint /healthz)
    metrics = get_metrics()
    add("cf_metrics", "cloudflared healthz",
        metrics["available"],
        f"Conexiones activas: {metrics['connections']}" if metrics["available"] else "Endpoint no disponible")

    # 4. Versión cloudflared
    exe = config.get("cloudflared_exe", "cloudflared.exe")
    version = get_cloudflared_version(exe)
    add("cf_version", "Versión cloudflared",
        version is not None,
        f"v{version}" if version else "cloudflared.exe no encontrado o no en PATH")

    # 5. DNS del dominio
    hostname = config.get("cf_hostname", "") or ""
    if hostname and _validate_hostname(hostname):
        dns_ok, dns_detail = _check_dns(hostname)
        add("dns", f"DNS — {hostname}", dns_ok, dns_detail)
    else:
        add("dns", "DNS del dominio", False, "Hostname no configurado")

    # 6. URL pública accesible
    pub_url = _validate_url(config.get("cf_public_url", "") or "")
    if pub_url:
        ms_pub = _check_url_latency(pub_url)
        add("public_url", "URL pública accesible",
            ms_pub is not None,
            f"{pub_url} — {ms_pub} ms" if ms_pub else f"{pub_url} no responde",
            ms_pub)
    else:
        add("public_url", "URL pública accesible", False, "PUBLIC_URL no configurada")

    # 7. HTTPS activo
    https_ok = bool(pub_url and pub_url.startswith("https://"))
    add("https", "HTTPS activo",
        https_ok,
        "HTTPS configurado" if https_ok else "No se usa HTTPS (configura PUBLIC_URL con https://)")

    # 8. Ruta /scan accesible
    if pub_url:
        scan_url = pub_url.rstrip("/") + "/scan"
        ms_scan = _check_url_latency(scan_url, timeout=4)
        add("scan_route", "Ruta /scan accesible",
            ms_scan is not None,
            f"{scan_url} — {ms_scan} ms" if ms_scan else f"{scan_url} no responde",
            ms_scan)
    else:
        # Comprobar /scan local
        ms_scan_local = _check_url_latency(f"http://localhost:{port}/scan", timeout=2)
        add("scan_route", "Ruta /scan (local)",
            ms_scan_local is not None,
            f"Local: {ms_scan_local} ms" if ms_scan_local else "Ruta /scan no responde")

    # 9. Servicio MRDToolControl (Windows)
    mrd_svc = _check_windows_service("MRDToolControl")
    add("mrd_service", "Servicio MRDToolControl",
        mrd_svc["running"],
        "Estado: " + mrd_svc["state"] + (" | Inicio: " + mrd_svc["start_type"] if mrd_svc.get("start_type") else ""))

    # 10. Certificado SSL
    if pub_url and pub_url.startswith("https://"):
        cert_host = (hostname or pub_url.replace("https://", "").split("/")[0])
        cert_ok, cert_detail = _check_ssl_cert(cert_host)
        add("ssl_cert", "Certificado SSL", cert_ok, cert_detail)
    else:
        add("ssl_cert", "Certificado SSL", False,
            "No aplica (HTTPS no configurado) — configura PUBLIC_URL con https://")

    # 11. Ruta /login accesible
    if pub_url:
        ms_login = _check_url_latency(pub_url.rstrip("/") + "/login", timeout=5)
        add("login_route", "Ruta /login accesible",
            ms_login is not None,
            (pub_url.rstrip("/") + "/login — " + str(ms_login) + " ms") if ms_login
            else (pub_url.rstrip("/") + "/login no responde"),
            ms_login)
    else:
        ms_login_loc = _check_url_latency(f"http://localhost:{port}/login", timeout=3)
        add("login_route", "Ruta /login (local)",
            ms_login_loc is not None,
            f"Local: {ms_login_loc} ms" if ms_login_loc else "Ruta /login no responde",
            ms_login_loc)

    # 12. Manifesto PWA
    ms_pwa = _check_url_latency(f"http://localhost:{port}/static/manifest.json", timeout=2)
    if ms_pwa is None:
        ms_pwa = _check_url_latency(f"http://localhost:{port}/manifest.json", timeout=2)
    add("pwa_manifest", "Manifesto PWA",
        ms_pwa is not None,
        f"manifest.json — {ms_pwa} ms" if ms_pwa else "manifest.json no accesible (PWA limitada)")

    return checks


def _check_windows_service(service_name: str) -> dict:
    import platform
    if platform.system() != "Windows":
        return {"running": False, "state": "NO_WINDOWS", "start_type": ""}
    sname = _sanitize_service_name(service_name)
    try:
        r = subprocess.run(
            ["sc", "query", sname],
            capture_output=True, text=True, timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
        out = r.stdout.upper()
        if r.returncode == 1060 or "DOES_NOT_EXIST" in out or "FAILED" in out:
            return {"running": False, "state": "NO_INSTALADO", "start_type": ""}
        running = "RUNNING" in out
        if "RUNNING" in out:
            state = "EN EJECUCION"
        elif "STOPPED" in out:
            state = "DETENIDO"
        elif "PAUSED" in out:
            state = "EN PAUSA"
        else:
            state = r.stdout.strip()[:30] if r.stdout.strip() else "DESCONOCIDO"
        return {"running": running, "state": state, "start_type": ""}
    except FileNotFoundError:
        return {"running": False, "state": "SC_NO_DISPONIBLE", "start_type": ""}
    except Exception as e:
        return {"running": False, "state": str(e)[:40], "start_type": ""}


def _check_ssl_cert(hostname: str) -> tuple:
    import ssl
    import datetime as _dt
    h = _validate_hostname(hostname)
    if not h:
        return False, "Hostname invalido para comprobar certificado"
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.socket(), server_hostname=h) as s:
            s.settimeout(5)
            s.connect((h, 443))
            cert = s.getpeercert()
        not_after_str = cert.get("notAfter", "")
        if not_after_str:
            import datetime as _dt2
            not_after = _dt2.datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z")
            days_left = (not_after - _dt2.datetime.utcnow()).days
            if days_left < 0:
                return False, "Certificado expirado hace " + str(-days_left) + " dias"
            elif days_left < 14:
                return True, "Certificado valido pero expira en " + str(days_left) + " dias RENOVAR"
            else:
                return True, "Certificado valido, expira en " + str(days_left) + " dias"
        return True, "Certificado valido"
    except ssl.SSLCertVerificationError as e:
        return False, "Certificado invalido: " + str(e)[:60]
    except ssl.SSLError as e:
        return False, "Error SSL: " + str(e)[:60]
    except OSError as e:
        return False, "Sin conexion a " + h + ":443"
    except Exception as e:
        return False, "Error: " + str(e)[:60]


def _check_port_latency(host: str, port: int, timeout: float = 2.0) -> Optional[int]:
    try:
        t0 = _time.time()
        with socket.create_connection((host, port), timeout=timeout):
            pass
        return max(1, int((_time.time() - t0) * 1000))
    except Exception:
        return None


def _check_url_latency(url: str, timeout: float = 3.0) -> Optional[int]:
    try:
        t0 = _time.time()
        req = urllib.request.Request(url, headers={"User-Agent": "MRD-TOOL/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(512)
        return max(1, int((_time.time() - t0) * 1000))
    except Exception:
        return None


def _check_dns(hostname: str) -> tuple:
    h = _validate_hostname(hostname)
    if not h:
        return False, "Hostname invalido"
    try:
        ips = socket.getaddrinfo(h, None, socket.AF_INET)
        if ips:
            ip = ips[0][4][0]
            return True, "Resuelve a " + ip
        return False, "Sin respuesta DNS"
    except socket.gaierror as e:
        return False, "Error DNS: " + str(e)[:60]
    except Exception as e:
        return False, str(e)[:60]


# ---- Estado completo del Named Tunnel ----

def get_tunnel_status(config: dict) -> dict:
    svc_name  = config.get("cloudflared_service", "cloudflared")
    exe_path  = config.get("cloudflared_exe", "cloudflared.exe")
    pub_url   = _validate_url(config.get("cf_public_url", "") or "")
    hostname  = _validate_hostname(config.get("cf_hostname", "") or "")
    domain    = _validate_hostname(config.get("cf_domain", "") or "")
    subdomain = re.sub(r"[^a-zA-Z0-9\-]", "", config.get("cf_subdomain", "") or "")[:63]

    svc     = get_service_status(svc_name)
    metrics = get_metrics()
    version = get_cloudflared_version(exe_path)

    if hostname:
        dns_ok, dns_detail = _check_dns(hostname)
    else:
        dns_ok, dns_detail = False, "Hostname no configurado"

    ms_local = _check_port_latency("localhost", int(config.get("cf_internal_port", 8000)))

    return {
        "connected":            svc["running"] and metrics["available"],
        "service_running":      svc["running"],
        "process_running":      svc["running"],
        "service_state":        svc["state"],
        "service_start_type":   svc.get("start_type", ""),
        "cloudflared_version":  version,
        "tunnel_name":          config.get("cf_tunnel_name") or "",
        "hostname":             hostname or "",
        "domain":               domain or "",
        "subdomain":            subdomain or "",
        "public_url":           pub_url or "",
        "dns_ok":               dns_ok,
        "dns_detail":           dns_detail,
        "metrics_available":    metrics["available"],
        "connections":          metrics.get("connections", 0),
        "local_server_ok":      ms_local is not None,
        "local_latency_ms":     ms_local,
        # Mantener ambos nombres: remote_access y clientes anteriores consumen
        # ``https``; la interfaz nueva utiliza ``has_https``.
        "https":                bool(pub_url and pub_url.startswith("https://")),
        "has_https":            bool(pub_url and pub_url.startswith("https://")),
        "checked_at":           datetime.now().isoformat(),
    }
