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
DB_PORT = os.getenv("DB_PORT", "1433")  # Puerto por defecto de SQL Server

if not all([DB_SERVER, DB_USER, DB_PASS]):
    raise ValueError("Faltan credenciales críticas en el entorno")

# 2. Configuración de Seguridad: Solo tu Dashboard puede hablar con la API
# Reemplaza la URL de abajo con la URL real de tu React cuando la subas (ej. Vercel)
ORIGENES_PERMITIDOS = [
    "http://localhost:5173",             # Para tus pruebas locales
    "http://localhost:3000",              # Puerto alternativo para React
    "https://ficha-cu.vercel.app",        # URL de producción de tu React
    "https://ficha-cu.vercel.app/*",      # Wildcard para todas las rutas
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

# 4. Motor de conexión para Linux usando pymssql
def get_db_engine(db_name: str):
    """
    Crea un motor de conexión usando pymssql (compatible con Linux/Alpine/Railway)
    """
    try:
        # Formato de conexión para pymssql:
        # mssql+pymssql://usuario:contraseña@servidor:puerto/base_datos
        connection_string = (
            f"mssql+pymssql://{DB_USER}:{DB_PASS}@{DB_SERVER}:{DB_PORT}/{db_name}"
        )
        
        # Parámetros específicos para Azure SQL
        connect_args = {
            "timeout": 30,  # Timeout de conexión en segundos
            "login_timeout": 30,
            "charset": "UTF-8",
            "tds_version": "7.4"  # Versión TDS compatible con Azure SQL
        }
        
        # Configuración del pool de conexiones
        engine = create_engine(
            connection_string,
            connect_args=connect_args,
            pool_pre_ping=True,  # Verifica conexión antes de usarla
            pool_recycle=1800,    # Recicla conexiones cada 30 minutos
            pool_size=5,          # Tamaño del pool
            max_overflow=10,      # Conexiones extras permitidas
            echo=False            # No mostrar logs SQL en producción
        )
        
        # Probar la conexión
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        print(f"Conexión exitosa a {db_name}")
        return engine
        
    except Exception as e:
        print(f"Error conectando a {db_name}: {str(e)}")
        return None

# 5. Fuentes de datos
FUENTES = {
    "ebitda": "Proyeccion_EBITDA",
    "indicadores": "Proyeccion_Indicadores",
    "poblacion": "Poblacion_Estudiantil",
    "estudiantes": "Proyeccion_Estudiantes",
    "desercion": "Desercion_Resumenes_CU"
}

# --- ENDPOINTS ---

# Endpoint de salud (útil para Railway)
@app.get("/health")
async def health_check():
    """Verifica que la API esté funcionando"""
    return {
        "status": "ok", 
        "database": DB_SERVER,
        "timestamp": pd.Timestamp.now().isoformat()
    }

@app.get("/api/observatorio/completo/{centro_id}")
async def get_all_data(centro_id: str):
    """Obtiene todos los datos de un centro específico"""
    resultados = {}
    errores = []
    
    for clave, db_nombre in FUENTES.items():
        try:
            engine = get_db_engine(db_nombre)
            if not engine:
                resultados[clave] = []
                errores.append(f"No se pudo conectar a {db_nombre}")
                continue
            
            # El uso de :id previene SQL Injection
            query = text("SELECT * FROM Datos WHERE centro_id = :id")
            df = pd.read_sql(query, engine, params={"id": centro_id})
            
            # Convertir columnas datetime a string para JSON
            for col in df.select_dtypes(include=['datetime64']).columns:
                df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
                
            resultados[clave] = df.to_dict(orient="records")
            
        except Exception as e:
            print(f"Error en {clave}: {str(e)}")
            resultados[clave] = []
            errores.append(f"Error en {clave}: {str(e)[:100]}")
    
    response = {
        "centro": centro_id, 
        "data": resultados,
        "timestamp": pd.Timestamp.now().isoformat()
    }
    
    if errores:
        response["warnings"] = errores
        
    return response

@app.get("/api/ebitda/{centro_id}")
async def get_ebitda(centro_id: str):
    """Datos de EBITDA para un centro específico"""
    try:
        engine = get_db_engine(FUENTES["ebitda"])
        if not engine: 
            raise HTTPException(status_code=503, detail="Base de datos no disponible")
        
        df = pd.read_sql(
            text("SELECT * FROM Datos WHERE centro_id = :id"), 
            engine, 
            params={"id": centro_id}
        )
        
        # Convertir datetime a string
        for col in df.select_dtypes(include=['datetime64']).columns:
            df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
            
        return df.to_dict(orient="records")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

@app.get("/api/indicadores/{centro_id}")
async def get_indicadores(centro_id: str):
    """Datos de indicadores para un centro específico."""
    try:
        engine = get_db_engine(FUENTES["indicadores"])
        if not engine:
            raise HTTPException(status_code=503, detail="Base de datos no disponible")
        
        df = pd.read_sql(
            text("SELECT * FROM Datos WHERE centro_id = :id"), 
            engine, 
            params={"id": centro_id}
        )
        
        for col in df.select_dtypes(include=['datetime64']).columns:
            df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
            
        return df.to_dict(orient="records")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

@app.get("/api/poblacion/{centro_id}")
async def get_poblacion(centro_id: str):
    """Datos de población estudiantil para un centro específico."""
    try:
        engine = get_db_engine(FUENTES["poblacion"])
        if not engine:
            raise HTTPException(status_code=503, detail="Base de datos no disponible")
        
        df = pd.read_sql(
            text("SELECT * FROM Datos WHERE centro_id = :id"), 
            engine, 
            params={"id": centro_id}
        )
        
        for col in df.select_dtypes(include=['datetime64']).columns:
            df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
            
        return df.to_dict(orient="records")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

@app.get("/api/estudiantes/{centro_id}")
async def get_estudiantes(centro_id: str):
    """Proyección de estudiantes para un centro específico."""
    try:
        engine = get_db_engine(FUENTES["estudiantes"])
        if not engine:
            raise HTTPException(status_code=503, detail="Base de datos no disponible")
        
        df = pd.read_sql(
            text("SELECT * FROM Datos WHERE centro_id = :id"), 
            engine, 
            params={"id": centro_id}
        )
        
        for col in df.select_dtypes(include=['datetime64']).columns:
            df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
            
        return df.to_dict(orient="records")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

@app.get("/api/desercion/{centro_id}")
async def get_desercion(centro_id: str):
    """Resumen de deserción para un centro específico."""
    try:
        engine = get_db_engine(FUENTES["desercion"])
        if not engine:
            raise HTTPException(status_code=503, detail="Base de datos no disponible")
        
        df = pd.read_sql(
            text("SELECT * FROM Datos WHERE centro_id = :id"), 
            engine, 
            params={"id": centro_id}
        )
        
        for col in df.select_dtypes(include=['datetime64']).columns:
            df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
            
        return df.to_dict(orient="records")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

# 10. Ejecución con Uvicorn - usando el puerto asignado por Railway
if __name__ == "__main__":
    import uvicorn
    
    # Obtener el puerto de la variable de entorno PORT (asignada por Railway)
    port = int(os.getenv("PORT", 8000))
    
    # En producción (Railway), no usar reload=True
    reload_mode = False if os.getenv("RAILWAY_ENVIRONMENT") else True
    
    print("=" * 50)
    print("Iniciando API con pymssql (Linux)")
    print("=" * 50)
    print(f"Servidor SQL: {DB_SERVER}:{DB_PORT}")
    print(f"Usuario: {DB_USER}")
    print(f"Bases de datos: {list(FUENTES.values())}")
    print(f"Orígenes permitidos: {ORIGENES_PERMITIDOS}")
    print(f" Puerto: {port}")
    print(f" Modo reload: {reload_mode}")
    print("=" * 50)
    
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=port, 
        reload=reload_mode,
        log_level="info"
    )