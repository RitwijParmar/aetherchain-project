-- Focus report: Vertex AI Search / Agent Builder style SKU usage.
-- Replace <BILLING_EXPORT_TABLE> with your detailed export table.

WITH focused AS (
  SELECT
    DATE(usage_start_time) AS usage_day,
    sku.id AS sku_id,
    sku.description AS sku_description,
    SUM(cost) AS gross_cost,
    SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) AS credits_applied,
    SUM(cost + IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) AS net_cost
  FROM `<BILLING_EXPORT_TABLE>`
  WHERE usage_start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
    AND (
      sku.id IN (
        '93D6-7280-CF05', -- Search API Request Count - Enterprise
        '151B-D7A2-B5B5', -- Search API Request Count - LLM Add-on
        'BADA-EE26-7BDA', -- Search API Request Count - Standard
        'C232-DC00-D993', -- Advanced Generative Answers
        'C42C-2852-B25D', -- Grounded Generation
        'BFE9-7E43-9B31', -- Check Grounding
        'EE89-3EE8-2541', -- Ranking
        'FBDD-D195-DEB5'  -- Web Grounded Generation
      )
      OR LOWER(sku.description) LIKE '%vertex ai search%'
      OR LOWER(sku.description) LIKE '%agent builder%'
      OR LOWER(sku.description) LIKE '%generative answers%'
    )
  GROUP BY 1, 2, 3
)
SELECT *
FROM focused
ORDER BY usage_day DESC, gross_cost DESC;
