"""Renders the blueprint's variables in order with mocked HA functions and
checks the decisions: recommendation, reminders, presence zone, area sensors."""
import ast
import datetime
import pathlib
import re
import unittest

import jinja2

from blueprint_yaml import Input, input_defaults, load

BLUEPRINT = pathlib.Path(
    "blueprints/automation/tezmanian/window-ventilation-advisor.yaml"
)
DATA = load(BLUEPRINT)
DEFAULTS = input_defaults(DATA)
NOW = datetime.datetime(2026, 1, 15, 12, 0)


class Ent:
    def __init__(self, entity_id, state, attrs=None, ago=60):
        self.entity_id = entity_id
        self.state = str(state)
        self.attributes = attrs or {}
        self.last_changed = NOW - datetime.timedelta(minutes=ago)


class States:
    def __init__(self, ents):
        self.ents = {e.entity_id: e for e in ents}

    def __call__(self, entity_id):
        e = self.ents.get(entity_id)
        return e.state if e else "unknown"

    def __getitem__(self, entity_id):
        return self.ents[entity_id]


def is_number(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def parse(text):
    """Like HA's native templates: literal_eval, else the stripped string."""
    text = text.strip()
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError, MemoryError, TypeError):
        return text


def evaluate(ents=(), inputs=None, devices=None, last_triggered=None,
             trigger_id="tick", area_ents=None):
    """Returns all blueprint variables for the given states and inputs.
    devices: {device_id: (name, [tracker entity ids])}"""
    states = States(ents)
    devices = devices or {}
    env = jinja2.Environment()

    def expand(*args):
        out = []
        for a in args:
            for item in [a] if isinstance(a, str) else a:
                if item in states.ents:
                    out.append(states.ents[item])
        return out

    env.globals.update(
        states=states,
        is_state=lambda e, s: states(e) == s,
        state_attr=lambda e, a: states.ents[e].attributes.get(a) if e in states.ents else None,
        expand=expand,
        now=lambda: NOW,
        timedelta=datetime.timedelta,
        area_entities=lambda a: list(area_ents or []),
        area_name=lambda a: "Area",
        device_attr=lambda d, a: devices[d][0],
        device_entities=lambda d: list(devices[d][1]),
    )
    env.filters.update(
        states=states,
        expand=expand,
        is_number=is_number,
        slugify=lambda v: re.sub(r"[^a-z0-9]+", "_", str(v).lower()).strip("_"),
    )
    env.tests.update(
        match=lambda v, p: re.match(p, v) is not None,
        is_number=is_number,
        is_state=lambda e, s: states(e) == s,
    )
    values = dict(DEFAULTS, **(inputs or {}))
    ctx = {
        "this": {"attributes": {"last_triggered": last_triggered}},
        "trigger": {"id": trigger_id},
    }
    for name, value in DATA["variables"].items():
        if isinstance(value, Input):
            ctx[name] = values[str(value)]
        elif isinstance(value, str) and ("{{" in value or "{%" in value):
            ctx[name] = parse(env.from_string(value).render(**ctx, **env.globals))
        else:
            ctx[name] = value
    return ctx


def window(state="off", ago=60):
    return Ent("binary_sensor.window", state, ago=ago)


def sensor(entity_id, state, device_class, unit=None):
    return Ent(entity_id, state, {"device_class": device_class,
                                  "unit_of_measurement": unit})


BASE = {"window_sensors": ["binary_sensor.window"]}
CO2_HIGH = sensor("sensor.co2", 1200, "carbon_dioxide")
CO2_LOW = sensor("sensor.co2", 450, "carbon_dioxide")


def inputs(**kw):
    return dict(BASE, co2_inside=["sensor.co2"], **kw)


class Recommendation(unittest.TestCase):
    def test_high_co2_with_closed_window_says_ventilate(self):
        r = evaluate([window(), CO2_HIGH], inputs())
        self.assertEqual(r["recommendation"], "ventilate")

    def test_pause_after_close_blocks_ventilate_unless_critical(self):
        r = evaluate([window(ago=5), CO2_HIGH], inputs())
        self.assertEqual(r["recommendation"], "ok")
        critical = sensor("sensor.co2", 1500, "carbon_dioxide")
        r = evaluate([window(ago=5), critical], inputs())
        self.assertEqual(r["recommendation"], "ventilate")

    def test_open_window_in_heating_season_closes_after_max_time(self):
        out = sensor("sensor.out", 5, "temperature", "°C")
        i = inputs(temp_outside=["sensor.out"])
        r = evaluate([window("on", ago=20), CO2_HIGH, out], i)
        self.assertEqual(r["max_open"], 10)
        self.assertEqual(r["recommendation"], "close")
        r = evaluate([window("on", ago=3), CO2_HIGH, out], i)
        self.assertEqual(r["recommendation"], "ok")

    def test_open_window_closes_when_air_is_good_again(self):
        out = sensor("sensor.out", 5, "temperature", "°C")
        r = evaluate([window("on", ago=6), CO2_LOW, out],
                     inputs(temp_outside=["sensor.out"]))
        self.assertEqual(r["recommendation"], "close")

    def test_unknown_window_blocks_ventilate(self):
        r = evaluate([window("unavailable"), CO2_HIGH], inputs())
        self.assertEqual(r["recommendation"], "ok")

    def test_deleted_window_contact_blocks_ventilate(self):
        r = evaluate([CO2_HIGH], inputs())
        self.assertEqual(r["recommendation"], "ok")

    def test_absolute_humidity(self):
        t = sensor("sensor.t", 21, "temperature", "°C")
        h = sensor("sensor.h", 60, "humidity", "%")
        r = evaluate([window(), t, h],
                     dict(BASE, temp_inside=["sensor.t"], humidity_inside=["sensor.h"]))
        self.assertAlmostEqual(r["ah_in"], 10.96, places=1)

    def test_fahrenheit_is_converted(self):
        t = sensor("sensor.t", 68, "temperature", "°F")
        r = evaluate([window(), t], dict(BASE, temp_inside=["sensor.t"]))
        self.assertEqual(r["t_in"], 20.0)


