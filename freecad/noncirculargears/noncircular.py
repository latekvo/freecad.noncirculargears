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

"""The pitch curves of a pair of meshing non-circular gears.

Both gears are reduced to their operating pitch lines and the teeth are a wave
laid along each line's arc length, in antiphase - the simplification Julien
Piellard's non-circular-gears generator makes, and the reason a gear here needs
no tooth geometry of its own.

The pair is driven by one scalar function of one turn of the first gear, given
either as the gear ratio w1/w2 or as the first gear's pitch radius. Everything
else follows from the two conditions that define a pitch pair with fixed axes:
the radii sum to the center distance, and the pitch lines roll on each other
without slipping.

    r1 + r2 = a                 fixed axes, contact on the line of centres
    r1 * dphi1 = r2 * dphi2     no slip, hence w1/w2 = r2/r1 = f

so r1 = a / (1 + f) and phi2 = integral of dphi1 / f. The second gear only
closes into itself when that integral comes to one full turn, which is a
condition on f rather than on anything drawn:

    "gear ratio"    a is free and scales the pair, so f itself is scaled by the
                    constant that closes it, and the factor is reported;
    "pitch radius"  f = (a - r1) / r1 depends on a, so a is solved for instead
                    and the given shape is kept exactly.
"""

import math

import numpy as np

TWO_PI = 2.0 * math.pi

_MATH_NAMES = (
    "acos asin atan atan2 ceil copysign cos cosh degrees e exp fabs floor fmod "
    "hypot log log10 log2 pi pow radians sin sinh sqrt tan tanh tau"
).split()

_FUNCTION_ENV = dict((name, getattr(math, name)) for name in _MATH_NAMES)
_FUNCTION_ENV.update(abs=abs, max=max, min=min, round=round)


class GearFunctionError(ValueError):
    """The given f(x) cannot drive a gear pair."""


def sample_function(expression, count):
    """f(x) over ``count`` equally spaced points of [0, 2pi).

    The expression is Python, evaluated with ``x`` in radians and the ``math``
    module's names in scope. Raises GearFunctionError with the offending x for
    anything that is not a finite number.
    """
    try:
        code = compile(expression, "<gear function>", "eval")
    except SyntaxError as err:
        raise GearFunctionError("cannot parse {!r}: {}".format(expression, err))

    values = np.empty(count)
    for index in range(count):
        x = TWO_PI * index / count
        scope = dict(_FUNCTION_ENV)
        scope["x"] = x
        try:
            value = eval(code, {"__builtins__": {}}, scope)  # noqa: S307
        except Exception as err:
            raise GearFunctionError(
                "f({:.6f}) raised {}: {}".format(x, type(err).__name__, err)
            )
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise GearFunctionError(
                "f({:.6f}) is {!r}, expected a number".format(x, value)
            )
        if not math.isfinite(value):
            raise GearFunctionError("f({:.6f}) is {}".format(x, value))
        values[index] = value
    return values


def _cumulative(integrand, step):
    """Trapezoid rule around a closed turn.

    ``integrand`` holds one period on an open grid, so the last interval is the
    one that wraps back to the first sample. Returns the running integral at
    each sample, starting at zero, and the integral over the whole turn.
    """
    increments = 0.5 * (integrand + np.roll(integrand, -1)) * step
    running = np.concatenate(([0.0], np.cumsum(increments[:-1])))
    return running, running[-1] + increments[-1]


def _derivative(values, step):
    """Central differences on one period of a closed curve."""
    return (np.roll(values, -1) - np.roll(values, 1)) / (2.0 * step)


def _outward_normals(points):
    """Unit normals of a closed polyline, each pointing away from the origin.

    Adapted from ``computeNormal`` in non-circular-gears' ``rays.ts``: rotate
    the local tangent by a quarter turn, then flip it if it came out facing the
    centre.
    """
    tangents = np.roll(points, -1, axis=0) - np.roll(points, 1, axis=0)
    normals = np.column_stack((tangents[:, 1], -tangents[:, 0]))
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    inward = np.sum(points * normals, axis=1) < 0.0
    normals[inward] *= -1.0
    return normals


