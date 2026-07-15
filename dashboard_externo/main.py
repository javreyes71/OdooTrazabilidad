from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional
import httpx
import json
import re
import asyncio
import datetime
import random

app = FastAPI(
    title="Dashboard Analítico ERP API + BIA",
    description="API RESTful con Beer Intelligence Agent (BIA) integrado.",
    version="2.0.0"
)

# Evento de inicio: pre-cargar modelo en RAM al iniciar el servidor
@app.on_event("startup")
async def startup_warmup():
    """Pre-carga LLaMA en RAM al iniciar el servidor para evitar cold-start en la primera consulta."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"http://localhost:11434/api/tags")
            tags = resp.json()
            modelos = [m["name"] for m in tags.get("models", [])]
            if any("llama3.2" in m for m in modelos):
                await client.post(
                    "http://localhost:11434/api/chat",
                    json={
                        "model": "llama3.2",
                        "messages": [{"role": "user", "content": "hola"}],
                        "stream": False,
                        "keep_alive": -1
                    },
                    timeout=60.0
                )
                print("[BIA] LLaMA 3.2 pre-cargado en RAM correctamente.")
            else:
                print("[BIA] Modelo llama3.2 no encontrado en Ollama.")
    except Exception as e:
        print(f"[BIA] Ollama no disponible al iniciar (modo fallback activo): {e}")


# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuración de base de datos PostgreSQL
DB_CONFIG = {
    "dbname": "Cerveza01",
    "user": "odoo",
    "password": "myodoo",
    "host": "localhost",
    "port": "5432"
}

# Configuración de Ollama
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2"


def get_db_connection():
    """Retorna la conexión activa a la base de datos."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error conectando a la base de datos: {e}")


# ─────────────────────────────────────────────
#  FUNCIONES DE CONTEXTO: Extraen datos del ERP
# ─────────────────────────────────────────────

def get_context_lote(lote_name: str) -> str:
    """Obtiene la historia completa de un lote de cocción."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    cc.name AS batch,
                    cc.state,
                    COALESCE(cc.maestro_cervecero, 'No asignado') AS maestro_cervecero,
                    cc.fecha_coccion,
                    cc.fecha_envasado,
                    COALESCE(cc.litros_producidos, 0) AS litros_producidos,
                    COALESCE(cc.rendimiento, 0) AS rendimiento,
                    COALESCE(cc.costo_total_produccion, 0) AS costo_total_produccion,
                    COALESCE(cr.name, 'Sin receta') AS receta,
                    COALESCE(cr.tiempo_hervor::text, 'N/A') AS tiempo_hervor,
                    COALESCE(cr.temperatura_macerado::text, 'N/A') AS temperatura_macerado,
                    COALESCE(cli.name, 'No registrado') AS insumo_critico,
                    COALESCE(cli.tipo_insumo, 'N/A') AS tipo_insumo,
                    COALESCE(rp.name, 'Sin proveedor') AS proveedor
                FROM cerveza_coccion cc
                LEFT JOIN cerveza_receta cr ON cc.receta_id = cr.id
                LEFT JOIN cerveza_lote_insumo cli ON cc.insumo_critico_id = cli.id
                LEFT JOIN res_partner rp ON cli.proveedor_id = rp.id
                WHERE cc.name ILIKE %s
                LIMIT 1;
            """, (f'%{lote_name}%',))
            row = cur.fetchone()
            if not row:
                return f"No se encontró información para el lote '{lote_name}'."

            # Ventas asociadas
            cur.execute("""
                SELECT
                    so.name AS orden_venta,
                    rp2.name AS cliente,
                    COALESCE(sol.product_uom_qty, 0) AS cantidad,
                    COALESCE(sol.price_subtotal, 0) AS price_subtotal
                FROM sale_order_line sol
                JOIN sale_order so ON sol.order_id = so.id
                JOIN res_partner rp2 ON so.partner_id = rp2.id
                WHERE sol.lote_coccion_id = (SELECT id FROM cerveza_coccion WHERE name ILIKE %s LIMIT 1)
                LIMIT 10;
            """, (f'%{lote_name}%',))
            ventas = cur.fetchall()

            rendimiento = float(row['rendimiento'])
            costo = float(row['costo_total_produccion'])
            litros = float(row['litros_producidos'])
            ctx = (
                f"[DOMINIO: TRAZABILIDAD Y AUDITORIA]\n"
                f"LOTE: {row['batch']} | ESTADO: {row['state']}\n"
                f"RECETA: {row['receta']} | HERVOR: {row['tiempo_hervor']} min | MACERADO: {row['temperatura_macerado']}C\n"
                f"MAESTRO CERVECERO: {row['maestro_cervecero']}\n"
                f"FECHA COCCION: {row['fecha_coccion']} | ENVASADO: {row['fecha_envasado'] or 'Pendiente'}\n"
                f"LITROS PRODUCIDOS: {litros:.0f} L | RENDIMIENTO: {rendimiento:.2f}\n"
                f"COSTO TOTAL: ${costo:,.0f}\n"
                f"INSUMO CRITICO: {row['insumo_critico']} ({row['tipo_insumo']}) | PROVEEDOR: {row['proveedor']}\n"
                f"CLIENTES QUE RECIBIERON ESTE LOTE: {len(ventas)}\n"
            )
            if ventas:
                ctx += "VENTAS:\n"
                for v in ventas:
                    ctx += f"  - Orden {v['orden_venta']} | Cliente: {v['cliente']} | Cant: {float(v['cantidad']):.0f} u | ${float(v['price_subtotal']):,.0f}\n"
            return ctx
    finally:
        conn.close()

