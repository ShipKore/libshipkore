"""Tests for the S3-compatible file store and its configuration."""

import io
import sys

import pytest

from libshipkore import files as files_module
from libshipkore.common.exceptions import NotFound, StorageError
from libshipkore.files import (
    FileStore,
    MemoryFileStore,
    S3FileStore,
    create_file_store,
)


class ClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeS3:
    """Just enough of a boto3 S3 client."""

    def __init__(self):
        self.objects = {}
        self.calls = []

    def put_object(self, Bucket, Key, Body, ContentType):
        self.calls.append(("put", Bucket, Key, ContentType))
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise ClientError("NoSuchKey")
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise ClientError("404")

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://s3.test/{Params['Bucket']}/{Params['Key']}?exp={ExpiresIn}"

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)


@pytest.fixture(params=["memory", "s3"])
def store(request):
    if request.param == "memory":
        return MemoryFileStore()
    return S3FileStore("bucket", prefix="pre/", client=FakeS3())


def test_roundtrip_exists_url_delete(store):
    assert store.exists("a.pdf") is False
    store.put("a.pdf", b"%PDF-1")
    assert store.exists("a.pdf") is True
    assert store.get("a.pdf") == b"%PDF-1"
    assert "a.pdf" in store.url("a.pdf", 60)
    store.delete("a.pdf")
    store.delete("a.pdf")  # a missing file is not an error
    assert store.exists("a.pdf") is False


def test_missing_file_raises_not_found(store):
    with pytest.raises(NotFound):
        store.get("nope.pdf")


def test_s3_prefix_content_type_and_expiry():
    client = FakeS3()
    store = S3FileStore("labels", prefix="eu/", client=client)
    store.put("x.pdf", b"1", content_type="application/pdf")
    assert client.calls == [("put", "labels", "eu/x.pdf", "application/pdf")]
    assert store.url("x.pdf", 120) == "https://s3.test/labels/eu/x.pdf?exp=120"


def test_s3_other_errors_are_not_hidden():
    client = FakeS3()
    client.head_object = lambda **kw: (_ for _ in ()).throw(ClientError("403"))
    with pytest.raises(ClientError):
        S3FileStore("b", client=client).exists("k")


def test_boto3_missing_gives_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)
    with pytest.raises(StorageError, match=r"libshipkore\[s3\]"):
        S3FileStore("bucket")


def test_s3_client_gets_endpoint_and_credentials(monkeypatch):
    seen = {}

    class FakeBoto3:
        @staticmethod
        def client(name, **kwargs):
            seen.update(name=name, **kwargs)
            return FakeS3()

    monkeypatch.setitem(sys.modules, "boto3", FakeBoto3)
    S3FileStore("b", endpoint_url="https://minio:9000", region="eu-1",
                access_key="AK", secret_key="SK")
    assert seen == {
        "name": "s3", "endpoint_url": "https://minio:9000",
        "region_name": "eu-1", "aws_access_key_id": "AK",
        "aws_secret_access_key": "SK",
    }


def test_create_file_store_specs(monkeypatch):
    assert create_file_store(None) is None
    assert isinstance(create_file_store("memory://"), MemoryFileStore)
    assert isinstance(create_file_store({"backend": "memory"}), MemoryFileStore)
    instance = MemoryFileStore()
    assert create_file_store(instance) is instance

    built = []
    monkeypatch.setattr(
        files_module, "S3FileStore",
        lambda *a, **k: built.append((a, k)) or "s3-store",
    )
    assert create_file_store("s3://my-bucket/some/prefix") == "s3-store"
    assert built[-1] == (("my-bucket",), {"prefix": "some/prefix/"})
    assert create_file_store({"backend": "s3", "bucket": "b"}) == "s3-store"
    assert built[-1] == ((), {"bucket": "b"})


def test_create_file_store_reads_the_environment(monkeypatch):
    monkeypatch.setenv("LIBSHIPKORE_FILES", "memory://")
    assert isinstance(create_file_store(), MemoryFileStore)


class CustomFiles(FileStore):
    def __init__(self, root):
        self.root = root

    def put(self, key, content, content_type="application/pdf"):
        pass

    def get(self, key):
        return b""

    def exists(self, key):
        return False

    def url(self, key, expires_in=3600):
        return key

    def delete(self, key):
        pass


def test_custom_file_backend_by_dotted_path():
    store = create_file_store(
        {"backend": "tests.test_files.CustomFiles", "root": "/x"}
    )
    assert isinstance(store, CustomFiles) and store.root == "/x"


@pytest.mark.parametrize("spec", ["ftp://x", 7, {"no": "backend"},
                                  {"backend": "nope.Missing"}])
def test_bad_file_specs_raise(spec):
    with pytest.raises(StorageError):
        create_file_store(spec)
