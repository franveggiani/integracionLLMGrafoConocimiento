import argparse
import json
import os, re
import uuid
from typing import List, Dict, Any, Tuple
from dotenv import load_dotenv
from neo4j import GraphDatabase
from langchain_community.chat_models import ChatOllama
from langchain.schema import SystemMessage, HumanMessage
from tabulate import tabulate
from langchain.agents import AgentType, initialize_agent
from langchain.tools import Tool
import csv
import io
from afpi_context import load_schema_prompt, parse_few_shots_from_datos, default_afpi_few_shots
from pi4_nlp_ia import categorize_movement

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


def run_write_cypher(query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    with driver.session() as s:
        result = s.run(query, params)
        return [dict(r) for r in result]

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


def _rows_table(rows: List[Dict[str, Any]]) -> str:
    return tabulate(rows, headers="keys", tablefmt="github") if rows else "(sin filas)"


def _default_movement_id(user_id: str, fecha: str) -> str:
    safe_user = user_id.replace("#", "_")
    safe_fecha = fecha.replace("-", "")
    rand_suffix = uuid.uuid4().hex[:6]
    return f"mov#{safe_fecha}#{safe_user}#{rand_suffix}"


def _default_goal_id(user_id: str, nombre: str) -> str:
    base = nombre.lower().replace(" ", "_")
    rand_suffix = uuid.uuid4().hex[:4]
    return f"obj#{base}#{user_id.replace('#','_')}#{rand_suffix}"


def _parse_json_payload(raw_input: str) -> Tuple[Dict[str, Any], str]:
    try:
        payload = json.loads(raw_input)
        if not isinstance(payload, dict):
            return {}, "El payload debe ser un objeto JSON (clave/valor)."
        return payload, ""
    except json.JSONDecodeError as exc:
        return {}, f"JSON inválido: {exc}"

def run_graph_pipeline(question: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "question": question,
        "cypher": "",
        "rows": [],
        "answer": "",
        "error": None,
    }
    cypher = generate_cypher(question)
    result["cypher"] = cypher

    if not is_safe_cypher(cypher):
        result["error"] = "La consulta generada no es segura o contiene operaciones no permitidas."
        return result

    try:
        rows = run_cypher(cypher)
    except Exception as e:
        result["error"] = f"Error al ejecutar Cypher: {e}"
        return result

    result["rows"] = rows
    result["answer"] = answer_in_natural_language(question, rows)
    return result


def ask(question: str):
    print(f"\n🟢 Pregunta: {question}")
    result = run_graph_pipeline(question)

    if result["error"]:
        print(f"\n⚠️ {result['error']}\n")
        print(result["cypher"])
        return

    print("\n📄 Cypher generado:\n")
    print(result["cypher"])

    rows = result["rows"]
    if rows:
        print("\n📊 Resultado:")
        print(_rows_table(rows))
    else:
        print("\n📭 Sin resultados.")

    print("\n🗣️ Respuesta:")
    print(result["answer"])


def graph_tool(question: str) -> str:
    result = run_graph_pipeline(question)
    if result["error"]:
        return f"ERROR: {result['error']}\nCypher:\n{result['cypher']}"

    table_text = _rows_table(result["rows"])
    return (
        f"Pregunta original: {question}\n"
        f"Cypher ejecutado:\n{result['cypher']}\n"
        f"Tabla:\n{table_text}\n"
        f"Respuesta_resumida: {result['answer']}"
    )


def create_movement_tool(raw_input: str) -> str:
    payload, err = _parse_json_payload(raw_input)
    if err:
        return f"ERROR: {err}"

    required = ["user_id", "tipo", "fecha", "descripcion", "monto", "categoria_id"]
    missing = [k for k in required if not payload.get(k)]
    if missing:
        return f"ERROR: faltan campos obligatorios: {', '.join(missing)}"

    try:
        monto = float(payload["monto"])
    except (TypeError, ValueError):
        return "ERROR: 'monto' debe ser numérico."

    movement_id = payload.get("movement_id") or _default_movement_id(payload["user_id"], payload["fecha"])
    params = {
        "movement_id": movement_id,
        "user_id": payload["user_id"],
        "tipo": payload["tipo"],
        "fecha": payload["fecha"],
        "descripcion": payload["descripcion"],
        "monto": monto,
        "categoria_id": payload["categoria_id"],
    }

    query = """
    MATCH (movF:Frame {name:'Movimiento'})
    MERGE (mov:FrameInst {id:$movement_id})-[:INSTANCE_OF]->(movF)
    WITH mov
    UNWIND [
        {slot:'tipoDeMovimiento', slot_name:'tipoDeMovimiento', value:$tipo},
        {slot:'fecha', slot_name:'fecha', value:$fecha},
        {slot:'descripcion', slot_name:'descripcion', value:$descripcion},
        {slot:'monto', slot_name:'monto', value:$monto}
    ] AS data
    MATCH (slot:Slot {name:data.slot_name})
    MERGE (mov)-[r:HAS_VALUE]->(slot)
    SET r.slot = data.slot,
        r.value = CASE
            WHEN data.slot_name='fecha' THEN date(data.value)
            WHEN data.slot_name='monto' THEN toFloat(data.value)
            ELSE data.value
        END,
        r.ts = datetime()
    WITH mov
    MATCH (usr:FrameInst {id:$user_id})
    MERGE (usr)-[:REALIZA]->(mov)
    WITH mov
    MATCH (cat:FrameInst {id:$categoria_id})
    MERGE (mov)-[:PERTENECE_A]->(cat)
    RETURN mov.id AS movimiento_id
    """

    try:
        rows = run_write_cypher(query, params)
    except Exception as exc:
        return f"ERROR al insertar movimiento: {exc}"

    mov_id = rows[0]["movimiento_id"] if rows else movement_id
    return (
        "Movimiento registrado correctamente.\n"
        f"- movement_id: {mov_id}\n"
        f"- usuario: {params['user_id']}\n"
        f"- categoría: {params['categoria_id']}\n"
        f"- monto: {monto}\n"
        f"- fecha: {params['fecha']}"
    )


def create_goal_tool(raw_input: str) -> str:
    payload, err = _parse_json_payload(raw_input)
    if err:
        return f"ERROR: {err}"

    required = ["user_id", "nombre", "monto_meta", "fecha_limite", "progreso"]
    missing = [k for k in required if not payload.get(k)]
    if missing:
        return f"ERROR: faltan campos obligatorios: {', '.join(missing)}"

    try:
        monto_meta = float(payload["monto_meta"])
        progreso = float(payload["progreso"])
    except (TypeError, ValueError):
        return "ERROR: 'monto_meta' y 'progreso' deben ser numéricos."

    objetivo_id = payload.get("objetivo_id") or _default_goal_id(payload["user_id"], payload["nombre"])

    params = {
        "objetivo_id": objetivo_id,
        "user_id": payload["user_id"],
        "nombre": payload["nombre"],
        "monto_meta": monto_meta,
        "fecha_limite": payload["fecha_limite"],
        "progreso": progreso,
    }

    query = """
    MATCH (frame:Frame {name:'Objetivo de Ahorro'})
    MERGE (obj:FrameInst {id:$objetivo_id})-[:INSTANCE_OF]->(frame)
    WITH obj
    UNWIND [
        {slot:'nombre', slot_name:'nombre', value:$nombre},
        {slot:'montoMeta', slot_name:'montoMeta', value:$monto_meta},
        {slot:'fechaLímite', slot_name:'fechaLímite', value:$fecha_limite},
        {slot:'progreso', slot_name:'progreso', value:$progreso}
    ] AS data
    MATCH (slot:Slot {name:data.slot_name})
    MERGE (obj)-[r:HAS_VALUE]->(slot)
    SET r.slot = data.slot,
        r.value = CASE
            WHEN data.slot_name='fechaLímite' THEN date(data.value)
            WHEN data.slot_name IN ['montoMeta', 'progreso'] THEN toFloat(data.value)
            ELSE data.value
        END,
        r.ts = datetime()
    WITH obj
    MATCH (usr:FrameInst {id:$user_id})
    MERGE (usr)-[:TIENE]->(obj)
    RETURN obj.id AS objetivo_id
    """

    try:
        rows = run_write_cypher(query, params)
    except Exception as exc:
        return f"ERROR al insertar objetivo: {exc}"

    obj_id = rows[0]["objetivo_id"] if rows else objetivo_id
    return (
        "Objetivo de ahorro registrado correctamente.\n"
        f"- objetivo_id: {obj_id}\n"
        f"- usuario: {params['user_id']}\n"
        f"- meta: {monto_meta}\n"
        f"- fecha límite: {params['fecha_limite']}\n"
        f"- progreso: {progreso}%"
    )


def classify_movement_tool(raw_input: str) -> str:
    descripcion = raw_input.strip()
    if not descripcion:
        return "ERROR: proporcioná la descripción textual del movimiento."

    lowered = descripcion.lower()
    if lowered.startswith("descripcion") and ":" in descripcion:
        descripcion = descripcion.split(":", 1)[1].strip()

    try:
        categoria = categorize_movement(descripcion)
    except Exception as exc:
        return f"ERROR al clasificar: {exc}"

    return (
        "Clasificación de movimiento:\n"
        f"- Descripción: {descripcion}\n"
        f"- Categoría sugerida: {categoria}\n"
        "Utilizá esta categoría al registrar el nuevo movimiento."
    )


AGENT_SYSTEM_PROMPT = (
    "Actuás como asistente financiero AFPI.\n"
    "- Tu prioridad es responder consultas (solo lectura) usando la herramienta consultar_grafo_afpi.\n"
    "- Solo usá registrar_movimiento o registrar_objetivo_ahorro cuando el usuario pida explícitamente "
    "crear/registrar/insertar/agregar un nuevo movimiento u objetivo y provea (o puedas inferir) todos los datos requeridos.\n"
    "- No intentes registrar nada si la persona solo quiere 'saber', 'ver', 'listar' o 'consultar'.\n"
    "- Antes de llamar a una herramienta de registro, verificá que user_id sea válido y que haya valores no vacíos.\n"
    "- Para clasificar una descripción sin crear registros, usá clasificar_movimiento_nuevo.\n"
    "- Nunca intentes registrar un movimiento/objetivo si la persona solo quiere consultar o no dio datos completos.\n"
    "- Respetá siempre estos pasos y explicá cualquier error sin reintentar automáticamente."
)

INSERT_KEYWORDS = [
    "registr",
    "crear",
    "agregar",
    "cargar",
    "insert",
    "nuevo movimiento",
    "nuevo objetivo",
    "dar de alta",
    "sumar un movimiento",
    "sumar un objetivo",
]


def wants_write_intent(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in INSERT_KEYWORDS)


def build_agent(include_write: bool = True):
    tools = [
        Tool(
            name="consultar_grafo_afpi",
            func=graph_tool,
            description=(
                "Usá esta herramienta para responder preguntas sobre el grafo AFPI. "
                "El input debe ser la pregunta en español tal como la hizo el usuario."
            ),
        ),
        Tool(
            name="clasificar_movimiento_nuevo",
            func=classify_movement_tool,
            description=(
                "Usá esta herramienta cuando el usuario quiera introducir/registrar "
                "un nuevo movimiento y necesite que se categorice automáticamente. "
                "Proveé como input la descripción del movimiento (texto libre, puede incluir monto o contexto)."
            ),
        ),
    ]

    if include_write:
        tools.extend(
            [
                Tool(
                    name="registrar_movimiento",
                    func=create_movement_tool,
                    description=(
                        "Inserta un nuevo movimiento. Proveé un JSON con campos: "
                        "user_id, tipo (Ingreso/Gasto), fecha (YYYY-MM-DD), descripcion, "
                        "monto (float), categoria_id, opcional movement_id."
                    ),
                ),
                Tool(
                    name="registrar_objetivo_ahorro",
                    func=create_goal_tool,
                    description=(
                        "Inserta un objetivo de ahorro. Proveé un JSON con campos: user_id, "
                        "nombre, monto_meta, fecha_limite (YYYY-MM-DD), progreso (porcentaje), "
                        "opcional objetivo_id."
                    ),
                ),
            ]
        )

    agent = initialize_agent(
        tools=tools,
        llm=llm,
        agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
        verbose=True,
        handle_parsing_errors=True,
        agent_kwargs={"system_prompt": AGENT_SYSTEM_PROMPT},
        max_iterations=4,
    )
    return agent


def run_agent_loop(read_agent, write_agent):
    print("Asistente AFPI con agente LangChain (consultas + clasificación + registros controlados).\n")
    while True:
        q = input(">> ").strip()
        if not q:
            continue
        try:
            agent = write_agent if wants_write_intent(q) else read_agent
            result = agent.invoke({"input": q})
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"\n❌ Error del agente: {exc}\n")
            continue
        output = result.get("output", result)
        print(f"\n🟢 Salida del asistente:\n{output}\n")


def run_legacy_loop():
    print("NL→Cypher (AFPI) sin agente. Escribí tu pregunta o Ctrl+C para salir.\n")
    while True:
        q = input(">> ")
        if not q.strip():
            continue
        ask(q.strip())

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Asistente AFPI (Neo4j + LangChain + Ollama).")
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Usar el modo tradicional (solo NL→Cypher) sin agente ni clasificación automática.",
    )
    args = parser.parse_args()

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

    try:
        if args.legacy:
            run_legacy_loop()
        else:
            read_agent = build_agent(include_write=False)
            full_agent = build_agent(include_write=True)
            run_agent_loop(read_agent, full_agent)
    finally:
        driver.close()
