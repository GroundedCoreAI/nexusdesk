import asyncio

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from agent_platform.core_platform.platform_services.persistence.store import DomainError


class S3Archive:
    """Thin boto3 wrapper with per-profile credentials.

    ``profile`` selects a credential set. ``skill`` points at the Skill package
    bucket and falls back field by field to the knowledge bucket, so an
    existing single-bucket deployment keeps working after the Skill library
    starts storing archives.
    """

    def __init__(self, settings, profile: str = "knowledge"):
        self.settings = settings
        self.profile = profile

    async def put(self, key, content, content_type: str = "application/octet-stream"):
        bucket = self._resolve()[1]

        def upload():
            client = self._client()
            try:
                client.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=content,
                    ContentType=content_type,
                )
            finally:
                client.close()

        await asyncio.to_thread(upload)
        return {"bucket": bucket, "key": key}

    async def get(self, key) -> bytes:
        bucket = self._resolve()[1]

        def download() -> bytes:
            client = self._client()
            try:
                response = client.get_object(Bucket=bucket, Key=key)
                try:
                    return response["Body"].read()
                finally:
                    response["Body"].close()
            finally:
                client.close()

        try:
            return await asyncio.to_thread(download)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in ("NoSuchKey", "404", "NotFound"):
                raise DomainError("skill_package_missing", 404) from None
            raise DomainError("s3_unavailable", 503) from None
        except BotoCoreError:
            raise DomainError("s3_unavailable", 503) from None

    async def delete(self, key) -> None:
        bucket = self._resolve()[1]

        def remove():
            client = self._client()
            try:
                client.delete_object(Bucket=bucket, Key=key)
            finally:
                client.close()

        try:
            await asyncio.to_thread(remove)
        except (ClientError, BotoCoreError):
            # Deletion of an immutable, digest-addressed object is best effort:
            # a leftover blob is garbage, never a correctness problem.
            return

    def configured(self) -> bool:
        try:
            self._resolve()
        except DomainError:
            return False
        return True

    def _resolve(self):
        s = self.settings
        if self.profile == "skill":
            endpoint = s.skill_s3_endpoint or s.knowledge_s3_endpoint
            bucket = s.skill_s3_bucket or s.knowledge_s3_bucket
            access = s.skill_s3_access_key or s.knowledge_s3_access_key
            secret = s.skill_s3_secret_key or s.knowledge_s3_secret_key
        else:
            endpoint = s.knowledge_s3_endpoint
            bucket = s.knowledge_s3_bucket
            access = s.knowledge_s3_access_key
            secret = s.knowledge_s3_secret_key
        if not bucket or not access or not secret:
            raise DomainError("s3_not_configured", 503)
        return endpoint, bucket, access, secret

    def _client(self):
        endpoint, _bucket, access, secret = self._resolve()
        return boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access.get_secret_value(),
            aws_secret_access_key=secret.get_secret_value(),
            region_name="us-east-1",
            config=Config(
                connect_timeout=5,
                read_timeout=30,
                retries={"max_attempts": 1},
                s3={"addressing_style": "path"},
            ),
        )
