"""
database.py - Configuración de SQLAlchemy y conexión a SQLite real
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

# Ruta de la base de datos SQLite en disco.
# Por defecto, `backend/aldia.db` (el comportamiento de siempre). Se puede
# apuntar a otro archivo con ALDIA_DB, que es lo que se usa para levantar una
# instancia de pruebas sin tocar la base real del comercio.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("ALDIA_DB") or os.path.join(BASE_DIR, "aldia.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

# Crear motor con check_same_thread=False para SQLite
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False  # Poner True para ver los queries SQL en consola
)

# SessionFactory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base para los modelos
Base = declarative_base()

# Dependencia para obtener la sesión de DB
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
