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
DB_USER   = os.getenv("DB_USER")
DB_PASS   = os.getenv("DB_PASS")
DB_PORT   = os.getenv("DB_PORT", "1433")
DB_NAME   = os.getenv("DB_NAME", "db360")
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
_engine_cache      = None
_ultima_conexion   = None
_total_conexiones  = 0
_conexiones_fallidas = 0
_ultimo_error      = None

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

        _engine_cache      = engine
        _ultima_conexion   = time.strftime("%Y-%m-%d %H:%M:%S")
        _total_conexiones += 1
        _ultimo_error      = None
        print("✅ Conexión a BD establecida correctamente")
        return engine

    except Exception as e:
        _ultimo_error        = str(e)
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
        fila[str(key).strip()] = value
    return fila


def normalizar_fila_proyecciones(row: dict) -> dict:
    """
    Mapea los nombres de columna originales de Proyecciones_cu
    a snake_case para que el modelo JS los consuma de forma consistente.

    Valores importantes confirmados en BD:
      Tipo de Estudiante : 'Nuevos' | 'Continuos' | 'Totales'
      Tipo de Información: 'Proyectado' (solo 2025-2026)
                           'Meta'       (2025-2030)
                           'Histórico'  (2017-2026)
    """
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


# Mapeo de centro_id del frontend al nombre exacto en la BD
CENTRO_ID_MAPA = {
    "centro-engativa":               "Especial Minuto de Dios - Engativ\u00e1",
    "centro-kennedy":                "Kennedy",
    "centro-santa-fe-las-cruces":    "Las Cruces - Santa Fe",
    "centro-perdomo-ciudad-bolivar": "Perdomo - Ciudad Bol\u00edvar",
    "centro-san-cristobal-usaquen":  "San Crist\u00f3bal Norte - Usaqu\u00e9n",
}

def resolver_centro_id(centro_id: str) -> str:
    """
    Convierte el centro_id del frontend (ej: 'centro-kennedy')
    al nombre exacto que usa la BD (ej: 'Kennedy').
    Si no est\u00e1 en el mapa, devuelve el valor limpio tal cual
    por si ya viene con el nombre real.
    """
    limpio = centro_id.strip().replace("\xa0", "").strip()
    return CENTRO_ID_MAPA.get(limpio, limpio)

def limpiar_centro_id(centro_id: str) -> str:
    return centro_id.strip().replace("\xa0", "").strip()

# ============================================================================
# CONSULTAS
# ============================================================================

def query_indicators(engine, centro_id):
    try:
        centro_limpio = limpiar_centro_id(centro_id)
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT
                    RTRIM(LTRIM([Nombre Corto])) AS [Nombre Corto],
                    [2025], [2026], [2027], [2028], [2029],
                    RTRIM(LTRIM([2030])) AS [2030]
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
                    "2030": fila.get("2030"),
                })
            print(f"query_indicators -> filas: {len(rows)}")
            return rows

    except Exception as e:
        print(f"❌ ERROR query_indicators: {e}")
        return []


