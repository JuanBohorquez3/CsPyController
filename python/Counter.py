'''Counter.py
Part of the AQuA Cesium Controller software package

author=Martin Lichtman
created=2013-10-19
modified>=2013-10-19

This file holds everything to model a National Instruments DAQmx counter.  It communicated to LabView via the higher up LabView class.
'''

from cs_errors import PauseError, setupLog
logger=setupLog(__name__)

from cs_instruments import Instrument

class Counter(Instrument):
    pass