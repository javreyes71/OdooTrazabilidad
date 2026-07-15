# -*- coding: utf-8 -*-
{
    'name': "Trazabilidad Cervecera ERP",
    'summary': "Cumplimiento RA1 y RA2: Módulos propios, Herencia y SQL Constraints",
    'author': "Ingeniería Informática",
    'version': '18.0.1.0',
    'depends': ['base', 'product', 'sale', 'sale_stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/trazabilidad_views.xml',
        'views/product_inherit_views.xml',
        'views/sale_order_inherit_views.xml',
        'views/dashboard_views.xml',
        'data/demo_data.xml',
        'data/demo_data_massive.xml',
    ],
    'installable': True,
    'application': True,
}
