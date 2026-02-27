import os
import time
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# ============================================================================
# CARGAR VARIABLES DE ENTORNO
# ============================================================================
load_dotenv()

DB_SERVER = os.getenv("DB_SERVER")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_PORT = os.getenv("DB_PORT", "1433")
DB_NAME = os.getenv("DB_NAME", "db360")
API_KEY_SECRETA = os.getenv("API_KEY_SECRET")

if not all([DB_SERVER, DB_USER, DB_PASS, API_KEY_SECRETA]):
    raise ValueError("Faltan variables de entorno críticas")

# ============================================================================
# SEGURIDAD
# ============================================================================
async def verificar_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    if x_api_key != API_KEY_SECRETA:
        raise HTTPException(status_code=403, detail="Acceso no autorizado")
    return x_api_key

# ============================================================================
# FASTAPI
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
    global _engine_cache, _ultima_conexion
    global _total_conexiones, _conexiones_fallidas, _ultimo_error

    if _engine_cache is not None:
        try:
            with _engine_cache.connect() as conn:
                conn.execute(text("SELECT 1"))
            return _engine_cache
        except Exception:
            _engine_cache = None

    try:
        connection_string = (
            f"mssql+pymssql://{DB_USER}:{DB_PASS}"
            f"@{DB_SERVER}:{DB_PORT}/{DB_NAME}"
        )
        engine = create_engine(
            connection_string,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        _engine_cache = engine
        _ultima_conexion = time.strftime("%Y-%m-%d %H:%M:%S")
        _total_conexiones += 1
        _ultimo_error = None
        print("✅ Conexión a BD establecida correctamente")
        return engine

    except Exception as e:
        _ultimo_error = str(e)
        _conexiones_fallidas += 1
        print(f"❌ Error conectando a BD: {e}")
        return None

# ============================================================================
# NORMALIZACIÓN
# ============================================================================
def normalizar_fila_indicadores(row):
    fila = {}
    for key, value in row.items():
        if key is None:
            continue
        key_str = str(key).strip()
        fila[key_str] = value
    return fila

def limpiar_centro_id(centro_id: str) -> str:
    """
    Elimina espacios normales Y espacios no-break \xa0 (CHAR 160)
    que algunos valores tienen al final en la BD.
    """
    return centro_id.strip().replace('\xa0', '').strip()

# ============================================================================
# CONSULTAS
# ============================================================================

def query_indicators(engine, centro_id):
    try:
        centro_limpio = limpiar_centro_id(centro_id)
        print(f"query_indicators -> centro_limpio='{centro_limpio}' largo={len(centro_limpio)}")

        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT
                    RTRIM(LTRIM([Nombre Corto])) AS [Nombre Corto],
                    [2025], [2026], [2027], [2028], [2029],
                    RTRIM(LTRIM([2030]))         AS [2030]
                FROM [dbo].[Indicadores_Proyecciones]
                WHERE REPLACE(RTRIM(LTRIM([Nivel])), CHAR(160), '') = :nivel
                  AND [Nombre Corto] IS NOT NULL
                  AND RTRIM(LTRIM([Nombre Corto])) <> ''
            """), {"nivel": centro_limpio})

            rows = []
            for row in result.mappings().all():
                fila = normalizar_fila_indicadores(dict(row))
                rows.append({
                    "Nombre Corto": fila.get("Nombre Corto"),
                    "2025": fila.get("2025"),
                    "2026": fila.get("2026"),
                    "2027": fila.get("2027"),
                    "2028": fila.get("2028"),
                    "2029": fila.get("2029"),
                    "2030": fila.get("2030")
                })

            print(f"query_indicators -> filas retornadas: {len(rows)}")
            return rows

    except Exception as e:
        print(f"❌ ERROR query_indicators: {e}")
        return []


def query_student_summary(engine, centro_id):
    """
    - Población (totales por nivel/modalidad): dbo.Poblacion Estudiantil
      filtrado por [Rectoría] = 'Bogotá', año=2026, Cuatrimestre IN ('S1','Q1').
      Segmentación: Posgrado = Maestría + Especialización, resto = Pregrado.

    - Géneros: dbo.Caracterizacion_Estudiantil
      filtrado por [Rectoría] = 'Bogotá', año=2026.

    Ambas queries son FIJAS a Bogotá, independiente del centro seleccionado.
    """
    try:
        # ── Totales por nivel y modalidad — siempre Rectoría Bogotá ──────────
        query_poblacion = text("""
            SELECT
                SUM(CASE
                    WHEN [Nivel] NOT IN ('Maestría', 'Especialización')
                     AND [Modalidad] = 'Distancia'
                    THEN [Estudiantes Totales] ELSE 0 END) AS pregradoDistancia,

                SUM(CASE
                    WHEN [Nivel] NOT IN ('Maestría', 'Especialización')
                     AND [Modalidad] = 'Presencial'
                    THEN [Estudiantes Totales] ELSE 0 END) AS pregradoPresencial,

                SUM(CASE
                    WHEN [Nivel] NOT IN ('Maestría', 'Especialización')
                    THEN [Estudiantes Totales] ELSE 0 END) AS pregradoTotal,

                SUM(CASE
                    WHEN [Nivel] IN ('Maestría', 'Especialización')
                     AND [Modalidad] = 'Distancia'
                    THEN [Estudiantes Totales] ELSE 0 END) AS posgradoDistancia,

                SUM(CASE
                    WHEN [Nivel] IN ('Maestría', 'Especialización')
                     AND [Modalidad] = 'Presencial'
                    THEN [Estudiantes Totales] ELSE 0 END) AS posgradoPresencial,

                SUM(CASE
                    WHEN [Nivel] IN ('Maestría', 'Especialización')
                    THEN [Estudiantes Totales] ELSE 0 END) AS posgradoTotal,

                SUM(CASE
                    WHEN [Modalidad] = 'Distancia'
                    THEN [Estudiantes Totales] ELSE 0 END) AS totalGeneralDistancia,

                SUM(CASE
                    WHEN [Modalidad] = 'Presencial'
                    THEN [Estudiantes Totales] ELSE 0 END) AS totalGeneralPresencial,

                SUM([Estudiantes Totales]) AS totalGeneral

            FROM [dbo].[Poblacion Estudiantil]
            WHERE [Rectoría] = 'Bogotá'
              AND [año] = 2026
              AND [Cuatrimestre] IN ('S1', 'Q1')
        """)

        # ── Géneros — siempre Rectoría Bogotá ────────────────────────────────
        query_generos = text("""
            SELECT
                SUM(CASE WHEN [Género] = 'Masculino' THEN [Estudiantes Totales] ELSE 0 END) AS hombres,
                SUM(CASE WHEN [Género] = 'Femenino'  THEN [Estudiantes Totales] ELSE 0 END) AS mujeres
            FROM [dbo].[Caracterizacion_Estudiantil]
            WHERE [Rectoría] = 'Bogotá'
              AND [año] = 2026
        """)

        with engine.connect() as conn:
            row_pob = conn.execute(query_poblacion).mappings().first()
            row_gen = conn.execute(query_generos).mappings().first()

        resultado = dict(row_pob) if row_pob else {}

        if row_gen:
            resultado["hombres"] = row_gen["hombres"]
            resultado["mujeres"] = row_gen["mujeres"]
            print(f"  géneros Bogotá -> hombres={row_gen['hombres']} mujeres={row_gen['mujeres']}")
        else:
            resultado["hombres"] = None
            resultado["mujeres"] = None
            print("  géneros -> sin resultados para Rectoría Bogotá año=2026")

        print(f"query_student_summary -> {resultado}")
        return resultado

    except Exception as e:
        print(f"❌ ERROR query_student_summary: {e}")
        return {}


def query_proyecciones(engine, centro_id):
    try:
        query = text("""
            SELECT [Nivel Académico], Modalidad, Periodicidad,
                   [Tipo de Estudiante], [Tipo de Información], Año, Valor
            FROM [Proyecciones_cu]
            WHERE [Centro Universitario] = :centro_id
        """)
        with engine.connect() as conn:
            result = conn.execute(query, {"centro_id": centro_id})
            return [dict(row) for row in result.mappings().all()]
    except Exception as e:
        print(f"❌ ERROR query_proyecciones: {e}")
        return []


def query_desercion(engine, centro_id):
    try:
        centro_limpio = limpiar_centro_id(centro_id)
        query = text("""
            SELECT [Nombre Corto], [2025], [2026], [2027], [2028], [2029], [2030 ]
            FROM [Indicadores_Proyecciones]
            WHERE REPLACE(RTRIM(LTRIM([Nivel])), CHAR(160), '') = :centro_id
              AND [Nombre Corto] IN ('Deserción Presencial', 'Deserción Distancia')
        """)
        with engine.connect() as conn:
            result = conn.execute(query, {"centro_id": centro_limpio})
            rows = result.mappings().all()

        desercion = []
        for row in rows:
            fila = normalizar_fila_indicadores(dict(row))
            nombre_corto = fila.get("Nombre Corto")
            modalidad = "Presencial" if nombre_corto and "Presencial" in nombre_corto else "Distancia"
            for año in ["2025", "2026", "2027", "2028", "2029", "2030"]:
                valor = fila.get(año)
                if valor is not None and valor != "":
                    desercion.append({
                        "año": año,
                        "modalidad": modalidad,
                        "porcentaje": valor
                    })
        return desercion
    except Exception as e:
        print(f"❌ ERROR query_desercion: {e}")
        return []


def query_oferta(engine, centro_id):
    try:
        query = text("""
            SELECT año, Nivel, Modalidad, Periodicidad,
                   COUNT(DISTINCT snies) as snies_unico
            FROM [dbo].[Poblacion Estudiantil]
            WHERE [Centro Universitario] = :centro_id
            GROUP BY año, Nivel, Modalidad, Periodicidad
        """)
        with engine.connect() as conn:
            result = conn.execute(query, {"centro_id": centro_id})
            return [dict(row) for row in result.mappings().all()]
    except Exception as e:
        print(f"❌ ERROR query_oferta: {e}")
        return []

# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/")
async def root():
    return {"message": "API Observatorio funcionando correctamente"}

@app.get("/health")
async def health():
    engine = conectar_bd()
    return {
        "status": "ok",
        "conexion_bd": engine is not None,
        "ultimo_error": _ultimo_error
    }

@app.get("/api/observatorio/completo/{centro_id}")
async def get_observatorio_completo(
    centro_id: str,
    api_key: str = Depends(verificar_api_key)
):
    engine = conectar_bd()
    if not engine:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")

    try:
        return {
            "indicators": query_indicators(engine, centro_id),
            "studentSummary": query_student_summary(engine, centro_id),
            "proyecciones": query_proyecciones(engine, centro_id),
            "desercion": query_desercion(engine, centro_id),
            "oferta": query_oferta(engine, centro_id),
        }
    except Exception as e:
        print("🔥 ERROR REAL:", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/observatorio/page2/{centro_id}")
async def get_page2_data(
    centro_id: str,
    api_key: str = Depends(verificar_api_key)
):
    return await get_observatorio_completo(centro_id, api_key)

# ============================================================================
# RUN
# ============================================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
