"""Uploads: type detection, size caps, quotas, sandboxed parsers, photo clean-up and per-member access."""

import asyncio
import io
import struct
import sys
import time
import zipfile
import zlib
from pathlib import Path

import pytest
from fastapi import Request
from PIL import Image

from openfolio_worker.cloud import parsers, sandbox
from openfolio_worker.cloud.uploads import (
    DOCX,
    JPEG,
    MB,
    PDF,
    PNG,
    TEXT,
    WEBP,
    UploadError,
    check_file,
    clean_filename,
    detect,
    read_multipart,
)

from studio_helpers import W_NS, app_for, browser, csrf, db_rows, join, make_docx, make_pdf, png, upload


@pytest.fixture
def app(cloud_settings):
    return app_for(cloud_settings)


def jpeg(image: Image.Image, **params) -> bytes:
    buf = io.BytesIO()
    image.save(buf, "JPEG", **params)
    return buf.getvalue()


def webp() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), "green").save(buf, "WEBP")
    return buf.getvalue()


# Detection uses magic bytes only


def test_detect_by_magic_bytes():
    assert detect(make_pdf(["x"])) is PDF
    assert detect(make_docx(["x"])) is DOCX
    assert detect(jpeg(Image.new("RGB", (80, 80)))) is JPEG
    assert detect(png()) is PNG
    assert detect(webp()) is WEBP
    assert detect("Résumé: designer\n".encode()) is TEXT
    for refused in (b"GIF89a....", b"MZ\x90\x00", b"\x7fELF\x02", b"\x1f\x8b\x08", b"text\x00with nul"):
        assert detect(refused) is None
    assert detect(b"\xff\xfe\x00\x00not utf8\x80\x81") is None


def test_check_file_slots_sizes_and_quotas():
    with pytest.raises(UploadError) as e:
        check_file(PNG, "document", 100, (0, 0))
    assert e.value.code == "wrong_slot_photo"
    with pytest.raises(UploadError) as e:
        check_file(PDF, "photo", 100, (0, 0))
    assert e.value.code == "wrong_slot_document"
    with pytest.raises(UploadError) as e:
        check_file(None, "document", 100, (0, 0))
    assert e.value.code == "unsupported"
    with pytest.raises(UploadError) as e:
        check_file(PDF, "document", 0, (0, 0))
    assert e.value.code == "empty"
    for file_type, limit in ((PDF, 10 * MB), (DOCX, 5 * MB), (TEXT, 200 * 1024), (JPEG, 5 * MB)):
        check_file(file_type, file_type.slot, limit, (0, 0))
        with pytest.raises(UploadError) as e:
            check_file(file_type, file_type.slot, limit + 1, (0, 0))
        assert e.value.code == "too_large"
    with pytest.raises(UploadError) as e:
        check_file(PDF, "document", 100, (10, 1000))
    assert e.value.code == "quota_files"
    with pytest.raises(UploadError) as e:
        check_file(PDF, "document", 2 * MB, (3, 29 * MB))
    assert e.value.code == "quota_bytes"


def test_clean_filename():
    assert clean_filename("../../etc/passwd") == "passwd"
    assert clean_filename("C:\\Users\\jane\\cv.pdf") == "cv.pdf"
    assert clean_filename("evil\u202egnp.pdf") == "evilgnp.pdf"  # no bidi override
    assert clean_filename("") == "upload"
    assert len(clean_filename("a" * 500)) == 120


def test_request_cap_holds_while_streaming_without_content_length():
    head = (
        b'--x\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\nContent-Type: application/pdf\r\n\r\n'
    )
    chunks = [head + b"0" * 500, b"0" * 600, b"0" * 600, b"\r\n--x--\r\n"]

    async def receive():
        body = chunks.pop(0) if chunks else b""
        return {"type": "http.request", "body": body, "more_body": bool(chunks)}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(b"content-type", b"multipart/form-data; boundary=x")],
    }

    async def go():
        await read_multipart(Request(scope, receive), max_bytes=1000)

    with pytest.raises(UploadError) as e:
        asyncio.run(go())
    assert e.value.code == "request_too_large"


