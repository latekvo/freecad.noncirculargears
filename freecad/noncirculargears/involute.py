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

"""Conjugate involute teeth, cut by ncgears.

Nothing here works out a tooth flank. ncgears does that: handed a pitch curve
it returns the two outlines whose flanks roll on each other properly, which is
what a wave laid along the pitch line can only approximate. What is here is the
translation between the two - this workbench's f(x), turns and tooth height
going out, and outlines in the frames its two gear objects are drawn in coming
back.

ncgears is not required to use this workbench. Without it the wave teeth are
exactly what they were, and asking for involute ones says what to install.
"""

import math
import tempfile

import numpy as np

TWO_PI = 2.0 * math.pi

# Tooth proportions as multiples of the addendum rather than absolutes, so that
# tooth_height stays the single knob for how big a tooth is. ncgears wants a
# dedendum that clears the fillet, which any positive addendum keeps here.
DEDENDUM_OF_ADDENDUM = 1.25
FILLET_OF_ADDENDUM = 0.3

# ncgears will not work from fewer samples of the pitch curve than this, and
# this workbench lets samples go lower, so the two have to be reconciled. More
# of them is never wrong, only slower.
FEWEST_SAMPLES = 1024

# ncgears walks the centrode clockwise and this workbench walks it
# counter-clockwise, so a pair comes back reflected in the line of centres.
# Reflecting it there is a symmetry of the assembly - both axes lie on that
# line - so the pair meshes exactly as ncgears verified it, and an f(x) that is
# not even draws the same gear in both tooth styles.
MIRROR = np.array([1.0, -1.0])

# How far the outline handed on may sit from the one ncgears drew, and how
# close together or far apart its points may then be left, all in modules.
# See ``_kept`` for what each of the three is holding off.
THINNING_TOLERANCE = 1e-3
SHORTEST_GAP = 0.04
LONGEST_GAP = 0.1


class InvoluteUnavailable(RuntimeError):
    """ncgears is not installed, so involute flanks cannot be cut."""


def _ncgears():
    """The ncgears entry points, or a message saying how to get them."""
    try:
        import ncgears
        from ncgears.api import PHI
    except ImportError as err:
        raise InvoluteUnavailable(
            "involute teeth are cut by ncgears, which is not here. Opening "
            "the workbench fetches it, and the Report view says so if that "
            "did not work; a headless run wants pip install ncgears. Wave "
            "teeth need nothing beyond FreeCAD ({})".format(err)
        )
    return ncgears, PHI


def available():
    """Whether involute teeth can be cut at all."""
    try:
        _ncgears()
    except InvoluteUnavailable:
        return False
    return True


def _as_expression(function, symbol):
    """``function`` as a SymPy expression of ncgears' own angle symbol.

    This is the real limit of the style rather than an implementation detail:
    ncgears differentiates the pitch curve, so an f(x) that SymPy cannot read
    or cannot differentiate has no involute pair, even though the wave teeth
    would have drawn it. Substituting the symbol rather than the text of "x"
    keeps names like ``exp`` and ``max`` from being rewritten from under it.
    """
    import sympy

    try:
        parsed = sympy.sympify(function, locals={"x": symbol})
    except Exception as err:
        raise ValueError(
            "involute teeth need an f(x) SymPy can read; it could not read "
            "{!r}: {}".format(function, err)
        )
    unknown = parsed.free_symbols - {symbol}
    if unknown:
        raise ValueError(
            "f(x) may only use x; SymPy also found {}".format(
                ", ".join(sorted(str(name) for name in unknown))
            )
        )
    return parsed


