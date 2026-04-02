# 1. Usamos una imagen de Python oficial y ligera
FROM python:3.10-slim

# 2. Evitamos que Python genere archivos .pyc y permitimos ver logs en tiempo real
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 3. Establecemos el directorio de trabajo dentro del contenedor
WORKDIR /app

# 4. Instalamos dependencias básicas del sistema para compilar algunas librerías si fuera necesario
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 5. Copiamos el archivo de requerimientos e instalamos las librerías
# Copiar primero el requirements permite que Docker cachee este paso si no hay cambios
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copiamos todo el contenido de la carpeta actual al contenedor
COPY . .

# 7. Informamos que el contenedor escuchará en el puerto 8080 (estándar de Cloud Run)
EXPOSE 8080

# 8. Comando para ejecutar la aplicación
# Usamos la variable de entorno $PORT que Google asigna automáticamente
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]