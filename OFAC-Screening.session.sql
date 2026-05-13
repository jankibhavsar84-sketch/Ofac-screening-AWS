
set transaction read write;



SELECT * FROM job_items 

SELECT * FROM jobs 

SELECt * FROM batch_file_uploads

SELECT * FROM vw_screening_results_dataset WHERe item_key='cb3c0273-9646-4a37-b50e-2320acffd48f' 

SELECT * FROM app_users

SELECT * FROM api_access_logs

SELECT * FROM batch_file_uploads

SELECt * FROM jobs order by created_at desc

SELECt * FROM job_metadata

SELECT * FROM schedule_record_state

SELECT * FROM job_schedule_notifications

SELECT * FROM  daily_schedules

SELECT * FROM information_schema.columns  

SELECT * FROM business_units

SELECt * FROM actimize_screening_type_mappings