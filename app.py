# app.py
import os
from dotenv import load_dotenv
from typing import Dict, Any
from langchain_community.chat_models import ChatOllama
from langchain.schema import HumanMessage, SystemMessage
from intents import KGClient, norm

load_dotenv()

NEO4J_URI  = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASS", "neo4j123")
MODEL      = os.getenv("OLLAMA_MODEL", "gemma:2b")

llm = ChatOllama(model=MODEL, temperature=0.2)
kg  = KGClient(NEO4J_URI, NEO4J_USER, NEO4J_PASS)

SYSTEM_PROMPT = """Sos un asistente que responde en español, breve y preciso.
Usá exclusivamente el CONTEXTO para fundamentar tu respuesta.
Si el contexto no alcanza, decí explícitamente "No tengo datos suficientes en el grafo".
Cuando corresponda, devolvé viñetas cortas.
"""

def bullets(rows, fmt):
    if not rows:
        return "- (sin resultados)\n"
    return "".join(fmt(r) for r in rows)

def route_and_query(question: str) -> Dict[str, Any]:
    q = norm(question)

    # 1) Prerrequisitos
    if "prerrequisit" in q or "antes de cursar" in q:
        course = kg.detect_course(question)
        ctx = kg.prerequisites_of(course) if course else []
        return {"intent": "prereqs", "context": ctx, "meta": {"course": course}}

    # 2) Cursos que cubren skills
    if "cubre" in q or "cubren" in q or "competenc" in q:
        terms = [t.lower() for t in kg.detect_skills(question)]
        ctx = kg.courses_covering_skill_terms(terms) if terms else []
        return {"intent": "courses_by_skill", "context": ctx, "meta": {"skills": terms}}

    # 3) Cursos en un área
    if "área" in q or "area" in q:
        area = kg.detect_area(question)
        ctx = kg.courses_in_area(area) if area else []
        return {"intent": "courses_in_area", "context": ctx, "meta": {"area": area}}

    # 4) Competencias de un curso
    if "competencias de" in q or "qué enseña" in q or "que enseña" in q:
        course = kg.detect_course(question)
        ctx = kg.skills_of_course(course) if course else []
        return {"intent": "skills_of_course", "context": ctx, "meta": {"course": course}}

    # 5) Semestre de un curso
    if "semestre" in q or "cuatri" in q:
        course = kg.detect_course(question)
        row = kg.semester_of_course(course) if course else None
        return {"intent": "semester_of_course", "context": [row] if row else [], "meta": {"course": course}}

    # Fallback
    return {"intent": "fallback", "context": [], "meta": {}}

def make_context_text(intent: str, ctx) -> str:
    if intent == "prereqs":
        return "Prerrequisitos del curso:\n" + bullets(ctx, lambda r: f"- {r['code']}: {r['name']}\n")
    if intent == "courses_by_skill":
        return "Cursos que cubren la/las competencias:\n" + bullets(ctx, lambda r: f"- {r['code']}: {r['name']} (skill: {r['skill']})\n")
    if intent == "courses_in_area":
        return "Cursos del área:\n" + bullets(ctx, lambda r: f"- {r['code']}: {r['name']} (semestre: {r.get('semester')})\n")
    if intent == "skills_of_course":
        return "Competencias del curso:\n" + bullets(ctx, lambda r: f"- {r['skill']}\n")
    if intent == "semester_of_course":
        if not ctx:
            return "No se encontró el curso en el grafo.\n"
        r = ctx[0]
        return f"Semestre del curso:\n- {r['code']}: {r['name']} → semestre {r['semester']}\n"
    return "No hay contexto del grafo disponible.\n"

def answer(question: str) -> str:
    routed = route_and_query(question)
    context_text = make_context_text(routed["intent"], routed["context"])

    msgs = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"CONTEXTO DEL GRAFO:\n{context_text}\n\nPREGUNTA:\n{question}")
    ]
    resp = llm.invoke(msgs)
    return resp.content

if __name__ == "__main__":
    tests = [
        "¿Qué materias tengo que aprobar antes de cursar Minería de Datos?",
        "¿Qué cursos cubren SQL y Modelado ER?",
        "Mostrame cursos del área Bases de Datos y en qué semestre se dictan",
    ]
    for i, q in enumerate(tests, 1):
        print(f"\n=== PREGUNTA {i} ===")
        print(q)
        print("\n--- RESPUESTA ---")
        print(answer(q))

    kg.close()
