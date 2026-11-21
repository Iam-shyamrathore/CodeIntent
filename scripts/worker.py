"""The worker: one Procrastinate worker for checks, scans and maintenance, and one for the ecosystem graph.

Ecosystem jobs only call deps.dev, OSV.dev and Neo4j over HTTP, so they run four at a time without slowing
pull request checks, which keep their own two slots.
"""

import asyncio
import signal

from codeintent.tasks import app, heartbeat


async def main() -> None:
    async with app.open_async():
        workers = asyncio.gather(
            app.run_worker_async(
                name="main",
                concurrency=2,
                queues=["investigations", "imports", "pulls", "scans", "maintenance"],
                install_signal_handlers=False,
            ),
            app.run_worker_async(
                name="ecosystem",
                concurrency=4,
                queues=["ecosystem"],
                install_signal_handlers=False,
            ),
        )
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, workers.cancel)
        try:
            await workers
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    heartbeat.func(0)
    asyncio.run(main())
