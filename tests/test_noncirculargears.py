# -*- coding: utf-8 -*-
"""Headless checks for the non-circular gear pair.

Run with the packaged interpreter, which is what puts the addons on the path::

    freecadcmd tests/test_noncirculargears.py

What the workbench is for is checked rather than assumed: the pitch lines are
walked through a whole revolution, and the teeth are measured against each
other over one too.
"""

import math
import os
import sys
import traceback

# A run is not worth taking the machine over for, so it is held to a share of
# the cores. Three things thread underneath and only one of them can be asked
# politely - ncgears takes the core count as its own, the numeric stack reads
# the environment when it is imported, and OCC meshes on a pool with no knob
# on it at all - so the share is pinned rather than requested, and the other
# two are told the same number only to stop them oversubscribing what is left.
CPU_SHARE = 0.4
WORKERS = max(1, int((os.cpu_count() or 1) * CPU_SHARE))
for _limit in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
):
    os.environ[_limit] = str(WORKERS)

if hasattr(os, "sched_setaffinity"):
    os.sched_setaffinity(0, set(sorted(os.sched_getaffinity(0))[:WORKERS]))

# Redirected to a file, print would otherwise hold a whole run's results in a
# buffer, and a crash in OCC takes the lot with it rather than the line before.
sys.stdout.reconfigure(line_buffering=True)

import numpy as np

import FreeCAD as App

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide import QtWidgets  # noqa: E402, after the platform is chosen

from freecad.noncirculargears import dependencies, involute, noncircular
from freecad.noncirculargears.commands import CreateNonCircularGearPair
from freecad.noncirculargears.noncirculargear import solve
from freecad.noncirculargears.taskpanel import GearPairPanel, parameters


def hold_ncgears_to(workers):
    """Keep an involute cut inside ``workers`` threads.

    ncgears takes the machine's core count as its own and offers no way to say
    otherwise, so the count it reads is what has to be set. Left alone it puts
    a run of these checks at 85% of the machine.
    """
    try:
        from ncgears import engine
    except ImportError:
        return
    engine._MAX_GEOMETRY_WORKERS = workers


hold_ncgears_to(WORKERS)

FAILURES = []


def check(name, condition, detail=""):
    status = "ok  " if condition else "FAIL"
    print("%s %-52s %s" % (status, name, detail))
    if not condition:
        FAILURES.append(name)


def make_pair(document, **overrides):
    """A pair with wave teeth unless asked otherwise.

    Most of these checks are about the pitch lines and the wave laid on them,
    and an involute cut costs seconds each, so the style a new gear really
    starts on is checked once rather than paid for throughout.
    """
    overrides.setdefault("tooth_style", "wave")
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


INVOLUTE_CASES = (
    ("", {}),
    (", a mate that turns twice", {"function": "1 + 0.45 * cos(2 * x)", "mate_turns": 2}),
    (", a mate that turns half as often", {"driver_turns": 2}),
    (
        ", from a pitch radius",
        {"mode": "pitch radius", "function": "30 - 6 * cos(x)"},
    ),
)


def test_involute_teeth(document):
    """Involute flanks, which ncgears cuts and this workbench only places.

    What is checked here is the part this workbench is answerable for: that the
    pair comes back at the centre distance and tooth counts asked for, that it
    builds, and that ncgears' own reading of the flanks it cut is carried
    through to the gear. How conjugate the flanks are is ncgears' measurement,
    not one repeated here - the sweep this workbench uses on wave teeth reads an
    outline as a radius against an angle, which a flank with a fillet under it
    is not.
    """
    if not involute.available():
        print("--   involute checks skipped: ncgears is not installed")
        return

    for label, overrides in INVOLUTE_CASES:
        driver, mate = make_pair(document, tooth_style="involute", **overrides)
        pair, distance, _ = solve(driver)

        check(
            "involute driver builds a valid solid" + label,
            driver.Shape.ShapeType == "Solid" and driver.Shape.isValid(),
            driver.Shape.ShapeType,
        )
        check(
            "involute mate builds a valid solid" + label,
            mate.Shape.ShapeType == "Solid" and mate.Shape.isValid(),
            mate.Shape.ShapeType,
        )

        tooth = tooth_size(driver, pair)
        check(
            "the involute driver was cut with the teeth it should have" + label,
            count_teeth(driver, tooth) == driver.num_teeth,
            "%d, expected %d" % (count_teeth(driver, tooth), driver.num_teeth),
        )
        check(
            "the involute mate was cut with mate_teeth" + label,
            count_teeth(mate, tooth) == driver.mate_teeth,
            "%d, expected %d" % (count_teeth(mate, tooth), driver.mate_teeth),
        )
        check(
            "the involute pair came back at the centre distance solved for" + label,
            abs(driver.solved_center_distance.Value - distance) < 1e-6,
            "%.9f against %.9f" % (driver.solved_center_distance.Value, distance),
        )
        check(
            "ncgears reports the flanks as conjugate" + label,
            0.0 < driver.transmission_error < 1e-4,
            "%.3g degrees of transmission error" % driver.transmission_error,
        )
        check(
            "the wave measure is left alone for involute teeth" + label,
            driver.tooth_interference.Value == 0.0,
            "%.6f" % driver.tooth_interference.Value,
        )

        document.removeObject(mate.Name)
        document.removeObject(driver.Name)


