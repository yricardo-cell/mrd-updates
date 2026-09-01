# -*- coding: utf-8 -*-
"""
MRD TOOL CONTROL - Mejora v2.1.4
  1) Codigos de barras en Maquinaria (etiquetas + escaner)
  2) Separacion de los dos depositos de combustible

Seguro: hace copia de seguridad y verifica con ast.parse() antes de guardar.
Uso:   venv/Scripts/python.exe MEJORA_v214.py
"""
import ast
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent.resolve()
MAIN = BASE / "main.py"
OK, ERR, WARN = "[OK]  ", "[ERROR]", "[AVISO]"
cambios = []


def log(tag, msg):
    print(f" {tag} {msg}")


def backup_archivo(p: Path) -> Path:
    dest = p.with_suffix(p.suffix + ".bak_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(p, dest)
    return dest


# ══════════════════════════════════════════════════════════════════
#  PARTE 1 - Base de datos: asignar codigo de barras a las maquinas
# ══════════════════════════════════════════════════════════════════
def localizar_db() -> Path:
    for cand in (BASE / "data" / "mrd_tool.db", BASE / "mrd_tool.db"):
        if cand.exists():
            return cand
    return None


def paso1_codigos_maquinaria():
    print("\n--- 1. Asignando codigos de barras a la maquinaria ---")
    db_path = localizar_db()
    if not db_path:
        log(ERR, "No encuentro la base de datos (data/mrd_tool.db)")
        return False

    log(OK, f"Base de datos: {db_path}")
    shutil.copy2(db_path, db_path.with_suffix(
        ".db.bak_" + datetime.now().strftime("%Y%m%d_%H%M%S")))
    log(OK, "Copia de seguridad de la base de datos creada")

    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    try:
        cur.execute("SELECT id, nombre, codigo_barras FROM maquinaria ORDER BY id")
        filas = cur.fetchall()
    except sqlite3.Error as e:
        log(ERR, f"No se pudo leer la tabla maquinaria: {e}")
        con.close()
        return False

    if not filas:
        log(WARN, "No hay maquinas registradas")
        con.close()
        return True

    # Mayor correlativo ya usado con el formato MRD-MAQ-XXXX
    maxn = 0
    for _, _, cb in filas:
        if cb:
            m = re.match(r"^MRD-MAQ-(\d+)$", str(cb).strip())
            if m:
                maxn = max(maxn, int(m.group(1)))

    asignados = 0
    for mid, nombre, cb in filas:
        if cb and str(cb).strip():
            continue
        maxn += 1
        nuevo = f"MRD-MAQ-{maxn:04d}"
        cur.execute("UPDATE maquinaria SET codigo_barras=? WHERE id=?", (nuevo, mid))
        log(OK, f"{nuevo}  ->  {nombre}")
        asignados += 1

    con.commit()
    con.close()

    if asignados:
        log(OK, f"{asignados} maquina(s) con codigo nuevo")
        cambios.append(f"{asignados} maquinas con codigo de barras asignado")
    else:
        log(OK, "Todas las maquinas ya tenian codigo")
    return True


# ══════════════════════════════════════════════════════════════════
#  PARTE 2 - main.py
# ══════════════════════════════════════════════════════════════════
def paso2_parchear_main():
    print("\n--- 2. Aplicando mejoras en main.py ---")
    if not MAIN.exists():
        log(ERR, "No encuentro main.py")
        return False

    src = MAIN.read_text(encoding="utf-8")
    original = src

    # --- 2.1 Guardar codigo_barras / codigo_interno al EDITAR maquina ---
    ancla = """    m.matricula = form.get("matricula") or None
    m.num_serie = form.get("num_serie") or None
    m.estado = form.get("estado") or m.estado"""
    nuevo = """    m.matricula = form.get("matricula") or None
    m.num_serie = form.get("num_serie") or None
    _cb = (form.get("codigo_barras") or "").strip()
    if _cb:
        m.codigo_barras = _cb
    _ci = (form.get("codigo_interno") or "").strip()
    if _ci:
        m.codigo_interno = _ci
    m.estado = form.get("estado") or m.estado"""
    if "_cb = (form.get(\"codigo_barras\")" in src:
        log(OK, "Editar maquina: ya guardaba los codigos")
    elif ancla in src:
        src = src.replace(ancla, nuevo, 1)
        log(OK, "Editar maquina: ahora guarda codigo de barras e interno")
        cambios.append("El formulario de editar maquina guarda los codigos")
    else:
        log(WARN, "No localizo el bloque de editar maquina (se omite)")

    # --- 2.2 Autogenerar codigo al CREAR maquina ---
    ancla2 = """    m = Maquinaria(
        nombre=nombre.strip(),"""
    nuevo2 = """    if not codigo_barras.strip():
        _ultimo = db.query(Maquinaria).filter(
            Maquinaria.codigo_barras.like("MRD-MAQ-%")
        ).order_by(Maquinaria.codigo_barras.desc()).first()
        _n = 0
        if _ultimo and _ultimo.codigo_barras:
            try:
                _n = int(str(_ultimo.codigo_barras).split("-")[-1])
            except ValueError:
                _n = 0
        codigo_barras = "MRD-MAQ-%04d" % (_n + 1)
    m = Maquinaria(
        nombre=nombre.strip(),"""
    if 'codigo_barras = "MRD-MAQ-%04d"' in src:
        log(OK, "Crear maquina: ya autogeneraba el codigo")
    elif ancla2 in src:
        src = src.replace(ancla2, nuevo2, 1)
        log(OK, "Crear maquina: genera codigo automatico MRD-MAQ-XXXX")
        cambios.append("Las maquinas nuevas reciben codigo automatico")
    else:
        log(WARN, "No localizo el bloque de crear maquina (se omite)")

    # --- 2.3 Stock del surtidor por tipo de combustible ---
    ancla3 = '''def _stock_surtidor(db) -> float:
    """Calcula el stock actual del depósito: compras - repostajes (todo el histórico)."""
    todos = db.query(RepostajeSurtidor).all()
    compras    = sum(r.litros for r in todos if r.tipo_registro == "compra")
    dispensado = sum(r.litros for r in todos if r.tipo_registro == "repostaje")
    return round(compras - dispensado, 2)'''

    nuevo3 = '''# Depositos de la nave: nombre normalizado -> etiqueta y capacidad en litros
DEPOSITOS_COMBUSTIBLE = {
    "gasoleo_a": {"label": "Gasóleo A (carretera)", "capacidad": 1000},
    "gasoleo_b": {"label": "Gasóleo B (maquinaria)", "capacidad": 3000},
}


def _norm_combustible(valor) -> str:
    """Normaliza el texto libre del combustible a una clave de deposito."""
    t = (valor or "").strip().lower()
    t = (t.replace("ó", "o").replace("á", "a").replace("é", "e")
          .replace("í", "i").replace("ú", "u"))
    if "b" in t.replace("gasoleo", "").replace("gasoil", "").replace(" ", ""):
        return "gasoleo_b"
    if t in ("gasoleo b", "gasoil b", "b", "rojo", "agricola"):
        return "gasoleo_b"
    return "gasoleo_a"


def _stock_surtidor(db, tipo: str = None) -> float:
    """Stock del deposito. Si se indica tipo, solo el de ese combustible."""
    todos = db.query(RepostajeSurtidor).all()
    if tipo:
        todos = [r for r in todos if _norm_combustible(r.tipo_combustible) == tipo]
    compras    = sum(r.litros for r in todos if r.tipo_registro == "compra")
    dispensado = sum(r.litros for r in todos if r.tipo_registro == "repostaje")
    return round(compras - dispensado, 2)


def _stocks_por_deposito(db) -> list:
    """Lista con el estado de cada deposito por separado."""
    salida = []
    for clave, info in DEPOSITOS_COMBUSTIBLE.items():
        litros = _stock_surtidor(db, clave)
        cap = info["capacidad"]
        salida.append({
            "clave": clave,
            "label": info["label"],
            "litros": litros,
            "capacidad": cap,
            "porcentaje": round(min(100, max(0, litros / cap * 100)), 1) if cap else 0,
            "bajo": litros < cap * 0.15,
        })
    return salida'''

    if "_stocks_por_deposito" in src:
        log(OK, "Surtidor: el stock por deposito ya estaba")
    elif ancla3 in src:
        src = src.replace(ancla3, nuevo3, 1)
        log(OK, "Surtidor: stock calculado por deposito (Gasoleo A y B)")
        cambios.append("El surtidor separa los dos depositos")

        # Pasar los depositos a la plantilla
        a4 = '        "stock_actual": stock_actual,'
        n4 = ('        "stock_actual": stock_actual,\n'
              '        "depositos": _stocks_por_deposito(db),\n'
              '        "DEPOSITOS_COMBUSTIBLE": DEPOSITOS_COMBUSTIBLE,')
        if a4 in src and '"depositos": _stocks_por_deposito(db)' not in src:
            src = src.replace(a4, n4, 1)
            log(OK, "Surtidor: los depositos llegan a la pantalla")
    else:
        log(WARN, "No localizo _stock_surtidor (se omite)")

    if src == original:
        log(WARN, "main.py no necesitaba cambios")
        return True

    # --- Verificacion obligatoria antes de guardar ---
    try:
        ast.parse(src)
        log(OK, "Verificacion de sintaxis correcta (ast.parse)")
    except SyntaxError as e:
        log(ERR, f"El resultado tendria un error de sintaxis en la linea {e.lineno}: {e.msg}")
        log(ERR, "NO se ha modificado nada. main.py sigue intacto.")
        return False

    bak = backup_archivo(MAIN)
    log(OK, f"Copia de seguridad: {bak.name}")
    MAIN.write_text(src, encoding="utf-8")
    log(OK, "main.py actualizado")
    return True


def main():
    print("=" * 62)
    print("  MRD TOOL CONTROL - Mejora v2.1.4")
    print("=" * 62)

    ok1 = paso1_codigos_maquinaria()
    ok2 = paso2_parchear_main()

    print("\n" + "=" * 62)
    if ok1 and ok2:
        print("  RESULTADO: mejora aplicada correctamente")
        for c in cambios:
            print("   - " + c)
        print("\n  AHORA:")
        print("   1) Reinicia el servidor (o el ordenador)")
        print("   2) Vuelve a imprimir las etiquetas de las maquinas")
        print("   3) Escanealas: ya deben reconocerse")
    else:
        print("  RESULTADO: revisa los mensajes de arriba")
    print("=" * 62)
    input("\nPulsa Enter para salir...")


if __name__ == "__main__":
    main()
