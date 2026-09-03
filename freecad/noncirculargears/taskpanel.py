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

"""The dialog a new gear pair is set up in.

Its rows are read off the driving gear's own properties - their types, their
limits, what they are documented as - so a parameter is described once, on the
gear, and turns up here without being named again.

The pair the dialog edits is already in the document and inside an open
transaction, which is what lets every change show up in the 3D view as it is
made and still leave nothing behind if the dialog is cancelled.
"""

from PySide import QtWidgets

from freecad import app

# The order a pair is worth deciding in, which alphabetical cannot carry.
PARAMETER_ORDER = (
    "mode",
    "function",
    "center_distance",
    "num_teeth",
    "mate_turns",
    "driver_turns",
    "height",
    "helix_angle",
    "tooth_style",
    "tooth_height",
    "pressure_angle",
    "backlash",
    "points_per_tooth",
    "samples",
)

PARAMETER_GROUPS = ("base", "accuracy")


def parameters(obj):
    """The gear's own parameters, in the order they are worth setting in.

    Anything the gear grows later is kept rather than dropped, so the dialog
    falls behind by an unordered row rather than by a missing one.
    """
    own = set(
        name
        for name in obj.PropertiesList
        if obj.getGroupOfProperty(name) in PARAMETER_GROUPS
    )
    ordered = [name for name in PARAMETER_ORDER if name in own]
    return ordered + sorted(own.difference(ordered))


class _Row(object):
    """One parameter, its widget, and the two directions between them."""

    def __init__(self, obj, name):
        self.name = name
        self.widget = self.build(obj, name)
        self.widget.setObjectName(name)
        self.widget.setToolTip(obj.getDocumentationOfProperty(name))
        self.show(getattr(obj, name))

    def show(self, value):
        """Put the property's own reading of the value back into the widget.

        Signals stay blocked for it: a property that clamps what it was given
        would otherwise be answered with another edit of the same row.
        """
        self.widget.blockSignals(True)
        self.display(value)
        self.widget.blockSignals(False)


class _Text(_Row):
    def build(self, obj, name):
        return QtWidgets.QLineEdit()

    def changed(self):
        return self.widget.editingFinished

    def display(self, value):
        self.widget.setText(value)

    def read(self):
        return self.widget.text()


class _Quantity(_Text):
    """A length, shown with its unit and handed back as text for FreeCAD to parse."""

    def display(self, value):
        self.widget.setText(value.UserString)


class _Choice(_Row):
    def build(self, obj, name):
        widget = QtWidgets.QComboBox()
        widget.addItems(obj.getEnumerationsOfProperty(name))
        return widget

    def changed(self):
        return self.widget.currentTextChanged

    def display(self, value):
        self.widget.setCurrentText(value)

    def read(self):
        return self.widget.currentText()


class _Whole(_Row):
    """A counted parameter, left to the property itself to keep within its limits."""

    def build(self, obj, name):
        widget = QtWidgets.QSpinBox()
        widget.setRange(1, 1000000)
        return widget

    def changed(self):
        return self.widget.editingFinished

    def display(self, value):
        self.widget.setValue(value)

    def read(self):
        return self.widget.value()


class _Fraction(_Row):
    def build(self, obj, name):
        widget = QtWidgets.QDoubleSpinBox()
        widget.setRange(0.0, 1000000.0)
        widget.setDecimals(3)
        widget.setSingleStep(0.01)
        return widget

    def changed(self):
        return self.widget.editingFinished

    def display(self, value):
        self.widget.setValue(value)

    def read(self):
        return self.widget.value()


ROW_KINDS = {
    "App::PropertyString": _Text,
    "App::PropertyLength": _Quantity,
    "App::PropertyDistance": _Quantity,
    "App::PropertyAngle": _Quantity,
    "App::PropertyEnumeration": _Choice,
    "App::PropertyIntegerConstraint": _Whole,
    "App::PropertyFloatConstraint": _Fraction,
}


class GearPairPanel(object):
    """Sets up the pair that the Gear Pair command has just put in the document.

    Accepting keeps it and cancelling undoes the whole of it, the pair included,
    by committing or aborting the transaction the command opened.
    """

    def __init__(self, driver, mate):
        self.driver = driver
        self.mate = mate
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(
            app.Qt.translate("NonCircularGear_Pair", "Non-Circular Gear Pair")
        )
        layout = QtWidgets.QFormLayout(self.form)

        self.rows = []
        for name in parameters(driver):
            row = ROW_KINDS[driver.getTypeIdOfProperty(name)](driver, name)
            row.changed().connect(self.apply)
            layout.addRow(name.replace("_", " "), row.widget)
            self.rows.append(row)

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        layout.addRow(self.status)

    def apply(self):
        """Put every row onto the gear, rebuild it, and report what it made of them."""
        try:
            for row in self.rows:
                setattr(self.driver, row.name, row.read())
        except (ValueError, TypeError) as err:
            self.status.setText(str(err))
        else:
            self.status.setText(self.rebuild())
        for row in self.rows:
            row.show(getattr(self.driver, row.name))

    def rebuild(self):
        """Recompute the pair, and say why if it would not build."""
        self.driver.Document.recompute()
        if "Invalid" not in self.driver.State:
            return ""
        try:
            self.driver.Proxy.generate_gear_shape(self.driver)
        except Exception as err:
            return str(err)
        return app.Qt.translate("NonCircularGear_Pair", "the pair could not be built")

    def accept(self):
        self.apply()
        self.driver.Document.commitTransaction()
        return True

    def reject(self):
        document = self.driver.Document
        names = [self.mate.Name, self.driver.Name]
        document.abortTransaction()
        # A document with undo turned off has no transaction to abort, and would
        # be left holding the pair that cancelling is meant to have never made.
        for name in names:
            if document.getObject(name) is not None:
                document.removeObject(name)
        return True