def query_student_summary(engine, centro_id):
    try:
        query_poblacion = text("""
            SELECT
                SUM(CASE WHEN [Nivel] NOT IN ('Maestría','Especialización') AND [Modalidad]='Distancia'  THEN [Estudiantes Totales] ELSE 0 END) AS pregradoDistancia,
                SUM(CASE WHEN [Nivel] NOT IN ('Maestría','Especialización') AND [Modalidad]='Presencial' THEN [Estudiantes Totales] ELSE 0 END) AS pregradoPresencial,
                SUM(CASE WHEN [Nivel] NOT IN ('Maestría','Especialización')                              THEN [Estudiantes Totales] ELSE 0 END) AS pregradoTotal,
                SUM(CASE WHEN [Nivel] IN     ('Maestría','Especialización') AND [Modalidad]='Distancia'  THEN [Estudiantes Totales] ELSE 0 END) AS posgradoDistancia,
                SUM(CASE WHEN [Nivel] IN     ('Maestría','Especialización') AND [Modalidad]='Presencial' THEN [Estudiantes Totales] ELSE 0 END) AS posgradoPresencial,
                SUM(CASE WHEN [Nivel] IN     ('Maestría','Especialización')                              THEN [Estudiantes Totales] ELSE 0 END) AS posgradoTotal,
                SUM(CASE WHEN [Modalidad]='Distancia'  THEN [Estudiantes Totales] ELSE 0 END) AS totalGeneralDistancia,
                SUM(CASE WHEN [Modalidad]='Presencial' THEN [Estudiantes Totales] ELSE 0 END) AS totalGeneralPresencial,
                SUM([Estudiantes Totales]) AS totalGeneral
            FROM [dbo].[Poblacion Estudiantil]
            WHERE [Rectoría] = 'Bogotá'
              AND [año] = 2026
              AND [Cuatrimestre] IN ('S1', 'Q1')
        """)

        query_generos = text("""
            SELECT
                SUM(CASE WHEN [Género]='Masculino' THEN [Estudiantes totales] ELSE 0 END) AS hombres,
                SUM(CASE WHEN [Género]='Femenino'  THEN [Estudiantes totales] ELSE 0 END) AS mujeres
            FROM [dbo].[Caracterizacion_Estudiantil]
            WHERE [Rectoría] = 'Bogotá'
              AND [año] = 2026
        """)

        with engine.connect() as conn:
            row_pob = conn.execute(query_poblacion).mappings().first()
            row_gen = conn.execute(query_generos).mappings().first()

        resultado = dict(row_pob) if row_pob else {}
        resultado["hombres"] = row_gen["hombres"] if row_gen else None
        resultado["mujeres"] = row_gen["mujeres"] if row_gen else None
        return resultado

    except Exception as e:
        print(f"❌ ERROR query_student_summary: {e}")
        return {}


def query_proyecciones(engine, centro_id):
    """
    Trae las filas de Proyecciones_cu para el centro dado,
    agrupadas por las dimensiones clave y sumando el Valor.

    Filtro de Atributo:
      - Para Tablas 1, 2, 4 (Meta): solo filas cuyo Atributo contiene 'Q1/S1'
        para evitar triplicar (Q1/S1, Q2, Q3/S2).
        Ej: 'C-M-Q1/S1-2026', 'N-M-Q1/S1-2026', 'T-M-Q1/S1-2026'
      - Para Tabla 3 (comparativa 2026): igual, solo Q1/S1.

    Se agrupa por: nivel_academico, nivel_formacion, modalidad, periodicidad,
                   tipo_estudiante, tipo_informacion, año
    y se suma Valor para consolidar los programas del centro.
    """
    try:
        nombre_bd = resolver_centro_id(centro_id)
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
            FROM [dbo].[Proyecciones_cu]
            WHERE [Centro Universitario] = :centro_id
              AND [Atributo] LIKE '%Q1/S1%'
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
            rows = conn.execute(query, {"centro_id": nombre_bd}).mappings().all()

        normalizadas = [normalizar_fila_proyecciones(dict(r)) for r in rows]
        print(f"query_proyecciones -> filas: {len(normalizadas)}")
        return normalizadas

    except Exception as e:
        print(f"❌ ERROR query_proyecciones: {e}")
        return []


