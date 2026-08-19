import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import data_file_tools as dft


class DummyApp:
    pass


def invoke(cmd):
    for name, detect, execute, _prio in dft.SKILLS:
        ctx = detect(cmd)
        if ctx is not None:
            return name, execute(DummyApp(), ctx)
    return None, None


SAMPLE_JSON = {
    "name": "Jarvis",
    "meta": {"version": 2, "tags": ["alpha", "beta"]},
    "items": [{"id": 1, "name": "one"}, {"id": 2, "name": "two"}],
    "count": 42,
}

SAMPLE_CSV = (
    "name,age,score\n"
    "Alice,30,91.5\n"
    "Bob,,78.0\n"
    "Cara,25,\n"
    "Dan,40,88.0\n"
    "Eve,29,95.5\n"
    "Frank,35,60.0\n"
    "Gina,31,84.0\n"
)


def make_png(path, w=1, h=1):
    pytest.importorskip("PIL")
    from PIL import Image

    Image.new("RGB", (w, h), color=(200, 10, 10)).save(path)
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(dft, "PROJECT_DIR", str(tmp_path))
    compact = tmp_path / "sample.json"
    compact.write_text(json.dumps(SAMPLE_JSON, separators=(",", ":")) + "\n")
    (tmp_path / "sample.csv").write_text(SAMPLE_CSV)
    (tmp_path / "many.csv").write_text(
        "grp,val\n" + "".join("g,%d\n" % i for i in range(7))
    )
    return tmp_path


def test_json_format_pretty_backup_and_key_count(env):
    p = env / "sample.json"
    original = p.read_text()
    name, reply = invoke("format json sample.json")
    assert name == "dt_json_format"
    text = p.read_text()
    assert text != original
    assert '"name": "Jarvis"' in text
    assert '\n  "meta"' in text
    bak = env / "sample.json.bak"
    assert bak.exists()
    assert bak.read_text() == original
    assert "4 top-level key(s)" in reply
    assert "sample.json.bak" in reply
    assert "sir" in reply


def test_json_format_prettify_alias_and_missing(env):
    name, _ = invoke("prettify sample.json")
    assert name == "dt_json_format"
    _, reply = invoke("format json ghost.json")
    assert "couldn't find" in reply and "sir." in reply


def test_json_query_dotted_paths_incl_array_index(env):
    _, reply = invoke("get meta.version from sample.json")
    assert "meta.version is 2, sir." in reply
    _, reply = invoke("get items.1.name from sample.json")
    assert "'two'" in reply
    name, reply = invoke("json sample.json key items.0.id")
    assert name == "dt_json_query"
    assert "items.0.id is 1" in reply


def test_json_query_type_summaries_for_dict_and_list(env):
    _, reply = invoke("get meta from sample.json")
    assert "a dict holding 2 key(s)" in reply
    assert "version" in reply and "tags" in reply
    _, reply = invoke("get items from sample.json")
    assert "a list holding 2 item(s)" in reply


def test_json_query_error_personas(env):
    _, reply = invoke("get nope.deep from sample.json")
    assert "no “nope.deep”" in reply and "sir." in reply
    _, reply = invoke("get items.5.id from sample.json")
    assert "past the end" in reply
    _, reply = invoke("get x from ghost.json")
    assert "couldn't find" in reply


def test_json_validate_ok_and_error_line(env):
    name, reply = invoke("validate json sample.json")
    assert name == "dt_json_validate"
    assert "valid JSON" in reply and "sir." in reply
    bad = env / "bad.json"
    bad.write_text('{\n"a": 1\n"b": 2\n}')
    _, reply = invoke("validate json bad.json")
    assert "isn't valid JSON" in reply
    assert "line 3" in reply


def test_csv_summarize_rows_types_stats_and_missing(env):
    name, reply = invoke("summarize csv sample.csv")
    assert name == "dt_csv_summarize"
    assert "7 data row(s)" in reply and "3 column(s)" in reply
    assert "- name: text, 0 missing" in reply
    assert "- age: int, 1 missing" in reply
    assert "min=25 max=40 mean=31.67" in reply
    assert "- score: float, 1 missing" in reply
    assert "min=60 max=95.5 mean=82.83" in reply
    _, reply = invoke("csv stats sample.csv")
    assert "3 column(s)" in reply
    _, reply = invoke("summarize csv ghost.csv")
    assert "couldn't find" in reply


def test_csv_filter_matches_and_pipe_rows(env):
    name, reply = invoke("csv sample.csv where name equals Dan")
    assert name == "dt_csv_filter"
    assert "1 matching row(s)" in reply
    assert "Dan|40|88.0" in reply


