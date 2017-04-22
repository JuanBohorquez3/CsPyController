from __future__ import division
__author__ = 'Martin Lichtman'
import logging
logger = logging.getLogger(__name__)
from cs_errors import PauseError

import traceback
from atom.api import Member

# Bring in other files in this package
import functional_waveforms, analysis, instek_pst, save2013style, TTL, LabView, DDS, roi_fitting, picomotors, andor, picampython, vaunix, DCNoiseEater, Laird_temperature, AnalogInput, Counter, conex, aerotech, unlock_pause
import origin
from experiments import Experiment


class AQuA(Experiment):
    """A subclass of Experiment which knows about all our particular hardware"""

    picomotors = Member()
    instekpsts = Member()
    aerotechs = Member()
    conexes = Member()
    Andors = Member()
    vaunixs = Member()
    PICams = Member()
    LabView = Member()
    DDS = Member()
    DC_noise_eaters = Member()
    box_temperature = Member()
    unlock_pause = Member()

    functional_waveforms = Member()
    functional_waveforms_graph = Member()
    TTL_filters = Member()
    AI_graph = Member()
    AI_filter = Member()
    squareROIAnalysis = Member()
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
    measurements_graph = Member()
    iterations_graph = Member()
    retention_graph = Member()
    #andor_viewer = Member()
    picam_viewer = Member()
    DC_noise_eater_graph = Member()
    DC_noise_eater_filter = Member()
    Ramsey = Member()
    retention_analysis = Member()
    counter_graph = Member()
    counter_hist = Member()
    save_notes = Member()
    save2013Analysis = Member()
    origin = Member()
    ROI_rows = 7
    ROI_columns = 7

    def __init__(self):
        super(AQuA, self).__init__()

        # instruments
        self.functional_waveforms = functional_waveforms.FunctionalWaveforms('functional_waveforms', self, 'Waveforms for HSDIO, DAQmx DIO, and DAQmx AO; defined as functions')
        self.aerotechs = aerotech.Aerotechs('aerotechs', self, 'Aerotech Ensemble')
        self.conexes = conex.Conexes('conexes', self, 'CONEX-CC')
        self.picomotors = picomotors.Picomotors('picomotors', self, 'Newport Picomotors')
        self.instekpsts = instek_pst.InstekPSTs('instekpsts', self, 'Instek PST power supply')
        self.Andors = andor.Andors('Andors', self, 'Andor Luca Cameras')
        self.vaunixs = vaunix.Vaunixs('vaunixs', self, 'Vaunix Signal Generator')
        self.PICams = picampython.PICams('PICams', self, 'Princeton Instruments Cameras')
        self.LabView = LabView.LabView(self)
        self.DDS = DDS.DDS('DDS', self, 'server for homemade DDS boxes')
        self.DC_noise_eaters = DCNoiseEater.DCNoiseEaters('DC_noise_eaters', self)
        self.box_temperature = Laird_temperature.LairdTemperature('box_temperature', self)
        self.unlock_pause = unlock_pause.UnlockMonitor('unlock_pause', self, 'Monitor for pausing when laser unlocks')
        # do not include functional_waveforms in self.instruments because it need not start/stop
        self.origin = origin.Origin('origin', self, 'saves selected data to the origin data server')
        self.instruments += [self.box_temperature, self.picomotors, self.Andors, self.PICams, self.DC_noise_eaters,
                             self.LabView, self.DDS, self.unlock_pause, self.origin]


        # analyses
        self.functional_waveforms_graph = functional_waveforms.FunctionalWaveformGraph('functional_waveform_graph', self, 'Graph the HSDIO, DAQmx DO, and DAQmx AO settings')
        self.TTL_filters = TTL.TTL_filters('TTL_filters', self)
        self.AI_graph = AnalogInput.AI_Graph('AI_graph', self, 'Analog Input Graph')
        self.AI_filter = AnalogInput.AI_Filter('AI_filter', self, 'Analog Input filter')
        self.loading_filters = analysis.LoadingFilters('loading_filters', self, 'drop measurements with no atom loaded')
        self.first_measurements_filter = analysis.DropFirstMeasurementsFilter('first_measurements_filter', self, 'drop the first N measurements')
        self.squareROIAnalysis = analysis.SquareROIAnalysis(self, ROI_rows=self.ROI_rows, ROI_columns=self.ROI_columns)
        self.gaussian_roi = roi_fitting.GaussianROI('gaussian_roi', self, rows=self.ROI_rows, columns=self.ROI_columns)
        self.text_analysis = analysis.TextAnalysis('text_analysis', self, 'text results from the measurement')
        self.imageSumAnalysis = analysis.ImageSumAnalysis(self)
        self.recent_shot_analysis = analysis.RecentShotAnalysis('recent_shot_analysis', self, description='just show the most recent shot')
        self.shotBrowserAnalysis = analysis.ShotsBrowserAnalysis(self)
        self.histogramAnalysis = analysis.HistogramAnalysis('histogramAnalysis', self, 'plot the histogram of any shot and roi')
        self.histogram_grid = analysis.HistogramGrid('histogram_grid', self, 'all 49 histograms for shot 0 at the same time')
        self.measurements_graph = analysis.MeasurementsGraph('measurements_graph', self, 'plot the ROI sum vs all measurements')
        self.iterations_graph = analysis.IterationsGraph('iterations_graph', self, 'plot the average of ROI sums vs iterations')
        self.retention_graph = analysis.RetentionGraph('retention_graph', self, 'plot occurence of binary result (i.e. whether or not atoms are there in the 2nd shot)')
        #self.andor_viewer = andor.AndorViewer('andor_viewer', self, 'show the most recent Andor image')
        #self.picam_viewer = picam.PICamViewer('picam_viewer', self, 'show the most recent PICam image')
        self.DC_noise_eater_graph = DCNoiseEater.DCNoiseEaterGraph('DC_noise_eater_graph', self, 'DC Noise Eater graph')
        self.DC_noise_eater_filter = DCNoiseEater.DCNoiseEaterFilter('DC_noise_eater_filter', self, 'DC Noise Eater Filter')
        self.Ramsey = analysis.Ramsey('Ramsey', self, 'Fit a cosine to retention results')
        self.retention_analysis = analysis.RetentionAnalysis('retention_analysis', self, 'calculate the loading and retention')
        self.counter_graph = Counter.CounterAnalysis('counter_graph', self, 'Graphs the counter data after each measurement.')
        self.counter_hist = Counter.CounterHistogramAnalysis('counter_hist', self, 'Fits histograms of counter data and plots hist and fits.')
        self.save_notes = save2013style.SaveNotes('save_notes', self, 'save a separate notes.txt')
        self.save2013Analysis = save2013style.Save2013Analysis(self)
        # do not include functional_waveforms_graph in self.analyses because it need not update on iterations, etc.
        self.analyses += [self.TTL_filters, self.AI_graph, self.AI_filter, self.squareROIAnalysis, self.gaussian_roi,
                          self.loading_filters, self.first_measurements_filter, self.text_analysis,
                          self.imageSumAnalysis, self.recent_shot_analysis, self.shotBrowserAnalysis,
                          self.histogramAnalysis, self.histogram_grid, self.measurements_graph, self.iterations_graph, self.DC_noise_eater_graph, self.DC_noise_eater_filter, self.Andors, self.PICams,
                          self.Ramsey, self.retention_analysis, self.retention_graph, self.counter_graph,
                          self.save_notes, self.save2013Analysis, self.aerotechs, self.conexes,self.counter_hist,
                          self.instekpsts, self.vaunixs, self.unlock_pause, self.origin]

        
        self.properties += ['functional_waveforms', 'LabView', 'functional_waveforms_graph', 'DDS', 'aerotechs', 'picomotors', 'conexes',
                            'Andors', 'PICams', 'DC_noise_eaters', 'box_temperature', 'squareROIAnalysis', 'gaussian_roi', 'instekpsts', 
                            'TTL_filters', 'AI_graph', 'AI_filter', 'loading_filters', 'first_measurements_filter', 'vaunixs', 
                            'imageSumAnalysis', 'recent_shot_analysis', 'shotBrowserAnalysis', 'histogramAnalysis',
                            'histogram_grid', 'retention_analysis', 'measurements_graph', 'iterations_graph',
                            'retention_graph', 'DC_noise_eater_filter',
                            'DC_noise_eater_graph', 'Ramsey', 'counter_graph', 'counter_hist', 'unlock_pause','origin']


        try:
            self.allow_evaluation = False
            self.loadDefaultSettings()

            #update variables
            self.allow_evaluation = True
            self.evaluateAll()
        except PauseError:
            logger.warning('Loading default settings aborted in AQuA.__init__().  PauseError')
        except Exception as e:
            logger.warning('Loading default settings aborted in AQuA.__init__().\n{}\n{}\n'.format(e, traceback.format_exc()))

        #make sure evaluation is allowed now
        self.allow_evaluation = True

    def exiting(self):
        self.PICams.__del__()
        self.Andors.__del__()
        return
