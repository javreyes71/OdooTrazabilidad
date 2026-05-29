{ 
    'name': "Hola Mundo - Visitantes", 
    'summary': "Módulo de prueba para comprender la arquitectura Odoo", 
    'author': "Ingeniería Informática", 
    'version': '1.0', 
    'depends': ['base'], 
    'data': [ 
        'security/ir.model.access.csv', 
        'views/visitante_view.xml', 
    ], 
    'installable': True, 
    'application': True, 
}