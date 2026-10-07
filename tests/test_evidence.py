"""The verification rule: a find is VERIFIED only when two independent sources agree on the same work."""
from reel_watcher import evidence as E

PARASITE = {"ext_key": "wikidata:Q1", "name": "Parasite", "names": [], "year": 2019, "type": "movie"}


def v(*ev):
    return E.verdict(list(ev))


def test_named_and_exact_unique_database_entry_is_verified():
    conf, why = v(E.named("text", "PARASITE"), E.database(PARASITE, "PARASITE"))
    assert conf == "confirmed" and "identified by Wikidata" in why


def test_one_source_is_never_enough():
    assert v(E.named("caption", "Parasite"))[0] == "check"                      # named, but which Parasite?
    assert v(E.database(PARASITE, "Parasite"))[0] == "check"                    # exists, but the screen does not say it
    assert v(E.picture("trace.moe", {"score": 0.97}))[0] == "check"             # picture searches can be wrong
    w = {"name": "Parasite", "year": 2019, "type": "movie", "site": "Wikipedia", "agree": 3, "evidence": "Parasite (2019 film)"}
    assert v(*E.web(w))[0] == "check"                                           # web results for screen words only
    assert v(E.ai("Parasite"))[0] == "check"                                    # an AI guess never counts


def test_close_or_shared_names_stay_possible():
    close = v(E.named("text", "PARASlTE"), E.database(PARASITE, "PARASlTE"))     # misread letter
    assert close == ("check", "not certain: the name on screen is only close")
    twin = v(E.named("text", "Monster"), E.database({**PARASITE, "name": "Monster", "ambiguous": True}, "Monster"))
    assert twin == ("check", "not certain: several works have this name")
    common = v(E.named("text", "Dark"), E.database({**PARASITE, "name": "Dark"}, "Dark", weak_word=True))
    assert common[0] == "check" and "common word" in common[1]


def test_web_agreement_and_year_conflicts():
    scene = {"name": "Scene", "year": 2026, "type": "movie", "site": "Wikipedia", "agree": 2, "evidence": "Scene (2026 film)",
             "same_name_other_years": []}
    assert v(E.named("text", "Scene (2026 film)"), *E.web(scene, "Scene", 2026))[0] == "confirmed"
    wrong_year = v(E.named("text", "x"), *E.web(scene, "Scene", 2019))
    assert wrong_year[0] == "check" and "the screen says 2019, the web says 2026" in wrong_year[1]
    twins = {**scene, "same_name_other_years": [2004]}
    assert v(E.named("text", "Scene"), *E.web(twins, "Scene", None))[0] == "check"   # no year on screen: which one?
    assert v(E.named("text", "Scene"), *E.web(twins, "Scene", 2026))[0] == "confirmed"
    other_name = v(E.named("text", "Scenes"), *E.web(scene, "Scenes", None))
    assert other_name[0] == "check"                                                  # web found a different title


def test_pictures_agreeing():
    assert v(E.picture("trace.moe", {"score": 0.93}), E.picture("SauceNAO", {"score": 0.9}))[0] == "confirmed"
    assert v(E.picture("trace.moe", {"score": 0.93}), E.named("text", "FRIEREN"))[0] == "confirmed"
    weak = v(E.picture("SauceNAO", {"score": 0.81}), E.named("text", "Vagabond"))
    assert weak[0] == "check"


def test_user_choice_is_final_and_summary_reads_well():
    assert v(E.ai("x"), E.user())[0] == "confirmed"
    s = E.summary([E.named("text", "a"), E.database(PARASITE, "Parasite"), E.named("caption", "b")])
    assert s == "on screen + Wikidata: Parasite (2019) + in the caption"


def test_exact_names():
    assert E.exact("FRIEREN", "Frieren: Beyond Journey's End") and E.exact("the dark knight", "The Dark Knight")
    assert not E.exact("Dark", "Dark Matter") and not E.exact("Scene", "Scenes") and not E.exact("", "x")