def get_context_auditoria_completa(lote_name: str) -> str:
    """Genera un reporte completo de trazabilidad (JSON-like) para auditorías HACCP."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    cc.name AS batch,
                    cc.state AS estado_produccion,
                    cc.estado_calidad,
                    cc.desviacion_temperatura,
                    cc.notas_laboratorio,
                    cc.notas_proceso,
                    cr.name AS receta,
                    cr.tiempo_hervor,
                    cr.temperatura_macerado,
                    cc.tanque_utilizado,
                    cc.operador_macerado,
                    cc.maestro_cervecero,
                    cc.fecha_coccion,
                    cc.fecha_envasado,
                    cc.litros_producidos,
                    cc.rendimiento,
                    cc.costo_total_produccion,
                    cli.name AS lote_insumo_critico,
                    cli.tipo_insumo,
                    rp.name AS proveedor_insumo
                FROM cerveza_coccion cc
                LEFT JOIN cerveza_receta cr ON cc.receta_id = cr.id
                LEFT JOIN cerveza_lote_insumo cli ON cc.insumo_critico_id = cli.id
                LEFT JOIN res_partner rp ON cli.proveedor_id = rp.id
                WHERE cc.name ILIKE %s
                LIMIT 1;
            """, (f'%{lote_name}%',))
            row = cur.fetchone()
            if not row:
                return f"No se encontró información de auditoría para el lote '{lote_name}'."

            # Ventas asociadas
            cur.execute("""
                SELECT so.name AS orden, rp2.name AS cliente, sol.product_uom_qty AS cantidad
                FROM sale_order_line sol
                JOIN sale_order so ON sol.order_id = so.id
                JOIN res_partner rp2 ON so.partner_id = rp2.id
                WHERE sol.lote_coccion_id = (SELECT id FROM cerveza_coccion WHERE name ILIKE %s LIMIT 1);
            """, (f'%{lote_name}%',))
            ventas = cur.fetchall()

            import json
            reporte = {
                "lote": row["batch"],
                "fechas": {
                    "coccion": str(row["fecha_coccion"]),
                    "envasado": str(row["fecha_envasado"]) if row["fecha_envasado"] else "N/A"
                },
                "personal_y_equipos": {
                    "maestro_cervecero": row["maestro_cervecero"],
                    "operador_macerado": row["operador_macerado"] or "No registrado",
                    "tanque_utilizado": row["tanque_utilizado"] or "No registrado"
                },
                "materias_primas": {
                    "receta": row["receta"],
                    "lote_critico": row["lote_insumo_critico"],
                    "tipo_insumo": row["tipo_insumo"],
                    "proveedor": row["proveedor_insumo"]
                },
                "control_calidad": {
                    "estado_laboratorio": row["estado_calidad"],
                    "desviacion_temperatura": row["desviacion_temperatura"],
                    "notas_laboratorio": row["notas_laboratorio"],
                    "notas_proceso": row["notas_proceso"]
                },
                "rendimiento": {
                    "litros_producidos": row["litros_producidos"],
                    "rendimiento_extraccion": row["rendimiento"]
                },
                "destinos_venta": [
                    {"orden": v["orden"], "cliente": v["cliente"], "cantidad": v["cantidad"]}
                    for v in ventas
                ]
            }
            return f"=== REPORTE AUDITORÍA JSON ===\n{json.dumps(reporte, ensure_ascii=False)}"
    finally:
        conn.close()

def get_context_resumen_ejecutivo() -> str:
    """Genera un resumen ejecutivo del estado actual de la producción."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Producción últimos 7 días (Por Receta)
            cur.execute("""
                SELECT
                    cr.name as receta,
                    COUNT(cc.id) AS total_lotes,
                    COALESCE(SUM(cc.litros_producidos), 0) AS total_litros
                FROM cerveza_coccion cc
                JOIN cerveza_receta cr ON cc.receta_id = cr.id
                WHERE cc.fecha_coccion >= CURRENT_DATE - INTERVAL '7 days'
                GROUP BY cr.name;
            """)
            prod_7d = cur.fetchall()

            # Producción últimos 30 días (Por Receta)
            cur.execute("""
                SELECT
                    cr.name as receta,
                    COUNT(cc.id) AS total_lotes,
                    COALESCE(SUM(cc.litros_producidos), 0) AS total_litros
                FROM cerveza_coccion cc
                JOIN cerveza_receta cr ON cc.receta_id = cr.id
                WHERE cc.fecha_coccion >= CURRENT_DATE - INTERVAL '30 days'
                GROUP BY cr.name;
            """)
            prod_30d = cur.fetchall()

            # Insumos con stock bajo
            cur.execute("""
                SELECT name, tipo_insumo, cantidad_actual_kg
                FROM cerveza_lote_insumo
                WHERE alerta_stock_bajo = TRUE;
            """)
            stock_bajo = cur.fetchall()

            # Lotes en proceso
            cur.execute("""
                SELECT cc.name, cc.state, cc.litros_producidos, cr.name as receta
                FROM cerveza_coccion cc
                LEFT JOIN cerveza_receta cr ON cc.receta_id = cr.id
                WHERE cc.state NOT IN ('done', 'draft')
                ORDER BY cc.fecha_coccion DESC;
            """)
            en_proceso = cur.fetchall()

            ctx = "[DOMINIO: RESUMEN EJECUTIVO Y PRODUCCION GENERAL]\n"
            
            ctx += "* PRODUCCIÓN ÚLTIMOS 7 DÍAS:\n"
            if not prod_7d:
                ctx += "  - No hubo producción en los últimos 7 días.\n"
            for p in prod_7d:
                ctx += f"  - {p['receta']}: {p['total_lotes']} lotes ({p['total_litros']:.0f} L)\n"
                
            ctx += "\n* PRODUCCIÓN ÚLTIMOS 30 DÍAS:\n"
            if not prod_30d:
                ctx += "  - No hubo producción en los últimos 30 días.\n"
            for p in prod_30d:
                ctx += f"  - {p['receta']}: {p['total_lotes']} lotes ({p['total_litros']:.0f} L)\n"

            ctx += f"\n* LOTES EN PROCESO ACTUALMENTE: {len(en_proceso)}\n"
            if en_proceso:
                for lp in en_proceso:
                    litros = float(lp['litros_producidos']) if lp['litros_producidos'] else 0
                    receta = lp['receta'] or "Sin receta"
                    ctx += f"  - {lp['name']} ({receta}) | {lp['state']} - {litros:.0f} L\n"
                    
            ctx += f"\n* ALERTAS DE STOCK BAJO: {len(stock_bajo)}\n"
            if stock_bajo:
                for sb in stock_bajo:
                    ctx += f"  - {sb['name']} ({sb['tipo_insumo']}): {sb['cantidad_actual_kg']} kg disponibles\n"
            return ctx
    finally:
        conn.close()


def get_context_riesgos() -> str:
    """Detecta riesgos activos en el sistema."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            riesgos = []

            # Lotes sin fecha de envasado que deberían estar listos
            cur.execute("""
                SELECT name, state, fecha_coccion
                FROM cerveza_coccion
                WHERE state = 'ready' AND fecha_envasado IS NULL;
            """)
            sin_envasado = cur.fetchall()
            for r in sin_envasado:
                riesgos.append(f"🔴 Lote {r['name']} en estado 'Listo para Envasar' pero sin fecha de envasado registrada.")

            # Insumos con stock bajo
            cur.execute("""
                SELECT name, tipo_insumo, cantidad_actual_kg, consumo_promedio_lote
                FROM cerveza_lote_insumo
                WHERE alerta_stock_bajo = TRUE;
            """)
            for r in cur.fetchall():
                riesgos.append(f"🟠 Stock crítico de {r['tipo_insumo']}: '{r['name']}' con solo {r['cantidad_actual_kg']} kg disponibles.")

            # Lotes en fermentación hace más de 20 días sin avanzar
            cur.execute("""
                SELECT name, state, fecha_coccion,
                       CURRENT_DATE - fecha_coccion AS dias_en_estado
                FROM cerveza_coccion
                WHERE state IN ('mashing', 'fermenting')
                  AND CURRENT_DATE - fecha_coccion > 20;
            """)
            for r in cur.fetchall():
                riesgos.append(f"🔴 Lote {r['name']} lleva {r['dias_en_estado']} días en estado '{r['state']}'. Posible estancamiento.")

            if not riesgos:
                return "✅ No se detectaron riesgos críticos en este momento."
            return "RIESGOS DETECTADOS:\n" + "\n".join(riesgos)
    finally:
        conn.close()


