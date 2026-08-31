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

import os

from freecad import app
from freecad import gui
from freecad.gears.basegear import ViewProviderGear

from .noncirculargear import NonCircularGear, NonCircularGearMate
from .taskpanel import GearPairPanel

QT_TRANSLATE_NOOP = app.Qt.QT_TRANSLATE_NOOP


class CreateNonCircularGearPair(object):
    """Create a non-circular gear and the gear that meshes with it."""

    ICONDIR = os.path.join(os.path.dirname(__file__), "icons")
    Pixmap = os.path.join(ICONDIR, "noncirculargear.svg")
    MenuText = QT_TRANSLATE_NOOP("NonCircularGear_Pair", "Gear Pair")
    ToolTip = QT_TRANSLATE_NOOP(
        "NonCircularGear_Pair",
        "Create a pair of meshing non-circular gears from a gear ratio function",
    )

    def IsActive(self):
        return app.ActiveDocument is not None and not gui.Control.activeDialog()

    def Activated(self):
        """Put a pair in the document, then open it for setting up.

        The pair is built first and edited in place, so the dialog's every
        parameter is one the gear itself has and each change shows in the 3D
        view. It goes into a transaction of its own, which cancelling aborts and
        so takes the pair back out again.
        """
        document = app.ActiveDocument
        if gui.Control.activeDialog():
            # The toolbar cannot reach this, but a macro calling it can, and the
            # pair it made would be left with no dialog to finish or cancel it.
            app.Console.PrintError(
                app.Qt.translate(
                    "Log", "close the open task dialog before starting a gear pair\n"
                )
            )
            return

        document.openTransaction("Create non-circular gear pair")
        before = set(document.Objects)
        gui.doCommandGui("import freecad.noncirculargears.commands")
        gui.doCommandGui(
            "freecad.noncirculargears.commands.CreateNonCircularGearPair.create()"
        )
        document.recompute()
        gui.SendMsgToActiveView("ViewFit")

        made = [obj for obj in document.Objects if obj not in before]
        mate = next(obj for obj in made if hasattr(obj, "master"))
        gui.Control.showDialog(GearPairPanel(mate.master, mate))

    @classmethod
    def create(cls):
        """Both gears, the second linked to and positioned against the first.

        A pair is two bodies at two axes, so unlike a single gear it has no
        place inside a PartDesign body; only a Part container takes it.
        """
        document = app.ActiveDocument
        driver = document.addObject("Part::FeaturePython", "NonCircularGear")
        NonCircularGear(driver)
        mate = document.addObject("Part::FeaturePython", "NonCircularGearMate")
        NonCircularGearMate(mate)
        mate.master = driver

        if app.GuiUp:
            ViewProviderGear(driver.ViewObject, cls.Pixmap)
            ViewProviderGear(mate.ViewObject, cls.Pixmap)
            container = gui.ActiveDocument.ActiveView.getActiveObject("part")
            if container:
                container.Group += [driver, mate]
        return driver, mate

    def GetResources(self):
        return {
            "Pixmap": self.Pixmap,
            "MenuText": self.MenuText,
            "ToolTip": self.ToolTip,
        }
