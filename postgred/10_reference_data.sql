-- Reference data for business-unit to screening-type mappings
-- Rule:
-- 1) SAN / PEP / AME / 314a are mapped to all active business units.
-- 2) All other active screening types are mapped to specific business units.

WITH global_type_keys AS (
    SELECT unnest(ARRAY['san', 'san-us', 'pep', 'pep-g', 'ame', '314a', 'mpin']) AS type_key
),
active_business_units AS (
    SELECT business_unit_code
    FROM public.business_units
    WHERE is_active = TRUE
),
active_screening_types AS (
    SELECT
        "Screening_Type" AS screening_type,
        "Search_Definition_ID" AS search_definition_id
    FROM public."actimize_screening_type_mappings"
    WHERE is_active = TRUE
      AND TRIM(COALESCE("Screening_Type", '')) <> ''
      AND TRIM(COALESCE("Search_Definition_ID", '')) <> ''
),
global_screening_types AS (
    SELECT ast.screening_type
    FROM active_screening_types ast
    JOIN global_type_keys gtk
      ON lower(regexp_replace(ast.screening_type, '\s+', ' ', 'g')) = gtk.type_key
)
INSERT INTO public.business_unit_screening_types (
    business_unit_code,
    "Screening_Type",
    is_active,
    created_at,
    updated_at
)
SELECT
    abu.business_unit_code,
    gst.screening_type,
    TRUE,
    now(),
    now()
FROM active_business_units abu
CROSS JOIN global_screening_types gst
ON CONFLICT (business_unit_code, "Screening_Type")
DO UPDATE SET
    is_active = TRUE,
    updated_at = EXCLUDED.updated_at;

WITH specific_map AS (
    SELECT *
    FROM (
        VALUES
            ('SD_US_Customers_Sanctions_PGIM_APAC', 'US_PRU_PGIM_RE_APAC'),
            ('SD_US_Customers_Sanctions_PGIM_CIO', 'US_PRU_PGIM_CIO'),
            ('SD_US_Customers_Sanctions_PGIM_FI', 'US_PRU_PGIM_FI'),
            ('SD_US_Customers_Sanctions_PGIM_JK_ASC', 'US_PRU_PGIM_JK_ASC'),
            ('SD_US_Customers_Sanctions_PGIM_LATAM', 'US_PRU_PGIM_LATAM'),
            ('SD_US_Customers_Sanctions_PGIM_MA', 'US_PRU_PGIM_MA'),
            ('SD_US_Customers_Sanctions_PGIM_NE_FI', 'US_PRU_PGIM_NE_FI'),
            ('SD_Customers_Sanctions_PGIM_HK', 'US_PRU_PGIM'),
            ('SD_Customers_Sanctions_PGIM_JAPAN', 'US_PRU_PGIM_JAPAN'),
            ('SD_US_Customers_Sanctions_PGIM_PP_FI', 'US_PRU_PGIM_PP_FI'),
            ('SD_US_Customers_Sanctions_PGIM_QUANT', 'US_PRU_PGIM_QUANT'),
            ('SD_US_Customers_Sanctions_PGIM_RE', 'US_PRU_PGIM_RE')
    ) AS t(search_definition_id, business_unit_code)
),
active_screening_types AS (
    SELECT
        "Screening_Type" AS screening_type,
        "Search_Definition_ID" AS search_definition_id
    FROM public."actimize_screening_type_mappings"
    WHERE is_active = TRUE
),
active_business_units AS (
    SELECT business_unit_code
    FROM public.business_units
    WHERE is_active = TRUE
)
INSERT INTO public.business_unit_screening_types (
    business_unit_code,
    "Screening_Type",
    is_active,
    created_at,
    updated_at
)
SELECT
    sm.business_unit_code,
    ast.screening_type,
    TRUE,
    now(),
    now()
FROM specific_map sm
JOIN active_business_units abu
  ON abu.business_unit_code = sm.business_unit_code
JOIN active_screening_types ast
  ON ast.search_definition_id = sm.search_definition_id
ON CONFLICT (business_unit_code, "Screening_Type")
DO UPDATE SET
    is_active = TRUE,
    updated_at = EXCLUDED.updated_at;
