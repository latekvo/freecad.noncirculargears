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

import collections
import math

from freecad import app
from freecad import part
from freecad.gears.basegear import BaseGear, fcvec

from . import __version__
from . import involute
from . import noncircular

QT_TRANSLATE_NOOP = app.Qt.QT_TRANSLATE_NOOP

MODES = ["gear ratio", "pitch radius"]
STYLES = ["wave", "involute"]

# Outline points per B-spline of the wire the gear is drawn from. Splines this
# short are what keep the extrusion cheap to mesh; see ``outline_wire``.
POINTS_PER_SPAN = 6

# Outlines already cut, oldest first, against the parameters they were cut
# from; see ``profiles``. Enough for both styles of a pair, and a few edits back.
CUTS_KEPT = 8
CUTS = collections.OrderedDict()

# How far a helical gear's teeth may move between one cross-section and the
# next, as a fraction of the circular pitch, and how many sections that is
# allowed to come to. The gear is ruled from one section to the next, so what
# it costs falls with the square of the step; an eighth of a pitch puts the
# shape halfway between two sections 0.005 mm from the pair cut for that height
# on the default pair, which is inside the 0.009 mm the thinning already moves
# the outline by. The count is capped by refusing rather than by opening the
# step out, since teeth leaning far enough to reach it are not a gear.
SECTION_STEP = 0.125
MOST_SECTIONS = 65


def sections(obj, pair):
    """How far along the pitch line the teeth stand at each height of ``obj``.

    Straight teeth stand in one place, so there is one section and the gear is
    extruded from it. Leaning teeth move along the pitch line as the gear rises
    - by the height times the tangent of the angle they lean at - and the gear
    is raised on sections cut at that many places. Both gears' teeth move
    the same way along the arc the two roll off each other, which is what keeps
    every height meshing and what leaves the mate with the opposite hand.
    """
    slide = obj.height.Value * math.tan(math.radians(obj.helix_angle.Value))
    if not slide:
        return (0.0,)
    pitch = pair.arc_length / noncircular.teeth_per_period(pair, obj.num_teeth)
    steps = int(math.ceil(abs(slide) / (SECTION_STEP * pitch)))
    if steps >= MOST_SECTIONS:
        raise ValueError(
            "teeth leaning {:.4g} degrees across {:.4g} mm move {:.4g} pitches "
            "along the pitch line, which wants {} cross-sections and at most "
            "{} are cut".format(
                obj.helix_angle.Value, obj.height.Value, abs(slide) / pitch,
                steps + 1, MOST_SECTIONS,
            )
        )
    return tuple(slide * step / steps for step in range(steps + 1))


def stamp_version(obj):
    """Own the ``version`` property BaseGear adds, which it fills with its own."""
    obj.version = __version__
    obj.setDocumentationOfProperty(
        "version",
        QT_TRANSLATE_NOOP("App::Property", "freecad.noncirculargears version"),
    )


