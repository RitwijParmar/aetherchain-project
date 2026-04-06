-- Credit attribution dashboard:
-- Shows which credit programs are actually covering GenAI-classified vs non-GenAI usage.
-- Edit billing_table and lookback_days before running.

DECLARE billing_table STRING DEFAULT 'my-billing-project.billing_export.gcp_billing_export_resource_v1_ABC_*';
DECLARE lookback_days INT64 DEFAULT 60;

EXECUTE IMMEDIATE FORMAT(
"""
WITH credit_lines AS (
  SELECT
    DATE(t.usage_start_time) AS usage_date,
    t.service.description AS service_name,
    t.sku.description AS sku_name,
    IFNULL(c.amount, 0.0) AS credit_amount,
    COALESCE(c.full_name, c.name, c.id, 'UNKNOWN_CREDIT') AS credit_name
  FROM `%s` AS t
  LEFT JOIN UNNEST(t.credits) AS c
  WHERE DATE(t.usage_start_time) >= DATE_SUB(CURRENT_DATE("UTC"), INTERVAL %d DAY)
),
classified AS (
  SELECT
    usage_date,
    credit_name,
    credit_amount,
    (
      REGEXP_CONTAINS(LOWER(service_name), r'(vertex ai|generative language|discovery engine|agent builder)')
      OR REGEXP_CONTAINS(LOWER(sku_name), r'(gemini|generative|vertex ai search|discovery engine|agent builder|grounded generation|search api request)')
    ) AS is_genai
  FROM credit_lines
)
SELECT
  usage_date,
  IF(is_genai, 'genai', 'non_genai') AS spend_class,
  credit_name,
  ROUND(SUM(credit_amount), 2) AS credits_usd,
  COUNT(1) AS credit_rows
FROM classified
WHERE credit_name IS NOT NULL
GROUP BY usage_date, spend_class, credit_name
ORDER BY usage_date DESC, ABS(credits_usd) DESC
""",
billing_table,
lookback_days
);
