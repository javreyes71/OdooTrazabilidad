# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class SaleOrderLineInherit(models.Model):
    """
    Herencia sobre sale.order.line para inyectar el campo de trazabilidad.
    Permite vincular cada línea de venta con el lote de cocción específico
    que se usó para producir la cerveza vendida.
    """
    _inherit = 'sale.order.line'

    lote_coccion_id = fields.Many2one(
        'cerveza.coccion',
        string='Lote de Cocción',
        help='Batch de cocción asociado a este producto vendido. '
             'Permite rastrear desde la venta hasta la materia prima.'
    )

    # Métricas Financieras y Estadísticas
    formato_venta = fields.Float(string='Volumen/U (L)', related='product_template_id.volumen_litros', store=True)
    litros_vendidos = fields.Float(string='Litros Vendidos', compute='_compute_rentabilidad', store=True)

    costo_materia_prima_linea = fields.Float(string='Costo M.P.', compute='_compute_rentabilidad', store=True)
    costo_mano_obra_linea = fields.Float(string='Costo M.O.', compute='_compute_rentabilidad', store=True)

    margen_ganancia = fields.Float(string='Margen de Ganancia ($)', compute='_compute_rentabilidad', store=True)
    rentabilidad_porcentaje = fields.Float(string='Rentabilidad (%)', compute='_compute_rentabilidad', store=True)

    @api.depends('product_uom_qty', 'formato_venta', 'lote_coccion_id', 'lote_coccion_id.costo_mp_por_litro', 'lote_coccion_id.costo_mo_por_litro', 'price_subtotal')
    def _compute_rentabilidad(self):
        for line in self:
            line.litros_vendidos = line.product_uom_qty * line.formato_venta
            if line.lote_coccion_id:
                line.costo_materia_prima_linea = line.litros_vendidos * line.lote_coccion_id.costo_mp_por_litro
                line.costo_mano_obra_linea = line.litros_vendidos * line.lote_coccion_id.costo_mo_por_litro
            else:
                line.costo_materia_prima_linea = 0.0
                line.costo_mano_obra_linea = 0.0

            costo_total = line.costo_materia_prima_linea + line.costo_mano_obra_linea
            line.margen_ganancia = line.price_subtotal - costo_total

            if costo_total > 0:
                line.rentabilidad_porcentaje = line.margen_ganancia / costo_total
            elif line.price_subtotal > 0:
                line.rentabilidad_porcentaje = 1.0
            else:
                line.rentabilidad_porcentaje = 0.0

    # --- Bloqueo de Sobreventa ---
    @api.constrains('product_uom_qty', 'lote_coccion_id')
    def _check_stock_batch(self):
        for line in self:
            if line.lote_coccion_id and line.lote_coccion_id.litros_producidos > 0:
                litros_solicitados = line.product_uom_qty * line.formato_venta
                disponibles = line.lote_coccion_id.litros_disponibles + (
                    line._origin.product_uom_qty * line._origin.formato_venta if line._origin.id else 0
                )
                if litros_solicitados > disponibles:
                    raise ValidationError(
                        f"¡Error! Stock insuficiente en este Batch ({line.lote_coccion_id.name}). "
                        f"Solo quedan {line.lote_coccion_id.litros_disponibles:.2f} litros disponibles."
                    )

    @api.onchange('product_id', 'order_id.partner_id')
    def _onchange_product_id_precio(self):
        for line in self:
            if line.product_id and line.product_id.is_beer:
                is_b2b = line.order_id.partner_id.is_company
                if is_b2b and line.product_id.precio_b2b > 0:
                    line.price_unit = line.product_id.precio_b2b
                elif not is_b2b and line.product_id.precio_b2c > 0:
                    line.price_unit = line.product_id.precio_b2c

    @api.constrains('product_uom_qty', 'price_unit')
    def _check_qty_price_positive(self):
        for line in self:
            # Solo aplicar a cervezas de producción propia
            if line.product_id and line.product_id.is_beer:
                if line.product_uom_qty <= 0:
                    raise ValidationError("La cantidad a vender no puede ser cero o negativa para cervezas.")
                if line.price_unit <= 0:
                    raise ValidationError("El precio de venta de una cerveza no puede ser cero o negativo.")

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_confirm(self):
        """Validaciones Enterprise antes de confirmar la venta."""
        for order in self:
            # 1. Validar que el cliente tenga RUT/NIF
            if not order.partner_id.vat:
                raise ValidationError(
                    f"No se puede confirmar la venta a un cliente no registrado formalmente. "
                    f"El cliente '{order.partner_id.name}' debe tener un ID/RUT (NIF) configurado en su contacto."
                )
            for line in order.order_line:
                # 2. Validar que toda línea con lote tenga un producto asociado
                if line.lote_coccion_id and not line.product_id:
                    raise ValidationError(
                        "Cada línea de venta con un Lote de Cocción debe tener un producto asociado."
                    )
                # 3. Validar rentabilidad de cada línea de cerveza
                if line.product_id and line.product_id.is_beer and line.costo_materia_prima_linea > 0:
                    if line.rentabilidad_porcentaje < 1.2 or line.rentabilidad_porcentaje > 2.5:
                        raise ValidationError(
                            f"¡Error Financiero! La rentabilidad de '{line.product_id.name}' "
                            f"es de {line.rentabilidad_porcentaje:.2f}x. "
                            f"Debe estar entre 1.2x y 2.5x para poder confirmar esta venta."
                        )
        return super(SaleOrder, self).action_confirm()

class ResPartner(models.Model):
    _inherit = 'res.partner'

    _sql_constraints = [
        ('vat_unique', 'unique(vat)', '¡El ID/RUT (NIF) debe ser único para cada cliente!')
    ]

