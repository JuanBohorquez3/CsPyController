"""
TTL.py
Part of the AQuA Cesium Controller software package

author=Martin Lichtman
created=2014-04-25
modified>=2014-04-25

This file is used for the lock monitors, and other things that require checking a TTL input.
"""

from __future__ import division
import logging
logger = logging.getLogger(__name__)


from atom.api import Bool, Int, Float, Str, Typed, Member, List, observe, Atom
from enaml.application import deferred_call
from instrument_property import Prop, BoolProp, IntProp, FloatProp, StrProp, ListProp
from cs_instruments import Instrument
from analysis import Analysis


class TTL(Instrument):
    version = '2014.04.24'
    enable = Bool(False)
    lines = Str('PXI1Slot6/port0/lines1:2')

    def __init__(self, experiment):
        super(TTL, self).__init__('TTL', experiment)
        self.properties += ['version', 'enable', 'lines']

    def evaluate(self):
        if self.experiment.allow_evaluation:
            logger.debug('TTL.evaluate()')
            super(TTL, self).evaluate()

class TTL_filters(Analysis):
    """This analysis monitors the TTL inputs and does either hard or soft cuts of the data accordingly.
    Low is good, high is bad."""

    text = Str()
    filter_level = Int()

    def __init__(self, name, experiment, description=''):
        super(TTL_filters, self).__init__(name, experiment, description)
        self.properties += ['text', 'lines']

    def analyzeMeasurement(self, measurementResults, iterationResults, experimentResults):
        text = 'none'
        if self.enable:
            if 'TTL/data' in measurementResults['data']:
                a = measurementResults['data/TTL/data']
                text = str(a)
                #check to see if any of the inputs were True
                if numpy.any(a):
                    #report the true inputs
                    text = 'TTL Filters failed:\n'
                    for i,b in enumerate(a):
                        #print out the row and column of the True input
                        text += 'Check {}: Laser(s) {}\n'.format(i, arange(len(b))[b])
                    #record to the log and screen
                    logger.warning(text)
                    self.set_gui({'text': text})
                    # User chooses whether or not to delete data.
                    # max takes care of ComboBox returning -1 for no selection
                    return max(0, self.filter_level)
                else:
                    text = 'okay'
        self.set_gui({'text': text})
