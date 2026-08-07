from app.services.manifest import load_manifest, preview_manifest


class FakeDb:
    def scalar(self, _query):
        return None


def test_manifest_accepts_title_only_as_pending_source():
    entries = load_manifest("sources:\n  - title: 待补充的文件\n    category: 政策法规\n".encode())
    report = preview_manifest(FakeDb(), entries)
    assert report.valid == 1
    assert report.items[0].action == "pending_source"


def test_manifest_rejects_invalid_root():
    try:
        load_manifest(b"title: wrong")
    except ValueError as exc:
        assert "sources" in str(exc)
    else:
        raise AssertionError("invalid manifest should fail")