def test_involute_thinning(document):
    """The thinning ncgears' outlines go through, on one built to break it.

    Driven straight rather than through a gear, because what it has to cope
    with is what ncgears hands over - repeated points, a stretch sampled far
    more finely than the rest, and a stretch barely sampled at all - and a gear
    that happens not to have all three would not say whether it copes.
    """
    if not involute.available():
        return

    angle = np.linspace(0.0, 2.0 * np.pi, 240, endpoint=False)
    ring = np.column_stack((20.0 * np.cos(angle), 20.0 * np.sin(angle)))
    outline = np.vstack(
        (
            np.repeat(ring[:30], 4, axis=0),  # every point four times over
            ring[30:200],
            ring[200:201],  # and then a long way round to the start
        )
    )
    thinned = involute._thinned(outline, 0.01, 0.4, 1.5)
    steps = np.linalg.norm(np.diff(np.vstack((thinned, thinned[:1])), axis=0), axis=1)

    check(
        "thinning hands back no point twice",
        steps.min() > 0.0,
        "shortest step %.3e mm" % steps.min(),
    )
    check(
        "thinning leaves every point on the outline it was given",
        all(
            np.abs(outline - point).sum(axis=1).min() == 0.0 for point in thinned
        ),
    )
    check(
        "thinning keeps the whole of the outline, not part of it",
        len(thinned) > 30,
        "%d points from %d" % (len(thinned), len(outline)),
    )


def test_involute_refusals(document):
    """What involute teeth cannot be asked for, and whether it is said plainly."""
    if not involute.available():
        return

    driver, mate = make_pair(
        document, tooth_style="involute", function="1 + 0.4 * min(cos(x), 0.5)"
    )
    check(
        "an f(x) SymPy cannot read is refused rather than drawn",
        "Invalid" in driver.State or "Touched" in driver.State,
        driver.State,
    )
    document.removeObject(mate.Name)
    document.removeObject(driver.Name)

    driver, mate = make_pair(document, tooth_style="involute", tooth_height=0.0)
    check(
        "involute teeth with no height are refused",
        "Invalid" in driver.State or "Touched" in driver.State,
        driver.State,
    )
    document.removeObject(mate.Name)
    document.removeObject(driver.Name)


def test_involute_says_what_is_missing(document):
    """Without ncgears the wave teeth still work and the message names the package."""
    blocked = dict(sys.modules)
    sys.modules["ncgears"] = None
    try:
        check(
            "involute teeth report themselves unavailable without ncgears",
            not involute.available(),
        )
        try:
            involute.outlines(None, "1", "gear ratio", 60.0, 1.0, 24, 0.14, 0.0, 20.0, 1024)
        except involute.InvoluteUnavailable as err:
            named = "ncgears" in str(err)
        else:
            named = False
        check("the message names the package to install", named)
        # Parameters of its own, so what follows is this pair being cut rather
        # than one cut earlier, while ncgears was there, being handed back.
        refused, mate = CreateNonCircularGearPair.create()
        refused.function = "1 + 0.37 * cos(x)"
        document.recompute()
        check(
            "a new pair asks for involute teeth whether ncgears is here or not",
            refused.tooth_style == "involute",
            refused.tooth_style,
        )
        check(
            "and refuses to build rather than standing a wave tooth in for one",
            "Invalid" in refused.State or "Touched" in refused.State,
            refused.State,
        )
    finally:
        sys.modules.clear()
        sys.modules.update(blocked)

    if involute.available():
        refused.touch()
        document.recompute()
        check(
            "installing ncgears is enough for the same gear to cut",
            "Invalid" not in refused.State and refused.Shape.isValid(),
            refused.State,
        )
    document.removeObject(mate.Name)
    document.removeObject(refused.Name)

    driver, mate = make_pair(document)
    check(
        "wave teeth are unaffected by ncgears being absent",
        "Invalid" not in driver.State and "Invalid" not in mate.State,
        driver.State,
    )
    document.removeObject(mate.Name)
    document.removeObject(driver.Name)


