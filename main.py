import os
import time
import urllib.parse
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# ============================================================================
# CONFIGURACIÓN DESDE VARIABLES DE ENTORNO
# ============================================================================
DB_SERVER = os.getenv("DB_SERVER")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_PORT = os.getenv("DB_PORT", "1433")
DB_NAME = os.getenv("DB_NAME", "db360")
API_KEY_SECRETA = os.getenv("API_KEY_SECRET")

if not all([DB_SERVER, DB_USER, DB_PASS, API_KEY_SECRETA]):
    raise ValueError("Faltan variables de entorno críticas: DB_SERVER, DB_USER, DB_PASS, API_KEY_SECRET")

# ============================================================================
# SEGURIDAD
# ============================================================================
async def verificar_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    if x_api_key != API_KEY_SECRETA:
        raise HTTPException(status_code=403, detail="Acceso no autorizado")
    return x_api_key

# ============================================================================
# APLICACIÓN FASTAPI
# ============================================================================
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

# ============================================================================
# CORS
# ============================================================================
ORIGENES_PERMITIDOS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "https://ficha-cu.vercel.app",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGENES_PERMITIDOS,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ============================================================================
# CONEXIÓN BD
# ============================================================================
_engine_cache = None
_ultima_conexion = None
_total_conexiones = 0
_conexiones_fallidas = 0
_ultimo_error = None

def conectar_bd():
    global _engine_cache, _ultima_conexion, _total_conexiones, _conexiones_fallidas, _ultimo_error
    if _engine_cache is not None:
        try:
            with _engine_cache.connect() as conn:
                conn.execute(text("SELECT 1"))
            return _engine_cache
        except Exception:
            _engine_cache = None

    try:
        password_escaped = urllib.parse.quote_plus(DB_PASS)
        connection_string = f"mssql+pymssql://{DB_USER}:{password_escaped}@{DB_SERVER}:{DB_PORT}/{DB_NAME}"
        engine = create_engine(connection_string, pool_pre_ping=True, pool_recycle=1800)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1")).scalar()
        _engine_cache = engine
        _ultima_conexion = time.strftime("%Y-%m-%d %H:%M:%S")
        _total_conexiones += 1
        _ultimo_error = None
        return engine
    except Exception as e:
        _ultimo_error = str(e)
        _conexiones_fallidas += 1
        print(f"Error conectando a BD: {e}")
        return None

# ============================================================================
# FUNCIONES DE CONSULTA (con filtro por [Centro Universitario])
def query_indicators(engine, centro_id):
    # 1. Limpiamos el ID que viene del front (ej: de 'centro-engativa' a 'engativa')
    nombre_limpio = centro_id.split('-')[-1].strip()
    
    query = text("""
        SELECT 
            TRIM([Nombre Corto]) AS [Nombre Corto], 
            TRIM([Indicador]) AS [Indicador],
            [2025 ] AS [2025], [2026 ] AS [2026], [2027 ] AS [2027], 
            [2028 ] AS [2028], [2029 ] AS [2030], [2030 ] AS [2030]
        FROM [dbo].[Indicadores_Proyecciones]
        WHERE [Nivel] LIKE :busqueda 
          AND ([Nombre Corto] IS NOT NULL OR [Indicador] IS NOT NULL)
    """)
    with engine.connect() as conn:
        result = conn.execute(query, {"busqueda": f"%{nombre_limpio}%"})
        return [dict(row) for row in result.mappings().all()]

