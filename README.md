# NL → Cypher con Neo4j y Ollama

Este proyecto convierte preguntas en español sobre un plan de estudios en consultas Cypher válidas, las ejecuta en un grafo Neo4j y devuelve la respuesta en lenguaje natural. Usa un modelo local servido por [Ollama](https://ollama.com/) para el razonamiento en lenguaje natural y un contenedor Neo4j con un dataset mínimo de materias, habilidades y prerrequisitos.

## Requisitos
- Python 3.10 o superior.
- [Ollama](https://ollama.com/download) instalado y con el modelo configurado (por defecto `llama3:3b-instruct`, configurable vía `.env`).
- Docker para ejecutar Neo4j (opcional si ya tenés una instancia disponible).

## Instalación rápida
```bash
git clone <repo>
cd pi5-ia
python -m venv .venv
source .venv/bin/activate  # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Configuración
El archivo `.env` define la conexión a Neo4j y el modelo de Ollama:
```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASS=neo4j123
OLLAMA_MODEL=llama3:3b-instruct
```
- Ajustá `OLLAMA_MODEL` si querés usar variantes más livianas (`qwen:3b-instruct`, `gemma:2b`, etc.).
- Si tu instancia Neo4j usa otras credenciales o URL, actualizá los valores correspondientes.

## Levantar Neo4j con Docker
Hay un script de ayuda (`run_neo4j.sh`) que levanta Neo4j con los plugins APOC y GDS habilitados:
```bash
./run_neo4j.sh
```
El contenedor expone el navegador en http://localhost:7474 y el puerto Bolt en `bolt://localhost:7687`. Las credenciales por defecto son `neo4j / neo4j123`.

## Cargar el dataset de ejemplo
Una vez que Neo4j está en funcionamiento:
1. Abrí http://localhost:7474/browser.
2. Iniciá sesión con las credenciales configuradas.
3. Copiá y pegá el contenido de `consulta-cypher.txt` en el editor y ejecutalo.  
   Esto crea nodos de cursos, áreas, competencias, semestres y sus relaciones.

## Ejecutar el asistente NL → Cypher
1. Asegurate de que Ollama esté activo (`ollama serve`) y que tengas el modelo descargado (`ollama run llama3:3b-instruct` al menos una vez).
2. Con el entorno virtual activado:
   ```bash
   python nl2cypher.py
   ```
3. Escribí tu pregunta en español. Ejemplos:
   - `¿Qué materias tengo que aprobar antes de cursar Minería de Datos?`
   - `Mostrame cursos del área Bases de Datos y en qué semestre se dictan`

El programa:
1. Genera una consulta Cypher usando few-shots y restricciones de seguridad.
2. Ejecuta la consulta contra Neo4j.
3. Presenta los resultados tabulados y redacta una respuesta breve basada únicamente en esos datos.

Si la consulta generada contiene palabras clave no permitidas (CREATE, MERGE, DELETE, etc.) el script la bloquea para proteger la base.

## Estructura del código
- `nl2cypher.py` contiene:
  - Carga de variables de entorno y creación del cliente Ollama (`ChatOllama`).
  - Generación de Cypher a partir de preguntas usando ejemplos (`FEW_SHOTS`) y un prompt de sistema con el esquema del grafo.
  - Validación de seguridad básica (`is_safe_cypher`) que fuerza consultas de solo lectura.
  - Ejecución de la consulta y tabulado del resultado.
  - Generación de una respuesta en lenguaje natural basada en CSV.
- `consulta-cypher.txt` ofrece el script para poblar Neo4j con el plan de estudios.
- `run_neo4j.sh` levanta un contenedor Neo4j listo para usar.

## Consejos de solución de problemas
- **Errores de conexión**: confirmá que Neo4j corre en el puerto configurado y que `NEO4J_URI` apunta ahí.
- **Modelo inexistente**: si Ollama no tiene el modelo solicitado, ejecutá `ollama pull <modelo>` o modificá `OLLAMA_MODEL`.
- **Consultas bloqueadas**: revisá el Cypher generado; quizá el modelo agregó verbos prohibidos. Reformulá la pregunta con más contexto.

## Próximos pasos sugeridos
- Extender el dataset con más cursos/competencias.
- Añadir pruebas unitarias para `extract_cypher` e `is_safe_cypher`.
- Integrar una interfaz web o CLI más robusta para registrar las consultas realizadas.

