import os
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from urllib.parse import quote_plus
from pydantic import BaseModel

load_dotenv()

# --- Azure SQL Server ---
DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_PORT = os.getenv("DB_PORT", "1433")
DB_NAME = os.getenv("DB_NAME")
API_KEY_SECRETA = os.getenv("API_KEY_SECRET")

if not all([DB_HOST, DB_USER, DB_PASS, DB_NAME, API_KEY_SECRETA]):
    raise ValueError("Faltan variables de entorno criticas")


async def verificar_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    if x_api_key != API_KEY_SECRETA:
        raise HTTPException(status_code=403, detail="Acceso no autorizado")
    return x_api_key


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

ORIGENES_PERMITIDOS = [
    "http://localhost:5173",
    "http://localhost:4173",
    "https://ficha-cu-two.vercel.app",
]


class ConfiguracionRequest(BaseModel):
    anio: int
    periodo: str
    periodicidad: str


app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGENES_PERMITIDOS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
            f"mssql+pymssql://{quote_plus(DB_USER)}:{quote_plus(DB_PASS)}"
            f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
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
        print("Conexion BD OK (Azure SQL Server)")
        return engine
    except Exception as e:
        _ultimo_error = str(e)
        _conexiones_fallidas += 1
        print(f"Error BD: {e}")
        return None


_cache = {}
_CACHE_TTL = 2592000  # 30 días


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


async def run_query(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, func, *args)


def normalizar_fila_proyecciones(row: dict) -> dict:
    MAPA = {
        "Rectoría": "rectoria",
        "Centro Universitario": "centro_universitario",
        "Sede": "sede",
        "Nivel Académico": "nivel_academico",
        "Nivel de Formación": "nivel_formacion",
        "Facultad": "facultad",
        "Periodicidad": "periodicidad",
        "Modalidad": "modalidad",
        "CECO": "ceco",
        "SNIES": "snies",
        "Programa Académico": "programa",
        "Atributo": "atributo",
        "Valor": "valor",
        "Tipo de Estudiante": "tipo_estudiante",
        "Tipo de Información": "tipo_informacion",
        "Periodo": "periodo",
        "Año": "año",
    }
    normalizado = {}
    for key, value in row.items():
        key_limpio = str(key).strip()
        nueva_clave = MAPA.get(key_limpio, key_limpio.lower().replace(" ", "_"))
        normalizado[nueva_clave] = value
    return normalizado


CENTRO_ID_MAPA = {
    "centro-engativa": "Especial Minuto de Dios - Engativá",
    "centro-kennedy": "Kennedy",
    "centro-santa-fe-las-cruces": "Las Cruces - Santa Fe",
    "centro-perdomo-ciudad-bolivar": "Perdomo - Ciudad Bolívar",
    "centro-san-cristobal-usaquen": "San Cristóbal Norte - Usaquén",
}


def resolver_centro_id(centro_id: str) -> str:
    limpio = centro_id.strip().replace("\xa0", "").strip()
    return CENTRO_ID_MAPA.get(limpio, limpio)


def obtener_configuracion(engine):
    query = text("""
        SELECT
            anio,
            periodo,
            periodicidad
        FROM dbo.Configuracion_Observatorio
        WHERE id = 1
    """)

    with engine.connect() as conn:
        row = conn.execute(query).mappings().first()

    if not row:
        raise HTTPException(
            status_code=500,
            detail="No existe configuración del observatorio en dbo.Configuracion_Observatorio (id=1)",
        )

    return {
        "anio": int(row["anio"]),
        "periodo": str(row["periodo"]).strip(),
        "periodicidad": str(row["periodicidad"]).strip(),
    }


