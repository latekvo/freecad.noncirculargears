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

What is asked for is a particular build, so being able to import ncgears is
not the end of it: what is installed is checked against what is asked for, and
installed over where the two differ.
"""

import glob
import importlib
import importlib.metadata
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

from freecad import app

# What package.xml asks for. pip brings what ncgears itself needs - shapely
# and ezdxf - along with it; numpy, scipy and sympy ship with FreeCAD.
WANTED = ("ncgears",)

# ncgears comes from a fork rather than from PyPI. It is upstream's own v0.3.1
# with the geometry engine doing the same arithmetic with less work: outlines
# and every number reported about them come back bit-identical, and a pair is
# cut in about half the time. NOTICE in the fork records what was changed.
#
# A package is asked for by name and installed by requirement, which are the
# same string for anything off PyPI and are not for this. pip reports what it
# resolved by name, so the two are kept apart here rather than assumed equal.
REQUIREMENTS = {
    "ncgears": (
        "ncgears @ https://github.com/latekvo/ncgears/releases/download/"
        "v0.3.1-speedups.1/ncgears-0.3.1%2Bspeedups.1-py3-none-any.whl"
    ),
}

# What each of those requirements installs. Both builds cut the same pair the
# same way and only one of them cuts it in half the time, so nothing about a
# pair says which was underneath: having ncgears is not having this one.
BUILDS = {"ncgears": "0.3.1+speedups.1"}


def requirement(name):
    """How pip is asked for ``name``, which for most things is the name."""
    return REQUIREMENTS.get(name, name)


def build(name):
    """The build ``requirement`` installs, or ``None`` where it pins none."""
    return BUILDS.get(name)


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


def _installed_in(directory, name):
    """Every install of ``name`` in ``directory``, as (metadata path, build).

    Read out of the one directory rather than off the path, and as a list
    because more than one of them can describe the same package: installing
    over a ``--target`` directory replaces the package but writes the new
    dist-info beside the one already there, and which of the two anything is
    answered with afterwards is whichever the filesystem lists first.
    """
    found = []
    for entry in sorted(glob.glob(os.path.join(directory, "*.dist-info"))):
        try:
            distribution = importlib.metadata.PathDistribution(pathlib.Path(entry))
            named = (distribution.metadata["Name"] or "").lower()
        except Exception:
            continue
        if named == name.lower():
            found.append((entry, distribution.version or ""))
    return found


def in_use(name):
    """The directory ``name`` would be imported from, and the builds in it.

    ``(None, [])`` where it would not be imported at all. Which directory it
    comes from is the question, not whether it is somewhere: FreeCAD puts the
    one an addon's packages go into after site-packages, so an ncgears
    installed there is what cuts a pair whatever this fetches.
    """
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        spec = None
    if spec is None:
        return None, []
    locations = list(getattr(spec, "submodule_search_locations", None) or [])
    origin = locations[0] if locations else (spec.origin or "")
    if not origin:
        return None, []
    directory = os.path.dirname(origin)
    return directory, sorted(held for _, held in _installed_in(directory, name))


def _same_directory(one, other):
    """Whether two paths name the same directory."""
    return os.path.normcase(os.path.realpath(one)) == os.path.normcase(
        os.path.realpath(other)
    )


def outdated(directory, packages=WANTED):
    """Those of ``packages`` in ``directory`` that are not the build asked for.

    Only what is in ``directory`` counts, because that is the copy this
    installed and the only one it can install over. Anything but the wanted
    build on its own is a directory to install over again - a stock ncgears
    that was fetched before this workbench asked for the fork, or the pair of
    dist-info an install over it leaves behind.
    """
    stale = []
    for name in packages:
        wanted = build(name)
        if wanted is None:
            continue
        where, builds = in_use(name)
        if where and _same_directory(where, directory) and builds != [wanted]:
            stale.append(name)
    return stale


def _drop_other_builds(directory, name, kept):
    """Take away what an install over ``name`` in ``directory`` left behind.

    ``--upgrade`` replaces the package and writes its own dist-info, leaving
    the one it replaced to describe files that are no longer there. It would
    be answered with just as readily as the build that is really installed, so
    it goes the way of the files it described.
    """
    for entry, held in _installed_in(directory, name):
        if held != kept:
            shutil.rmtree(entry, ignore_errors=True)


def _mention_what_cuts(packages=WANTED):
    """Say when a cut will not use the build this workbench asks for.

    Installing it is not the same as using it. The directory it goes into
    comes after site-packages, so an ncgears somebody put there is what a cut
    imports and no amount of fetching changes that; all it changes is how long
    a pair takes, which is not something a pair can be looked at to find out.
    """
    for name in packages:
        wanted = build(name)
        if wanted is None:
            continue
        where, builds = in_use(name)
        if where is None or builds == [wanted]:
            continue
        app.Console.PrintWarning(
            "Non-Circular Gear: involute teeth will be cut by the {} in {} "
            "rather than the {} asked for, which cuts a pair in about half "
            'the time. To replace it: pip install --upgrade "{}"\n'.format(
                "%s %s" % (name, ", ".join(builds)) if builds else name,
                where,
                wanted,
                requirement(name),
            )
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
            + [requirement(name) for name in packages]
        )
        with open(report) as handle:
            resolved = json.load(handle)

    names = [item["metadata"]["name"] for item in resolved.get("install", [])]
    return [name for name in names if not _held_already(name)]


def ensure():
    """Fetch what the involute teeth need, if it is not here or is not ours.

    Returns what is still missing, which is nothing when all is well. Looked
    into once a session, and said out loud at each point it matters - starting
    a download without a word, failing to, and cutting with an ncgears other
    than the one asked for are each worse in silence.
    """
    global _attempted

    absent = missing()
    if _attempted:
        return absent
    _attempted = True

    stale = []
    try:
        directory = vendor_directory()
        stale = outdated(directory)
        if not absent and not stale:
            _mention_what_cuts()
            return absent
        needed = (_what_is_needed(absent, directory) if absent else []) + stale
        app.Console.PrintMessage(
            "Non-Circular Gear: installing {} into {}\n".format(
                ", ".join(needed), directory
            )
        )
        # --upgrade because the install that matters most is the one over a
        # package already in that directory: without it pip leaves what is
        # there alone and reports the build it did not install as installed.
        _pip(
            ["install", "--no-deps", "--upgrade", "--target", directory]
            + [requirement(name) for name in needed]
        )
        for name in needed:
            kept = build(name)
            if kept is not None:
                _drop_other_builds(directory, name, kept)
    except Exception as failure:
        if absent:
            app.Console.PrintWarning(
                "Non-Circular Gear: could not install {} ({}). Involute teeth "
                "need it; the other styles do not.\n".format(
                    ", ".join(absent), _why(failure)
                )
            )
        elif stale:
            app.Console.PrintWarning(
                "Non-Circular Gear: could not install the build of {} asked "
                "for ({}). Teeth are cut by the one that is here either way, "
                "and it takes about twice as long over them.\n".format(
                    ", ".join(stale), _why(failure)
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
        return still

    app.Console.PrintMessage("Non-Circular Gear: {} ready\n".format(
        ", ".join(absent or stale)
    ))
    if any(name in sys.modules for name in stale):
        app.Console.PrintMessage(
            "Non-Circular Gear: the {} imported earlier this session is what "
            "cuts until FreeCAD is restarted\n".format(", ".join(stale))
        )
    _mention_what_cuts()
    return still
