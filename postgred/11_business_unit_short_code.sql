-- Migration: add and backfill business-unit short code (4 chars)
-- Safe to run multiple times.

ALTER TABLE public.business_units
ADD COLUMN IF NOT EXISTS bu_short_code character varying(4);

-- Normalize existing values (uppercase alphanumeric only).
UPDATE public.business_units
SET bu_short_code = upper(regexp_replace(COALESCE(bu_short_code, ''), '[^A-Za-z0-9]', '', 'g'))
WHERE bu_short_code IS NOT NULL;

-- Keep only valid 4-char values.
UPDATE public.business_units
SET bu_short_code = NULL
WHERE bu_short_code IS NULL
   OR bu_short_code !~ '^[A-Z0-9]{4}$';

-- If duplicates exist, keep the first by business_unit_code and reassign the rest.
WITH duplicate_rows AS (
    SELECT business_unit_code
    FROM (
        SELECT
            business_unit_code,
            bu_short_code,
            row_number() OVER (PARTITION BY bu_short_code ORDER BY business_unit_code) AS rn
        FROM public.business_units
        WHERE bu_short_code IS NOT NULL
    ) dedup
    WHERE dedup.rn > 1
)
UPDATE public.business_units bu
SET bu_short_code = NULL
FROM duplicate_rows d
WHERE bu.business_unit_code = d.business_unit_code;

-- Assign deterministic unique fallback codes for any missing short codes.
WITH missing AS (
    SELECT
        business_unit_code,
        row_number() OVER (ORDER BY business_unit_code) AS rn
    FROM public.business_units
    WHERE bu_short_code IS NULL
),
available AS (
    SELECT
        candidate_code,
        row_number() OVER (ORDER BY candidate_code) AS rn
    FROM (
        SELECT upper(lpad(to_hex(gs.n), 4, '0')) AS candidate_code
        FROM generate_series(0, 65535) AS gs(n)
    ) pool
    WHERE candidate_code NOT IN (
        SELECT bu_short_code
        FROM public.business_units
        WHERE bu_short_code IS NOT NULL
    )
),
assigned AS (
    SELECT
        m.business_unit_code,
        a.candidate_code AS bu_short_code
    FROM missing m
    JOIN available a
      ON a.rn = m.rn
)
UPDATE public.business_units bu
SET bu_short_code = a.bu_short_code
FROM assigned a
WHERE bu.business_unit_code = a.business_unit_code;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.business_units'::regclass
          AND conname = 'business_units_bu_short_code_key'
    ) THEN
        ALTER TABLE ONLY public.business_units
        ADD CONSTRAINT business_units_bu_short_code_key UNIQUE (bu_short_code);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.business_units'::regclass
          AND conname = 'chk_business_units_bu_short_code_format'
    ) THEN
        ALTER TABLE ONLY public.business_units
        ADD CONSTRAINT chk_business_units_bu_short_code_format
        CHECK (bu_short_code ~ '^[A-Z0-9]{4}$');
    END IF;
END $$;
