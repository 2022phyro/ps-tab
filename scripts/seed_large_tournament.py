"""Script to seed a large realistic tournament dataset for performance benchmarking.

Creates:
- 1 Tournament ('benchmark')
- 100 Institutions
- 500 Speakers (assigned across Novice/Open divisions)
- 150 Judges (with chair credentials & secondary affiliations)
- 25 Officials with RBAC roles
"""

import asyncio
import random
import time
from sqlalchemy import select
from kwuo.core.database import async_session_factory
from kwuo.core.security import hash_password
from kwuo.models.tournament import (
    Tournament,
    TournamentStatus,
    LocationType,
    Division,
    Institution,
    Participant,
    SpeakerProfile,
    JudgeProfile,
    OfficialProfile,
    ParticipantStatus,
    ParticipantInstitution,
    OfficialRole,
    Role,
)
from kwuo.models.user import User

FIRST_NAMES = [
    "Ada", "Chidi", "Olumide", "Ngozi", "Emeka", "Fatima", "Ibrahim", "Zainab", "Tunde", "Amina",
    "Kwame", "Kofi", "Akua", "Yaw", "Esi", "Liam", "Emma", "Noah", "Olivia", "Ethan",
    "Sophia", "Lucas", "Mia", "Aiden", "Isabella", "James", "Ava", "Alexander", "Charlotte", "Daniel",
    "Elena", "Mateo", "Camila", "Santiago", "Sofia", "Yuki", "Haruto", "Yui", "Souta", "Hina",
    "Arjun", "Ananya", "Rohan", "Priya", "Dev", "Isha", "Chen", "Wei", "Mei", "Jun"
]

LAST_NAMES = [
    "Okafor", "Adeyemi", "Balogun", "Eze", "Danjuma", "Bello", "Mensah", "Asante", "Osei", "Boateng",
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
    "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson",
    "Tanaka", "Sato", "Suzuki", "Takahashi", "Watanabe", "Sharma", "Patel", "Verma", "Rao", "Gupta"
]

INST_PREFIXES = [
    "University of", "Federal University of", "State University of", "Institute of",
    "College of", "Academy of", "St. Jude's", "Heritage", "Metropolitan", "Imperial"
]

INST_NAMES = [
    "Lagos", "Ibadan", "Accra", "Nairobi", "Cape Town", "Cairo", "Johannesburg", "Oxford", "Cambridge", "Harvard",
    "Toronto", "Sydney", "Melbourne", "Edinburgh", "Manchester", "Bristol", "London", "Chicago", "Boston", "Austin",
    "Dublin", "Singapore", "Tokyo", "Seoul", "Beijing", "Delhi", "Mumbai", "Kigali", "Kampala", "Dakar",
    "Abuja", "Enugu", "Benin", "Jos", "Calabar", "Port Harcourt", "Kumasi", "Pretoria", "Durban", "Alexandria"
]

REGIONS = ["Africa", "Europe", "Americas", "Asia-Pacific", "Middle East"]
COUNTRIES = ["Nigeria", "Ghana", "Kenya", "South Africa", "United Kingdom", "United States", "Canada", "Australia", "India", "Japan"]


