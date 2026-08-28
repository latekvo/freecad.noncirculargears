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

__dirname__ = os.path.dirname(__file__)


class NonCircularGearWorkbench(gui.Workbench):
    """A pair of gears whose ratio varies over a turn"""

    MenuText = app.Qt.translate("Workbench", "Non-Circular Gear")
    ToolTip = app.Qt.translate("Workbench", "Non-Circular Gear Workbench")
    Icon = os.path.join(__dirname__, "icons", "noncirculargear.svg")
    commands = ["NonCircularGear_Pair"]

    def GetClassName(self):
        return "Gui::PythonWorkbench"

    def Initialize(self):
        QT_TRANSLATE_NOOP = app.Qt.QT_TRANSLATE_NOOP
        from .commands import CreateNonCircularGearPair

        self.appendToolbar(
            QT_TRANSLATE_NOOP("Workbench", "Non-Circular Gear"), self.commands
        )
        self.appendMenu(
            QT_TRANSLATE_NOOP("Workbench", "Non-Circular Gear"), self.commands
        )
        gui.addCommand("NonCircularGear_Pair", CreateNonCircularGearPair())

    def Activated(self):
        pass

    def Deactivated(self):
        pass


gui.addWorkbench(NonCircularGearWorkbench())
