"""
Script de diagnóstico para los 500 en rutas IA.
Ejecutar desde el directorio del proyecto con el venv activo:
  cd "C:\mrd tool\mrd_tool_control"
  venv\Scripts\python.exe DIAGNOSTICO.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

print("=" * 60)
print("MRD TOOL CONTROL — Diagnóstico de rutas IA")
print("=" * 60)

# 1. Importar módulos
tests = {}

try:
    from database import SessionLocal, Base, engine
    print("[OK] database.py importado")
    tests['database'] = True
except Exception as e:
    print(f"[ERROR] database.py: {e}")
    tests['database'] = False

try:
    from models import (
        CanalNotificacion, NotificacionEnviada, TIPOS_CANAL, PRIORIDADES_CANAL,
        MantenimientoProgramado, TIPOS_MANTENIMIENTO,
        Aviso, Herramienta, Maquinaria
    )
    print("[OK] models.py importado")
    tests['models'] = True
except Exception as e:
    print(f"[ERROR] models.py: {e}")
    tests['models'] = False

try:
    import notificaciones as notif_engine
    print("[OK] notificaciones.py importado")
    tests['notificaciones'] = True
except Exception as e:
    print(f"[ERROR] notificaciones.py: {e}")
    tests['notificaciones'] = False

try:
    import anomalias as anom_engine
    print("[OK] anomalias.py importado")
    tests['anomalias'] = True
except Exception as e:
    print(f"[ERROR] anomalias.py: {e}")
    tests['anomalias'] = False

try:
    import mantenimiento as mant_engine
    print("[OK] mantenimiento.py importado")
    tests['mantenimiento'] = True
except Exception as e:
    print(f"[ERROR] mantenimiento.py: {e}")
    tests['mantenimiento'] = False

print()
print("─" * 60)
print("Verificando tablas en la base de datos...")
print("─" * 60)

if tests.get('database'):
    db = SessionLocal()
    try:
        # Tablas nuevas
        for modelo, nombre in [
            (CanalNotificacion, "canales_notificacion"),
            (NotificacionEnviada, "notificaciones_enviadas"),
            (MantenimientoProgramado, "mantenimientos_programados"),
            (Aviso, "avisos"),
            (Herramienta, "herramientas"),
            (Maquinaria, "maquinaria"),
        ]:
            try:
                cnt = db.query(modelo).count()
                print(f"[OK] tabla '{nombre}': {cnt} registros")
            except Exception as e:
                print(f"[ERROR] tabla '{nombre}': {e}")
    finally:
        db.close()

print()
print("─" * 60)
print("Simulando ruta /notificaciones...")
print("─" * 60)
if tests.get('database') and tests.get('models'):
    db = SessionLocal()
    try:
        canales = db.query(CanalNotificacion).order_by(CanalNotificacion.id).all()
        log = db.query(NotificacionEnviada).order_by(NotificacionEnviada.fecha_envio.desc()).limit(50).all()
        print(f"[OK] canales={len(canales)}, log={len(log)}")
    except Exception as e:
        import traceback
        print(f"[ERROR] /notificaciones query: {e}")
        traceback.print_exc()
    finally:
        db.close()

print()
print("─" * 60)
print("Simulando ruta /anomalias...")
print("─" * 60)
if tests.get('anomalias') and tests.get('database'):
    db = SessionLocal()
    try:
        resultado = anom_engine.ejecutar_deteccion_completa(db)
        print(f"[OK] detección completa: {resultado['resumen']}")
    except Exception as e:
        import traceback
        print(f"[ERROR] /anomalias: {e}")
        traceback.print_exc()
    finally:
        db.close()

print()
print("─" * 60)
print("Simulando ruta /mantenimiento...")
print("─" * 60)
if tests.get('mantenimiento') and tests.get('database'):
    db = SessionLocal()
    try:
        plan = mant_engine.generar_plan_mantenimiento(db)
        print(f"[OK] plan generado: {plan['resumen']}")
    except Exception as e:
        import traceback
        print(f"[ERROR] /mantenimiento: {e}")
        traceback.print_exc()
    finally:
        db.close()

print()
print("=" * 60)
print("Diagnóstico completado.")
print("=" * 60)
