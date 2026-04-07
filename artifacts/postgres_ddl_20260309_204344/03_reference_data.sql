-- Reference data seed script for initial PostgreSQL setup
-- Generated from the current application default reference data
-- Target schema: public
--
-- What this seeds:
-- 1. business_units        -> baseline business-unit reference data used by screening flows
--
-- What this does not seed automatically:
-- 1. user_business_units   -> environment-specific user-to-business-unit mappings
--                             A commented template is included below for manual setup.

BEGIN;

WITH seed_now AS (
    SELECT to_char(timezone('utc', now()), 'YYYY-MM-DD"T"HH24:MI:SS.MS"+00:00"') AS ts
),
seed_business_units AS (
    SELECT *
    FROM (
        VALUES
            ('US_PRU_OSGLI', 'OSGLI'),
            ('US_PRU_VM', 'Vendor Management'),
            ('US_PRU_HR', 'Human Resources'),
            ('US_PRU_OPES', 'Operation/Enabling Solutions'),
            ('US_PRU_PGIM', 'PGIM'),
            ('US_PRU_PGIM_RE_TENANT', 'PGIM Real Estate tenant'),
            ('US_PRU_PGIM_RE', 'PGIM Real Estate'),
            ('US_PRU_PGIM_FI', 'PGIM Fixed Income'),
            ('US_PRU_PGIM_PP_FI', 'PGIMPublic and Private Fixed Income'),
            ('US_PRU_PGIM_MA', 'PGIM Multi Asset Solutions'),
            ('US_PRU_PGIM_CIO', 'PGIM CIO'),
            ('US_PRU_PGIM_JAPAN', 'PGIM Japan'),
            ('US_PRU_PGIM_JK_ASC', 'PGIM Jenkins Associates'),
            ('US_PRU_PGIM_NE_FI', 'PGIM Netherlands'),
            ('US_PRU_PGIM_QUANT', 'PGIM Quant Compliance'),
            ('US_PRU_PGIM_RE_APAC', 'PGIM Real Estate APAC'),
            ('US_PRU_PGIM_LATAM', 'PGIM LATAM')
    ) AS t(business_unit_code, business_unit_name)
)
INSERT INTO public.business_units (
    business_unit_code,
    business_unit_name,
    is_active,
    created_at,
    updated_at
)
SELECT
    s.business_unit_code,
    s.business_unit_name,
    TRUE,
    n.ts,
    n.ts
FROM seed_business_units s
CROSS JOIN seed_now n
ON CONFLICT (business_unit_code) DO UPDATE
SET
    business_unit_name = EXCLUDED.business_unit_name,
    is_active = TRUE,
    updated_at = EXCLUDED.updated_at;

COMMIT;

-- -------------------------------------------------------------------------
-- Optional: user-to-business-unit mappings
-- -------------------------------------------------------------------------
-- These mappings depend on the real identity-provider user ids in each
-- environment, so they are intentionally left as a template instead of being
-- auto-seeded.
--
-- Example:
--
-- WITH seed_now AS (
--     SELECT to_char(timezone('utc', now()), 'YYYY-MM-DD"T"HH24:MI:SS.MS"+00:00"') AS ts
-- )
-- INSERT INTO public.user_business_units (
--     user_id,
--     user_name,
--     business_unit_code,
--     is_active,
--     created_at,
--     updated_at
-- )
-- SELECT
--     'replace-with-real-user-id',
--     'Replace With Real User Name',
--     'US_PRU_HR',
--     TRUE,
--     ts,
--     ts
-- FROM seed_now
-- ON CONFLICT (user_id, business_unit_code) DO UPDATE
-- SET
--     user_name = EXCLUDED.user_name,
--     is_active = TRUE,
--     updated_at = EXCLUDED.updated_at;
