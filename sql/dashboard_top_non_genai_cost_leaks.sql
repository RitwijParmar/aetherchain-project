-- Identify top non-GenAI net spend SKUs ("cost leaks") to keep normal credits usage minimal.
-- Edit billing_table and lookback_days before running.

DECLARE billing_table STRING DEFAULT 'my-billing-project.billing_export.gcp_billing_export_resource_v1_ABC_*';
DECLARE lookback_days INT64 DEFAULT 30;

EXECUTE IMMEDIATE FORMAT(
"""
WITH base AS (
  SELECT
    service.description AS service_name,
    sku.id AS sku_id,
    sku.description AS sku_name,
    cost,
    IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0.0) AS credit_amount
  FROM `%s`
  WHERE DATE(usage_start_time) >= DATE_SUB(CURRENT_DATE("UTC"), INTERVAL %d DAY)
),
classified AS (
  SELECT
    service_name,
    sku_id,
    sku_name,
    cost,
    credit_amount,
    (cost + credit_amount) AS net_cost,
    (
      REGEXP_CONTAINS(LOWER(service_name), r'(vertex ai|generative language|discovery engine|agent builder)')
      OR REGEXP_CONTAINS(LOWER(sku_name), r'(gemini|generative|vertex ai search|discovery engine|agent builder|grounded generation|search api request)')
    ) AS is_genai
  FROM base
)
SELECT
  service_name,
  sku_id,
  sku_name,
  ROUND(SUM(cost), 2) AS gross_usd,
  ROUND(SUM(credit_amount), 2) AS credits_usd,
  ROUND(SUM(net_cost), 2) AS net_usd
FROM classified
WHERE NOT is_genai
GROUP BY service_name, sku_id, sku_name
HAVING net_usd > 0
ORDER BY net_usd DESC
LIMIT 50
""",
billing_table,
lookback_days
);
