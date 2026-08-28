# freecad.noncirculargears

A FreeCAD workbench that turns a gear ratio function into two gears that mesh.

Give it `f(x)` over one turn of the first gear, `x` in radians from `0` to
`2*pi` and `f(x)` anywhere above zero, and one command leaves two solids in the
document, drawn on the line of centres in the position they mesh at.

```
f(x) = 1 + 0.55 * cos(x)        the first gear turns the second between
                                0.54 and 1.86 times its own speed
```

![a pair, drawn by this workbench, from f(x) = 1 + 0.45 * cos(2 * x)](freecad/noncirculargears/icons/noncirculargear.svg)

## Where it comes from

The pitch curve construction is [Julien Piellard's non-circular-gears
generator](https://github.com/piellardj/non-circular-gears) - both gears
reduced to their operating pitch lines, teeth laid on top as a wave - carried
over to FreeCAD. The document objects, the view provider, the attachment
handling and the PartDesign integration are [looooo's
freecad.gears](https://github.com/looooo/freecad.gears), which this workbench
imports rather than copies and therefore requires.

## Installing

Link or copy this directory into FreeCAD's user `Mod` directory, beside
`freecad.gears`:

    ln -s ~/dev/freecad.noncirculargears ~/.local/share/FreeCAD/v1-1/Mod/

Then pick **Non-Circular Gear** from the workbench list and use **Non-Circular
Gear > Gear Pair**.

## What it makes

Two objects. `NonCircularGear` carries every parameter and draws the driving
gear; `NonCircularGearMate` links to it, draws the gear that meshes with it,
and places itself - so its `Placement` is driven rather than edited, and
editing the driver rebuilds both.

| property | |
|---|---|
| `mode` | whether `function` is the gear ratio or the first gear's pitch radius |
| `function` | `f(x)`, Python, with the `math` module's names in scope |
| `center_distance` | distance between the axes; solved for in pitch radius mode |
| `num_teeth` | teeth, the same number on both gears |
| `height` | extrusion height; `0` leaves the bare outline |
| `tooth_height` | tooth height above the pitch line, as a fraction of the circular pitch |
| `backlash` | gap held open between the two tooth surfaces |
| `samples`, `points_per_tooth` | how finely `f(x)` and the outline are sampled |

and five read-only ones: `solved_center_distance`, `ratio_scale`, `min_ratio`,
`max_ratio`, and `tooth_interference`, which the last section is about.

## The two modes

**gear ratio.** `f(x)` is `w1 / w2`, the driving gear's speed over the driven
gear's. The centre distance only scales the pair, so it is taken as given.

**pitch radius.** `f(x)` is the first gear's pitch radius in millimetres, which
is the way in for a shape you already have. The centre distance is then solved
for instead of used, and `solved_center_distance` reports it.

Either way the second gear's shape falls out of the first's; the two readings
of "give me the shapes of two gears" meet in the same pipeline, since a ratio
of `f` is a radius of `a / (1 + f)` and a radius of `r` is a ratio of
`(a - r) / r`.

## Two things worth knowing

**Your `f(x)` may be scaled.** The second gear only closes into itself if the
integral of `1 / f` over the turn comes to one full turn. In gear ratio mode
nothing else can fix that, so `f` is multiplied by whatever constant does, and
`ratio_scale` reports the factor. It is a constant, so the *variation* you
asked for survives: `2 + cos(x)` still swings by a factor of three between its
slowest and its fastest, whatever constant it is multiplied by. The
average ratio over a turn is therefore always 1:1 - both gears turn once. In
pitch radius mode the shape is kept exactly and the centre distance moves
instead.

**The teeth are approximate; the rolling is not.** The pitch lines roll on each
other exactly - the contact stays on the line of centres and the delivered
ratio is the `f(x)` you asked for to about one part in 10^5. The teeth are a
sine wave laid along the arc length of each pitch line in antiphase, not
conjugate flanks, so a tooth passes about a hundredth of its own height into
the gap it meshes with. `tooth_interference` measures exactly that, over a
whole revolution, and `backlash` clears it: for the default pair, 0.012 mm of
interference on a 1.07 mm tooth, and `backlash = 0.1 mm` takes it to -0.079 mm.
Raising `num_teeth` lowers it too.

## Checking it

    freecadcmd tests/test_noncirculargears.py

Thirty checks: both gears build as valid solids, the pitch points meet on
the line of centres, the delivered ratio is the one asked for, the teeth clear
each other, both modes solve, and an `f(x)` that goes negative, does not parse,
is not finite or reaches outside the `math` module is refused rather than drawn.

`tests/noncircular-gears.steps` drives the same thing through a real FreeCAD
window with [ReproCAD](https://github.com/latekvo/ReproCAD) - its header has the
command - and `docs/noncircular-gears.mp4` is that run: the pair built from one
menu entry, its computed values read off the property editor, and then `f(x)`
retyped in place so both gears rebuild.

![the default pair, and what it came out at](docs/pair-default.png)

![f(x) = 1 + 0.5 * cos(3 * x), from above](docs/pair-three-lobes.png)
