-- Functions and Procedures
-- Generated at: 2026-05-08T22:36:36.285888+00:00
-- Schema: public

CREATE OR REPLACE FUNCTION public.set_job_items_job_seq_id()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
  IF NEW.job_seq_id IS NULL THEN
    SELECT job_seq_id
    INTO NEW.job_seq_id
    FROM jobs
    WHERE job_id = NEW.job_id;
  END IF;
  RETURN NEW;
END;
$function$

CREATE OR REPLACE FUNCTION public.set_related_job_seq_id_from_job_id()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
  IF NEW.job_seq_id IS NULL AND NEW.job_id IS NOT NULL THEN
    SELECT j.job_seq_id
    INTO NEW.job_seq_id
    FROM jobs j
    WHERE j.job_id = NEW.job_id;
  END IF;
  RETURN NEW;
END;
$function$

CREATE OR REPLACE FUNCTION public.set_schedule_record_last_job_seq_id()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
  IF NEW.last_job_seq_id IS NULL AND NEW.last_job_id IS NOT NULL THEN
    SELECT j.job_seq_id
    INTO NEW.last_job_seq_id
    FROM jobs j
    WHERE j.job_id = NEW.last_job_id;
  END IF;
  RETURN NEW;
END;
$function$
