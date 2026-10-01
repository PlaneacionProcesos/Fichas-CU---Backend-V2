# API Fichas Centro Universitario (FastAPI)
Esta es una API robusta construida con FastAPI para gestionar y consultar indicadores, proyecciones y datos estadísticos de estudiantes. Está diseñada para conectarse a una base de datos SQL Server (MSSQL) y servir datos normalizados a un frontend moderno.

link: api-cu-production.up.railway.app

## 🚀 Características Principales
FastAPI Framework: Alto rendimiento y facilidad de uso.

### Conexión SQL Server: 
Integración mediante SQLAlchemy y pymssql con sistema de caché de conexión y auto-recuperación.

### Seguridad:
Protección de endpoints mediante X-API-Key en el encabezado.

### CORS:
Configurado para aceptar peticiones de dominios locales y en produccion.

### Normalización:
Procesamiento de datos desde la DB para entregar JSON limpios y en formato snake_case.

## 🛠️ Requisitos e Instalación
### 1. Variables de Entorno
Crea un archivo .env en la raíz del proyecto (o configúralas en el panel de Railway):

Fragmento de código

DB_HOST=tu_servidor.database.windows.net

DB_USER= (usuario de consulta de DB)

DB_PASS= (contraseña de consulta en db)

DB_PORT=1433

DB_NAME= (nombre de db)

API_KEY_SECRET=(una clave muy segura)

REDIS_CACHE_ENABLED=true
REDIS_HOST=host_entregado_por_redis_cloud
REDIS_PORT=puerto_entregado_por_redis_cloud
REDIS_USERNAME=default
REDIS_PASSWORD=contraseña_entregada_por_redis_cloud
REDIS_SSL=true
CACHE_REFRESH_SECRET=secreto_independiente_para_refresh

También puede usarse `REDIS_URL` en lugar de las variables Redis separadas. No
usar variables `VITE_*`: las credenciales son exclusivamente del backend. El pool
está limitado a 4 conexiones por instancia y usa timeouts cortos.

### 2. Instalación de dependencias
Bash
pip install fastapi uvicorn sqlalchemy pymssql python-dotenv
🔒 Seguridad
Todos los endpoints (excepto / y /health) requieren una clave de API. Debes incluirla en las cabeceras de tu petición HTTP:

Header	Valor
X-API-Key	El valor definido en API_KEY_SECRET

## 🛣️ Endpoints

### 🟢 Públicos / Monitoreo
- **`GET /`**: Verifica que la API esté en línea.
- **`GET /health`**: Confirma que la API está en línea sin consultar ni reactivar Azure SQL.

### ⚙️ Configuración del Observatorio (Protegidos con `X-API-Key`)
- **`GET /api/configuracion`**: Consulta la configuración activa en Azure SQL (`dbo.Configuracion_Observatorio`), el caso de período actual y el atributo proyectado calculado.
  - **Respuesta de ejemplo:**
    ```json
    {
      "status": "ok",
      "configuracion": {
        "anio": 2026,
        "periodo": "S1+Q1",
        "periodicidad": "Semestral"
      },
      "atributo_proyeccion": "Q1/S1-2026"
    }
    ```
- **`PUT /api/configuracion`**: Actualiza el año y período en Azure SQL, valida y limpia automáticamente la caché en memoria.
  - **Body (JSON):**
    ```json
    {
      "anio": 2026,
      "periodo": "S1+Q1",
      "periodicidad": "Semestral"
    }
    ```

#### 📌 Los 5 Casos Oficiales de Período Soportados:

| Caso (`periodo`) | Periodicidad | Descripción Académica | Población / Matrícula | Proyecciones |
| :--- | :--- | :--- | :--- | :--- |
| **`S1+Q1`** | `Semestral` | Inicio de Año | `Semestral S1` + `Cuatrimestral Q1` | `Q1/S1` (2026-2030) |
| **`S1+Q2`** | `Semestral` | Semestre 1 + Cuatrimestre 2 | `Semestral S1` + `Cuatrimestral Q2` | `Q1/S1` (2026-2030) |
| **`Q2`** | `Cuatrimestral` | Mitad de Año (Solo Cuatrimestre 2) | `Cuatrimestral Q2` | `Q2` (2026-2030) |
| **`S2+Q2`** | `Semestral` | Semestre 2 + Cuatrimestre 2 | `Semestral S2` + `Cuatrimestral Q2` | `Q3/S2` (2026-2030) |
| **`S2+Q3`** | `Semestral` | Segundo Semestre Tradicional | `Semestral S2` + `Cuatrimestral Q3` | `Q3/S2` (2026-2030) |

*(Nota: También se aceptan alias simples como `S1` $\rightarrow$ `S1+Q1`, `S2` $\rightarrow$ `S2+Q3`, `Q2` $\rightarrow$ `Q2`).*