def get_context_rendimiento_insumos() -> str:
    """Analiza rendimiento y problemáticas por insumo y proveedor."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    cli.name AS insumo,
                    cli.tipo_insumo,
                    rp.name AS proveedor,
                    COUNT(cc.id) AS total_lotes,
                    ROUND(AVG(cc.rendimiento)::numeric, 4) AS avg_rendimiento,
                    ROUND(AVG(cc.litros_producidos)::numeric, 2) AS avg_litros,
                    ROUND(AVG(cc.costo_total_produccion)::numeric, 0) AS avg_costo
                FROM cerveza_coccion cc
                JOIN cerveza_lote_insumo cli ON cc.insumo_critico_id = cli.id
                JOIN res_partner rp ON cli.proveedor_id = rp.id
                GROUP BY cli.name, cli.tipo_insumo, rp.name
                ORDER BY avg_rendimiento ASC;
            """)
            rows = cur.fetchall()
            if not rows:
                return "No hay datos suficientes para analizar rendimiento por insumo."
            ctx = "[DOMINIO: RENDIMIENTO E INSUMOS]\n"
            for r in rows:
                ctx += (f"  - Insumo: {r['insumo']} ({r['tipo_insumo']}) | Proveedor: {r['proveedor']}\n"
                        f"    Lotes: {r['total_lotes']} | Rendimiento promedio: {r['avg_rendimiento']} L/kg | "
                        f"Litros promedio: {r['avg_litros']} L | Costo promedio: ${r['avg_costo']:,.0f}\n")
            return ctx
    finally:
        conn.close()


def get_context_lotes_activos() -> str:
    """Retorna información detallada únicamente de los lotes que están actualmente en proceso."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    cc.name AS batch,
                    cc.state,
                    COALESCE(cr.name, 'Sin receta') AS receta,
                    cc.fecha_coccion,
                    COALESCE(cc.litros_producidos, 0) AS litros_producidos,
                    COALESCE(cc.rendimiento, 0) AS rendimiento,
                    COALESCE(cc.maestro_cervecero, 'No asignado') AS maestro_cervecero
                FROM cerveza_coccion cc
                LEFT JOIN cerveza_receta cr ON cc.receta_id = cr.id
                WHERE cc.state NOT IN ('done', 'draft')
                ORDER BY cc.fecha_coccion ASC;
            """)
            rows = cur.fetchall()
            if not rows:
                return "No hay lotes en proceso actualmente."
            
            ctx = f"[DOMINIO: LOTES ACTIVOS EN PROCESO]\nTOTAL: {len(rows)}\n"
            for r in rows:
                litros = float(r['litros_producidos'])
                ctx += (f"* {r['batch']} | {r['receta']} | Estado: {r['state']} | "
                        f"Inicio: {r['fecha_coccion']} | {litros:.0f} L | "
                        f"MC: {r['maestro_cervecero']}\n")
            return ctx
    finally:
        conn.close()


def get_context_proyeccion_lotes_activos() -> str:
    """Calcula la ganancia total proyectada de los lotes actualmente en proceso."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                WITH rentabilidad AS (
                    SELECT
                        cr.id AS receta_id,
                        ROUND(AVG(cc.costo_total_produccion / NULLIF(cc.litros_producidos, 0))::numeric, 0) AS avg_costo_litro,
                        ROUND(COALESCE(AVG(sol.price_unit / NULLIF(sol.formato_venta, 0)), 0)::numeric, 0) AS avg_precio_venta_litro
                    FROM cerveza_coccion cc
                    JOIN cerveza_receta cr ON cc.receta_id = cr.id
                    LEFT JOIN sale_order_line sol ON sol.lote_coccion_id = cc.id
                    WHERE cc.state = 'done'
                    GROUP BY cr.id
                )
                SELECT
                    cc.name AS batch,
                    cr.name AS receta,
                    cc.state,
                    cc.litros_producidos,
                    (r.avg_precio_venta_litro - r.avg_costo_litro) AS ganancia_neta_litro,
                    (cc.litros_producidos * (r.avg_precio_venta_litro - r.avg_costo_litro)) AS proyeccion_total
                FROM cerveza_coccion cc
                JOIN cerveza_receta cr ON cc.receta_id = cr.id
                JOIN rentabilidad r ON cr.id = r.receta_id
                WHERE cc.state NOT IN ('done', 'draft')
                ORDER BY proyeccion_total DESC;
            """)
            rows = cur.fetchall()
            if not rows:
                return "No hay lotes en proceso o no hay datos de rentabilidad para proyectar."
            
            total_global = sum(float(r['proyeccion_total']) for r in rows)
            
            ctx = f"[DOMINIO: PROYECCION FINANCIERA]\nGANANCIA TOTAL ESTIMADA - LOTES EN PROCESO (${total_global:,.0f}):\n"
            for r in rows:
                litros = float(r['litros_producidos'])
                proyeccion = float(r['proyeccion_total'])
                ganancia_litro = float(r['ganancia_neta_litro'])
                ctx += (f"* {r['batch']} | {r['receta']} ({r['state']}) | "
                        f"{litros:.0f} L x ${ganancia_litro:.0f}/L | "
                        f"Ganancia Proyectada: ${proyeccion:,.0f}\n")
            return ctx
    finally:
        conn.close()