# Parsers (called directly, then through the sandbox)


def test_pdf_text_page_cap_and_trailing_data(tmp_path):
    path = tmp_path / "cv.pdf"
    path.write_bytes(make_pdf(["Jane Doe designs checkout flows", "Acme 2021 to present"]))
    result = parsers.parse_pdf(path)
    assert result["pages"] == 2
    assert "Jane Doe designs checkout flows" in result["text"]
    path.write_bytes(make_pdf(["page"] * 31))
    with pytest.raises(parsers.ParseError) as e:
        parsers.parse_pdf(path)
    assert e.value.code == "pdf_pages"
    # A PDF with a ZIP appended (a polyglot) is refused.
    path.write_bytes(make_pdf(["x"]) + make_docx(["hidden"]))
    with pytest.raises(parsers.ParseError) as e:
        parsers.parse_pdf(path)
    assert e.value.code == "pdf_malformed"
    path.write_bytes(b"%PDF-1.4\n garbage %%EOF")
    with pytest.raises(parsers.ParseError) as e:
        parsers.parse_pdf(path)
    assert e.value.code == "pdf_malformed"


def test_docx_text_and_zip_defences(tmp_path):
    path = tmp_path / "cv.docx"
    path.write_bytes(make_docx(["Jane Doe", "Senior Product Designer"]))
    assert parsers.parse_docx(path)["text"] == "Jane Doe\nSenior Product Designer"
    # Declares more than 25 MB uncompressed but is tiny on disk.
    path.write_bytes(make_docx(document_xml="<a>" + "A" * (26 * 1024 * 1024) + "</a>"))
    assert path.stat().st_size < 200_000
    with pytest.raises(parsers.ParseError) as e:
        parsers.parse_docx(path)
    assert e.value.code == "zip_bomb"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(400):
            z.writestr(f"f{i}", "x")
    path.write_bytes(buf.getvalue())
    with pytest.raises(parsers.ParseError) as e:
        parsers.parse_docx(path)
    assert e.value.code == "docx_entries"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", "<x/>")
    path.write_bytes(buf.getvalue())
    with pytest.raises(parsers.ParseError) as e:
        parsers.parse_docx(path)
    assert e.value.code == "docx_not_word"
    # Entity expansion (billion laughs / XXE) is refused by defusedxml.
    evil = (
        '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;">]>'
        f'<w:document xmlns:w="{W_NS}"><w:body><w:p><w:r><w:t>&b;</w:t></w:r></w:p></w:body></w:document>'
    )
    path.write_bytes(make_docx(document_xml=evil))
    with pytest.raises(parsers.ParseError) as e:
        parsers.parse_docx(path)
    assert e.value.code == "docx_malformed"