def query_student_summary(engine, centro_id):
    # También usamos LIKE aquí por si el nombre en esta tabla es distinto
    nombre_limpio = centro_id.split('-')[-1].strip()
    
    query = text("""
        SELECT 
            SUM(CASE WHEN nivel = 'Pregrado' AND Modalidad = 'Distancia' THEN [Estudiantes Totales] ELSE 0 END) as pregradoDistancia,
            SUM(CASE WHEN nivel = 'Pregrado' AND Modalidad = 'Presencial' THEN [Estudiantes Totales] ELSE 0 END) as pregradoPresencial,
            SUM(CASE WHEN nivel = 'Pregrado' THEN [Estudiantes Totales] ELSE 0 END) as pregradoTotal,
            SUM(CASE WHEN nivel = 'Posgrado' AND Modalidad = 'Distancia' THEN [Estudiantes Totales] ELSE 0 END) as posgradoDistancia,
            SUM(CASE WHEN nivel = 'Posgrado' AND Modalidad = 'Presencial' THEN [Estudiantes Totales] ELSE 0 END) as posgradoPresencial,
            SUM(CASE WHEN nivel = 'Posgrado' THEN [Estudiantes Totales] ELSE 0 END) as posgradoTotal,
            SUM(CASE WHEN Modalidad = 'Distancia' THEN [Estudiantes Totales] ELSE 0 END) as totalGeneralDistancia,
            SUM(CASE WHEN Modalidad = 'Presencial' THEN [Estudiantes Totales] ELSE 0 END) as totalGeneralPresencial,
            SUM([Estudiantes Totales]) as totalGeneral,
            SUM(CASE WHEN Género = 'Hombre' THEN [Estudiantes Totales] ELSE 0 END) as hombres,
            SUM(CASE WHEN Género = 'Mujer' THEN [Estudiantes Totales] ELSE 0 END) as mujeres
        FROM Caracterizacion_Estudiantil
        WHERE [Centro Universitario] LIKE :busqueda 
          AND año = 2026 
    """)
    with engine.connect() as conn:
        result = conn.execute(query, {"busqueda": f"%{nombre_limpio}%"})
        row = result.mappings().first()
        return dict(row) if row else {}

def query_proyecciones(engine, centro_id):
    """Datos de proyección de estudiantes."""
    query = text("""
        SELECT [Nivel Académico], Modalidad, Periodicidad, [Tipo de Estudiante], [Tipo de Información], Año, Valor
        FROM [Proyecciones_cu]
        WHERE [Centro Universitario] = :centro_id
    """)
    with engine.connect() as conn:
        result = conn.execute(query, {"centro_id": centro_id})
        rows = result.mappings().all()
    return [dict(row) for row in rows]

def query_desercion(engine, centro_id):
    """Obtiene porcentajes de deserción desde Indicadores_Proyecciones para los nombres cortos específicos."""
    query = text("""
        SELECT [Nombre Corto], [2025], [2026], [2027], [2028], [2029], [2030]
        FROM [Indicadores_Proyecciones]
        WHERE [Nivel] = :centro_id
          AND [Nombre Corto] IN ('Deserción Presencial', 'Deserción Distancia')
    """)
    with engine.connect() as conn:
        result = conn.execute(query, {"centro_id": centro_id})
        rows = result.mappings().all()
    
    desercion = []
    for row in rows:
        modalidad = "Presencial" if "Presencial" in row["nombre_corto"] else "Distancia"
        for año in [2025,2026,2027,2028,2029,2030]:
            valor = row[str(año)]
            if valor is not None:
                desercion.append({
                    "año": str(año),
                    "modalidad": modalidad,
                    "porcentaje": float(valor)  # asegurar que sea número
                })
    return desercion

def query_oferta(engine, centro_id):
    """Datos de oferta académica."""
    query = text("""
        SELECT año, Nivel, Modalidad, Periodicidad, COUNT(DISTINCT snies) as snies_unico
        FROM [dbo].[Poblacion Estudiantil]
        WHERE [Centro Universitario] = :centro_id
        GROUP BY año, Nivel, modalidad, periodicidad
    """)
    with engine.connect() as conn:
        result = conn.execute(query, {"centro_id": centro_id})
        rows = result.mappings().all()
    return [dict(row) for row in rows]

# ============================================================================
# ENDPOINTS PÚBLICOS
# ============================================================================
@app.get("/")
async def root():
    return {"message": "API del Observatorio Uniminuto funcionando"}

@app.get("/health")
async def health():
    return {"status": "ok", "conexion_bd": _engine_cache is not None, "ultimo_error": _ultimo_error}

# ============================================================================
# ENDPOINT PROTEGIDO
# ============================================================================
@app.get("/api/observatorio/completo/{centro_id}")
async def get_observatorio_completo(centro_id: str, api_key: str = Depends(verificar_api_key)):
    engine = conectar_bd()
    if not engine:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")

    try:
        indicators = query_indicators(engine, centro_id)
        studentSummary = query_student_summary(engine, centro_id)
        proyecciones = query_proyecciones(engine, centro_id)
        desercion = query_desercion(engine, centro_id)
        oferta = query_oferta(engine, centro_id)

        return {
            "indicators": indicators,
            "studentSummary": studentSummary,
            "proyecciones": proyecciones,
            "desercion": desercion,
            "oferta": oferta
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

@app.get("/api/observatorio/page2/{centro_id}")
async def get_page2_data(centro_id: str, api_key: str = Depends(verificar_api_key)):
    return await get_observatorio_completo(centro_id)

# ============================================================================
# EJECUCIÓN
# ============================================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)