def get_context_produccion_general() -> str:
    """Retorna un resumen general de todos los lotes de producción."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    cc.name AS batch,
                    cc.state,
                    COALESCE(cr.name, 'Sin receta') AS receta,
                    cc.fecha_coccion,
                    COALESCE(cc.litros_producidos, 0) AS litros_producidos,
                    COALESCE(cc.rendimiento, 0) AS rendimiento,
                    COALESCE(cc.maestro_cervecero, 'N/A') AS maestro_cervecero
                FROM cerveza_coccion cc
                LEFT JOIN cerveza_receta cr ON cc.receta_id = cr.id
                ORDER BY cc.fecha_coccion DESC
                LIMIT 10;
            """)
            rows = cur.fetchall()
            if not rows:
                return "No se encontraron lotes de producción."
            rows.reverse()
            ctx = f"[DOMINIO: PRODUCCION GENERAL]\nULTIMOS {len(rows)} LOTES (mas antiguo a mas reciente):\n"
            for r in rows:
                rend = float(r['rendimiento'])
                litros = float(r['litros_producidos'])
                ctx += (f"* {r['batch']} | {r['receta']} | {r['state']} | "
                        f"{r['fecha_coccion']} | {litros:.0f} L | "
                        f"Rend: {rend:.3f} | MC: {r['maestro_cervecero']}\n")
            return ctx
    finally:
        conn.close()


def get_context_ventas() -> str:
    """Retorna resumen de ventas asociadas a lotes cerveceros."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    so.name AS orden,
                    rp.name AS cliente,
                    COALESCE(so.amount_total, 0) AS amount_total,
                    COALESCE(cc.name, 'N/A') AS batch,
                    COALESCE(cr.name, 'N/A') AS receta,
                    COALESCE(sol.product_uom_qty, 0) AS cantidad
                FROM sale_order_line sol
                JOIN sale_order so ON sol.order_id = so.id
                JOIN res_partner rp ON so.partner_id = rp.id
                LEFT JOIN cerveza_coccion cc ON sol.lote_coccion_id = cc.id
                LEFT JOIN cerveza_receta cr ON cc.receta_id = cr.id
                ORDER BY so.id DESC
                LIMIT 15;
            """)
            rows = cur.fetchall()
            if not rows:
                return "No hay ventas registradas con lotes cerveceros."
            ctx = f"[DOMINIO: VENTAS Y CLIENTES]\nULTIMAS {len(rows)} LINEAS DE VENTA:\n"
            for r in rows:
                ctx += (f"  - Orden: {r['orden']} | Cliente: {r['cliente']} | "
                        f"Batch: {r['batch']} | Receta: {r['receta']} | "
                        f"Cant: {float(r['cantidad']):.0f} u | Total: ${float(r['amount_total']):,.0f}\n")
            return ctx
    finally:
        conn.close()


def get_context_rentabilidad() -> str:
    """Retorna los datos de costo, venta y margen de rentabilidad por receta."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    t.receta,
                    t.avg_costo_litro,
                    t.avg_precio_venta_litro,
                    CASE 
                        WHEN t.avg_precio_venta_litro > 0 
                        THEN ROUND(((t.avg_precio_venta_litro - t.avg_costo_litro) / t.avg_precio_venta_litro * 100)::numeric, 1)
                        ELSE 0
                    END AS margen_porcentaje
                FROM (
                    SELECT
                        cr.name AS receta,
                        ROUND(AVG(cc.costo_total_produccion / NULLIF(cc.litros_producidos, 0))::numeric, 0) AS avg_costo_litro,
                        ROUND(COALESCE(AVG(sol.price_unit / NULLIF(sol.formato_venta, 0)), 0)::numeric, 0) AS avg_precio_venta_litro
                    FROM cerveza_coccion cc
                    JOIN cerveza_receta cr ON cc.receta_id = cr.id
                    LEFT JOIN sale_order_line sol ON sol.lote_coccion_id = cc.id
                    WHERE cc.state = 'done'
                    GROUP BY cr.name
                ) t
                ORDER BY margen_porcentaje DESC;
            """)
            rows = cur.fetchall()
            if not rows:
                return "No hay datos de rentabilidad calculados."
            ctx = "[DOMINIO: RENTABILIDAD Y COSTOS POR RECETA]\n"
            for r in rows:
                costo = float(r['avg_costo_litro'])
                venta = float(r['avg_precio_venta_litro'])
                ganancia = venta - costo
                margen = float(r['margen_porcentaje'])
                ctx += (f"  - {r['receta']} | Costo: ${costo:.0f}/L | "
                        f"Venta: ${venta:.0f}/L | "
                        f"Ganancia: ${ganancia:.0f}/L | "
                        f"Margen: {margen:.1f} pct\n")
            return ctx
    finally:
        conn.close()


def get_context_balance() -> str:
    """Extrae ingresos, costos y utilidad neta agrupados por mes."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT 
                    TO_CHAR(cc.fecha_coccion, 'YYYY-MM') as mes,
                    SUM(sol.price_unit * sol.product_uom_qty) as total_ventas
                FROM sale_order_line sol
                JOIN cerveza_coccion cc ON sol.lote_coccion_id = cc.id
                GROUP BY mes
            """)
            ventas = {r['mes']: r['total_ventas'] for r in cur.fetchall()}
            
            cur.execute("""
                SELECT 
                    TO_CHAR(fecha_coccion, 'YYYY-MM') as mes,
                    SUM(costo_total_produccion) as total_costos
                FROM cerveza_coccion
                GROUP BY mes
                ORDER BY mes DESC
                LIMIT 12
            """)
            costos = {r['mes']: r['total_costos'] for r in cur.fetchall()}
            
            if not costos:
                return "No hay registros de costos o ventas para calcular balance."
                
            ctx = "[DOMINIO: BALANCE GENERAL MENSUAL (Ultimos 12 meses)]\n"
            for mes in sorted(costos.keys(), reverse=True):
                costo = float(costos.get(mes, 0))
                venta = float(ventas.get(mes, 0))
                balance = venta - costo
                ctx += f"- Mes: {mes} | Ingresos Totales: ${venta:,.0f} | Costos Produccion: ${costo:,.0f} | Utilidad Neta: ${balance:,.0f}\n"
            return ctx
    except Exception as e:
        return f"Error leyendo balance: {e}"
    finally:
        conn.close()

