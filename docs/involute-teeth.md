# Involute teeth

The teeth this workbench draws by default are a sine wave laid along each pitch
line's arc length in antiphase. The pitch lines roll exactly; the flanks are not
conjugate, so a tooth passes a little way into the gap it meshes with - 0.012 mm
on a 1.07 mm tooth for the default pair, which `tooth_interference` measures and
`backlash` clears.

`tooth_style = involute` replaces them with flanks that are conjugate, cut by
[ncgears](https://github.com/kylebme/ncgears). This is the note that found it,
kept up to date with what it turned out to cost.

## The involute does not port from freecad.gears

`pygears.involute_tooth.InvoluteTooth` builds a flank from the base circle:
`involute_function_x` is `dg/2 * (cos(phi) + phi * sin(phi))` and `dg` is a
diameter, derived from the module, the tooth count and the pressure angle. A
non-circular gear has no single base circle to put there, and no single pitch
radius to derive one from, so there is nothing in that class to point at a pitch
line whose radius varies.

What does carry over is one class further down: `InvoluteRack.points()` returns
the straight-flanked rack as a polyline, from the module and the pressure angle
alone. That is the cutter, and the cutter is what a non-circular gear is
actually given its flanks by. Rolling it along a pitch line and taking the
envelope of where it has been is the textbook construction (Litvin's, the one
elliptical gears are hobbed by), and it is the part that would have to be
written. So: the rack ports, the tooth does not, and the envelope is the whole
job.

## Three ways to get there

**The local equivalent circular gear.** At each tooth, take the radius of
curvature of the pitch curve there as the pitch radius of an ordinary circular
involute gear, and stand one standard tooth on it. Genuine involute flanks,
exact only where the curvature is locally constant, and wrong by however much it
is not. `phillbaker/non-circular-gears-generator` (BSD, Python 2.5, thirteen
commits) is this. Cheapest of the three and the least correct.

**The rack envelope.** Roll the rack along the pitch line and take the envelope
of its flank positions. Most of the input is already here: `PitchPair` holds the
rolling as `theta`, `angle2` and `arc`. The missing piece is the envelope, and
undercutting where the pitch curve's curvature is smallest is the known failure
mode. This means writing and then owning an envelope solver.

**Hand it to ncgears**, which is what was done.

## What was built

`involute.py` is the translation, and only that - no flank is worked out here.
The mapping onto ncgears is close to one line each:

| this workbench | ncgears |
|---|---|
| `function`, in gear ratio mode | centrode `a / (1 + ratio_scale * f)`, as a SymPy expression |
| `function`, in pitch radius mode | centrode `f` |
| `num_teeth` | `teeth` |
| `mate_turns` : `driver_turns` | `target_cycle_delta = 2*pi * driver_lobes / mate_lobes` |
| the pitch length already solved for | `module`, so a tooth is the size it would have been |
| `tooth_height` | `addendum_factor = tooth_height * pi`, dedendum and fillet in proportion |
| `backlash` | `clearance`, half of it a face, in modules |
| `pressure_angle` | `pressure_angle_deg` |

ncgears solves its own centre distance from the turns it is given, so the pair
comes back scaled onto the one this pair is drawn at. That is a whole scaling,
which leaves conjugate flanks conjugate.

Two things had to be handled that only showed up against real outlines:

**Thinning.** ncgears returns some fourteen thousand points a gear, an order of
magnitude more than a spline through them needs. Dropping every nth point spaces
them evenly but rounds the corners at the tooth tips, moving the outline by
0.13 mm - a tenth of a tooth. Dropping by a tolerance keeps the corners but
leaves points four microns apart at the fillets and a third of a millimetre
apart along the flanks, and the spline fitted through that crosses itself, which
leaves the solid invalid. `_thinned` bounds all three: the tolerance, the
closest two points may be, and the furthest.

**Numpy scalars.** ncgears writes a JSON summary of what it was given, and a
numpy scalar reaching it comes back out as a numpy bool that `json` will not
write. Everything crossing the boundary is a plain float.

## What it costs

- **Five to fifteen seconds a pair**, against a tenth of a second for the wave.
  `samples_per_radian` barely moves it; the flank construction is the cost. This
  is why `profiles` is cached on the gear: without it a rebuild cuts the pair
  twice, once for each half.
- **shapely and ezdxf**, which FreeCAD does not ship. It does ship numpy, scipy
  and sympy, which ncgears also wants.
- **An f(x) SymPy can read and differentiate.** `min`, `max` and friends do not
  go through, and say so rather than being drawn wrong.
- **Alpha**, which is the project's own word for itself.
- **Some pairs it will not cut.** A three-lobe driver with 24 teeth at the
  default tooth height fails with "could not intersect drive analytic flank with
  its addendum boundary"; a shorter tooth (`tooth_height` 0.19 rather than 0.14)
  cuts it. Apache-2.0 into GPL-3 is fine in this direction.

## What is checked, and by whom

The workbench checks what it is answerable for: that both gears build as valid
solids, that the teeth counted off the built shapes are `num_teeth` and
`mate_teeth`, and that the pair comes back at the centre distance solved for.

How conjugate the flanks are is ncgears' own measurement, carried through to
`transmission_error` - 2.4e-7 degrees for the default pair, against
`tooth_interference` of 0.012 mm for the wave. It is reported rather than
measured again here, and that is a real limitation rather than a convenience:
the sweep `noncircular.interference` runs reads an outline as a radius against
an angle, which needs the outline to be star-shaped about its axis. An involute
outline is not - the angle doubles back four to sixteen thousandths of a radian
at every root fillet - and sorting those points by angle folds them over the
teeth, which reports a tooth of penetration on a pair ncgears has verified has
none. So `tooth_interference` reads 0 for involute teeth rather than reading
something untrue.

Checking the flanks independently would mean rolling the pair from its assembled
position and finding the contact at each phase - which is the envelope work
again, in another guise.
