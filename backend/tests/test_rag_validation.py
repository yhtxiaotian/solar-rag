from app.services.rag import REFUSAL, _validated_answer


def test_removes_invented_citation():
    answer, cited = _validated_answer("结论一 [1]，虚构内容 [9]。", 2)
    assert "[9]" not in answer
    assert cited == {1}


def test_refuses_uncited_answer():
    answer, cited = _validated_answer("这是一个没有引用的确定结论。", 3)
    assert answer == REFUSAL
    assert cited == set()


def test_refuses_invented_source_metadata_even_with_valid_marker():
    answer, cited = _validated_answer(
        "根据《虚构政策.pdf》第 99 页，项目可以实施 [1]。",
        1,
        allowed_titles={"真实政策"},
        allowed_pages={3},
        allowed_files={"真实政策.pdf"},
    )
    assert answer == REFUSAL
    assert cited == set()
