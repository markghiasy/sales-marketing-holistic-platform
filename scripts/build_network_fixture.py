"""Regenerate the deliberately fictional, shareable network demonstration."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path


def build():
    nodes = [
        {
            "id": "person:owner",
            "name": "Jordan Ellis",
            "kind": "person",
            "role": "Your network",
            "functions": ["Founder"],
        }
    ]
    people = [
        ("maya", "Maya Chen", "Accounting", "CFO & project adviser", "north"),
        ("priya", "Priya Shah", "Accounting", "Logistics finance specialist", "atlas"),
        ("alex", "Alex Morgan", "Operations", "Operations director", "atlas"),
        ("sam", "Sam Rivera", "Research", "University partnerships", "uni"),
        ("nora", "Nora Bennett", "Investment", "Investment partner", "north"),
        ("leo", "Leo Park", "Sales", "New inbound contact", "atlas"),
        ("alex2", "Alex Morgan", "Research", "Research fellow · different person", "uni"),
        ("oliver", "Oliver Reed", "Operations", "Supply chain adviser", "atlas"),
        ("ella", "Ella Brooks", "Legal", "Commercial counsel", "north"),
        ("amir", "Amir Khan", "Engineering", "Platform engineering", "atlas"),
        ("grace", "Grace Liu", "Research", "Applied AI researcher", "uni"),
        ("ben", "Ben Walsh", "Sales", "Partnerships lead", "north"),
        ("sofia", "Sofia Costa", "Design", "Service designer", "atlas"),
        ("theo", "Theo Martin", "Investment", "Venture analyst", "north"),
        ("aisha", "Aisha Rahman", "Research", "Industry research lead", "uni"),
        ("jack", "Jack Wilson", "Operations", "Warehouse systems", "atlas"),
        ("lily", "Lily James", "Accounting", "Financial controller", "north"),
        ("daniel", "Daniel Kim", "Engineering", "Data engineering", "uni"),
        ("ruby", "Ruby Thomas", "Design", "Product researcher", "uni"),
        ("ethan", "Ethan Scott", "Legal", "Technology contracts", "north"),
        ("isla", "Isla Wright", "Sales", "Enterprise accounts", "atlas"),
        ("noah", "Noah Patel", "Engineering", "Integration engineer", "atlas"),
        ("chloe", "Chloe Evans", "Operations", "Program manager", "uni"),
        ("max", "Max Turner", "Investment", "Angel investor", "north"),
    ]
    for key, name, function, role, org in people:
        nodes.append(
            {
                "id": "person:" + key,
                "name": name,
                "kind": "person",
                "role": role,
                "functions": [function],
                "cluster": org,
                "coverage": "partial" if key == "alex2" else "observed channels only",
            }
        )
    for key, name, kind, role in [
        ("north", "Northline Advisory", "organization", "Finance & investment"),
        ("atlas", "Atlas Logistics", "organization", "Logistics & operations"),
        ("uni", "Coastal University", "organization", "Research & industry"),
        ("harbour", "Harbour expansion", "project", "Logistics finance & delivery"),
        ("bridge", "Research bridge", "project", "Industry research partnership"),
    ]:
        nodes.append(
            {
                "id": ("org:" if kind == "organization" else "project:") + key,
                "name": name,
                "kind": kind,
                "role": role,
                "functions": [],
            }
        )
    claims, evidence, messages = [], [], []
    labels = {n["id"]: n["name"] for n in nodes}

    def claim(
        key,
        source,
        target,
        relation,
        text,
        *,
        observed="2026-01-15T09:00:00Z",
        valid="2026-01-01T00:00:00Z",
        status="confirmed",
        **extra,
    ):
        eid = "evidence:" + key
        evidence.append(
            {
                "id": eid,
                "channel": "outlook",
                "at": observed,
                "from": labels[source],
                "subject": "Fictional relationship record",
                "text": text,
                "synthetic": True,
            }
        )
        claims.append(
            {
                "id": key,
                "source": source,
                "target": target,
                "relation": relation,
                "status": status,
                "origin": "manual",
                "scope": "ego_relative" if "person:owner" in (source, target) else "world",
                "observed_at": observed,
                "valid_from": valid,
                "valid_to": None,
                "evidence_ids": [eid],
                **extra,
            }
        )

    for i, (key, name, function, role, org) in enumerate(people):
        if key != "alex":
            claim(
                "job-" + key,
                "person:" + key,
                "org:" + org,
                "Works at",
                f"I am {name}, working at {labels['org:' + org]} in {function.lower()}.",
            )
        claim(
            "contact-" + key,
            "person:owner",
            "person:" + key,
            "In contact",
            f"Jordan and {name} exchanged contact details for industry work.",
        )
        if key == "alex2":
            continue
        ages = (
            [110, 140, 170, 200, 230, 260]
            if key == "maya"
            else ([2] if key == "priya" else [4 + i * 2, 25 + i * 3, 70 + i * 2])
        )
        if key == "leo":
            ages = list(range(1, 20))
        for j, age in enumerate(ages):
            when = datetime(2026, 9, 27, 9, tzinfo=UTC) - timedelta(days=age)
            for direction in ["in"] if key == "leo" else ["in", "out"]:
                messages.append(
                    {
                        "id": f"msg:{key}:{j}:{direction}",
                        "contact_id": "person:" + key,
                        "channel": "whatsapp" if j % 2 else "outlook",
                        "direction": direction,
                        "direct": True,
                        "at": (
                            when + timedelta(minutes=5 if direction == "out" else 0)
                        ).isoformat(),
                        "text": f"Fictional exchange with {name} about {function.lower()} and shared work.",
                    }
                )
    claim(
        "job-alex-old",
        "person:alex",
        "org:north",
        "Works at",
        "I am leaving Northline at the end of July.",
        valid="2026-01-01T00:00:00Z",
        valid_to="2026-08-01T00:00:00Z",
        end_observed_at="2026-09-03T09:00:00Z",
    )
    # The original evidence must not disclose the later correction.
    evidence[-1]["text"] = "I work at Northline Advisory as an operations adviser."
    claim(
        "job-alex-new",
        "person:alex",
        "org:atlas",
        "Works at",
        "I joined Atlas on 1 August, after leaving my Northline employee role at the end of July.",
        observed="2026-09-03T09:00:00Z",
        valid="2026-08-01T00:00:00Z",
    )
    claim(
        "job-alex-advisor",
        "person:alex",
        "org:north",
        "Advises",
        "I still advise Northline one day each month alongside my role at Atlas.",
        observed="2026-09-03T09:00:00Z",
        valid="2026-08-01T00:00:00Z",
    )
    for key in ["owner", "maya", "priya", "alex", "oliver", "jack"]:
        claim(
            "harbour-" + key,
            "person:" + key,
            "project:harbour",
            "Project member",
            f"{labels['person:' + key]} is on the Harbour expansion working group.",
        )
    for key in ["owner", "sam", "grace", "aisha", "daniel", "chloe"]:
        claim(
            "bridge-" + key,
            "person:" + key,
            "project:bridge",
            "Project member",
            f"{labels['person:' + key]} is part of Research bridge.",
        )
    claim(
        "client-maya",
        "person:maya",
        "person:owner",
        "Client of",
        "Jordan, our advisory team would like to engage you for the project discovery work.",
    )
    claim(
        "collab-maya",
        "person:owner",
        "person:maya",
        "Collaborates with",
        "Maya and I co-designed the Harbour finance workshop.",
    )
    claim(
        "intro-sam",
        "person:sam",
        "person:priya",
        "Introduced",
        "Jordan, please meet Priya. She has led finance work for logistics operators.",
    )
    claim(
        "intro-pending",
        "person:nora",
        "person:priya",
        "Possible introduction",
        "I think Nora might know Priya; this has not been checked.",
        status="pending",
    )
    claim(
        "rejected-role",
        "person:leo",
        "person:maya",
        "Reports to",
        "Unverified claim rejected in the demo review.",
        status="rejected",
    )
    next(c for c in claims if c["id"] == "job-alex-old")["correction_evidence_ids"] = [
        "evidence:job-alex-new"
    ]
    profiles = []
    for key, name, function, _role, _org in people:
        attributes = [("function", function, f"My professional focus is {function.lower()}.")]
        if key in ("maya", "priya"):
            attributes.append(
                (
                    "industry",
                    "Logistics",
                    "I have led finance reviews and accounting work for logistics operators.",
                )
            )
        for kind, label, text in attributes:
            aid = f"profile:{key}:{kind}"
            eid = f"evidence:{aid}"
            evidence.append(
                {
                    "id": eid,
                    "channel": "outlook",
                    "at": "2026-01-15T09:00:00Z",
                    "from": name,
                    "subject": "Fictional professional introduction",
                    "text": f"I am {name}. {text}",
                    "synthetic": True,
                }
            )
            profiles.append(
                {
                    "id": aid,
                    "person_id": "person:" + key,
                    "kind": kind,
                    "label": label,
                    "status": "confirmed",
                    "observed_at": "2026-01-15T09:00:00Z",
                    "valid_from": "2026-01-01T00:00:00Z",
                    "valid_to": None,
                    "evidence_ids": [eid],
                }
            )
    return {
        "owner_id": "person:owner",
        "nodes": nodes,
        "claims": claims,
        "evidence": evidence,
        "messages": messages,
        "profile_assertions": profiles,
    }


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "tests/fixtures/network_demo.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build(), indent=2), encoding="utf-8")
    print(target)
