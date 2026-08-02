MATCH (t:term)
WITH
  t.origin_name AS origin_name,
  t.origin_id AS origin_id,
  t.origin_version AS origin_version,
  t.value AS value,
  t
ORDER BY
  CASE
    WHEN t.origin_definition IS NOT NULL
      AND trim(toString(t.origin_definition)) <> ''
      AND toLower(trim(toString(t.origin_definition))) <> 'null'
    THEN 0
    ELSE 1
  END,
  t.nanoid
WITH
  origin_name,
  origin_id,
  origin_version,
  value,
  collect(t) AS terms
WHERE size(terms) > 1
UNWIND terms[1..] AS redundant
OPTIONAL MATCH (redundant)-[outRel]->(outNode)
WITH origin_name, redundant, outRel, outNode
WHERE outRel IS NOT NULL
RETURN
  origin_name,
  'outgoing' AS direction,
  type(outRel) AS relationship_type,
  labels(outNode) AS other_node_labels,
  count(*) AS relationship_count

UNION ALL

MATCH (t:term)
WITH
  t.origin_name AS origin_name,
  t.origin_id AS origin_id,
  t.origin_version AS origin_version,
  t.value AS value,
  t
ORDER BY
  CASE
    WHEN t.origin_definition IS NOT NULL
      AND trim(toString(t.origin_definition)) <> ''
      AND toLower(trim(toString(t.origin_definition))) <> 'null'
    THEN 0
    ELSE 1
  END,
  t.nanoid
WITH
  origin_name,
  origin_id,
  origin_version,
  value,
  collect(t) AS terms
WHERE size(terms) > 1
UNWIND terms[1..] AS redundant
OPTIONAL MATCH (inNode)-[inRel]->(redundant)
WITH origin_name, redundant, inRel, inNode
WHERE inRel IS NOT NULL
RETURN
  origin_name,
  'incoming' AS direction,
  type(inRel) AS relationship_type,
  labels(inNode) AS other_node_labels,
  count(*) AS relationship_count
ORDER BY origin_name, direction, relationship_type, other_node_labels;