class Reminders(unittest.TestCase):
    HELPER = dict(status_helper="input_select.vent")

    def helper(self, ago):
        return Ent("input_select.vent", "ventilate", {
            "options": ["ventilate", "close", "ok"]}, ago=ago)

    def run_reminder(self, ago, last_triggered_ago=None, **kw):
        lt = None if last_triggered_ago is None else NOW - datetime.timedelta(
            minutes=last_triggered_ago)
        return evaluate([window(), CO2_HIGH, self.helper(ago)],
                        inputs(**self.HELPER, **kw), last_triggered=lt)

    def test_reminder_is_due_after_interval_despite_ms_jitter(self):
        self.assertTrue(self.run_reminder(30, 14.99)["reminder_due"])
        self.assertFalse(self.run_reminder(30, 10)["reminder_due"])

    def test_max_reminders_stops_reminding(self):
        self.assertTrue(self.run_reminder(30, max_reminders=2)["reminders_left"])
        self.assertFalse(self.run_reminder(40, max_reminders=2)["reminders_left"])

    def test_zero_means_unlimited(self):
        self.assertTrue(self.run_reminder(999, max_reminders=0)["reminders_left"])

    def test_cap_needs_a_helper(self):
        r = evaluate([window(), CO2_HIGH], inputs(max_reminders=1))
        self.assertTrue(r["reminders_left"])

    def test_window_contact_event_does_not_redeliver(self):
        r = evaluate([window(), CO2_HIGH], inputs(notify_from="00:00:00", notify_until="23:59:00"),
                     trigger_id="window")
        self.assertFalse(r["window_just_opened"])


class NotifyList(unittest.TestCase):
    DEVICES = {
        "d_home": ("Phone Home", ["device_tracker.home"]),
        "d_away": ("Phone Away", ["device_tracker.away"]),
        "d_none": ("Tablet", []),
    }
    ENTS = [window(), Ent("device_tracker.home", "home"),
            Ent("device_tracker.away", "not_home"),
            Ent("zone.home", "0", {"friendly_name": "Home"})]

    def notify_list(self, **kw):
        i = inputs(notify_devices=list(self.DEVICES), **kw)
        return evaluate(self.ENTS, i, devices=self.DEVICES)["notify_list"]

    def test_without_zone_all_devices(self):
        self.assertEqual(self.notify_list(), [
            "notify.mobile_app_phone_home", "notify.mobile_app_phone_away",
            "notify.mobile_app_tablet"])

    def test_zone_skips_devices_that_are_away(self):
        self.assertEqual(self.notify_list(notify_zone="zone.home"), [
            "notify.mobile_app_phone_home", "notify.mobile_app_tablet"])

    def test_invalid_service_entries_are_dropped(self):
        r = self.notify_list(
            notify_services="notify.Family, telegram, notify.a b, notify.mobile_app_phone_home")
        self.assertEqual(r[-1], "notify.family")
        self.assertEqual(r.count("notify.mobile_app_phone_home"), 1)
        self.assertNotIn("telegram", r)
        self.assertNotIn("notify.a b", r)
        self.assertEqual(len(r), len(set(r)))


class AreaSensors(unittest.TestCase):
    def test_air_quality_types_are_not_averaged(self):
        pm = sensor("sensor.pm", 8, "pm25")
        voc = sensor("sensor.voc", 300, "volatile_organic_compounds")
        r = evaluate([window(), pm, voc], dict(BASE, area="area.office"),
                     area_ents=["sensor.pm", "sensor.voc"])
        self.assertEqual(r["aq_inside"], ["sensor.pm"])
        self.assertEqual(r["aq_in"], 8.0)

    def test_sensors_outside_the_area_are_ignored(self):
        t1 = sensor("sensor.t1", 20, "temperature", "°C")
        t2 = sensor("sensor.t2", 30, "temperature", "°C")
        r = evaluate([window(), t1, t2],
                     dict(BASE, area="area.office", temp_inside=["sensor.t1", "sensor.t2"]),
                     area_ents=["sensor.t1"])
        self.assertEqual(r["t_in"], 20.0)


if __name__ == "__main__":
    unittest.main()
