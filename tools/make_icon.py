"""Draw the workbench icon from the geometry the workbench actually generates.

Run from the repository root; overwrites freecad/noncirculargears/icons.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

from freecad.noncirculargears import noncircular  # noqa: E402

FUNCTION = "1 + 0.45 * cos(2 * x)"
CENTER_DISTANCE = 60.0
NUM_TEETH = 16
SIZE = 64.0
MARGIN = 3.0


def main():
    pair, _ = noncircular.from_ratio(
        noncircular.sample_function(FUNCTION, 512), CENTER_DISTANCE
    )
    driver, mate = noncircular.tooth_profiles(pair, NUM_TEETH, 16, 0.14)
    # the mate as the workbench places it: on the line of centres, turned to face
    placed = np.column_stack((CENTER_DISTANCE - mate[:, 0], -mate[:, 1]))

    both = np.vstack((driver, placed))
    low, high = both.min(0), both.max(0)
    scale = (SIZE - 2 * MARGIN) / (high - low).max()
    flip = np.array([1.0, -1.0])  # SVG y grows downward
    offset = np.array([SIZE / 2, SIZE / 2]) - 0.5 * (low + high) * scale * flip

    def place(point):
        return np.asarray(point) * scale * flip + offset

    def path(points):
        return "M " + " L ".join("%.2f %.2f" % tuple(place(p)) for p in points) + " Z"

    axes = [place((0.0, 0.0)), place((CENTER_DISTANCE, 0.0))]
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" '
        'viewBox="0 0 64 64">\n'
        '  <path d="%s" fill="#e8963c" stroke="#7d4a12" stroke-width="1.2" '
        'stroke-linejoin="round"/>\n'
        '  <path d="%s" fill="#c94f3d" stroke="#6d2418" stroke-width="1.2" '
        'stroke-linejoin="round"/>\n'
        '  <circle cx="%.2f" cy="%.2f" r="2.4" fill="#1f5c1f"/>\n'
        '  <circle cx="%.2f" cy="%.2f" r="2.4" fill="#1f5c1f"/>\n'
        "</svg>\n"
    ) % (path(driver), path(placed), axes[0][0], axes[0][1], axes[1][0], axes[1][1])

    target = os.path.join(
        os.path.dirname(__file__),
        os.pardir,
        "freecad",
        "noncirculargears",
        "icons",
        "noncirculargear.svg",
    )
    with open(target, "w") as handle:
        handle.write(svg)
    print("wrote %s (%d bytes)" % (os.path.normpath(target), len(svg)))


if __name__ == "__main__":
    main()
