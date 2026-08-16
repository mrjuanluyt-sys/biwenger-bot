from bot.visual import auto_html, chunk, esc


def test_escapes_html() -> None:
    assert "&lt;b&gt;" in esc("<b>")


def test_auto_html_bolds_first_line() -> None:
    out = auto_html("Hola\nsegunda")
    assert out.startswith("<b>Hola</b>")
    assert "segunda" in out


def test_chunk_splits_long() -> None:
    text = "\n".join(["linea"] * 200)
    parts = chunk(text, limit=80)
    assert len(parts) > 1
    assert all(len(p) <= 90 for p in parts)
