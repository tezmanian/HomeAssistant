"""Renders the blueprint's heating_season template with mocked HA functions."""
import datetime
import pathlib
import re
import unittest

import jinja2
import yaml

BLUEPRINT = pathlib.Path(
    "blueprints/automation/tezmanian/window-ventilation-advisor.yaml"
)


class Loader(yaml.SafeLoader):
    pass


Loader.add_constructor("!input", lambda l, n: l.construct_scalar(n))
TEMPLATE = yaml.load(BLUEPRINT.read_text(encoding="utf-8"), Loader)["variables"][
    "heating_season"
]

ENV = jinja2.Environment()
ENV.tests["match"] = lambda value, pattern: re.match(pattern, value) is not None


def season(month_day="01-15", mode="temperature", t_out=None, limit=15,
           start="10-01", end="04-30", entity=None, states=None):
    states = states or {}
    month, day = (int(x) for x in month_day.split("-"))
    now = datetime.datetime(2026, month, day)
    out = ENV.from_string(TEMPLATE).render(
        now=lambda: now,
        states=lambda e: states.get(e, "unknown"),
        is_state=lambda e, s: states.get(e) == s,
        heating_mode=mode,
        heating_entity=[] if entity is None else entity,
        heating_start=start,
        heating_end=end,
        heating_limit=limit,
        t_out=t_out,
    )
    assert out in ("True", "False"), repr(out)
    return out == "True"


class Temperature(unittest.TestCase):
    def test_below_limit(self):
        self.assertTrue(season(t_out=10))

    def test_at_or_above_limit(self):
        self.assertFalse(season(t_out=15))
        self.assertFalse(season(t_out=20))

    def test_no_outdoor_sensor_falls_back_to_months(self):
        self.assertTrue(season("11-05"))
        self.assertTrue(season("04-30"))
        self.assertFalse(season("06-01"))

    def test_temperature_ignores_date(self):
        self.assertFalse(season("01-15", t_out=20))


class Dates(unittest.TestCase):
    def test_across_new_year(self):
        for md, exp in [("10-01", True), ("12-31", True), ("01-01", True),
                        ("04-30", True), ("05-01", False), ("09-30", False)]:
            with self.subTest(md=md):
                self.assertEqual(season(md, mode="dates"), exp)

    def test_same_year_range(self):
        kw = dict(mode="dates", start="05-01", end="09-30")
        self.assertTrue(season("05-01", **kw))
        self.assertTrue(season("07-15", **kw))
        self.assertTrue(season("09-30", **kw))
        self.assertFalse(season("04-30", **kw))
        self.assertFalse(season("10-01", **kw))

    def test_dates_ignore_outdoor_temperature(self):
        self.assertTrue(season("01-15", mode="dates", t_out=25))
        self.assertFalse(season("07-15", mode="dates", t_out=0))

    def test_invalid_format_falls_back_to_temperature(self):
        self.assertTrue(season("07-15", mode="dates", start="Oct 1", t_out=5))
        self.assertFalse(season("07-15", mode="dates", end="4-30", t_out=25))
        self.assertFalse(season("07-15", mode="dates", start="", t_out=25))


class Entity(unittest.TestCase):
    def test_on_off(self):
        e = "input_boolean.heating"
        self.assertTrue(season(mode="entity", entity=[e], states={e: "on"}, t_out=25))
        self.assertFalse(season(mode="entity", entity=[e], states={e: "off"}, t_out=0))

    def test_string_entity(self):
        e = "input_boolean.heating"
        self.assertTrue(season(mode="entity", entity=e, states={e: "on"}))

    def test_unavailable_falls_back(self):
        e = "binary_sensor.heating"
        for st in ("unavailable", "unknown"):
            with self.subTest(state=st):
                self.assertTrue(season(mode="entity", entity=[e], states={e: st}, t_out=5))
                self.assertFalse(season(mode="entity", entity=[e], states={e: st}, t_out=25))

    def test_no_entity_selected_falls_back(self):
        self.assertTrue(season(mode="entity", entity=[], t_out=5))

    def test_entity_ignored_in_other_modes(self):
        e = "input_boolean.heating"
        self.assertFalse(season("07-15", mode="temperature", entity=[e],
                                states={e: "on"}, t_out=25))


if __name__ == "__main__":
    unittest.main()
