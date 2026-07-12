FROM python:3.11-slim

# --- Driver ODBC de Microsoft para SQL Server / Azure SQL ---
# Sin esto, pyodbc no encuentra "ODBC Driver 18 for SQL Server" y falla con:
# "Can't open lib 'ODBC Driver 18 for SQL Server' : file not found"
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        gnupg2 \
        apt-transport-https \
        unixodbc \
        unixodbc-dev \
    && curl -sSL -O https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb \
    && dpkg -i packages-microsoft-prod.deb \
    && rm packages-microsoft-prod.deb \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
