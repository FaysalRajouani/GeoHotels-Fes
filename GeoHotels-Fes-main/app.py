from flask import Flask, request, jsonify
from flask_cors import CORS
from neo4j import GraphDatabase

app = Flask(__name__)
CORS(app)

URI = "bolt://127.0.0.1:7687"
AUTH = ("neo4j", "test1234")

def execute_query(query, params={}):
    try:
        with GraphDatabase.driver(URI, auth=AUTH) as driver:
            with driver.session() as session:
                result = session.run(query, **params)
                return [record.data() for record in result], None
    except Exception as e:
        return [], str(e)

# ==============================================================================
# 1. ROUTE : Récupérer tous les hôtels proches (nearby)
# ==============================================================================
@app.route('/api/hotels/nearby', methods=['GET'])
def get_hotels_nearby():
    try:
        lat = float(request.args.get('lat', 34.0500))
        lng = float(request.args.get('lng', -4.9900))
        radius = float(request.args.get('radius', 5000))  # en mètres
    except ValueError:
        return jsonify({"success": False, "error": "Paramètres invalides"}), 400

    query = """
    MATCH (h:Hotel)
    WHERE h.latitude IS NOT NULL AND h.longitude IS NOT NULL
    WITH h, point({latitude: h.latitude, longitude: h.longitude}) as hPt,
         point({latitude: $lat, longitude: $lng}) as refPt
    WITH h, point.distance(hPt, refPt) AS dist_m
    WHERE dist_m <= $radius
    RETURN h.id AS id, h.nom AS name, h.latitude AS latitude, h.longitude AS longitude, 
           coalesce(h.etoiles, "3") AS stars, coalesce(h.adresse, "N/A") AS address, 
           coalesce(h.telephone, "N/A") AS phone, (dist_m / 1000.0) AS distance_km
    ORDER BY distance_km ASC
    """
    data, error = execute_query(query, {"lat": lat, "lng": lng, "radius": radius})
    if error:
        return jsonify({"success": False, "error": error}), 500
    return jsonify({"success": True, "hotels": data})

# ==============================================================================
# 2. ROUTE : Filtrer les hôtels par étoiles
# ==============================================================================
@app.route('/api/hotels/filter', methods=['GET'])
def get_hotels_filter():
    try:
        lat = float(request.args.get('lat', 34.0500))
        lng = float(request.args.get('lng', -4.9900))
        radius = float(request.args.get('radius', 5000))
        stars = request.args.get('stars', '')
    except ValueError:
        return jsonify({"success": False, "error": "Paramètres invalides"}), 400

    query = """
    MATCH (h:Hotel)
    WHERE h.latitude IS NOT NULL AND h.longitude IS NOT NULL 
      AND toString(h.etoiles) = $stars
    WITH h, point({latitude: h.latitude, longitude: h.longitude}) as hPt,
         point({latitude: $lat, longitude: $lng}) as refPt
    WITH h, point.distance(hPt, refPt) AS dist_m
    WHERE dist_m <= $radius
    RETURN h.id AS id, h.nom AS name, h.latitude AS latitude, h.longitude AS longitude, 
           h.etoiles AS stars, coalesce(h.adresse, "N/A") AS address, 
           coalesce(h.telephone, "N/A") AS phone, (dist_m / 1000.0) AS distance_km
    ORDER BY distance_km ASC
    """
    data, error = execute_query(query, {"lat": lat, "lng": lng, "radius": radius, "stars": stars})
    if error:
        return jsonify({"success": False, "error": error}), 500
    return jsonify({"success": True, "hotels": data})

