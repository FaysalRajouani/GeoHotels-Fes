import xml.etree.ElementTree as ET
from neo4j import GraphDatabase

URI = "neo4j://127.0.0.1:7687"
AUTH = ("siaw", "20032003")
FICHIER_OSM = "map_fes_V2.osm"  # Assurez-vous que c'est le bon nom de fichier

def charger_osm_dans_neo4j():
    print("⏳ Analyse du fichier OSM et importation en cours...")

    driver = GraphDatabase.driver(URI, auth=AUTH)

    with driver.session() as session:
        # ── 0. Nettoyage complet ──
        print("🗑  Nettoyage de la base...")
        session.run("MATCH (n) DETACH DELETE n")

        coords_dict = {}  # ID -> (lat, lon)
        routes = []       # Liste des chemins à créer
        hotels = []       # Liste des hôtels à importer

        # ── 1. Lecture du fichier OSM ──
        print("🔍 Lecture du fichier OSM...")
        context = ET.iterparse(FICHIER_OSM, events=("end",))
        for _, elem in context:
            # --- Nœuds ---
            if elem.tag == "node":
                node_id = elem.get("id")
                lat = float(elem.get("lat"))
                lon = float(elem.get("lon"))
                coords_dict[node_id] = (lat, lon)

                # Détection d'un hôtel sur un nœud
                is_hotel = False
                hotel_name = elem.get('name')
                for tag in elem.findall("tag"):
                    k = tag.get("k")
                    v = tag.get("v")
                    if k in ("tourism", "amenity") and v == "hotel":
                        is_hotel = True
                    if k == "name":
                        hotel_name = v
                if is_hotel:
                    hotels.append({
                        "id": node_id,
                        "name": hotel_name or f"Hôtel {node_id}",
                        "lat": lat,
                        "lon": lon,
                        "stars": "4"
                    })

            # --- Chemins (ways) ---
            elif elem.tag == "way":
                is_highway = False
                is_hotel = False
                hotel_name = elem.get('name')
                nd_refs = [nd.get("ref") for nd in elem.findall("nd") if nd.get("ref") is not None]

                for tag in elem.findall("tag"):
                    k = tag.get("k")
                    v = tag.get("v")
                    # Détection d'une route
                    if k == "highway" and v is not None:
                        is_highway = True
                    # Détection d'un hôtel sur un way
                    if k in ("tourism", "amenity") and v == "hotel":
                        is_hotel = True
                    if k == "name":
                        hotel_name = v

                # Ajouter les relations ROUTE si le way est une highway
                if is_highway and len(nd_refs) > 1:
                    for i in range(len(nd_refs) - 1):
                        a, b = nd_refs[i], nd_refs[i+1]
                        if a in coords_dict and b in coords_dict:
                            routes.append({
                                "a_id": a, "a_lat": coords_dict[a][0], "a_lon": coords_dict[a][1],
                                "b_id": b, "b_lat": coords_dict[b][0], "b_lon": coords_dict[b][1],
                            })

                # Ajouter l'hôtel si le way en contient un (cas rare mais possible)
                if is_hotel and nd_refs:
                    first_node_id = nd_refs[0]
                    if first_node_id in coords_dict:
                        lat, lon = coords_dict[first_node_id]
                        hotels.append({
                            "id": elem.get("id"),
                            "name": hotel_name or f"Hôtel {elem.get('id')}",
                            "lat": lat,
                            "lon": lon,
                            "stars": "4"
                        })

                elem.clear()  # Libère la mémoire

        print(f"   → {len(coords_dict)} nœuds géographiques chargés.")
        print(f"   → {len(routes)} segments de route identifiés.")
        print(f"   → {len(hotels)} hôtels identifiés.")

        # ── 2. Insertion dans Neo4j ──
        print("📍 Insertion des données dans Neo4j...")

        # A. Création des Points et des Relations ROUTE
        print("   → Création du réseau routier...")
        BATCH_SIZE = 1000
        batch = []
        for r in routes:
            batch.append(r)
            if len(batch) >= BATCH_SIZE:
                session.run("""
                UNWIND $pairs AS p
                MERGE (a:Point {id: p.a_id})
                SET a.latitude = p.a_lat,
                    a.longitude = p.a_lon,
                    a.location = point({latitude: p.a_lat, longitude: p.a_lon})
                MERGE (b:Point {id: p.b_id})
                SET b.latitude = p.b_lat,
                    b.longitude = p.b_lon,
                    b.location = point({latitude: p.b_lat, longitude: p.b_lon})
                MERGE (a)-[:ROUTE]->(b)
                MERGE (b)-[:ROUTE]->(a)
                """, pairs=batch)
                batch = []
        if batch:
            session.run("""
            UNWIND $pairs AS p
            MERGE (a:Point {id: p.a_id})
            SET a.latitude = p.a_lat,
                a.longitude = p.a_lon,
                a.location = point({latitude: p.a_lat, longitude: p.a_lon})
            MERGE (b:Point {id: p.b_id})
            SET b.latitude = p.b_lat,
                b.longitude = p.b_lon,
                b.location = point({latitude: p.b_lat, longitude: p.b_lon})
            MERGE (a)-[:ROUTE]->(b)
            MERGE (b)-[:ROUTE]->(a)
            """, pairs=batch)

        # B. Création des Hôtels
        print("   → Création des nœuds Hôtels...")
        if hotels:
            session.run("""
            UNWIND $rows AS h
            MERGE (hotel:Hotel {id: h.id})
            SET hotel.nom = h.name,
                hotel.latitude = h.lat,
                hotel.longitude = h.lon,
                hotel.location = point({latitude: h.lat, longitude: h.lon}),
                hotel.etoiles = h.stars
            """, rows=hotels)

        # C. Indexation
        print("🔑 Création des index...")
        session.run("CREATE INDEX point_id IF NOT EXISTS FOR (p:Point) ON (p.id)")
        session.run("CREATE INDEX hotel_id IF NOT EXISTS FOR (h:Hotel) ON (h.id)")
        session.run("CREATE INDEX point_location IF NOT EXISTS FOR (p:Point) ON (p.location)")

        # D. Statistiques finales
        res_pts = session.run("MATCH (p:Point) RETURN count(p) AS nb").single()
        res_hotels = session.run("MATCH (h:Hotel) RETURN count(h) AS nb").single()
        res_routes = session.run("MATCH ()-[r:ROUTE]->() RETURN count(r) AS nb").single()

        print(f"\n✅ IMPORTATION TERMINÉE !")
        print(f"   🚀 Points : {res_pts['nb']}")
        print(f"   🏨 Hôtels : {res_hotels['nb']}")
        print(f"   🔗 Routes  : {res_routes['nb']}")

    driver.close()

if __name__ == "__main__":
    charger_osm_dans_neo4j()