def _kept(outline, tolerance, shortest, longest):
    """Which of the outline's points a spline through it needs, and no more.

    ncgears samples a flank an order of magnitude more finely than a spline
    needs, so its points have to be thinned before OCC is asked to interpolate
    and extrude them. Three things go wrong if that is done carelessly, and all
    three were measured on the outlines rather than guessed at:

    dropping every nth point spaces them evenly but rounds off the corners at
    the tooth tips, which moved the outline by a tenth of a tooth;

    dropping by a tolerance alone keeps the corners but leaves a crowd of
    points a few microns apart where a flank meets a fillet, and the spline
    fitted through those wiggles enough to cross itself, which leaves the solid
    invalid;

    and it leaves gaps a hundred times longer elsewhere, which the spline
    crosses by overshooting instead.

    So all three are bounded: the tolerance decides what may go, no two points
    are left closer than ``shortest``, and none further apart than ``longest``.

    ncgears also repeats a point where one piece of an outline meets the next,
    which an interpolation has nothing to do with. Simplifying drops those
    along with the rest, since a repeat is a step of nothing and every step of
    nothing is within any tolerance; the checks hold it to that.
    """
    import shapely

    ring = shapely.LinearRing(outline)
    kept = np.asarray(
        shapely.Polygon(ring).simplify(tolerance, preserve_topology=True).exterior.coords
    )
    at = {}
    for index, point in enumerate(outline):
        at.setdefault((point[0], point[1]), index)
    corners = sorted(at[(point[0], point[1])] for point in kept[:-1])

    spaced = [corners[0]]
    for index in corners[1:]:
        if np.linalg.norm(outline[index] - outline[spaced[-1]]) >= shortest:
            spaced.append(index)

    filled = []
    for start, stop in zip(spaced, spaced[1:] + [spaced[0] + len(outline)]):
        filled.append(start)
        gap = float(np.linalg.norm(outline[stop % len(outline)] - outline[start]))
        # never asked for more pieces than there are points to make them from,
        # which would hand the same point back more than once
        pieces = max(1, min(int(math.ceil(gap / longest)), stop - start))
        filled.extend(
            (start + (stop - start) * step // pieces) % len(outline)
            for step in range(1, pieces)
        )

    return filled


def _walk(outline):
    """Length along the closed outline at each point, and once all the way round."""
    closed = np.vstack((outline, outline[:1]))
    return np.concatenate(
        ([0.0], np.cumsum(np.linalg.norm(np.diff(closed, axis=0), axis=1)))
    )


def _fractions(outline, kept):
    """How far round the outline each of ``kept`` stands, in fractions of it."""
    walk = _walk(outline)
    return walk[kept] / walk[-1]


def _along(outline, fractions):
    """The outline read at those fractions of its own length, from its first point.

    Sections of one helical gear are raised point against point, so they have
    to be read at fractions that mean the same thing on each. They do: a
    section is the one below it with the teeth slid along the pitch line, so
    the same tooth stands the same way round both. It is the outline ncgears
    drew that is read rather than the thinned one, which keeps the reading off
    a chord: its points are twenty microns apart, and a fifth of a millimetre
    once thinned.
    """
    walk = _walk(outline)
    closed = np.vstack((outline, outline[:1]))
    want = np.asarray(fractions) * walk[-1]
    return np.column_stack([np.interp(want, walk, closed[:, axis]) for axis in (0, 1)])


def _turned(points, angle):
    """``points`` turned about the origin."""
    cos, sin = math.cos(angle), math.sin(angle)
    across, up = points[:, 0], points[:, 1]
    return np.column_stack((cos * across - sin * up, sin * across + cos * up))


def _whole_turn(pair, mate):
    """The arc of the whole of one gear's pitch line, all its periods together."""
    return pair.arc_length * (pair.mate_lobes if mate else pair.driver_lobes)


def _pitch_table(pair, mate):
    """The gear's pitch line as (angle, radius, arc), read in order of angle.

    The copies either side let a reading near the seam be taken without a wrap
    in the middle of it. Ordered by angle, which on the mate runs backwards
    along the arc, so only a reading that starts from an angle comes from here.
    """
    points, arcs = pair.pitch_line(mate)
    angle = np.arctan2(points[:, 1], points[:, 0]) % TWO_PI
    order = np.argsort(angle)
    angle, radius, arc = angle[order], np.hypot(*points[order].T), arcs[order]
    whole = _whole_turn(pair, mate)
    return (
        np.concatenate((angle - TWO_PI, angle, angle + TWO_PI)),
        np.tile(radius, 3),
        np.concatenate((arc - whole, arc, arc + whole)),
    )


def _first_crossing(outline, table):
    """The arc at which ``outline`` first passes from inside its pitch line to outside.

    One tooth carries one such crossing, so this names a tooth, and it names it
    where the outline runs across the pitch line rather than along it - the
    tips and the roots, which is where the two are hardest to tell apart, are
    half a tooth away in either direction.
    """
    angle, radius, arc = table
    at = np.arctan2(outline[:, 1], outline[:, 0]) % TWO_PI
    outside = np.hypot(*outline.T) - np.interp(at, angle, radius)
    rising = np.nonzero((outside <= 0.0) & (np.roll(outside, -1) > 0.0))[0]
    if not len(rising):
        raise ValueError("an outline that never crosses its own pitch line")
    return float(np.interp(at[rising[0]], angle, arc))


def _started_at(outline, pair, mate, wanted):
    """``outline`` rolled round to begin at the tooth standing at ``wanted``.

    Sections of a helical gear are raised point against point, so each has to
    begin on the same tooth as the last, one pitch further along the line if
    the teeth have moved that far. The tooth it lands on is the one the section
    before it began on: consecutive sections are a fraction of a pitch apart,
    and the next tooth along is a whole one.
    """
    points, arcs = pair.pitch_line(mate)
    whole = _whole_turn(pair, mate)
    walk = np.append(arcs, whole)
    closed = np.vstack((points, points[:1]))
    standing = np.array(
        [np.interp(wanted % whole, walk, closed[:, axis]) for axis in (0, 1)]
    )
    return np.roll(outline, -int(np.argmin(np.hypot(*(outline - standing).T))), axis=0)


def outlines(
    pair,
    function,
    mode,
    center_distance,
    ratio_scale,
    num_teeth,
    tooth_height,
    backlash,
    pressure_angle,
    samples,
    phases=(0.0,),
):
    """Both gears' outlines at each of ``phases``, as (drives, mates, error).

    The pitch curve is handed over as the expression it came from rather than
    as the points already solved for, because ncgears differentiates it. It
    solves its own centre distance from the turns asked of it, so the result
    comes back scaled onto the centre distance this pair is drawn at - a whole
    scaling, which leaves the flanks as conjugate as they were.

    A phase is how far along the pitch line the teeth of that section stand,
    which is what makes a helical gear when the sections are stacked. ncgears
    starts the teeth where the centrode it is handed starts, so a section is
    cut from the centrode read from that point on and then turned back until
    its pitch line lies where the others' do. Every section is a pair ncgears
    has verified in its own right, meshing at the one position the pair is
    drawn in - which is what a helical pair has to do at every height.

    The error returned is ncgears' own, worst of the sections: the worst the
    delivered motion strays from the one asked for, in degrees, over a
    staggered grid of mesh phases. It is reported rather than measured again
    here because the measure this workbench applies to wave teeth cannot be
    applied to these ones; see ``noncircular.interference``.
    """
    ncgears, angle = _ncgears()
    if tooth_height <= 0.0:
        raise ValueError("involute teeth need a tooth_height above 0")

    curve = _as_expression(function, angle)
    if mode != "pitch radius":
        curve = float(center_distance) / (1 + float(ratio_scale) * curve)

    # ncgears sizes a tooth in modules, so handing it the module this pair
    # already has is what makes tooth_height mean the same in both styles.
    # Plain floats, not numpy ones: ncgears writes a JSON summary of what it
    # was given, and a numpy scalar reaching it comes back out as a numpy bool
    # that json will not write.
    module = float(pair.arc_length) * pair.driver_lobes / (num_teeth * math.pi)
    addendum = float(tooth_height) * math.pi

    def section(phase):
        """One cross-section, cut with its teeth ``phase`` along the pitch line."""
        driver_turn, mate_turn = pair.angles_at_arc(phase)
        with tempfile.TemporaryDirectory() as directory:
            cut = ncgears.generate_from_centrode(
                curve.subs(angle, angle + driver_turn),
                name="pair",
                teeth=int(num_teeth),
                module=module,
                pressure_angle_deg=float(pressure_angle),
                addendum_factor=addendum,
                dedendum_factor=addendum * DEDENDUM_OF_ADDENDUM,
                fillet_factor=addendum * FILLET_OF_ADDENDUM,
                clearance=0.5 * float(backlash) / module,
                target_cycle_delta=TWO_PI * pair.driver_lobes / pair.mate_lobes,
                samples=max(FEWEST_SAMPLES, int(samples)),
                output_directory=directory,
            )
            drive = _turned(np.asarray(cut.drive_outline, dtype=float), -driver_turn)
            driven = _turned(np.asarray(cut.driven_outline, dtype=float), mate_turn)
            placed = driven + np.array([float(cut.center_distance), 0.0])
            scale = float(center_distance) / float(cut.center_distance)
            error = float(cut.maximum_transmission_error)
        # The mate object carries a fixed placement - a half turn about z, then
        # out along x to the second axis - so the outline it is drawn from is
        # the assembled one brought back through that.
        return (
            drive * scale * MIRROR,
            np.array([center_distance, 0.0]) - placed * scale * MIRROR,
            error,
        )

    bounds = (
        THINNING_TOLERANCE * module,
        SHORTEST_GAP * module,
        LONGEST_GAP * module,
    )
    if len(phases) == 1:
        drive, mate, error = section(phases[0])
        return [drive[_kept(drive, *bounds)]], [mate[_kept(mate, *bounds)]], error

    tables = (_pitch_table(pair, False), _pitch_table(pair, True))
    cut, error, anchors = [], 0.0, None
    for phase in phases:
        drive, mate, strayed = section(phase)
        if anchors is None:
            anchors = [
                _first_crossing(outline, table) - phase
                for outline, table in zip((drive, mate), tables)
            ]
        cut.append(
            (
                _started_at(drive, pair, False, anchors[0] + phase),
                _started_at(mate, pair, True, anchors[1] + phase),
            )
        )
        error = max(error, strayed)

    def stacked(outlines):
        """Every section read at the fractions the first one's thinning chose."""
        fractions = _fractions(outlines[0], _kept(outlines[0], *bounds))
        return [_along(outline, fractions) for outline in outlines]

    drives, mates = zip(*cut)
    return stacked(drives), stacked(mates), error
