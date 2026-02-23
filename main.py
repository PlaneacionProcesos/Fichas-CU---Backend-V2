import os
import time
import traceback
import socket
import urllib.parse
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# 1. Cargar variables de entorno
load_dotenv()

DB_SERVER = os.getenv("DB_SERVER")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_PORT = os.getenv("DB_PORT", "1433")
DB_NAME = "db360"
DB_DRIVER = os.getenv("DB_DRIVER", "pymssql")  # Puede ser 'pymssql' o 'pyodbc'

# Mostrar configuración al iniciar (sin contraseña)
print("=" * 60)
print("CONFIGURACION DE LA API")
print("=" * 60)
print(f"DB_SERVER: {DB_SERVER}")
print(f"DB_USER: {DB_USER}")
print(f"DB_PORT: {DB_PORT}")
print(f"DB_NAME: {DB_NAME}")
print(f"DB_DRIVER: {DB_DRIVER}")
print(f"DB_PASS: {'*' * len(DB_PASS) if DB_PASS else 'NO CONFIGURADA'}")
print("=" * 60)

if not all([DB_SERVER, DB_USER, DB_PASS]):
    print("ERROR CRITICO: Faltan credenciales")
    raise ValueError("Faltan credenciales críticas en el entorno")
else:
    print("Credenciales basicas configuradas correctamente")

# 2. Configuración de Seguridad
ORIGENES_PERMITIDOS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "https://ficha-cu.vercel.app",
]
print(f"Origenes permitidos: {ORIGENES_PERMITIDOS}")

# 3. Crear aplicación FastAPI
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGENES_PERMITIDOS,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# 4. Variables para almacenar el engine y errores
_engine_cache = None
_ultima_conexion = None
_total_conexiones = 0
_conexiones_fallidas = 0
_ultimo_error = None

def get_connection_string():
    """Construye la cadena de conexión según el driver seleccionado."""
    if DB_DRIVER == "pyodbc":
        # Para pyodbc necesitas ODBC Driver 17 para SQL Server
        params = urllib.parse.quote_plus(
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={DB_SERVER},{DB_PORT};"
            f"DATABASE={DB_NAME};"
            f"UID={DB_USER};"
            f"PWD={DB_PASS};"
            f"Encrypt=yes;TrustServerCertificate=no;"
        )
        return f"mssql+pyodbc:///?odbc_connect={params}"
    else:
        # pymssql por defecto
        return f"mssql+pymssql://{DB_USER}:{DB_PASS}@{DB_SERVER}:{DB_PORT}/{DB_NAME}"

def conectar_bd():
    """
    Establece conexión con la base de datos db360 en Azure SQL.
    Retorna el engine si tiene éxito, None en caso contrario.
    """
    global _engine_cache, _ultima_conexion, _total_conexiones, _conexiones_fallidas, _ultimo_error

    print("\nIntentando conectar a la base de datos...")

    try:
        print(f"   Servidor: {DB_SERVER}:{DB_PORT}")
        print(f"   Base datos: {DB_NAME}")
        print(f"   Usuario: {DB_USER}")
        print(f"   Driver: {DB_DRIVER}")

        start_time = time.time()

        # Cadena de conexión
        connection_string = get_connection_string()
        # Ofuscar contraseña para logs
        conn_str_debug = connection_string.replace(DB_PASS, '*' * len(DB_PASS))
        print(f"   Connection string: {conn_str_debug}")

        # Parámetros comunes
        connect_args = {}
        if DB_DRIVER == "pymssql":
            connect_args = {
                "timeout": 30,
                "login_timeout": 30,
                "charset": "UTF-8",
                "tds_version": "7.4"
            }

        engine = create_engine(
            connection_string,
            connect_args=connect_args,
            pool_pre_ping=True,
            pool_recycle=1800,
            pool_size=5,
            max_overflow=10,
            echo=False
        )

        # Probar la conexión con SELECT 1
        print("   Probando conexion con SELECT 1...")
        test_start = time.time()
        with engine.connect() as conn:
            test_result = conn.execute(text("SELECT 1")).scalar()
            test_elapsed = time.time() - test_start
            print(f"   Prueba de conexion exitosa en {test_elapsed:.2f}s (resultado: {test_result})")

        # Guardar en caché
        _engine_cache = engine
        _ultima_conexion = time.strftime("%Y-%m-%d %H:%M:%S")
        _total_conexiones += 1
        _ultimo_error = None

        total_elapsed = time.time() - start_time

        # Mensaje de éxito
        print("\n" + "=" * 60)
        print("CONEXION ESTABLECIDA EXITOSAMENTE")
        print("=" * 60)
        print(f"Servidor: {DB_SERVER}")
        print(f"Base de datos: {DB_NAME}")
        print(f"Usuario: {DB_USER}")
        print(f"Puerto: {DB_PORT}")
        print(f"Driver: {DB_DRIVER}")
        print(f"Tiempo de conexion: {total_elapsed:.2f}s")
        print(f"Conexiones exitosas totales: {_total_conexiones}")
        print("=" * 60 + "\n")

        return engine

    except Exception as e:
        elapsed = time.time() - start_time if 'start_time' in locals() else 0
        error_msg = str(e)
        _ultimo_error = error_msg
        print(f"\nERROR DE CONEXION despues de {elapsed:.2f}s")
        print(f"Error: {error_msg}")
        traceback.print_exc()

        _conexiones_fallidas += 1
        return None

