from app.services.chunker import ParsedBlock, chunk_blocks


def test_chunker_preserves_page_and_section(monkeypatch):
    blocks = [
        ParsedBlock("第一章 总则。" * 80, page=1, section="第一章"),
        ParsedBlock("第二章 备案管理。" * 80, page=2, section="第二章"),
    ]
    chunks = chunk_blocks(blocks)
    assert len(chunks) >= 2
    assert chunks[0].page_start == 1
    assert chunks[-1].page_end == 2
    assert chunks[0].section_path == "第一章"


def test_chunker_repeats_table_header_when_splitting(monkeypatch):
    header = "| 型号 | 功率 |\n| --- | --- |\n"
    rows = "\n".join(f"| M-{index} | {index} kW |" for index in range(180))
    chunks = chunk_blocks([ParsedBlock(header + rows, page=8, section="参数表", kind="table")])
    assert len(chunks) > 1
    assert all("| 型号 | 功率 |" in item.content for item in chunks)
    assert all(item.page_start == 8 for item in chunks)