MAPA_5_CASOS = {
    "S1+Q1": {
        "prefijo_proyeccion": "Q1/S1",
        "clausula_poblacion": "(([Periodicidad] = 'Semestral' AND [Periodo] = 'S1') OR ([Periodicidad] = 'Cuatrimestral' AND [Periodo] = 'Q1'))",
        "descripcion": "Semestral S1 + Cuatrimestral Q1 (Inicio de Año)",
        "periodo_guardado": "S1+Q1",
        "periodicidad_guardada": "Semestral",
    },
    "S1+Q2": {
        "prefijo_proyeccion": "Q1/S1",
        "clausula_poblacion": "(([Periodicidad] = 'Semestral' AND [Periodo] = 'S1') OR ([Periodicidad] = 'Cuatrimestral' AND [Periodo] = 'Q2'))",
        "descripcion": "Semestral S1 + Cuatrimestral Q2",
        "periodo_guardado": "S1+Q2",
        "periodicidad_guardada": "Semestral",
    },
    "Q2": {
        "prefijo_proyeccion": "Q2",
        "clausula_poblacion": "([Periodicidad] = 'Cuatrimestral' AND [Periodo] = 'Q2')",
        "descripcion": "Cuatrimestral Q2 (Mitad de Año)",
        "periodo_guardado": "Q2",
        "periodicidad_guardada": "Cuatrimestral",
    },
    "S2+Q2": {
        "prefijo_proyeccion": "Q3/S2",
        "clausula_poblacion": "(([Periodicidad] = 'Semestral' AND [Periodo] = 'S2') OR ([Periodicidad] = 'Cuatrimestral' AND [Periodo] = 'Q2'))",
        "descripcion": "Semestral S2 + Cuatrimestral Q2",
        "periodo_guardado": "S2+Q2",
        "periodicidad_guardada": "Semestral",
    },
    "S2+Q3": {
        "prefijo_proyeccion": "Q3/S2",
        "clausula_poblacion": "(([Periodicidad] = 'Semestral' AND [Periodo] = 'S2') OR ([Periodicidad] = 'Cuatrimestral' AND [Periodo] = 'Q3'))",
        "descripcion": "Semestral S2 + Cuatrimestral Q3 (Segundo Semestre)",
        "periodo_guardado": "S2+Q3",
        "periodicidad_guardada": "Semestral",
    },
}


def normalizar_clave_periodo(periodo: str, periodicidad: str = "") -> str:
    p = (
        str(periodo)
        .strip()
        .upper()
        .replace("/", "+")
        .replace(" ", "")
        .replace("_", "+")
        .replace("-", "+")
    )
    per = str(periodicidad).strip().capitalize()

    if p in MAPA_5_CASOS:
        return p

    # Alias y equivalencias
    if p == "S1":
        return "S1+Q1"
    if p == "S2":
        return "S2+Q3"
    if p == "Q1":
        return "S1+Q1"
    if p == "Q3":
        return "S2+Q3"

    return p


def obtener_filtros_periodo(config: dict):
    periodo = str(config.get("periodo", "")).strip()
    periodicidad = str(config.get("periodicidad", "")).strip()

    clave = normalizar_clave_periodo(periodo, periodicidad)

    if clave in MAPA_5_CASOS:
        return MAPA_5_CASOS[clave]

    casos_validos = list(MAPA_5_CASOS.keys())
    raise ValueError(
        f"Combinación '{periodo}' no es válida. Los 5 casos soportados son: {casos_validos}"
    )


def obtener_prefijo_periodo(config: dict) -> str:
    filtros = obtener_filtros_periodo(config)
    return filtros["prefijo_proyeccion"]


def obtener_codigo_atributo(config: dict) -> str:
    prefijo = obtener_prefijo_periodo(config)
    return f"{prefijo}-{config['anio']}"


# ============================================================================
# CONSULTAS A LA BASE DE DATOS
# ============================================================================