def get_context_forecasting() -> str:
    """Proyecta inventario y dias restantes de cada insumo basado en el consumo historico real."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT 
                    cli.name,
                    cli.cantidad_actual_kg,
                    COALESCE(SUM(crl.cantidad_kg), 0) as consumo_30d
                FROM cerveza_lote_insumo cli
                LEFT JOIN cerveza_receta_linea crl ON crl.name = cli.name
                LEFT JOIN cerveza_coccion cc ON cc.receta_id = crl.receta_id AND cc.fecha_coccion >= CURRENT_DATE - INTERVAL '30 days'
                GROUP BY cli.name, cli.cantidad_actual_kg
            """)
            rows = cur.fetchall()
            
            ctx = "[DOMINIO: PREDICCION DE STOCK Y FORECASTING]\n"
            for r in rows:
                consumo = float(r['consumo_30d'])
                stock = float(r['cantidad_actual_kg'])
                if consumo > 0:
                    burn_rate_diario = consumo / 30.0
                    dias_restantes = stock / burn_rate_diario
                    ctx += f"- {r['name']}: {stock:.1f} kg en bodega | Consumo últimos 30d: {consumo:.1f} kg | Se agotará en {dias_restantes:.0f} días al ritmo actual.\n"
                else:
                    ctx += f"- {r['name']}: {stock:.1f} kg en bodega | Sin consumo reciente. Riesgo de estancamiento.\n"
            return ctx
    finally:
        conn.close()

def get_context_crm() -> str:
    """Analisis de mejores clientes y sus preferencias."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT 
                    rp.name as cliente,
                    cr.name as receta,
                    SUM(sol.product_uom_qty * sol.price_unit) as total_comprado,
                    SUM(sol.product_uom_qty) as barriles_comprados
                FROM sale_order_line sol
                JOIN sale_order so ON sol.order_id = so.id
                JOIN res_partner rp ON so.partner_id = rp.id
                JOIN cerveza_coccion cc ON sol.lote_coccion_id = cc.id
                JOIN cerveza_receta cr ON cc.receta_id = cr.id
                GROUP BY rp.name, cr.name
                ORDER BY total_comprado DESC
            """)
            rows = cur.fetchall()
            
            ctx = "[DOMINIO: CRM Y COMPORTAMIENTO DE CLIENTES]\n"
            clientes = {}
            for r in rows:
                c = r['cliente']
                if c not in clientes: clientes[c] = []
                clientes[c].append(r)
                
            for c, data in clientes.items():
                total = sum(float(d['total_comprado']) for d in data)
                ctx += f"\n* Cliente: {c} | Total Historico: ${total:,.0f}\n"
                for d in data:
                    ctx += f"  - Favorita: {d['receta']} | {d['barriles_comprados']} barriles (${float(d['total_comprado']):,.0f})\n"
            return ctx
    finally:
        conn.close()

def get_context_calidad() -> str:
    """Analisis de lotes con mermas y auditoria de laboratorio."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT 
                    cc.name as batch, 
                    cr.name as receta,
                    cc.litros_producidos,
                    cc.operador_macerado,
                    cc.estado_calidad,
                    cc.notas_laboratorio,
                    TO_CHAR(cc.fecha_coccion, 'YYYY-MM-DD') as fecha
                FROM cerveza_coccion cc
                JOIN cerveza_receta cr ON cc.receta_id = cr.id
                WHERE cc.estado_calidad = 'Advertencia' OR cc.litros_producidos < 470
                ORDER BY cc.fecha_coccion DESC
                LIMIT 15
            """)
            rows = cur.fetchall()
            
            ctx = "[DOMINIO: CONTROL DE CALIDAD Y DIAGNOSTICO DE MERMAS]\n"
            if not rows:
                return ctx + "No se detectan mermas recientes ni problemas de calidad."
                
            ctx += "ULTIMOS LOTES CON MERMAS O ALERTAS DE CALIDAD:\n"
            for r in rows:
                ctx += (f"- Batch: {r['batch']} ({r['fecha']}) | {r['receta']} | {r['litros_producidos']:.0f}L (MERMA) | "
                        f"Operador: {r['operador_macerado']} | Causa detectada: {r['notas_laboratorio']}\n")
            return ctx
    finally:
        conn.close()

# ─────────────────────────────────────────────
#  MOTOR BIA: Selección de contexto semántico
# ─────────────────────────────────────────────

