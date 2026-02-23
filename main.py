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
DB_NAME = "db360"  # Base de datos única

if not all([DB_SERVER, DB_USER, DB_PASS]):
    raise ValueError("Faltan credenciales críticas en el entorno")

# 2. Configuración de Seguridad: Solo tu Dashboard puede hablar con la API
ORIGENES_PERMITIDOS = [
    "http://localhost:5173",             # Para tus pruebas locales
    "http://localhost:3000",              # Puerto alternativo para React
    "https://ficha-cu.vercel.app",        # URL de producción de tu React
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

# 4. Variable para almacenar el engine en caché (conexión perezosa)
_engine_cache = None

def get_db_engine():
    """
    Crea un motor de conexión para db360 SOLO cuando se necesita (lazy loading)
    y lo cachea para reutilizarlo en peticiones posteriores
    """
    global _engine_cache
    
    # Si ya tenemos un engine en caché, lo retornamos
    if _engine_cache is not None:
        engine = _engine_cache
        # Verificamos rápidamente si la conexión sigue viva
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return engine
        except:
            # Si la conexión está muerta, eliminamos del caché y creamos una nueva
            print("Reconectando a db360 (conexión anterior muerta)")
            _engine_cache = None
    
    # Si no hay engine en caché, creamos uno nuevo
    try:
        print("Conectando a base de datos: db360")
        
        # Formato de conexión para pymssql
        connection_string = (
            f"mssql+pymssql://{DB_USER}:{DB_PASS}@{DB_SERVER}:{DB_PORT}/{DB_NAME}"
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
        _engine_cache = engine
        print("Engine creado para db360 (conexión perezosa)")
        return engine
        
    except Exception as e:
        print(f"Error creando engine para db360: {str(e)}")
        return None

# 5. Tablas disponibles en db360
TABLAS = {
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
        "database": f"{DB_SERVER}/{DB_NAME}",
        "timestamp": pd.Timestamp.now().isoformat()
    }

@app.get("/api/tablas")
async def get_tablas_disponibles():
    """Devuelve la lista de tablas disponibles en db360"""
    return {
        "base_datos": DB_NAME,
        "tablas": list(TABLAS.keys()),
        "tablas_nombres": list(TABLAS.values())
    }

@app.get("/api/observatorio/completo/{centro_id}")
async def get_all_data(centro_id: str):
    """Obtiene todos los datos de un centro desde todas las tablas de db360"""
    resultados = {}
    errores = []
    conexiones_exitosas = 0
    
    # Obtener el engine una sola vez para todas las consultas
    engine = get_db_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="No se pudo conectar a la base de datos db360")
    
    for clave, nombre_tabla in TABLAS.items():
        try:
            print(f"Consultando tabla {nombre_tabla} para centro {centro_id}")
            
            # Consulta específica para cada tabla
            query = text(f"SELECT * FROM {nombre_tabla} WHERE centro_id = :id")
            df = pd.read_sql(query, engine, params={"id": centro_id})
            
            # Convertir datetime a string
            for col in df.select_dtypes(include=['datetime64']).columns:
                df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
                
            resultados[clave] = df.to_dict(orient="records")
            conexiones_exitosas += 1 if not df.empty else 0
            
        except Exception as e:
            print(f"Error en tabla {nombre_tabla}: {str(e)}")
            resultados[clave] = []
            errores.append(f"Error en {clave}: {str(e)[:100]}")
    
    response = {
        "centro": centro_id, 
        "base_datos": DB_NAME,
        "data": resultados,
        "tablas_con_datos": conexiones_exitosas,
        "total_tablas": len(TABLAS),
        "timestamp": pd.Timestamp.now().isoformat()
    }
    
    if errores:
        response["warnings"] = errores
        
    return response

@app.get("/api/ebitda/{centro_id}")
async def get_ebitda(centro_id: str):
    """Datos de EBITDA desde tabla Proyeccion_EBITDA en db360"""
    try:
        engine = get_db_engine()
        if not engine: 
            raise HTTPException(status_code=503, detail="Base de datos no disponible")
        
        query = text(f"SELECT * FROM {TABLAS['ebitda']} WHERE centro_id = :id")
        df = pd.read_sql(query, engine, params={"id": centro_id})
        
        for col in df.select_dtypes(include=['datetime64']).columns:
            df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
            
        return {
            "centro": centro_id,
            "tabla": TABLAS['ebitda'],
            "data": df.to_dict(orient="records")
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

@app.get("/api/indicadores/{centro_id}")
async def get_indicadores(centro_id: str):
    """Datos de indicadores desde tabla Proyeccion_Indicadores en db360"""
    try:
        engine = get_db_engine()
        if not engine:
            raise HTTPException(status_code=503, detail="Base de datos no disponible")
        
        query = text(f"SELECT * FROM {TABLAS['indicadores']} WHERE centro_id = :id")
        df = pd.read_sql(query, engine, params={"id": centro_id})
        
        for col in df.select_dtypes(include=['datetime64']).columns:
            df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
            
        return {
            "centro": centro_id,
            "tabla": TABLAS['indicadores'],
            "data": df.to_dict(orient="records")
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

@app.get("/api/poblacion/{centro_id}")
async def get_poblacion(centro_id: str):
    """Datos de población desde tabla Poblacion_Estudiantil en db360"""
    try:
        engine = get_db_engine()
        if not engine:
            raise HTTPException(status_code=503, detail="Base de datos no disponible")
        
        query = text(f"SELECT * FROM {TABLAS['poblacion']} WHERE centro_id = :id")
        df = pd.read_sql(query, engine, params={"id": centro_id})
        
        for col in df.select_dtypes(include=['datetime64']).columns:
            df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
            
        return {
            "centro": centro_id,
            "tabla": TABLAS['poblacion'],
            "data": df.to_dict(orient="records")
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

@app.get("/api/estudiantes/{centro_id}")
async def get_estudiantes(centro_id: str):
    """Proyección estudiantes desde tabla Proyeccion_Estudiantes en db360"""
    try:
        engine = get_db_engine()
        if not engine:
            raise HTTPException(status_code=503, detail="Base de datos no disponible")
        
        query = text(f"SELECT * FROM {TABLAS['estudiantes']} WHERE centro_id = :id")
        df = pd.read_sql(query, engine, params={"id": centro_id})
        
        for col in df.select_dtypes(include=['datetime64']).columns:
            df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
            
        return {
            "centro": centro_id,
            "tabla": TABLAS['estudiantes'],
            "data": df.to_dict(orient="records")
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

@app.get("/api/desercion/{centro_id}")
async def get_desercion(centro_id: str):
    """Resumen deserción desde tabla Desercion_Resumenes_CU en db360"""
    try:
        engine = get_db_engine()
        if not engine:
            raise HTTPException(status_code=503, detail="Base de datos no disponible")
        
        query = text(f"SELECT * FROM {TABLAS['desercion']} WHERE centro_id = :id")
        df = pd.read_sql(query, engine, params={"id": centro_id})
        
        for col in df.select_dtypes(include=['datetime64']).columns:
            df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
            
        return {
            "centro": centro_id,
            "tabla": TABLAS['desercion'],
            "data": df.to_dict(orient="records")
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

# Endpoint para consulta personalizada (con precaución)
@app.get("/api/consulta/{tabla}/{centro_id}")
async def consulta_tabla(tabla: str, centro_id: str):
    """Endpoint genérico para consultar cualquier tabla por centro_id"""
    if tabla not in TABLAS:
        raise HTTPException(status_code=404, detail=f"Tabla {tabla} no encontrada")
    
    try:
        engine = get_db_engine()
        if not engine:
            raise HTTPException(status_code=503, detail="Base de datos no disponible")
        
        nombre_tabla = TABLAS[tabla]
        query = text(f"SELECT * FROM {nombre_tabla} WHERE centro_id = :id")
        df = pd.read_sql(query, engine, params={"id": centro_id})
        
        for col in df.select_dtypes(include=['datetime64']).columns:
            df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
            
        return {
            "centro": centro_id,
            "tabla": nombre_tabla,
            "data": df.to_dict(orient="records")
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

# Endpoint para ver estado del caché de conexión
@app.get("/admin/connection-status")
async def connection_status():
    """Muestra el estado de la conexión en caché (solo administración)"""
    return {
        "conexion_activa": _engine_cache is not None,
        "base_datos": DB_NAME,
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
    print(f"Base de datos: {DB_NAME}")
    print(f"Tablas disponibles: {len(TABLAS)}")
    print(f"Usuario: {DB_USER}")
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