import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
import pandas as pd
from dotenv import load_dotenv

# 1. Cargar variables de entorno (local: .env / producción: Azure App Settings)
load_dotenv()

# 2. Verificar que las credenciales necesarias estén presentes
DB_SERVER = os.getenv("DB_SERVER")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")

if not all([DB_SERVER, DB_USER, DB_PASS]):
    raise ValueError("Faltan credenciales de base de datos en las variables de entorno")

# 3. Crear la aplicación FastAPI
app = FastAPI(
    title="API Observatorio Uniminuto - MultiDB",
    description="Consulta consolidada de múltiples bases de datos del observatorio.",
    version="1.0.0"
)

# 4. Configurar CORS (permitir cualquier origen en desarrollo; ajustar en producción)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 5. Función para conectar dinámicamente a cualquier base de datos
def get_db_engine(db_name: str):
    """Crea y retorna un engine de SQLAlchemy para la base de datos especificada."""
    try:
        connection_string = (
            f"mssql+pyodbc://{DB_USER}:{DB_PASS}@{DB_SERVER}/{db_name}"
            "?driver=ODBC+Driver+17+for+SQL+Server"
        )
        return create_engine(connection_string, pool_pre_ping=True)
    except Exception as e:
        print(f"Error conectando a {db_name}: {e}")
        return None

# 6. Definir las fuentes de datos (nombre lógico -> nombre real de la BD)
FUENTES = {
    "ebitda": "Proyeccion_EBITDA",
    "indicadores": "Proyeccion_Indicadores",
    "poblacion": "Poblacion_Estudiantil",
    "estudiantes": "Proyeccion_Estudiantes",
    "desercion": "Desercion_Resumenes_CU"
}

# 7. Endpoint raíz (verificación de que la API está activa)
@app.get("/")
async def root():
    return {
        "message": "API Observatorio Uniminuto funcionando",
        "endpoints": [
            "/api/observatorio/completo/{centro_id}",
            "/api/ebitda/{centro_id}",
            "/api/indicadores/{centro_id}",
            "/api/poblacion/{centro_id}",
            "/api/estudiantes/{centro_id}",
            "/api/desercion/{centro_id}"
        ]
    }

# 8. Endpoint principal que consolida todas las bases
@app.get("/api/observatorio/completo/{centro_id}")
async def get_all_data(centro_id: str):
    """
    Retorna datos de todas las fuentes (ebitda, indicadores, población, estudiantes, deserción)
    para el centro_id proporcionado.
    """
    resultados = {}
    for clave, db_nombre in FUENTES.items():
        engine = get_db_engine(db_nombre)
        if engine:
            try:
                query = text("SELECT * FROM Datos WHERE centro_id = :id")
                df = pd.read_sql(query, engine, params={"id": centro_id})
                resultados[clave] = df.to_dict(orient="records")
            except Exception as e:
                # Si falla la consulta, se registra el error y se retorna lista vacía
                print(f"Error consultando {db_nombre} para centro_id {centro_id}: {e}")
                resultados[clave] = []
        else:
            resultados[clave] = []

    return {
        "centro": centro_id,
        "data": resultados
    }

# 9. Endpoints individuales (uno por cada fuente)
@app.get("/api/ebitda/{centro_id}")
async def get_ebitda(centro_id: str):
    """Datos de EBITDA para un centro específico."""
    engine = get_db_engine(FUENTES["ebitda"])
    if not engine:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    df = pd.read_sql(text("SELECT * FROM Datos WHERE centro_id = :id"), engine, params={"id": centro_id})
    return df.to_dict(orient="records")

@app.get("/api/indicadores/{centro_id}")
async def get_indicadores(centro_id: str):
    """Datos de indicadores para un centro específico."""
    engine = get_db_engine(FUENTES["indicadores"])
    if not engine:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    df = pd.read_sql(text("SELECT * FROM Datos WHERE centro_id = :id"), engine, params={"id": centro_id})
    return df.to_dict(orient="records")

@app.get("/api/poblacion/{centro_id}")
async def get_poblacion(centro_id: str):
    """Datos de población estudiantil para un centro específico."""
    engine = get_db_engine(FUENTES["poblacion"])
    if not engine:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    df = pd.read_sql(text("SELECT * FROM Datos WHERE centro_id = :id"), engine, params={"id": centro_id})
    return df.to_dict(orient="records")

@app.get("/api/estudiantes/{centro_id}")
async def get_estudiantes(centro_id: str):
    """Proyección de estudiantes para un centro específico."""
    engine = get_db_engine(FUENTES["estudiantes"])
    if not engine:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    df = pd.read_sql(text("SELECT * FROM Datos WHERE centro_id = :id"), engine, params={"id": centro_id})
    return df.to_dict(orient="records")

@app.get("/api/desercion/{centro_id}")
async def get_desercion(centro_id: str):
    """Resumen de deserción para un centro específico."""
    engine = get_db_engine(FUENTES["desercion"])
    if not engine:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    df = pd.read_sql(text("SELECT * FROM Datos WHERE centro_id = :id"), engine, params={"id": centro_id})
    return df.to_dict(orient="records")

# 10. Ejecución con Uvicorn (para desarrollo local)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)