#### 💻 Ejemplos cURL para cambiar entre los 5 casos:
```powershell
# Caso 1: S1 + Q1
curl.exe -X PUT "http://localhost:8000/api/configuracion" -H "Content-Type: application/json" -H "X-API-Key: TU_API_KEY" -d "{\"anio\": 2026, \"periodo\": \"S1+Q1\", \"periodicidad\": \"Semestral\"}"

# Caso 2: S1 + Q2
curl.exe -X PUT "http://localhost:8000/api/configuracion" -H "Content-Type: application/json" -H "X-API-Key: TU_API_KEY" -d "{\"anio\": 2026, \"periodo\": \"S1+Q2\", \"periodicidad\": \"Semestral\"}"

# Caso 3: Q2
curl.exe -X PUT "http://localhost:8000/api/configuracion" -H "Content-Type: application/json" -H "X-API-Key: TU_API_KEY" -d "{\"anio\": 2026, \"periodo\": \"Q2\", \"periodicidad\": \"Cuatrimestral\"}"

# Caso 4: S2 + Q2
curl.exe -X PUT "http://localhost:8000/api/configuracion" -H "Content-Type: application/json" -H "X-API-Key: TU_API_KEY" -d "{\"anio\": 2026, \"periodo\": \"S2+Q2\", \"periodicidad\": \"Semestral\"}"

# Caso 5: S2 + Q3
curl.exe -X PUT "http://localhost:8000/api/configuracion" -H "Content-Type: application/json" -H "X-API-Key: TU_API_KEY" -d "{\"anio\": 2026, \"periodo\": \"S2+Q3\", \"periodicidad\": \"Semestral\"}"
```

### ⚡ Gestión de Caché (Protegidos con `X-API-Key`)
- **`GET /api/cache/refresh`**: Limpia manualmente todos los centros almacenados en la memoria caché para forzar la recarga desde Azure SQL en la siguiente petición.
- **`GET /api/cache/status`**: Muestra el estado del caché, cantidad de centros en memoria, fechas de carga y tiempo restante de expiración (TTL).

### 📊 Datos del Observatorio (Protegidos con `X-API-Key`)
- **`GET /api/observatorio/sede-bogota`**: Retorna los cinco centros bajo
  `centros`, más `cache_updated_at` y `version`. Sólo lee Redis; un HIT no abre
  SQL. Un MISS o caída de Redis devuelve 503 para evitar estampidas.
- **`GET /api/observatorio/completo/{centro_id}`**: Retorna un objeto consolidado con toda la información necesaria para el tablero según la configuración activa:
  - **`indicators`**: Proyecciones anuales (2025-2030).
  - **`studentSummary`**: Resumen de población por género y modalidad para el año y período configurados.
  - **`proyecciones`**: Datos consolidados por nivel y año filtrados por el atributo activo (ej. `%Q1/S1-2026%`).
  - **`matriculados`** / **`matriculados2026`**: Comparativa de nuevos vs. continuos según la configuración activa.
  - **`desercion`**: Tasas de deserción por modalidad.
  - **`oferta`**: Conteo de programas únicos (SNIES) proyectados en una ventana de 5 años a partir del año configurado.
- **`GET /api/observatorio/page2/{centro_id}`**: Retorna los datos del observatorio para la página 2.

### Actualización explícita de caché

`POST /api/admin/cache/refresh` se protege con `X-Cache-Refresh-Secret`. Adquiere
un bloqueo distribuido con expiración, construye los cinco centros usando una sola
conexión SQLAlchemy y publica mediante una clave temporal y reemplazo atómico. Si
Azure o la construcción fallan, la versión activa anterior se conserva. La caché
no tiene TTL y no se refresca periódicamente.

El workflow `.github/workflows/refresh-cache.yml` ofrece el botón manual
`workflow_dispatch`. Configure únicamente los secrets `CACHE_REFRESH_URL` (URL
completa del endpoint) y `CACHE_REFRESH_SECRET`. Su paso puede reutilizarse tras
una carga de datos exitosa.

Las pruebas se ejecutan sin Azure con `python -m pytest -q`. Cubren HIT sin SQL,
refresh exitoso, conservación ante fallo, bloqueo concurrente, autenticación,
contrato consolidado y reutilización/cierre de conexión. Queda pendiente validar
en octubre contenido y tiempos reales contra Azure. No se introdujeron consultas
por conjunto con `IN/GROUP BY`: deben compararse con datos reales antes de sustituir
las consultas actuales.

## 📊 Mapeo de Centros Universitarios
La API traduce automáticamente los IDs del frontend a los nombres exactos en la base de datos. Algunos ejemplos soportados:

centro-kennedy ➡️ "Kennedy"

centro-engativa ➡️ "Especial Minuto de Dios - Engativá"

centro-perdomo-ciudad-bolivar ➡️ "Perdomo - Ciudad Bolívar"

## 🚀 Despliegue en Railway
Este proyecto está listo para Railway mediante el archivo main.py.

Conecta tu repositorio de GitHub a Railway.

Hay que configurar el comando de inicio de la API con este:
uvicorn main:app --host 0.0.0.0 --port $PORT

Luego se configuran todas las Variables de Entorno en la pestaña Variables del servicio en Railway.

## ⚙️ Estructura del Código
Gestión de Conexión: El motor de la base de datos utiliza un pool_pre_ping=True para evitar conexiones muertas, algo común en entornos de nube.

### Normalización:
Incluye funciones dedicadas a limpiar espacios en blanco (LTRIM/RTRIM) y caracteres especiales (CHAR(160)) que suelen venir en datos de Excel cargados a SQL Server.
