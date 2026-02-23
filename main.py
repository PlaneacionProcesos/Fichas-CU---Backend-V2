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
DB_TABLA = "dbo.Poblacion Estudiantil"  # Tabla específica con esquema

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

# --- ENDPOINTS ---

@app.get("/health")
async def health_check():
    """Endpoint de salud - NO hace conexión a BD"""
    return {
        "status": "ok",
        "message": "API funcionando (conexiones bajo demanda)",
        "database": f"{DB_SERVER}/{DB_NAME}",
        "tabla": DB_TABLA,
        "timestamp": pd.Timestamp.now().isoformat()
    }

@app.get("/api/poblacion/{centro_id}")
async def get_poblacion_estudiantil(centro_id: str):
    """
    Obtiene datos de población estudiantil para un centro específico
    desde la tabla dbo.Poblacion_Estudiantil en db360
    """
    try:
        # Obtener conexión a la base de datos
        engine = get_db_engine()
        if not engine:
            raise HTTPException(
                status_code=503, 
                detail="No se pudo conectar a la base de datos db360"
            )
        
        print(f"Consultando {DB_TABLA} para centro {centro_id}")
        
        # Consulta específica para la tabla Poblacion_Estudiantil
        # El uso de :id previene SQL Injection
        query = text(f"""
            SELECT * FROM {DB_TABLA} 
            WHERE centro_id = :id 
            ORDER BY periodo DESC
        """)
        
        df = pd.read_sql(query, engine, params={"id": centro_id})
        
        # Convertir columnas datetime a string para JSON
        for col in df.select_dtypes(include=['datetime64']).columns:
            df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # Preparar respuesta
        response = {
            "centro": centro_id,
            "base_datos": DB_NAME,
            "tabla": DB_TABLA,
            "total_registros": len(df),
            "data": df.to_dict(orient="records"),
            "timestamp": pd.Timestamp.now().isoformat()
        }
        
        return response
        
    except Exception as e:
        print(f"Error en consulta: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Error al consultar datos: {str(e)}"
        )

@app.get("/api/poblacion")
async def get_todos_los_centros():
    """
    Obtiene todos los registros de población estudiantil (sin filtrar por centro)
    Útil para exploración inicial o para obtener lista de centros disponibles
    """
    try:
        engine = get_db_engine()
        if not engine:
            raise HTTPException(
                status_code=503, 
                detail="No se pudo conectar a la base de datos db360"
            )
        
        print(f"Consultando todos los registros de {DB_TABLA}")
        
        query = text(f"SELECT * FROM {DB_TABLA} ORDER BY centro_id, periodo DESC")
        df = pd.read_sql(query, engine)
        
        # Convertir columnas datetime a string
        for col in df.select_dtypes(include=['datetime64']).columns:
            df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # Obtener lista de centros únicos
        centros_unicos = df['centro_id'].unique().tolist() if 'centro_id' in df.columns else []
        
        response = {
            "base_datos": DB_NAME,
            "tabla": DB_TABLA,
            "total_registros": len(df),
            "centros_disponibles": centros_unicos,
            "data": df.to_dict(orient="records"),
            "timestamp": pd.Timestamp.now().isoformat()
        }
        
        return response
        
    except Exception as e:
        print(f"Error en consulta: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Error al consultar datos: {str(e)}"
        )

@app.get("/api/poblacion/centros")
async def get_centros_disponibles():
    """
    Obtiene la lista de centros disponibles en la tabla Poblacion_Estudiantil
    """
    try:
        engine = get_db_engine()
        if not engine:
            raise HTTPException(
                status_code=503, 
                detail="No se pudo conectar a la base de datos db360"
            )
        
        print(f"Obteniendo centros disponibles de {DB_TABLA}")
        
        query = text(f"SELECT DISTINCT centro_id FROM {DB_TABLA} ORDER BY centro_id")
        df = pd.read_sql(query, engine)
        
        centros = df['centro_id'].tolist() if not df.empty else []
        
        return {
            "base_datos": DB_NAME,
            "tabla": DB_TABLA,
            "total_centros": len(centros),
            "centros": centros,
            "timestamp": pd.Timestamp.now().isoformat()
        }
        
    except Exception as e:
        print(f"Error en consulta: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Error al consultar centros: {str(e)}"
        )

# Endpoint para ver estado del caché de conexión
@app.get("/admin/connection-status")
async def connection_status():
    """Muestra el estado de la conexión en caché (solo administración)"""
    return {
        "conexion_activa": _engine_cache is not None,
        "base_datos": DB_NAME,
        "tabla": DB_TABLA,
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
    print(f"Tabla: {DB_TABLA}")
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