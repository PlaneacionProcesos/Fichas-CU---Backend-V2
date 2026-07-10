import os
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# --- Supabase / PostgreSQL ---
DB_HOST     = os.getenv("DB_HOST")       # ej: db.xxxxxxxxxxxx.supabase.co
DB_USER     = os.getenv("DB_USER")       # ej: postgres
DB_PASS     = os.getenv("DB_PASS")
DB_PORT     = os.getenv("DB_PORT", "5432")
DB_NAME     = os.getenv("DB_NAME", "postgres")
API_KEY_SECRETA = os.getenv("API_KEY_SECRET")

if not all([DB_HOST, DB_USER, DB_PASS, API_KEY_SECRETA]):
     raise ValueError("Faltan variables de entorno criticas")

async def verificar_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    if x_api_key != API_KEY_SECRETA:
        raise HTTPException(status_code=403, detail="Acceso no autorizado")
    return x_api_key

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

ORIGENES_PERMITIDOS = [
    "http://localhost:5173",
    "http://localhost:4173",
     "https://ficha-cu-two.vercel.app/",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGENES_PERMITIDOS,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

_engine_cache        = None
_ultima_conexion     = None
_total_conexiones    = 0
_conexiones_fallidas = 0
_ultimo_error        = None

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
        # PostgreSQL connection string para Supabase
        connection_string = (
            f"postgresql+psycopg2://{DB_USER}:{DB_PASS}"
            f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        )
        engine = create_engine(
            connection_string,
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args={"sslmode": "require"},  # Supabase requiere SSL
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        _engine_cache      = engine
        _ultima_conexion   = time.strftime("%Y-%m-%d %H:%M:%S")
        _total_conexiones += 1
        _ultimo_error      = None
        print("Conexion BD OK (Supabase)")
        return engine
    except Exception as e:
        _ultimo_error        = str(e)
        _conexiones_fallidas += 1
        print(f"Error BD: {e}")
        return None

_cache     = {}
_CACHE_TTL = 2592000  # 30 días en segundos

def get_cached(centro_id: str):
    if centro_id in _cache:
        data, ts = _cache[centro_id]
        if time.time() - ts < _CACHE_TTL:
            return data
        del _cache[centro_id]
    return None

def set_cached(centro_id: str, data: dict):
    _cache[centro_id] = (data, time.time())

_executor = ThreadPoolExecutor(max_workers=6)

async def run_query(func, engine, centro_id):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, func, engine, centro_id)

def normalizar_fila_indicadores(row):
    fila = {}
    for key, value in row.items():
        if key is None:
            continue
        fila[str(key).strip()] = value
    return fila

def normalizar_fila_proyecciones(row: dict) -> dict:
    MAPA = {
        "Rectoría":             "rectoria",
        "Centro Universitario": "centro_universitario",
        "Sede":                 "sede",
        "Nivel Académico":      "nivel_academico",
        "Nivel de Formación":   "nivel_formacion",
        "Facultad":             "facultad",
        "Periodicidad":         "periodicidad",
        "Modalidad":            "modalidad",
        "CECO":                 "ceco",
        "Snies":                "snies",
        "Programa":             "programa",
        "Atributo":             "atributo",
        "Valor":                "valor",
        "Tipo de Estudiante":   "tipo_estudiante",
        "Tipo de Información":  "tipo_informacion",
        "Periodo":              "periodo",
        "Año":                  "año",
    }
    normalizado = {}
    for key, value in row.items():
        key_limpio = str(key).strip()
        nueva_clave = MAPA.get(key_limpio, key_limpio.lower().replace(" ", "_"))
        normalizado[nueva_clave] = value
    return normalizado

CENTRO_ID_MAPA = {
    "centro-engativa":               "Especial Minuto de Dios - Engativá",
    "centro-kennedy":                "Kennedy",
    "centro-santa-fe-las-cruces":    "Las Cruces - Santa Fe",
    "centro-perdomo-ciudad-bolivar": "Perdomo - Ciudad Bolívar",
    "centro-san-cristobal-usaquen":  "San Cristóbal Norte - Usaquén",
}

def resolver_centro_id(centro_id: str) -> str:
    limpio = centro_id.strip().replace("\xa0", "").strip()
    return CENTRO_ID_MAPA.get(limpio, limpio)

def limpiar_centro_id(centro_id: str) -> str:
    return centro_id.strip().replace("\xa0", "").strip()

# ============================================================================
# CONSULTAS  —  PostgreSQL / Supabase
# Cambios respecto a Azure:
#   • Sin corchetes []: se usan comillas dobles "" para nombres con espacios
#   • CHAR(160) → CHR(160)
#   • RTRIM/LTRIM → TRIM
#   • Sin esquema [dbo]: se usa el schema "public" por defecto
#   • Nombre tabla: Caracterizacion_Estudiantil → caracterizacion_estudiantes
#   • Nombre tabla: Indicadores_Proyecciones   → indicadores_proyecciones
#   • Nombre tabla: Poblacion Estudiantil      → "Poblacion Estudiantil"
#   • Nombre tabla: Proyecciones_cu            → proyecciones_cu
#   • CAST(x AS VARCHAR) → CAST(x AS TEXT)
# ============================================================================

def query_indicators(engine, centro_id):
    try:
        nombre_bd = resolver_centro_id(centro_id)
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT
                    TRIM("Nombre Corto")          AS "Nombre Corto",
                    "Linea Base"                  AS "2024",
                    "2025", "2026", "2027", "2028", "2029",
                    TRIM(CAST("2030" AS TEXT))     AS "2030"
                FROM indicadores_proyecciones
                WHERE REPLACE(TRIM("Nivel"), CHR(160), '') = :nivel
                  AND "Nombre Corto" IS NOT NULL
                  AND TRIM("Nombre Corto") <> ''
            """), {"nivel": nombre_bd})
            rows = result.mappings().all()
        filas_procesadas = []
        for row in rows:
            fila = normalizar_fila_indicadores(dict(row))
            filas_procesadas.append({
                "Nombre Corto": fila.get("Nombre Corto"),
                "2024": fila.get("2024"),
                "2025": fila.get("2025"),
                "2026": fila.get("2026"),
                "2027": fila.get("2027"),
                "2028": fila.get("2028"),
                "2029": fila.get("2029"),
                "2030": fila.get("2030"),
            })
        print(f"query_indicators: {len(filas_procesadas)} filas")
        return filas_procesadas
    except Exception as e:
        print(f"ERROR query_indicators: {e}")
        return []

def query_student_summary(engine, centro_id):
    try:
        nombre_bd = resolver_centro_id(centro_id)
        print(f"query_student_summary: '{nombre_bd}'")

        query_poblacion = text("""
            SELECT
                SUM(CASE WHEN REPLACE(TRIM("Nivel Académico"), CHR(160), '') = 'Pregrado'  AND TRIM("Modalidad") = 'Distancia'  THEN "Estudiantes Totales" ELSE 0 END) AS pregrado_distancia,
                SUM(CASE WHEN REPLACE(TRIM("Nivel Académico"), CHR(160), '') = 'Pregrado'  AND TRIM("Modalidad") = 'Presencial' THEN "Estudiantes Totales" ELSE 0 END) AS pregrado_presencial,
                SUM(CASE WHEN REPLACE(TRIM("Nivel Académico"), CHR(160), '') = 'Pregrado'                                        THEN "Estudiantes Totales" ELSE 0 END) AS pregrado_total,
                SUM(CASE WHEN REPLACE(TRIM("Nivel Académico"), CHR(160), '') = 'Posgrado'  AND TRIM("Modalidad") = 'Distancia'  THEN "Estudiantes Totales" ELSE 0 END) AS posgrado_distancia,
                SUM(CASE WHEN REPLACE(TRIM("Nivel Académico"), CHR(160), '') = 'Posgrado'  AND TRIM("Modalidad") = 'Presencial' THEN "Estudiantes Totales" ELSE 0 END) AS posgrado_presencial,
                SUM(CASE WHEN REPLACE(TRIM("Nivel Académico"), CHR(160), '') = 'Posgrado'                                        THEN "Estudiantes Totales" ELSE 0 END) AS posgrado_total,
                SUM(CASE WHEN TRIM("Modalidad") = 'Distancia'  THEN "Estudiantes Totales" ELSE 0 END) AS total_general_distancia,
                SUM(CASE WHEN TRIM("Modalidad") = 'Presencial' THEN "Estudiantes Totales" ELSE 0 END) AS total_general_presencial,
                SUM("Estudiantes Totales") AS total_general
            FROM poblacion_estudiantil
            WHERE "Centro Universitario" = :centro_id
              AND "Año" = 2026
              AND REPLACE(TRIM("Nivel Académico"), CHR(160), '') IN ('Pregrado', 'Posgrado')
              AND (
                  ("Periodicidad" = 'Semestral'     AND "Periodo" = 'S1')
               OR ("Periodicidad" = 'Cuatrimestral' AND "Periodo" = 'Q1')
              )
        """)

        query_generos = text("""
            SELECT
                SUM(CASE WHEN "Género" = 'Masculino' THEN "Estudiantes Totales" ELSE 0 END) AS hombres,
                SUM(CASE WHEN "Género" = 'Femenino'  THEN "Estudiantes Totales" ELSE 0 END) AS mujeres
            FROM caracterizacion_estudiantes
            WHERE "Centro Universitario" = :centro_id
              AND "Año" = 2026
              AND (
                  ("Periodicidad" = 'Semestral'     AND "Periodo" = 'S1')
               OR ("Periodicidad" = 'Cuatrimestral' AND "Periodo" = 'Q1')
              )
        """)

        with engine.connect() as conn:
            row_pob = conn.execute(query_poblacion, {"centro_id": nombre_bd}).mappings().first()
            row_gen = conn.execute(query_generos,   {"centro_id": nombre_bd}).mappings().first()

        print(f"row_pob: {dict(row_pob) if row_pob else 'NONE'}")
        print(f"row_gen: {dict(row_gen) if row_gen else 'NONE'}")

        resultado = dict(row_pob) if row_pob else {}
        resultado["hombres"] = row_gen["hombres"] if row_gen else None
        resultado["mujeres"] = row_gen["mujeres"] if row_gen else None
        return resultado

    except Exception as e:
        print(f"ERROR query_student_summary: {e}")
        return {}

def query_proyecciones(engine, centro_id):
    try:
        nombre_bd = resolver_centro_id(centro_id)
        query = text("""
            SELECT
                "Nivel Académico",
                "Nivel de Formación",
                "Modalidad",
                "Periodicidad",
                "Tipo de Estudiante",
                "Tipo de Información",
                "Año",
                SUM("Valor") AS "Valor"
            FROM proyecciones_cu
            WHERE "Centro Universitario" = :centro_id
              AND "Atributo" LIKE '%Q1/S1%'
            GROUP BY
                "Nivel Académico",
                "Nivel de Formación",
                "Modalidad",
                "Periodicidad",
                "Tipo de Estudiante",
                "Tipo de Información",
                "Año"
        """)
        with engine.connect() as conn:
            rows = conn.execute(query, {"centro_id": nombre_bd}).mappings().all()
        normalizadas = [normalizar_fila_proyecciones(dict(r)) for r in rows]
        print(f"query_proyecciones: {len(normalizadas)} filas")
        return normalizadas
    except Exception as e:
        print(f"ERROR query_proyecciones: {e}")
        return []


def query_matriculados_2026(engine, centro_id):
    try:
        nombre_bd = resolver_centro_id(centro_id)
        query = text("""
            SELECT
                REPLACE(TRIM("Nivel Académico"), CHR(160), '') AS nivel_academico,
                TRIM("Modalidad")                              AS modalidad,
                SUM("Estudiantes Nuevos")                      AS nuevos_matriculados,
                SUM("Estudiantes Continuos")                   AS continuos_matriculados,
                SUM("Estudiantes Totales")                     AS totales_matriculados
            FROM "poblacion_estudiantil"
            WHERE "Centro Universitario" = :centro_id
              AND "Año" = 2026
              AND "Periodicidad" IN ('Semestral', 'Cuatrimestral')
              AND REPLACE(TRIM("Nivel Académico"), CHR(160), '') IN ('Pregrado', 'Posgrado')
            GROUP BY
                REPLACE(TRIM("Nivel Académico"), CHR(160), ''),
                TRIM("Modalidad")
        """)
        with engine.connect() as conn:
            rows = conn.execute(query, {"centro_id": nombre_bd}).mappings().all()

        resultado = [
            {
                "nivel_academico":        str(r["nivel_academico"]).strip(),
                "modalidad":              str(r["modalidad"]).strip(),
                "nuevos_matriculados":    int(r["nuevos_matriculados"]    or 0),
                "continuos_matriculados": int(r["continuos_matriculados"] or 0),
                "totales_matriculados":   int(r["totales_matriculados"]   or 0),
            }
            for r in rows
        ]
        print(f"query_matriculados_2026: {len(resultado)} filas")
        return resultado

    except Exception as e:
        print(f"ERROR query_matriculados_2026: {e}")
        return []


def query_desercion(engine, centro_id):
    try:
        nombre_bd = resolver_centro_id(centro_id)
        query = text("""
            SELECT "Nombre Corto", "2026", "2027", "2028", "2029", "2030"
            FROM indicadores_proyecciones
            WHERE REPLACE(TRIM("Nivel"), CHR(160), '') = :centro_id
              AND "Nombre Corto" IN ('Deserción Presencial', 'Deserción Distancia')
        """)
        with engine.connect() as conn:
            rows = conn.execute(query, {"centro_id": nombre_bd}).mappings().all()
        desercion = []
        for row in rows:
            fila = normalizar_fila_indicadores(dict(row))
            nombre = fila.get("Nombre Corto", "")
            modalidad = "Presencial" if "Presencial" in nombre else "Distancia"
            for anio in ["2026", "2027", "2028", "2029", "2030"]:
                valor = fila.get(anio)
                if valor is not None and valor != "":
                    desercion.append({"año": anio, "modalidad": modalidad, "porcentaje": valor})
        print(f"query_desercion: {len(desercion)} filas")
        return desercion
    except Exception as e:
        print(f"ERROR query_desercion: {e}")
        return []


def query_oferta(engine, centro_id):
    try:
        nombre_bd = resolver_centro_id(centro_id)
        query = text("""
            SELECT
                CAST("Año" AS TEXT)                                          AS año,
                REPLACE(TRIM("Nivel Académico"), CHR(160), '')               AS nivel_academico,
                REPLACE(TRIM("Modalidad"),       CHR(160), '')               AS modalidad,
                REPLACE(TRIM("Periodicidad"),    CHR(160), '')               AS periodicidad,
                COUNT(DISTINCT "SNIES")                                      AS snies_unico
            FROM proyecciones_cu
            WHERE "Centro Universitario" = :centro_id
              AND "SNIES" IS NOT NULL
              AND "Año" BETWEEN 2026 AND 2030
            GROUP BY
                "Año",
                REPLACE(TRIM("Nivel Académico"), CHR(160), ''),
                REPLACE(TRIM("Modalidad"),       CHR(160), ''),
                REPLACE(TRIM("Periodicidad"),    CHR(160), '')
        """)
        with engine.connect() as conn:
            rows = conn.execute(query, {"centro_id": nombre_bd}).mappings().all()
        resultado = [
            {
                "año":             str(r["año"]).strip(),
                "nivel_academico": str(r["nivel_academico"]).strip() if r["nivel_academico"] else "",
                "modalidad":       str(r["modalidad"]).strip()       if r["modalidad"]       else "",
                "periodicidad":    str(r["periodicidad"]).strip()     if r["periodicidad"]    else "",
                "snies_unico":     int(r["snies_unico"]),
            }
            for r in rows
        ]
        print(f"query_oferta: {len(resultado)} filas")
        return resultado
    except Exception as e:
        print(f"ERROR query_oferta: {e}")
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
    return {"status": "ok", "conexion_bd": engine is not None, "ultimo_error": _ultimo_error}

@app.get("/api/cache/refresh")
async def refresh_cache(api_key: str = Depends(verificar_api_key)):
    centros_en_cache = list(_cache.keys())
    _cache.clear()
    print(f"🗑️ Caché limpiado manualmente. Centros eliminados: {centros_en_cache}")
    return {
        "status": "ok",
        "mensaje": "Caché limpiado. La próxima consulta de cada centro recargará datos frescos desde Supabase.",
        "centros_eliminados": centros_en_cache
    }

@app.get("/api/cache/status")
async def cache_status(api_key: str = Depends(verificar_api_key)):
    ahora = time.time()
    estado = {}
    for centro_id, (data, ts) in _cache.items():
        segundos_restantes = int(_CACHE_TTL - (ahora - ts))
        dias_restantes = segundos_restantes // 86400
        estado[centro_id] = {
            "cargado_en": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
            "expira_en_dias": dias_restantes,
            "expira_en_segundos": segundos_restantes,
        }
    return {
        "total_centros_en_cache": len(_cache),
        "ttl_configurado_dias": _CACHE_TTL // 86400,
        "centros": estado
    }

@app.get("/api/observatorio/completo/{centro_id}")
async def get_observatorio_completo(
    centro_id: str,
    api_key: str = Depends(verificar_api_key),
):
    cached = get_cached(centro_id)
    if cached:
        return cached

    engine = conectar_bd()
    if not engine:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")

    try:
        t0 = time.time()
        results = await asyncio.gather(
            run_query(query_indicators,        engine, centro_id),
            run_query(query_student_summary,   engine, centro_id),
            run_query(query_proyecciones,      engine, centro_id),
            run_query(query_matriculados_2026, engine, centro_id),
            run_query(query_desercion,         engine, centro_id),
            run_query(query_oferta,            engine, centro_id),
        )
        response = {
            "indicators":       results[0],
            "studentSummary":   results[1],
            "proyecciones":     results[2],
            "matriculados2026": results[3],
            "desercion":        results[4],
            "oferta":           results[5],
        }
        print(f"Tiempo total: {time.time() - t0:.2f}s")
        set_cached(centro_id, response)
        return response

    except Exception as e:
        print("ERROR:", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/observatorio/page2/{centro_id}")
async def get_page2_data(
    centro_id: str,
    api_key: str = Depends(verificar_api_key),
):
    return await get_observatorio_completo(centro_id, api_key)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