def query_indicators(engine, centro_id):
    try:
        nombre_bd = resolver_centro_id(centro_id)
        query = text("""
            SELECT
                CONCAT(RTRIM(LTRIM([Tipo de Información])), ' ', RTRIM(LTRIM([Tipo de Estudiante]))) AS [Nombre Corto],
                SUM(CASE WHEN [Año] = 2024 THEN [Valor] ELSE 0 END) AS [2024],
                SUM(CASE WHEN [Año] = 2025 THEN [Valor] ELSE 0 END) AS [2025],
                SUM(CASE WHEN [Año] = 2026 THEN [Valor] ELSE 0 END) AS [2026],
                SUM(CASE WHEN [Año] = 2027 THEN [Valor] ELSE 0 END) AS [2027],
                SUM(CASE WHEN [Año] = 2028 THEN [Valor] ELSE 0 END) AS [2028],
                SUM(CASE WHEN [Año] = 2029 THEN [Valor] ELSE 0 END) AS [2029],
                SUM(CASE WHEN [Año] = 2030 THEN [Valor] ELSE 0 END) AS [2030]
            FROM dbo.[Proyeccion_Estudiantes]
            WHERE [Centro Universitario] = :centro_id
              AND [Año] BETWEEN 2024 AND 2030
            GROUP BY [Tipo de Información], [Tipo de Estudiante]
            ORDER BY [Tipo de Información], [Tipo de Estudiante]
        """)
        with engine.connect() as conn:
            rows = conn.execute(query, {"centro_id": nombre_bd}).mappings().all()

        resultado = [
            {
                "Nombre Corto": str(r["Nombre Corto"]).strip(),
                "2024": int(r["2024"] or 0),
                "2025": int(r["2025"] or 0),
                "2026": int(r["2026"] or 0),
                "2027": int(r["2027"] or 0),
                "2028": int(r["2028"] or 0),
                "2029": int(r["2029"] or 0),
                "2030": int(r["2030"] or 0),
            }
            for r in rows
        ]
        print(f"query_indicators: {len(resultado)} filas para '{nombre_bd}'")
        return resultado
    except Exception as e:
        print(f"ERROR query_indicators: {e}")
        return []


def query_student_summary(engine, centro_id, config):
    try:
        nombre_bd = resolver_centro_id(centro_id)
        filtros = obtener_filtros_periodo(config)
        clausula_poblacion = filtros["clausula_poblacion"]
        print(f"query_student_summary: '{nombre_bd}' - {config}")

        query_poblacion = text(f"""
            SELECT
                SUM(CASE WHEN REPLACE(RTRIM(LTRIM([Nivel Académico])), CHAR(160), '') = 'Pregrado'  AND RTRIM(LTRIM([Modalidad])) = 'Distancia'  THEN [Estudiantes Totales] ELSE 0 END) AS pregrado_distancia,
                SUM(CASE WHEN REPLACE(RTRIM(LTRIM([Nivel Académico])), CHAR(160), '') = 'Pregrado'  AND RTRIM(LTRIM([Modalidad])) = 'Presencial' THEN [Estudiantes Totales] ELSE 0 END) AS pregrado_presencial,
                SUM(CASE WHEN REPLACE(RTRIM(LTRIM([Nivel Académico])), CHAR(160), '') = 'Pregrado'                                                THEN [Estudiantes Totales] ELSE 0 END) AS pregrado_total,
                SUM(CASE WHEN REPLACE(RTRIM(LTRIM([Nivel Académico])), CHAR(160), '') = 'Posgrado'  AND RTRIM(LTRIM([Modalidad])) = 'Distancia'  THEN [Estudiantes Totales] ELSE 0 END) AS posgrado_distancia,
                SUM(CASE WHEN REPLACE(RTRIM(LTRIM([Nivel Académico])), CHAR(160), '') = 'Posgrado'  AND RTRIM(LTRIM([Modalidad])) = 'Presencial' THEN [Estudiantes Totales] ELSE 0 END) AS posgrado_presencial,
                SUM(CASE WHEN REPLACE(RTRIM(LTRIM([Nivel Académico])), CHAR(160), '') = 'Posgrado'                                                THEN [Estudiantes Totales] ELSE 0 END) AS posgrado_total,
                SUM(CASE WHEN RTRIM(LTRIM([Modalidad])) = 'Distancia'  THEN [Estudiantes Totales] ELSE 0 END) AS total_general_distancia,
                SUM(CASE WHEN RTRIM(LTRIM([Modalidad])) = 'Presencial' THEN [Estudiantes Totales] ELSE 0 END) AS total_general_presencial,
                SUM([Estudiantes Totales]) AS total_general
            FROM dbo.[Poblacion_Estudiantil2]
            WHERE [Centro Universitario] = :centro_id
              AND [Año] = :anio
              AND REPLACE(RTRIM(LTRIM([Nivel Académico])), CHAR(160), '') IN ('Pregrado', 'Posgrado')
              AND {clausula_poblacion}
        """)

        query_generos = text(f"""
            SELECT
                SUM(CASE WHEN [Género] = 'Masculino' THEN [Estudiantes Totales] ELSE 0 END) AS hombres,
                SUM(CASE WHEN [Género] = 'Femenino'  THEN [Estudiantes Totales] ELSE 0 END) AS mujeres
            FROM dbo.[Caracterizacion_Estudiantes]
            WHERE [Centro Universitario] = :centro_id
              AND [Año] = :anio
              AND {clausula_poblacion}
        """)

        params = {
            "centro_id": nombre_bd,
            "anio": config["anio"],
        }

        with engine.connect() as conn:
            row_pob = conn.execute(query_poblacion, params).mappings().first()
            row_gen = conn.execute(query_generos, params).mappings().first()

        print(f"row_pob: {dict(row_pob) if row_pob else 'NONE'}")
        print(f"row_gen: {dict(row_gen) if row_gen else 'NONE'}")

        resultado = dict(row_pob) if row_pob else {}
        resultado["hombres"] = row_gen["hombres"] if row_gen else None
        resultado["mujeres"] = row_gen["mujeres"] if row_gen else None
        return resultado

    except Exception as e:
        print(f"ERROR query_student_summary: {e}")
        return {}


