import os, re
from typing import List, Dict, Any, Tuple
from dotenv import load_dotenv
from neo4j import GraphDatabase
from langchain_community.chat_models import ChatOllama
from langchain.schema import SystemMessage, HumanMessage
from tabulate import tabulate
import csv
import io
from afpi_context import load_schema_prompt, parse_few_shots_from_datos, default_afpi_few_shots

load_dotenv()

NEO4J_URI  = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASS", "neo4j123")
NEO4J_AUTH_DISABLED = os.getenv("NEO4J_AUTH_DISABLED", "").lower() in ("1", "true", "yes")
# 👇 modelo que SÍ existe y entra en tu 1050 de 3GB (si no, probá qwen:3b-instruct o gemma:2b)
MODEL      = os.getenv("OLLAMA_MODEL", "llama3:3b-instruct")

# ---- LLM local (Ollama) ----
# Mantengo el constructor simple; si querés limitar tokens: ChatOllama(model_kwargs={"num_predict": 512})
llm = ChatOllama(model=MODEL, temperature=0.0)

# ---- Conexión Neo4j ----
_auth = None if NEO4J_AUTH_DISABLED or (not NEO4J_USER and not NEO4J_PASS) else (NEO4J_USER, NEO4J_PASS)
driver = GraphDatabase.driver(NEO4J_URI, auth=_auth)

SCHEME_PATH = os.path.join(os.path.dirname(__file__), "SCHEME.txt")
DATOS_PATH = os.path.join(os.path.dirname(__file__), "DATOS.txt")

# Se inicializan dinámicamente a partir de SCHEME.txt y DATOS.txt
SCHEMA: str = ""
FEW_SHOTS: List[Tuple[str, str]] = []

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

def _rows_to_csv(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()

def answer_in_natural_language(question: str, rows: List[Dict[str, Any]]) -> str:
    n = len(rows)
    csv_text = _rows_to_csv(rows)

    # recomendación: poné temperature=0.0 al crear ChatOllama
    sys = SystemMessage(content=(
        "Redactá una respuesta breve en español usando EXCLUSIVAMENTE los datos de la tabla CSV."
        " Si conteo_filas > 0, NO digas 'No hay resultados'."
        " Si conteo_filas = 0, debés decir exactamente: 'No hay resultados.'"
        " No inventes datos ni columnas."
    ))
    usr = HumanMessage(content=f"Pregunta: {question}\nconteo_filas: {n}\n\nCSV:\n{csv_text if csv_text else '(sin filas)'}")
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
    # Preparar contexto dinámico
    try:
        SCHEMA = load_schema_prompt(SCHEME_PATH, driver)
    except Exception:
        SCHEMA = ""

    try:
        parsed = parse_few_shots_from_datos(DATOS_PATH)
        FEW_SHOTS = parsed if parsed else default_afpi_few_shots()
    except Exception:
        FEW_SHOTS = default_afpi_few_shots()

    print("NL→Cypher (AFPI) con LLM local (Ollama). Escribí tu pregunta o Ctrl+C para salir.\n")
    try:
        while True:
            q = input(">> ")
            if not q.strip():
                continue
            ask(q.strip())
    finally:
        driver.close()