def query_matriculados_2026(engine, centro_id):
    """
    Trae el recuento REAL de estudiantes de [Poblacion Estudiantil]
    para el centro dado, año 2026, periodos S1 y Q1.
    
    - nuevos_matriculados    ← SUM([Estudiantes Nuevos])
    - continuos_matriculados ← SUM([Estudiantes Continuos])
    - totales_matriculados   ← SUM([Estudiantes Totales])
    
    Agrupado por Pregrado/Posgrado y Modalidad.
    """
    try:
        nombre_bd = resolver_centro_id(centro_id)
        query = text("""
            SELECT
                CASE
                    WHEN [Nivel] IN ('Maestría', 'Especialización', 'Doctorado')
                    THEN 'Posgrado'
                    ELSE 'Pregrado'
                END                           AS nivel_academico,
                RTRIM(LTRIM([Modalidad]))      AS modalidad,
                SUM([Estudiantes Nuevos])      AS nuevos_matriculados
            FROM [dbo].[Poblacion Estudiantil]
            WHERE [Centro Universitario] = :centro_id
              AND [año]          = 2026
              AND [Cuatrimestre] IN ('S1', 'Q1')
            GROUP BY
                CASE
                    WHEN [Nivel] IN ('Maestría', 'Especialización', 'Doctorado')
                    THEN 'Posgrado'
                    ELSE 'Pregrado'
                END,
                RTRIM(LTRIM([Modalidad]))
        """)
        with engine.connect() as conn:
            rows = conn.execute(query, {"centro_id": nombre_bd}).mappings().all()

        resultado = [
            {
                "nivel_academico":       str(r["nivel_academico"]).strip(),
                "modalidad":             str(r["modalidad"]).strip(),
                "nuevos_matriculados":   int(r["nuevos_matriculados"]   or 0),
                "continuos_matriculados":int(r["continuos_matriculados"] or 0),
                "totales_matriculados":  int(r["totales_matriculados"]  or 0),
            }
            for r in rows
        ]

        print(f"query_matriculados_2026 -> centro='{nombre_bd}' filas: {len(resultado)}")
        for r in resultado:
            print(f"  {r['nivel_academico']} | {r['modalidad']} | "
                  f"nuevos={r['nuevos_matriculados']} | "
                  f"continuos={r['continuos_matriculados']} | "
                  f"totales={r['totales_matriculados']}")
        return resultado

    except Exception as e:
        print(f"❌ ERROR query_matriculados_2026: {e}")
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
            rows = conn.execute(query, {"centro_id": centro_limpio}).mappings().all()

        desercion = []
        for row in rows:
            fila = normalizar_fila_indicadores(dict(row))
            nombre = fila.get("Nombre Corto", "")
            modalidad = "Presencial" if "Presencial" in nombre else "Distancia"
            for año in ["2025", "2026", "2027", "2028", "2029", "2030"]:
                valor = fila.get(año)
                if valor is not None and valor != "":
                    desercion.append({"año": año, "modalidad": modalidad, "porcentaje": valor})
        return desercion

    except Exception as e:
        print(f"❌ ERROR query_desercion: {e}")
        return []


def query_oferta(engine, centro_id):
    """
    Cuenta SNIES únicos por año, nivel académico, modalidad y periodicidad
    directamente desde Proyecciones_cu.
    Cada SNIES distinto cuenta como 1 programa de oferta.
    """
    try:
        nombre_bd = resolver_centro_id(centro_id)
        query = text("""
            SELECT
                CAST([Año] AS VARCHAR(4))  AS año,
                [Nivel Académico]          AS nivel_academico,
                [Modalidad]                AS modalidad,
                [Periodicidad]             AS periodicidad,
                COUNT(DISTINCT [Snies])    AS snies_unico
            FROM [dbo].[Proyecciones_cu]
            WHERE [Centro Universitario] = :centro_id
              AND [Snies] IS NOT NULL
              AND [Año] BETWEEN 2026 AND 2030
            GROUP BY
                [Año],
                [Nivel Académico],
                [Modalidad],
                [Periodicidad]
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
        print(f"query_oferta (Proyecciones_cu) -> centro='{nombre_bd}' filas: {len(resultado)}")
        # Debug: muestra muestra de valores únicos para verificar
        niveles = set(r["nivel_academico"] for r in resultado)
        modalidades = set(r["modalidad"] for r in resultado)
        periodicidades = set(r["periodicidad"] for r in resultado)
        print(f"  niveles={niveles} | modalidades={modalidades} | periodicidades={periodicidades}")
        return resultado

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
        "ultimo_error": _ultimo_error,
    }


@app.get("/api/observatorio/completo/{centro_id}")
async def get_observatorio_completo(
    centro_id: str,
    api_key: str = Depends(verificar_api_key),
):
    engine = conectar_bd()
    if not engine:
        raise HTTPException(status_code=503, detail="Base de datos no disponible")

    try:
        return {
            "indicators":        query_indicators(engine, centro_id),
            "studentSummary":    query_student_summary(engine, centro_id),
            "proyecciones":      query_proyecciones(engine, centro_id),
            "matriculados2026":  query_matriculados_2026(engine, centro_id),
            "desercion":         query_desercion(engine, centro_id),
            "oferta":            query_oferta(engine, centro_id),
        }
    except Exception as e:
        print("🔥 ERROR REAL:", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/observatorio/page2/{centro_id}")
async def get_page2_data(
    centro_id: str,
    api_key: str = Depends(verificar_api_key),
):
    return await get_observatorio_completo(centro_id, api_key)

# ============================================================================
# RUN
# ============================================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)