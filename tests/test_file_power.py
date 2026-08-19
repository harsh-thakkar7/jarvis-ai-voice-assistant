import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import file_power as fp


class DummyApp:
    pass


def invoke(cmd):
    for name, detect, execute, _prio in fp.SKILLS:
        ctx = detect(cmd)
        if ctx is not None:
            return name, execute(DummyApp(), ctx)
    return None, None


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(fp, "PROJECT_DIR", str(tmp_path))
    (tmp_path / "a.txt").write_text("alpha\nbravo\ncharlie\ndelta\necho\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("NEEDLE one\nplain line\nNEEDLE two\n")
    deep = sub / "deep"
    deep.mkdir()
    (deep / "c.txt").write_text("deep NEEDLE here\n")
    hidden = tmp_path / "junk" / ".venv"
    hidden.mkdir(parents=True)
    (hidden / "x.txt").write_text("NEEDLE hidden\n")
    return tmp_path


def make_big(env, name="big.txt", n=70):
    (env / name).write_text(
        "".join("line%03d\n" % i for i in range(1, n + 1))
    )
    return env / name


def test_head_numbering(env):
    name, reply = invoke("first 3 lines of a.txt")
    assert name == "fp_read_head"
    assert "1 | alpha" in reply
    assert "2 | bravo" in reply
    assert "3 | charlie" in reply
    assert "4 |" not in reply


def test_head_default_and_caps_at_60(env):
    make_big(env)
    _, reply = invoke("head big.txt")
    assert "60 | line060" in reply
    assert "61 |" not in reply
    assert "trimmed" in reply and "sir" in reply


def test_tail_numbering_and_cap(env):
    make_big(env)
    name, reply = invoke("last 2 lines of big.txt")
    assert name == "fp_read_tail"
    assert "69 | line069" in reply
    assert "70 | line070" in reply
    assert "1 |" not in reply
    _, reply = invoke("tail big.txt")
    assert "trimmed" in reply


def test_range_inclusive_and_validation(env):
    name, reply = invoke("lines 2 to 4 of a.txt")
    assert name == "fp_read_range"
    assert "2 | bravo" in reply
    assert "4 | delta" in reply
    assert "1 | alpha" not in reply
    assert "5 | echo" not in reply
    _, reply = invoke("lines 9 to 12 of a.txt")
    assert "beyond the end" in reply


def test_full_read_and_binary_refusal(env):
    name, reply = invoke("show contents of a.txt")
    assert name == "fp_read_full"
    for word in ("alpha", "bravo", "charlie", "delta", "echo"):
        assert word in reply
    (env / "blob.dat").write_bytes(b"\x00\x01binary")
    _, reply = invoke("cat blob.dat")
    assert "binary" in reply
    assert "bytes" in reply
    assert "\x00" not in reply


def test_write_creates_parents_and_converts_literal_newlines(env):
    name, reply = invoke("write file fresh/dir/nl.txt with: l1\\nl2")
    assert name == "fp_write_file"
    p = env / "fresh" / "dir" / "nl.txt"
    assert p.read_text() == "l1\nl2"
    assert "bytes" in reply and "line(s)" in reply


def test_write_overwrite_backs_up(env, tmp_path):
    (env / "o.txt").write_text("old stuff\n")
    _, reply = invoke("overwrite o.txt with: new stuff")
    assert (env / "o.txt").read_text() == "new stuff"
    bak = env / "o.txt.bak"
    assert bak.exists() and bak.read_text() == "old stuff\n"
    assert "backup" in reply.lower()


def test_write_refuses_protected(env):
    name, reply = invoke("write file /System/jarvis_pwn.txt with: hi")
    assert name == "fp_write_file"
    assert "protected" in reply.lower() or "afraid" in reply.lower()
    assert not os.path.exists("/System/jarvis_pwn.txt")


def test_append_creates_when_missing(env):
    _, reply = invoke("append hello again to brand_new.txt")
    p = env / "brand_new.txt"
    assert p.exists() and "hello again" in p.read_text()
    assert "did not exist" in reply.lower() or "created" in reply.lower()
    _, _ = invoke("append second line to brand_new.txt")
    lines = p.read_text().splitlines()
    assert lines == ["hello again", "second line"]


def test_replace_counts_quotes_zero_match_backup(env):
    (env / "q.txt").write_text("say hello world now, hello world\n")
    _, reply = invoke("replace 'hello world' with 'hi there' in q.txt")
    q = env / "q.txt"
    assert q.read_text() == "say hi there now, hi there\n"
    assert "2 replacement" in reply
    assert (env / "q.txt.bak").exists()
    _, reply = invoke("replace zebra with lion in q.txt")
    assert "0 replacements" in reply and "nothing matched" in reply


def test_replace_double_quoted(env):
    (env / "q2.txt").write_text("keep a b end\n")
    invoke('replace "a b" with "x y" in q2.txt')
    assert (env / "q2.txt").read_text() == "keep x y end\n"


def test_insert_after_line_semantics(env):
    name, reply = invoke("add 'NEWLINE' after line 2 in a.txt")
    assert name == "fp_insert_line"
    assert (env / "a.txt").read_text().splitlines() == [
        "alpha",
        "bravo",
        "NEWLINE",
        "charlie",
        "delta",
        "echo",
    ]
    _, reply = invoke("insert 'TOP' at line 1 in a.txt")
    assert (env / "a.txt").read_text().startswith("TOP\n")


def test_insert_bounds_checked(env):
    _, reply = invoke("add 'X' after line 99 in a.txt")
    assert "out of bounds" in reply.lower() or "bounds" in reply.lower()


def test_delete_lines_removes_span(env):
    dl = env / "dl.txt"
    dl.write_text("one\ntwo\nthree\nfour\nfive\nsix\n")
    name, reply = invoke("delete lines 2 to 4 in dl.txt")
    assert name == "fp_delete_lines"
    assert dl.read_text().splitlines() == ["one", "five", "six"]
    assert "3 line(s)" in reply
    assert (env / "dl.txt.bak").exists()


def test_delete_single_line(env):
    one = env / "one.txt"
    one.write_text("keep\ndrop\nkeep2\n")
    _, reply = invoke("delete line 2 in one.txt")
    assert one.read_text().splitlines() == ["keep", "keep2"]


def test_delete_file_trash_or_gone(env):
    victim = env / "victim.txt"
    victim.write_text("bye\n")
    name, reply = invoke("delete file victim.txt")
    assert name == "fp_delete_file"
    assert not victim.exists()
    if sys.platform == "darwin":
        assert "trash" in reply.lower()
        try:
            os.unlink(
                os.path.join(os.path.expanduser("~"), ".Trash", "victim.txt")
            )
        except OSError:
            pass
    else:
        assert "deleted" in reply.lower()


def test_delete_file_refuses_directory(env):
    name, reply = invoke("delete file sub")
    assert name == "fp_delete_file"
    assert (env / "sub").is_dir()
    low = reply.lower()
    assert "folder" in low or "directory" in low
    assert "rm" in low or "shell" in low


def test_copy_move_with_dest_backup(env):
    dst_dir = env / "backup"
    name, reply = invoke("copy a.txt to backup/a2.txt")
    assert name == "fp_copy_file"
    assert (dst_dir / "a2.txt").read_text() == (env / "a.txt").read_text()
    (dst_dir / "a2.txt").write_text("stale\n")
    _, reply = invoke("copy a.txt to backup/a2.txt")
    bak = dst_dir / "a2.txt.bak"
    assert bak.exists() and bak.read_text() == "stale\n"
    name, reply = invoke("rename sub/b.txt to moved.txt")
    assert name == "fp_move_file"
    assert not (env / "sub" / "b.txt").exists()
    assert (env / "moved.txt").exists()


def test_search_finds_needle_excludes_venv(env):
    name, reply = invoke("search for NEEDLE")
    assert name == "fp_search_content"
    assert "sub/b.txt:1:" in reply
    assert "sub/deep/c.txt" in reply
    assert ".venv" not in reply
    assert "hidden" not in reply
    assert "3 match" in reply or "match(es)" in reply


def test_search_ext_filter_and_grep_form(env):
    _, reply = invoke("grep NEEDLE sub")
    assert "sub/b.txt" in reply
    (env / "only.md").write_text("NEEDLE in markdown\n")
    _, reply = invoke("search for NEEDLE for .md")
    assert "only.md" in reply
    assert "b.txt" not in reply


def test_search_regex_mode(env):
    _, reply = invoke("search for /NE.DLE/ in sub")
    assert "b.txt:1:" in reply and "b.txt:3:" in reply
    assert "deep/c.txt:1:" in reply


def test_tree_prunes_skip_dirs_and_footer(env):
    name, reply = invoke("tree .")
    assert name == "fp_tree"
    assert ".venv" not in reply
    assert "sub/" in reply
    assert "junk/" in reply
    m = re.search(r"\((\d+) files, (\d+) dirs\)", reply)
    assert m, reply
    many = env / "many"
    many.mkdir()
    for i in range(130):
        (many / ("f%03d.txt" % i)).write_text("x\n")
    _, reply = invoke("tree .")
    assert "pruned" in reply.lower()
    m = re.search(r"\((\d+) files, (\d+) dirs\)", reply)
    assert m, reply
    assert int(m.group(1)) <= 120


def test_diff_shows_unified_and_counts(env):
    (env / "d1.txt").write_text("one\ntwo\nthree\n")
    (env / "d2.txt").write_text("one\nTWO\nthree\nfour\n")
    name, reply = invoke("diff d1.txt and d2.txt")
    assert name == "fp_diff_files"
    assert "+++" in reply
    assert "---" in reply
    assert "2 added" in reply
    assert "1 removed" in reply
    _, reply = invoke("compare d1.txt with d2.txt")
    assert "+++" in reply


def test_mkdir_idempotent(env):
    _, first = invoke("make folder newbox")
    assert "Created" in first
    assert (env / "newbox").is_dir()
    _, second = invoke("make folder newbox")
    assert "already" in second.lower()


def test_negatives_do_not_fire():
    for cmd in ("open youtube", "play some music", "what time is it"):
        for name, detect, _execute, _prio in fp.SKILLS:
            assert detect(cmd) is None, "%s fired on %r" % (name, cmd)