def solve(obj):
    """The pitch pair for ``obj``'s parameters, its center distance and ratio scale."""
    driver_lobes, mate_lobes = noncircular.lobe_counts(obj.mate_turns, obj.driver_turns)
    # f is sampled over the whole turn, so a driver that does not repeat as often
    # as the turns ask for is caught rather than cut down to its first period.
    per_period = -(-obj.samples // driver_lobes)
    values = noncircular.sample_function(obj.function, per_period * driver_lobes)
    if obj.mode == "pitch radius":
        pair, distance = noncircular.from_radius(values, driver_lobes, mate_lobes)
        return pair, distance, 1.0
    pair, scale = noncircular.from_ratio(
        values, obj.center_distance.Value, driver_lobes, mate_lobes
    )
    return pair, obj.center_distance.Value, scale


def profiles(obj, pair, scale):
    """Both gears' cross-sections for the parameters on ``obj``.

    Both halves of a pair are drawn from the driving gear's outlines and
    FreeCAD recomputes the two objects separately, so without this an involute
    pair - which takes seconds to cut, not milliseconds - would be cut twice
    over for every rebuild. Several are kept rather than one, which is what
    lets a style be gone back to, or an edit undone, for nothing.

    A cut that would not cut is kept along with the ones that did, because a
    recompute swallows the reason and the dialog has to ask a second time to
    have it; the second ask is the same refusal, and is not worth seconds.
    """
    phases = sections(obj, pair)
    key = (
        phases,
        obj.tooth_style,
        obj.mode,
        obj.function,
        obj.center_distance.Value,
        int(obj.samples),
        int(obj.mate_turns),
        int(obj.driver_turns),
        int(obj.num_teeth),
        int(obj.points_per_tooth),
        obj.tooth_height,
        obj.backlash.Value,
        obj.pressure_angle,
    )
    if key in CUTS:
        CUTS.move_to_end(key)
    else:
        try:
            CUTS[key] = _cut_profiles(obj, pair, scale, phases)
        except involute.InvoluteUnavailable:
            # Not decided by the parameters: installing ncgears must lift it.
            raise
        except Exception as refusal:
            CUTS[key] = refusal
        while len(CUTS) > CUTS_KEPT:
            CUTS.popitem(last=False)
    cut = CUTS[key]
    if isinstance(cut, Exception):
        raise cut
    return cut


def _cut_profiles(obj, pair, scale, phases):
    """Both gears' sections, and how far the pair strays from f(x).

    Each style is measured its own way, because neither measure fits the other
    shape. A wave tooth is not conjugate, so what matters is how far it cuts
    in. An involute flank is, so what matters is the motion it delivers - and
    it cannot be put through the first measure at all, which reads an outline
    as a radius against an angle and so needs one a flank with a fillet under
    it does not give. Either way it is the worst of the sections that is
    reported, since a helical pair is only as good as its worst height.
    """
    if obj.tooth_style == "involute":
        drives, mates, error = involute.outlines(
            pair,
            obj.function,
            obj.mode,
            pair.center_distance,
            scale,
            obj.num_teeth,
            obj.tooth_height,
            obj.backlash.Value,
            obj.pressure_angle,
            obj.samples,
            phases,
        )
        return drives, mates, 0.0, error
    cut = [
        noncircular.tooth_profiles(
            pair,
            obj.num_teeth,
            obj.points_per_tooth,
            obj.tooth_height,
            obj.backlash.Value,
            phase,
        )
        for phase in phases
    ]
    drives = [drive for drive, _ in cut]
    mates = [mate for _, mate in cut]
    penetration = max(
        noncircular.interference(pair, drive, mate) for drive, mate in cut
    )
    return drives, mates, penetration, 0.0


def span_count(points, span=POINTS_PER_SPAN):
    """How many B-splines to leave an outline of ``points`` in."""
    return max(1, min(len(points) // span, len(points) // 2))


def outline_wire(points, pieces=None):
    """The closed curve through ``points``, handed over as short B-splines.

    One periodic spline is interpolated through the points and then cut into
    pieces that each carry only their own poles, which leaves the curve itself
    untouched. What it buys is that OCC extrudes and meshes a row of small
    faces rather than one large one, and it is far faster at that - the same
    reason freecad.gears builds its wires from short splines. The 3D view pays
    this on every rebuild, so none of it shows up in a recompute.

    ``pieces`` is how many to cut it into, which the sections of one helical
    gear all have to agree on: the gear is raised piece against piece.
    """
    curve = part.BSplineCurve()
    curve.interpolate(Points=[fcvec(point) for point in points], PeriodicFlag=True)
    if pieces is None:
        pieces = span_count(points)
    start, length = curve.FirstParameter, curve.LastParameter - curve.FirstParameter
    cuts = [start + length * index / pieces for index in range(pieces + 1)]
    spans = []
    for first, last in zip(cuts, cuts[1:]):
        piece = curve.copy()
        piece.segment(first, last)
        spans.append(piece.toShape())
    return part.Wire(spans)


def make_shape(cross_sections, height):
    """The gear these ``cross_sections`` stack into, over ``height``.

    Straight teeth leave one section, which is extruded. Leaning teeth leave
    several, standing at equal heights, and the gear is raised on them. That
    is what a gear whose pitch line is not a circle needs: the twist that
    carries a circular gear's section up its own helix is a turn about the
    axis, and this one is not.

    It is raised as a row of surfaces ruled from one section to the next rather
    than by ``makeLoft`` through the lot, because a loft searches the wires'
    vertices for the pairing that matches them best, and on sections whose
    teeth have moved along by less than one tooth that can be the pairing which
    undoes the move - joining each tooth tip to a point partway down the next
    section's flank. Whether it is turns on how the wire's edges compare with
    the move: at one edge per 0.98 mm against a 0.91 mm step the loft reads
    0.20 mm from the section really cut halfway up, and at 1.95 mm an edge it
    reads 0.015 mm. Ruling pairs the wires edge for edge whatever those two
    lengths are, and reads 0.019 mm. What it gives up is smoothness up the
    flank, which is faceted between sections by the same 0.005 mm the sections
    are spaced to allow.

    Each section is left in fewer pieces the more sections there are, so that a
    gear carries about as many faces however it is raised; see ``outline_wire``
    for what the pieces are for.
    """
    if height <= 0.0:
        return outline_wire(cross_sections[0])
    if len(cross_sections) == 1:
        return part.Face(outline_wire(cross_sections[0])).extrude(
            app.Vector(0.0, 0.0, height)
        )
    steps = len(cross_sections) - 1
    pieces = max(1, span_count(cross_sections[0]) // steps)
    wires = []
    for index, points in enumerate(cross_sections):
        wire = outline_wire(points, pieces)
        wire.translate(app.Vector(0.0, 0.0, height * index / steps))
        wires.append(wire)
    faces = []
    for below, above in zip(wires, wires[1:]):
        faces.extend(
            part.makeRuledSurface(one, other)
            for one, other in zip(below.Edges, above.Edges)
        )
    faces.extend((part.Face(wires[0]), part.Face(wires[-1])))
    return part.makeSolid(part.makeShell(faces))


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
            "App::PropertyEnumeration",
            "tooth_style",
            "base",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "wave lays a sine along the pitch line, which is quick and "
                "approximate; involute cuts flanks that roll on it properly, "
                "which needs the ncgears package and takes seconds",
            ),
        )
        obj.tooth_style = STYLES
        # Involute whether or not ncgears is here to cut it. Standing a wave
        # tooth in for one that was asked for would leave a pair that is not
        # conjugate looking exactly like one that is; refusing says so.
        obj.tooth_style = "involute"
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
                "App::Property",
                "number of teeth on this gear; the mate gets mate_teeth, which "
                "is the same only for a pair that turns 1:1",
            ),
        ).num_teeth = (24, 4, 400, 1)
        obj.addProperty(
            "App::PropertyIntegerConstraint",
            "mate_turns",
            "base",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "turns the mate makes for every driver_turns turns of this gear. "
                "Above driver_turns, f(x) has to repeat mate_turns/gcd times over "
                "the turn, and num_teeth be a multiple of that",
            ),
        ).mate_turns = (1, 1, 64, 1)
        obj.addProperty(
            "App::PropertyIntegerConstraint",
            "driver_turns",
            "base",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "turns this gear makes for every mate_turns turns of the mate; "
                "raise it above mate_turns for a mate that turns slower",
            ),
        ).driver_turns = (1, 1, 64, 1)
        obj.addProperty(
            "App::PropertyLength",
            "height",
            "base",
            QT_TRANSLATE_NOOP(
                "App::Property", "extrusion height; 0 leaves the bare outline"
            ),
        ).height = "5 mm"
        obj.addProperty(
            "App::PropertyAngle",
            "helix_angle",
            "base",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "angle the teeth lean at across the height, in degrees; 0 "
                "leaves them straight. The mate takes the opposite hand, and "
                "an involute pair is cut once per cross-section, so what this "
                "costs is helix_sections times a straight pair",
            ),
        ).helix_angle = "0 deg"
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
                "makes tooth_interference negative on wave teeth, and it is "
                "cut into the flanks of involute ones",
            ),
        ).backlash = "0 mm"
        obj.addProperty(
            "App::PropertyFloatConstraint",
            "pressure_angle",
            "accuracy",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "angle the involute flanks press at, in degrees; wave teeth "
                "have no flank angle to set and ignore it",
            ),
        ).pressure_angle = (20.0, 1.0, 44.0, 0.5)
        obj.addProperty(
            "App::PropertyIntegerConstraint",
            "points_per_tooth",
            "accuracy",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "points the outline of one wave tooth is drawn from; involute "
                "flanks are drawn from as many points as their shape needs",
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
                "mate_teeth",
                "App::PropertyInteger",
                "number of teeth on the mate, which follows from num_teeth and "
                "the turns the two make",
            ),
            (
                "helix_sections",
                "App::PropertyInteger",
                "cross-sections the gear is raised on; 1 for straight "
                "teeth, and otherwise enough to keep the teeth within an "
                "eighth of a circular pitch of the section below",
            ),
            (
                "tooth_interference",
                "App::PropertyDistance",
                "deepest wave teeth cut into one another over a revolution; "
                "negative once backlash holds them apart. 0 for involute "
                "teeth, which transmission_error measures instead",
            ),
            (
                "transmission_error",
                "App::PropertyFloat",
                "worst the motion involute teeth deliver strays from f(x), in "
                "degrees, as ncgears measures it. 0 for wave teeth, which "
                "tooth_interference measures instead",
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
        driver, _, penetration, error = profiles(obj, pair, scale)
        obj.solved_center_distance = distance
        obj.helix_sections = len(driver)
        obj.ratio_scale = scale
        obj.min_ratio = pair.min_ratio
        obj.max_ratio = pair.max_ratio
        obj.mate_teeth = noncircular.mate_teeth(pair, obj.num_teeth)
        obj.tooth_interference = penetration
        obj.transmission_error = error
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
        pair, distance, scale = solve(master)

        placement = app.Placement(
            app.Vector(distance, 0.0, 0.0),
            app.Rotation(app.Vector(0.0, 0.0, 1.0), 180.0),
        )
        if not _same_placement(obj.Placement, placement):
            obj.Placement = placement

        mate = profiles(master, pair, scale)[1]
        return make_shape(mate, master.height.Value)


def _same_placement(one, other, tolerance=1e-9):
    """Whether two placements agree, so a recompute leaves an unchanged one alone."""
    return one.Base.distanceToPoint(other.Base) < tolerance and one.Rotation.isSame(
        other.Rotation, tolerance
    )
