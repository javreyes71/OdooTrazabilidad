# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_beer = fields.Boolean(string='Es Cerveza de Producción Propia')
    beer_style = fields.Selection([
        ('lager', 'Lager'),
        ('ale', 'Ale'),
        ('stout', 'Stout'),
        ('ipa', 'IPA'),
        ('porter', 'Porter')
    ], string='Estilo de Cerveza')

    volumen_litros = fields.Float(
        string='Volumen por Unidad (L)', default=0.5,
        help='Volumen en litros. Ej: 0.5 para 500ml, 50.0 para Barril.')
    formato_ml = fields.Selection([
        ('350', '350ml'),
        ('500', '500ml'),
    ], string='Formato de Envase',
        help='Formato comercial del envase.')

    precio_b2b = fields.Float(string='Precio B2B (Mayorista)', help='Precio exclusivo para Distribuidores y Bares.')
    precio_b2c = fields.Float(string='Precio B2C (Detalle)', help='Precio para clientes directos o consumidor final.')

    # Métricas Estadísticas de Venta (Calculadas desde sale.order.line)
    unidades_vendidas = fields.Float(string='Unidades Vendidas', compute='_compute_estadisticas_venta')
    total_ingresos = fields.Float(string='Ingresos Totales ($)', compute='_compute_estadisticas_venta')
    indice_rentabilidad = fields.Float(string='Índice de Rentabilidad (%)', compute='_compute_estadisticas_venta')

    def _compute_estadisticas_venta(self):
        for template in self:
            lines = self.env['sale.order.line'].search([
                ('product_template_id', '=', template.id),
                ('state', 'in', ['sale', 'done'])
            ])
            template.unidades_vendidas = sum(lines.mapped('product_uom_qty'))
            template.total_ingresos = sum(lines.mapped('price_subtotal'))

            rentabilidades = lines.filtered(
                lambda l: l.rentabilidad_porcentaje != 0.0
            ).mapped('rentabilidad_porcentaje')
            template.indice_rentabilidad = (
                sum(rentabilidades) / len(rentabilidades) if rentabilidades else 0.0
            )

    abv = fields.Float(string='Graduación Alcohólica (% ABV)')
    ibu = fields.Integer(string='Amargor (IBU)')

    # --- Acciones para Dashboard: Top 3 ---
    @api.model
    def action_top_vendidos(self):
        """Devuelve acción con los Top 3 productos más vendidos."""
        templates = self.search([('is_beer', '=', True)])
        data = []
        for t in templates:
            lines = self.env['sale.order.line'].search([
                ('product_template_id', '=', t.id),
                ('state', 'in', ['sale', 'done'])
            ])
            data.append((t.id, sum(lines.mapped('product_uom_qty'))))
        data.sort(key=lambda x: x[1], reverse=True)
        top_ids = [d[0] for d in data[:3]]
        return {
            'type': 'ir.actions.act_window',
            'name': '🏆 Top 3 Más Vendidos',
            'res_model': 'product.template',
            'view_mode': 'list,form',
            'domain': [('id', 'in', top_ids)],
            'target': 'current',
        }

    @api.model
    def action_top_rentables(self):
        """Devuelve acción con los Top 3 productos más rentables."""
        templates = self.search([('is_beer', '=', True)])
        data = []
        for t in templates:
            lines = self.env['sale.order.line'].search([
                ('product_template_id', '=', t.id),
                ('state', 'in', ['sale', 'done'])
            ])
            rents = lines.filtered(
                lambda l: l.rentabilidad_porcentaje != 0.0
            ).mapped('rentabilidad_porcentaje')
            avg_rent = sum(rents) / len(rents) if rents else 0.0
            data.append((t.id, avg_rent))
        data.sort(key=lambda x: x[1], reverse=True)
        top_ids = [d[0] for d in data[:3]]
        return {
            'type': 'ir.actions.act_window',
            'name': '💰 Top 3 Más Rentables',
            'res_model': 'product.template',
            'view_mode': 'list,form',
            'domain': [('id', 'in', top_ids)],
            'target': 'current',
        }