class PitchPair(object):
    """Two pitch lines that roll on each other, sampled over one turn of gear 1.

    Every array holds one period on an open grid of ``len(theta)`` samples: the
    sample after the last one is index 0 again.
    """

    def __init__(self, ratio, center_distance):
        self.ratio = ratio
        self.center_distance = center_distance
        self.theta = np.linspace(0.0, TWO_PI, len(ratio), endpoint=False)
        step = self.theta[1]

        self.radius1 = center_distance / (1.0 + ratio)
        self.radius2 = center_distance - self.radius1

        angle2, turns = _cumulative(1.0 / ratio, step)
        # Gear 2 must come back to where it started after gear 1's turn. The
        # residual is quadrature and root-finding error, not a modelling choice.
        self.closure_error = turns / TWO_PI - 1.0
        self.angle2 = angle2 * (TWO_PI / turns)

        slope = _derivative(self.radius1, step)
        self.arc, self.arc_length = _cumulative(np.hypot(self.radius1, slope), step)

    @property
    def min_ratio(self):
        return float(self.ratio.min())

    @property
    def max_ratio(self):
        return float(self.ratio.max())

    def resample(self, count):
        """The pair at ``count`` points spaced equally along the pitch lines.

        Rolling without slipping makes the two arc lengths advance together
        - r2 * dphi2 is r1 * dphi1 and dr2 is -dr1 - so one arc parameter
        drives both curves, which is what keeps their teeth in step.
        """
        arc = np.append(self.arc, self.arc_length)
        targets = np.linspace(0.0, self.arc_length, count, endpoint=False)

        def along(values, closing_value):
            return np.interp(targets, arc, np.append(values, closing_value))

        return (
            targets,
            along(self.radius1, self.radius1[0]),
            along(self.theta, TWO_PI),
            along(self.radius2, self.radius2[0]),
            along(self.angle2, TWO_PI),
        )


def from_ratio(ratio, center_distance):
    """A pair driven by the gear ratio w1/w2, scaled by the factor that closes it.

    Returns the pair and that factor, which is 1 for a ratio that already
    closes. The center distance only scales the result, so it stays as given.
    """
    if ratio.min() <= 0.0:
        raise GearFunctionError(
            "the gear ratio reaches {:.6g}; it must stay above 0".format(ratio.min())
        )
    step = TWO_PI / len(ratio)
    _, turns = _cumulative(1.0 / ratio, step)
    scale = turns / TWO_PI
    return PitchPair(scale * ratio, center_distance), scale


def from_radius(radius, tolerance=1e-12, max_iterations=200):
    """A pair driven by gear 1's pitch radius, with the center distance solved for.

    Gear 2 turns ``integral of r1 / (a - r1)`` over gear 1's turn, which falls
    from infinity to zero as ``a`` grows, so one center distance makes it a
    full turn and bisection finds it. This is what non-circular-gears'
    ``getNextFittingDistance`` searches for; here the target is one turn rather
    than a whole number of periods.
    """
    if radius.min() <= 0.0:
        raise GearFunctionError(
            "the pitch radius reaches {:.6g}; it must stay above 0".format(radius.min())
        )
    step = TWO_PI / len(radius)
    largest = float(radius.max())

    def turns_of_gear2(distance):
        return _cumulative(radius / (distance - radius), step)[1]

    low = largest * (1.0 + 1e-6)
    for _ in range(max_iterations):
        if turns_of_gear2(low) >= TWO_PI:
            break
        low = largest + (low - largest) * 0.1
    else:
        raise GearFunctionError("no center distance closes gear 2 around this shape")

    high = largest + 2.0 * float(radius.mean())
    for _ in range(max_iterations):
        if turns_of_gear2(high) <= TWO_PI:
            break
        high += high - largest
    else:
        raise GearFunctionError("no center distance closes gear 2 around this shape")

    for _ in range(max_iterations):
        middle = 0.5 * (low + high)
        if middle <= low or middle >= high or high - low < tolerance * largest:
            break
        if turns_of_gear2(middle) > TWO_PI:
            low = middle
        else:
            high = middle

    distance = 0.5 * (low + high)
    return PitchPair((distance - radius) / radius, distance), distance


