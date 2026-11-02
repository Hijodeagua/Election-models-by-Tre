from src.data.names import names_match, normalize_name, pollster_key, pollsters_match


def test_middle_initials_accents_and_suffixes_are_ignored():
    assert names_match("John Sununu", "John E. Sununu")
    assert names_match("Ben Ray Lujan", "Ben Ray Luján")
    assert names_match("James Byrd", "James W. Byrd")
    assert names_match("Darline Graham", "Darline Graham Nordone")
    assert names_match("N'Kiyla Thomas", "N'Kiyla Jasmine Thomas")
    assert names_match("Dan Sullivan", "Daniel J. Sullivan Jr.") is False  # different first name
    assert not names_match("Mike Collins", "Susan Collins")
    assert normalize_name("Jr. John E. Sununu") == ["john", "sununu"]


def test_pollster_key_tolerates_spelling_and_sponsor_variants():
    assert pollster_key("NY Times/Siena") == pollster_key("Siena/NYT")
    assert pollster_key("Siena College/The New York Times") == pollster_key("NYT/Siena")
    assert pollster_key("The Citadel Poll") == pollster_key("The Citadel")
    assert pollster_key("East Carolina U.") == pollster_key("East Carolina University")
    assert pollsters_match("Emerson College/WPRI-TV", "Emerson College")
    assert pollsters_match("Chism Strategies (D)", "Chism Strategies / Blueprint Polling")
    assert pollsters_match("Hart Research (D)", "Hart Research Associates")
    assert not pollsters_match("Emerson College", "Embold Research")
    assert pollster_key("Public Policy Polling (D)") == pollster_key("PPP")
    assert pollster_key("Public Policy Polling") != pollster_key("Public Opinion Strategies")
