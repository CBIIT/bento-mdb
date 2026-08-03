MATCH (t:term)
WITH t.origin_name as origin_name, t.origin_id as origin_id, t.origin_version as origin_version, t.value as value, count(*) AS n
WHERE n > 1
RETURN count(*) AS duplicate_groups