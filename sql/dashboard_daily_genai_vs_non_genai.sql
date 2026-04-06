-- Daily cost/credit split: GenAI-classified usage vs non-GenAI usage.
-- Edit billing_table and lookback_days before running.

DECLARE billing_table STRING DEFAULT 'my-billing-project.billing_export.gcp_billing_export_resource_v1_ABC_*';
DECLARE lookback_days INT64 DEFAULT 60;

EXECUTE IMMEDIATE FORMAT(
"""
WITH base AS (
  SELECT
    DATE(usage_start_time) AS usage_date,
    service.description AS service_name,
    sku.description AS sku_name,
    cost,
    IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0.0) AS credit_amount
  FROM `%s`
  WHERE DATE(usage_start_time) >= DATE_SUB(CURRENT_DATE("UTC"), INTERVAL %d DAY)
),
classified AS (
  SELECT
    usage_date,
    service_name,
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
  usage_date,
  ROUND(SUM(IF(is_genai, cost, 0.0)), 2) AS genai_gross_usd,
  ROUND(SUM(IF(is_genai, credit_amount, 0.0)), 2) AS genai_credits_usd,
  ROUND(SUM(IF(is_genai, net_cost, 0.0)), 2) AS genai_net_usd,
  ROUND(SUM(IF(NOT is_genai, cost, 0.0)), 2) AS non_genai_gross_usd,
  ROUND(SUM(IF(NOT is_genai, credit_amount, 0.0)), 2) AS non_genai_credits_usd,
  ROUND(SUM(IF(NOT is_genai, net_cost, 0.0)), 2) AS non_genai_net_usd,
  ROUND(SUM(net_cost), 2) AS total_net_usd
FROM classified
GROUP BY usage_date
ORDER BY usage_date DESC
""",
billing_table,
lookback_days
);
