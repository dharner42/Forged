-- Forged Machine Monitoring warehouse. DuckDB is the default so a clone does not need Docker.
-- line, production_impact, parts, and technicians are SIMULATED.

CREATE TABLE machines (
    machine_id INTEGER PRIMARY KEY,
    model VARCHAR NOT NULL,
    age_years INTEGER NOT NULL,
    line VARCHAR NOT NULL,
    production_impact INTEGER NOT NULL CHECK (production_impact BETWEEN 1 AND 5)
);

CREATE TABLE sensor_readings (
    machine_id INTEGER NOT NULL,
    ts TIMESTAMP NOT NULL,
    volt DOUBLE NOT NULL,
    rotate DOUBLE NOT NULL,
    pressure DOUBLE NOT NULL,
    vibration DOUBLE NOT NULL,
    PRIMARY KEY (machine_id, ts),
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id)
);

CREATE TABLE faults (
    fault_id INTEGER PRIMARY KEY,
    machine_id INTEGER NOT NULL,
    ts TIMESTAMP NOT NULL,
    error_code VARCHAR NOT NULL,
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id)
);

CREATE TABLE failures (
    failure_id INTEGER PRIMARY KEY,
    machine_id INTEGER NOT NULL,
    ts TIMESTAMP NOT NULL,
    component VARCHAR NOT NULL,
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id)
);

-- Shifts are SIMULATED shop hours. Technicians point at shift_id.
CREATE TABLE shifts (
    shift_id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    start_hour INTEGER NOT NULL,
    end_hour INTEGER NOT NULL,
    simulated BOOLEAN NOT NULL
);

CREATE TABLE technicians (
    technician_id INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL,
    skill VARCHAR NOT NULL,
    shift VARCHAR NOT NULL,
    simulated BOOLEAN NOT NULL,
    FOREIGN KEY (shift) REFERENCES shifts(shift_id)
);

CREATE TABLE parts (
    part_id INTEGER PRIMARY KEY,
    component VARCHAR NOT NULL,
    on_hand INTEGER NOT NULL,
    reorder_point INTEGER NOT NULL,
    lead_time_days INTEGER NOT NULL,
    simulated BOOLEAN NOT NULL
);

CREATE TABLE maintenance_events (
    event_id INTEGER PRIMARY KEY,
    machine_id INTEGER NOT NULL,
    ts TIMESTAMP NOT NULL,
    component VARCHAR NOT NULL,
    type VARCHAR NOT NULL,
    technician_id INTEGER,
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id),
    FOREIGN KEY (technician_id) REFERENCES technicians(technician_id)
);

CREATE TABLE work_orders (
    work_order_id INTEGER PRIMARY KEY,
    machine_id INTEGER NOT NULL,
    component VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    priority_score DOUBLE,
    opened_ts TIMESTAMP NOT NULL,
    closed_ts TIMESTAMP,
    technician_id INTEGER,
    reason VARCHAR,
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id),
    FOREIGN KEY (technician_id) REFERENCES technicians(technician_id)
);

CREATE TABLE plant_clock (
    id INTEGER PRIMARY KEY,
    as_of TIMESTAMP NOT NULL,
    note VARCHAR
);

-- One row per machine for the current plant clock. Replaced on every rescore.
CREATE TABLE current_scores (
    machine_id INTEGER PRIMARY KEY,
    ts TIMESTAMP NOT NULL,
    p_fail_24h DOUBLE NOT NULL,
    predicted_component VARCHAR NOT NULL,
    parts_factor DOUBLE NOT NULL,
    priority_score DOUBLE NOT NULL,
    queue_score DOUBLE NOT NULL,
    band VARCHAR NOT NULL,
    top_reason VARCHAR NOT NULL,
    serviced_within_24h BOOLEAN NOT NULL,
    contrib_json VARCHAR,
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id)
);

