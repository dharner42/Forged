"""The plant as objects and the links between them.

This is the data model a maintenance lead and a software reviewer can share.
It is not a Palantir Foundry ontology. The names are the same idea: an object
type has a primary key and properties, and a link type says how two objects
connect. The warehouse tables are the backing store. Simulated properties are
marked, because parts, shifts, and production impact were not in the public
files.

Component and inventory share the ``parts`` table. This dataset has one SKU
per component, so one row is both the component and its stock position. A real
storeroom would split the part master from the bin. The ``inventory`` view is
that stock position.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Property:
    name: str
    type_name: str
    description: str
    simulated: bool = False


@dataclass(frozen=True)
class ObjectType:
    name: str
    api_name: str
    primary_key: str
    table: str
    description: str
    simulated: bool
    properties: tuple[Property, ...]


@dataclass(frozen=True)
class LinkType:
    name: str
    from_object: str
    to_object: str
    cardinality: str
    description: str
    # Rows that should be zero: the child does not point at a real parent.
    # None when the link is descriptive only.
    orphan_sql: str | None


@dataclass(frozen=True)
class Shift:
    shift_id: str
    name: str
    start_hour: int
    end_hour: int


# Hour ranges are simulated. Day 06:00–14:00, swing 14:00–22:00, night otherwise.
# end_hour is exclusive. Night wraps past midnight, so end_hour < start_hour.
SHIFTS: tuple[Shift, ...] = (
    Shift("day", "Day", 6, 14),
    Shift("swing", "Swing", 14, 22),
    Shift("night", "Night", 22, 6),
)

# The Azure file names components comp1–comp4 and never says what they are.
# The skill is the simulated link from a component to the technician who can work it.
COMPONENTS: tuple[str, ...] = ("comp1", "comp2", "comp3", "comp4")
COMPONENT_SKILL: dict[str, str] = {
    "comp1": "mechanical",
    "comp2": "hydraulics",
    "comp3": "electrical",
    "comp4": "general",
}


def shift_id_for_hour(hour: int) -> str:
    hour = int(hour)
    for shift in SHIFTS:
        if shift.start_hour < shift.end_hour:
            if shift.start_hour <= hour < shift.end_hour:
                return shift.shift_id
        elif hour >= shift.start_hour or hour < shift.end_hour:
            return shift.shift_id
    raise RuntimeError(f"hour {hour} did not match a shift")


def shift_id_for_timestamp(as_of) -> str:
    hour = getattr(as_of, "hour", None)
    if hour is None:
        text = str(as_of).replace("T", " ")
        clock = text.split()[-1]
        hour = int(clock.split(":")[0])
    return shift_id_for_hour(int(hour))


OBJECTS: tuple[ObjectType, ...] = (
    ObjectType(
        name="Machine",
        api_name="Machine",
        primary_key="machine_id",
        table="machines",
        description="A physical asset on a line. Model and age come from the Azure file. Line and production impact are simulated.",
        simulated=False,
        properties=(
            Property("machine_id", "integer", "Stable id from the source file."),
            Property("model", "string", "Machine model, model1–model4."),
            Property("age_years", "integer", "Age in years from the source file."),
            Property("line", "string", "Machining, Assembly, Test, or Finish.", simulated=True),
            Property("production_impact", "integer", "1–5 rating of how much production this machine stops.", simulated=True),
        ),
    ),
    ObjectType(
        name="Component",
        api_name="Component",
        primary_key="component",
        table="parts",
        description="A replaceable component type. In this plant there is one part SKU per component, so the row also holds stock.",
        simulated=True,
        properties=(
            Property("component", "string", "comp1–comp4. The dataset does not define them physically.", simulated=True),
            Property("part_id", "integer", "Surrogate id for the SKU.", simulated=True),
        ),
    ),
    ObjectType(
        name="SensorReading",
        api_name="SensorReading",
        primary_key="machine_id, ts",
        table="sensor_readings",
        description="One hour of voltage, rotation, pressure, and vibration from one machine.",
        simulated=False,
        properties=(
            Property("machine_id", "integer", "The machine that emitted the reading."),
            Property("ts", "timestamp", "Hour of the reading."),
            Property("volt", "double", "Voltage."),
            Property("rotate", "double", "Rotation."),
            Property("pressure", "double", "Pressure."),
            Property("vibration", "double", "Vibration."),
        ),
    ),
    ObjectType(
        name="Failure",
        api_name="Failure",
        primary_key="failure_id",
        table="failures",
        description="A component on a machine actually failed. This is a label. It is never a model feature.",
        simulated=False,
        properties=(
            Property("failure_id", "integer", "Surrogate id."),
            Property("machine_id", "integer", "Machine that failed."),
            Property("ts", "timestamp", "When the failure was logged."),
            Property("component", "string", "Which component failed."),
        ),
    ),
    ObjectType(
        name="WorkOrder",
        api_name="WorkOrder",
        primary_key="work_order_id",
        table="work_orders",
        description="A job opened from the queue and closed when someone logs the repair.",
        simulated=True,
        properties=(
            Property("work_order_id", "integer", "Surrogate id."),
            Property("machine_id", "integer", "Machine the job is for."),
            Property("component", "string", "Component the job replaces."),
            Property("status", "string", "open or closed."),
            Property("priority_score", "double", "Formula score at the time the job was opened."),
            Property("opened_ts", "timestamp", "Plant clock when the job was opened."),
            Property("closed_ts", "timestamp", "Plant clock when the job was closed. Null while open."),
            Property("technician_id", "integer", "Who it was assigned to.", simulated=True),
            Property("reason", "string", "Why the machine was on the list."),
        ),
    ),
    ObjectType(
        name="Technician",
        api_name="Technician",
        primary_key="technician_id",
        table="technicians",
        description="A person who can be assigned a work order. Names, skills, and shifts are simulated.",
        simulated=True,
        properties=(
            Property("technician_id", "integer", "Surrogate id.", simulated=True),
            Property("name", "string", "Fictional name.", simulated=True),
            Property("skill", "string", "mechanical, hydraulics, electrical, or general.", simulated=True),
            Property("shift", "string", "The shift this person works.", simulated=True),
        ),
    ),
    ObjectType(
        name="Shift",
        api_name="Shift",
        primary_key="shift_id",
        table="shifts",
        description="Day, swing, or night. The hours are a simulated shop rule, not a union contract.",
        simulated=True,
        properties=(
            Property("shift_id", "string", "day, swing, or night.", simulated=True),
            Property("name", "string", "Display name.", simulated=True),
            Property("start_hour", "integer", "Inclusive hour, 0–23.", simulated=True),
            Property("end_hour", "integer", "Exclusive hour. Night wraps, so end is before start.", simulated=True),
        ),
    ),
    ObjectType(
        name="Inventory",
        api_name="Inventory",
        primary_key="inventory_id",
        table="inventory",
        description="How many of a component are on the shelf, the reorder point, and the lead time. A view over parts.",
        simulated=True,
        properties=(
            Property("inventory_id", "integer", "Same as part_id.", simulated=True),
            Property("component", "string", "The component this bin stocks.", simulated=True),
            Property("on_hand", "integer", "Units on the shelf.", simulated=True),
            Property("reorder_point", "integer", "Below this, the parts factor becomes 1.5.", simulated=True),
            Property("lead_time_days", "integer", "Days to restock.", simulated=True),
        ),
    ),
)

# Work orders may be empty on a freshly built warehouse. The other objects are
# part of a load: a plant with no machines, or no shifts, is not this ontology.
REQUIRED_NONEMPTY = frozenset(
    {"Machine", "Component", "SensorReading", "Failure", "Technician", "Shift", "Inventory"}
)

LINKS: tuple[LinkType, ...] = (
    LinkType(
        name="emits",
        from_object="Machine",
        to_object="SensorReading",
        cardinality="one_to_many",
        description="A machine emits sensor readings.",
        orphan_sql=(
            "SELECT count(*) FROM sensor_readings s "
            "LEFT JOIN machines m ON m.machine_id = s.machine_id "
            "WHERE m.machine_id IS NULL"
        ),
    ),
    LinkType(
        name="suffers",
        from_object="Machine",
        to_object="Failure",
        cardinality="one_to_many",
        description="A machine suffers failures.",
        orphan_sql=(
            "SELECT count(*) FROM failures f "
            "LEFT JOIN machines m ON m.machine_id = f.machine_id "
            "WHERE m.machine_id IS NULL"
        ),
    ),
    LinkType(
        name="failed_component",
        from_object="Failure",
        to_object="Component",
        cardinality="many_to_one",
        description="A failure names the component that broke.",
        orphan_sql=(
            "SELECT count(*) FROM failures f "
            "LEFT JOIN parts p ON p.component = f.component "
            "WHERE p.component IS NULL"
        ),
    ),
    LinkType(
        name="has_work_order",
        from_object="Machine",
        to_object="WorkOrder",
        cardinality="one_to_many",
        description="A machine has work orders opened from the queue.",
        orphan_sql=(
            "SELECT count(*) FROM work_orders w "
            "LEFT JOIN machines m ON m.machine_id = w.machine_id "
            "WHERE m.machine_id IS NULL"
        ),
    ),
    LinkType(
        name="replaces",
        from_object="WorkOrder",
        to_object="Component",
        cardinality="many_to_one",
        description="A work order replaces one component.",
        orphan_sql=(
            "SELECT count(*) FROM work_orders w "
            "LEFT JOIN parts p ON p.component = w.component "
            "WHERE p.component IS NULL"
        ),
    ),
    LinkType(
        name="assigned_to",
        from_object="WorkOrder",
        to_object="Technician",
        cardinality="many_to_one",
        description="A work order is assigned to one technician.",
        orphan_sql=(
            "SELECT count(*) FROM work_orders w "
            "LEFT JOIN technicians t ON t.technician_id = w.technician_id "
            "WHERE w.technician_id IS NOT NULL AND t.technician_id IS NULL"
        ),
    ),
    LinkType(
        name="works",
        from_object="Technician",
        to_object="Shift",
        cardinality="many_to_one",
        description="A technician works one shift.",
        orphan_sql=(
            "SELECT count(*) FROM technicians t "
            "LEFT JOIN shifts s ON s.shift_id = t.shift "
            "WHERE s.shift_id IS NULL"
        ),
    ),
    LinkType(
        name="stocked_as",
        from_object="Component",
        to_object="Inventory",
        cardinality="one_to_one",
        description="Each component has one inventory position in this plant.",
        orphan_sql=(
            "SELECT count(*) FROM parts p "
            "LEFT JOIN inventory i ON i.component = p.component "
            "WHERE i.component IS NULL"
        ),
    ),
    LinkType(
        name="installed_on",
        from_object="Component",
        to_object="Machine",
        cardinality="many_to_many",
        description="A component is installed on a machine. The evidence is a maintenance event, which is a replacement, not a separate object.",
        orphan_sql=(
            "SELECT count(*) FROM maintenance_events e "
            "LEFT JOIN machines m ON m.machine_id = e.machine_id "
            "LEFT JOIN parts p ON p.component = e.component "
            "WHERE m.machine_id IS NULL OR p.component IS NULL"
        ),
    ),
)


def object_by_name(name: str) -> ObjectType:
    for obj in OBJECTS:
        if obj.name == name:
            return obj
    raise KeyError(name)


def assert_warehouse_matches_ontology(con) -> dict[str, int]:
    """Reject a warehouse whose objects are empty or whose links are dangling.

    Called at the end of a pipeline build and after the bundled sample plant
    is created. Work orders may be empty. Everything else in REQUIRED_NONEMPTY
    must have rows, and every link query must return zero orphans.
    """
    counts: dict[str, int] = {}
    for obj in OBJECTS:
        counts[obj.name] = int(con.execute(f"SELECT count(*) FROM {obj.table}").fetchone()[0])
        if obj.name in REQUIRED_NONEMPTY and counts[obj.name] == 0:
            raise RuntimeError(f"Ontology object {obj.name} ({obj.table}) has no rows.")
    for link in LINKS:
        if link.orphan_sql is None:
            continue
        orphans = int(con.execute(link.orphan_sql).fetchone()[0])
        if orphans:
            raise RuntimeError(f"Link {link.from_object} -[{link.name}]-> {link.to_object} has {orphans} dangling rows.")
    return counts
