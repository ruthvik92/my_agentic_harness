"""Trusted read-only hardware sampling; model commands never access host GPUs."""

import asyncio
from datetime import UTC, datetime

import httpx


async def sample():
    data = {"timestamp_utc": datetime.now(UTC).isoformat(), "gpus": None, "ollama_ps": None}
    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi",
            "--query-gpu=index,name,memory.used,memory.total,temperature.gpu,power.draw,utilization.gpu",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), 5)
        except BaseException:
            proc.kill()
            await proc.wait()
            raise
        if proc.returncode == 0:
            data["gpus"] = []
            for line in out.decode().splitlines():
                values = [v.strip() for v in line.split(",")]
                data["gpus"].append(
                    dict(
                        zip(
                            (
                                "index",
                                "name",
                                "memory_used_mib",
                                "memory_total_mib",
                                "temperature_c",
                                "power_w",
                                "utilization_percent",
                            ),
                            values,
                            strict=True,
                        )
                    )
                )
    except (OSError, TimeoutError, ValueError):
        pass
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            response = await client.get("http://127.0.0.1:11434/api/ps")
            response.raise_for_status()
            data["ollama_ps"] = response.json()
    except (httpx.HTTPError, ValueError):
        pass
    return data


async def monitor(samples, stop):
    while not stop.is_set():
        samples.append(await sample())
        try:
            await asyncio.wait_for(stop.wait(), 2)
        except TimeoutError:
            pass
