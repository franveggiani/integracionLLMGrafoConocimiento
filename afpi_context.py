import os
import re
from typing import List, Tuple


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _introspect_graph(driver) -> str:
    """
    Lee del grafo los nombres de Frames, Slots y tipos de relaciones
    para enriquecer el prompt del modelo con contexto real.
    No es obligatorio; si falla, devuelve cadena vacía.
    """
    try:
        with driver.session() as s:
            frames = s.run("MATCH (f:Frame) RETURN collect(DISTINCT f.name) AS frames").single()
            slots = s.run("MATCH (s:Slot) RETURN collect(DISTINCT s.name) AS slots").single()
            rels = s.run("MATCH ()-[r]-() RETURN collect(DISTINCT type(r)) AS reltypes").single()
            frames_list = (frames[0] if frames and frames[0] else [])
            slots_list = (slots[0] if slots and slots[0] else [])
            rels_list = (rels[0] if rels and rels[0] else [])
            return (
                "Contexto detectado en BD:\n"
                f"Frames: {sorted(frames_list)}\n"
                f"Slots: {sorted(slots_list)}\n"
                f"Tipos de relaciones: {sorted(rels_list)}\n"
            )
    except Exception:
        return ""


def load_schema_prompt(schema_file: str, driver) -> str:
    """
    Construye un prompt de esquema a partir de SCHEME.txt y la introspección
    de la BD. No ejecuta nada, solo usa texto de referencia.
    """
    raw = _read_text(schema_file)
    intro = (
        "Metamodelo AFPI (Frames/Slots/FrameInst):\n"
        "- Nodos: Frame {name}, Slot {name}, FrameInst {id}.\n"
        "- Relaciones claves:\n"
        "  * (fi:FrameInst)-[:INSTANCE_OF]->(f:Frame)\n"
        "  * (fi)-[:HAS_VALUE {slot, value, ts?}]->(s:Slot)\n"
        "  * (usr:FrameInst)-[:REALIZA]->(mov:FrameInst)\n"
        "  * (mov)-[:PERTENECE_A]->(cat:FrameInst)\n"
        "  * (usr)-[:TIENE]->(obj:FrameInst)\n"
        "  * (usr)-[:RECIBE]->(rec:FrameInst)\n"
        "  * (rec)-[:BASADO_EN]->(cat), (rec)-[:DIRIGIDA_A]->(obj)\n"
        "- Slots frecuentes: nombre, esencialidad, umbralDeGasto, tipoDeMovimiento, fecha, descripcion, monto, montoMeta, fechaLímite, progreso, tipo_recomendacion.\n"
        "- Importante: consultas SOLO de lectura (MATCH/OPTIONAL MATCH/WHERE/RETURN/ORDER BY/LIMIT/UNWIND).\n"
        "  NO usar CREATE, MERGE, DELETE, DETACH, SET, DROP, CALL, LOAD, REMOVE, FOREACH, APOC, IMPORT.\n"
    )
    detected = _introspect_graph(driver)
    # Truncar el archivo para evitar pasajes excesivos de triggers/DDL; nos interesa como referencia.
    schema_excerpt = "\n".join(raw.splitlines()[:200]) if raw else ""
    return f"{intro}\n{detected}\nReferencia (extracto SCHEME.txt):\n{schema_excerpt}"


CY_KEYWORDS = (
    "MATCH", "OPTIONAL MATCH", "WHERE", "WITH", "RETURN", "ORDER BY", "LIMIT",
    "UNWIND", "CALL", "MERGE", "CREATE", "SET", "DELETE", "DETACH", "FOREACH",
)


def parse_few_shots_from_datos(datos_file: str) -> List[Tuple[str, str]]:
    """
    Parsea la sección "CONSULTAS DE EJEMPLO PARA LANGCHAIN" de DATOS.txt
    y genera pares (pregunta, cypher) a partir de comentarios y sentencias comentadas.
    Devuelve lista vacía si no encuentra nada.
    """
    txt = _read_text(datos_file)
    if not txt:
        return []
    # Encontrar ancla
    m = re.search(r"CONSULTAS DE EJEMPLO PARA LANGCHAIN", txt, re.I)
    if not m:
        return []
    lines = txt[m.end():].splitlines()

    def is_comment(line: str) -> bool:
        return line.strip().startswith("//")

    def strip_comment(line: str) -> str:
        return re.sub(r"^\s*//\s?", "", line).rstrip()

    def starts_with_cypher_kw(s: str) -> bool:
        up = s.lstrip().upper()
        return any(up.startswith(kw) for kw in CY_KEYWORDS)

    shots: List[Tuple[str, str]] = []
    q_current = None
    cy_lines: List[str] = []

    for raw in lines:
        if not is_comment(raw):
            # Fin de bloque
            if q_current and cy_lines:
                shots.append((q_current, "\n".join(cy_lines).strip()))
            q_current, cy_lines = None, []
            continue

        s = strip_comment(raw)
        if not s:
            continue

        if q_current is None and not starts_with_cypher_kw(s):
            # Línea descriptiva => usar como pregunta
            q_current = s.strip()
            cy_lines = []
            continue

        # Si tenemos pregunta activa y esto parece cypher, lo acumulamos
        if q_current is not None and starts_with_cypher_kw(s):
            cy_lines.append(s)

    # Flush final
    if q_current and cy_lines:
        shots.append((q_current, "\n".join(cy_lines).strip()))

    # Limpiar posibles encabezados residuales que no formaron bloque
    return shots


