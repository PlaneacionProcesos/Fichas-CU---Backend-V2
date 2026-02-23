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
ORIGENES_PERMITIDOS = [
    "http://localhost:5173",             # Para tus pruebas locales
    "http://localhost:3000",              # Puerto alternativo para React
    "https://ficha-cu.vercel.app",        # URL de producción de tu React
    "https://ficha-cu.vercel.app/*",      # Wildcard para todas las rutas
]

# 3. Crear aplicación FastAPI OCULTA
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

# 4. Diccionario para almacenar engines en caché (conexión perezosa)
_engine_cache = {}

def get_db_engine(db_name: str):
    """
    Crea un motor de conexión SOLO cuando se necesita (lazy loading)
    y lo cachea para reutilizarlo en peticiones posteriores
    """
    global _engine_cache
    
    # Si ya tenemos un engine en caché para esta BD, lo retornamos
    if db_name in _engine_cache:
        engine = _engine_cache[db_name]
        # Verificamos rápidamente si la conexión sigue viva
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return engine
        except:
            # Si la conexión está muerta, eliminamos del caché y creamos una nueva
            print(f"Reconectando a {db_name} (conexión anterior muerta)")
            del _engine_cache[db_name]
    
    # Si no hay engine en caché, creamos uno nuevo
    try:
        print(f"Conectando a base de datos: {db_name}")
        
        # Formato de conexión para pymssql
        connection_string = (
            f"mssql+pymssql://{DB_USER}:{DB_PASS}@{DB_SERVER}:{DB_PORT}/{db_name}"
        )
        
        # Parámetros específicos para Azure SQL
        connect_args = {
            "timeout": 30,           # Timeout de conexión
            "login_timeout": 30,      # Timeout de login
            "charset": "UTF-8",
            "tds_version": "7.4"      # Versión TDS para Azure SQL
        }
        
        # Crear engine SIN probar la conexión inmediatamente
        engine = create_engine(
            connection_string,
            connect_args=connect_args,
            pool_pre_ping=True,        # Verifica conexión antes de usarla
            pool_recycle=1800,         # Recicla cada 30 minutos
            pool_size=5,                # Tamaño del pool
            max_overflow=10,            # Conexiones extras
            echo=False                  # Sin logs SQL
        )
        
        # Guardamos en caché
        _engine_cache[db_name] = engine
        print(f"Engine creado para {db_name} (conexión perezosa)")
        return engine
        
    except Exception as e:
        print(f"Error creando engine para {db_name}: {str(e)}")
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

@app.get("/health")
async def health_check():
    """Endpoint de salud - NO hace conexión a BD"""
    return {
        "status": "ok",
        "message": "API funcionando (conexiones bajo demanda)",
        "database": DB_SERVER,
        "timestamp": pd.Timestamp.now().isoformat()
    }

@app.get("/api/observatorio/completo/{centro_id}")
async def get_all_data(centro_id: str):
    """Obtiene todos los datos de un centro - conecta bajo demanda"""
    resultados = {}
    errores = []
    conexiones_exitosas = 0
    
    for clave, db_nombre in FUENTES.items():
        try:
            # La conexión se crea SOLO cuando se necesita
            engine = get_db_engine(db_nombre)
            if not engine:
                resultados[clave] = []
                errores.append(f"No se pudo conectar a {db_nombre}")
                continue
            
            # Ejecutar consulta
            query = text("SELECT * FROM Datos WHERE centro_id = :id")
            df = pd.read_sql(query, engine, params={"id": centro_id})
            
            # Convertir datetime a string
            for col in df.select_dtypes(include=['datetime64']).columns:
                df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
                
            resultados[clave] = df.to_dict(orient="records")
            conexiones_exitosas += 1
            
        except Exception as e:
            print(f"Error en {clave}: {str(e)}")
            resultados[clave] = []
            errores.append(f"Error en {clave}: {str(e)[:100]}")
    
    response = {
        "centro": centro_id, 
        "data": resultados,
        "conexiones_exitosas": conexiones_exitosas,
        "total_bases": len(FUENTES),
        "timestamp": pd.Timestamp.now().isoformat()
    }
    
    if errores:
        response["warnings"] = errores
        
    return response

@app.get("/api/ebitda/{centro_id}")
async def get_ebitda(centro_id: str):
    """Datos de EBITDA - conecta bajo demanda"""
    try:
        engine = get_db_engine(FUENTES["ebitda"])
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

@app.get("/api/indicadores/{centro_id}")
async def get_indicadores(centro_id: str):
    """Datos de indicadores - conecta bajo demanda"""
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
    """Datos de población - conecta bajo demanda"""
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
    """Proyección estudiantes - conecta bajo demanda"""
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
    """Resumen deserción - conecta bajo demanda"""
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

# Endpoint para ver estado del caché de conexiones (útil para debugging)
@app.get("/admin/connection-status")
async def connection_status():
    """Muestra el estado de las conexiones en caché (solo administración)"""
    return {
        "conexiones_cache": list(_engine_cache.keys()),
        "total_conexiones": len(_engine_cache),
        "servidor": DB_SERVER
    }

# 10. Ejecución con Uvicorn
if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    reload_mode = False if os.getenv("RAILWAY_ENVIRONMENT") else True
    
    print("=" * 60)
    print("API INICIADA - MODO CONEXION BAJO DEMANDA")
    print("=" * 60)
    print(f"Servidor SQL: {DB_SERVER}:{DB_PORT}")
    print(f"Usuario: {DB_USER}")
    print(f"Bases disponibles: {len(FUENTES)}")
    print(f"Origenes permitidos: {len(ORIGENES_PERMITIDOS)}")
    print(f"Puerto: {port}")
    print(f"Modo reload: {reload_mode}")
    print(f"Las conexiones a BD se crearan SOLO cuando se soliciten")
    print("=" * 60)
    
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=port, 
        reload=reload_mode,
        log_level="info"
    )