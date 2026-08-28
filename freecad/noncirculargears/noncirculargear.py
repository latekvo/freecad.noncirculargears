# -*- coding: utf-8 -*-
# ***************************************************************************
# *                                                                         *
# * This program is free software: you can redistribute it and/or modify    *
# * it under the terms of the GNU General Public License as published by    *
# * the Free Software Foundation, either version 3 of the License, or       *
# * (at your option) any later version.                                     *
# *                                                                         *
# * This program is distributed in the hope that it will be useful,         *
# * but WITHOUT ANY WARRANTY; without even the implied warranty of          *
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the           *
# * GNU General Public License for more details.                            *
# *                                                                         *
# * You should have received a copy of the GNU General Public License       *
# * along with this program.  If not, see <http://www.gnu.org/licenses/>.   *
# *                                                                         *
# ***************************************************************************

"""The two document objects of a non-circular gear pair.

``NonCircularGear`` carries the parameters and draws the driving gear.
``NonCircularGearMate`` links to one and draws the gear that meshes with it,
placing itself on the line of centres in the position the two are drawn for.
"""

from freecad import app
from freecad import part
from freecad.gears.basegear import BaseGear, fcvec

from . import __version__
from . import noncircular

QT_TRANSLATE_NOOP = app.Qt.QT_TRANSLATE_NOOP

MODES = ["gear ratio", "pitch radius"]


def stamp_version(obj):
    """Own the ``version`` property BaseGear adds, which it fills with its own."""
    obj.version = __version__
    obj.setDocumentationOfProperty(
        "version",
        QT_TRANSLATE_NOOP("App::Property", "freecad.noncirculargears version"),
    )


def solve(obj):
    """The pitch pair for ``obj``'s parameters, its center distance and ratio scale."""
    values = noncircular.sample_function(obj.function, obj.samples)
    if obj.mode == "pitch radius":
        pair, distance = noncircular.from_radius(values)
        return pair, distance, 1.0
    pair, scale = noncircular.from_ratio(values, obj.center_distance.Value)
    return pair, obj.center_distance.Value, scale


def profiles(obj, pair):
    """Both gears' outlines for the parameters on ``obj``."""
    return noncircular.tooth_profiles(
        pair,
        obj.num_teeth,
        obj.points_per_tooth,
        obj.tooth_height,
        obj.backlash.Value,
    )


def make_shape(points, height):
    """A closed outline through ``points``, extruded when ``height`` is set."""
    curve = part.BSplineCurve()
    curve.interpolate(Points=[fcvec(point) for point in points], PeriodicFlag=True)
    wire = part.Wire(curve.toShape())
    if height <= 0.0:
        return wire
    return part.Face(wire).extrude(app.Vector(0.0, 0.0, height))


