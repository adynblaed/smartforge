"""Seed the SmartForge sandbox: 1 factory, 1 line, 3 machines, users, supply
chain, customers/orders, knowledge docs, and baseline production/OEE data."""

from __future__ import annotations

import random
import uuid
from datetime import timedelta

from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    Customer,
    CustomerOrder,
    Defect,
    Factory,
    Incident,
    Inspection,
    InventoryItem,
    Job,
    JobStatus,
    KnowledgeDocument,
    Line,
    LineStatus,
    Machine,
    MachineConfiguration,
    MachineType,
    MaintenanceTicket,
    MaintenanceTicketLog,
    MaintenanceTicketPart,
    OrderStage,
    ProductionRun,
    PurchaseOrder,
    PurchaseOrderStatus,
    RcaRecord,
    Recommendation,
    RecommendationStatus,
    Severity,
    Sop,
    SopSection,
    Supplier,
    SupplierStatus,
    UserCreate,
    UserRole,
)
from app.models.base import get_datetime_utc
from app.services.factory_intelligence import compute_oee_from_run, vision_verdict

_RNG = random.Random(42)


def seed_sandbox(session: Session) -> None:
    if session.exec(select(Factory)).first():
        return  # already seeded

    factory = Factory(name="SmartForge Plant 1", location="Detroit, MI")
    session.add(factory)
    session.commit()
    session.refresh(factory)

    line = Line(name="Line 01", status=LineStatus.running, factory_id=factory.id)
    session.add(line)
    session.commit()
    session.refresh(line)

    machines = [
        Machine(
            code="cnc-01",
            name="CNC Mill 01",
            machine_type=MachineType.cnc_mill,
            manufacturer="Haas",
            model="VF-2",
            factory_id=factory.id,
            line_id=line.id,
            pos_x=-4.0,
            pos_z=0.0,
            runtime_hours=1850,
        ),
        Machine(
            code="arm-01",
            name="Robotic Arm 01",
            machine_type=MachineType.robotic_arm,
            manufacturer="KUKA",
            model="KR-10",
            factory_id=factory.id,
            line_id=line.id,
            pos_x=0.0,
            pos_z=0.0,
            runtime_hours=1200,
        ),
        Machine(
            code="press-01",
            name="Hydraulic Press 01",
            machine_type=MachineType.hydraulic_press,
            manufacturer="Schuler",
            model="HP-400",
            factory_id=factory.id,
            line_id=line.id,
            pos_x=4.0,
            pos_z=0.0,
            runtime_hours=2100,
        ),
    ]
    session.add_all(machines)
    session.commit()
    for m in machines:
        session.refresh(m)

    # Sandbox internal users per role
    for email, role in [
        ("operator@smartforge.com", UserRole.operator),
        ("maintenance@smartforge.com", UserRole.maintenance),
        ("planner@smartforge.com", UserRole.planner),
    ]:
        if not crud.get_user_by_email(session=session, email=email):
            crud.create_user(
                session=session,
                user_create=UserCreate(
                    email=email,
                    password=settings.SANDBOX_USER_PASSWORD,
                    full_name=role.value.title(),
                    role=role,
                ),
            )

    # Customers + portal users
    acme = Customer(name="Acme Robotics", contact_email="ops@acme-robotics.com")
    globex = Customer(name="Globex Manufacturing", contact_email="ops@globex-mfg.com")
    session.add_all([acme, globex])
    session.commit()
    session.refresh(acme)
    session.refresh(globex)
    for email, cust in [
        ("buyer@acme-robotics.com", acme),
        ("buyer@globex-mfg.com", globex),
    ]:
        if not crud.get_user_by_email(session=session, email=email):
            u = crud.create_user(
                session=session,
                user_create=UserCreate(
                    email=email,
                    password=settings.SANDBOX_USER_PASSWORD,
                    full_name="Portal User",
                    role=UserRole.customer,
                ),
            )
            u.customer_id = cust.id
            session.add(u)
    session.commit()

    # Customer orders across stages
    stages = list(OrderStage)
    for i in range(6):
        cust = acme if i % 2 == 0 else globex
        session.add(
            CustomerOrder(
                customer_id=cust.id,
                order_number=f"SO-10{i}",
                part_type=_RNG.choice(["bracket", "housing", "gear", "flange"]),
                quantity=_RNG.randint(50, 500),
                estimated_completion=get_datetime_utc()
                + timedelta(days=_RNG.randint(2, 20)),
                stage=stages[i % len(stages)],
                delayed=(i == 5),
                delay_reason="Material shortage" if i == 5 else None,
            )
        )

    # Suppliers + inventory
    s1 = Supplier(name="Steel Co", status=SupplierStatus.ok, lead_time_days=7)
    s2 = Supplier(name="Alloy Inc", status=SupplierStatus.delayed, lead_time_days=21)
    session.add_all([s1, s2])
    session.commit()
    session.refresh(s1)
    session.refresh(s2)
    session.add_all(
        [
            InventoryItem(
                sku="STL-4140",
                name="Steel 4140 bar",
                material_type="steel",
                quantity=120,
                reorder_threshold=100,
                supplier_id=s1.id,
                factory_id=factory.id,
            ),
            InventoryItem(
                sku="AL-6061",
                name="Aluminum 6061 block",
                material_type="aluminum",
                quantity=40,
                reorder_threshold=80,
                supplier_id=s2.id,
                factory_id=factory.id,
            ),
            InventoryItem(
                sku="HYD-OIL",
                name="Hydraulic oil",
                material_type="consumable",
                quantity=15,
                reorder_threshold=25,
                supplier_id=s1.id,
                factory_id=factory.id,
            ),
        ]
    )

    # Jobs
    session.add_all(
        [
            Job(
                customer="Acme Robotics",
                part_type="bracket",
                quantity=200,
                priority=2,
                status=JobStatus.approved,
                factory_id=factory.id,
            ),
            Job(
                customer="Globex Manufacturing",
                part_type="housing",
                quantity=350,
                priority=1,
                status=JobStatus.scheduled,
                factory_id=factory.id,
            ),
        ]
    )

    # Knowledge documents (RAG corpus)
    session.add_all(
        [
            KnowledgeDocument(
                title="CNC Mill Vibration Troubleshooting",
                kind="troubleshooting",
                machine_id=machines[0].id,
                tags="vibration,bearing,spindle",
                content="High vibration on the CNC mill is usually caused by worn spindle "
                "bearings, an unbalanced tool, or loose workholding. Inspect bearings, "
                "verify tool balance, and check fixture torque. If vibration index exceeds "
                "0.6, stop the machine and schedule bearing replacement.",
            ),
            KnowledgeDocument(
                title="Hydraulic Press Overheating SOP",
                kind="sop",
                machine_id=machines[2].id,
                tags="temperature,coolant,hydraulic",
                content="If press temperature exceeds 85C, check hydraulic oil level and "
                "cooler airflow. Low oil or a clogged cooler causes overheating. Replace "
                "oil per the maintenance schedule (every 2000 runtime hours).",
            ),
            KnowledgeDocument(
                title="Robotic Arm Fault Codes",
                kind="manual",
                machine_id=machines[1].id,
                tags="fault,error,controls",
                content="Fault E101 indicates a joint encoder error; E205 indicates a "
                "collision stop. Clear faults from the pendant, re-home the arm, and verify "
                "payload limits before resuming production.",
            ),
            KnowledgeDocument(
                title="Preventive Maintenance Standard",
                kind="sop",
                tags="maintenance,pm",
                content="Preventive maintenance is scheduled at runtime thresholds. Lubricate "
                "ways, inspect belts, and replace filters. Overdue PM increases downtime risk.",
            ),
        ]
    )
    session.commit()

    # Baseline production runs + OEE
    for shift in ["A", "B"]:
        for m in machines:
            run = ProductionRun(
                line_id=line.id,
                machine_id=m.id,
                shift=shift,
                planned_units=1000,
                actual_units=_RNG.randint(820, 980),
                scrap_units=_RNG.randint(5, 40),
                rework_units=_RNG.randint(2, 20),
                downtime_minutes=_RNG.randint(10, 90),
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            session.add(compute_oee_from_run(run))
    session.commit()

    # Machine configurations: current + a recommended profile per machine (2C/2D)
    for m in machines:
        session.add(
            MachineConfiguration(
                machine_id=m.id,
                version=1,
                is_current=True,
                is_recommended=False,
                approved=True,
                speed=1200,
                temperature=60,
                pressure=120,
                feed_rate=0.25,
                tooling_profile="standard",
                material_type="steel",
            )
        )
        session.add(
            MachineConfiguration(
                machine_id=m.id,
                version=2,
                is_current=False,
                is_recommended=True,
                approved=False,
                performance_delta=_RNG.uniform(3, 9),
                speed=1350,
                temperature=58,
                pressure=128,
                feed_rate=0.28,
                tooling_profile="optimized",
                material_type="steel",
            )
        )
    session.commit()

    # Closed-loop recommendations (2D)
    recs = [
        Recommendation(
            machine_id=machines[0].id,
            line_id=line.id,
            category="config",
            title="Increase spindle speed to 1350 RPM",
            detail="Historical runs show +6% throughput with stable vibration.",
            confidence=0.78,
        ),
        Recommendation(
            machine_id=machines[2].id,
            line_id=line.id,
            category="maintenance",
            title="Advance hydraulic oil change by 1 week",
            detail="Temperature trend predicts overheating within 120 runtime hours.",
            confidence=0.82,
            status=RecommendationStatus.accepted,
            outcome_impact=4.5,
        ),
        Recommendation(
            machine_id=machines[1].id,
            line_id=line.id,
            category="config",
            title="Reduce payload to cut cycle time variance",
            detail="Rejected — payload required for current job mix.",
            confidence=0.55,
            status=RecommendationStatus.rejected,
        ),
    ]
    session.add_all(recs)
    session.commit()

    # Incident + RCA (3D)
    incident = Incident(
        title="Line 01 hydraulic press unplanned stop",
        factory_id=factory.id,
        affected_machines=str(machines[2].id),
        delayed_orders=1,
        downtime_minutes=95,
        estimated_cost=12500.0,
        severity=Severity.high,
        resolved=False,
    )
    session.add(incident)
    session.commit()
    session.refresh(incident)
    session.add(
        RcaRecord(
            incident_id=incident.id,
            root_cause="Hydraulic oil cooler airflow restricted by debris buildup.",
            corrective_actions="Cleaned cooler, added cooler airflow check to PM checklist.",
            timeline_note="Detected 09:12, stopped 09:15, restored 10:50.",
        )
    )
    session.commit()

    # Purchase orders linked to jobs / orders / inventory (4C)
    jobs = list(session.exec(select(Job)).all())
    orders = list(session.exec(select(CustomerOrder)).all())
    inv = list(session.exec(select(InventoryItem)).all())
    for i in range(14):
        session.add(
            PurchaseOrder(
                po_number=f"PO-20{i:02d}",
                supplier_id=inv[i % len(inv)].supplier_id,
                customer_order_id=orders[i % len(orders)].id if orders else None,
                job_id=jobs[i % len(jobs)].id if jobs else None,
                inventory_item_id=inv[i % len(inv)].id,
                amount=_RNG.uniform(2000, 24000),
                status=[
                    PurchaseOrderStatus.open,
                    PurchaseOrderStatus.received,
                    PurchaseOrderStatus.draft,
                ][i % 3],
                shop_floor_ready=(i % 2 == 0),
            )
        )
    session.commit()

    # Vision inspections + defects (2A/2E)
    for i in range(24):
        part_id = f"PART-{1000 + i}"
        detected, dtype, conf = vision_verdict(part_id)
        insp = Inspection(
            part_id=part_id,
            line_id=line.id,
            defect_detected=detected,
            defect_type=dtype,
            confidence=conf,
            image_reference=f"s3://inspections/{part_id}.jpg",
        )
        session.add(insp)
        session.commit()
        session.refresh(insp)
        if detected:
            session.add(
                Defect(
                    inspection_id=insp.id,
                    line_id=line.id,
                    defect_type=dtype,
                    part_id=part_id,
                    scrap_cost=42.0,
                    is_scrap=True,
                )
            )
    session.commit()


def _sop(
    session: Session,
    *,
    code: str,
    title: str,
    category: str,
    entity_type: str,
    machine_id: uuid.UUID | None,
    summary: str,
    sections: list[tuple[str, str, str]],
) -> Sop:
    """Create an SOP with ordered (anchor, title, body) chapters."""
    sop = Sop(
        code=code,
        title=title,
        category=category,
        entity_type=entity_type,
        machine_id=machine_id,
        summary=summary,
    )
    session.add(sop)
    session.commit()
    session.refresh(sop)
    for i, (anchor, sec_title, body) in enumerate(sections):
        session.add(
            SopSection(
                sop_id=sop.id, anchor=anchor, order_index=i, title=sec_title, body=body
            )
        )
    session.commit()
    return sop


def seed_tickets_and_sops(session: Session) -> None:
    """Seed SOPs + maintenance tickets. Idempotent: keyed on the SOP table being
    empty, so it back-fills an already-seeded sandbox without a full reset."""
    if session.exec(select(Sop)).first():
        return  # already seeded

    machines = {m.code: m for m in session.exec(select(Machine)).all()}
    if not machines:
        return  # sandbox not seeded yet; nothing to attach to
    cnc = machines.get("cnc-01")
    arm = machines.get("arm-01")
    press = machines.get("press-01")
    incident = session.exec(select(Incident)).first()

    # --- Maintenance-part inventory (separate from raw materials) -----------
    suppliers = {s.name: s for s in session.exec(select(Supplier)).all()}
    steel = suppliers.get("Steel Co")
    alloy = suppliers.get("Alloy Inc")
    factory = session.exec(select(Factory)).first()
    fid = factory.id if factory else None
    sid_steel = steel.id if steel else None
    sid_alloy = alloy.id if alloy else None

    parts_inv = {
        "BRG-SPN-01": InventoryItem(
            sku="BRG-SPN-01",
            name="CNC spindle bearing",
            material_type="spare-part",
            quantity=1,
            unit="ea",
            reorder_threshold=2,
            supplier_id=sid_steel,
            factory_id=fid,
        ),
        "SEAL-HYD-01": InventoryItem(
            sku="SEAL-HYD-01",
            name="Hydraulic seal kit",
            material_type="spare-part",
            quantity=4,
            unit="kit",
            reorder_threshold=2,
            supplier_id=sid_alloy,
            factory_id=fid,
        ),
        "ENC-JNT-01": InventoryItem(
            sku="ENC-JNT-01",
            name="Robotic arm joint encoder",
            material_type="spare-part",
            quantity=0,
            unit="ea",
            reorder_threshold=1,
            supplier_id=sid_alloy,
            factory_id=fid,
        ),
        "FLT-AIR-01": InventoryItem(
            sku="FLT-AIR-01",
            name="Air intake filter",
            material_type="consumable",
            quantity=12,
            unit="ea",
            reorder_threshold=6,
            supplier_id=sid_steel,
            factory_id=fid,
        ),
        "LUB-WAY-01": InventoryItem(
            sku="LUB-WAY-01",
            name="Way lubricant (1L)",
            material_type="consumable",
            quantity=8,
            unit="bottle",
            reorder_threshold=4,
            supplier_id=sid_steel,
            factory_id=fid,
        ),
    }
    session.add_all(list(parts_inv.values()))
    session.commit()
    for it in parts_inv.values():
        session.refresh(it)
    # reuse existing hydraulic oil if present
    hyd_oil = session.exec(
        select(InventoryItem).where(InventoryItem.sku == "HYD-OIL")
    ).first()

    # --- SOPs (strict, chaptered operating guidelines) ---------------------
    sop_cnc = _sop(
        session,
        code="SOP-CNC-001",
        title="CNC Mill VF-2 — Operating & Maintenance SOP",
        category="maintenance",
        entity_type="machine",
        machine_id=cnc.id if cnc else None,
        summary="Authoritative procedure for safe operation, inspection and spindle "
        "service of the Haas VF-2 CNC mill.",
        sections=[
            (
                "overview",
                "1. Overview & Scope",
                "This SOP governs the Haas VF-2 CNC mill (cnc-01). It is a strict "
                "guideline: deviations require maintenance-supervisor sign-off.",
            ),
            (
                "startup",
                "2. Startup & Warm-up",
                "Confirm guards closed, coolant level nominal, and air pressure ≥ 6 bar. "
                "Run the spindle warm-up program (S1) for 8 minutes before cutting.",
            ),
            (
                "operation",
                "3. Normal Operation Limits",
                "Keep spindle load < 85%. Vibration index must stay below 0.6. Stop "
                "immediately if vibration exceeds 0.6 or abnormal noise is heard.",
            ),
            (
                "spindle-bearing-service",
                "4. Spindle Bearing Service",
                "Required when vibration index > 0.6 or every 4000 runtime hours.\n\n"
                "1. Lock out / tag out the machine.\n"
                "2. Remove the spindle cartridge per Haas service manual §7.\n"
                "3. Replace both angular-contact bearings (part BRG-SPN-01) as a set.\n"
                "4. Re-balance the tool holder and verify runout < 5 µm.\n"
                "5. Re-run warm-up S1, confirm vibration index < 0.4.",
            ),
            (
                "tool-balancing",
                "5. Tool Balancing",
                "Balance all tools to G2.5 at max RPM. An unbalanced tool is the most "
                "common cause of elevated vibration after a bearing service.",
            ),
            (
                "shutdown",
                "6. Shutdown",
                "Return axes to home, retract spindle, run chip wash, power down at the "
                "main disconnect.",
            ),
            (
                "safety",
                "7. Safety",
                "Never open the enclosure while the spindle is rotating. Always LOTO "
                "before any service task.",
            ),
        ],
    )
    sop_press = _sop(
        session,
        code="SOP-PRESS-001",
        title="Hydraulic Press HP-400 — Operating & Maintenance SOP",
        category="maintenance",
        entity_type="machine",
        machine_id=press.id if press else None,
        summary="Authoritative procedure for the Schuler HP-400 hydraulic press, "
        "including the oil/cooler service that prevents overheating.",
        sections=[
            (
                "overview",
                "1. Overview & Scope",
                "Governs the Schuler HP-400 hydraulic press (press-01). Strict guideline; "
                "overheating events must open a maintenance ticket.",
            ),
            (
                "startup",
                "2. Startup",
                "Verify hydraulic oil level in the sight glass and that cooler fans run. "
                "Do not start production if oil temperature is already above 70°C.",
            ),
            (
                "hydraulic-oil-service",
                "3. Hydraulic Oil & Seal Service",
                "Required when temperature exceeds 85°C or every 2000 runtime hours.\n\n"
                "1. LOTO and let the press cool below 40°C.\n"
                "2. Drain and replace hydraulic oil (HYD-OIL).\n"
                "3. Replace the seal kit (SEAL-HYD-01) if weeping is observed.\n"
                "4. Refill, bleed air, and confirm pressure holds at 120 bar.",
            ),
            (
                "cooler-cleaning",
                "4. Cooler Cleaning",
                "Debris on the oil-cooler fins restricts airflow and is the leading "
                "cause of overheating. Clean fins and verify fan airflow each PM.",
            ),
            (
                "pressure-check",
                "5. Pressure Verification",
                "After any hydraulic service, hold 120 bar for 10 minutes and confirm "
                "< 2 bar drop.",
            ),
            (
                "shutdown",
                "6. Shutdown",
                "Lower the ram, relieve pressure, power down at the disconnect.",
            ),
            (
                "safety",
                "7. Safety",
                "Hydraulic systems store energy — always relieve pressure and LOTO "
                "before opening any line.",
            ),
        ],
    )
    sop_arm = _sop(
        session,
        code="SOP-ARM-001",
        title="Robotic Arm KR-10 — Operating & Troubleshooting SOP",
        category="troubleshooting",
        entity_type="machine",
        machine_id=arm.id if arm else None,
        summary="Operating, fault-recovery and encoder-service procedure for the "
        "KUKA KR-10 robotic arm.",
        sections=[
            (
                "overview",
                "1. Overview & Scope",
                "Governs the KUKA KR-10 arm (arm-01). Strict guideline for fault "
                "recovery and joint service.",
            ),
            (
                "fault-recovery",
                "2. Fault Recovery",
                "Fault E101 = joint encoder error; E205 = collision stop. Clear from the "
                "pendant, re-home, and verify payload before resuming.",
            ),
            (
                "encoder-service",
                "3. Joint Encoder Service",
                "Required on repeated E101 faults.\n\n"
                "1. LOTO the controller.\n"
                "2. Replace the joint encoder (ENC-JNT-01).\n"
                "3. Re-master the affected axis.\n"
                "4. Verify repeatability < 0.05 mm before release.",
            ),
            (
                "payload-limits",
                "4. Payload Limits",
                "Never exceed 10 kg at full reach. Overload accelerates encoder wear.",
            ),
            (
                "re-homing",
                "5. Re-homing",
                "After any joint service, re-home all axes and run the validation path.",
            ),
            (
                "safety",
                "6. Safety",
                "Keep the cell guarded. Enable reduced speed for any in-cell work.",
            ),
        ],
    )
    sop_pm = _sop(
        session,
        code="SOP-PM-001",
        title="Preventive Maintenance Standard",
        category="process",
        entity_type="process",
        machine_id=None,
        summary="Plant-wide preventive maintenance cadence and checklist.",
        sections=[
            (
                "schedule",
                "1. PM Schedule",
                "PM is triggered at runtime thresholds per asset. Overdue PM materially "
                "increases unplanned-downtime risk.",
            ),
            (
                "lubrication",
                "2. Lubrication",
                "Lubricate ways and linear guides with way lubricant (LUB-WAY-01) at "
                "every PM interval.",
            ),
            (
                "filter-replacement",
                "3. Filter Replacement",
                "Replace air intake filters (FLT-AIR-01). A clogged filter reduces "
                "cooling and raises operating temperature.",
            ),
            (
                "belt-inspection",
                "4. Belt & Fastener Inspection",
                "Inspect drive belts for wear and verify fastener torque.",
            ),
        ],
    )

    # --- Tickets -----------------------------------------------------------
    now = get_datetime_utc()

    def ticket(
        code: str,
        title: str,
        machine: Machine | None,
        severity: str,
        status: str,
        window: int,
        sop: Sop | None,
        anchor: str | None,
        what: str,
        exec_: str,
        op: str,
        remediation: str,
        incident_id: uuid.UUID | None = None,
        acknowledged: tuple[str, str] | None = None,
    ) -> MaintenanceTicket:
        t = MaintenanceTicket(
            code=code,
            title=title,
            machine_id=machine.id if machine else None,
            incident_id=incident_id,
            severity=severity,
            status=status,
            what_happened=what,
            executive_summary=exec_,
            operator_detail=op,
            remediation=remediation,
            sop_id=sop.id if sop else None,
            sop_anchor=anchor,
            suggested_window_days=window,
        )
        if acknowledged:
            t.acknowledged_by, t.acknowledged_tz = acknowledged
            t.acknowledged_at = now - timedelta(hours=2)
        session.add(t)
        session.commit()
        session.refresh(t)
        return t

    def add_parts(
        t: MaintenanceTicket, items: list[tuple[InventoryItem | None, str, float]]
    ) -> None:
        for inv, name, qty in items:
            session.add(
                MaintenanceTicketPart(
                    ticket_id=t.id,
                    inventory_item_id=inv.id if inv else None,
                    name=name,
                    qty_needed=qty,
                )
            )
        session.commit()

    def add_log(
        t: MaintenanceTicket,
        kind: str,
        message: str,
        author: str | None = None,
        tz: str | None = None,
    ) -> None:
        session.add(
            MaintenanceTicketLog(
                ticket_id=t.id, kind=kind, author_email=author, message=message, tz=tz
            )
        )
        session.commit()

    # T1 — CNC vibration
    t1 = ticket(
        "TICKET-0001",
        "CNC-01 elevated vibration",
        cnc,
        "high",
        "open",
        2,
        sop_cnc,
        "spindle-bearing-service",
        what="The CNC mill is shaking more than it should. Left unaddressed it will "
        "produce out-of-spec parts and could fail unexpectedly.",
        exec_="Vibration on CNC-01 threatens scrap and an unplanned stop on Line 01. "
        "Estimated exposure ~$8k if it escalates to a bearing failure. A planned "
        "2-day intervention avoids that.",
        op="Vibration index 0.71 (> 0.6 limit). Pattern is consistent with worn "
        "angular-contact spindle bearings; tool balance verified OK. Schedule "
        "spindle bearing service per SOP-CNC-001 §4.",
        remediation="Replace both spindle bearings as a set, re-balance tooling, and "
        "confirm vibration index < 0.4 on warm-up. See @SOP-CNC-001.",
    )
    add_parts(
        t1,
        [
            (parts_inv["BRG-SPN-01"], "CNC spindle bearing", 2),
            (parts_inv["LUB-WAY-01"], "Way lubricant (1L)", 1),
        ],
    )
    add_log(
        t1,
        "system",
        "Ticket opened automatically from vibration rule (index 0.71 > 0.60).",
    )

    # T2 — Press overheating (tied to the seeded incident, acknowledged)
    t2 = ticket(
        "TICKET-0002",
        "PRESS-01 hydraulic overheating",
        press,
        "critical",
        "acknowledged",
        1,
        sop_press,
        "hydraulic-oil-service",
        what="The hydraulic press is running too hot. If it keeps overheating it will "
        "shut the line down and may damage the hydraulic system.",
        exec_="Critical: PRESS-01 overheating already caused a 95-minute stop "
        "(~$12.5k impact) and one delayed order. Immediate oil/cooler service "
        "protects delivery commitments.",
        op="Oil temperature peaked at 92°C (> 85°C limit). Root cause from RCA: cooler "
        "airflow restricted by debris. Replace oil + seal kit and clean cooler per "
        "SOP-PRESS-001 §3–4.",
        remediation="Replace hydraulic oil and seal kit, clean cooler fins, verify "
        "120 bar holds. See @SOP-PRESS-001.",
        incident_id=incident.id if incident else None,
        acknowledged=("maintenance@smartforge.com", "America/Detroit"),
    )
    add_parts(
        t2,
        [
            (parts_inv["SEAL-HYD-01"], "Hydraulic seal kit", 1),
            (hyd_oil, "Hydraulic oil", 2),
        ],
    )
    add_log(
        t2,
        "system",
        "Ticket opened from temperature rule (92°C > 85°C); linked to incident.",
    )
    add_log(
        t2,
        "acknowledgement",
        "Acknowledged by maintenance@smartforge.com",
        author="maintenance@smartforge.com",
        tz="America/Detroit",
    )
    add_log(
        t2,
        "note",
        "Need to order more of the hydraulic seal kit and oil before "
        "next PM. Following @SOP-PRESS-001 cooler-cleaning step; see "
        "related @TICKET-0001 for the CNC work this week.",
        author="maintenance@smartforge.com",
        tz="America/Detroit",
    )

    # T3 — Arm encoder fault (in progress)
    t3 = ticket(
        "TICKET-0003",
        "ARM-01 repeated E101 encoder fault",
        arm,
        "medium",
        "in_progress",
        3,
        sop_arm,
        "encoder-service",
        what="The robot arm keeps faulting and stopping. It needs a sensor replaced "
        "so it stops interrupting production.",
        exec_="Recurring E101 faults on ARM-01 cause short stoppages that nibble at "
        "OEE. A planned encoder swap removes the interruptions.",
        op="Three E101 (joint encoder) faults in 24h after re-homing. Replace joint "
        "encoder and re-master per SOP-ARM-001 §3. Encoder currently out of stock.",
        remediation="Replace joint encoder, re-master axis, verify repeatability "
        "< 0.05 mm. See @SOP-ARM-001.",
    )
    add_parts(t3, [(parts_inv["ENC-JNT-01"], "Robotic arm joint encoder", 1)])
    add_log(t3, "system", "Ticket opened from repeated-fault rule (3× E101 / 24h).")
    add_log(
        t3,
        "status_change",
        "Status changed open → in_progress",
        author="maintenance@smartforge.com",
    )

    # T4 — CNC PM overdue
    t4 = ticket(
        "TICKET-0004",
        "CNC-01 preventive maintenance overdue",
        cnc,
        "low",
        "open",
        7,
        sop_pm,
        "lubrication",
        what="Routine upkeep on the CNC mill is past due. Doing it now keeps the "
        "machine reliable and prevents bigger problems later.",
        exec_="Overdue PM raises downtime risk. Low cost, high return — schedule "
        "within the week.",
        op="PM overdue by 120 runtime hours. Lubricate ways and replace air filter "
        "per SOP-PM-001 §2–3.",
        remediation="Lubricate ways, replace air intake filter, inspect belts. "
        "See @SOP-PM-001.",
    )
    add_parts(
        t4,
        [
            (parts_inv["FLT-AIR-01"], "Air intake filter", 2),
            (parts_inv["LUB-WAY-01"], "Way lubricant (1L)", 2),
        ],
    )
    add_log(t4, "system", "Ticket opened from PM-overdue rule (+120h).")

    session.commit()
