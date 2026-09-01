# MRD TOOL CONTROL — Scripts de Herramientas

## Estructura

### development/
Scripts de uso durante el desarrollo. **No usar en producción.**
- `reset_admin.py` — Resetear contraseña del administrador
- `hacer_admin.py` — Promover usuario a administrador
- `get_access_info.py` — Obtener información de acceso
- `descargar_assets.py` — Descargar assets estáticos

### maintenance/
Scripts de mantenimiento y diagnóstico.
- `fix_admin_ghost.py` — Corregir usuarios fantasma
- `fix_usuarios.py` — Correcciones de BD de usuarios
- `ver_usuarios.py` — Listar usuarios y roles
- `DIAGNOSTICO.py` — Diagnóstico del sistema
- `fix_config.py` — Corrección de configuración
- `anomalias.py` — Análisis de anomalías

### obsolete/
Scripts deprecados. No usar.

## Ejecución

```powershell
# Desde el directorio raíz del proyecto
python tools/development/reset_admin.py
python tools/maintenance/DIAGNOSTICO.py
```

**NUNCA ejecutar scripts de desarrollo directamente en producción sin revisar el código.**
