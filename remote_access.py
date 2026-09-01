"""
MRD TOOL CONTROL — Sistema de detección de acceso remoto multi-proveedor
Soporta: Cloudflare Tunnel, ngrok, Tailscale, Red local

No bloquea la UI: usa caché con refresco en background.
"""
import json
import os
import re
import socket
import subprocess
import threading
import time as _time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional

# Inicializado por init()
_CONFIG_FILE: Optional[Path] = None
_BASE_DIR: Optional[Path] = None

# Caché
_cache_lock = threading.Lock()
_cached_status: Optional[dict] = None
_cache_time: Optional[datetime] = None
_refresh_running = False

CREATE_NO_WINDOW = 0x08000000  # Windows: no abrir ventana CMD


# ─── Inicialización ─────────────────────────────────────────────────────────

def init(base_dir: Path):
    global _CONFIG_FILE, _BASE_DIR
    _BASE_DIR = base_dir
    _CONFIG_FILE = base_dir / "data" / "remote_access_config.json"


# ─── Configuración ──────────────────────────────────────────────────────────

def _default_config() -> dict:
    return {
        "manual_url": "",
        "preferred_provider": "auto",
        "port": 8000,
        "auto_detect": True,
        "qr_public": True,
        "check_https": True,
        "check_interval": 60,
        "allow_restart": False,
        "cloudflared_service": "cloudflared",
        "cloudflared_exe": "cloudflared.exe",
        "cloudflared_log_file": "data/cloudflared.log",
        "tailscale_url": "",
        "hidden_providers": [],
        # Sprint 5.4 — Named Tunnel
        "cf_tunnel_name":  "",
        "cf_tunnel_id":    "",
        "cf_hostname":     "",
        "cf_domain":       "",
        "cf_subdomain":    "",
        "cf_public_url":   "",
        "cf_config_file":  "",
        "cf_force_https":  True,
        "cf_internal_port": 8000,
    }


def load_config() -> dict:
    if _CONFIG_FILE and _CONFIG_FILE.exists():
        try:
            raw = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
            cfg = _default_config()
            cfg.update(raw)
            return cfg
        except Exception:
            pass
    return _default_config()


def save_config(updates: dict) -> bool:
    """Guarda la configuración. Solo acepta claves conocidas y valida URLs."""
    if not _CONFIG_FILE:
        return False
    cfg = load_config()
    allowed_keys = set(_default_config().keys())
    # Claves CF adicionales permitidas
    _cf_str_keys = {"cf_tunnel_name","cf_tunnel_id","cf_hostname","cf_domain",
                    "cf_subdomain","cf_public_url","cf_config_file"}
    _cf_bool_keys = {"cf_force_https"}
    _cf_int_keys  = {"cf_internal_port"}
    for k, v in updates.items():
        if k not in allowed_keys:
            continue
        # Validar URLs
        if k in ("manual_url", "tailscale_url", "cf_public_url") and v:
            v = _validate_url(str(v)) or ""
        # Claves CF: hostname/domain/subdomain
        if k in ("cf_hostname", "cf_domain") and v:
            import re as _re
            v = _re.sub(r"[^a-zA-Z0-9\.\-]", "", str(v))[:253]
        if k == "cf_subdomain" and v:
            import re as _re
            v = _re.sub(r"[^a-zA-Z0-9\-]", "", str(v))[:63]
        if k in ("cf_tunnel_name", "cf_tunnel_id") and v:
            import re as _re
            v = _re.sub(r"[^a-zA-Z0-9\-_\.]", "", str(v))[:64]
        if k == "cf_config_file" and v:
            v = str(v).strip()[:512]
        # CF booleanos e int
        if k in _cf_bool_keys:
            v = bool(v)
        if k in _cf_int_keys:
            try: v = max(1, min(int(v), 65535))
            except: continue
        # Validar rutas de archivo (no ejecutar, solo almacenar)
        if k in ("cloudflared_exe", "cloudflared_log_file") and v:
            v = str(v).strip()
        # Validar strings simples
        if k in ("cloudflared_service", "preferred_provider") and v:
            v = re.sub(r"[^a-zA-Z0-9_\-\. ]", "", str(v))[:64]
        # Booleanos
        if k in ("auto_detect", "qr_public", "check_https", "allow_restart"):
            v = bool(v)
        # Enteros
        if k in ("port", "check_interval"):
            try:
                v = max(1, min(int(v), 65535 if k == "port" else 3600))
            except (ValueError, TypeError):
                continue
        # Listas
        if k == "hidden_providers" and isinstance(v, list):
            v = [str(x) for x in v if str(x) in ("cloudflare", "ngrok", "tailscale")]
        cfg[k] = v

    try:
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:
        return False


