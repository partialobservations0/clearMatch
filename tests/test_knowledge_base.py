"""Tests for src/knowledge_base.py. No API calls -- these only exercise local text/DB logic."""

from knowledge_base import looks_non_latin_script, normalize, find_name_forms_in_text

# Real excerpt from a live Xinhua news article about Xi Jinping (fetched during this project's
# foreign-language investigation) -- genuinely relevant, zero Latin-script occurrence of his
# romanized name anywhere in the text.
REAL_CHINESE_ARTICLE_EXCERPT = (
    "9月23日下午，国家主席习近平乘专机离开北京，应美国总统特朗普邀请，对美国进行国事访问。"
    "这是习近平主席时隔3年再次到访美国，也是中美两国元首在半年内实现互访，具有历史性、里程碑意义。"
)

REAL_RUSSIAN_SNIPPET = "Владимир Владимирович Путин выступил с заявлением на пресс-конференции сегодня утром."

REAL_ARABIC_SNIPPET = "أعلن الرئيس عن خطة جديدة للإصلاح الاقتصادي في اجتماع صحفي اليوم."


def test_chinese_text_detected_as_non_latin():
    assert looks_non_latin_script(REAL_CHINESE_ARTICLE_EXCERPT) is True


def test_russian_text_detected_as_non_latin():
    assert looks_non_latin_script(REAL_RUSSIAN_SNIPPET) is True


def test_arabic_text_detected_as_non_latin():
    assert looks_non_latin_script(REAL_ARABIC_SNIPPET) is True


def test_english_text_not_flagged():
    text = "Simone Biles won the vault final at the Paris Olympics, her third gold of the Games."
    assert looks_non_latin_script(text) is False


def test_french_diacritics_not_flagged_as_non_latin():
    """Accented Latin letters (French, Spanish, German, etc.) are still Latin script --
    only genuinely different scripts (CJK, Cyrillic, Arabic, ...) should trigger this."""
    text = "Le président français a annoncé une réforme économique majeure à Paris, où il a été élu."
    assert looks_non_latin_script(text) is False


def test_mixed_text_with_romanized_name_still_mostly_latin():
    """Regression context: Chinese Wikipedia's article on Xi Jinping DID contain the Latin
    romanization somewhere (citations), and the pre-check found it directly via
    find_name_forms_in_text -- this function only matters for the case where NO romanized
    form exists at all, like the pure-native-language news article above."""
    text = "Xi Jinping (born June 15, 1953) is a Chinese politician."
    assert looks_non_latin_script(text) is False


def test_short_text_insufficient_signal_defaults_to_false():
    """Not enough letters to make a confident call -- must not override the pre-check on a
    hunch when there's too little text to be sure."""
    assert looks_non_latin_script("Hi") is False
    assert looks_non_latin_script("") is False


def test_real_chinese_article_pre_check_would_have_failed_without_fix():
    """Documents the exact bug this was built to fix: our Latin-only name forms genuinely
    find nothing in real Chinese news text, confirming looks_non_latin_script is the only
    thing that can catch this case."""
    name_forms = ["Xi Jinping", "President Xi", "Xi Dada"]
    found = find_name_forms_in_text(REAL_CHINESE_ARTICLE_EXCERPT, name_forms)
    assert found == []
    assert looks_non_latin_script(REAL_CHINESE_ARTICLE_EXCERPT) is True


def test_apostrophe_normalization_still_works():
    """Regression test for a real bug: curly vs straight apostrophes ('O'Donnell' with a
    Unicode right-single-quote vs a straight apostrophe) must be treated as equivalent."""
    assert normalize("Shannon O’Donnell") == normalize("Shannon O'Donnell")