def seleccionar_contexto(mensaje: str, historial: list = None) -> str:
    """
    Selecciona el contexto mas relevante del ERP segun la intencion del mensaje.
    Tambien revisa el historial reciente para detectar el tema de la conversacion.
    Soporta multiples fuentes combinadas si el mensaje activa varias palabras clave.
    """
    msg = mensaje.lower()

    # Enriquecer el mensaje con el tema del historial reciente para preguntas de seguimiento
    # (ej: "y cuanto cuesta?" despues de hablar de rentabilidad)
    if historial:
        # Tomar los ultimos 2 turnos del usuario para inferir el contexto
        ultimos = historial[-4:]
        texto_reciente = " ".join(
            h.get("content", "").lower() for h in ultimos if h.get("role") == "user"
        )
        # SIEMPRE enriquecer con historial para detectar el tema de la conversacion
        msg = msg + " " + texto_reciente

    # Interceptores Exclusivos (Retornan inmediatamente un contexto especifico)
    if 'proyecci' in msg or ('ganancia' in msg and 'proceso' in msg) or ('monto total' in msg and 'lote' in msg):
        return get_context_proyeccion_lotes_activos()

    # Detectar si la consulta es sobre precios/rentabilidad (para no mezclar con ventas de clientes)
    es_consulta_rentabilidad = any(k in msg for k in [
        'ganancia', 'rentabilidad', 'margen', 'costo', 'coste', 'lucro', 'beneficio',
        'dinero', 'plata', 'precio', 'mas cara', 'mas barata', 'valor',
        'ingreso', 'precio de venta', 'cuanto vale', 'cuanto cuesta',
        'precio por litro', 'cuanto vende', 'cuanto genera', 'venta x litro'
    ])

    contextos = []

    # Resumen Ejecutivo (Periodos)
    if any(k in msg for k in ['resumen', 'semana', 'mes', 'ejecutivo', 'general']):
        contextos.append(get_context_resumen_ejecutivo())

    # Historia de un lote especifico o Auditoría
    lote_match = re.search(r'batch-[\w-]+', msg, re.IGNORECASE)
    if lote_match:
        if any(k in msg for k in ['auditoria', 'auditoría', 'historia completa', 'trazabilidad', 'laboratorio', 'calidad', 'todo']):
            contextos.append(get_context_auditoria_completa(lote_match.group()))
        else:
            contextos.append(get_context_lote(lote_match.group()))

    # Rentabilidad, ganancias y costos
    if es_consulta_rentabilidad:
        contextos.append(get_context_rentabilidad())

    # Ventas y clientes
    if any(k in msg for k in ['venta', 'cliente', 'pedido', 'orden', 'despacho', 'compra']):
        contextos.append(get_context_ventas())
        
    # Balance general
    if any(k in msg for k in ['balance', 'financiero', 'general', 'global', 'mensual', 'flujo']):
        contextos.append(get_context_balance())

    # Insumos y proveedores
    if any(k in msg for k in ['insumo', 'proveedor', 'malta', 'levadura', 'lupulo', 'stock', 'inventario', 'bodega', 'almacen']):
        contextos.append(get_context_rendimiento_insumos())

    # Forecasting / Predicción
    if any(k in msg for k in ['prediccion', 'predicción', 'proyeccion', 'agotara', 'acabara', 'dias faltan', 'durara', 'cuanto queda']):
        contextos.append(get_context_forecasting())
        
    # CRM / Clientes
    if any(k in msg for k in ['crm', 'cliente', 'quien compra', 'mejor bar', 'favorito', 'favorita', 'comprador']):
        contextos.append(get_context_crm())
        
    # Calidad y Mermas
    if any(k in msg for k in ['calidad', 'merma', 'falló', 'fallo', 'por que', 'laboratorio', 'operador', 'macerado', 'temperatura', 'problema', 'diagnostico']):
        contextos.append(get_context_calidad())

    # En proceso / lotes activos
    if any(k in msg for k in ['proceso', 'activo', 'fermentando', 'coccion', 'envasando', 'en curso']):
        contextos.append(get_context_lotes_activos())

    # Riesgos y alertas
    if any(k in msg for k in ['riesgo', 'alerta', 'problema', 'urgente', 'critico']):
        contextos.append(get_context_riesgos())

    # Si no hubo match, usamos el contexto por defecto (ejecutivo + general)
    if not contextos:
        contextos.append(get_context_resumen_ejecutivo())
        contextos.append(get_context_produccion_general())

    return "\n\n".join(contextos)


# ─────────────────────────────────────────────
#  CONFIGURACIÓN GROQ CLOUD (LLaMA 3.1)
# ─────────────────────────────────────────────
GROQ_API_KEY = "tu_api_key_aqui" # Reemplazar con tu clave real
GROQ_MODEL = "llama-3.1-8b-instant"

SYSTEM_PROMPT = """Eres Don Pilsen, Asistente de Inteligencia Operacional ERP (Agente Cervecero).
REGLAS DE COMPORTAMIENTO:
1. TONO CONVERSACIONAL: Hila las ideas de forma natural, inteligente y profesional. Puedes dar explicaciones breves si ayudan a entender el contexto de los datos, aportando valor analítico.
2. FORMATO OBLIGATORIO: Usa texto plano y viñetas simples con "-". (PROHIBIDO usar tablas markdown).
3. EMOJIS: Usa emojis con moderación para darle vida al texto. Esta ESTRICTAMENTE PROHIBIDO usar 🔴 o cualquier emoji rojo, a menos que el lote este cancelado o haya stock 0. Usa 🟡 para mermas reales.
4. EXHAUSTIVIDAD (MUY IMPORTANTE): NUNCA resumas listas ni te guardes información. Si el usuario te pregunta por inventario, stock crítico, lotes activos, o ventas, DEBES listar TODOS los ítems que aparecen en tu contexto. No los agrupes ni menciones solo un par.
5. LONGITUD: Sé claro y directo, pero prioriza entregar la información completa requerida. No limites la cantidad de datos si el usuario te pide un listado.
6. RESPUESTAS DE EJECUCION: Si en tu contexto recibes un mensaje del "[SISTEMA DE EJECUCION]" informando que se canceló o vendió un lote, asume el crédito de la acción y comunícaselo al usuario con un tono resolutivo.
7. FORMATO DE NUMEROS: Separa siempre los miles con puntos (ej. $1.500.000) para facilitar la lectura financiera.

[DICCIONARIO CONTABLE Y OPERATIVO]
* Formato de Negocio: Venta Mayorista B2B. Los precios de venta (ej. $120.000) siempre son por Barril de 50 Litros. Si divides el precio total de un item por los litros, obtienes el precio/L.
* Ingresos=Ventas, COGS=Costo, Ganancia=Utilidad, Margen=(Ganancia/Ventas). No usamos distinciones entre bruto/neto porque no consideramos costos fijos.
* Trazabilidad=Batch/Lote/Insumo/Proveedor.
* Merma=100-Rendimiento. ROI=(Ganancia/Costo Produccion)*100.

[CONOCIMIENTO CERVECERO]
* Stout (Bundor Belial): Cerveza negra, maltas tostadas/chocolate, amargor bajo, densa.
* Pale Ale / APA (Fuzz): Cerveza amarga (IBU alto), lúpulos cítricos o tropicales (Citra).
* Golden (Kross): Cerveza rubia, de entrada, muy refrescante, bajo amargor, malta pilsen.
* Amber (Cuello Negro): Cerveza roja, equilibrio entre malta caramelo y lúpulo medio.

[MODO SIMULADOR]
* Si el usuario pregunta "qué pasaría si", "si aumento", "si cae", debes actuar como un Simulador Matemático de Negocios.
* Recalcula los costos y utilidades utilizando los datos proporcionados y la matemática simple, entregando proyecciones directas basadas en los porcentajes o precios que pida el usuario.
"""