def query_proyecciones(engine, centro_id, config):
    try:
        nombre_bd = resolver_centro_id(centro_id)
        prefijo = obtener_prefijo_periodo(config)
        filtro_atributo = f"%{prefijo}%"
        anio_inicio = int(config.get("anio", 2026))
        print(
            f"query_proyecciones: '{nombre_bd}' - filtro atributo: '{filtro_atributo}' (años {anio_inicio} a 2030)"
        )

        query = text("""
            SELECT
                [Nivel Académico],
                [Nivel de Formación],
                [Modalidad],
                [Periodicidad],
                [Tipo de Estudiante],
                [Tipo de Información],
                [Año],
                SUM([Valor]) AS [Valor]
            FROM dbo.[Proyeccion_Estudiantes]
            WHERE [Centro Universitario] = :centro_id
              AND [Atributo] LIKE :atributo
              AND [Año] BETWEEN :anio_inicio AND 2030
            GROUP BY
                [Nivel Académico],
                [Nivel de Formación],
                [Modalidad],
                [Periodicidad],
                [Tipo de Estudiante],
                [Tipo de Información],
                [Año]
        """)
        with engine.connect() as conn:
            rows = (
                conn.execute(
                    query,
                    {
                        "centro_id": nombre_bd,
                        "atributo": filtro_atributo,
                        "anio_inicio": anio_inicio,
                    },
                )
                .mappings()
                .all()
            )
        normalizadas = [normalizar_fila_proyecciones(dict(r)) for r in rows]
        print(f"query_proyecciones: {len(normalizadas)} filas")
        return normalizadas
    except Exception as e:
        print(f"ERROR query_proyecciones: {e}")
        return []


