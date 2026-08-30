# -*- coding: utf-8 -*-
"""Headless checks for the non-circular gear pair.

Run with the packaged interpreter, which is what puts the addons on the path::

    freecadcmd tests/test_noncirculargears.py

What the workbench is for is checked rather than assumed: the pitch lines are
walked through a whole revolution, and the teeth are measured against each
other over one too.
"""

import math
import sys
import traceback

import numpy as np

import FreeCAD as App

from freecad.noncirculargears import noncircular
from freecad.noncirculargears.commands import CreateNonCircularGearPair
from freecad.noncirculargears.noncirculargear import solve

FAILURES = []


def check(name, condition, detail=""):
    status = "ok  " if condition else "FAIL"
    print("%s %-52s %s" % (status, name, detail))
    if not condition:
        FAILURES.append(name)


def make_pair(document, **overrides):
    driver, mate = CreateNonCircularGearPair.create()
    for key, value in overrides.items():
        setattr(driver, key, value)
    document.recompute()
    return driver, mate


def test_default_pair(document):
    driver, mate = make_pair(document)

    check(
        "driver recomputes without error", "Invalid" not in driver.State, driver.State
    )
    check("mate recomputes without error", "Invalid" not in mate.State, mate.State)
    check(
        "driver is a solid", driver.Shape.ShapeType == "Solid", driver.Shape.ShapeType
    )
    check("mate is a solid", mate.Shape.ShapeType == "Solid", mate.Shape.ShapeType)
    check("driver shape is valid", driver.Shape.isValid())
    check("mate shape is valid", mate.Shape.isValid())

    height = driver.height.Value
    for name, gear in (("driver", driver), ("mate", mate)):
        box = gear.Shape.BoundBox
        check(
            "%s is extruded to the set height" % name,
            abs(box.ZLength - height) < 1e-6,
            "%.4f mm" % box.ZLength,
        )

    driver.height = "0 mm"
    document.recompute()
    check(
        "height 0 leaves the bare outline on both gears",
        driver.Shape.ShapeType == "Wire" and mate.Shape.ShapeType == "Wire",
        "%s and %s" % (driver.Shape.ShapeType, mate.Shape.ShapeType),
    )
    driver.height = "%f mm" % height
    document.recompute()

    check(
        "the ratio was scaled to close gear 2",
        abs(driver.ratio_scale - 1.0 / math.sqrt(1.0 - 0.55**2)) < 1e-6,
        "scale %.9f" % driver.ratio_scale,
    )
    check(
        "the reported ratio spans a real variation",
        driver.max_ratio / driver.min_ratio > 3.0,
        "%.4f .. %.4f" % (driver.min_ratio, driver.max_ratio),
    )
    check(
        "the pair is drawn at the given center distance",
        abs(driver.solved_center_distance.Value - driver.center_distance.Value) < 1e-9,
        "%.4f mm" % driver.solved_center_distance.Value,
    )
    check(
        "the mate sits on the line of centres, turned to face",
        abs(mate.Placement.Base.x - driver.solved_center_distance.Value) < 1e-9
        and abs(mate.Placement.Base.y) < 1e-9
        and abs(mate.Placement.Rotation.Angle - math.pi) < 1e-9,
        str(mate.Placement),
    )
    return driver, mate


def test_pitch_radius_mode(document):
    """A pitch radius drawn as given, with the center distance solved for."""
    driver, mate = make_pair(
        document,
        mode="pitch radius",
        function="30 - 9 * cos(x)",
        center_distance="1 mm",
    )
    check("pitch radius mode recomputes", "Invalid" not in driver.State, driver.State)
    check(
        "the center distance was solved for, not taken from the property",
        driver.solved_center_distance.Value > 40.0,
        "solved %.6f mm, property %.3f mm"
        % (driver.solved_center_distance.Value, driver.center_distance.Value),
    )
    check("pitch radius mode leaves f(x) unscaled", driver.ratio_scale == 1.0)

    samples = noncircular.sample_function(driver.function, driver.samples)
    solved, distance = noncircular.from_radius(samples)
    check(
        "the drawn pitch radius is the one that was asked for",
        np.abs(solved.radius1 - samples).max() < 1e-9,
        "max deviation %.3g mm" % np.abs(solved.radius1 - samples).max(),
    )
    check(
        "gear 2 closes at the solved distance",
        abs(solved.closure_error) < 1e-9,
        "closure error %.3g turns" % solved.closure_error,
    )
    check(
        "the mate follows the solved distance",
        abs(mate.Placement.Base.x - distance) < 1e-6,
        "%.6f mm" % mate.Placement.Base.x,
    )
    return driver, mate


