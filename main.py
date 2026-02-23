import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
import pandas as pd
from dotenv import load_dotenv

# 1. Cargar variables de entorno
load_dotenv()

DB_SERVER = os.getenv("DB_SERVER")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")

if not all([DB_SERVER, DB_USER, DB_PASS]):
    raise ValueError("Faltan credenciales críticas en el entorno")

# 2. Configuración de Seguridad: Solo tu Dashboard puede hablar con la API
# Reemplaza la URL de abajo con la URL real de tu React cuando la subas (ej. Vercel)
ORIGENES_PERMITIDOS = [
    "http://localhost:5173",             # Para tus pruebas locales
    "https://ficha-cu.vercel.app"    # URL de producción de tu React
]

# 3. Crear aplicación FastAPI OCULTA
# Desactivamos docs_url y openapi_url para que nadie vea la estructura de la API
app = FastAPI(
    docs_url=None, 
    redoc_url=None, 
    openapi_url=None 
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGENES_PERMITIDOS, 
    allow_credentials=True,
    allow_methods=["GET"], # Solo lectura
    allow_headers=["*"],
)

# 4. Motor de conexión mejorado
def get_db_engine(db_name: str):
    try:
        # Añadimos parámetros de seguridad para SQL Server
        connection_string = (
            f"mssql+pyodbc://{DB_USER}:{DB_PASS}@{DB_SERVER}/{db_name}"
            "?driver=ODBC+Driver+17+for+SQL+Server"
            "&Encrypt=yes&TrustServerCertificate=no"
            "&ConnectionTimeout=30"  # Timeout de conexión
        )
        # pool_pre_ping asegura que la conexión no esté "muerta" antes de usarla
        return create_engine(connection_string, pool_pre_ping=True, pool_recycle=3600)
    except Exception as e:
        print(f"Error conectando a {db_name}: {str(e)}")
        return None

FUENTES = {
    "ebitda": "Proyeccion_EBITDA",
    "indicadores": "Proyeccion_Indicadores",
    "poblacion": "Poblacion_Estudiantil",
    "estudiantes": "Proyeccion_Estudiantes",
    "desercion": "Desercion_Resumenes_CU"
}

# --- ENDPOINTS ---

# Endpoint de salud (opcional, útil para Railway)
@app.get("/health")
async def health_check():
    return {"status": "ok"}

# Elimina el endpoint raíz "/" por seguridad 

@app.get("/api/observatorio/completo/{centro_id}")
async def get_all_data(centro_id: str):
    resultados = {}
    for clave, db_nombre in FUENTES.items():
        engine = get_db_engine(db_nombre)
        if engine:
            try:
                # El uso de :id previene SQL Injection
                query = text("SELECT * FROM Datos WHERE centro_id = :id")
                df = pd.read_sql(query, engine, params={"id": centro_id})
                resultados[clave] = df.to_dict(orient="records")
            except Exception as e:
                print(f"Error en {clave}: {str(e)}")
                resultados[clave] = []
        else:
            resultados[clave] = []

    return {"centro": centro_id, "data": resultados}

# Los endpoints individuales se mantienen pero están protegidos por el CORS
@app.get("/api/ebitda/{centro_id}")
async def get_ebitda(centro_id: str):
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

# 10. Ejecución con Uvicorn - usando el puerto asignado por Railway
if __name__ == "__main__":
    import uvicorn
    
    # Obtener el puerto de la variable de entorno PORT (asignada por Railway)
    # Si no existe, usar 8000 como fallback para desarrollo local
    port = int(os.getenv("PORT", 8000))
    
    # En producción (Railway), no usar reload=True
    reload_mode = False if os.getenv("RAILWAY_ENVIRONMENT") else True
    
    print(f"Iniciando servidor en puerto: {port}")
    print(f"Conectando a servidor SQL: {DB_SERVER}")
    print(f"Orígenes permitidos: {ORIGENES_PERMITIDOS}")
    
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=port, 
        reload=reload_mode
    )