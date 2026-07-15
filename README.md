# Don Pilsen: Agente Cervecero Interactivo

## Instrucciones de Ejecución Rápida

1. **Levantar Odoo y Base de Datos:**
   ```bash
   docker compose up -d
   ```
   *(Odoo disponible en localhost:8069, credenciales: admin/admin)*

2. **Instalar Dependencias del Agente:**
   ```bash
   cd dashboard_externo
   pip install -r requirements.txt
   ```

3. **Configurar API Key:**
   Edita el archivo `dashboard_externo/main.py` y pon tu clave de Groq en la línea ~831:
   ```python
   GROQ_API_KEY = "tu_clave_aqui" 
   ```

4. **Correr el Dashboard:**
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```

5. **Acceder:**
   Entra a `http://localhost:8000` y haz clic en el ícono de cerveza para chatear.
