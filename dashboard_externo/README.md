# Dashboard Analítico Cervecero (API + Frontend)

Este proyecto contiene el Dashboard Analítico externo que se conecta a la base de datos de Odoo (PostgreSQL) para mostrar indicadores clave (KPIs) de producción de la cervecería.

## 🛠 Requisitos Previos
1. **Python 3.8+** instalado.
2. Contenedores de **Odoo y PostgreSQL** corriendo en el equipo con el puerto de BD expuesto (`5432`).
3. Base de datos creada en Odoo con el nombre exacto: `Cerveza01`.
   *(Nota: si la base de datos tiene otro nombre, debes cambiarlo en el archivo `main.py` línea 25).*

---

## 🚀 Instrucciones de Instalación y Ejecución

### PASO 1: Instalar dependencias de Python
Abre una terminal en esta misma carpeta y ejecuta:
```bash
pip install -r requirements.txt
```

### PASO 2: (Opcional) Cargar Datos Demo
Si la base de datos está vacía y quieres probar los gráficos rápidamente, puedes ejecutar el script de carga de datos demo (esto insertará recetas, lotes y trazabilidad directamente en PostgreSQL):
```bash
python cargar_demo.py
```

### PASO 3: Levantar la API REST (Backend)
Para iniciar el servidor de la API, ejecuta en la terminal:
```bash
uvicorn main:app --reload
```

### PASO 4: Abrir el Dashboard (Frontend)
El frontend no necesita ningún servidor de Node.js o similar.
1. Ve a la carpeta `dashboard_externo` desde el explorador de archivos.
2. Haz **doble clic** en el archivo `index.html`.