# ─── Utilidades ─────────────────────────────────────────────────────────────

def _validate_url(url: str) -> Optional[str]:
    """Valida URL: solo http/https, sin inyecciones."""
    if not url:
        return None
    url = url.strip().rstrip("/")
    if not re.match(r'^https?://', url):
        return None
    if re.search(r'[\s;<>&\'"]', url):
        return None
    if len(url) > 512:
        return None
    return url


def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _fetch_json(url: str, timeout: int = 3) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MRD-TOOL/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _measure_latency(url: str, timeout: float = 2.0) -> Optional[int]:
    """Mide latencia en ms haciendo una petición GET. Devuelve None si falla."""
    try:
        t0 = _time.time()
        req = urllib.request.Request(url, headers={"User-Agent": "MRD-TOOL/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(512)
        return max(1, int((_time.time() - t0) * 1000))
    except Exception:
        return None


def run_diagnostics(port: int = 8000) -> dict:
    """
    Ejecuta diagnósticos completos: servidor local, puerto, cloudflare,
    URL pública, HTTPS, ruta /scan, validez del QR.
    Usa timeouts cortos para no bloquear.
    """
    status = get_status_cached(max_age=60)
    cfg = load_config()

    diag = {
        "local_server": False,
        "port_open": False,
        "cloudflare_service": False,
        "public_url_reachable": False,
        "https_active": bool(status.get("https")),
        "scan_route": False,
        "qr_valid": bool(status.get("scan_url")),
        "response_ms": None,
        "public_response_ms": None,
        "errors": [],
    }

    # 1. Servidor local
    ms = _measure_latency(f"http://localhost:{port}/", timeout=2)
    diag["local_server"] = ms is not None
    diag["port_open"] = ms is not None
    diag["response_ms"] = ms

    # 2. Ruta /scan local
    if diag["local_server"]:
        ms_scan = _measure_latency(f"http://localhost:{port}/scan", timeout=2)
        diag["scan_route"] = ms_scan is not None

    # 3. Servicio/proceso Cloudflare
    cf_proc = _is_process_running("cloudflared.exe")
    cf_svc = _is_service_running(cfg.get("cloudflared_service", "cloudflared"))
    diag["cloudflare_service"] = cf_proc or cf_svc

    # 4. URL pública accesible (con timeout más largo)
    pub = status.get("public_url")
    if pub:
        val = _validate_url(pub)
        if val:
            try:
                ms_pub = _measure_latency(val, timeout=5)
                diag["public_url_reachable"] = ms_pub is not None
                diag["public_response_ms"] = ms_pub
            except Exception as e:
                diag["errors"].append(str(e)[:80])

    # 5. HTTPS activo si public_url empieza por https://
    diag["https_active"] = bool(pub and pub.startswith("https://"))

    # 6. QR apunta a URL correcta
    diag["qr_valid"] = bool(status.get("scan_url"))

    return diag


def get_server_stats() -> dict:
    """
    Estadísticas del servidor: CPU, RAM, tiempo activo.
    Requiere psutil; si no está instalado, devuelve campos vacíos.
    """
    stats: dict = {
        "pid": os.getpid(),
        "cpu_percent": None,
        "ram_percent": None,
        "ram_used_mb": None,
        "ram_total_mb": None,
        "uptime_s": None,
        "uptime_str": "—",
        "psutil_available": False,
    }
    try:
        import psutil  # type: ignore
        stats["psutil_available"] = True
        stats["cpu_percent"] = round(psutil.cpu_percent(interval=0.2), 1)
        mem = psutil.virtual_memory()
        stats["ram_percent"] = round(mem.percent, 1)
        stats["ram_used_mb"] = int(mem.used / 1024 / 1024)
        stats["ram_total_mb"] = int(mem.total / 1024 / 1024)
        proc = psutil.Process()
        uptime_s = int(_time.time() - proc.create_time())
        stats["uptime_s"] = uptime_s
        h, rem = divmod(uptime_s, 3600)
        m, s = divmod(rem, 60)
        stats["uptime_str"] = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"
    except ImportError:
        pass
    except Exception:
        pass
    return stats


def _is_process_running(name: str) -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
            capture_output=True, text=True, timeout=2,
            creationflags=CREATE_NO_WINDOW,
        )
        return name.lower() in result.stdout.lower()
    except Exception:
        return False


def _is_service_running(service_name: str) -> bool:
    if not service_name or not service_name.strip():
        return False
    svc = re.sub(r"[^a-zA-Z0-9_\-]", "", service_name)[:50]
    if not svc:
        return False
    try:
        result = subprocess.run(
            ["sc", "query", svc],
            capture_output=True, text=True, timeout=2,
            creationflags=CREATE_NO_WINDOW,
        )
        return "RUNNING" in result.stdout
    except Exception:
        return False


# ─── Detectores por proveedor ───────────────────────────────────────────────

def _detect_cloudflare(cfg: dict) -> Optional[dict]:
    cf_process = _is_process_running("cloudflared.exe")
    cf_service = _is_service_running(cfg.get("cloudflared_service", ""))
    is_running = cf_process or cf_service

    # Prioridad 1: Named Tunnel con PUBLIC_URL configurada (Sprint 5.4)
    named_url = _validate_url(cfg.get("cf_public_url", ""))
    if named_url:
        return {
            "name": "cloudflare",
            "label": "Cloudflare Named Tunnel",
            "active": True,
            "url": named_url,
            "type": "named_tunnel",
            "source": "named_config",
            "tunnel_name": cfg.get("cf_tunnel_name", "") or None,
            "hostname": cfg.get("cf_hostname", "") or None,
            "process_running": cf_process,
            "service_running": cf_service,
        }

    # Prioridad 2: URL manual configurada
    manual_url = _validate_url(cfg.get("manual_url", ""))
    if manual_url:
        is_quick = "trycloudflare.com" in manual_url
        return {
            "name": "cloudflare",
            "label": "Cloudflare Tunnel",
            "active": True,
            "url": manual_url,
            "type": "quick_tunnel" if is_quick else "named_tunnel",
            "source": "manual_config",
            "process_running": cf_process,
            "service_running": cf_service,
        }

    # Prioridad 2: cloudflared activo + log file con URL
    if is_running:
        log_file = cfg.get("cloudflared_log_file", "")
        if log_file:
            try:
                content = Path(log_file).read_text(encoding="utf-8", errors="ignore")
                match = re.search(r'https://[\w\-]+\.trycloudflare\.com', content)
                if match:
                    url = _validate_url(match.group(0))
                    if url:
                        return {
                            "name": "cloudflare",
                            "label": "Cloudflare Quick Tunnel",
                            "active": True,
                            "url": url,
                            "type": "quick_tunnel",
                            "source": "log_file",
                            "process_running": cf_process,
                            "service_running": cf_service,
                        }
            except Exception:
                pass

        # cloudflared activo pero URL no disponible
        return {
            "name": "cloudflare",
            "label": "Cloudflare Tunnel",
            "active": True,
            "url": None,
            "type": "unknown",
            "source": "process_detected",
            "process_running": cf_process,
            "service_running": cf_service,
            "note": "cloudflared activo — configura la URL manualmente",
        }

    return None


def _detect_ngrok(port: int) -> Optional[dict]:
    data = _fetch_json("http://localhost:4040/api/tunnels", timeout=1)
    if not data:
        return None
    tunnels = data.get("tunnels", [])
    # Preferir HTTPS
    for t in tunnels:
        if t.get("proto") == "https":
            url = _validate_url(t.get("public_url", ""))
            if url:
                return {
                    "name": "ngrok",
                    "label": "ngrok",
                    "active": True,
                    "url": url,
                    "type": "https_tunnel",
                    "source": "ngrok_api",
                    "process_running": _is_process_running("ngrok.exe"),
                }
    # Fallback: cualquier https
    for t in tunnels:
        url = _validate_url(t.get("public_url", ""))
        if url and url.startswith("https://"):
            return {
                "name": "ngrok",
                "label": "ngrok",
                "active": True,
                "url": url,
                "type": "https_tunnel",
                "source": "ngrok_api",
                "process_running": True,
            }
    return None


def _detect_tailscale(cfg: dict, port: int) -> Optional[dict]:
    # URL manual Tailscale
    manual_ts = _validate_url(cfg.get("tailscale_url", ""))
    if manual_ts:
        return {
            "name": "tailscale",
            "label": "Tailscale",
            "active": True,
            "url": manual_ts,
            "type": "vpn_tunnel",
            "source": "manual_config",
        }

    # Auto-detectar via CLI
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True, text=True, timeout=2,
            creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            ips = data.get("Self", {}).get("TailscaleIPs", [])
            if ips:
                ts_ip = ips[0]
                return {
                    "name": "tailscale",
                    "label": "Tailscale",
                    "active": True,
                    "url": f"http://{ts_ip}:{port}",
                    "type": "vpn_tunnel",
                    "source": "tailscale_cli",
                }
    except Exception:
        pass
    return None


# ─── Detección completa ──────────────────────────────────────────────────────

def detect_all(cfg: dict = None) -> dict:
    """
    Detecta todos los proveedores y devuelve estado completo.
    Timeout máximo total ~9s (3 detectores × 3s).
    """
    if cfg is None:
        cfg = load_config()

    port = int(cfg.get("port", 8000))
    ip = _get_local_ip()
    local_url = f"http://{ip}:{port}"
    errors = []
    providers = []
    hidden = cfg.get("hidden_providers", [])

    # Ejecutar detección de cada proveedor
    def run_detector(name, fn, *args):
        try:
            return fn(*args)
        except Exception as e:
            errors.append(f"{name}: {str(e)[:100]}")
            return None

    if "cloudflare" not in hidden:
        r = run_detector("cloudflare", _detect_cloudflare, cfg)
        if r:
            providers.append(r)

    if "ngrok" not in hidden:
        r = run_detector("ngrok", _detect_ngrok, port)
        if r:
            providers.append(r)

    if "tailscale" not in hidden:
        r = run_detector("tailscale", _detect_tailscale, cfg, port)
        if r:
            providers.append(r)

    # Red local siempre disponible
    providers.append({
        "name": "local",
        "label": "Red local",
        "active": True,
        "url": local_url,
        "type": "local_network",
        "source": "auto",
    })

    # Seleccionar proveedor principal
    priority_order = ["cloudflare", "ngrok", "tailscale", "local"]
    pref = cfg.get("preferred_provider", "auto")
    primary = None

    if pref != "auto":
        for p in providers:
            if p["name"] == pref and p.get("url"):
                primary = p
                break

    if not primary:
        for name in priority_order:
            for p in providers:
                if p["name"] == name and p.get("url"):
                    primary = p
                    break
            if primary:
                break

    # Estado general y mensaje
    has_public = any(p["name"] in ("cloudflare", "ngrok") and p.get("url") for p in providers)
    has_tailscale = any(p["name"] == "tailscale" and p.get("url") for p in providers)

    if has_public:
        status = "online"
        pname = (primary or {}).get("name", "")
        if pname == "cloudflare":
            message = "Acceso público activo mediante Cloudflare Tunnel."
        else:
            message = "Acceso público activo mediante ngrok."
    elif has_tailscale:
        status = "private"
        message = "Acceso privado disponible mediante Tailscale."
    else:
        status = "local_only"
        message = "Acceso disponible únicamente en la red local."

    public_url = primary.get("url") if primary else None
    # Sprint 5.8: MRD_PUBLIC_URL y MRD_SCAN_URL tienen máxima prioridad
    _env_public_url = os.getenv("MRD_PUBLIC_URL", os.getenv("PUBLIC_URL", "")).rstrip("/")
    _env_scan_url   = os.getenv("MRD_SCAN_URL", "")
    if _env_public_url:
        public_url = _env_public_url
    has_https = bool(public_url and public_url.startswith("https://"))
    # Prioridad: MRD_SCAN_URL > PUBLIC_URL/scan > local_url/scan
    if _env_scan_url:
        scan_url = _env_scan_url
    elif public_url:
        scan_url = public_url.rstrip("/") + "/scan"
    else:
        # Sin URL pública: usar IP local (más útil en red que localhost)
        scan_url = local_url + "/scan"

    # Latencia del servidor local (sin bloquear demasiado)
    latency_ms = _measure_latency(f"http://localhost:{port}/", timeout=1)

    # Tipo de túnel y servicio del proveedor principal
    primary_type = (primary or {}).get("type", "local_network")
    service_active = False
    if primary:
        pname = primary.get("name", "")
        if pname in ("cloudflare",):
            service_active = bool(primary.get("process_running") or primary.get("service_running"))
        elif pname == "ngrok":
            service_active = bool(primary.get("process_running"))
        elif pname in ("tailscale", "local"):
            service_active = True

    # Diagnósticos rápidos (sin probar URL pública para no bloquear)
    cf_provider = next((p for p in providers if p["name"] == "cloudflare"), None)
    basic_diag = {
        "local_server": latency_ms is not None,
        "port_open": latency_ms is not None,
        "cloudflare_service": bool(cf_provider and (
            cf_provider.get("process_running") or cf_provider.get("service_running")
        )) if cf_provider else False,
        "public_url": bool(public_url),
        "https_active": has_https,
        "scan_route": bool(scan_url),
        "qr_valid": bool(scan_url),
    }

    return {
        "status": status,
        "message": message,
        "primary_provider": primary["name"] if primary else "local",
        "public_url": public_url,
        "scan_url": scan_url,
        "local_url": local_url,
        "internal_url": f"http://localhost:{port}",
        "https": has_https,
        "latency_ms": latency_ms,
        "tunnel_type": primary_type,
        "service_active": service_active,
        "ip": ip,
        "port": port,
        "providers": providers,
        "checked_at": datetime.now().isoformat(),
        "diagnostics": basic_diag,
        "errors": errors,
    }


# ─── Caché con refresco en background ────────────────────────────────────────

def get_status_cached(max_age: int = 30) -> dict:
    """
    Devuelve estado cacheado. Si expiró, refresca en background y devuelve
    el último resultado conocido (no bloquea la petición HTTP).
    Un solo thread de refresco a la vez — sin race condition.
    """
    global _cached_status, _cache_time, _refresh_running

    with _cache_lock:
        now = datetime.now()
        age = (now - _cache_time).total_seconds() if _cache_time else 9999
        has_cache = _cached_status is not None

        # Cache válida → devolver directamente
        if has_cache and age < max_age:
            return dict(_cached_status)

        # ¿Hay que refrescar? Solo si no hay un refresh ya en marcha
        if _refresh_running:
            # Ya hay un refresh en curso → devolver caché o fallback sin lanzar otro thread
            return dict(_cached_status) if _cached_status else _fallback_status()

        # Marcar como en proceso ANTES de liberar el lock
        _refresh_running = True
        first_time = not has_cache

    if first_time:
        # Primera llamada (startup background thread): detectar sincrónicamente
        try:
            result = detect_all()
        except Exception:
            result = _fallback_status()
        with _cache_lock:
            _cached_status = result
            _cache_time = datetime.now()
            _refresh_running = False
        return dict(result)
    else:
        # Caché expirada: refrescar en background, devolver último resultado conocido
        def _bg_refresh():
            global _cached_status, _cache_time, _refresh_running
            try:
                result = detect_all()
            except Exception:
                result = _fallback_status()
            with _cache_lock:
                _cached_status = result
                _cache_time = datetime.now()
                _refresh_running = False

        threading.Thread(target=_bg_refresh, daemon=True).start()
        with _cache_lock:
            return dict(_cached_status) if _cached_status else _fallback_status()


def invalidate_cache():
    """Fuerza refresco en la próxima llamada."""
    global _cache_time
    with _cache_lock:
        _cache_time = None


def _fallback_status() -> dict:
    ip = _get_local_ip()
    port = 8000
    local_url = f"http://{ip}:{port}"
    return {
        "status": "local_only",
        "message": "Acceso disponible únicamente en la red local.",
        "primary_provider": "local",
        "public_url": None,
        "scan_url": local_url + "/scan",
        "local_url": local_url,
        "internal_url": f"http://localhost:{port}",
        "https": False,
        "ip": ip,
        "port": port,
        "providers": [{"name": "local", "label": "Red local", "active": True,
                        "url": local_url, "type": "local_network", "source": "auto"}],
        "latency_ms": None,
        "tunnel_type": None,
        "service_active": None,
        "qr": None,
        "checked_at": __import__("datetime").datetime.now().isoformat(),
        "diagnostics": {},
    }
