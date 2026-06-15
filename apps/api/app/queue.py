"""Render-job queue on Google Cloud Pub/Sub.

The API publishes one message per render request; the worker process holds the
pull subscription. Ack deadline is 600s and the worker extends leases while a
render is in flight, so Veo's multi-minute generations don't cause redelivery.
"""
from __future__ import annotations

import json

from google.cloud import pubsub_v1

from app.config import Settings, get_settings


class RenderQueue:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._publisher = pubsub_v1.PublisherClient()
        self._topic_path = self._publisher.topic_path(
            self.settings.gcp_project_id, self.settings.pubsub_topic
        )

    def publish_render(self, job_id: str, tour_id: str, max_shots: int, dry_run: bool) -> str:
        payload = json.dumps(
            {
                "job_id": job_id,
                "tour_id": tour_id,
                "max_shots": max_shots,
                "dry_run": dry_run,
            }
        ).encode()
        future = self._publisher.publish(self._topic_path, payload)
        return future.result(timeout=30)
