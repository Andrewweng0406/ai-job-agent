from app.applications.standard_answers import StandardAnswers


def test_city_label_beats_earlier_generic_location_rule():
    answers = StandardAnswers(
        values={"location_full": "San Jose, CA, USA", "city": "San Jose"},
        rules=[
            ("location_full", ("location",)),
            ("city", ("location (city)", "city")),
        ],
    )

    assert answers.resolve("Location (City)*") == "San Jose"


def test_label_punctuation_does_not_break_matching():
    answers = StandardAnswers(
        values={"country": "United States"},
        rules=[("country", ("country *",))],
    )

    assert answers.resolve("Country*") == "United States"
