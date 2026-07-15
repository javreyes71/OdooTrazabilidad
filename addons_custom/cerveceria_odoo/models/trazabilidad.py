# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError

class CervezaRecetaLinea(models.Model):
    _name = 'cerveza.receta.linea'
    _description = 'Ingrediente de Receta'

    receta_id = fields.Many2one('cerveza.receta', string='Receta', ondelete='cascade')
    name = fields.Char(string='Insumo (Malta/Lúpulo/Levadura)', required=True)
    cantidad_kg = fields.Float(string='Cantidad (Kg/U)', required=True, default=1.0)
    costo_unitario = fields.Float(string='Costo Unitario ($)', required=True, default=0.0)
    
    costo_subtotal = fields.Float(string='Subtotal ($)', compute='_compute_subtotal', store=True)

    @api.depends('cantidad_kg', 'costo_unitario')
    def _compute_subtotal(self):
        for linea in self:
            linea.costo_subtotal = linea.cantidad_kg * linea.costo_unitario

class CervezaReceta(models.Model):
    _name = 'cerveza.receta'
    _description = 'Recetario Maestro'
    
    name = fields.Char(string='Nombre de la Receta', required=True)
    tiempo_hervor = fields.Integer(string='Tiempo de Hervor (Minutos)')
    temperatura_macerado = fields.Float(string='Temp. Macerado (°C)')
    descripcion_receta = fields.Html(string='Descripción y Notas de Ingredientes')

    linea_ids = fields.One2many('cerveza.receta.linea', 'receta_id', string='Desglose de Ingredientes')
    costo_total_materia_prima = fields.Float(string='Costo Total Materia Prima', compute='_compute_costo_mp', store=True)

    @api.depends('linea_ids.costo_subtotal')
    def _compute_costo_mp(self):
        for receta in self:
            receta.costo_total_materia_prima = sum(receta.linea_ids.mapped('costo_subtotal'))

class CervezaLoteInsumo(models.Model):
    _name = 'cerveza.lote.insumo'
    _description = 'Lotes de Materia Prima'

    name = fields.Char(string='Código de Lote Insumo', required=True)
    tipo_insumo = fields.Selection([
        ('malta', 'Malta'), ('lupulo', 'Lúpulo'), ('levadura', 'Levadura')
    ], string='Tipo de Insumo', required=True)
    
    proveedor_id = fields.Many2one('res.partner', string='Proveedor de Origen', required=True)
    cantidad_kg = fields.Float(string='Cantidad (Kg)')
    cantidad_actual_kg = fields.Float(
        string='Stock Actual (Kg)', default=0.0,
        help='Cantidad actualmente disponible en bodega.')
    consumo_promedio_lote = fields.Float(
        string='Consumo Promedio por Lote (Kg)', default=0.0,
        help='Cantidad promedio consumida por cada batch de cocción.')
    alerta_stock_bajo = fields.Boolean(
        string='⚠️ Stock Bajo', compute='_compute_alerta_stock',
        store=True, help='Se activa cuando el stock actual es menor o igual al doble del consumo promedio por lote.')

    @api.depends('cantidad_actual_kg', 'consumo_promedio_lote')
    def _compute_alerta_stock(self):
        for rec in self:
            if rec.consumo_promedio_lote > 0:
                rec.alerta_stock_bajo = rec.cantidad_actual_kg <= (rec.consumo_promedio_lote * 2)
            else:
                rec.alerta_stock_bajo = False

    _sql_constraints = [
        ('lote_insumo_unique', 'unique(name)', '¡Error! El código de lote de insumo ya existe.')
    ]