def tooth_size(driver, pair):
    """How tall a tooth is, in mm, for the pair the driver's parameters solved to."""
    per_period = noncircular.teeth_per_period(pair, driver.num_teeth)
    return driver.tooth_height * pair.arc_length / per_period


def test_teeth_clear(document, driver, mate, label="", bound=0.02):
    """The teeth are a wave on the pitch lines, so they are checked, not assumed."""
    pair, _, _ = solve(driver)
    tooth = tooth_size(driver, pair)

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


def test_involute_follows_the_pitch_line(document):
    """The gear ncgears cuts stands where this workbench's own pitch line says.

    ncgears walks the centrode the other way round than this workbench does,
    so what it hands back has to be reflected in the line of centres before it
    is drawn. An even f(x) hides that, and every other f(x) in this file is
    even, so this one is not.
    """
    if not involute.available():
        return

    driver, mate = make_pair(
        document,
        tooth_style="involute",
        function="1 + 0.35 * cos(x) + 0.22 * sin(2 * x)",
    )
    pair, _, _ = solve(driver)
    tooth = tooth_size(driver, pair)
    outline = min(driver.Shape.Faces, key=lambda face: face.CenterOfMass.z).OuterWire
    points = outline.discretize(Number=4000)
    angle = np.array(
        [math.atan2(point.y, point.x) % (2.0 * math.pi) for point in points]
    )
    radius = np.array([math.hypot(point.x, point.y) for point in points])
    stands_at = np.interp(
        angle,
        np.append(pair.theta, 2.0 * math.pi),
        np.append(pair.radius1, pair.radius1[0]),
    )
    worst = float(np.abs(radius - stands_at).max())
    check(
        "involute teeth stand on the pitch line f(x) solved to",
        worst < 2.0 * tooth,
        "%.4f mm off a %.4f mm tooth, whose root goes 1.25 of one down"
        % (worst, tooth),
    )
    document.removeObject(mate.Name)
    document.removeObject(driver.Name)


