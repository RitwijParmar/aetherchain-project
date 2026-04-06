-- Monthly guardrail query (UTC month-to-date).
-- Edit billing_table and budget parameters before running.

DECLARE billing_table STRING DEFAULT 'my-billing-project.billing_export.gcp_billing_export_resource_v1_ABC_*';
DECLARE monthly_net_budget_usd FLOAT64 DEFAULT 220.0;
DECLARE stop_buffer_usd FLOAT64 DEFAULT 15.0;

EXECUTE IMMEDIATE FORMAT(
"""
WITH mtd AS (
  SELECT
    COALESCE(SUM(cost), 0.0) AS gross_usd,
    COALESCE(SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0.0)), 0.0) AS credits_usd,
    COALESCE(SUM(cost + IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0.0)), 0.0) AS net_usd
  FROM `%s`
  WHERE DATE(usage_start_time) BETWEEN DATE_TRUNC(CURRENT_DATE("UTC"), MONTH) AND CURRENT_DATE("UTC")
)
SELECT
  ROUND(gross_usd, 2) AS gross_usd,
  ROUND(credits_usd, 2) AS credits_usd,
  ROUND(net_usd, 2) AS net_usd,
  ROUND(%f, 2) AS monthly_net_budget_usd,
  ROUND(%f, 2) AS stop_buffer_usd,
  ROUND((%f - net_usd), 2) AS remaining_budget_usd,
  CASE
    WHEN (%f - net_usd) <= %f THEN 'STOP_INGEST'
    ELSE 'OK_TO_INGEST'
  END AS guardrail_status
FROM mtd
""",
billing_table,
monthly_net_budget_usd,
stop_buffer_usd,
monthly_net_budget_usd,
monthly_net_budget_usd,
stop_buffer_usd
);
