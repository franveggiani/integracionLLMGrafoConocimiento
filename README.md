# NL → Cypher para AFPI (Neo4j + Ollama)

Este proyecto convierte preguntas en español sobre finanzas personales (AFPI) en consultas Cypher, las ejecuta en Neo4j y redacta una respuesta breve basada en los resultados. Usa un LLM local vía [Ollama](https://ollama.com/).

**Qué soporta**
- Metamodelo AFPI con `Frame`, `Slot`, `FrameInst` y relaciones como `HAS_VALUE`, `REALIZA`, `PERTENECE_A`, `TIENE`, `RECIBE`, `BASADO_EN`, `DIRIGIDA_A`.
- Carga de esquema desde `SCHEME.txt` y datos desde `DATOS.txt`.
- Few-shots tomados automáticamente de la sección “CONSULTAS DE EJEMPLO…” en `DATOS.txt`.
- Seguridad: solo lectura (bloquea `CREATE`, `MERGE`, `DELETE`, `CALL`, `APOC`, etc.).

## Requisitos
- Python 3.10+ (se recomienda entorno virtual).
- [Ollama](https://ollama.com/download) corriendo localmente con un modelo (por defecto `llama3.2`, configurable en `.env`).
- Neo4j Desktop o instancia Neo4j 5.x accesible por Bolt. (El script `run_neo4j.sh` es opcional.)

## Instalación rápida
```bash
git clone <repo>
cd pi5-ia
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Configuración
Configurá tu conexión y el modelo en `.env`:
```env
NEO4J_URI=bolt://localhost:7687   # o neo4j://..., bolt+s://..., etc.
NEO4J_USER=neo4j                  # dejar vacío si auth deshabilitada
NEO4J_PASS=neo4j123               # dejar vacío si auth deshabilitada
NEO4J_AUTH_DISABLED=              # poner true si la auth está OFF
OLLAMA_MODEL=llama3.2             # por ejemplo: llama3:3b-instruct, qwen:3b-instruct, gemma:2b
```
- Ajustá `NEO4J_URI` según lo que muestre Neo4j Desktop para tu DB.
- Si tu DB no requiere auth, dejá `NEO4J_USER`/`NEO4J_PASS` vacíos y poné `NEO4J_AUTH_DISABLED=true`.

## Cargar esquema y datos en Neo4j
1. Iniciá tu base en Neo4j Desktop y abrí el Browser.
2. Ejecutá el contenido de `SCHEME.txt` (crea Frames/Slots/constraints y triggers APOC).
3. Ejecutá `DATOS.txt` (carga usuarios, categorías, movimientos, objetivos, recomendaciones).

## Prueba rápida sin LLM
Para validar que el dataset está cargado y la conexión es correcta:
```bash
.venv/bin/python smoke_test.py
```
Ejecuta 3 consultas de ejemplo directamente y muestra tablas.

## Ejecutar el asistente (modo agente + NL → Cypher)
1. Asegurate que Ollama esté activo (`ollama serve`) y que el modelo exista (`ollama run <modelo>` al menos una vez).
2. Ejecutá:
```bash
.venv/bin/python nl2cypher.py
```
   - Este modo crea un agente LangChain con herramientas:
     - `consultar_grafo_afpi`: preguntas NL→Cypher como antes.
     - `clasificar_movimiento_nuevo`: invoca el clasificador de `pi4_nlp_ia.py` para etiquetar automáticamente la categoría de un movimiento cuando el usuario quiere registrarlo.
     - `registrar_movimiento`: inserta un movimiento usando un JSON con los campos necesarios.
     - `registrar_objetivo_ahorro`: crea objetivos de ahorro con un JSON similar.
   - El agente detecta automáticamente si tu prompt implica “registrar/crear/agregar” y solo entonces habilita las herramientas de escritura; para preguntas como “quiero saber mis objetivos” usa exclusivamente la herramienta de consulta.
3. Si preferís el flujo tradicional sin agente, usá `--legacy`:
```bash
.venv/bin/python nl2cypher.py --legacy
```

## Estructura del código
- `nl2cypher.py`: bucle interactivo NL→Cypher; seguridad de solo lectura; ejecución y respuesta breve.
- `afpi_context.py`: arma el prompt de esquema (lee `SCHEME.txt` + introspección de BD) y parsea few‑shots desde `DATOS.txt`.
- `smoke_test.py`: sanity-check sin LLM para las primeras consultas de ejemplo.
- `SCHEME.txt`, `DATOS.txt`: definición de esquema AFPI y dataset de prueba.
- `run_neo4j.sh`: script opcional para levantar Neo4j en Docker con APOC/GDS.

## Consejos y ejemplos de prompts
- Especificar usuario por id (`user#maria`, `user#carlos`) mejora la precisión.
- Aclará rangos de fechas: “este mes”, “últimos 30 días”, o fechas exactas.
- Pedí columnas: “con fecha, tipo, monto, categoría” si querés ajustar el RETURN.
- Ejemplos: “Top 3 categorías por gasto de user#maria este mes”, “Recomendaciones de tipo Alerta para user#carlos”.

## Solución de problemas
- Conexión: revisá `.env` (`NEO4J_URI`, usuario/clave o `NEO4J_AUTH_DISABLED=true`).
- Esquema/datos: corré `SCHEME.txt` y `DATOS.txt` en la misma DB que usás por Bolt.
- LLM/modelo: si el modelo no existe, cambiá `OLLAMA_MODEL` o ejecutá `ollama pull <modelo>`.
- Consultas bloqueadas: si el modelo genera verbos prohibidos, reformulá la pregunta más específica (solo lectura).
### Ejemplos rápidos de inserts vía agente
Cuando el usuario pide registrar algo, el agente arma el JSON y llama a la herramienta apropiada. También podés hacerlo manualmente describiendo el JSON:

- Movimiento:
  ```text
  Usa registrar_movimiento con:
  {"user_id":"user#maria","tipo":"Gasto","fecha":"2025-11-05","descripcion":"Cena con amigos","monto":18500,"categoria_id":"cat#entretenimiento"}
  ```
- Objetivo:
  ```text
  Usa registrar_objetivo_ahorro con:
  {"user_id":"user#maria","nombre":"Computadora nueva","monto_meta":450000,"fecha_limite":"2026-03-31","progreso":12.5}
  ```
