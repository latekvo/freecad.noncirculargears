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

"""The packages involute teeth need, fetched the way FreeCAD fetches them.

Installing a workbench through the Addon Manager installs whatever its
package.xml asks for, into a directory FreeCAD keeps beside the Mod tree for
exactly that. A checkout linked in by hand never goes through the Addon
Manager, so nothing fills that directory, and the difference shows up as a
workbench telling whoever opened it to go and run pip.

So it is filled from here instead, through the Addon Manager's own call, which
is what knows the platform, which pip to use and which flags that pip wants.
Only the GUI asks for this: a headless run is somebody's script, and a script
that quietly grew a package would be worse than one that said what it lacked.
"""

import importlib
import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

from freecad import app

# What package.xml asks for. pip brings what ncgears itself needs - shapely
# and ezdxf - along with it; numpy, scipy and sympy ship with FreeCAD.
WANTED = ("ncgears",)

def _why(failure):
    """What went wrong, in the words of whatever went wrong."""
    said = getattr(failure, "stderr", None) or getattr(failure, "stdout", None)
    if not said:
        return str(failure)
    return said.strip().splitlines()[-1]


# One attempt a session. Offline, the second try would fail as slowly as the
# first, and it would do it every time the workbench was opened.
_attempted = False


def missing(packages=WANTED):
    """Those of ``packages`` that are not importable, without importing them."""
    absent = []
    for name in packages:
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            absent.append(name)
    return absent


def vendor_directory():
    """Where the Addon Manager puts the packages it installs for an addon.

    Put on the path as well as returned: FreeCAD only adds it at startup, and
    on the run that creates it there was nothing there to add.
    """
    from addonmanager_utilities import get_pip_target_directory

    directory = get_pip_target_directory()
    if directory and directory not in sys.path:
        sys.path.append(directory)
    return directory


def _pip(arguments):
    """Run pip the way FreeCAD runs it, and hand back what it said."""
    from addonmanager_utilities import create_pip_call

    return subprocess.run(
        create_pip_call(arguments),
        capture_output=True,
        text=True,
        check=True,
    )


def _held_already(distribution):
    """Whether FreeCAD can already import ``distribution``, by its packaged name."""
    try:
        importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


def _what_is_needed(packages, directory):
    """Of everything ``packages`` pull in, the ones that are not here yet.

    ``--target`` cannot see what FreeCAD already ships, so left to itself pip
    fills that directory with its own numpy, scipy and sympy - a third of a
    gigabyte, and worse than the waste, the directory goes on the path in
    front of the ones FreeCAD meant to be used. So pip is asked what it would
    install rather than told to install it, and only what is really absent is
    then fetched. Asking beats a list kept here, which would be a copy of
    somebody else's dependencies going quietly out of date.
    """
    with tempfile.TemporaryDirectory() as scratch:
        report = os.path.join(scratch, "resolved.json")
        _pip(
            ["install", "--dry-run", "--report", report, "--target", directory]
            + list(packages)
        )
        with open(report) as handle:
            resolved = json.load(handle)

    names = [item["metadata"]["name"] for item in resolved.get("install", [])]
    return [name for name in names if not _held_already(name)]


def ensure():
    """Fetch anything the involute teeth need that is not here yet.

    Returns what is still missing, which is nothing when all is well. Tried
    once a session, and said out loud both times it matters - starting a
    download without a word, and failing to, are each worse in silence.
    """
    global _attempted

    absent = missing()
    if not absent or _attempted:
        return absent
    _attempted = True

    try:
        directory = vendor_directory()
        needed = _what_is_needed(absent, directory)
        app.Console.PrintMessage(
            "Non-Circular Gear: installing {} into {}\n".format(
                ", ".join(needed), directory
            )
        )
        _pip(["install", "--no-deps", "--target", directory] + needed)
    except Exception as failure:
        app.Console.PrintWarning(
            "Non-Circular Gear: could not install {} ({}). Involute teeth "
            "need it; wave teeth do not.\n".format(
                ", ".join(absent), _why(failure)
            )
        )
        return absent

    importlib.invalidate_caches()
    still = missing()
    if still:
        app.Console.PrintWarning(
            "Non-Circular Gear: {} installed but still not importable\n".format(
                ", ".join(still)
            )
        )
    else:
        app.Console.PrintMessage("Non-Circular Gear: {} ready\n".format(
            ", ".join(absent)
        ))
    return still