async def seed_benchmark_tournament():
    print("🚀 Starting large tournament benchmark seeding...")
    start_time = time.perf_counter()

    async with async_session_factory() as session:
        # 1. Ensure a benchmark organizer exists
        stmt_user = select(User).where(User.email == "benchmark_admin@kwuo.com")
        res_u = await session.execute(stmt_user)
        user = res_u.scalar_one_or_none()
        if not user:
            user = User(
                email="benchmark_admin@kwuo.com",
                first_name="Benchmark",
                last_name="Administrator",
                password_hash=hash_password("BenchmarkAdmin123!"),
                is_admin=True,
                is_verified=True,
            )
            session.add(user)
            await session.flush()

        # 2. Check if benchmark tournament exists
        slug = "benchmark"
        stmt_t = select(Tournament).where(Tournament.slug == slug)
        res_t = await session.execute(stmt_t)
        tournament = res_t.scalar_one_or_none()

        if tournament:
            print(f"⚠️  Tournament '{slug}' already exists. Skipping recreation.")
            return

        print(f"Creating tournament '{slug}'...")
        tournament = Tournament(
            name="2026 National Forensic Championship",
            slug=slug,
            description="Benchmark tournament containing 500 speakers, 150 adjudicators, and 100 institutions.",
            status=TournamentStatus.ACTIVE,
            location_type=LocationType.HYBRID,
            timezone="Africa/Lagos",
            organizer_id=user.id,
        )
        session.add(tournament)
        await session.flush()

        # 3. Divisions
        div_open = Division(tournament_id=tournament.id, name="Open", description="Open tier")
        div_novice = Division(tournament_id=tournament.id, name="Novice", description="Novice tier")
        session.add_all([div_open, div_novice])
        await session.flush()
        divisions = [div_open, div_novice]

        # 4. Create 100 Institutions in bulk
        print("Seeding 100 institutions...")
        institutions = []
        for i in range(100):
            p = random.choice(INST_PREFIXES)
            n = random.choice(INST_NAMES)
            name = f"{p} {n} #{i + 1}"
            code = f"INS{i + 1:03d}"
            country = random.choice(COUNTRIES)
            region = random.choice(REGIONS)
            inst = Institution(
                tournament_id=tournament.id,
                name=name,
                name_normalized=name.lower(),
                code=code,
                country=country,
                region=region,
            )
            institutions.append(inst)

        session.add_all(institutions)
        await session.flush()

        # 5. Create 500 Speakers in bulk
        print("Seeding 500 speakers...")
        participants_to_add = []
        speaker_profiles_to_add = []

        for i in range(500):
            first = random.choice(FIRST_NAMES)
            last = random.choice(LAST_NAMES)
            inst = random.choice(institutions)
            part = Participant(
                tournament_id=tournament.id,
                name=f"{first} {last}",
                email=f"speaker_{i + 1}_{tournament.id[:6]}@benchmark.kwuo.test",
                institution_id=inst.id,
                status=ParticipantStatus.CHECKED_IN if i % 4 != 0 else ParticipantStatus.REGISTERED,
            )
            part.divisions = [random.choice(divisions)]
            session.add(part)
            participants_to_add.append(part)

        await session.flush()

        for part in participants_to_add:
            sp = SpeakerProfile(
                participant_id=part.id,
                pronouns=random.choice(["they/them", "she/her", "he/him", ""]),
            )
            session.add(sp)

        await session.flush()

        # 6. Create 150 Judges in bulk
        print("Seeding 150 adjudicators...")
        judges_parts = []
        for i in range(150):
            first = random.choice(FIRST_NAMES)
            last = random.choice(LAST_NAMES)
            inst = random.choice(institutions)
            part = Participant(
                tournament_id=tournament.id,
                name=f"{first} {last}",
                email=f"judge_{i + 1}_{tournament.id[:6]}@benchmark.kwuo.test",
                institution_id=inst.id,
                status=ParticipantStatus.CHECKED_IN if i % 5 != 0 else ParticipantStatus.REGISTERED,
            )
            part.divisions = divisions  # can judge both
            session.add(part)
            judges_parts.append(part)

        await session.flush()

        for i, part in enumerate(judges_parts):
            jp = JudgeProfile(
                participant_id=part.id,
                is_chair_eligible=(i % 3 == 0),
                is_reserve=(i % 10 == 0),
                is_independent=(i % 8 == 0),
                test_score=round(random.uniform(6.5, 9.8), 1),
                cv_score=round(random.uniform(6.0, 9.5), 1),
            )
            session.add(jp)

            # Add a secondary affiliation for some judges (institutional clash)
            if i % 3 == 0:
                other_inst = random.choice(institutions)
                if other_inst.id != part.institution_id:
                    aff = ParticipantInstitution(
                        participant_id=part.id,
                        institution_id=other_inst.id,
                        tie_type="alumni",
                    )
                    session.add(aff)

        await session.flush()

        # 7. Create 25 Staff / Officials
        print("Seeding 25 staff & tab room officials...")
        roles = []
        for r_name in ["Tab Director", "Clerk", "Equity Officer", "Runner"]:
            role = Role(tournament_id=tournament.id, name=r_name, is_system=False)
            session.add(role)
            roles.append(role)
        await session.flush()

        for i in range(25):
            first = random.choice(FIRST_NAMES)
            last = random.choice(LAST_NAMES)
            inst = random.choice(institutions)
            part = Participant(
                tournament_id=tournament.id,
                name=f"{first} {last}",
                email=f"staff_{i + 1}_{tournament.id[:6]}@benchmark.kwuo.test",
                institution_id=inst.id,
                status=ParticipantStatus.ACTIVE,
            )
            session.add(part)
            await session.flush()

            off = OfficialProfile(
                participant_id=part.id,
                role=random.choice(list(OfficialRole)),
                title="Tab Staff",
            )
            off.roles = [random.choice(roles)]
            session.add(off)

        await session.commit()

        dur = time.perf_counter() - start_time
        print(f"✅ Seeding complete in {dur:.2f}s! Benchmark tournament ready at slug 'benchmark'.")


if __name__ == "__main__":
    asyncio.run(seed_benchmark_tournament())