# 5. Endpoints de monitoreo
@app.get("/health")
async def health_check():
    """Endpoint de salud que muestra estado de conexión y último error"""
    global _engine_cache
    if _engine_cache is None:
        conectar_bd()
    if _engine_cache:
        return {"status": "ok", "conexion": "establecida"}
    else:
        return {
            "status": "error",
            "conexion": "no establecida",
            "ultimo_error": _ultimo_error
        }

@app.get("/api/connection-status")
async def connection_status():
    global _engine_cache
    if _engine_cache is None:
        conectar_bd()
    return {
        "conexion_activa": _engine_cache is not None,
        "base_datos": DB_NAME,
        "servidor": DB_SERVER,
        "puerto": DB_PORT,
        "driver": DB_DRIVER,
        "ultima_conexion": _ultima_conexion,
        "total_conexiones_exitosas": _total_conexiones,
        "conexiones_fallidas": _conexiones_fallidas,
        "ultimo_error": _ultimo_error
    }

@app.get("/api/diagnostico")
async def diagnostico():
    """Realiza pruebas de red y conexión para diagnosticar problemas."""
    import socket
    import dns.resolver  # necesitas instalar dnspython

    resultados = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "servidor": DB_SERVER,
        "puerto": DB_PORT,
        "driver": DB_DRIVER,
        "pruebas": {}
    }

    # 1. Resolución DNS
    try:
        start = time.time()
        ip = socket.gethostbyname(DB_SERVER)
        elapsed = time.time() - start
        resultados["pruebas"]["dns"] = {
            "exito": True,
            "ip": ip,
            "tiempo_ms": round(elapsed * 1000, 2)
        }
    except Exception as e:
        resultados["pruebas"]["dns"] = {
            "exito": False,
            "error": str(e)
        }

    # 2. Conexión TCP al puerto
    if "ip" in resultados["pruebas"].get("dns", {}):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            start = time.time()
            sock.connect((resultados["pruebas"]["dns"]["ip"], int(DB_PORT)))
            elapsed = time.time() - start
            sock.close()
            resultados["pruebas"]["tcp"] = {
                "exito": True,
                "tiempo_ms": round(elapsed * 1000, 2)
            }
        except Exception as e:
            resultados["pruebas"]["tcp"] = {
                "exito": False,
                "error": str(e)
            }

    # 3. Prueba de conexión con la base de datos (SELECT 1)
    try:
        # Usar una conexión nueva (no cacheada) para probar
        connection_string = get_connection_string()
        connect_args = {}
        if DB_DRIVER == "pymssql":
            connect_args = {"timeout": 10, "login_timeout": 10}
        engine_test = create_engine(connection_string, connect_args=connect_args)
        start = time.time()
        with engine_test.connect() as conn:
            result = conn.execute(text("SELECT 1")).scalar()
        elapsed = time.time() - start
        resultados["pruebas"]["bd_select"] = {
            "exito": True,
            "resultado": result,
            "tiempo_ms": round(elapsed * 1000, 2)
        }
    except Exception as e:
        resultados["pruebas"]["bd_select"] = {
            "exito": False,
            "error": str(e)
        }

    return resultados

# 6. Ejecución con Uvicorn
if __name__ == "__main__":
    import uvicorn

    # Intentar conectar al iniciar
    engine = conectar_bd()
    if engine:
        print("API iniciada con conexion a base de datos")
    else:
        print("ADVERTENCIA: API iniciada SIN conexion a base de datos")

    port = int(os.getenv("PORT", 8000))
    reload_mode = False if os.getenv("RAILWAY_ENVIRONMENT") else True

    print(f"\nIniciando servidor en puerto: {port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=reload_mode)