def test_text_parser(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_bytes("\ufeffJane\r\n\r\n\r\n\r\nDesigner\u200b\u202e".encode())
    assert parsers.parse_text(path)["text"] == "Jane\n\nDesigner"
    path.write_bytes(b"\xff\xfeJ\x00")
    with pytest.raises(parsers.ParseError):
        parsers.parse_text(path)
    path.write_bytes(b"hello\x01world")
    with pytest.raises(parsers.ParseError) as e:
        parsers.parse_text(path)
    assert e.value.code == "text_binary"


def test_photo_is_uprighted_cropped_and_stripped_of_exif(tmp_path):
    # Stored sideways (orientation 6): left half red, right half blue, plus a GPS position.
    image = Image.new("RGB", (400, 200), "blue")
    image.paste(Image.new("RGB", (200, 200), "red"), (0, 0))
    exif = Image.Exif()
    exif[0x0112] = 6
    exif[0x010F] = "SpyCam"
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (51.0, 30.0, 0.0)
    raw = jpeg(image, exif=exif.tobytes(), quality=95)
    with Image.open(io.BytesIO(raw)) as check:
        assert check.getexif().get(0x0112) == 6
        assert check.getexif().get_ifd(0x8825)
    src, out = tmp_path / "in", tmp_path / "out.jpg"
    src.write_bytes(raw)
    assert parsers.process_photo(src, out) == {"width": 512, "height": 512}
    data = out.read_bytes()
    assert b"SpyCam" not in data
    assert b"Exif" not in data
    with Image.open(out) as result:
        assert result.size == (512, 512)
        assert result.format == "JPEG"
        assert not result.getexif()
        assert "icc_profile" not in result.info
        top, bottom = result.getpixel((256, 60)), result.getpixel((256, 450))
    # red on top: the rotation was applied
    assert top[0] > 180
    assert top[2] < 80
    assert bottom[2] > 180
    assert bottom[0] < 80


def test_photo_pixel_cap_and_tiny_images(tmp_path):
    data = bytearray(png(100, 100))
    # Rewrite the PNG header to claim 8000 x 6000 (48 megapixels) with a valid checksum.
    data[16:24] = struct.pack(">II", 8000, 6000)
    data[29:33] = struct.pack(">I", zlib.crc32(bytes(data[12:29])) & 0xFFFFFFFF)
    src = tmp_path / "big.png"
    src.write_bytes(bytes(data))
    with pytest.raises(parsers.ParseError) as e:
        parsers.process_photo(src, tmp_path / "out.jpg")
    assert e.value.code == "image_pixels"
    src.write_bytes(png(20, 20))
    with pytest.raises(parsers.ParseError) as e:
        parsers.process_photo(src, tmp_path / "out.jpg")
    assert e.value.code == "image_small"
    src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)
    with pytest.raises(parsers.ParseError) as e:
        parsers.process_photo(src, tmp_path / "out.jpg")
    assert e.value.code == "image_malformed"


def test_sandbox_runs_parsers_in_a_child_process(tmp_path):
    pdf = tmp_path / "cv.pdf"
    pdf.write_bytes(make_pdf(["Jane Doe designs checkout flows"]))
    assert "checkout flows" in asyncio.run(sandbox.run("pdf", pdf))["text"]
    bomb = tmp_path / "bomb.docx"
    bomb.write_bytes(make_docx(document_xml="<a>" + "A" * (26 * 1024 * 1024) + "</a>"))
    with pytest.raises(sandbox.SandboxError) as e:
        asyncio.run(sandbox.run("docx", bomb))
    assert e.value.code == "zip_bomb"


def test_sandbox_kills_a_parser_that_hangs(tmp_path):
    start = time.monotonic()
    hang = [sys.executable, "-c", "import time; time.sleep(30)"]
    with pytest.raises(sandbox.SandboxError) as e:
        asyncio.run(sandbox.run("pdf", tmp_path / "x.pdf", seconds=0.5, command=hang))
    assert e.value.code == "timeout"
    assert time.monotonic() - start < 5


def test_sandbox_treats_a_crash_as_too_complex(tmp_path):
    crash = [sys.executable, "-c", "import os; os.abort()"]
    with pytest.raises(sandbox.SandboxError) as e:
        asyncio.run(sandbox.run("pdf", tmp_path / "x.pdf", command=crash))
    assert e.value.code == "too_complex"
    garbage = [sys.executable, "-c", "print('not json')"]
    with pytest.raises(sandbox.SandboxError):
        asyncio.run(sandbox.run("pdf", tmp_path / "x.pdf", command=garbage))


