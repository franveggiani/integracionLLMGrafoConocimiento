# docker run -d \
#   --name neo4j \
#   -p 7474:7474 -p 7687:7687 \
#   -e NEO4J_AUTH=neo4j/neo4j123 \
#   -e NEO4JLABS_PLUGINS='["apoc","graph-data-science"]' \
#   -e NEO4J_dbms_security_procedures_unrestricted=apoc.*,gds.* \
#   -v ~/neo4j/data:/data \
#   -v ~/neo4j/logs:/logs \
#   neo4j:5.22


# docker stop neo4j
# docker rm neo4j

# rm -rf ~/neo4j/data/*

# docker run -d \
#   --name neo4j \
#   -p 7474:7474 -p 7687:7687 \
#   -e NEO4J_AUTH=neo4j/neo4j123 \
#   -e NEO4JLABS_PLUGINS='["apoc","graph-data-science"]' \
#   -e NEO4J_dbms_security_procedures_unrestricted=apoc.*,gds.* \
#   -e NEO4J_initial_dbms_default__database=neo4j \
#   -e NEO4J_dbms_mode=SINGLE \
#   -v ~/neo4j/data:/data \
#   -v ~/neo4j/logs:/logs \
#   neo4j:5.22


# MATCH (n)
# DETACH DELETE n;
# // Eliminar todos los índices
# CALL apoc.schema.assert({}, {}, true);

# // Eliminar todos los constraints
# CALL apoc.schema.assert({}, {}, true);

# docker stop neo4j || true
# docker rm neo4j || true
# rm -rf ~/neo4j/data/* ~/neo4j/logs/*

# docker run -d \
#   --name neo4j \
#   -p 7474:7474 -p 7687:7687 \
#   -e NEO4J_AUTH=neo4j/neo4j123 \
#   -e NEO4J_PLUGINS='["apoc","graph-data-science"]' \
#   -e NEO4J_dbms_security_procedures_unrestricted=apoc.*,gds.* \
#   -e NEO4J_dbms_security_procedures_allowlist=apoc.*,gds.* \
#   -e NEO4J_apoc_trigger_enabled=true \
#   -v ~/neo4j/data:/data \
#   -v ~/neo4j/logs:/logs \
#   neo4j:5.22