def test_rejects_bad_functions(document):
    for expression, why in (
        ("1 - 2 * cos(x)", "goes negative"),
        ("cos(x) +", "does not parse"),
        ("1 / (cos(x) - 1)", "is not finite"),
        ("__import__('os').getcwd()", "reaches outside the math module"),
    ):
        driver, _ = make_pair(document, function=expression)
        check(
            "f(x) that %s is refused: %r" % (why, expression),
            "Invalid" in driver.State or "Touched" in driver.State,
            driver.State,
        )
        document.removeObject(driver.Name)


def test_pitch_lines_roll(document, driver, mate, label=""):
    """Roll the pair through a period and check the pitch lines keep contact.

    The pitch point of each gear must be the same world point at every rolling
    position, and the delivered ratio must be the f(x) that was asked for. This
    is the part the workbench gets exactly right; the teeth are checked against
    a tolerance separately.
    """
    pair, distance, _ = solve(driver)

    # Gear 1 turned by -theta brings its pitch point to (r1, 0); gear 2 turned
    # by pi + phi2 brings its own to a - r2. They have to be the same point.
    separation = np.abs(pair.radius1 - (distance - pair.radius2)).max()
    check(
        "the two pitch points meet on the line of centres" + label,
        separation < 1e-9,
        "worst separation %.3g mm" % separation,
    )

    turn1, turn2 = -pair.theta, math.pi + pair.angle2
    delivered = np.gradient(turn1) / np.gradient(turn2)
    inner = slice(2, -2)
    error = np.abs(delivered[inner] / -pair.ratio[inner] - 1.0).max()
    check(
        "the delivered ratio is the f(x) that was asked for, counter-rotating" + label,
        error < 1e-4
        and np.all(np.gradient(turn1)[inner] * np.gradient(turn2)[inner] < 0),
        "worst relative error %.3g" % error,
    )


def delivered_turns(driver):
    """Turns the mate makes per turn of the driver, integrated from f(x) as drawn.

    Taken from the property and the reported scale rather than from the solver,
    so a pair that quietly closes on a different number of turns than it was
    asked for cannot pass.
    """
    values = noncircular.sample_function(driver.function, driver.samples)
    if driver.mode == "pitch radius":
        ratio = (driver.solved_center_distance.Value - values) / values
    else:
        ratio = driver.ratio_scale * values
    step = 2.0 * math.pi / len(ratio)
    swept = 0.5 * (1.0 / ratio + np.roll(1.0 / ratio, -1)) * step
    return float(swept.sum()) / (2.0 * math.pi)


TURN_CASES = (
    ("a mate that turns twice", {"function": "1 + 0.45 * cos(2 * x)", "mate_turns": 2}),
    ("a mate that turns half as often", {"driver_turns": 2}),
    (
        "a mate that turns three times for every two",
        {"function": "1 + 0.3 * cos(3 * x)", "mate_turns": 3, "driver_turns": 2},
    ),
    (
        "a pitch radius whose mate turns twice",
        {"mode": "pitch radius", "function": "30 - 6 * cos(2 * x)", "mate_turns": 2},
    ),
)


def test_turns(document):
    """Pairs asked to turn at something other than 1:1 on average.

    The turns are read back out of the drawn pair - what f(x) integrates to and
    how many teeth each shape came out with - rather than off the properties
    that asked for them.
    """
    for name, overrides in TURN_CASES:
        driver, mate = make_pair(document, **overrides)
        label = ", %s" % name
        check(
            "%s recomputes" % name,
            "Invalid" not in driver.State and "Invalid" not in mate.State,
            "%s and %s" % (driver.State, mate.State),
        )
        if "Invalid" in driver.State or "Invalid" in mate.State:
            continue

        wanted = float(driver.mate_turns) / driver.driver_turns
        turns = delivered_turns(driver)
        check(
            "the mate is drawn turning %g times per turn of the driver" % wanted,
            abs(turns - wanted) < 1e-9,
            "%.12f turns" % turns,
        )
        check(
            "the two tooth counts share one pitch%s" % label,
            abs(driver.mate_teeth * wanted - driver.num_teeth) < 1e-9,
            "%d teeth against %d" % (driver.num_teeth, driver.mate_teeth),
        )
        test_pitch_lines_roll(document, driver, mate, label)
        test_teeth_clear(document, driver, mate, label, bound=0.05)
        document.removeObject(mate.Name)
        document.removeObject(driver.Name)