class CervezaCoccion(models.Model):
    _name = 'cerveza.coccion'
    _description = 'Registro de Cocción (Trazabilidad)'

    name = fields.Char(string='Código de Producción (Batch)', required=True)

    # --- 1. Gestión de Estados (Workflow Visual) ---
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('mashing', 'Maceración'),
        ('fermenting', 'Fermentación'),
        ('ready', 'Listo para Envasar'),
        ('done', 'Terminado'),
    ], string='Estado', default='draft', required=True, tracking=True)

    receta_id = fields.Many2one('cerveza.receta', string='Receta Utilizada', required=True)
    insumo_critico_id = fields.Many2one('cerveza.lote.insumo', string='Lote de Insumo Crítico')

    producto_id = fields.Many2one('product.template', string='Producto Final a Vender', required=True)
    responsable_id = fields.Many2one('res.users', string='Usuario Responsable', default=lambda self: self.env.user)
    
    maestro_cervecero = fields.Char(string='Maestro a cargo')
    fecha_coccion = fields.Date(string='Fecha de Cocción', default=fields.Date.context_today)
    fecha_envasado = fields.Date(string='Fecha de Envasado',
        help='Fecha en que el batch fue envasado. No puede ser anterior a la fecha de cocción.')

    litros_producidos = fields.Float(string='Litros Obtenidos', required=False, default=0.0)
    notas_proceso = fields.Text(string='Notas de Proceso', help='Registro de PH, densidades y observaciones químicas.')

    # --- Trazabilidad Avanzada y Calidad ---
    tanque_utilizado = fields.Char(string='Tanque/Fermentador', help='Identificador del equipo utilizado (ej: F-01).')
    operador_macerado = fields.Char(string='Operador Macerado', help='Nombre del operador a cargo de la etapa de maceración.')
    estado_calidad = fields.Selection([
        ('pendiente', 'Pendiente Lab'),
        ('aprobado', 'Aprobado'),
        ('rechazado', 'Rechazado (Descarte)')
    ], string='Estado de Calidad', default='pendiente', tracking=True)
    desviacion_temperatura = fields.Boolean(string='Hubo Desviación de Temp.', default=False)
    notas_laboratorio = fields.Text(string='Resultados de Laboratorio')

    # --- Variables Financieras y de Costo ---
    horas_trabajadas = fields.Float(string='Horas Trabajadas', default=0.0, help='Horas invertidas por el Maestro Cervecero.')
    costo_mano_obra = fields.Float(string='Costo Mano de Obra ($)', compute='_compute_costos', store=True)
    costo_materia_prima = fields.Float(string='Costo Materia Prima ($)', related='receta_id.costo_total_materia_prima', store=True)
    costo_total_produccion = fields.Float(string='Costo Total Producción ($)', compute='_compute_costos', store=True)
    
    costo_mp_por_litro = fields.Float(string='Costo MP x Litro', compute='_compute_costos_por_litro', store=True)
    costo_mo_por_litro = fields.Float(string='Costo MO x Litro', compute='_compute_costos_por_litro', store=True)

    litros_disponibles = fields.Float(
        string='Litros Disponibles', compute='_compute_litros_disponibles',
        store=True, help='Litros producidos menos litros ya comprometidos en ventas.')

    @api.depends('horas_trabajadas')
    def _compute_costos(self):
        for record in self:
            record.costo_mano_obra = record.horas_trabajadas * 4000.0
            record.costo_total_produccion = record.costo_mano_obra + record.costo_materia_prima

    @api.depends('costo_materia_prima', 'costo_mano_obra', 'litros_producidos', 'state')
    def _compute_costos_por_litro(self):
        for record in self:
            if record.state == 'done' and record.litros_producidos > 0:
                record.costo_mp_por_litro = record.costo_materia_prima / record.litros_producidos
                record.costo_mo_por_litro = record.costo_mano_obra / record.litros_producidos
            else:
                record.costo_mp_por_litro = 0.0
                record.costo_mo_por_litro = 0.0

    @api.depends('litros_producidos', 'lineas_venta_ids.litros_vendidos')
    def _compute_litros_disponibles(self):
        for rec in self:
            vendidos = sum(rec.lineas_venta_ids.mapped('litros_vendidos'))
            rec.litros_disponibles = rec.litros_producidos - vendidos

    # --- Acciones de Transición de Estado ---
    def action_start_mashing(self):
        self.write({'state': 'mashing'})

    def action_start_fermenting(self):
        self.write({'state': 'fermenting'})

    def action_set_ready(self):
        self.write({'state': 'ready'})

    def action_button_done(self):
        self.write({'state': 'done'})

    # --- Trazabilidad Bidireccional: Enlace inverso hacia Ventas ---
    lineas_venta_ids = fields.One2many(
        'sale.order.line', 'lote_coccion_id',
        string='Líneas de Venta Asociadas',
        help='Todas las líneas de pedido de venta que fueron despachadas con este lote de cocción.'
    )

    # --- Campos Related: Visibilidad directa del insumo desde la cocción ---
    proveedor_insumo_id = fields.Many2one(
        related='insumo_critico_id.proveedor_id',
        string='Proveedor del Insumo Crítico',
        store=True, readonly=True
    )
    tipo_insumo_critico = fields.Selection(
        related='insumo_critico_id.tipo_insumo',
        string='Tipo de Insumo Crítico',
        store=True, readonly=True
    )
    descripcion_receta = fields.Html(
        related='receta_id.descripcion_receta',
        string='Descripción de la Receta',
        readonly=True
    )

    # --- 2. Smart Button: Contador de líneas de venta ---
    sale_line_count = fields.Integer(
        string='Ventas Vinculadas',
        compute='_compute_sale_line_count',
    )

    @api.depends('lineas_venta_ids')
    def _compute_sale_line_count(self):
        for rec in self:
            rec.sale_line_count = len(rec.lineas_venta_ids)

    def action_view_sale_lines(self):
        """Abre una ventana con las líneas de venta asociadas a este batch."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Ventas del Batch {self.name}',
            'res_model': 'sale.order.line',
            'view_mode': 'list,form',
            'domain': [('lote_coccion_id', '=', self.id)],
            'context': dict(self.env.context),
        }

    # --- 3. Campo Calculado: Rendimiento (L/Kg) ---
    rendimiento = fields.Float(
        string='Rendimiento (L/Kg)',
        compute='_compute_rendimiento',
        store=True,
        help='Litros obtenidos por cada Kg de insumo crítico utilizado.'
    )

    @api.depends('litros_producidos', 'insumo_critico_id.cantidad_kg')
    def _compute_rendimiento(self):
        for rec in self:
            kg = rec.insumo_critico_id.cantidad_kg
            if kg and kg > 0:
                rec.rendimiento = rec.litros_producidos / kg
            else:
                rec.rendimiento = 0.0

    # --- 4. Validación Lógica e Inmutabilidad ---
    def write(self, vals):
        # Bloqueo Enterprise: Inmutabilidad de campos críticos si el estado es Terminado
        if 'receta_id' in vals or 'fecha_coccion' in vals:
            for rec in self:
                if rec.state == 'done':
                    # Verificar si realmente está cambiando el valor
                    cambio_receta = 'receta_id' in vals and vals['receta_id'] != rec.receta_id.id
                    # Odoo pasa las fechas como strings en el vals a veces, o como objetos date.
                    # Una forma segura es chequear si cambió sustancialmente.
                    cambio_fecha = 'fecha_coccion' in vals and str(vals['fecha_coccion']) != str(rec.fecha_coccion)
                    
                    if cambio_receta or cambio_fecha:
                        # Permitir bypass si Odoo está instalando/actualizando módulos
                        if not self.env.context.get('install_mode'):
                            raise ValidationError(
                                "¡Bloqueo Enterprise! No está permitido modificar la receta ni la fecha de cocción "
                                "de un Batch que ya se encuentra en estado 'Terminado'."
                            )
        return super().write(vals)

    @api.constrains('litros_producidos', 'state')
    def _check_litros_producidos(self):
        for rec in self:
            if rec.state != 'draft' and rec.litros_producidos <= 0:
                raise ValidationError(
                    '⚠️ Error de Validación: Los litros producidos deben ser '
                    'mayores a cero cuando el batch ha salido del estado Borrador. '
                    f'(Batch: {rec.name}, Estado actual: {rec.state})'
                )

    @api.constrains('fecha_coccion', 'fecha_envasado')
    def _check_fechas(self):
        for rec in self:
            if rec.fecha_envasado and rec.fecha_coccion:
                if rec.fecha_envasado < rec.fecha_coccion:
                    raise ValidationError(
                        "Error: La fecha de envasado no puede ser previa "
                        "a la fecha de inicio de cocción."
                    )

    _sql_constraints = [
        ('lote_coccion_unique', 'unique(name)', '¡Error Crítico! Este Batch ya fue registrado. Violación de integridad evitada.')
    ]

