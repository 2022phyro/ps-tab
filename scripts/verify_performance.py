"""Script to benchmark and verify query counts and response latency on the benchmark tournament."""

import asyncio
import logging
import time
import httpx

# Silence verbose SQL logs so we get a clean summary table
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

from kwuo.main import app
from kwuo.core.database import async_session_factory
from kwuo.core.security import create_official_token
from kwuo.models.tournament import Tournament, Participant, OfficialProfile
from sqlalchemy import select
from sqlalchemy.orm import selectinload


async def run_benchmark():
    async with async_session_factory() as session:
        # Fetch the benchmark tournament
        t_stmt = select(Tournament).where(Tournament.slug == "benchmark")
        tournament = (await session.execute(t_stmt)).scalar_one()

        # Fetch an official for admin cookie auth
        off_stmt = (
            select(OfficialProfile)
            .join(Participant, Participant.id == OfficialProfile.participant_id)
            .where(Participant.tournament_id == tournament.id)
            .options(selectinload(OfficialProfile.participant))
        )
        official_profile = (await session.execute(off_stmt)).scalars().first()
        auth_token = create_official_token(
            official_id=official_profile.id,
            participant_id=official_profile.participant_id,
            tournament_id=tournament.id,
            role=official_profile.role.value if official_profile.role else "tab",
        )

    transport = httpx.ASGITransport(app=app)
    headers = {"Host": "benchmark.localhost"}
    cookies = {f"kwuo_off_{tournament.id}": auth_token}

    endpoints = [
        ("GET", "/", "Tenant Overview Home"),
        ("GET", "/participants", "Public Participants (Page 1, 50 rows)"),
        ("GET", "/participants?page=2", "Public Participants (Page 2, 50 rows)"),
        ("GET", "/participants?q=Okafor", "Public Participants (Search query)"),
        ("GET", "/admin", "Admin Control Center Hub"),
        ("GET", "/admin/speakers", "Admin Speakers Roster (Page 1)"),
        ("GET", "/admin/speakers?q=Amina", "Admin Speakers (Search filter)"),
        ("GET", "/admin/judges", "Admin Judges Roster (Page 1)"),
        ("GET", "/admin/institutions", "Admin Institutions Roster"),
        ("GET", "/admin/settings", "Admin Tournament Settings"),
        ("GET", "/admin/rubric", "Admin Scoring Rubric"),
    ]

    print("\n" + "=" * 80)
    print(f"{'Endpoint':<40} | {'Status':<6} | {'Queries':<8} | {'Latency':<10} | {'Server-Timing'}")
    print("=" * 80)

    async with httpx.AsyncClient(transport=transport, base_url="http://benchmark.localhost") as client:
        # Warmup
        await client.get("/", headers=headers)

        for method, path, desc in endpoints:
            t0 = time.perf_counter()
            resp = await client.get(path, headers=headers, cookies=cookies)
            elapsed_ms = (time.perf_counter() - t0) * 1000

            q_count = resp.headers.get("X-Query-Count", "N/A")
            timing = resp.headers.get("Server-Timing", "N/A")

            print(f"{desc:<40} | {resp.status_code:<6} | {q_count:<8} | {elapsed_ms:>6.2f}ms   | {timing}")
            assert resp.status_code == 200, f"Expected 200 on {path}, got {resp.status_code}"

    print("=" * 80)
    print("🎯 All benchmark requests completed successfully!\n")


if __name__ == "__main__":
    asyncio.run(run_benchmark())
