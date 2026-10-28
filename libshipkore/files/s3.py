from libshipkore.common.exceptions import NotFound, StorageError
from .base import FileStore

MISSING = ("NoSuchKey", "404", "NotFound")


class S3FileStore(FileStore):
    """
    Any S3-compatible object store: AWS S3, MinIO, Cloudflare R2,
    DigitalOcean Spaces, Ceph. Needs `pip install libshipkore[s3]`.

    Point it at a non-AWS service with endpoint_url. Without access_key and
    secret_key the standard AWS credential chain (environment, profile, IAM
    role) is used. prefix is prepended to every key. A ready-made client
    can be passed as `client`, which is also how the tests run offline.
    """

    def __init__(self, bucket, prefix="", endpoint_url=None, region=None,
                 access_key=None, secret_key=None, client=None):
        self.bucket = bucket
        self.prefix = prefix
        if client is None:
            try:
                import boto3
            except ImportError:
                raise StorageError(
                    "S3FileStore needs boto3: pip install libshipkore[s3]"
                )
            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
            )
        self.client = client

    def _key(self, key):
        return self.prefix + key

    def put(self, key, content, content_type="application/pdf"):
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._key(key),
            Body=content,
            ContentType=content_type,
        )

    def get(self, key):
        try:
            return self.client.get_object(
                Bucket=self.bucket, Key=self._key(key)
            )["Body"].read()
        except Exception as error:
            code = getattr(error, "response", {}).get("Error", {}).get("Code")
            if code in MISSING:
                raise NotFound(f"no stored file '{key}'")
            raise

    def exists(self, key):
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(key))
        except Exception as error:
            code = getattr(error, "response", {}).get("Error", {}).get("Code")
            if code in MISSING:
                return False
            raise
        return True

    def url(self, key, expires_in=3600):
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._key(key)},
            ExpiresIn=expires_in,
        )

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=self._key(key))
