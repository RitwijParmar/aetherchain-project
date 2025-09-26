from django.core.management.base import BaseCommand
from aetherchain.core.models import Product, Port, ShippingRoute
from neomodel import db
class Command(BaseCommand):
    help = 'Populates the Neo4j database with a sample supply chain.'
    def handle(self, *args, **options):
        self.stdout.write('Clearing existing graph data for a clean slate...')
        db.cypher_query("MATCH (n) DETACH DELETE n")
        self.stdout.write('Populating graph...')
        shoe_a = Product(sku='SHOE-ABC', name='Running Shoe Model A').save()
        boot_x = Product(sku='BOOT-XYZ', name='Hiking Boot Model X').save()
        port_hcm = Port(name='Port of Ho Chi Minh', country='Vietnam').save()
        port_la = Port(name='Port of Los Angeles', country='USA').save()
        port_sea = Port(name='Port of Seattle', country='USA').save()
        route = ShippingRoute(route_id='VNHCM-USLAX').save()
        route.origin_port.connect(port_hcm)
        route.destination_port.connect(port_la)
        route.carries_product.connect(shoe_a)
        route.carries_product.connect(boot_x)
        self.stdout.write(self.style.SUCCESS('Successfully populated the graph database.'))
