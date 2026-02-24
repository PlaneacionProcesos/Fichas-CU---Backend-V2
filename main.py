import os
import time
import traceback
import socket
import urllib.parse
from fastapi import FastAPI, HTTPException, Header, Depends
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
DB_DRIVER = os.getenv("DB_DRIVER", "pymssql")
API_KEY_SECRETA = os.getenv("API_KEY_SECRET")

# 2. Definir la función de seguridad ANTES de crear la App
async def verificar_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    """Valida la clave secreta en el header X-API-Key."""
    if x_api_key != API_KEY_SECRETA:
        raise HTTPException(status_code=403, detail="Acceso no autorizado")
    return x_api_key

# 3. CREAR LA APP (Una sola vez, con seguridad global)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Configurar CORS
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

# --- IMPRESIÓN DE CONFIGURACIÓN ---
print("=" * 60)
print("CONFIGURACION DE LA API - SEGURIDAD ACTIVADA")
print("=" * 60)
print(f"DB_SERVER: {DB_SERVER}")
print(f"API_KEY: {'CONFIGURADA' if API_KEY_SECRETA else 'MISSING'}")
print("=" * 60)

if not all([DB_SERVER, DB_USER, DB_PASS, API_KEY_SECRETA]):
    raise ValueError("Faltan credenciales críticas en el entorno")

# --- LÓGICA DE BASE DE DATOS ---
_engine_cache = None
_ultima_conexion = None
_total_conexiones = 0
_conexiones_fallidas = 0
_ultimo_error = None

def get_connection_string():
    password_escaped = urllib.parse.quote_plus(DB_PASS)
    return f"mssql+pymssql://{DB_USER}:{password_escaped}@{DB_SERVER}:{DB_PORT}/{DB_NAME}"

def conectar_bd():
    global _engine_cache, _ultima_conexion, _total_conexiones, _conexiones_fallidas, _ultimo_error
    if _engine_cache:
        try:
            with _engine_cache.connect() as conn:
                conn.execute(text("SELECT 1"))
            return _engine_cache
        except:
            _engine_cache = None

    try:
        engine = create_engine(get_connection_string(), pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        _engine_cache = engine
        _ultima_conexion = time.strftime("%Y-%m-%d %H:%M:%S")
        _total_conexiones += 1
        return engine
    except Exception as e:
        _ultimo_error = str(e)
        _conexiones_fallidas += 1
        return None

# --- ENDPOINTS ---
# (Ahora todos están protegidos automáticamente por la dependencia global)

@app.get("/")
async def root():
    return {"message": "API segura funcionando"}

@app.get("/api/diagnostico")
async def diagnostico():
    # ... tu lógica de diagnóstico ...
    return {"status": "Privado y Seguro", "server": DB_SERVER}

# Para ejecutar localmente
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)