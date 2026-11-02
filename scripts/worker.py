from codeintent.tasks import app, heartbeat

if __name__ == "__main__":
    heartbeat.func(0)
    app.run_worker(concurrency=1, queues=["imports", "maintenance"])
