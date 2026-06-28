from neo4j import GraphDatabase

URI = "neo4j://127.0.0.1:7687"
AUTH = ("siaw", "20032003")

def tester_connexion():
    try:
        with GraphDatabase.driver(URI, auth=AUTH) as driver:
            driver.verify_connectivity()
            print("🚀 Connexion réussie entre Python et Neo4j !")
    except Exception as e:
        print(f"❌ Erreur de connexion : {e}")

if __name__ == "__main__":
    tester_connexion()