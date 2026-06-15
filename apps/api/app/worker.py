"""Render worker — pulls jobs from Pub/Sub and runs the pipeline.

Run with:  python -m app.worker

One job at a time (flow control max_messages=1): renders are long and serial
submission respects rate limits. The streaming-pull client extends ack leases
automatically while a render is in flight. The job runs the continuous
frame-chained drone tour (pipeline2), not the old crossfade composite.
"""
from __future__ import annotations

import json
import signal
import sys

from google.cloud import pubsub_v1

from app.config import get_settings
from app.pipeline2.job import run_render_job


def main() -> None:
    settings = get_settings()
    subscriber = pubsub_v1.SubscriberClient()
    sub_path = subscriber.subscription_path(
        settings.gcp_project_id, settings.pubsub_subscription
    )

    def handle(message: pubsub_v1.subscriber.message.Message) -> None:
        try:
            payload = json.loads(message.data.decode())
            print(f"[worker] job {payload.get('job_id')} → tour {payload.get('tour_id')}")
            run_render_job(
                job_id=payload["job_id"],
                tour_id=payload["tour_id"],
                max_shots=int(payload.get("max_shots", 6)),
                dry_run=bool(payload.get("dry_run", False)),
            )
            message.ack()
            print(f"[worker] job {payload.get('job_id')} done")
        except json.JSONDecodeError:
            print("[worker] dropping malformed message")
            message.ack()
        except Exception as e:
            # run_render_job records failures in Firestore itself; ack so a
            # deterministic failure doesn't redeliver forever.
            print(f"[worker] job error: {e}")
            message.ack()

    flow = pubsub_v1.types.FlowControl(max_messages=1)
    future = subscriber.subscribe(sub_path, callback=handle, flow_control=flow)
    print(f"[worker] listening on {sub_path}")

    def shutdown(*_):
        print("[worker] shutting down")
        future.cancel()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        future.result()
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