def default_afpi_few_shots() -> List[Tuple[str, str]]:
    """Fallback con ejemplos manuales para AFPI si no se pudieron parsear del DATOS."""
    return [
        (
            "Ver todos los movimientos de un usuario con sus categorías",
            (
                "MATCH (u:FrameInst {id:'user#maria'})-[:REALIZA]->(m:FrameInst)-[:INSTANCE_OF]->(:Frame {name:'Movimiento'})\n"
                "OPTIONAL MATCH (m)-[:PERTENECE_A]->(cat:FrameInst)-[:INSTANCE_OF]->(:Frame {name:'Categoría'})\n"
                "OPTIONAL MATCH (m)-[hvMonto:HAS_VALUE]->(:Slot {name:'monto'})\n"
                "OPTIONAL MATCH (m)-[hvTipo:HAS_VALUE]->(:Slot {name:'tipoDeMovimiento'})\n"
                "RETURN m.id AS movimiento, hvTipo.value AS tipo, hvMonto.value AS monto, cat.id AS categoria\n"
                "ORDER BY movimiento"
            ),
        ),
        (
            "Calcular gasto total por categoría de un usuario",
            (
                "MATCH (u:FrameInst {id:'user#maria'})-[:REALIZA]->(m:FrameInst)-[:PERTENECE_A]->(cat:FrameInst)\n"
                "MATCH (cat)-[:HAS_VALUE]->(:Slot {name:'nombre'})\n"
                "MATCH (m)-[hvTipo:HAS_VALUE]->(:Slot {name:'tipoDeMovimiento'})\n"
                "WHERE hvTipo.value = 'Gasto'\n"
                "MATCH (m)-[hvMonto:HAS_VALUE]->(:Slot {name:'monto'})\n"
                "RETURN cat.id AS categoria, SUM(hvMonto.value) AS total_gastado\n"
                "ORDER BY total_gastado DESC"
            ),
        ),
        (
            "Ver objetivos de ahorro de un usuario con su progreso",
            (
                "MATCH (u:FrameInst {id:'user#maria'})-[:TIENE]->(obj:FrameInst)-[:INSTANCE_OF]->(:Frame {name:'Objetivo de Ahorro'})\n"
                "MATCH (obj)-[hvMeta:HAS_VALUE]->(:Slot {name:'montoMeta'})\n"
                "MATCH (obj)-[hvProg:HAS_VALUE]->(:Slot {name:'progreso'})\n"
                "MATCH (obj)-[hvFecha:HAS_VALUE]->(:Slot {name:'fechaLímite'})\n"
                "RETURN obj.id AS objetivo, hvMeta.value AS meta, hvProg.value AS progreso_porcentaje, hvFecha.value AS fecha_limite"
            ),
        ),
        (
            "Ver recomendaciones de un usuario",
            (
                "MATCH (u:FrameInst {id:'user#maria'})-[:RECIBE]->(rec:FrameInst)-[:INSTANCE_OF]->(:Frame {name:'Recomendación'})\n"
                "MATCH (rec)-[hvDesc:HAS_VALUE]->(:Slot {name:'descripcion'})\n"
                "MATCH (rec)-[hvTipo:HAS_VALUE]->(:Slot {name:'tipo_recomendacion'})\n"
                "OPTIONAL MATCH (rec)-[:BASADO_EN]->(cat:FrameInst)\n"
                "OPTIONAL MATCH (cat)-[hvCat:HAS_VALUE]->(:Slot {name:'nombre'})\n"
                "RETURN rec.id AS recomendacion, hvDesc.value AS descripcion, hvTipo.value AS tipo, hvCat.value AS categoria"
            ),
        ),
        (
            "Resumen financiero completo de un usuario",
            (
                "MATCH (u:FrameInst {id:'user#maria'})\n"
                "OPTIONAL MATCH (u)-[:REALIZA]->(m:FrameInst)-[hvTipo:HAS_VALUE]->(:Slot {name:'tipoDeMovimiento'})\n"
                "OPTIONAL MATCH (m)-[hvMonto:HAS_VALUE]->(:Slot {name:'monto'})\n"
                "WITH u, \n"
                "     SUM(CASE WHEN hvTipo.value = 'Ingreso' THEN hvMonto.value ELSE 0 END) AS total_ingresos,\n"
                "     SUM(CASE WHEN hvTipo.value = 'Gasto' THEN hvMonto.value ELSE 0 END) AS total_gastos\n"
                "OPTIONAL MATCH (u)-[:TIENE]->(obj:FrameInst)-[:INSTANCE_OF]->(:Frame {name:'Objetivo de Ahorro'})\n"
                "RETURN u.id AS usuario, total_ingresos, total_gastos, (total_ingresos - total_gastos) AS balance, COUNT(obj) AS objetivos_activos"
            ),
        ),
    ]