# ==============================================================================
# 3. ROUTE : Obtenir l'Itinéraire (Get Direction)
# ==============================================================================
@app.route('/api/chemin', methods=['POST'])
def calculer_chemin():
    data = request.json or {}
    try:
        user_lat = float(data['user_lat'])
        user_lon = float(data['user_lon'])
        # On accepte soit hotel_id, soit hotel_lat/hotel_lon
        hotel_id = data.get('hotel_id')
        hotel_lat = data.get('hotel_lat')
        hotel_lon = data.get('hotel_lon')
        
        # Si hotel_id est fourni, on récupère ses coordonnées depuis la base
        if hotel_id and hotel_id != 'test_id':
            with GraphDatabase.driver(URI, auth=AUTH) as driver:
                with driver.session() as session:
                    result = session.run(
                        "MATCH (h:Hotel {id: $id}) RETURN h.latitude AS lat, h.longitude AS lon",
                        id=hotel_id
                    ).single()
                    if result:
                        hotel_lat = result['lat']
                        hotel_lon = result['lon']
                    else:
                        return jsonify({"status": "error", "message": "Hôtel non trouvé."}), 404
        
        # Vérification des coordonnées de l'hôtel
        if hotel_lat is None or hotel_lon is None:
            return jsonify({"status": "error", "message": "Coordonnées de l'hôtel manquantes."}), 400
            
        hotel_lat = float(hotel_lat)
        hotel_lon = float(hotel_lon)
        
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({"status": "error", "message": f"Données requises manquantes ou invalides: {str(e)}"}), 400

    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        with driver.session() as session:
            try:
                # Étape 1 : Point de route le plus proche de la position utilisateur
                q_dept = """
                MATCH (p:Point) 
                WHERE p.latitude IS NOT NULL AND p.longitude IS NOT NULL
                WITH p, point({latitude: p.latitude, longitude: p.longitude}) as pPt,
                     point({latitude: $lat, longitude: $lon}) as uPt
                ORDER BY point.distance(pPt, uPt) ASC 
                LIMIT 1
                RETURN p.id AS id, p.latitude AS lat, p.longitude AS lon
                """
                res_dept = session.run(q_dept, lat=user_lat, lon=user_lon).single()

                # Étape 2 : Point de route le plus proche de l'hôtel cible
                q_arr = """
                MATCH (p:Point)
                WHERE p.latitude IS NOT NULL AND p.longitude IS NOT NULL
                WITH p, point({latitude: p.latitude, longitude: p.longitude}) as pPt,
                     point({latitude: $lat, longitude: $lon}) as hotelPt
                ORDER BY point.distance(pPt, hotelPt) ASC
                LIMIT 1
                RETURN p.id AS id, p.latitude AS lat, p.longitude AS lon
                """
                res_arr = session.run(q_arr, lat=hotel_lat, lon=hotel_lon).single()

                # Vérification des résultats
                if not res_dept:
                    return jsonify({
                        "status": "error", 
                        "message": f"Aucun point de route trouvé près de la position utilisateur ({user_lat}, {user_lon})."
                    }), 404
                    
                if not res_arr:
                    return jsonify({
                        "status": "error", 
                        "message": f"Aucun point de route trouvé près de l'hôtel ({hotel_lat}, {hotel_lon})."
                    }), 404

                id_start = res_dept['id']
                id_end = res_arr['id']
                
                print(f"🟢 Départ: {id_start} ({res_dept['lat']}, {res_dept['lon']})")
                print(f"🟢 Arrivée: {id_end} ({res_arr['lat']}, {res_arr['lon']})")

                # Étape 3 : Recherche du plus court chemin
                q_route = """
                MATCH (start:Point {id: $start_id}), (end:Point {id: $end_id})
                MATCH path = shortestPath((start)-[:ROUTE*]-(end))
                WHERE path IS NOT NULL
                RETURN [n in nodes(path) | {lat: n.latitude, lon: n.longitude}] AS coords
                """
                res_route = session.run(q_route, start_id=id_start, end_id=id_end).single()

                if res_route and res_route['coords'] and len(res_route['coords']) > 0:
                    chemin = res_route['coords']
                    
                    # Vérifier que le chemin commence bien près du point de départ
                    first = chemin[0]
                    dist_first = ((first['lat'] - user_lat)**2 + (first['lon'] - user_lon)**2)**0.5
                    if dist_first > 0.01:  # Si le premier point est trop loin, on ajoute le point de départ
                        chemin.insert(0, {"lat": user_lat, "lon": user_lon})
                    
                    # Vérifier que le chemin finit bien près de l'hôtel
                    last = chemin[-1]
                    dist_last = ((last['lat'] - hotel_lat)**2 + (last['lon'] - hotel_lon)**2)**0.5
                    if dist_last > 0.01:  # Si le dernier point est trop loin, on ajoute l'hôtel
                        chemin.append({"lat": hotel_lat, "lon": hotel_lon})
                    
                    print(f"✅ Chemin trouvé avec {len(chemin)} points")
                    return jsonify({"status": "success", "chemin": chemin})
                else:
                    # Si pas de chemin, on retourne un chemin direct
                    print("⚠️ Aucun chemin routier, retour du chemin direct")
                    return jsonify({
                        "status": "success", 
                        "chemin": [
                            {"lat": user_lat, "lon": user_lon},
                            {"lat": (user_lat + hotel_lat) / 2, "lon": (user_lon + hotel_lon) / 2},
                            {"lat": hotel_lat, "lon": hotel_lon}
                        ]
                    })

            except Exception as inner_e:
                print(f"❌ Erreur interne: {str(inner_e)}")
                return jsonify({"status": "error", "message": str(inner_e)}), 500

# ==============================================================================
# 4. ROUTE : Récupérer un hôtel par son ID
# ==============================================================================
@app.route('/api/hotels/<hotel_id>', methods=['GET'])
def get_hotel_by_id(hotel_id):
    query = """
    MATCH (h:Hotel {id: $id})
    RETURN h.id AS id, h.nom AS name, h.latitude AS latitude, h.longitude AS longitude,
           h.etoiles AS stars, h.adresse AS address, h.telephone AS phone
    """
    data, error = execute_query(query, {"id": hotel_id})
    if error:
        return jsonify({"success": False, "error": error}), 500
    if not data:
        return jsonify({"success": False, "error": "Hôtel non trouvé"}), 404
    return jsonify({"success": True, "hotel": data[0]})

# ==============================================================================
# 5. ROUTE : Statistiques de la base
# ==============================================================================
@app.route('/api/stats', methods=['GET'])
def get_stats():
    query = """
    MATCH (p:Point) WITH count(p) AS points
    MATCH (h:Hotel) WITH points, count(h) AS hotels
    MATCH ()-[r:ROUTE]->() WITH points, hotels, count(r) AS routes
    RETURN points, hotels, routes
    """
    data, error = execute_query(query)
    if error:
        return jsonify({"success": False, "error": error}), 500
    return jsonify({"success": True, "stats": data[0] if data else {}})

# ==============================================================================
# 6. ROUTE : Vérification de la connexion
# ==============================================================================
@app.route('/api/health', methods=['GET'])
def health_check():
    try:
        with GraphDatabase.driver(URI, auth=AUTH) as driver:
            with driver.session() as session:
                result = session.run("RETURN 1 AS test").single()
                if result and result['test'] == 1:
                    return jsonify({"status": "healthy", "neo4j": "connected"})
    except Exception as e:
        return jsonify({"status": "unhealthy", "neo4j": "disconnected", "error": str(e)}), 500
    return jsonify({"status": "unhealthy", "neo4j": "unknown"}), 500

if __name__ == '__main__':
    print("🚀 Démarrage du serveur GeoHotels API")
    print(f"📍 API disponible sur http://localhost:5001")
    print(f"📡 Connexion Neo4j: {URI}")
    print("-" * 50)
    app.run(debug=True, port=5001, host='0.0.0.0')