def query_matriculados(engine, centro_id, config):
    try:
        nombre_bd = resolver_centro_id(centro_id)
        filtros = obtener_filtros_periodo(config)
        clausula_poblacion = filtros["clausula_poblacion"]
        print(f"query_matriculados: '{nombre_bd}' - {config}")

        query = text(f"""
            SELECT
                REPLACE(RTRIM(LTRIM([Nivel Académico])), CHAR(160), '') AS nivel_academico,
                RTRIM(LTRIM([Modalidad])) AS modalidad,
                SUM([Estudiantes Nuevos]) AS nuevos_matriculados,
                SUM([Estudiantes Continuos]) AS continuos_matriculados,
                SUM([Estudiantes Totales]) AS totales_matriculados
            FROM dbo.[Poblacion_Estudiantil2]
            WHERE [Centro Universitario] = :centro_id
              AND [Año] = :anio
              AND REPLACE(RTRIM(LTRIM([Nivel Académico])), CHAR(160), '') IN ('Pregrado', 'Posgrado')
              AND {clausula_poblacion}
            GROUP BY
                REPLACE(RTRIM(LTRIM([Nivel Académico])), CHAR(160), ''),
                RTRIM(LTRIM([Modalidad]))
        """)
        params = {
            "centro_id": nombre_bd,
            "anio": config["anio"],
        }
        with engine.connect() as conn:
            rows = conn.execute(query, params).mappings().all()

        resultado = [
            {
                "nivel_academico": str(r["nivel_academico"]).strip(),
                "modalidad": str(r["modalidad"]).strip(),
                "nuevos_matriculados": int(r["nuevos_matriculados"] or 0),
                "continuos_matriculados": int(r["continuos_matriculados"] or 0),
                "totales_matriculados": int(r["totales_matriculados"] or 0),
            }
            for r in rows
        ]
        print(f"query_matriculados: {len(resultado)} filas")
        return resultado

    except Exception as e:
        print(f"ERROR query_matriculados: {e}")
        return []


def query_desercion(engine, centro_id):
    try:
        nombre_centro = resolver_centro_id(centro_id)

        query = text("""
            SELECT
                [Rectoria] AS rectoria,
                [Centro Universitario] AS centro_universitario,
                [Año] AS año,
                [Modalidad] AS modalidad,
                [Desercion] * 100 AS desercion_porcentaje
            FROM dbo.Desercion_Proyecciones
            WHERE
                [Centro Universitario] = :centro_id
            ORDER BY
                [Año],
                [Modalidad];
        """)

        with engine.connect() as conn:
            rows = conn.execute(query, {"centro_id": nombre_centro}).mappings().all()

        resultado = [
            {
                "rectoria": str(r["rectoria"]).strip() if r["rectoria"] else "",
                "centro_universitario": (
                    str(r["centro_universitario"]).strip()
                    if r["centro_universitario"]
                    else ""
                ),
                "año": int(r["año"]),
                "modalidad": str(r["modalidad"]).strip() if r["modalidad"] else "",
                "desercion_porcentaje": float(r["desercion_porcentaje"] or 0),
            }
            for r in rows
        ]

        print(f"query_desercion: {len(resultado)} filas para '{nombre_centro}'")

        return resultado

    except Exception as e:
        print(f"ERROR query_desercion: {e}")
        return []


