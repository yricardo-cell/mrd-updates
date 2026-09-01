"""
Descarga Bootstrap y Bootstrap Icons localmente para evitar dependencia de CDN.
Ejecutar una sola vez.
"""
import urllib.request
import os

BASE = os.path.dirname(os.path.abspath(__file__))
CSS_DIR = os.path.join(BASE, "static", "css")
JS_DIR = os.path.join(BASE, "static", "js")
FONTS_DIR = os.path.join(BASE, "static", "fonts")

os.makedirs(CSS_DIR, exist_ok=True)
os.makedirs(JS_DIR, exist_ok=True)
os.makedirs(FONTS_DIR, exist_ok=True)

ASSETS = [
    ("https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css",
     os.path.join(CSS_DIR, "bootstrap.min.css")),
    ("https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js",
     os.path.join(JS_DIR, "bootstrap.bundle.min.js")),
    ("https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css",
     os.path.join(CSS_DIR, "bootstrap-icons.min.css")),
    ("https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff2",
     os.path.join(FONTS_DIR, "bootstrap-icons.woff2")),
    ("https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff",
     os.path.join(FONTS_DIR, "bootstrap-icons.woff")),
    ("https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js",
     os.path.join(JS_DIR, "chart.umd.min.js")),
]

for url, dest in ASSETS:
    name = os.path.basename(dest)
    if os.path.exists(dest) and os.path.getsize(dest) > 1000:
        print(f"  [ya existe] {name}")
        continue
    try:
        print(f"  Descargando {name}...", end=" ", flush=True)
        urllib.request.urlretrieve(url, dest)
        size = os.path.getsize(dest)
        print(f"OK ({size//1024} KB)")
    except Exception as e:
        print(f"ERROR: {e}")

print("\nListo. Reinicia el servidor para aplicar.")
input("Pulsa Enter para cerrar...")