async def llamar_ollama_stream(mensaje: str, contexto: str, historial: list = None):
    """Envía el prompt a la API de Groq y transmite la respuesta en streaming."""
    contexto_seguro = contexto.replace('%', ' pct')
    hoy = datetime.datetime.now().strftime('%d de %B de %Y')
    system_content = f"{SYSTEM_PROMPT}\n\n[DATOS DEL ERP]:\n{contexto_seguro}\n\nFecha actual: {hoy}"
    messages = [{"role": "system", "content": system_content}]
    
    if historial:
        for h in historial[-4:]:
            messages.append({"role": "user" if h.get("role") == "user" else "assistant", "content": h.get("content")})
    messages.append({"role": "user", "content": mensaje})

    payload = {"model": GROQ_MODEL, "messages": messages, "stream": True, "temperature": 0.05, "max_tokens": 150}
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    
    async with httpx.AsyncClient(timeout=180.0) as client:
        async with client.stream("POST", "https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    content = line[6:].strip()
                    if content == "[DONE]": break
                    try:
                        data = json.loads(content)
                        if "choices" in data:
                            yield data["choices"][0]["delta"].get("content", "")
                    except: pass


async def verificar_ollama() -> bool:
    return True


async def asegurar_modelo_disponible() -> bool:
    return True


def respuesta_fallback(mensaje: str, contexto: str) -> str:
    """
    Motor de respuesta determinista cuando la API no está disponible.
    """
    msg = mensaje.lower()
    encabezado = "🤖 **BIA — Modo Análisis Directo**\n\n"
    lineas = [line for line in contexto.split('\n') if not line.startswith('REGLA:')]
    
    if any(k in msg for k in ['mas', 'mayor', 'mejor', 'peor', 'menos']):
        lineas_datos = []
        encontrado_primero = False
        for line in lineas:
            if line.strip().startswith('*') or line.strip().startswith('-'):
                if not encontrado_primero:
                    lineas_datos.append(line)
                    encontrado_primero = True
            else:
                lineas_datos.append(line)
        lineas = lineas_datos

    contexto_limpio = '\n'.join(lineas).strip()
    return f"{encabezado}{contexto_limpio}"


# ─────────────────────────────────────────────
#  ENDPOINTS
# ─────────────────────────────────────────────

@app.get("/")
def read_root():
    """Endpoint raíz para comprobar que la API está funcionando."""
    return {
        "mensaje": "¡La API del Dashboard Analítico + BIA está funcionando!",
        "documentacion": "Visita http://localhost:8000/docs para ver los endpoints.",
        "bia": "Endpoint de chat en POST /api/bia/chat"
    }


class ChatRequest(BaseModel):
    mensaje: str
    historial: Optional[list] = None

async def extraer_parametros_accion(mensaje: str) -> dict:
    """Usa Groq (JSON mode) para extraer parametros de ejecucion si los hay."""
    msg_lower = mensaje.lower()
    if not any(k in msg_lower for k in ['cancela', 'vende', 'anula', 'venta', 'factura', 'vender']):
        return None
        
    prompt = f"""Extrae la intención de acción del siguiente mensaje.
Responde ÚNICAMENTE con un objeto JSON válido.
Posibles acciones: "cancelar_lote", "vender_lote", "ninguna".
Formato esperado:
{{
    "accion": "cancelar_lote",
    "batch_id": "BATCH-2026-042" (extrae el ID si existe, sino null),
    "cliente": "nombre" (para ventas, null si no hay),
    "cantidad_barriles": numero_entero (para ventas, null si no hay)
}}
Mensaje: "{mensaje}"
"""
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "response_format": {"type": "json_object"}
    }
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
            data = res.json()
            return json.loads(data["choices"][0]["message"]["content"])
        except:
            return None

def ejecutar_accion_db(datos_accion: dict) -> str:
    if not datos_accion or datos_accion.get("accion") == "ninguna":
        return ""
        
    accion = datos_accion.get("accion")
    batch = datos_accion.get("batch_id")
    
    if not batch:
        return ""
        
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if accion == "cancelar_lote":
                cur.execute("SELECT state FROM cerveza_coccion WHERE name = %s", (batch,))
                row = cur.fetchone()
                if not row:
                    return f"[SISTEMA DE EJECUCION]: Fallo, el lote {batch} no existe."
                if row[0] in ['cancel', 'done']:
                    return f"[SISTEMA DE EJECUCION]: Fallo, el lote {batch} ya esta cerrado o cancelado."
                    
                cur.execute("UPDATE cerveza_coccion SET state = 'cancel', notas_laboratorio = 'Cancelado manualmente vía BIA' WHERE name = %s", (batch,))
                conn.commit()
                return f"[SISTEMA DE EJECUCION]: EXITO. El lote {batch} ha sido marcado como cancelado."
                
            elif accion == "vender_lote":
                cliente = datos_accion.get("cliente")
                cant = datos_accion.get("cantidad_barriles")
                if not cliente or not cant:
                    return f"[SISTEMA DE EJECUCION]: Faltan datos (cliente o cantidad) para vender el {batch}. Pídeselos al usuario."
                    
                cur.execute("SELECT id FROM res_partner WHERE name ILIKE %s LIMIT 1", (f"%{cliente}%",))
                rp = cur.fetchone()
                if not rp:
                    return f"[SISTEMA DE EJECUCION]: Fallo, el cliente '{cliente}' no existe en la base de datos."
                partner_id = rp[0]
                
                cur.execute("SELECT id, receta_id, producto_id, litros_producidos FROM cerveza_coccion WHERE name = %s", (batch,))
                cc = cur.fetchone()
                if not cc: return f"[SISTEMA DE EJECUCION]: Fallo, lote {batch} no encontrado."
                lote_id = cc[0]
                producto_id = cc[2]
                
                cur.execute("INSERT INTO sale_order (name, partner_id, amount_total) VALUES (%s, %s, %s) RETURNING id", 
                            (f"SO-BIA-{random.randint(1000,9999)}", partner_id, cant * 100000))
                so_id = cur.fetchone()[0]
                
                cur.execute("INSERT INTO sale_order_line (order_id, product_tmpl_id, product_uom_qty, price_unit, lote_coccion_id, formato_venta) VALUES (%s, %s, %s, %s, %s, %s)",
                            (so_id, producto_id, cant, 100000, lote_id, 50))
                conn.commit()
                return f"[SISTEMA DE EJECUCION]: EXITO. Se crearon las ordenes de venta para {cant} barriles del {batch} al cliente {cliente}."
    except Exception as e:
        conn.rollback()
        return f"[SISTEMA DE EJECUCION]: Error SQL: {e}"
    finally:
        conn.close()
    return ""

