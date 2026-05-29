from odoo import models, fields

class registroVisitante(models.Model):
    _name = 'hola.visitante'
    _description = 'Registro basico de visitantes'
    
    name = fields.Char(string="Nombre de Visitante", required=True)
    fecha_visita = fields.Datetime(string='Fecha y Hora',default=fields.Datetime.now)
    motivo = fields.Text(string="Motivo de la Visita")
