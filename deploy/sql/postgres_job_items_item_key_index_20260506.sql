BEGIN;

CREATE INDEX IF NOT EXISTS idx_job_items_item_key
ON job_items(item_key);

COMMIT;