def query_oferta(engine, centro_id, config=None):
    try:
        nombre_centro = resolver_centro_id(centro_id)
        print(f"query_oferta: '{nombre_centro}'")

        query = text("""
            SELECT
                [Año] AS año,
                [Periodo] AS periodicidad,
                [Nivel Académico] AS nivel_academico,
                [Modalidad] AS modalidad,
                COUNT(DISTINCT [SNIES]) AS snies_unico
            FROM dbo.Proyeccion_Estudiantes
            WHERE
                [Nivel Académico] IN ('Pregrado', 'Posgrado')
                AND [Modalidad] IN ('Distancia', 'Presencial')
                AND [Tipo de Información] = 'Meta'
                AND [Tipo de Estudiante] = 'Nuevos'
                AND [Periodo] IN ('Q1', 'S1')
                AND [Centro Universitario] = :centro
                AND [Año] BETWEEN :anio_desde AND :anio_hasta
            GROUP BY
                [Año],
                [Periodo],
                [Nivel Académico],
                [Modalidad]
            ORDER BY
                [Nivel Académico],
                [Modalidad],
                [Año],
                [Periodo];
        """)

        params = {
            "centro": nombre_centro,
            "anio_desde": 2026,
            "anio_hasta": 2030,
        }

        with engine.connect() as conn:
            rows = conn.execute(query, params).mappings().all()

        resultado = [
            {
                "año": int(r["año"]),
                "nivel_academico": (
                    str(r["nivel_academico"]).strip() if r["nivel_academico"] else ""
                ),
                "modalidad": str(r["modalidad"]).strip() if r["modalidad"] else "",
                "periodicidad": (
                    str(r["periodicidad"]).strip() if r["periodicidad"] else ""
                ),
                "snies_unico": int(r["snies_unico"]),
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
    return {
        "status": "ok",
        "conexion_bd": engine is not None,
        "ultimo_error": _ultimo_error,
    }


@app.get("/api/cache/refresh")
async def refresh_cache(api_key: str = Depends(verificar_api_key)):
    centros_en_cache = list(_cache.keys())
    _cache.clear()
    print(f"[CACHE] Cache limpiado manualmente. Centros eliminados: {centros_en_cache}")
    return {
        "status": "ok",
        "mensaje": "Caché limpiado. La próxima consulta de cada centro recargará datos frescos desde Azure.",
        "centros_eliminados": centros_en_cache,
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
        "centros": estado,
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
        # Obtener configuración centralizada de Azure SQL una sola vez
        config = obtener_configuracion(engine)

        results = await asyncio.gather(
            run_query(query_indicators, engine, centro_id),
            run_query(query_student_summary, engine, centro_id, config),
            run_query(query_proyecciones, engine, centro_id, config),
            run_query(query_matriculados, engine, centro_id, config),
            run_query(query_desercion, engine, centro_id),
            run_query(query_oferta, engine, centro_id, config),
        )
        response = {
            "indicators": results[0],
            "studentSummary": results[1],
            "proyecciones": results[2],
            "matriculados": results[3],
            "matriculados2026": results[3],  # Compatibilidad con frontend
            "desercion": results[4],
            "oferta": results[5],
        }
        print(f"Tiempo total: {time.time() - t0:.2f}s")
        set_cached(centro_id, response)
        return response

    except HTTPException:
        raise
    except Exception as e:
        print("ERROR:", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/observatorio/page2/{centro_id}")
async def get_page2_data(
    centro_id: str,
    api_key: str = Depends(verificar_api_key),
):
    return await get_observatorio_completo(centro_id, api_key)


@app.get("/api/configuracion")
async def get_configuracion(
    api_key: str = Depends(verificar_api_key),
):
    engine = conectar_bd()

    if not engine:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")

    try:
        config = obtener_configuracion(engine)

        return {
            "status": "ok",
            "configuracion": config,
            "atributo_proyeccion": obtener_codigo_atributo(config),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/configuracion")
async def actualizar_configuracion(
    config: ConfiguracionRequest,
    api_key: str = Depends(verificar_api_key),
):
    engine = conectar_bd()

    if not engine:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")

    try:
        # Validar y normalizar a uno de los 5 casos soportados
        filtros = obtener_filtros_periodo(
            {"periodo": config.periodo, "periodicidad": config.periodicidad}
        )

        nueva_config = {
            "anio": config.anio,
            "periodo": filtros["periodo_guardado"],
            "periodicidad": filtros["periodicidad_guardada"],
        }

        atributo = obtener_codigo_atributo(nueva_config)

        query = text("""
            UPDATE dbo.Configuracion_Observatorio
            SET
                anio = :anio,
                periodo = :periodo,
                periodicidad = :periodicidad,
                fecha_actualizacion = GETDATE()
            WHERE id = 1
        """)

        with engine.begin() as conn:
            resultado = conn.execute(query, nueva_config)

        if resultado.rowcount == 0:
            raise HTTPException(
                status_code=500,
                detail="No existe el registro de configuración con id=1 en dbo.Configuracion_Observatorio",
            )

        # Limpiar automáticamente la memoria caché para forzar datos frescos
        centros_eliminados = list(_cache.keys())
        _cache.clear()
        print(
            f"[CACHE] Cache limpiado tras actualizar configuracion. Centros eliminados: {centros_eliminados}"
        )

        return {
            "status": "ok",
            "mensaje": "Configuración actualizada correctamente",
            "caso_periodo": filtros["periodo_guardado"],
            "descripcion": filtros["descripcion"],
            "configuracion": nueva_config,
            "atributo_proyeccion": atributo,
            "cache_limpiado": True,
            "centros_eliminados": centros_eliminados,
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="localhost", port=8000, reload=True)
