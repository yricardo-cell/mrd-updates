"""
Importar proveedores a MRD Tool Control
Ejecutar desde C:\mrd_tool_control con:
  venv\Scripts\python.exe importar_proveedores.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal
from models import Proveedor

PROVEEDORES = [
    # (nombre, telefono, email, contacto, web, direccion, observaciones)
    (
        "ABLACAR",
        "91 672 91 11", "", "", "www.ablacar.com",
        "Avda. del Jarama, 12, 28823 Coslada (Madrid)",
        "Polipastos Yale. Reparación y venta de maquinaria de elevación. CIF: B81316614"
    ),
    (
        "SOGEISA",
        "91 628 18 00", "algete@sogeisa.e.telefonica.net", "", "www.sogeisa.com",
        "Camino de los Malatones s/n, Ctra. Fuente el Saz Km 18,900, 28110 Algete (Madrid)",
        "Material de encofrado Doka. Cubetas, abrazaderas, paneles, puntales."
    ),
    (
        "TURBOIBER",
        "91 352 75 60", "info@turboiber.com", "", "www.turboiber.com",
        "C/ Uranio, 18 (P.I. Aimayr), 28330 San Martín de la Vega (Madrid)",
        "Maquinillos eléctricos. Repuestos y reparaciones. Cables de acero. Taller. CIF: B83336040"
    ),
    (
        "ALIMAK",
        "", "", "", "www.alimakiberia.es",
        "Madrid (España)",
        "Montacargas Alimak STS 300. Piezas de repuesto (refs AT000XXXXX). Rent to Buy."
    ),
    (
        "DOBRAM",
        "91 628 02 12", "", "", "",
        "Calle Suero de Quiñones, 1, 28002 Madrid",
        "Venta de material metálico. Vigas HEA 700, tubos estructurales. CIF: B87239588"
    ),
    (
        "SORSA SA",
        "93 721 40 00", "", "", "www.sorsa.es",
        "C/ Ramón Berenguer 6, Pol. Ind. Can Vinyals, 08130 Santa Perpètua de Mogoda (Barcelona)",
        "Fleje para flejadoras (Madrid y Barcelona). Repuestos flejadora (pieza 47 y otros). Maquinaria flejadora. CIF: A58454976"
    ),
    (
        "FIBERCORD 2006 SLU",
        "96 675 86 19", "", "", "",
        "Calle Almendro Grupo, 36, 03360 Callosa de Segura (Alicante)",
        "Cuerdas trenzadas nylon 16mm. Mallas mosquitera. Mallas blancas 6x12. CIF: B54088521"
    ),
    (
        "JOYSA IRUDEK",
        "91 674 17 80", "", "", "www.vestuario-joysa.com",
        "P.º de las Flores, 16, 28820 Coslada (Madrid)",
        "EPI: Chalecos, absorbedores de caída, ganchos. Logos/serigrafía MRD. CIF: B81055048"
    ),
    (
        "COMERCIAL MD (AYERBE)",
        None, None, None, None, None,
        "Material general de ferretería y construcción."
    ),
    (
        "MOÑITA",
        "91 670 81 82", "", "", "www.toldosmonita.com",
        "C/ Austria, 15 (CT Coslada), 28821 Madrid",
        "Fabricación de lonas a medida. CIF: A28242808"
    ),
    (
        "PROLIANS METALCO",
        "91 681 34 24", "", "", "prolians.es",
        "C/ Morse, 16, Pol. Ind. San Marcos, 28906 Getafe (Madrid)",
        "EPI: Cascos amarillos de seguridad y material de protección."
    ),
    (
        "TOLDOS NORTE",
        "91 654 22 02", "", "", "www.toldoselnorte.net",
        "Plaza Rosa Chacel, 5, 28100 Alcobendas (Madrid)",
        "Fabricación de toldos y lonas. CIF: B80041361"
    ),
    (
        "UNION FERRETERA",
        "985 26 33 34", "clientes@unionferretera.com", "", "www.unionferretera.com",
        "Pol. de Silvota, C/ Peña Santa, Parcela 1, 33192 Llanera (Asturias)",
        "Ferretería general. Tornillería y suministros industriales."
    ),
    (
        "ENDUTEX",
        "93 893 64 67", "endutexiberica@endutexiberica.com", "", "www.endutexiberica.com",
        "P.I. Santa Magdalena, Rbla. dels Països C. 8, 08800 Vilanova i la Geltrú (Barcelona)",
        "Material textil industrial. Lonas y redes. CIF: A58673849"
    ),
    (
        "OCSA",
        None, None, None, None, None,
        "Suministros varios (facturas recurrentes)."
    ),
    (
        "SUMINISTROS SARGUI",
        "91 620 17 14", "", "", "www.suministrossargui.com",
        "Camino de la Carrera, 9, 28140 Fuente el Saz de Jarama (Madrid)",
        "Herramientas. Carracas y utillaje. CIF: B83030015"
    ),
    (
        "FROMM EMBALAJES",
        "93 568 99 10", "es@fromm.es", "", "www.fromm.es",
        "Pol. El Circuit, C/ del Rec Molinar, 14, 08160 Montmeló (Barcelona)",
        "Flejadoras y material de embalaje. CIF: A58943812"
    ),
]

def main():
    db = SessionLocal()
    existentes = {p.nombre.upper() for p in db.query(Proveedor).all()}
    añadidos = 0
    omitidos = 0

    for nombre, telefono, email, contacto, web, direccion, obs in PROVEEDORES:
        if nombre.upper() in existentes:
            print(f"  OMITIDO (ya existe): {nombre}")
            omitidos += 1
            continue
        p = Proveedor(
            nombre=nombre,
            telefono=telefono or None,
            email=email or None,
            contacto=contacto or None,
            web=web or None,
            direccion=direccion or None,
            observaciones=obs,
            activo=True,
        )
        db.add(p)
        añadidos += 1
        print(f"  + {nombre}")

    db.commit()
    db.close()
    print(f"\nListo: {añadidos} añadidos, {omitidos} omitidos.")

if __name__ == "__main__":
    main()