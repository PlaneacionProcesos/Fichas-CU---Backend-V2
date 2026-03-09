# API Fichas Centro Universitario (FastAPI)
Esta es una API robusta construida con FastAPI para gestionar y consultar indicadores, proyecciones y datos estadísticos de estudiantes. Está diseñada para conectarse a una base de datos SQL Server (MSSQL) y servir datos normalizados a un frontend moderno.

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

DB_SERVER=tu_servidor.database.windows.net

DB_USER= (usuario de consulta de DB)

DB_PASS= (contraseña de consulta en db)

DB_PORT=1433

DB_NAME= (nombre de db)

API_KEY_SECRET=(una clave muy segura)


### 2. Instalación de dependencias
Bash
pip install fastapi uvicorn sqlalchemy pymssql python-dotenv
🔒 Seguridad
Todos los endpoints (excepto / y /health) requieren una clave de API. Debes incluirla en las cabeceras de tu petición HTTP:

Header	Valor
X-API-Key	El valor definido en API_KEY_SECRET

## 🛣️ Endpoints
Públicos / Monitoreo
GET /: Verifica que la API esté en línea.

GET /health: Estado detallado de la conexión a la base de datos y últimos errores registrados.

### Datos del Observatorio
GET /api/observatorio/completo/{centro_id}: Retorna un objeto masivo con toda la información necesaria para el tablero:

indicators: Proyecciones anuales (2025-2030).

studentSummary: Resumen de población por género y modalidad.

proyecciones: Datos consolidados por nivel y año.

matriculados2026: Comparativa de nuevos vs. antiguos.

desercion: Tasas de deserción por modalidad.

oferta: Conteo de programas únicos (SNIES).

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