-- Morning scores across the September–December test window.
CREATE TABLE predictions (
    machine_id INTEGER NOT NULL,
    ts TIMESTAMP NOT NULL,
    p_fail_24h DOUBLE NOT NULL,
    predicted_component VARCHAR NOT NULL,
    parts_factor DOUBLE NOT NULL,
    priority_score DOUBLE NOT NULL,
    queue_score DOUBLE NOT NULL,
    band VARCHAR NOT NULL,
    top_reason VARCHAR NOT NULL,
    PRIMARY KEY (machine_id, ts),
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id)
);

CREATE TABLE bench_ai4i (
    udi INTEGER,
    product_id VARCHAR,
    type VARCHAR,
    air_temp_k DOUBLE,
    process_temp_k DOUBLE,
    rpm INTEGER,
    torque_nm DOUBLE,
    tool_wear_min INTEGER,
    machine_failure INTEGER,
    twf INTEGER,
    hdf INTEGER,
    pwf INTEGER,
    osf INTEGER,
    rnf INTEGER
);

CREATE TABLE bench_cmapss_fd001 (
    unit INTEGER,
    cycle INTEGER,
    op1 DOUBLE,
    op2 DOUBLE,
    op3 DOUBLE,
    s1 DOUBLE, s2 DOUBLE, s3 DOUBLE, s4 DOUBLE, s5 DOUBLE,
    s6 DOUBLE, s7 DOUBLE, s8 DOUBLE, s9 DOUBLE, s10 DOUBLE,
    s11 DOUBLE, s12 DOUBLE, s13 DOUBLE, s14 DOUBLE, s15 DOUBLE,
    s16 DOUBLE, s17 DOUBLE, s18 DOUBLE, s19 DOUBLE, s20 DOUBLE, s21 DOUBLE,
    split VARCHAR
);

CREATE TABLE bench_cmapss_rul (
    unit INTEGER PRIMARY KEY,
    rul INTEGER
);

CREATE INDEX idx_sensor_machine_ts ON sensor_readings(machine_id, ts);
CREATE INDEX idx_faults_machine_ts ON faults(machine_id, ts);
CREATE INDEX idx_failures_machine_ts ON failures(machine_id, ts);
CREATE INDEX idx_maint_machine_ts ON maintenance_events(machine_id, ts);
CREATE INDEX idx_predictions_ts ON predictions(ts);

CREATE VIEW fix_first AS
SELECT
    cs.machine_id,
    m.model,
    m.line,
    m.age_years,
    m.production_impact,
    cs.ts,
    cs.p_fail_24h,
    cs.predicted_component,
    cs.parts_factor,
    cs.priority_score,
    cs.queue_score,
    cs.band,
    cs.top_reason,
    cs.serviced_within_24h,
    ROW_NUMBER() OVER (
        ORDER BY cs.queue_score DESC, cs.p_fail_24h DESC, cs.machine_id
    ) AS rank
FROM current_scores cs
JOIN machines m ON m.machine_id = cs.machine_id;

CREATE VIEW sensor_readings_live AS
SELECT s.*
FROM sensor_readings s
WHERE s.ts <= (SELECT as_of FROM plant_clock WHERE id = 1);

CREATE VIEW faults_live AS
SELECT f.*
FROM faults f
WHERE f.ts <= (SELECT as_of FROM plant_clock WHERE id = 1);

CREATE VIEW failures_live AS
SELECT f.*
FROM failures f
WHERE f.ts <= (SELECT as_of FROM plant_clock WHERE id = 1);

CREATE VIEW maintenance_live AS
SELECT m.*
FROM maintenance_events m
WHERE m.ts <= (SELECT as_of FROM plant_clock WHERE id = 1);

-- One stock position per component. The object model calls this Inventory.
-- The parts table is still the row you update when a repair consumes a unit.
CREATE VIEW inventory AS
SELECT
    part_id AS inventory_id,
    component,
    on_hand,
    reorder_point,
    lead_time_days,
    simulated
FROM parts;
