from __future__ import division
import logging

from cs_errors import PauseError
from atom.api import Member, Int

# get the config file
from __init__ import import_config

# Bring in other files in this package
from ConfigInstrument import Config
import functional_waveforms, analysis, instek_pst, save2013style, TTL, LabView
import DDS, roi_fitting
import picomotors, andor, picampython, vaunix, DCNoiseEater, Laird_temperature, AnalogInput
import Counter, conex, aerotech, unlock_pause, niscope, newportstage, nidaq_ai
import origin_interface
import FakeInstrument  # for testing
from pypico import PyPicoServer  # for communicating with a picomotor server
from blackfly import BlackflyClient  # communicates with Blackfly camera server
# from vital_sign_sound import Vitalsign

# analyses
from SquareROIAnalysis import SquareROIAnalysis
from recent_shot_analysis import RecentShotAnalysis
from image_sum_analysis import ImageSumAnalysis
from threshold_analysis import ThresholdROIAnalysis
from retention_analysis import RetentionAnalysis, RetentionGraph
from histogram_analysis import HistogramAnalysis, HistogramGrid
from beam_position_analysis import BeamPositionAnalysis

from experiments import Experiment

__author__ = 'Martin Lichtman'
logger = logging.getLogger(__name__)
config = import_config()


class AQuA(Experiment):
    """A subclass of Experiment which knows about all our particular hardware"""

    Config = Member()
    picomotors = Member()
    instekpsts = Member()
    aerotechs = Member()
    conexes = Member()
    Andors = Member()
    blackfly_client = Member()
    NewportStage = Member()
    DAQmxAI = Member()
    vaunixs = Member()
    PICams = Member()
    LabView = Member()
    DDS = Member()
    DC_noise_eaters = Member()
    box_temperature = Member()
    unlock_pause = Member()
    pyPicoServer = Member()
    Embezzletron = Member()
    NIScopes = Member()

    functional_waveforms = Member()
    functional_waveforms_graph = Member()
    TTL_filters = Member()
    AI_graph = Member()
    AI_filter = Member()
    squareROIAnalysis = Member()
    thresholdROIAnalysis = Member()
    gaussian_roi = Member()
    loading_filters = Member()
    first_measurements_filter = Member()
    text_analysis = Member()
    recent_shot_analysis = Member()
    shotBrowserAnalysis = Member()
    imageSumAnalysis = Member()
    imageWithROIAnalysis = Member()
    histogramAnalysis = Member()
    histogram_grid = Member()
    # vitalsignsound=Member()
    measurements_graph = Member()
    iterations_graph = Member()
    retention_graph = Member()
    # andor_viewer = Member()
    picam_viewer = Member()
    DC_noise_eater_graph = Member()
    DC_noise_eater_filter = Member()
    Ramsey = Member()
    retention_analysis = Member()
    counter_graph = Member()
    counter_hist = Member()
    save_notes = Member()
    save2013Analysis = Member()
    beam_position_analysis = Member()
    origin = Member()
    ROI_rows = Int(1)
    ROI_columns = Int(1)
    ROI_bg_rows = Int(0)
    ROI_bg_columns = Int(0)

    def __init__(self):
        super(AQuA, self).__init__()

        # instruments CONFIG MUST BE FIRST INSTRUMENT
        self.Config = Config('Config', self, 'Configuration file')
        self.functional_waveforms = functional_waveforms.FunctionalWaveforms('functional_waveforms', self, 'Waveforms for HSDIO, DAQmx DIO, and DAQmx AO; defined as functions')
        self.aerotechs = aerotech.Aerotechs('aerotechs', self, 'Aerotech Ensemble')
        self.conexes = conex.Conexes('conexes', self, 'CONEX-CC')
        self.picomotors = picomotors.Picomotors('picomotors', self, 'Newport Picomotors')
        self.instekpsts = instek_pst.InstekPSTs('instekpsts', self, 'Instek PST power supply')
        self.Andors = andor.Andors('Andors', self, 'Andor Luca measurementResults')
        self.blackfly_client = BlackflyClient('BlackflyClient', self)
        self.vaunixs = vaunix.Vaunixs('vaunixs', self, 'Vaunix Signal Generator')
        self.PICams = picampython.PICams('PICams', self, 'Princeton Instruments Cameras')
        self.DAQmxAI = nidaq_ai.NIDAQmxAI('DAQmxAI', self, 'NI-DAQmx Analog Input')
        self.NewportStage = newportstage.NewportStage('NewportStage', self, 'Newport Translation Stage')
        self.LabView = LabView.LabView(self)
        self.DDS = DDS.DDS('DDS', self, 'server for homemade DDS boxes')
        self.DC_noise_eaters = DCNoiseEater.DCNoiseEaters('DC_noise_eaters', self)
        self.box_temperature = Laird_temperature.LairdTemperature('box_temperature', self)
        self.unlock_pause = unlock_pause.UnlockMonitor('unlock_pause', self, 'Monitor for pausing when laser unlocks')
        self.pyPicoServer = PyPicoServer('PyPicomotor', self, 'PyPico server interface for controlling closed loop picomotors')
        self.Embezzletron = FakeInstrument.Embezzletron('Embezzletron', self, 'Fake instrument that generates random data for testing')
        self.NIScopes = niscope.NIScopes('NIScopes', self, 'National Instruments Scopes')
        # do not include functional_waveforms in self.instruments because it
        # need not start/stop
        self.instruments += [
            self.box_temperature, self.picomotors, self.pyPicoServer,
            self.NIScopes, self.Andors, self.PICams, self.blackfly_client,
            self.DC_noise_eaters, self.DDS, self.unlock_pause,
            self.Embezzletron, self.aerotechs, self.conexes, self.instekpsts,
            self.vaunixs, self.NewportStage,
            self.LabView  # Labview must be last at least until someone fixes the start command
        ]

        # analyses
        self.functional_waveforms_graph = functional_waveforms.FunctionalWaveformGraph('functional_waveform_graph', self, 'Graph the HSDIO, DAQmx DO, and DAQmx AO settings')
        self.TTL_filters = TTL.TTL_filters('TTL_filters', self)
        self.AI_graph = AnalogInput.AI_Graph('AI_graph', self, 'Analog Input Graph')
        self.AI_filter = AnalogInput.AI_Filter('AI_filter', self, 'Analog Input filter')
        self.first_measurements_filter = analysis.DropFirstMeasurementsFilter('first_measurements_filter', self, 'drop the first N measurements')
        self.squareROIAnalysis = SquareROIAnalysis(self)
        self.gaussian_roi = roi_fitting.GaussianROI('gaussian_roi', self)
        self.thresholdROIAnalysis = ThresholdROIAnalysis(self)
        self.loading_filters = analysis.LoadingFilters('loading_filters', self, 'drop measurements with no atom loaded')
        self.text_analysis = analysis.TextAnalysis('text_analysis', self, 'text results from the measurement')
        self.imageSumAnalysis = ImageSumAnalysis(self)
        self.recent_shot_analysis = RecentShotAnalysis('recent_shot_analysis', self, description='just show the most recent shot')
        self.shotBrowserAnalysis = analysis.ShotsBrowserAnalysis(self)
        self.histogramAnalysis = HistogramAnalysis('histogramAnalysis', self, 'plot the histogram of any shot and roi')
        self.histogram_grid = HistogramGrid('histogram_grid', self, 'all 49 histograms for shot 0 at the same time')
        self.measurements_graph = analysis.MeasurementsGraph('measurements_graph', self, 'plot the ROI sum vs all measurements')
        self.iterations_graph = analysis.IterationsGraph('iterations_graph', self, 'plot the average of ROI sums vs iterations')
        self.retention_graph = RetentionGraph('retention_graph', self, 'plot occurence of binary result (i.e. whether or not atoms are there in the 2nd shot)')
        # self.andor_viewer = andor.AndorViewer('andor_viewer', self, 'show the most recent Andor image')
        # self.picam_viewer = picam.PICamViewer('picam_viewer', self, 'show the most recent PICam image')
        self.DC_noise_eater_graph = DCNoiseEater.DCNoiseEaterGraph('DC_noise_eater_graph', self, 'DC Noise Eater graph')
        self.DC_noise_eater_filter = DCNoiseEater.DCNoiseEaterFilter('DC_noise_eater_filter', self, 'DC Noise Eater Filter')
        self.Ramsey = analysis.Ramsey('Ramsey', self, 'Fit a cosine to retention results')
        self.retention_analysis = RetentionAnalysis('retention_analysis', self, 'calculate the loading and retention')
        self.counter_graph = Counter.CounterAnalysis('counter_graph', self, 'Graphs the counter data after each measurement.')
        self.counter_hist = Counter.CounterHistogramAnalysis('counter_hist', self, 'Fits histograms of counter data and plots hist and fits.')
        self.save_notes = save2013style.SaveNotes('save_notes', self, 'save a separate notes.txt')
        self.save2013Analysis = save2013style.Save2013Analysis(self)
        self.beam_position_analysis = BeamPositionAnalysis(self)
        # self.vitalsignsound=Vitalsign('vital_sign_sound',self,'beeps when atoms are loaded')
        self.origin = origin_interface.Origin('origin', self, 'saves selected data to the origin data server')

        # do not include functional_waveforms_graph in self.analyses because it
        # need not update on iterations, etc.
        # origin needs to be the last analysis always
        self.analyses += [
            self.TTL_filters, self.AI_graph, self.AI_filter,
            self.squareROIAnalysis, self.thresholdROIAnalysis,
            self.gaussian_roi, self.loading_filters,
            self.first_measurements_filter, self.text_analysis,
            self.imageSumAnalysis, self.recent_shot_analysis,
            self.shotBrowserAnalysis, self.histogramAnalysis,
            self.histogram_grid, self.measurements_graph,
            self.iterations_graph, self.DC_noise_eater_graph,
            self.DC_noise_eater_filter, self.Andors, self.PICams, self.Ramsey,
            self.DAQmxAI, self.unlock_pause,
            self.retention_analysis, self.retention_graph, self.counter_graph,
            self.save_notes, self.save2013Analysis, self.NIScopes,
            self.counter_hist,  # self.vitalsignsound,
            self.beam_position_analysis,
            self.origin  # origin has to be last
        ]

        self.properties += [
            'Config',
            'functional_waveforms', 'LabView', 'functional_waveforms_graph',
            'DDS', 'aerotechs', 'picomotors', 'pyPicoServer', 'conexes',
            'Andors', 'PICams', 'DC_noise_eaters', 'blackfly_client',
            'box_temperature', 'DAQmxAI', 'squareROIAnalysis',
            'thresholdROIAnalysis', 'gaussian_roi', 'instekpsts', 'TTL_filters',
            'AI_graph', 'AI_filter', 'NewportStage', 'loading_filters',
            'first_measurements_filter', 'vaunixs', 'imageSumAnalysis',
            'recent_shot_analysis', 'shotBrowserAnalysis', 'histogramAnalysis',
            'histogram_grid', 'retention_analysis', 'measurements_graph',
            'iterations_graph', 'retention_graph', 'DC_noise_eater_filter',
            'DC_noise_eater_graph', 'Ramsey', 'counter_graph', 'counter_hist',
            'unlock_pause', 'ROI_rows', 'ROI_columns', 'ROI_bg_rows',
            'ROI_bg_columns', 'NIScopes', 'beam_position_analysis',
            'origin'
        ]

        try:
            self.allow_evaluation = False
            self.loadDefaultSettings()
            # update variables
            self.allow_evaluation = True
            self.evaluateAll()
        except PauseError:
            logger.warning('Loading default settings aborted in AQuA.__init__().  PauseError')
        except:
            logger.exception('Loading default settings aborted in AQuA.__init__()')

        # make sure evaluation is allowed now
        self.allow_evaluation = True

    def exiting(self):
        self.PICams.__del__()
        self.Andors.__del__()
        return
