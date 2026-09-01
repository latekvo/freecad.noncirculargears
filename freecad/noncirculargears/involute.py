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

# How far the outline handed on may sit from the one ncgears drew, and how
# close together or far apart its points may then be left, all in modules.
# See ``_thinned`` for what each of the three is holding off.
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
            "involute teeth are cut by ncgears, which is not installed here: "
            "pip install ncgears ({})".format(err)
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


def _thinned(outline, tolerance, shortest, longest):
    """The outline cut down to what a spline through it needs, and no further.

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

    return outline[filled]


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
):
    """Both outlines and ncgears' reading of the pair, as (drive, mate, error).

    The pitch curve is handed over as the expression it came from rather than
    as the points already solved for, because ncgears differentiates it. It
    solves its own centre distance from the turns asked of it, so the result
    comes back scaled onto the centre distance this pair is drawn at - a whole
    scaling, which leaves the flanks as conjugate as they were.

    The error returned is ncgears' own: the worst the delivered motion strays
    from the one asked for, in degrees, over a staggered grid of mesh phases.
    It is reported rather than measured again here because the measure this
    workbench applies to wave teeth cannot be applied to these ones; see
    ``noncircular.interference``.
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

    with tempfile.TemporaryDirectory() as directory:
        cut = ncgears.generate_from_centrode(
            curve,
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
        drive = np.asarray(cut.drive_outline, dtype=float)
        placed = np.asarray(cut.placed_driven_outline, dtype=float)
        scale = float(center_distance) / float(cut.center_distance)
        error = float(cut.maximum_transmission_error)

    drive = drive * scale
    # The mate object carries a fixed placement - a half turn about z, then out
    # along x to the second axis - so the outline it is drawn from is the
    # assembled one brought back through that.
    mate = np.array([center_distance, 0.0]) - placed * scale

    bounds = (
        THINNING_TOLERANCE * module,
        SHORTEST_GAP * module,
        LONGEST_GAP * module,
    )
    return _thinned(drive, *bounds), _thinned(mate, *bounds), error