def test_csv_filter_case_insensitive_value_and_cap_at_five(env):
    _, reply = invoke("csv many.csv where grp equals G")
    assert "7 matching row(s)" in reply
    assert "|".join(["g", "0"]) in reply
    shown = [ln for ln in reply.splitlines() if ln.startswith("g|")]
    assert len(shown) == 5
    assert "2 more remain unshown" in reply


def test_csv_filter_no_match_and_unknown_column(env):
    _, reply = invoke("csv sample.csv where name equals Zed")
    assert "zero matches" in reply
    _, reply = invoke("csv sample.csv where nope equals 1")
    assert "can't find a “nope” column" in reply
    assert "available columns" in reply


def test_csv_to_json_writes_target_and_backups_existing(env):
    target = env / "sample.json"
    sentinel = '{"sentinel": true}\n'
    target.write_text(sentinel)
    name, reply = invoke("convert sample.csv to json")
    assert name == "dt_csv_to_json"
    records = json.loads(target.read_text())
    assert isinstance(records, list) and len(records) == 7
    assert records[0]["name"] == "Alice"
    assert "7 record(s)" in reply
    bak = env / "sample.json.bak"
    assert bak.exists() and bak.read_text() == sentinel


def test_img_info_reports_size_mode_format_bytes(env):
    make_png(env / "pix.png")
    name, reply = invoke("image info pix.png")
    assert name == "dt_img_info"
    assert "PNG" in reply
    assert "1x1 pixels" in reply
    assert "RGB mode" in reply
    import re as _re

    assert _re.search(r"\d+ bytes", reply)


def test_img_resize_backs_up_and_changes_dimensions(env):
    make_png(env / "pix.png", 4, 4)
    original = (env / "pix.png").read_bytes()
    name, reply = invoke("resize pix.png to 2x3")
    assert name == "dt_img_resize"
    from PIL import Image

    with Image.open(env / "pix.png") as im:
        assert im.size == (2, 3)
    bak = env / "pix.png.bak"
    assert bak.exists()
    with Image.open(bak) as im:
        assert im.size == (4, 4)
    assert bak.read_bytes() == original
    assert "2x3" in reply and "sir." in reply


def test_img_convert_png_to_jpg_creates_target_with_backup(env):
    make_png(env / "pix.png")
    existing = b"old jpg bytes"
    (env / "pix.jpg").write_bytes(existing)
    name, reply = invoke("convert pix.png to jpg")
    assert name == "dt_img_convert"
    from PIL import Image

    with Image.open(env / "pix.jpg") as im:
        assert im.format == "JPEG"
        assert im.size == (1, 1)
    assert (env / "pix.jpg.bak").read_bytes() == existing
    assert "pix.jpg" in reply and "JPG" in reply


def test_img_convert_same_extension_is_noop(env):
    make_png(env / "pix.png")
    _, reply = invoke("convert pix.png to png")
    assert "already a PNG" in reply


def test_pillow_offline_persona_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(dft, "PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(dft, "HAVE_PIL", False)
    (tmp_path / "pix.png").write_bytes(b"not really a png")
    for cmd in (
        "image info pix.png",
        "resize pix.png to 2x2",
        "convert pix.png to jpg",
    ):
        _, reply = invoke(cmd)
        assert "Pillow isn't installed" in reply
        assert "offline" in reply and "sir" in reply


def test_register_protocol_on_stub_brain():
    class StubBrain:
        def __init__(self):
            self.skills = []

        def register(self, name, detect, execute, priority=False):
            self.skills.append((name, detect, execute, priority))

    brain = StubBrain()
    dft.register(brain)
    names = [n for n, *_ in brain.skills]
    assert names == [
        "dt_json_format",
        "dt_json_query",
        "dt_json_validate",
        "dt_csv_summarize",
        "dt_csv_filter",
        "dt_csv_to_json",
        "dt_img_info",
        "dt_img_resize",
        "dt_img_convert",
    ]
    for _, detect, execute, prio in brain.skills:
        assert callable(detect) and callable(execute)
        assert prio is False


NOISE_COMMANDS = [
    "hello there",
    "what time is it",
    "tell me a joke",
    "open chrome",
    "resize the window",
    "convert this document to pdf",
    "validate my feelings",
    "summarize the article",
    "get me coffee from the kitchen",
    "run the tests",
]


@pytest.mark.parametrize("cmd", NOISE_COMMANDS)
def test_detector_noise_returns_none(cmd):
    for _name, detect, _execute, _prio in dft.SKILLS:
        assert detect(cmd) is None, cmd