def test_creation_dialog(document):
    """The dialog the Gear Pair button opens, driven rather than described.

    Its widgets are made and read here the way the dialog itself does, which is
    everything about it apart from the click - a row for every parameter, values
    that reach the gear, a refusal that says why, and a cancel that takes the
    pair back out of the document.
    """
    qt_running()

    document.openTransaction("dialog")
    driver, mate = CreateNonCircularGearPair.create()
    # Wave teeth: what is checked here is the dialog, and cutting involute
    # flanks for each value typed into it would be seconds a row.
    driver.tooth_style = "wave"
    document.recompute()
    panel = GearPairPanel(driver, mate)
    rows = dict((row.name, row) for row in panel.rows)

    check(
        "the dialog has a row for each of the gear's own parameters",
        sorted(rows) == sorted(parameters(driver)),
        "%d rows: %s" % (len(rows), ", ".join(row.name for row in panel.rows)),
    )
    check(
        "each row starts on what the gear is set to",
        rows["function"].read() == driver.function
        and rows["num_teeth"].read() == driver.num_teeth
        and rows["center_distance"].read() == driver.center_distance.UserString,
        "%r, %d teeth, %s"
        % (rows["function"].read(), rows["num_teeth"].read(), rows["center_distance"].read()),
    )

    # The dropdown is the one row whose signal carries a value, and it reaches a
    # handler that takes none, so it is changed on its own and through the signal.
    rows["mode"].widget.setCurrentText("pitch radius")
    check(
        "changing a row rebuilds the pair without being asked to",
        driver.mode == "pitch radius" and driver.ratio_scale == 1.0,
        "%s, scale %g" % (driver.mode, driver.ratio_scale),
    )
    rows["mode"].widget.setCurrentText("gear ratio")

    rows["function"].widget.setText("1 + 0.45 * cos(2 * x)")
    rows["mate_turns"].widget.setValue(2)
    rows["center_distance"].widget.setText("80 mm")
    panel.apply()
    check(
        "what is typed into the dialog reaches the gear and rebuilds it",
        driver.function == "1 + 0.45 * cos(2 * x)"
        and driver.mate_turns == 2
        and driver.mate_teeth == 12
        and abs(driver.solved_center_distance.Value - 80.0) < 1e-9
        and "Invalid" not in driver.State,
        "%s, %d mate teeth, %s" % (driver.function, driver.mate_teeth, driver.State),
    )

    rows["num_teeth"].widget.setValue(25)
    panel.apply()
    check(
        "a pair that cannot be built says so in the dialog",
        "multiple of 2" in panel.status.text(),
        repr(panel.status.text()),
    )

    rows["num_teeth"].widget.setValue(100000)
    panel.apply()
    check(
        "a value past what the property allows comes back clamped",
        driver.num_teeth == 400 and rows["num_teeth"].read() == 400,
        "%d on the gear, %d in the dialog" % (driver.num_teeth, rows["num_teeth"].read()),
    )

    names = [driver.Name, mate.Name]
    check("cancelling the dialog closes it", panel.reject() is True)
    check(
        "cancelling takes the pair back out of a document with no undo",
        all(document.getObject(name) is None for name in names),
        ", ".join(obj.Name for obj in document.Objects),
    )

    # The GUI has undo on, so cancelling there aborts the command's transaction
    # rather than falling back on removing what it made.
    document.UndoMode = 1
    document.openTransaction("dialog")
    driver, mate = CreateNonCircularGearPair.create()
    # Wave teeth: what is checked here is the dialog, and cutting involute
    # flanks for each value typed into it would be seconds a row.
    driver.tooth_style = "wave"
    document.recompute()
    names = [driver.Name, mate.Name]
    GearPairPanel(driver, mate).reject()
    # Whatever comes next has to land in a transaction of its own, which it
    # cannot if cancelling removed the pair but left the command's still open.
    document.openTransaction("after cancelling")
    document.addObject("App::FeaturePython", "probe")
    document.commitTransaction()
    check(
        "cancelling aborts the transaction where there is one to abort",
        all(document.getObject(name) is None for name in names)
        and document.UndoNames == ["after cancelling"],
        "%s left, undo stack %s"
        % (", ".join(obj.Name for obj in document.Objects), document.UndoNames),
    )
    document.removeObject("probe")
    document.UndoMode = 0

    document.openTransaction("dialog")
    driver, mate = CreateNonCircularGearPair.create()
    # Wave teeth: what is checked here is the dialog, and cutting involute
    # flanks for each value typed into it would be seconds a row.
    driver.tooth_style = "wave"
    document.recompute()
    panel = GearPairPanel(driver, mate)
    check("accepting the dialog closes it", panel.accept() is True)
    check(
        "accepting leaves the pair in the document, built",
        document.getObject(driver.Name) is not None
        and driver.Shape.ShapeType == "Solid"
        and mate.Shape.ShapeType == "Solid",
        "%s and %s" % (driver.State, mate.State),
    )
    document.removeObject(mate.Name)
    document.removeObject(driver.Name)


def prominences(radius):
    """How far each local maximum of a closed series stands above its surroundings.

    Each maximum is walked away from in both directions until the series rises
    above it again, and it is credited with the deeper of the two lowest points
    reached. Carrying on to a higher maximum rather than stopping at the first
    dip is what makes this immune to a lone spurious extremum beside a real
    one: a sampling that lands on the seam of the wire leaves exactly that, and
    reading the dip next door would report a whole tooth as flat.
    """
    count = len(radius)
    peaks = np.flatnonzero(
        (radius > np.roll(radius, 1)) & (radius >= np.roll(radius, -1))
    )
    found = []
    for peak in peaks:
        cols = []
        for step in (1, -1):
            lowest = radius[peak]
            index = peak
            for _ in range(count):
                index = (index + step) % count
                if radius[index] > radius[peak]:
                    break
                lowest = min(lowest, radius[index])
            cols.append(lowest)
        found.append(radius[peak] - max(cols))
    return np.array(found)


def count_teeth(gear, tooth, samples=6400):
    """Teeth on the built shape, counted as maxima of its outline's radius.

    Read off the solid rather than the arrays that made it, so a shape built
    with the wrong tooth count cannot pass. The default is sixteen points per
    tooth at the most teeth the workbench allows.

    A maximum has to stand a tenth of ``tooth`` above its surroundings to
    count, which is what separates a tooth from the extremum a sampling leaves
    where the outline's splines meet.
    """
    outline = min(gear.Shape.Faces, key=lambda face: face.CenterOfMass.z).OuterWire
    center = gear.Placement.Base
    points = outline.discretize(Number=samples)
    radius = np.array([(point - center).Length for point in points])
    return int(np.sum(prominences(radius) > 0.1 * tooth))


