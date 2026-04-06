-- Credit Mix Guardrail
-- Goal: keep non-GenAI-App-Builder net spend minimal while using GenAI trial credits.
-- Replace <BILLING_EXPORT_TABLE> with your detailed billing export table.

WITH base AS (
  SELECT
    DATE(usage_start_time) AS usage_date,
    service.description AS service,
    sku.description AS sku,
    cost,
    IFNULL((
      SELECT SUM(c.amount)
      FROM UNNEST(credits) c
    ), 0.0) AS credit_amount
  FROM `<BILLING_EXPORT_TABLE>`
  WHERE usage_start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
),
enriched AS (
  SELECT
    usage_date,
    service,
    sku,
    cost,
    credit_amount,
    (cost + credit_amount) AS net_cost,
    (
      REGEXP_CONTAINS(LOWER(service), r'genai app builder|discovery engine|agent builder')
      OR REGEXP_CONTAINS(LOWER(sku), r'genai|discovery engine|agent builder|search requests')
    ) AS is_genai_app_builder
  FROM base
)
SELECT
  usage_date,
  ROUND(SUM(cost), 2) AS gross_cost_usd,
  ROUND(SUM(credit_amount), 2) AS credit_total_usd,
  ROUND(SUM(net_cost), 2) AS net_cost_usd,
  ROUND(SUM(IF(is_genai_app_builder, net_cost, 0)), 2) AS genai_app_builder_net_usd,
  ROUND(SUM(IF(NOT is_genai_app_builder, net_cost, 0)), 2) AS non_genai_net_usd,
  ROUND(
    SAFE_DIVIDE(
      SUM(IF(NOT is_genai_app_builder, net_cost, 0)),
      NULLIF(SUM(net_cost), 0)
    ),
    4
  ) AS non_genai_net_share
FROM enriched
GROUP BY usage_date
ORDER BY usage_date DESC;
