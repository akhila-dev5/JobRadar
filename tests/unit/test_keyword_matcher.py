from backend.app.matching.keyword_matcher import KeywordMatcher, KeywordRule

RULES = [KeywordRule("Python"), KeywordRule(".NET"), KeywordRule("React"), KeywordRule("Microservices")]


def m(title="", desc=""):
    return KeywordMatcher(RULES).match(title, desc)


# ---- the mandatory OR requirement ---------------------------------------
def test_job_a_only_python_qualifies():
    assert m("Engineer", "We use Python daily.").qualified


def test_job_b_only_react_qualifies():
    assert m("Frontend Dev", "Build UIs with React.").qualified


def test_job_c_python_and_microservices_qualifies():
    r = m("Backend", "Python microservices on Azure")
    assert r.qualified and r.matched_keywords == ["Python", "Microservices"]


def test_job_d_no_keyword_does_not_qualify():
    assert not m("Accountant", "Manage ledgers and audits.").qualified


def test_single_match_is_sufficient_even_if_other_keywords_missing():
    r = m("Dev", "only .NET here")
    assert r.qualified and r.matched_keywords == [".NET"]


def test_no_enabled_keywords_qualifies_nothing():
    assert not KeywordMatcher([]).match("Python Dev", "Python").qualified


# ---- case, boundaries, phrases -------------------------------------------
def test_case_insensitive():
    assert m("PYTHON developer").qualified and m("python developer").qualified


def test_no_partial_word_matches():
    java = KeywordMatcher([KeywordRule("Java")])
    assert not java.match("JavaScript Developer", "We love JavaScript").qualified
    assert java.match("Java Developer", "").qualified
    go = KeywordMatcher([KeywordRule("Go")])
    assert not go.match("Google engineer", "Working at a good company").qualified
    assert go.match("Backend", "Experience with Go.").qualified


def test_c_does_not_match_c_sharp_or_cpp():
    c = KeywordMatcher([KeywordRule("C")])
    assert not c.match("", "C# and C++ developer").qualified
    assert c.match("", "Embedded C, firmware").qualified


def test_dot_net_matches_inside_aspdotnet_but_not_plain_word_net():
    assert m("", "ASP.NET Core developer").qualified
    assert not KeywordMatcher([KeywordRule(".NET")]).match("", "Network engineer, internet").qualified


def test_c_sharp_special_characters():
    r = KeywordMatcher([KeywordRule("C#")]).match("", "Strong C# skills, C#.")
    assert r.qualified


def test_phrase_matching_allows_hyphen_and_extra_spaces():
    fs = KeywordMatcher([KeywordRule("Full Stack Developer")])
    assert fs.match("Full-Stack  Developer", "").qualified
    assert not fs.match("Full Developer Stack", "").qualified


def test_aliases_match_and_report_canonical_keyword():
    matcher = KeywordMatcher([KeywordRule("PostgreSQL", ("postgres", "psql"))])
    r = matcher.match("", "Experience with Postgres required")
    assert r.qualified and r.matched_keywords == ["PostgreSQL"]


def test_title_hits_are_tracked_separately():
    r = m("Python Engineer", "React too")
    assert r.title_keywords == ["Python"]


def test_highlight_wraps_matches_and_escapes_html():
    matcher = KeywordMatcher([KeywordRule("Python")])
    out = matcher.highlight("<b>Python</b> & Pythonic")
    assert out == "&lt;b&gt;<mark>Python</mark>&lt;/b&gt; &amp; Pythonic"


def test_regex_metacharacters_in_keywords_are_escaped():
    matcher = KeywordMatcher([KeywordRule("C++"), KeywordRule("(weird")])
    assert matcher.match("", "We use C++ a lot").qualified