def test_sandbox_child_has_no_secrets(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-secret")
    monkeypatch.setenv("SESSION_SECRET", "s3cret")
    env = sandbox._clean_env()
    assert "LLM_API_KEY" not in env
    assert "SESSION_SECRET" not in env


# Through the Studio


def user_dir(settings, user_id: int = 1) -> Path:
    return Path(settings.data_dir) / "users" / str(user_id)


def test_upload_document_and_photo(app, cloud_settings):
    client = join(app, cloud_settings)
    r = upload(client, "document", "Jane CV.pdf", make_pdf(["Jane Doe designs checkout flows"]), "application/pdf")
    assert r.status_code == 303
    assert r.headers["location"].startswith("/studio/setup?m=uploaded")
    ((name, mime, text),) = db_rows(cloud_settings, "SELECT original_name, mime, text FROM files")
    assert (name, mime) == ("Jane CV.pdf", "application/pdf")
    assert "checkout flows" in text
    page = client.get("/studio/setup")
    assert "Jane CV.pdf" in page.text
    assert "checkout flows" in page.text  # what we read is shown
    stored = list(user_dir(cloud_settings).iterdir())
    assert len(stored) == 1
    assert stored[0].name != "Jane CV.pdf"
    assert len(stored[0].stem) == 32
    r = upload(client, "photo", "me.png", png(), "image/png")
    assert r.status_code == 303
    (photo,) = db_rows(cloud_settings, "SELECT id, stored_name, mime FROM files WHERE kind = 'photo'")
    assert photo[1].endswith(".jpg")
    assert photo[2] == "image/jpeg"
    data = client.get("/studio/profile").text
    assert f"/p/jane/photo-{photo[0]}.jpg" in data
    download = client.get(f"/studio/files/{photo[0]}")
    assert download.status_code == 200
    assert download.headers["content-type"] == "image/jpeg"
    doc_id = db_rows(cloud_settings, "SELECT id FROM files WHERE kind = 'document'")[0][0]
    doc = client.get(f"/studio/files/{doc_id}")
    assert doc.headers["content-disposition"].startswith("attachment")
    assert "sandbox" in doc.headers["content-security-policy"]
    assert doc.headers["x-content-type-options"] == "nosniff"


def test_a_new_photo_replaces_the_old_one(app, cloud_settings):
    client = join(app, cloud_settings)
    upload(client, "photo", "a.png", png(color=(255, 0, 0)))
    upload(client, "photo", "b.png", png(color=(0, 0, 255)))
    assert db_rows(cloud_settings, "SELECT COUNT(*) FROM files WHERE kind = 'photo'") == [(1,)]
    assert len(list(user_dir(cloud_settings).iterdir())) == 1


@pytest.mark.parametrize(
    ("slot", "filename", "data", "status", "message"),
    [
        ("document", "resume.pdf", png(), 400, "That&#39;s a photo"),  # fake extension
        ("photo", "photo.jpg", b"<html><script>alert(1)</script></html>", 400, "That&#39;s a document"),
        ("document", "resume.pdf", b"MZ\x90\x00 this is a windows program", 400, "isn&#39;t supported"),
        ("document", "resume.pdf", b"GIF89a" + b"\x00" * 100, 400, "isn&#39;t supported"),
        ("document", "big.pdf", b"%PDF-" + b"0" * (10 * 1024 * 1024 + 10), 413, "PDF files can be up to 10 MB."),
        ("document", "big.txt", b"a" * (200 * 1024 + 1), 413, "text files can be up to 200 KB."),
        ("photo", "big.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024), 413, "PNG files can be up to 5 MB."),
        ("document", "broken.pdf", b"%PDF-1.7 not really a pdf", 400, "couldn&#39;t read that PDF"),
        ("document", "pages.pdf", make_pdf(["p"] * 31), 400, "up to 30 pages"),
        ("document", "bomb.docx", make_docx(document_xml="<a>" + "A" * (26 * 1024 * 1024) + "</a>"), 400, "25 MB"),
        ("document", "sheet.docx", b"PK\x03\x04" + b"\x00" * 100, 400, "Word"),
        ("photo", "corrupt.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 100, 400, "couldn&#39;t read that photo"),
        ("document", "empty.txt", b"", 400, "empty"),
    ],
)
def test_upload_rejections(app, cloud_settings, slot, filename, data, status, message):
    client = join(app, cloud_settings)
    r = upload(client, slot, filename, data)
    assert r.status_code == status, r.text[-400:]
    assert message in r.text
    assert db_rows(cloud_settings, "SELECT COUNT(*) FROM files") == [(0,)]
    assert not any(user_dir(cloud_settings).glob("*")) if user_dir(cloud_settings).exists() else True
    assert db_rows(cloud_settings, "SELECT COUNT(*) FROM audit_log WHERE action = 'file.rejected'") == [(1,)]


def test_whole_request_over_12_mb_is_refused_before_parsing(app, cloud_settings):
    client = join(app, cloud_settings)
    r = upload(client, "document", "huge.pdf", b"%PDF-" + b"0" * (13 * 1024 * 1024))
    assert r.status_code == 413
    assert "Uploads are limited to 12 MB." in r.text


def test_photo_polyglot_is_neutralised(app, cloud_settings):
    client = join(app, cloud_settings)
    payload = jpeg(Image.new("RGB", (200, 200), "orange")) + make_docx(["<script>alert(1)</script>"])
    assert upload(client, "photo", "polyglot.jpg", payload).status_code == 303
    (stored,) = db_rows(cloud_settings, "SELECT stored_name FROM files")
    data = (user_dir(cloud_settings) / stored[0]).read_bytes()
    assert b"PK\x03\x04" not in data
    assert b"script" not in data
    with Image.open(io.BytesIO(data)) as image:
        assert image.size == (512, 512)


def test_quota_of_ten_files(app, cloud_settings):
    client = join(app, cloud_settings)
    for i in range(10):
        assert upload(client, "document", f"n{i}.txt", f"note {i} about my work".encode()).status_code == 303
    r = upload(client, "document", "n10.txt", b"one more")
    assert r.status_code == 400
    assert "up to 10 files" in r.text


def test_pasted_text_becomes_a_document(app, cloud_settings):
    client = join(app, cloud_settings)
    r = client.post("/studio/text", data={"csrf": csrf(client), "text": "I design payments at Acme."})
    assert r.status_code == 303
    assert db_rows(cloud_settings, "SELECT original_name, text FROM files") == [
        ("Pasted text", "I design payments at Acme.")
    ]


def test_members_never_reach_each_others_files(app, cloud_settings):
    jane = join(app, cloud_settings, handle="jane")
    upload(jane, "document", "jane.pdf", make_pdf(["Jane secret plans"]))
    upload(jane, "photo", "jane.png", png())
    doc_id, photo_id = (row[0] for row in db_rows(cloud_settings, "SELECT id FROM files ORDER BY kind"))
    bob = join(app, cloud_settings, handle="bob")
    for file_id in (doc_id, photo_id):
        assert bob.get(f"/studio/files/{file_id}").status_code == 404
        r = bob.post(f"/studio/files/{file_id}/delete", data={"csrf": csrf(bob)})
        assert r.status_code == 303
    assert db_rows(cloud_settings, "SELECT COUNT(*) FROM files") == [(2,)]
    assert "jane.pdf" not in bob.get("/studio/setup").text
    assert bob.get(f"/p/jane/photo-{photo_id}.jpg").status_code == 404  # not live, and not Bob's
    assert browser(app).get(f"/p/jane/photo-{photo_id}.jpg").status_code == 404
    assert jane.get(f"/p/jane/photo-{photo_id}.jpg").status_code == 200  # the owner sees it before go-live
    export = bob.get("/studio/account/export")
    with zipfile.ZipFile(io.BytesIO(export.content)) as z:
        assert not any("jane" in n for n in z.namelist())
        assert b"Jane secret" not in z.read("data.json")
    assert jane.post(f"/studio/files/{doc_id}/delete", data={"csrf": csrf(jane)}).status_code == 303
    assert db_rows(cloud_settings, "SELECT COUNT(*) FROM files WHERE kind = 'document'") == [(0,)]
