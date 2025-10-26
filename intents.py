# intents.py
from typing import List, Dict, Any, Optional
from neo4j import GraphDatabase
import re

def norm(s: str) -> str:
    return (s or "").strip().lower()

COURSE_CODE_RE = re.compile(r"\b[A-Z]{2,}-\d{3}\b")

class KGClient:
    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        # Cargar vocabulario del grafo para detección de entidades
        self._courses = self._load_courses()    # [{code,name}]
        self._skills  = self._load_skills()     # [name]
        self._areas   = self._load_areas()      # [name]

    def close(self):
        self.driver.close()

    # ---------- Bootstrap de vocabulario ----------
    def _load_courses(self) -> List[Dict[str, str]]:
        cy = "MATCH (c:Course) RETURN c.code AS code, c.name AS name"
        with self.driver.session() as s:
            return [dict(r) for r in s.run(cy)]

    def _load_skills(self) -> List[str]:
        cy = "MATCH (s:Skill) RETURN s.name AS name"
        with self.driver.session() as s:
            return [r["name"] for r in s.run(cy)]

    def _load_areas(self) -> List[str]:
        cy = "MATCH (a:Area) RETURN a.name AS name"
        with self.driver.session() as s:
            return [r["name"] for r in s.run(cy)]

    # ---------- Detección de entidades ----------
    def detect_course(self, text: str) -> Optional[Dict[str, str]]:
        t = text.strip()

        # 1) Código explícito (IS-402)
        m = COURSE_CODE_RE.search(t)
        if m:
            code = m.group(0)
            for c in self._courses:
                if c["code"].lower() == code.lower():
                    return c

        # 2) Por nombre (substring más largo que matchee)
        t_low = t.lower()
        best = None
        best_len = 0
        for c in self._courses:
            name_low = c["name"].lower()
            if name_low in t_low and len(name_low) > best_len:
                best = c
                best_len = len(name_low)
        return best

    def detect_skills(self, text: str) -> List[str]:
        t_low = text.lower()
        found = []
        for s in self._skills:
            if s.lower() in t_low:
                found.append(s)
        # además, si hay tokens sueltos como "sql" o "er"
        tokens = re.findall(r"[a-zA-ZáéíóúñÁÉÍÓÚÑ0-9]+", t_low)
        tokens = [tok for tok in tokens if len(tok) >= 2]
        # Mapear tokens simples conocidos
        alias_map = {
            "sql": "SQL",
            "er": "Modelado ER",
        }
        for tok in tokens:
            if tok in alias_map and alias_map[tok] not in found and alias_map[tok] in self._skills:
                found.append(alias_map[tok])
        return list(dict.fromkeys(found))  # únicos y en orden

    def detect_area(self, text: str) -> Optional[str]:
        t_low = text.lower()
        best = None
        best_len = 0
        for a in self._areas:
            al = a.lower()
            if al in t_low and len(al) > best_len:
                best = a
                best_len = len(al)
        return best

    # ---------- Consultas Cypher ----------
    def prerequisites_of(self, course: Dict[str, str]) -> List[Dict[str, Any]]:
        cypher = """
        MATCH (pre:Course)-[:PREREQ]->(c:Course {code: $code})
        RETURN pre.code AS code, pre.name AS name
        ORDER BY name
        """
        with self.driver.session() as s:
            return s.run(cypher, code=course["code"]).data()

    def courses_covering_skill_terms(self, terms: List[str]) -> List[Dict[str, Any]]:
        if not terms:
            return []
        cypher = """
        MATCH (c:Course)-[:COVERS]->(s:Skill)
        WHERE any(term IN $terms WHERE toLower(s.name) CONTAINS toLower(term))
        RETURN c.code AS code, c.name AS name, s.name AS skill
        ORDER BY c.name, skill
        """
        with self.driver.session() as s:
            return s.run(cypher, terms=terms).data()

    def courses_in_area(self, area_name: str) -> List[Dict[str, Any]]:
        cypher = """
        MATCH (c:Course)-[:BELONGS_TO]->(a:Area {name: $area})
        OPTIONAL MATCH (c)-[:TAUGHT_IN]->(sm:Semester)
        RETURN c.code AS code, c.name AS name, a.name AS area, sm.num AS semester
        ORDER BY semester, c.name
        """
        with self.driver.session() as s:
            return s.run(cypher, area=area_name).data()

    def skills_of_course(self, course: Dict[str, str]) -> List[Dict[str, Any]]:
        cypher = """
        MATCH (c:Course {code: $code})-[:COVERS]->(s:Skill)
        RETURN s.name AS skill
        ORDER BY s.name
        """
        with self.driver.session() as s:
            return s.run(cypher, code=course["code"]).data()

    def semester_of_course(self, course: Dict[str, str]) -> Optional[Dict[str, Any]]:
        cypher = """
        MATCH (c:Course {code: $code})-[:TAUGHT_IN]->(sm:Semester)
        RETURN c.code AS code, c.name AS name, sm.num AS semester
        """
        with self.driver.session() as s:
            row = s.run(cypher, code=course["code"]).single()
            return dict(row) if row else None