def qt_running():
    """The QApplication the dialog checks build their widgets in."""
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def counting_cuts():
    """``involute.outlines`` with a tally of how often it was reached."""
    cuts = []
    original = involute.outlines

    def counted(*arguments, **keywords):
        cuts.append(1)
        return original(*arguments, **keywords)

    return cuts, counted, original


def test_involute_is_cut_once(document):
    """An involute outline is cut once, however many times it is asked for.

    A cut takes seconds, so a pair rebuilt - by its second gear, by a style
    gone back to - must not pay again for one it already has. A refusal is
    kept the same way: a pair too slow to cut is too slow to refuse twice.
    """
    if not involute.available():
        print("--   involute cut checks skipped: ncgears is not installed")
        return

    cuts, counted, original = counting_cuts()
    involute.outlines = counted
    try:
        # Parameters of its own, so this is a cut rather than one handed back.
        driver, mate = make_pair(
            document, tooth_style="involute", function="1 + 0.31 * cos(x)"
        )
        check(
            "a pair is cut once, not once for each of the two gears drawn from it",
            len(cuts) == 1,
            "%d cut(s)" % len(cuts),
        )
        check(
            "both gears are built from that one cut",
            driver.Shape.isValid() and mate.Shape.isValid(),
            "%s and %s" % (driver.Shape.ShapeType, mate.Shape.ShapeType),
        )

        driver.tooth_style = "wave"
        document.recompute()
        driver.tooth_style = "involute"
        document.recompute()
        check(
            "an outline already cut is not cut a second time",
            len(cuts) == 1,
            "%d cut(s) after going back to wave and forward again" % len(cuts),
        )

        # A tooth of no height has no flank to cut, so involute refuses it.
        driver.tooth_height = 0.0
        document.recompute()
        check(
            "a refusal is arrived at once, not once per gear that asks",
            len(cuts) == 2,
            "%d cut(s), so %d attempt(s) at the refusal" % (len(cuts), len(cuts) - 1),
        )
    finally:
        involute.outlines = original
    document.removeObject(mate.Name)
    document.removeObject(driver.Name)


def test_what_is_fetched_is_what_is_absent(document):
    """The workbench only goes looking for packages that are not already here.

    Fetching them is the GUI's business and is not done from a script, so what
    a run can check is the reading the fetching is decided on - which is also
    the reading that must not be fooled by ncgears being blocked, since that is
    how the rest of these checks stand in for it not being installed.
    """
    try:
        import ncgears  # noqa: F401, imported to find out whether it is there
        importable = True
    except ImportError:
        importable = False
    check(
        "nothing is reported absent when ncgears is importable",
        dependencies.missing() == ([] if importable else ["ncgears"]),
        "%s, importable %s" % (dependencies.missing(), importable),
    )

    blocked = dict(sys.modules)
    sys.modules["ncgears"] = None
    try:
        check(
            "ncgears is reported absent when it cannot be imported",
            dependencies.missing() == ["ncgears"],
            str(dependencies.missing()),
        )
    finally:
        sys.modules.clear()
        sys.modules.update(blocked)


def test_new_pairs_are_involute(document):
    """A new pair starts on involute teeth, which is what a pair is worth having."""
    driver, mate = CreateNonCircularGearPair.create()
    document.recompute()
    check(
        "a new pair starts on involute teeth",
        driver.tooth_style == "involute",
        driver.tooth_style,
    )
    if not involute.available():
        print("--   the rest of the default check needs ncgears")
        document.removeObject(mate.Name)
        document.removeObject(driver.Name)
        return
    check(
        "and builds on them without being asked twice",
        driver.Shape.isValid() and mate.Shape.isValid()
        and driver.transmission_error > 0.0,
        "%s, error %.3g deg" % (driver.Shape.ShapeType, driver.transmission_error),
    )
    document.removeObject(mate.Name)
    document.removeObject(driver.Name)


def main():
    document = App.newDocument("noncircular")
    driver, mate = test_default_pair(document)
    test_pitch_lines_roll(document, driver, mate)
    test_teeth_clear(document, driver, mate)
    test_pitch_radius_mode(document)
    test_turns(document)
    test_rejects_bad_functions(document)
    test_rejects_impossible_turns(document)
    test_involute_teeth(document)
    test_involute_thinning(document)
    test_involute_refusals(document)
    test_involute_says_what_is_missing(document)
    test_involute_follows_the_pitch_line(document)
    test_creation_dialog(document)
    test_involute_is_cut_once(document)
    test_new_pairs_are_involute(document)
    test_what_is_fetched_is_what_is_absent(document)

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
