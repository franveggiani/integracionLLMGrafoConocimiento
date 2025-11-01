import os
from dotenv import load_dotenv
from neo4j import GraphDatabase
from tabulate import tabulate

from afpi_context import parse_few_shots_from_datos, default_afpi_few_shots


load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASS", "neo4j123")
NEO4J_AUTH_DISABLED = os.getenv("NEO4J_AUTH_DISABLED", "").lower() in ("1", "true", "yes")

HERE = os.path.dirname(__file__)
DATOS_PATH = os.path.join(HERE, "DATOS.txt")


def main():
    auth = None if NEO4J_AUTH_DISABLED or (not NEO4J_USER and not NEO4J_PASS) else (NEO4J_USER, NEO4J_PASS)
    driver = GraphDatabase.driver(NEO4J_URI, auth=auth)
    with driver.session() as s:
        shots = parse_few_shots_from_datos(DATOS_PATH)
        if not shots:
            shots = default_afpi_few_shots()

        print("Probando primeras 3 consultas de ejemplo...\n")
        for i, (q, cy) in enumerate(shots[:3], 1):
            print(f"[{i}] {q}")
            print(cy)
            try:
                rows = [dict(r) for r in s.run(cy)]
                if rows:
                    print(tabulate(rows, headers="keys", tablefmt="github"))
                else:
                    print("(sin resultados)")
            except Exception as e:
                print("Error ejecutando Cypher:", e)
            print("\n" + "-" * 60 + "\n")

    driver.close()


if __name__ == "__main__":
    main()
