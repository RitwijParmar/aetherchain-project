-- Track whether usage is being covered by promo credits at SKU level.
-- Replace <BILLING_EXPORT_TABLE> with your detailed export table:
-- project.dataset.gcp_billing_export_resource_v1_<billing_account_id>

SELECT
  DATE(usage_start_time) AS usage_day,
  service.description AS service_name,
  sku.id AS sku_id,
  sku.description AS sku_description,
  SUM(cost) AS gross_cost,
  SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) AS credits_applied,
  SUM(cost + IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) AS net_cost,
  COUNT(1) AS line_items
FROM `<BILLING_EXPORT_TABLE>`
WHERE usage_start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY 1, 2, 3, 4
ORDER BY usage_day DESC, gross_cost DESC;