def _radius_by_angle(points):
    """A closed outline as radius against angle, wrapped for interpolation.

    Sound as long as the outline is star-shaped about its axis, which a pitch
    line with r > 0 and teeth far shorter than r is.
    """
    angle = np.arctan2(points[:, 1], points[:, 0]) % TWO_PI
    radius = np.hypot(points[:, 0], points[:, 1])
    order = np.argsort(angle)
    angle, radius = angle[order], radius[order]
    return (
        np.concatenate((angle - TWO_PI, angle, angle + TWO_PI)),
        np.tile(radius, 3),
    )


def interference(pair, driver, mate, steps=719):
    """How deep the two outlines cut into each other over a revolution, in mm.

    The pitch lines roll exactly, but teeth laid on them are not conjugate
    flanks, so a tooth passes a little way into the gap it meshes with. This
    turns the pair through ``steps`` positions and measures the worst of it -
    negative when the pair never touches, which is what backlash buys.

    A tooth is worst somewhere partway through meshing, so what matters is how
    many phases *within* one tooth pitch get sampled. A step count tied to the
    tooth count falls into step with the teeth and revisits the same handful of
    phases; a prime one does not. 719 agrees with a sweep seven times as dense
    to the last digit, at every tooth count this allows.
    """
    angle, radius = _radius_by_angle(driver)
    worst = -float("inf")
    for step in range(steps):
        index = int(round(step * len(pair.theta) / float(steps))) % len(pair.theta)
        turn = math.pi + pair.angle2[index]
        cos, sin = math.cos(turn), math.sin(turn)
        placed = np.column_stack(
            (
                cos * mate[:, 0] - sin * mate[:, 1] + pair.center_distance,
                sin * mate[:, 0] + cos * mate[:, 1],
            )
        )
        # as gear 1 sees it, gear 1 itself having turned by -theta to meet it
        seen = (np.arctan2(placed[:, 1], placed[:, 0]) + pair.theta[index]) % TWO_PI
        depth = np.interp(seen, angle, radius) - np.hypot(placed[:, 0], placed[:, 1])
        worst = max(worst, float(depth.max()))
    return worst


def tooth_profiles(pair, num_teeth, points_per_tooth, tooth_height, backlash=0.0):
    """Both gears' outlines, in their own frames, as (n, 2) arrays of points.

    The teeth are one wave of ``num_teeth`` periods along the shared arc length,
    pushed along each outline's own outward normal - gear 2's negated, so a
    tooth on one is a gap on the other. This is non-circular-gears'
    ``buildPeriodPointsWithTeeth`` with a plain sine in place of its
    ``cos ** 1/5``: the squarer wave was for the look of an animation, and its
    steep flanks are what a rolling pair cannot clear. Neither wave is a
    conjugate flank, so a curvature mismatch is left over - about a hundredth
    of a tooth for the sine, which is what ``backlash`` is for.

    Gear 2 is wound the other way round its centre, which is what makes the two
    counter-rotate once gear 2 is turned to face gear 1.
    """
    count = num_teeth * points_per_tooth
    arc, radius1, angle1, radius2, angle2 = pair.resample(count)

    pitch = pair.arc_length / num_teeth
    wave = tooth_height * pitch * np.sin(TWO_PI * arc / pitch)

    def outline(radius, angle, sign):
        points = np.column_stack((radius * np.cos(angle), radius * np.sin(angle)))
        offset = sign * wave - 0.5 * backlash
        return points + offset[:, None] * _outward_normals(points)

    return outline(radius1, angle1, 1.0), outline(radius2, -angle2, -1.0)