@app.post("/api/bia/chat")
async def bia_chat(request: ChatRequest):
    if not request.mensaje or not request.mensaje.strip():
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío.")

    resultado_ejecucion = ""
    try:
        datos_accion = await extraer_parametros_accion(request.mensaje)
        if datos_accion:
            resultado_ejecucion = ejecutar_accion_db(datos_accion)

        contexto = seleccionar_contexto(request.mensaje, request.historial)
        
        if resultado_ejecucion:
            contexto = resultado_ejecucion + "\n\n" + contexto
            
    except Exception as e:
        contexto = f"Error: {e}"

    return StreamingResponse(
        llamar_ollama_stream(request.mensaje, contexto, request.historial),
        media_type="text/plain"
    )


@app.get("/api/bia/estado")
async def bia_estado():
    """Verifica el estado de la API de Groq."""
    return {
        "status": "ok",
        "ollama_activo": True,
        "modelo_disponible": True,
        "modelo_configurado": GROQ_MODEL,
        "modelos_en_sistema": [GROQ_MODEL],
        "url_ollama": "https://api.groq.com"
    }


# ─────────────────────────────────────────────
#  ENDPOINTS ORIGINALES DEL DASHBOARD
# ─────────────────────────────────────────────

@app.get("/api/filtros")
def get_filtros():
    """Obtiene la lista de recetas disponibles para los filtros del dashboard."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            query = """
                SELECT id, name
                FROM cerveza_receta
                ORDER BY name ASC;
            """
            cursor.execute(query)
            resultados = cursor.fetchall()
            return {"status": "success", "data": resultados}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/kpi/grafico_uno")
def get_grafico_uno(
    receta_id: Optional[int] = Query(None, description="Filtro por ID de Receta"),
    mes: Optional[str] = Query(None, description="Filtro por mes (YYYY-MM)")
):
    """Retorna la producción por lote, permitiendo filtrar por receta y por mes."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            query = """
                SELECT
                    cc.name AS codigo_batch,
                    cr.name AS nombre_receta,
                    cc.litros_producidos,
                    cc.rendimiento,
                    cc.state AS estado,
                    TO_CHAR(cc.fecha_coccion, 'YYYY-MM') AS mes,
                    cc.fecha_coccion,
                    cc.fecha_envasado AS fecha_fin_real
                FROM cerveza_coccion cc
                JOIN cerveza_receta cr ON cc.receta_id = cr.id
                WHERE 1=1
            """
            params = []
            if receta_id:
                query += " AND cc.receta_id = %s"
                params.append(receta_id)
            if mes:
                query += " AND TO_CHAR(cc.fecha_coccion, 'YYYY-MM') = %s"
                params.append(mes)
            query += " ORDER BY cc.fecha_coccion DESC;"
            cursor.execute(query, tuple(params))
            resultados = cursor.fetchall()
            return {"status": "success", "data": resultados}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/kpi/grafico_dos")
def get_grafico_dos():
    """Retorna la tendencia mensual de litros producidos y stock estimado."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            query = """
                SELECT
                    TO_CHAR(fecha_coccion, 'YYYY-MM') AS mes,
                    COUNT(*) AS total_lotes,
                    ROUND(SUM(litros_producidos)::numeric, 2) AS litros_producidos,
                    ROUND(SUM(
                        CASE
                            WHEN state = 'done' THEN litros_producidos * 0.85
                            ELSE 0
                        END
                    )::numeric, 2) AS litros_vendidos,
                    ROUND(SUM(
                        CASE
                            WHEN state = 'done' THEN litros_producidos * 0.15
                            WHEN state IN ('fermenting', 'mashing', 'ready') THEN litros_producidos
                            ELSE 0
                        END
                    )::numeric, 2) AS stock_actual
                FROM cerveza_coccion
                WHERE fecha_coccion IS NOT NULL
                GROUP BY TO_CHAR(fecha_coccion, 'YYYY-MM')
                ORDER BY mes ASC;
            """
            cursor.execute(query)
            resultados = cursor.fetchall()
            return {"status": "success", "data": resultados}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/kpi/grafico_tres")
def get_grafico_tres():
    """Retorna la distribución actual del estado de los lotes (Pipeline)."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            query = """
                SELECT
                    state AS estado,
                    COUNT(*) AS cantidad
                FROM cerveza_coccion
                WHERE state != 'draft'
                GROUP BY state
                ORDER BY cantidad DESC;
            """
            cursor.execute(query)
            resultados = cursor.fetchall()
            return {"status": "success", "data": resultados}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/kpi/grafico_cuatro")
def get_grafico_cuatro():
    """Retorna el costo promedio por litro y el precio de venta promedio por litro."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            query = """
                SELECT
                    t.receta,
                    t.avg_costo_litro,
                    t.avg_precio_venta_litro,
                    CASE 
                        WHEN t.avg_precio_venta_litro > 0 
                        THEN ROUND(((t.avg_precio_venta_litro - t.avg_costo_litro) / t.avg_precio_venta_litro * 100)::numeric, 1)
                        ELSE 0
                    END AS margen_porcentaje
                FROM (
                    SELECT
                        cr.name AS receta,
                        ROUND(AVG(cc.costo_total_produccion / NULLIF(cc.litros_producidos, 0))::numeric, 0) AS avg_costo_litro,
                        ROUND(COALESCE(AVG(sol.price_unit / NULLIF(sol.formato_venta, 0)), 0)::numeric, 0) AS avg_precio_venta_litro
                    FROM cerveza_coccion cc
                    JOIN cerveza_receta cr ON cc.receta_id = cr.id
                    LEFT JOIN sale_order_line sol ON sol.lote_coccion_id = cc.id
                    WHERE cc.state = 'done'
                    GROUP BY cr.name
                ) t
                ORDER BY t.avg_costo_litro DESC;
            """
            cursor.execute(query)
            resultados = cursor.fetchall()
            return {"status": "success", "data": resultados}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/kpi/alertas_stock")
def get_alertas_stock():
    """Retorna los insumos que están por debajo del nivel crítico."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Consideramos alerta si la cantidad actual es menor a 2.5 veces el consumo promedio
            query = """
                SELECT 
                    name AS insumo,
                    cantidad_actual_kg,
                    consumo_promedio_lote
                FROM cerveza_lote_insumo
                WHERE cantidad_actual_kg <= (consumo_promedio_lote * 2.5) OR alerta_stock_bajo = True
                ORDER BY cantidad_actual_kg ASC;
            """
            cursor.execute(query)
            resultados = cursor.fetchall()
            return {"status": "success", "data": resultados}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
