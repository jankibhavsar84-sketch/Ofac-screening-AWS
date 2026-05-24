--
-- PostgreSQL database dump
--

\restrict ziRPPGlIkGZger347GeI24FLOjdOiodPiHFtdc0FfXkTdCrDtXWbzPgh7rEdf7a

-- Dumped from database version 17.6
-- Dumped by pg_dump version 17.9 (Debian 17.9-1.pgdg13+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: actimize_screening_type_mappings; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.actimize_screening_type_mappings ("Search_Definition_ID", is_active, created_at, updated_at, search_definition_name, "Screening_Type", display_order) VALUES ('SD_US_Customers_314(a)', true, '2026-04-29 00:00:00+00', '2026-05-04 19:16:08.270907+00', 'Customer FinCEN 314(a)', '314a', 2);
INSERT INTO public.actimize_screening_type_mappings ("Search_Definition_ID", is_active, created_at, updated_at, search_definition_name, "Screening_Type", display_order) VALUES ('SD_US_Customers_AME', true, '2026-04-29 00:00:00+00', '2026-05-04 19:16:08.271898+00', 'Customer AME', 'AME', 3);
INSERT INTO public.actimize_screening_type_mappings ("Search_Definition_ID", is_active, created_at, updated_at, search_definition_name, "Screening_Type", display_order) VALUES ('SD_US_Customers_PEP_RCA_International', true, '2026-04-29 00:00:00+00', '2026-05-04 19:16:08.272727+00', 'Political Exposed Person - Non -US', 'PEP', 4);
INSERT INTO public.actimize_screening_type_mappings ("Search_Definition_ID", is_active, created_at, updated_at, search_definition_name, "Screening_Type", display_order) VALUES ('SD_US_Marijuana_DJ_External', true, '2026-04-29 00:00:00+00', '2026-05-04 19:16:08.273527+00', 'Marijuana Screening', 'MPIN', 5);
INSERT INTO public.actimize_screening_type_mappings ("Search_Definition_ID", is_active, created_at, updated_at, search_definition_name, "Screening_Type", display_order) VALUES ('SD_Customers_PEP_RCA_International', true, '2026-05-02 00:00:00+00', '2026-05-04 19:16:08.274474+00', 'Global Political Exposed Person', 'PEP-G', 6);
INSERT INTO public.actimize_screening_type_mappings ("Search_Definition_ID", is_active, created_at, updated_at, search_definition_name, "Screening_Type", display_order) VALUES ('SD_US_Customers_Sanctions_PGIM_APAC', true, '2026-05-02 00:00:00+00', '2026-05-04 19:16:08.275287+00', 'Customer Sanctions PGIM Real Estate (APAC) & PGIM Private Capital (Australia)', 'SAN-PAPC', 7);
INSERT INTO public.actimize_screening_type_mappings ("Search_Definition_ID", is_active, created_at, updated_at, search_definition_name, "Screening_Type", display_order) VALUES ('SD_US_Customers_Sanctions_PGIM_CIO', true, '2026-05-02 00:00:00+00', '2026-05-04 19:16:08.276174+00', 'Customer Sanctions PGIM CIO', 'SAN-PCIO', 8);
INSERT INTO public.actimize_screening_type_mappings ("Search_Definition_ID", is_active, created_at, updated_at, search_definition_name, "Screening_Type", display_order) VALUES ('SD_US_Customers_Sanctions_PGIM_FI', true, '2026-05-02 00:00:00+00', '2026-05-04 19:16:08.276965+00', 'Customer Sanctions PGIM Fixed Income', 'SAN-PFIC', 9);
INSERT INTO public.actimize_screening_type_mappings ("Search_Definition_ID", is_active, created_at, updated_at, search_definition_name, "Screening_Type", display_order) VALUES ('SD_US_Customers_Sanctions', true, '2026-04-29 00:00:00+00', '2026-05-04 19:16:08.268995+00', 'Customer Sanctions', 'SAN-US', 1);
INSERT INTO public.actimize_screening_type_mappings ("Search_Definition_ID", is_active, created_at, updated_at, search_definition_name, "Screening_Type", display_order) VALUES ('SD_US_Customers_Sanctions_PGIM_JK_ASC', true, '2026-05-02 00:00:00+00', '2026-05-04 19:16:08.27783+00', 'Customer Sanctions Jennison Associates', 'SAN-PJAC', 10);
INSERT INTO public.actimize_screening_type_mappings ("Search_Definition_ID", is_active, created_at, updated_at, search_definition_name, "Screening_Type", display_order) VALUES ('SD_US_Customers_Sanctions_PGIM_LATAM', true, '2026-05-02 00:00:00+00', '2026-05-04 19:16:08.278589+00', 'Customer Sanctions PGIM LATAM', 'SAN-PPLA', 11);
INSERT INTO public.actimize_screening_type_mappings ("Search_Definition_ID", is_active, created_at, updated_at, search_definition_name, "Screening_Type", display_order) VALUES ('SD_US_Customers_Sanctions_PGIM_MA', true, '2026-05-02 00:00:00+00', '2026-05-04 19:16:08.279318+00', 'Customer Sanctions PGIM Multi-Asset Solutions / PGIM Strategic Capital Group', 'SAN-PSCG', 12);
INSERT INTO public.actimize_screening_type_mappings ("Search_Definition_ID", is_active, created_at, updated_at, search_definition_name, "Screening_Type", display_order) VALUES ('SD_US_Customers_Sanctions_PGIM_NE_FI', true, '2026-05-02 00:00:00+00', '2026-05-04 19:16:08.28+00', 'Customer Sanctions Public & Private Fixed Income, PGIM Netherlands B.V.', 'SAN-PUPV', 13);
INSERT INTO public.actimize_screening_type_mappings ("Search_Definition_ID", is_active, created_at, updated_at, search_definition_name, "Screening_Type", display_order) VALUES ('SD_Customers_Sanctions_PGIM_HK', true, '2026-05-02 00:00:00+00', '2026-05-04 19:16:08.280686+00', 'Customer Sanctions PGIM HongKong', 'SAN-PGHK', 14);
INSERT INTO public.actimize_screening_type_mappings ("Search_Definition_ID", is_active, created_at, updated_at, search_definition_name, "Screening_Type", display_order) VALUES ('SD_Customers_Sanctions_PGIM_JAPAN', true, '2026-05-02 00:00:00+00', '2026-05-04 19:16:08.281451+00', 'Customer Sanctions PGIM Japan', 'SAN-PGJP', 15);
INSERT INTO public.actimize_screening_type_mappings ("Search_Definition_ID", is_active, created_at, updated_at, search_definition_name, "Screening_Type", display_order) VALUES ('SD_US_Customers_Sanctions_PGIM_PP_FI', true, '2026-05-02 00:00:00+00', '2026-05-04 19:16:08.282099+00', 'Customer Sanctions PGIM Public and Private Fixed Income', 'SAN-PPFI', 16);
INSERT INTO public.actimize_screening_type_mappings ("Search_Definition_ID", is_active, created_at, updated_at, search_definition_name, "Screening_Type", display_order) VALUES ('SD_US_Customers_Sanctions_PGIM_QUANT', true, '2026-05-02 00:00:00+00', '2026-05-04 19:16:08.282835+00', 'Customer Sanctions PGIM Quant', 'SAN-PPQS', 17);
INSERT INTO public.actimize_screening_type_mappings ("Search_Definition_ID", is_active, created_at, updated_at, search_definition_name, "Screening_Type", display_order) VALUES ('SD_US_Customers_Sanctions_PGIM_RE', true, '2026-05-02 00:00:00+00', '2026-05-04 19:16:08.284692+00', 'Customer Sanctions PGIM Real Estate', 'SAN-PLUX', 18);


--
-- Data for Name: business_units; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.business_units (business_unit_code, business_unit_name, is_active, created_at, updated_at) VALUES ('US_PRU_OSGLI', 'OSGLI', true, '2026-04-17 22:48:09.326599+00', '2026-04-17 22:48:09.326599+00');
INSERT INTO public.business_units (business_unit_code, business_unit_name, is_active, created_at, updated_at) VALUES ('US_PRU_VM', 'Vendor Management', true, '2026-04-17 22:48:09.326599+00', '2026-04-17 22:48:09.326599+00');
INSERT INTO public.business_units (business_unit_code, business_unit_name, is_active, created_at, updated_at) VALUES ('US_PRU_HR', 'Human Resources', true, '2026-04-17 22:48:09.326599+00', '2026-04-17 22:48:09.326599+00');
INSERT INTO public.business_units (business_unit_code, business_unit_name, is_active, created_at, updated_at) VALUES ('US_PRU_OPES', 'Operation/Enabling Solutions', true, '2026-04-17 22:48:09.326599+00', '2026-04-17 22:48:09.326599+00');
INSERT INTO public.business_units (business_unit_code, business_unit_name, is_active, created_at, updated_at) VALUES ('US_PRU_PGIM', 'PGIM', true, '2026-04-17 22:48:09.326599+00', '2026-04-17 22:48:09.326599+00');
INSERT INTO public.business_units (business_unit_code, business_unit_name, is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE_TENANT', 'PGIM Real Estate tenant', true, '2026-04-17 22:48:09.326599+00', '2026-04-17 22:48:09.326599+00');
INSERT INTO public.business_units (business_unit_code, business_unit_name, is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE', 'PGIM Real Estate', true, '2026-04-17 22:48:09.326599+00', '2026-04-17 22:48:09.326599+00');
INSERT INTO public.business_units (business_unit_code, business_unit_name, is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_FI', 'PGIM Fixed Income', true, '2026-04-17 22:48:09.326599+00', '2026-04-17 22:48:09.326599+00');
INSERT INTO public.business_units (business_unit_code, business_unit_name, is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_PP_FI', 'PGIMPublic and Private Fixed Income', true, '2026-04-17 22:48:09.326599+00', '2026-04-17 22:48:09.326599+00');
INSERT INTO public.business_units (business_unit_code, business_unit_name, is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_MA', 'PGIM Multi Asset Solutions', true, '2026-04-17 22:48:09.326599+00', '2026-04-17 22:48:09.326599+00');
INSERT INTO public.business_units (business_unit_code, business_unit_name, is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_CIO', 'PGIM CIO', true, '2026-04-17 22:48:09.326599+00', '2026-04-17 22:48:09.326599+00');
INSERT INTO public.business_units (business_unit_code, business_unit_name, is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_JAPAN', 'PGIM Japan', true, '2026-04-17 22:48:09.326599+00', '2026-04-17 22:48:09.326599+00');
INSERT INTO public.business_units (business_unit_code, business_unit_name, is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_JK_ASC', 'PGIM Jenkins Associates', true, '2026-04-17 22:48:09.326599+00', '2026-04-17 22:48:09.326599+00');
INSERT INTO public.business_units (business_unit_code, business_unit_name, is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_NE_FI', 'PGIM Netherlands', true, '2026-04-17 22:48:09.326599+00', '2026-04-17 22:48:09.326599+00');
INSERT INTO public.business_units (business_unit_code, business_unit_name, is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_QUANT', 'PGIM Quant Compliance', true, '2026-04-17 22:48:09.326599+00', '2026-04-17 22:48:09.326599+00');
INSERT INTO public.business_units (business_unit_code, business_unit_name, is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE_APAC', 'PGIM Real Estate APAC', true, '2026-04-17 22:48:09.326599+00', '2026-04-17 22:48:09.326599+00');
INSERT INTO public.business_units (business_unit_code, business_unit_name, is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_LATAM', 'PGIM LATAM', true, '2026-04-17 22:48:09.326599+00', '2026-04-17 22:48:09.326599+00');
INSERT INTO public.business_units (business_unit_code, business_unit_name, is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_HK', 'PGIM HongKong', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');


--
-- Data for Name: business_unit_screening_types; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE_APAC', 'SAN-PAPC', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_CIO', 'SAN-PCIO', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_FI', 'SAN-PFIC', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_JK_ASC', 'SAN-PJAC', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_LATAM', 'SAN-PPLA', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_MA', 'SAN-PSCG', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_NE_FI', 'SAN-PUPV', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_HK', 'SAN-PGHK', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_JAPAN', 'SAN-PGJP', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_PP_FI', 'SAN-PPFI', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_QUANT', 'SAN-PPQS', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE', 'SAN-PLUX', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_HR', 'SAN-US', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_OPES', 'SAN-US', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_OSGLI', 'SAN-US', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM', 'SAN-US', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_CIO', 'SAN-US', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_FI', 'SAN-US', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_HK', 'SAN-US', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_JAPAN', 'SAN-US', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_JK_ASC', 'SAN-US', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_LATAM', 'SAN-US', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_MA', 'SAN-US', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_NE_FI', 'SAN-US', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_PP_FI', 'SAN-US', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_QUANT', 'SAN-US', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE', 'SAN-US', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE_APAC', 'SAN-US', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE_TENANT', 'SAN-US', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_VM', 'SAN-US', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_HR', 'AME', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_OPES', 'AME', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_OSGLI', 'AME', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM', 'AME', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_CIO', 'AME', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_FI', 'AME', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_HK', 'AME', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_JAPAN', 'AME', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_JK_ASC', 'AME', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_LATAM', 'AME', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_MA', 'AME', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_NE_FI', 'AME', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_PP_FI', 'AME', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_QUANT', 'AME', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE', 'AME', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE_APAC', 'AME', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE_TENANT', 'AME', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_VM', 'AME', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_HR', 'PEP-G', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_OPES', 'PEP-G', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_OSGLI', 'PEP-G', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM', 'PEP-G', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_CIO', 'PEP-G', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_FI', 'PEP-G', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_HK', 'PEP-G', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_JAPAN', 'PEP-G', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_JK_ASC', 'PEP-G', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_LATAM', 'PEP-G', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_MA', 'PEP-G', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_NE_FI', 'PEP-G', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_PP_FI', 'PEP-G', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_QUANT', 'PEP-G', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE', 'PEP-G', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE_APAC', 'PEP-G', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE_TENANT', 'PEP-G', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_VM', 'PEP-G', true, '2026-05-20 13:35:23.489831+00', '2026-05-20 13:35:23.489831+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_OSGLI', 'PEP', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_OSGLI', '314a', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_OSGLI', 'MPIN', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_VM', 'PEP', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_VM', '314a', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_VM', 'MPIN', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_HR', 'PEP', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_HR', '314a', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_HR', 'MPIN', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_OPES', 'PEP', true, '2026-05-20 13:35:23.489831+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_OPES', '314a', true, '2026-05-20 13:35:23.489831+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_OPES', 'MPIN', true, '2026-05-20 13:35:23.489831+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM', 'PEP', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM', '314a', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM', 'MPIN', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE_TENANT', 'PEP', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE_TENANT', '314a', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE_TENANT', 'MPIN', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE', 'PEP', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE', '314a', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE', 'MPIN', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_FI', 'PEP', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_FI', '314a', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_FI', 'MPIN', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_PP_FI', 'PEP', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_PP_FI', '314a', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_PP_FI', 'MPIN', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_MA', 'PEP', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_MA', '314a', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_MA', 'MPIN', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_CIO', 'PEP', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_CIO', '314a', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_CIO', 'MPIN', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_JAPAN', 'PEP', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_JAPAN', '314a', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_JAPAN', 'MPIN', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_JK_ASC', 'PEP', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_JK_ASC', '314a', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_JK_ASC', 'MPIN', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_NE_FI', 'PEP', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_NE_FI', '314a', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_NE_FI', 'MPIN', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_QUANT', 'PEP', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_QUANT', '314a', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_QUANT', 'MPIN', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE_APAC', 'PEP', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE_APAC', '314a', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_RE_APAC', 'MPIN', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_LATAM', 'PEP', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_LATAM', '314a', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_LATAM', 'MPIN', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_HK', 'PEP', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_HK', '314a', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');
INSERT INTO public.business_unit_screening_types (business_unit_code, "Screening_Type", is_active, created_at, updated_at) VALUES ('US_PRU_PGIM_HK', 'MPIN', true, '2026-05-22 13:57:09.900222+00', '2026-05-22 13:57:09.900222+00');


--
-- PostgreSQL database dump complete
--

\unrestrict ziRPPGlIkGZger347GeI24FLOjdOiodPiHFtdc0FfXkTdCrDtXWbzPgh7rEdf7a

