import socket
import urllib.request
import json
import subprocess
import sys

# IP local
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
except:
    ip = "No disponible"

# URL ngrok
url_https = None
try:
    with urllib.request.urlopen("http://localhost:4040/api/tunnels", timeout=3) as r:
        data = json.loads(r.read())
    for t in data.get("tunnels", []):
        if t.get("proto") == "https":
            url_https = t["public_url"]
            break
except:
    pass

print("=" * 50)
print(f"  IP LOCAL  : {ip}")
print(f"  URL LOCAL : http://{ip}:8000/scan")
if url_https:
    print(f"  NGROK HTTPS: {url_https}/scan  ← USAR ESTE EN IPHONE")
else:
    print("  NGROK: No detectado")
print("=" * 50)

# Guardar en archivo
with open("access_info.txt", "w") as f:
    f.write(f"IP_LOCAL={ip}\n")
    f.write(f"URL_LOCAL=http://{ip}:8000/scan\n")
    if url_https:
        f.write(f"URL_HTTPS={url_https}/scan\n")
    else:
        f.write("URL_HTTPS=No disponible\n")

print("Guardado en access_info.txt")
