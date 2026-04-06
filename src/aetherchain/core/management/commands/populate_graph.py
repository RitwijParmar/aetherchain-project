from django.core.management.base import BaseCommand
from neomodel import db


class Command(BaseCommand):
    help = 'Populates the Neo4j database with a sample supply chain.'

    def handle(self, *args, **options):
        self.stdout.write('Clearing existing graph data for a clean slate...')
        db.cypher_query("MATCH (n) DETACH DELETE n")

        self.stdout.write('Populating graph...')

        seed_query = """
        MERGE (p1:Port {name: 'Port of Los Angeles'})
        MERGE (p2:Port {name: 'Port of Seattle'})
        MERGE (r1:Route {route_id: 'VNHCM-USLAX'})
        MERGE (r2:Route {route_id: 'VNHCM-USSEA'})
        MERGE (prod1:Product {sku: 'SHOE-ABC'})
        MERGE (prod2:Product {sku: 'BOOT-XYZ'})
        MERGE (prod3:Product {sku: 'APP-321'})
        MERGE (s1:Supplier {name: 'Vietnam Footwear Co.', location: 'Ho Chi Minh City, Vietnam'})
        MERGE (s2:Supplier {name: 'Pacific Apparel Supplier', location: 'Ho Chi Minh City, Vietnam'})

        MERGE (r1)-[:DESTINED_FOR]->(p1)
        MERGE (r2)-[:DESTINED_FOR]->(p2)
        MERGE (prod1)-[:CARRIES]->(r1)
        MERGE (prod2)-[:CARRIES]->(r1)
        MERGE (prod3)-[:CARRIES]->(r2)
        MERGE (s1)-[:SUPPLIES]->(prod1)
        MERGE (s1)-[:SUPPLIES]->(prod2)
        MERGE (s2)-[:SUPPLIES]->(prod3)
        """
        db.cypher_query(seed_query)

        self.stdout.write(self.style.SUCCESS('Successfully populated the graph database.'))
