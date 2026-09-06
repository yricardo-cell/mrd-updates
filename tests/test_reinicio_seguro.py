"""2.7.40: reinicio seguro. Diagnostico del 06/09/2026: cada reinicio desde
/servicio moria en el execv de Windows por el espacio de "C:\\mrd tool" y el
bucle de SERVICIO_MRD.ps1 relanzaba uvicorn sin afinidad de CPU; dos de esos
relanzamientos se estrellaron en el arranque (nucleo defectuoso)."""
from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[1]


def test_execv_en_windows_entrecomilla_rutas_con_espacio():
    args = [r"C:\mrd tool\mrd-tool-control-2.5.0\venv\Scripts\uvicorn.exe", "main:app", "--host", "0.0.0.0"]
    assert main._exec_args_para_so(args, "nt") == [
        '"C:\\mrd tool\\mrd-tool-control-2.5.0\\venv\\Scripts\\uvicorn.exe"', "main:app", "--host", "0.0.0.0",
    ]
    assert main._exec_args_para_so(args, "posix") == args
    ya = ['"C:\\mrd tool\\x.exe"']
    assert main._exec_args_para_so(ya, "nt") == ya


def test_lanzador_fija_afinidad_y_supervisa_el_reinicio():
    ps1 = (ROOT / "SERVICIO_MRD.ps1").read_text(encoding="utf-8")
    assert "Set-AfinidadCpu" in ps1 and "ProcessorAffinity" in ps1 and "cpu_excluir.txt" in ps1
    assert '$env:MRD_SUPERVISADO = "1"' in ps1
    assert "$LASTEXITCODE -eq 3" in ps1 and "Start-Sleep -Seconds 1" in ps1
    assert ps1.index("Set-AfinidadCpu\n") < ps1.index("Iniciando uvicorn")


def test_main_aplica_afinidad_antes_de_las_importaciones_pesadas():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert src.index("_afinidad_temprana()") < src.index("from fastapi import")
    assert 'os.getenv("MRD_SUPERVISADO") == "1"' in src and "os._exit(3)" in src
    assert "os.execv(executable, _exec_args_para_so(args, os.name))" in src
