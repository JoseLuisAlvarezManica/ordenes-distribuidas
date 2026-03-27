from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


class Seeder():
    def __init__(self, session, redis):
        self.session = session
        self.redis = redis

        # Formato SKU: NNN-X
        # E = Electrónica (computadoras, laptops, workstations)
        # T = Telecomunicaciones (fax, smartphones, routers, switches, servidores)
        # P = Periféricos (impresoras, teclados, ratones, escáneres, copiadoras, webcams)
        # A = Audio/Visual (auriculares, monitores, proyectores, smart TVs)
        # S = Almacenamiento (discos duros, memorias USB)
        # W = Wearables (smartwatches, rastreadores de actividad)
        # G = Gaming (cascos VR, consolas de videojuegos)
        # M = Móviles (tablets)

        self.products = [
            {'sku': '001-E', 'name': 'Computadora',              'stock': 100},
            {'sku': '002-T', 'name': 'Máquina de Fax',           'stock': 200},
            {'sku': '003-E', 'name': 'Laptop',                   'stock': 300},
            {'sku': '004-P', 'name': 'Impresora',                'stock': 400},
            {'sku': '005-T', 'name': 'Smartphone',               'stock': 500},
            {'sku': '006-M', 'name': 'Tablet',                   'stock': 600},
            {'sku': '007-A', 'name': 'Monitor',                  'stock': 700},
            {'sku': '008-P', 'name': 'Teclado',                  'stock': 800},
            {'sku': '009-P', 'name': 'Ratón',                    'stock': 900},
            {'sku': '010-A', 'name': 'Auriculares',              'stock': 1000},
            {'sku': '011-P', 'name': 'Webcam',                   'stock': 1100},
            {'sku': '012-S', 'name': 'Disco Duro Externo',       'stock': 1200},
            {'sku': '013-S', 'name': 'Memoria USB',              'stock': 1300},
            {'sku': '014-T', 'name': 'Router',                   'stock': 1400},
            {'sku': '015-T', 'name': 'Switch',                   'stock': 1500},
            {'sku': '016-T', 'name': 'Servidor',                 'stock': 1600},
            {'sku': '017-E', 'name': 'Workstation',              'stock': 1700},
            {'sku': '018-A', 'name': 'Proyector',                'stock': 1800},
            {'sku': '019-P', 'name': 'Escáner',                  'stock': 1900},
            {'sku': '020-P', 'name': 'Copiadora',                'stock': 2000},
            {'sku': '021-W', 'name': 'Smartwatch',               'stock': 2100},
            {'sku': '022-W', 'name': 'Rastreador de Actividad',  'stock': 2200},
            {'sku': '023-G', 'name': 'Casco de Realidad Virtual','stock': 2300},
            {'sku': '024-G', 'name': 'Consola de Videojuegos',   'stock': 2400},
            {'sku': '025-A', 'name': 'Smart TV',                 'stock': 2500},
        ]
    
    async def seed(self):
        # Seed Base datos
        result = await self.session.execute(text("SELECT COUNT(*) FROM products"))
        count = result.scalar_one()
        logger.info(f"[Seeder] products count: {count}")
        if count == 0:
            for product in self.products:
                await self.session.execute(text(f"""
                    INSERT INTO products (sku, name, stock) VALUES
                    ('{product['sku']}', '{product['name']}', {product['stock']})
                """))
            await self.session.commit()
            
            logger.info("[Seeder] Seed completed successfully.")
        else:
            logger.info("[Seeder] Products already seeded, skipping.")
        
        # Seed Redis
        try:
            for product in self.products:
                if not await self.redis.exists(product['sku']):
                    await self.redis.hset(product['sku'], mapping={"name": product['name']})             
        except Exception as exc:
            logger.error(f"[Seeder] Redis error: {exc}", exc_info=True)