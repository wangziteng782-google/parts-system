-- SKU、规格值、供应商及全部价格的完整展示查询
-- 一行代表“一个SKU规格 + 一个供应商报价”；没有供应商的SKU也会显示。
SELECT
    spu.id AS spu_id,
    spu.spu_code,
    spu.goods_name AS product_name,
    spu.brand AS product_brand,
    spu.version AS model,
    sku.id AS sku_id,
    sku.sku_code,
    GROUP_CONCAT(
        DISTINCT CONCAT(spec.spec_name, '：', spec_value.value)
        ORDER BY spec.id
        SEPARATOR '；'
    ) AS specification,
    supplier.id AS supplier_id,
    supplier.supplier_name,
    CASE
        WHEN quotation.price_enabled = 1 THEN quotation.price
        ELSE NULL
    END AS purchase_no_tax_price,
    CASE
        WHEN quotation.special_enabled = 1 THEN quotation.special_price
        ELSE NULL
    END AS purchase_special_invoice_price,
    CASE
        WHEN quotation.normal_enabled = 1 THEN quotation.normal_price
        ELSE NULL
    END AS purchase_general_invoice_price,
    sales_price.price AS retail_price,
    quotation.valid_until AS quotation_valid_until,
    quotation.valid_until_txt AS quotation_valid_until_text,
    quotation.shipping_address,
    quotation.delivery_time_desc,
    quotation.warranty,
    CASE
        WHEN quotation.id IS NULL THEN '无供应商'
        WHEN quotation.status = 1 THEN '报价有效'
        ELSE '待完善报价'
    END AS quotation_status
FROM yh_goods_sku AS sku
INNER JOIN yh_goods_spu AS spu
    ON spu.id = sku.spu_id
LEFT JOIN yh_sku_spec_value AS sku_spec
    ON sku_spec.sku_id = sku.id
   AND sku_spec.delete_time IS NULL
LEFT JOIN yh_spec_value AS spec_value
    ON spec_value.id = sku_spec.value_id
   AND spec_value.delete_time IS NULL
LEFT JOIN yh_spec AS spec
    ON spec.id = spec_value.spec_id
   AND spec.delete_time IS NULL
LEFT JOIN yh_goods_quotation AS quotation
    ON quotation.sku_id = sku.id
   AND quotation.delete_time IS NULL
LEFT JOIN yh_supplier AS supplier
    ON supplier.id = quotation.supplier_id
   AND supplier.delete_time IS NULL
LEFT JOIN yh_price_type AS price_type
    ON price_type.code = 'retail_price'
   AND price_type.delete_time IS NULL
LEFT JOIN yh_goods_sku_sales_price AS sales_price
    ON sales_price.sku_id = sku.id
   AND sales_price.price_type_id = price_type.id
   AND sales_price.delete_time IS NULL
WHERE sku.is_delete = 0
GROUP BY
    spu.id,
    spu.spu_code,
    spu.goods_name,
    spu.brand,
    spu.version,
    sku.id,
    sku.sku_code,
    supplier.id,
    supplier.supplier_name,
    quotation.id,
    quotation.price_enabled,
    quotation.price,
    quotation.special_enabled,
    quotation.special_price,
    quotation.normal_enabled,
    quotation.normal_price,
    sales_price.price,
    quotation.valid_until,
    quotation.valid_until_txt,
    quotation.shipping_address,
    quotation.delivery_time_desc,
    quotation.warranty,
    quotation.status
ORDER BY spu.id, sku.id, quotation.id;