def test_rejects_impossible_turns(document):
    """Turns that no pair can be drawn at, refused rather than drawn wrong."""
    for overrides, why in (
        ({"mate_turns": 2}, "f(x) does not repeat twice over the turn"),
        (
            {"function": "1 + 0.45 * cos(2 * x)", "mate_turns": 2, "num_teeth": 25},
            "num_teeth cannot be split between the driver's periods",
        ),
    ):
        driver, mate = make_pair(document, **overrides)
        check(
            "refused because %s" % why,
            "Invalid" in driver.State,
            driver.State,
        )
        document.removeObject(mate.Name)
        document.removeObject(driver.Name)


def tooth_height(driver, pair):
    """How tall a tooth is, in mm, for the pair the driver's parameters solved to."""
    per_period = noncircular.teeth_per_period(pair, driver.num_teeth)
    return driver.tooth_height * pair.arc_length / per_period


def test_teeth_clear(document, driver, mate, label="", bound=0.02):
    """The teeth are a wave on the pitch lines, so they are checked, not assumed."""
    pair, _, _ = solve(driver)
    tooth = tooth_height(driver, pair)

    check(
        "the teeth barely graze each other with no backlash" + label,
        0.0 < driver.tooth_interference.Value < bound * tooth,
        "%.4f mm into a %.3f mm tooth (%.2f%%)"
        % (
            driver.tooth_interference.Value,
            tooth,
            100.0 * driver.tooth_interference.Value / tooth,
        ),
    )

    driver.backlash = "0.1 mm"
    document.recompute()
    check(
        "backlash holds the teeth apart" + label,
        driver.tooth_interference.Value < 0.0,
        "%.4f mm" % driver.tooth_interference.Value,
    )
    driver.backlash = "0 mm"
    document.recompute()

    for name, gear, expected in (
        ("driver", driver, driver.num_teeth),
        ("mate", mate, driver.mate_teeth),
    ):
        counted = count_teeth(gear, tooth)
        check(
            "the %s was cut with the number of teeth it is meant to have%s"
            % (name, label),
            counted == expected,
            "%d teeth on the built shape, %d expected" % (counted, expected),
        )

    separation = driver.Shape.distToShape(mate.Shape)[0]
    check(
        "the two solids are drawn touching, not apart" + label,
        separation < 1e-6,
        "%.3g mm between them" % separation,
    )


def count_teeth(gear, tooth, samples=6400):
    """Teeth on the built shape, counted as maxima of its outline's radius.

    Read off the solid rather than the arrays that made it, so a shape built
    with the wrong tooth count cannot pass. The default is sixteen points per
    tooth at the most teeth the workbench allows.

    A maximum has to stand a tenth of ``tooth`` above the outline either side of
    it to count: the spline through a gear built in periods puts a maximum of a
    few times 1e-15 mm at each join between them, which is a tooth to nobody.
    """
    outline = min(gear.Shape.Faces, key=lambda face: face.CenterOfMass.z).OuterWire
    center = gear.Placement.Base
    points = outline.discretize(Number=samples)
    radius = np.array([(point - center).Length for point in points])
    rising = radius > np.roll(radius, 1)
    peaks = np.flatnonzero(rising & (radius >= np.roll(radius, -1)))
    valleys = np.flatnonzero(~rising & (radius <= np.roll(radius, -1)))
    after = np.searchsorted(valleys, peaks)
    # index -1 and index len are the valleys the closed outline wraps around to
    shoulder = np.maximum(radius[valleys[after - 1]], radius[valleys[after % len(valleys)]])
    return int(np.sum(radius[peaks] - shoulder > 0.1 * tooth))


def main():
    document = App.newDocument("noncircular")
    driver, mate = test_default_pair(document)
    test_pitch_lines_roll(document, driver, mate)
    test_teeth_clear(document, driver, mate)
    test_pitch_radius_mode(document)
    test_turns(document)
    test_rejects_bad_functions(document)
    test_rejects_impossible_turns(document)

    if FAILURES:
        print("\n%d check(s) failed: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("\nall checks passed")
    return 0


# freecadcmd execs this file under a name of its own, so there is no
# __main__ guard to hang the run off.
try:
    STATUS = main()
except Exception:
    traceback.print_exc()
    STATUS = 2
sys.stdout.flush()
sys.exit(STATUS)
