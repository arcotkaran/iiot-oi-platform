--
-- PostgreSQL database dump
--

\restrict ZeZzibWzjYfEx09lRKr8aMSgNUx8xgWOgyrAP3OIEAPOKJknloewbU9Qbdm1pWh

-- Dumped from database version 15.17 (Debian 15.17-1.pgdg13+1)
-- Dumped by pg_dump version 15.17 (Debian 15.17-1.pgdg13+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: analytics; Type: SCHEMA; Schema: -; Owner: factory
--

CREATE SCHEMA analytics;


ALTER SCHEMA analytics OWNER TO factory;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: machine_telemetry; Type: TABLE; Schema: public; Owner: factory
--

CREATE TABLE public.machine_telemetry (
    id integer NOT NULL,
    machine_id character varying(50) NOT NULL,
    mqtt_topic character varying(100),
    temperature_c double precision,
    spindle_rpm double precision,
    vibration_mms double precision,
    tool_wear_pct double precision,
    belt_speed_mpm double precision,
    motor_load_pct double precision,
    running_hours double precision,
    pressure_bar double precision,
    oil_temp_c double precision,
    cycle_count integer,
    status character varying(20),
    fault character varying(50),
    received_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.machine_telemetry OWNER TO factory;

--
-- Name: dim_machines; Type: VIEW; Schema: analytics; Owner: factory
--

CREATE VIEW analytics.dim_machines AS
 SELECT DISTINCT ON (machine_telemetry.machine_id) machine_telemetry.machine_id,
        CASE machine_telemetry.machine_id
            WHEN 'cnc_mill'::text THEN 'CNC Mill'::character varying
            WHEN 'conveyor'::text THEN 'Conveyor Belt'::character varying
            WHEN 'hydraulic_press'::text THEN 'Hydraulic Press'::character varying
            ELSE machine_telemetry.machine_id
        END AS machine_name,
        CASE machine_telemetry.machine_id
            WHEN 'cnc_mill'::text THEN 'Machining'::text
            WHEN 'conveyor'::text THEN 'Material Handling'::text
            WHEN 'hydraulic_press'::text THEN 'Press'::text
            ELSE 'Unknown'::text
        END AS machine_type,
    machine_telemetry.status AS current_status,
    machine_telemetry.fault AS current_fault,
    machine_telemetry.received_at AS last_seen
   FROM public.machine_telemetry
  ORDER BY machine_telemetry.machine_id, machine_telemetry.received_at DESC;


ALTER TABLE analytics.dim_machines OWNER TO factory;

--
-- Name: fct_hourly_performance; Type: VIEW; Schema: analytics; Owner: factory
--

CREATE VIEW analytics.fct_hourly_performance AS
 SELECT machine_telemetry.machine_id,
    date_trunc('hour'::text, machine_telemetry.received_at) AS hour_bucket,
    count(*) AS reading_count,
    round((avg(COALESCE(machine_telemetry.temperature_c, machine_telemetry.oil_temp_c)))::numeric, 2) AS avg_temp_c,
    round((max(COALESCE(machine_telemetry.temperature_c, machine_telemetry.oil_temp_c)))::numeric, 2) AS max_temp_c,
    round((min(COALESCE(machine_telemetry.temperature_c, machine_telemetry.oil_temp_c)))::numeric, 2) AS min_temp_c,
    round((avg(machine_telemetry.spindle_rpm))::numeric, 1) AS avg_spindle_rpm,
    round((avg(machine_telemetry.vibration_mms))::numeric, 3) AS avg_vibration_mms,
    round((avg(machine_telemetry.belt_speed_mpm))::numeric, 2) AS avg_belt_speed,
    round((avg(machine_telemetry.motor_load_pct))::numeric, 1) AS avg_motor_load,
    round((avg(machine_telemetry.pressure_bar))::numeric, 1) AS avg_pressure_bar,
    max(machine_telemetry.cycle_count) AS max_cycle_count,
    count(
        CASE
            WHEN (machine_telemetry.fault IS NOT NULL) THEN 1
            ELSE NULL::integer
        END) AS fault_count,
    count(
        CASE
            WHEN ((machine_telemetry.status)::text = 'running'::text) THEN 1
            ELSE NULL::integer
        END) AS running_count,
    count(
        CASE
            WHEN ((machine_telemetry.status)::text = 'stopped'::text) THEN 1
            ELSE NULL::integer
        END) AS stopped_count
   FROM public.machine_telemetry
  GROUP BY machine_telemetry.machine_id, (date_trunc('hour'::text, machine_telemetry.received_at))
  ORDER BY machine_telemetry.machine_id, (date_trunc('hour'::text, machine_telemetry.received_at));


ALTER TABLE analytics.fct_hourly_performance OWNER TO factory;

--
-- Name: stg_telemetry; Type: VIEW; Schema: analytics; Owner: factory
--

CREATE VIEW analytics.stg_telemetry AS
 SELECT machine_telemetry.id,
    machine_telemetry.machine_id,
    machine_telemetry.mqtt_topic,
    COALESCE(machine_telemetry.temperature_c, machine_telemetry.oil_temp_c) AS temperature_c,
    machine_telemetry.spindle_rpm,
    machine_telemetry.vibration_mms,
    machine_telemetry.tool_wear_pct,
    machine_telemetry.belt_speed_mpm,
    machine_telemetry.motor_load_pct,
    machine_telemetry.running_hours,
    machine_telemetry.pressure_bar,
    machine_telemetry.oil_temp_c,
    machine_telemetry.cycle_count,
    machine_telemetry.status,
    machine_telemetry.fault,
    machine_telemetry.received_at,
    date_trunc('hour'::text, machine_telemetry.received_at) AS hour_bucket
   FROM public.machine_telemetry
  WHERE (machine_telemetry.machine_id IS NOT NULL);


ALTER TABLE analytics.stg_telemetry OWNER TO factory;

--
-- Name: machine_telemetry_id_seq; Type: SEQUENCE; Schema: public; Owner: factory
--

CREATE SEQUENCE public.machine_telemetry_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.machine_telemetry_id_seq OWNER TO factory;

--
-- Name: machine_telemetry_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: factory
--

ALTER SEQUENCE public.machine_telemetry_id_seq OWNED BY public.machine_telemetry.id;


--
-- Name: machine_telemetry id; Type: DEFAULT; Schema: public; Owner: factory
--

ALTER TABLE ONLY public.machine_telemetry ALTER COLUMN id SET DEFAULT nextval('public.machine_telemetry_id_seq'::regclass);


--
-- Name: machine_telemetry machine_telemetry_pkey; Type: CONSTRAINT; Schema: public; Owner: factory
--

ALTER TABLE ONLY public.machine_telemetry
    ADD CONSTRAINT machine_telemetry_pkey PRIMARY KEY (id);


--
-- Name: idx_machine_telemetry_machine_id; Type: INDEX; Schema: public; Owner: factory
--

CREATE INDEX idx_machine_telemetry_machine_id ON public.machine_telemetry USING btree (machine_id);


--
-- Name: idx_machine_telemetry_received_at; Type: INDEX; Schema: public; Owner: factory
--

CREATE INDEX idx_machine_telemetry_received_at ON public.machine_telemetry USING btree (received_at);


--
-- PostgreSQL database dump complete
--

\unrestrict ZeZzibWzjYfEx09lRKr8aMSgNUx8xgWOgyrAP3OIEAPOKJknloewbU9Qbdm1pWh