class NonCircularGear(BaseGear):
    """The driving gear of a non-circular pair."""

    def __init__(self, obj):
        super(NonCircularGear, self).__init__(obj)
        stamp_version(obj)
        obj.addProperty(
            "App::PropertyEnumeration",
            "mode",
            "base",
            QT_TRANSLATE_NOOP("App::Property", "what f(x) states about this gear"),
        )
        obj.mode = MODES
        obj.addProperty(
            "App::PropertyString",
            "function",
            "base",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "f(x) over one turn, x in radians from 0 to 2*pi; the math module's "
                "names are in scope. Must stay above zero",
            ),
        ).function = "1 + 0.55 * cos(x)"
        obj.addProperty(
            "App::PropertyLength",
            "center_distance",
            "base",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "distance between the two axes; in pitch radius mode this is "
                "solved for instead of used",
            ),
        ).center_distance = "60 mm"
        obj.addProperty(
            "App::PropertyIntegerConstraint",
            "num_teeth",
            "base",
            QT_TRANSLATE_NOOP(
                "App::Property", "number of teeth, the same on both gears"
            ),
        ).num_teeth = (24, 4, 400, 1)
        obj.addProperty(
            "App::PropertyLength",
            "height",
            "base",
            QT_TRANSLATE_NOOP(
                "App::Property", "extrusion height; 0 leaves the bare outline"
            ),
        ).height = "5 mm"
        obj.addProperty(
            "App::PropertyFloatConstraint",
            "tooth_height",
            "accuracy",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "height of a tooth above the pitch line, as a fraction of the "
                "circular pitch",
            ),
        ).tooth_height = (0.14, 0.0, 0.4, 0.01)
        obj.addProperty(
            "App::PropertyLength",
            "backlash",
            "accuracy",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "gap held open between the two tooth surfaces; enough of it "
                "makes tooth_interference negative",
            ),
        ).backlash = "0 mm"
        obj.addProperty(
            "App::PropertyIntegerConstraint",
            "points_per_tooth",
            "accuracy",
            QT_TRANSLATE_NOOP(
                "App::Property", "points the outline of one tooth is drawn from"
            ),
        ).points_per_tooth = (24, 4, 400, 1)
        obj.addProperty(
            "App::PropertyIntegerConstraint",
            "samples",
            "accuracy",
            QT_TRANSLATE_NOOP(
                "App::Property", "points f(x) is evaluated at over one turn"
            ),
        ).samples = (1024, 64, 65536, 64)

        for name, kind, doc in (
            (
                "solved_center_distance",
                "App::PropertyLength",
                "the center distance the pair was drawn at",
            ),
            (
                "ratio_scale",
                "App::PropertyFloat",
                "the constant f(x) was multiplied by so that gear 2 closes; "
                "1 for an f(x) that already closed",
            ),
            ("min_ratio", "App::PropertyFloat", "smallest gear ratio over the turn"),
            ("max_ratio", "App::PropertyFloat", "largest gear ratio over the turn"),
            (
                "tooth_interference",
                "App::PropertyDistance",
                "deepest the teeth cut into one another over a revolution; "
                "negative once backlash holds them apart",
            ),
        ):
            obj.addProperty(
                kind, name, "computed", QT_TRANSLATE_NOOP("App::Property", doc), 1
            )

        obj.Proxy = self

    def generate_gear_shape(self, obj):
        pair, distance, scale = solve(obj)
        if abs(scale - 1.0) > 1e-9:
            app.Console.PrintMessage(
                app.Qt.translate(
                    "Log",
                    "{}: f(x) scaled by {:.6g} so the second gear closes into itself\n",
                ).format(obj.Label, scale)
            )
        obj.solved_center_distance = distance
        obj.ratio_scale = scale
        obj.min_ratio = pair.min_ratio
        obj.max_ratio = pair.max_ratio

        driver, mate = profiles(obj, pair)
        obj.tooth_interference = noncircular.interference(pair, driver, mate)
        return make_shape(driver, obj.height.Value)


class NonCircularGearMate(BaseGear):
    """The gear that meshes with a NonCircularGear."""

    def __init__(self, obj):
        super(NonCircularGearMate, self).__init__(obj)
        stamp_version(obj)
        obj.addProperty(
            "App::PropertyLink",
            "master",
            "base",
            QT_TRANSLATE_NOOP(
                "App::Property", "the non-circular gear this one meshes with"
            ),
        )
        # Where this gear sits is part of what is being solved, so it is driven
        # rather than edited.
        obj.setEditorMode("Placement", 1)
        obj.Proxy = self

    def generate_gear_shape(self, obj):
        master = obj.master
        if master is None:
            raise ValueError("no master gear is set")
        pair, distance, _ = solve(master)

        placement = app.Placement(
            app.Vector(distance, 0.0, 0.0),
            app.Rotation(app.Vector(0.0, 0.0, 1.0), 180.0),
        )
        if not _same_placement(obj.Placement, placement):
            obj.Placement = placement

        _, mate = profiles(master, pair)
        return make_shape(mate, master.height.Value)


def _same_placement(one, other, tolerance=1e-9):
    """Whether two placements agree, so a recompute leaves an unchanged one alone."""
    return one.Base.distanceToPoint(other.Base) < tolerance and one.Rotation.isSame(
        other.Rotation, tolerance
    )
