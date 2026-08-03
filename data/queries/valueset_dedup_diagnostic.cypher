MATCH (vs:value_set)-[:has_term]->(t:term)
WITH
  vs.nanoid AS value_set_id,
  t.origin_name AS origin_name,
  t.origin_id AS origin_id,
  t.origin_version AS origin_version,
  t.value AS value,
  count(*) AS n
WHERE n > 1
RETURN count(*) AS redundant_value_set_term_groups