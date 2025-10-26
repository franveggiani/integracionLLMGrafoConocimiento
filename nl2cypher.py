import os, re
from typing import List, Dict, Any
from dotenv import load_dotenv
from neo4j import GraphDatabase
from langchain_community.chat_models import ChatOllama
from langchain.schema import SystemMessage, HumanMessage
from tabulate import tabulate

load_dotenv()

NEO4J_URI  = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASS", "neo4j123")
# 👇 modelo que SÍ existe y entra en tu 1050 de 3GB (si no, probá qwen:3b-instruct o gemma:2b)
MODEL      = os.getenv("OLLAMA_MODEL", "llama3:3b-instruct")

# ---- LLM local (Ollama) ----
# Mantengo el constructor simple; si querés limitar tokens: ChatOllama(model_kwargs={"num_predict": 512})
llm = ChatOllama(model=MODEL, temperature=0.1)

# ---- Conexión Neo4j ----
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

# ---- Esquema del grafo ----
SCHEMA = """
NODES (labels, properties):
- Course {code: STRING, name: STRING}
- Area {name: STRING}
- Semester {num: INTEGER}
- Skill {name: STRING}
- Category {name: STRING}

RELATIONSHIPS (type):
- (Course)-[:BELONGS_TO]->(Area)
- (Course)-[:TAUGHT_IN]->(Semester)
- (Course)-[:COVERS]->(Skill)
- (Course)-[:IS_A]->(Category)
- (Course)-[:PREREQ]->(Course)

REGLAS:
- Generá SOLO una consulta Cypher de lectura (MATCH/OPTIONAL MATCH/WHERE/RETURN/ORDER BY/LIMIT/UNWIND).
- NO uses CREATE, MERGE, DELETE, DETACH, SET, DROP, CALL, LOAD, REMOVE, FOREACH, APOC, IMPORT.
- Devolvé columnas con nombres descriptivos.
- Devolvé SOLO un bloque ```cypher``` con la consulta (sin texto adicional).
"""

FEW_SHOTS = [
# 1) Prerrequisitos de un curso (por nombre)
("¿Qué materias tengo que aprobar antes de cursar Minería de Datos?",
"""MATCH (pre:Course)-[:PREREQ]->(c:Course {name: "Minería de Datos"})
RETURN pre.code AS code, pre.name AS name
ORDER BY name"""),
# 2) Cursos que cubren una competencia
("¿Qué cursos cubren SQL y Modelado ER?",
"""MATCH (c:Course)-[:COVERS]->(s:Skill)
WHERE toLower(s.name) IN [toLower("SQL"), toLower("Modelado ER")]
RETURN c.code AS code, c.name AS course, collect(DISTINCT s.name) AS skills
ORDER BY course"""),
# 3) Cursos por área
("Mostrame cursos del área Bases de Datos y en qué semestre se dictan",
"""MATCH (c:Course)-[:BELONGS_TO]->(a:Area {name: "Bases de Datos"})
OPTIONAL MATCH (c)-[:TAUGHT_IN]->(sm:Semester)
RETURN c.code AS code, c.name AS course, a.name AS area, sm.num AS semester
ORDER BY semester, course"""),
# 4) Semestre de un curso (por código)
("¿En qué semestre se dicta IS-401?",
"""MATCH (c:Course {code: "IS-401"})-[:TAUGHT_IN]->(sm:Semester)
RETURN c.code AS code, c.name AS course, sm.num AS semester"""),
# 5) Competencias de un curso
("¿Qué competencias enseña Ingeniería de Software I?",
"""MATCH (c:Course {name: "Ingeniería de Software I"})-[:COVERS]->(s:Skill)
RETURN c.code AS code, c.name AS course, collect(s.name) AS skills
ORDER BY course"""),
]

def extract_cypher(text: str) -> str:
    """
    Extrae la consulta del bloque ```cypher ...``` si existe.
    Si no viene fenceado, devuelve el texto limpio.
    """
    m = re.search(r"```cypher\s*(.*?)```", text, re.S | re.I)
    if m:
        return m.group(1).strip()
    # También aceptar bloque sin 'cypher' explícito
    m2 = re.search(r"```(.*?)```", text, re.S)
    if m2:
        return m2.group(1).strip()
    # fallback: todo el texto
    return text.strip()

def is_safe_cypher(q: str) -> bool:
    """
    Permite solo lectura. Bloquea instrucciones peligrosas.
    Acepta UNWIND, listas, IN, funciones, OPTIONAL MATCH, etc.
    Requiere que haya un RETURN.
    """
    # sacar comentarios de línea
    q_no_comments = re.sub(r"//.*?$", "", q, flags=re.M).strip()
    q_up = q_no_comments.upper()

    banned = [
        "CREATE", "MERGE", "DELETE", "DETACH", "SET", "DROP",
        "CALL", "LOAD", "REMOVE", "FOREACH", "APOC", "IMPORT"
    ]
    # bloquear si aparece cualquier palabra prohibida como palabra entera
    if any(re.search(rf"\b{kw}\b", q_up) for kw in banned):
        return False

    # Debe tener RETURN para garantizar que sea lectura con salida
    if "RETURN" not in q_up:
        return False

    return True

def generate_cypher(question: str) -> str:
    shots = "\n\n".join(
        f"Usuario: {q}\nCypher:\n```cypher\n{a}\n```"
        for q, a in FEW_SHOTS
    )
    sys = SystemMessage(
        content=(
            f"Actuá como traductor NL→Cypher sobre este esquema:\n{SCHEMA}\n\n"
            f"Ejemplos:\n{shots}\n"
            f"Recordatorio: devolvé SOLO un bloque ```cypher```."
        )
    )
    usr = HumanMessage(content=question)
    resp = llm.invoke([sys, usr])
    return extract_cypher(resp.content)

def run_cypher(query: str) -> List[Dict[str, Any]]:
    with driver.session() as s:
        return [dict(r) for r in s.run(query)]

def answer_in_natural_language(question: str, rows: List[Dict[str, Any]]) -> str:
    table = tabulate(rows, headers="keys", tablefmt="github") if rows else "(sin filas)"
    sys = SystemMessage(content="Redactá una respuesta breve en español usando EXCLUSIVAMENTE los datos de la tabla dada. Si no hay datos, indicá que no hay resultados.")
    usr = HumanMessage(content=f"Pregunta: {question}\n\nDatos:\n{table}")
    resp = llm.invoke([sys, usr])
    return resp.content.strip()

def ask(question: str):
    print(f"\n🟢 Pregunta: {question}")
    cypher = generate_cypher(question)

    if not is_safe_cypher(cypher):
        print("\n⚠️ La consulta generada no es segura o contiene operaciones no permitidas.\n")
        print(cypher)
        return

    print("\n📄 Cypher generado:\n")
    print(cypher)

    try:
        rows = run_cypher(cypher)
    except Exception as e:
        print("\n❌ Error al ejecutar Cypher:", e)
        return

    if rows:
        print("\n📊 Resultado:")
        print(tabulate(rows, headers="keys", tablefmt="github"))
    else:
        print("\n📭 Sin resultados.")

    nl = answer_in_natural_language(question, rows)
    print("\n🗣️ Respuesta:")
    print(nl)

if __name__ == "__main__":
    print("NL→Cypher con LLM local (Ollama). Escribí tu pregunta o Ctrl+C para salir.\n")
    try:
        while True:
            q = input(">> ")
            if not q.strip():
                continue
            ask(q.strip())
    finally:
        driver.close()
