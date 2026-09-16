"""
Script Seeder para inicializar catálogos de Especies y Razas en SherekePet.
Inserta 'Canino (Perro)' y 'Felino (Gato)' con razas de ejemplo de forma idempotente.
"""
from sqlalchemy.orm import Session
from app.database import SessionLocal, init_db
from app.clinic.models import Especie, Raza


DATOS_CATALOGO = [
    {
        "especie": "Canino (Perro)",
        "razas": [
            "Labrador Retriever",
            "Bulldog Francés",
            "Golden Retriever",
            "Mestizo / Criollo",
            "Pastor Alemán",
            "Poodle"
        ]
    },
    {
        "especie": "Felino (Gato)",
        "razas": [
            "Siamés",
            "Persa",
            "Bengala",
            "Común Europeo / Mestizo",
            "Maine Coon",
            "Angora"
        ]
    }
]


def seed_catalogos(db: Session) -> None:
    """Inserta las especies y razas de catálogo si aún no existen."""
    for item in DATOS_CATALOGO:
        nombre_especie = item["especie"]
        especie_db = db.query(Especie).filter(Especie.nombre == nombre_especie).first()

        if not especie_db:
            especie_db = Especie(nombre=nombre_especie)
            db.add(especie_db)
            db.flush()
            print(f"[OK] Especie agregada: {nombre_especie}")

        for nombre_raza in item["razas"]:
            raza_db = db.query(Raza).filter(
                Raza.especie_id == especie_db.id,
                Raza.nombre == nombre_raza
            ).first()

            if not raza_db:
                raza_db = Raza(especie_id=especie_db.id, nombre=nombre_raza)
                db.add(raza_db)
                print(f"  + Raza agregada: {nombre_raza} ({nombre_especie})")

    db.commit()
    print("[OK] Seeder de catalogos completado exitosamente.")


if __name__ == "__main__":
    init_db()
    db = SessionLocal()
    try:
        seed_catalogos(db)
    finally:
        db.close()
