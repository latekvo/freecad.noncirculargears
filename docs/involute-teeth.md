# Involute teeth, and what it would take to have them

The teeth this workbench draws are a sine wave laid along each pitch line's arc
length in antiphase. The pitch lines roll exactly; the flanks are not conjugate,
so a tooth passes a little way into the gap it meshes with, and
`tooth_interference` is there to measure how far - 0.012 mm on a 1.07 mm tooth
for the default pair. Real flanks would take that to nothing, and this is what
finding out how to get them turned up.

## The involute does not port from freecad.gears

`pygears.involute_tooth.InvoluteTooth` builds a flank from the base circle:
`involute_function_x` is `dg/2 * (cos(phi) + phi * sin(phi))` and `dg` is a
diameter, derived from the module, the tooth count and the pressure angle. A
non-circular gear has no single base circle to put there, and no single pitch
radius to derive one from, so there is nothing in that class to point at a pitch
line whose radius varies.

What does carry over is one class further down: `InvoluteRack.points()` returns
the straight-flanked rack as a polyline, `[-m_n * (1 + clearance), -a - b]` and
so on, from the module and the pressure angle alone. That is the cutter, and the
cutter is what a non-circular gear is actually given its flanks by. Rolling it
along a pitch line and taking the envelope of where it has been is the textbook
construction (Litvin's, the one elliptical gears are hobbed by), and it is the
part that would have to be written. So: the rack ports, the tooth does not, and
the envelope is the whole job.

## Three ways to get there

**The local equivalent circular gear.** At each tooth, take the radius of
curvature of the pitch curve there as the pitch radius of an ordinary circular
involute gear, and stand one standard tooth on it. Genuine involute flanks,
exact only where the curvature is locally constant, and wrong by however much it
is not. `phillbaker/non-circular-gears-generator` (BSD, Python 2.5, thirteen
commits) is this, and asks for `radiusOfCurvature` or the second derivatives to
compute it from. Cheapest of the three and the least correct.

**The rack envelope.** Roll the rack along the pitch line; the envelope of its
flank positions is the conjugate profile. Most of the input is already here:
`PitchPair` holds the rolling itself as `theta`, `angle2` and `arc`, which is
exactly the parameter the rack would be placed by, and `resample` already walks
that parameter at equal arc length. The missing piece is taking the envelope,
and there are two ways to get one - solve the envelope condition analytically,
or sweep the rack through positions and cut every one of them out of a blank,
which FreeCAD's booleans give for free and which is short, obviously correct and
slow. Undercutting where the pitch curve's curvature is smallest is the known
failure mode and would need catching.

**Hand it to ncgears.** `ncgears` (Apache-2.0, `kylebme/ncgears`, 0.3.1 of
4 August 2026, alpha) generates non-circular pairs with generalised-involute
teeth, and its shape is close enough to this workbench's to be unsettling:

    ncgears.generate_from_centrode(
        expression,               # our function in pitch radius mode, x for phi
        teeth=...,                # our num_teeth
        module=...,
        pressure_angle_deg=...,
        target_cycle_delta=...,   # our mate_turns against driver_turns
        reference_center_distance=...,   # our center_distance
        clearance=..., max_backlash_deg=...,
    ) -> GearPair

and a `GearPair` carries `drive_outline` and `driven_outline` as `(n, 2)` arrays
with a `center_distance`, which is what `make_shape` already takes. It verifies
what it makes, over a whole cycle, for interference and transmission error.

Its costs are real and worth stating. FreeCAD 1.1.3 ships numpy, scipy, sympy
and matplotlib but not shapely or ezdxf, so two dependencies would have to be
installed alongside the workbench. Every call writes a result directory to disk
- `generate_from_centrode` takes an `output_directory` and `GearPair` reads its
outlines back out of it - which a document object recomputing on every keystroke
would have to be pointed somewhere harmless. The expression is parsed by sympy,
so an `f(x)` written with `min`, `max`, `abs` or `round` would not go through it
and would have to stay on the wave. And alpha is the project's own word for
itself. Apache-2.0 into GPL-3 is compatible in this direction, so depending on
it or vendoring it is open either way.

## What to do

Take ncgears, behind a `tooth_style` property, with the wave kept as the default
so the workbench still builds a pair with nothing installed beyond
`freecad.gears`. It is the only one of the three that does not mean writing and
then owning an envelope solver, and the mapping onto the properties that already
exist is one line each. If the dependencies turn out to be unwelcome, the rack
envelope by boolean subtraction is the fallback, and the rack for it is already
sitting in `pygears`.

Either way `tooth_interference` is how we would know: it is already the number
this is about, and conjugate flanks should take it to nothing.

## What has not been checked

How long an ncgears generation takes, which decides whether it can sit behind a
dialog that rebuilds as it is typed into. Whether its outlines mesh to this
workbench's own measure once built as solids. Whether a pair it draws and a pair
drawn here agree on where the gears go.
