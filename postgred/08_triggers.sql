-- Triggers
-- Generated at: 2026-05-08T22:36:36.285888+00:00
-- Schema: public

DROP TRIGGER IF EXISTS trg_batch_file_uploads_set_job_seq_id ON public.batch_file_uploads;
CREATE TRIGGER trg_batch_file_uploads_set_job_seq_id BEFORE INSERT OR UPDATE OF job_id, job_seq_id ON batch_file_uploads FOR EACH ROW EXECUTE FUNCTION set_related_job_seq_id_from_job_id();

DROP TRIGGER IF EXISTS trg_job_items_set_job_seq_id ON public.job_items;
CREATE TRIGGER trg_job_items_set_job_seq_id BEFORE INSERT OR UPDATE OF job_id ON job_items FOR EACH ROW EXECUTE FUNCTION set_job_items_job_seq_id();

DROP TRIGGER IF EXISTS trg_job_metadata_set_job_seq_id ON public.job_metadata;
CREATE TRIGGER trg_job_metadata_set_job_seq_id BEFORE INSERT OR UPDATE OF job_id, job_seq_id ON job_metadata FOR EACH ROW EXECUTE FUNCTION set_related_job_seq_id_from_job_id();

DROP TRIGGER IF EXISTS trg_job_schedule_notifications_set_job_seq_id ON public.job_schedule_notifications;
CREATE TRIGGER trg_job_schedule_notifications_set_job_seq_id BEFORE INSERT OR UPDATE OF job_id, job_seq_id ON job_schedule_notifications FOR EACH ROW EXECUTE FUNCTION set_related_job_seq_id_from_job_id();

DROP TRIGGER IF EXISTS trg_schedule_notifications_set_job_seq_id ON public.schedule_notifications;
CREATE TRIGGER trg_schedule_notifications_set_job_seq_id BEFORE INSERT OR UPDATE OF job_id, job_seq_id ON schedule_notifications FOR EACH ROW EXECUTE FUNCTION set_related_job_seq_id_from_job_id();

DROP TRIGGER IF EXISTS trg_schedule_record_state_set_last_job_seq_id ON public.schedule_record_state;
CREATE TRIGGER trg_schedule_record_state_set_last_job_seq_id BEFORE INSERT OR UPDATE OF last_job_id, last_job_seq_id ON schedule_record_state FOR EACH ROW EXECUTE FUNCTION set_schedule_record_last_job_seq_id();
