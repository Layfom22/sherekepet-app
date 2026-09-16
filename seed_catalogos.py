"""
Script Seeder para inicializar catálogos de Especies y Razas en SherekePet.
Incluye: Canino (Perro), Felino (Gato), Ave, Roedor, Reptil, Exótico.
Con más de 55 razas de caninos y 25 de felinos de forma idempotente.
"""
from sqlalchemy.orm import Session
from app.database import SessionLocal, init_db
from app.clinic.models import Especie, Raza


DATOS_CATALOGO = [
    {
        "especie": "Canino (Perro)",
        "razas": [
            "Mestizo / Criollo",
            "Labrador Retriever",
            "Golden Retriever",
            "Pastor Alemán",
            "Bulldog Francés",
            "Bulldog Inglés",
            "Poodle (Caniche)",
            "Chihuahua",
            "Pug",
            "Beagle",
            "Rottweiler",
            "Dachshund (Salchicha)",
            "Schnauzer Miniatura",
            "Schnauzer Estándar",
            "Yorkshire Terrier",
            "Shih Tzu",
            "Boxer",
            "Siberian Husky",
            "Doberman Pinscher",
            "Gran Danés",
            "Pomerania",
            "Border Collie",
            "Cocker Spaniel",
            "Bichón Frisé",
            "Bichón Maltés",
            "Boston Terrier",
            "San Bernardo",
            "Bull Terrier",
            "Pitbull Terrier Americano",
            "Staffordshire Bull Terrier",
            "Akita Inu",
            "Shiba Inu",
            "Chow Chow",
            "Jack Russell Terrier",
            "Dálmata",
            "Samoyedo",
            "Alaskan Malamute",
            "Mastín Napolitano",
            "Mastín Tibetano",
            "Pastor Belga Malinois",
            "Pastor Australiano",
            "Basset Hound",
            "Weimaraner",
            "Vizsla",
            "Pointer Inglés",
            "Setter Irlandés",
            "Shar Pei",
            "Lhasa Apso",
            "Papillón",
            "Galgo Español",
            "Galgo Afgano",
            "Whippet",
            "Terranova",
            "Perro Sin Pelo del Perú (Viringo)",
            "Cane Corso",
            "Bernés de la Montaña"
        ]
    },
    {
        "especie": "Felino (Gato)",
        "razas": [
            "Común Europeo / Mestizo",
            "Siamés",
            "Persa",
            "Maine Coon",
            "Bengala",
            "Sphynx (Esfinge)",
            "Ragdoll",
            "British Shorthair",
            "American Shorthair",
            "Ruso Azul",
            "Angora Turco",
            "Bosque de Noruega",
            "Birmano",
            "Abisinio",
            "Scottish Fold",
            "Devon Rex",
            "Cornish Rex",
            "Chartreux",
            "Somalí",
            "Bombay",
            "Oriental de Pelo Corto",
            "Himalayo",
            "Burmés",
            "Manx",
            "Tonkinés"
        ]
    },
    {
        "especie": "Ave",
        "razas": [
            "Perico Australiano",
            "Canario",
            "Ninfa / Cacotillo",
            "Agapornis (Inseparable)",
            "Loro Cabeza Amarilla",
            "Guacamayo",
            "Cacatúa",
            "Perico Esmeralda",
            "Jilguero",
            "Cotorra Argentina"
        ]
    },
    {
        "especie": "Roedor",
        "razas": [
            "Hámster Sirio / Dorado",
            "Hámster Ruso",
            "Hámster Roborovski",
            "Cobayo / Cuy Peruano",
            "Cobayo Abisinio",
            "Chinchilla",
            "Conejo Enano / Toy",
            "Conejo Belier",
            "Conejo Cabeza de León",
            "Rata Doméstica",
            "Jerbo"
        ]
    },
    {
        "especie": "Reptil",
        "razas": [
            "Tortuga de Orejas Rojas",
            "Tortuga Rusa",
            "Gecko Leopardo",
            "Dragón Barbudo",
            "Iguana Verde",
            "Camaleón del Yemen",
            "Serpiente del Maíz",
            "Pitón Bola"
        ]
    },
    {
        "especie": "Exótico",
        "razas": [
            "Hurón Doméstico",
            "Erizo Pigmeo Africano",
            "Petauro del Azúcar",
            "Minipig"
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
