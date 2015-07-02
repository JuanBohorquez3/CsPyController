from __future__ import division
__author__ = 'Martin Lichtman'
import logging
logger = logging.getLogger(__name__)

from cs_errors import PauseError

import threading, numpy, traceback, os, datetime

#MPL plotting
import matplotlib as mpl
mpl.use('PDF')
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.path import Path
import matplotlib.patches as patches
from matplotlib.gridspec import GridSpec
from mpl_toolkits.axes_grid1 import make_axes_locatable
#from matplotlib.backends.backend_pdf import PdfPages
from enaml.application import deferred_call

from atom.api import Bool, Typed, Str, Member, List, Int, observe, Float
np = numpy
from scipy.optimize import curve_fit
from scipy.special import erf

from colors import my_cmap, green_cmap

from instrument_property import Prop
import cs_evaluate


def mpl_rectangle(ax, ROI):
    """Draws a rectangle, for use in drawing ROIs on images"""
    #left, top, right, bottom, threshold = (0, 1, 2, 3, 4)  # column ordering of ROI boundaries in each ROI in ROIs
    left = ROI[0] - 0.5
    top = ROI[1] - 0.5
    right = ROI[2] - 0.5
    bottom = ROI[3] - 0.5
    verts = [
        (left, bottom),  # left, bottom
        (left, top),  # left, top
        (right, top),  # right, top
        (right, bottom),  # right, bottom
        (0., 0.),  # ignored
        ]

    codes = [Path.MOVETO,
             Path.LINETO,
             Path.LINETO,
             Path.LINETO,
             Path.CLOSEPOLY,
             ]

    path = Path(verts, codes)

    patch = patches.PathPatch(path, edgecolor='orange', facecolor='none', lw=1)
    ax.add_patch(patch)


class Analysis(Prop):
    """This is the parent class for all data analyses.  New analyses should subclass off this,
    and redefine at least one of preExperiment(), preIteration(), postMeasurement(), postIteration() or
    postExperiment().  You can enable multi-threading of analyses using queueAfterMeasurement and queueAfterIteration,
    but only if those results are not needed for other things (filtering, other analyses, optimization).  If
    multi-threading, you can also chose to dropMeasurementIfSlow or dropIterationIfSlow, which will not delete the data
    but will just not process it.  An analysis can return a success code after analyzeMesurement, which can be used to
    filter results.  The highest returned code dominates others:
        0 or None: good measurement, increment measurement total
        1: soft fail, continue with other analyses, but do not increment measurement total
        2: med fail, continue with other analyses, do not increment measurement total, and delete measurement data after all analyses
        3: hard fail, do not continue with other analyses, do not increment measurement total, delete measurement data
    """
    
    queueAfterMeasurement = Bool()  # Set to True to allow multi-threading on this analysis.  Only do this if you are NOT filtering on this analysis, and if you do NOT depend on the results of this analysis later. Default is False.
    dropMeasurementIfSlow = Bool()  # Set to True to skip measurements when slow.  Applies only to multi-threading.  Raw data can still be used post-iteration and post-experiment. Default is False.
    queueAfterIteration = Bool()  # Set to True to allow multi-threading on this analysis.  Only do this if you do NOT depend on the results of this analysis later. Default is False.
    dropIterationIfSlow = Bool()  # Set to True to skip iterations when slow.  Applies only to multi-threading.  Raw data can still be used in post-experiment.  Default is False.
    
    #internal variables, user should not modify
    measurementProcessing = Bool()
    iterationProcessing = Bool()
    measurementQueue = []
    iterationQueue = []

    def __init__(self, name, experiment, description=''):  # subclassing from Prop provides save/load mechanisms
        super(Analysis, self).__init__(name, experiment, description)
        self.properties += ['dropMeasurementIfSlow', 'dropIterationIfSlow']
    
    def preExperiment(self, experimentResults):
        """This is called before an experiment.
        The parameter experimentResults is a reference to the HDF5 file for this experiment.
        Subclass this to prepare the analysis appropriately."""
        pass

    def preIteration(self, iterationResults, experimentResults):
        """This is called before an iteration.
        The parameter experimentResults is a reference to the HDF5 file for this experiment.
        The parameter iterationResults is a reference to the HDF5 node for this coming iteration.
        Subclass this to prepare the analysis appropriately."""
        pass

    def postMeasurement(self, measurementResults, iterationResults, experimentResults):
        """Results is a tuple of (measurementResult,iterationResult,experimentResult) references to HDF5 nodes for this
        measurement."""
        if self.queueAfterMeasurement:  # if self.updateAfterMeasurement:
            if not self.measurementProcessing:  # check to see if a processing queue is already going
                self.measurementProcessing  =True
                self.measurementQueue.append((measurementResults, iterationResults, experimentResults))
                threading.Thread(target=self.measurementProcessLoop).start()
            elif not self.dropMeasurementIfSlow:  # if a queue is already going, add to it, unless we can't tolerate being behind
                self.measurementQueue.append((measurementResults, iterationResults, experimentResults))
        else:
            return self.analyzeMeasurement(measurementResults, iterationResults, experimentResults)
    
    def measurementProcessLoop(self):
        while len(self.measurementQueue) > 0:
            self.analyzeMeasurement(*self.measurementQueue.pop(0))  # process the oldest element
        self.measurementProcessing = False
    
    def analyzeMeasurement(self, measurementResults, iterationResults, experimentResults):
        """This is called after each measurement.
        The parameters (measurementResults, iterationResults, experimentResults)
        reference the HDF5 nodes for this measurement.
        Subclass this to update the analysis appropriately."""
        pass
    
    def postIteration(self, iterationResults, experimentResults):
        if self.queueAfterIteration:
            if not self.iterationProcessing:  # check to see if a processing queue is already going
                self.iterationProcessing = True
                self.iterationQueue.append((iterationResults, experimentResults))
                threading.Thread(target=self.iterationProcessLoop).start()
            elif not self.dropIterationIfSlow:
                # if a queue is already going, add to it, unless we can't tolerate being behind
                self.iterationQueue.append((iterationResults, experimentResults))
        else:
            self.analyzeIteration(iterationResults, experimentResults)
    
    def iterationProcessLoop(self):
        while len(self.iterationQueue) > 0:
            self.analyzeIteration(*self.iterationQueue.pop(0))  # process the oldest element
        self.iterationProcessing = False
    
    def analyzeIteration(self, iterationResults, experimentResults):
        """This is called after each iteration.
        The parameters (iterationResults, experimentResults) reference the HDF5 nodes for this iteration.
        Subclass this to update the analysis appropriately."""
        pass
    
    def postExperiment(self, experimentResults):
        #no queueing, must do post experiment processing at this time
        self.analyzeExperiment(experimentResults)
    
    def analyzeExperiment(self, experimentResults):
        """This is called at the end of the experiment.
        The parameter experimentResults is a reference to the HDF5 file for the experiment.
        Subclass this to update the analysis appropriately."""
        pass

    def finalize(self, hdf5):
        """To be run after all optimization loops are complete, so as to close files and such."""
        pass


class AnalysisWithFigure(Analysis):
    
    #matplotlib figures
    figure = Typed(Figure)
    backFigure = Typed(Figure)
    figure1 = Typed(Figure)
    figure2 = Typed(Figure)
    
    def __init__(self, name, experiment, description=''):
        super(AnalysisWithFigure, self).__init__(name, experiment, description)
        
        #set up the matplotlib figures
        self.figure1 = Figure()
        self.figure2 = Figure()
        self.backFigure = self.figure2
        self.figure = self.figure1
    
    def swapFigures(self):
        temp = self.backFigure
        self.backFigure = self.figure
        self.figure = temp
    
    def updateFigure(self):
        #signal the GUI to redraw figure
        try:
            deferred_call(self.swapFigures)
        except RuntimeError: #application not started yet
            self.swapFigures()

    def blankFigure(self):
        fig = self.backFigure
        fig.clf()
        self.updateFigure()


class TextAnalysis(Analysis):
    #Text output that can be updated back to the GUI
    text = Str()

    def __init__(self, name, experiment, description=''):
        super(TextAnalysis, self).__init__(name, experiment, description)
        self.properties += ['text']

    def analyzeMeasurement(self, measurementResults, iterationResults, experimentResults):
        try:
            text = 'iteration {} measurement {}'.format(iterationResults.attrs['iteration'],
                                                              measurementResults.name.split('/')[-1])
            if 'data/Hamamatsu/temperature' in measurementResults:
                text += '\nCamera temperature: {} C'.format(measurementResults['data/Hamamatsu/temperature'].value)
        except KeyError as e:
            logger.warning('HDF5 text does not exist in TextAnalysis\n{}\n'.format(e))
            return
        self.set_gui({'text': text})


class TTL_filters(Analysis):
    """This analysis monitors the TTL inputs and does either hard or soft cuts of the data accordingly.
    Low is good, high is bad."""

    text = Str()
    lines = Str('PXI1Slot6/port0')
    filter_level = Int()

    def __init__(self, name, experiment, description=''):
        super(TTL_filters, self).__init__(name, experiment, description)
        self.properties += ['lines', 'filter_level']

    def analyzeMeasurement(self, measurementResults, iterationResults, experimentResults):
        text = 'none'
        if self.experiment.LabView.TTL.enable and ('TTL/data' in measurementResults['data']):
            a = measurementResults['data/TTL/data']
            #check to see if any of the inputs were True
            if numpy.any(a):
                #report the true inputs
                text = 'TTL Filters failed:\n'
                for i, b in enumerate(a):
                    #print out the row and column of the True input
                    text += 'Check {}: Laser(s) {}\n'.format(i, numpy.arange(len(b))[b])
                #record to the log and screen
                logger.warning(text)
                self.set_gui({'text': text})
                # User chooses whether or not to delete data.
                # max takes care of ComboBox returning -1 for no selection
                return max(0, self.filter_level)
            else:
                text = 'okay'
        self.set_gui({'text': text})


class RecentShotAnalysis(AnalysisWithFigure):
    """Plots the currently incoming shot"""
    data = Member()
    showROIs = Bool(False)
    shot = Int(0)
    update_lock = Bool(False)
    subtract_background = Bool()

    def __init__(self, name, experiment, description=''):
        super(RecentShotAnalysis, self).__init__(name, experiment, description)
        self.properties += ['showROIs', 'shot', 'subtract_background']

    def analyzeMeasurement(self, measurementResults, iterationResults, experimentResults):
        self.data = []
        if 'data/Hamamatsu/shots' in measurementResults:
            #for each image
            for shot in measurementResults['data/Hamamatsu/shots'].values():
                self.data.append(shot)
        self.updateFigure()  # only update figure if image was loaded

    @observe('shot', 'showROIs', 'subtract_background')
    def reload(self, change):
        self.updateFigure()

    def updateFigure(self):
        if not self.update_lock:
            try:
                self.update_lock = True
                fig = self.backFigure
                fig.clf()

                if (self.data is not None) and (self.shot < len(self.data)):
                    ax = fig.add_subplot(111)

                    if self.subtract_background:
                        data = self.data[self.shot] - self.experiment.imageSumAnalysis.background_array
                        vmin = self.experiment.imageSumAnalysis.min_minus_bg
                        vmax = self.experiment.imageSumAnalysis.max_minus_bg
                    else:
                        data = self.data[self.shot]
                        vmin = self.experiment.imageSumAnalysis.min
                        vmax = self.experiment.imageSumAnalysis.max

                    ax.matshow(data, cmap=my_cmap, vmin=self.experiment.imageSumAnalysis.min, vmax=self.experiment.imageSumAnalysis.max)
                    ax.set_title('most recent shot '+str(self.shot))
                    if self.showROIs:
                        #overlay ROIs
                        for ROI in self.experiment.squareROIAnalysis.ROIs:
                            mpl_rectangle(ax, ROI)

                super(RecentShotAnalysis, self).updateFigure()
            except Exception as e:
                logger.warning('Problem in RecentShotAnalysis.updateFigure()\n:{}'.format(e))
            finally:
                self.update_lock = False


class XYPlotAnalysis(AnalysisWithFigure):
    #### needs updating
    X=Member()
    Y=Member()
    
    def updateFigure(self):
        fig=self.backFigure
        fig.clf()
        ax=fig.add_subplot(111)
        if (self.X is not None) and (self.Y is not None):
            ax.plot(self.X, self.Y)
        super(XYPlotAnalysis, self).updateFigure()


class SampleXYAnalysis(XYPlotAnalysis):
    #### needs updating
    
    '''This analysis plots the sum of the whole camera image every measurement.'''
    def analyzeMeasurement(self,measurementResults,iterationResults,experimentResults):
        if 'data/Hamamatsu/shots' in measurementResults:
            self.Y = numpy.append(self.Y,numpy.sum(measurementResults['data/Hamamatsu/shots/0']))
            self.X = numpy.arange(len(self.Y))
        self.updateFigure()


class ShotsBrowserAnalysis(AnalysisWithFigure):
    
    ivarNames=List(default=[])
    ivarValueLists=List(default=[])
    selection=List(default=[])
    measurement=Int(0)
    shot=Int(0)
    array=Member()
    experimentResults=Member()
    showROIs = Bool(False)
    
    def __init__(self, experiment):
        super(ShotsBrowserAnalysis, self).__init__('ShotsBrowser', experiment, 'Shows a particular shot from the experiment')
        self.properties += ['measurement', 'shot', 'showROIs']
    
    def preExperiment(self, experimentResults):
        self.experimentResults = experimentResults
        self.ivarValueLists = [i for i in self.experiment.ivarValueLists]  # this line used to access the hdf5 file, but I have temporarily removed ivarValueLists from the HDF5 because it could not handle arbitrary lists of lists
        self.selection = [0]*len(self.ivarValueLists)
        deferred_call(setattr, self, 'ivarNames', [i for i in experimentResults.attrs['ivarNames']])
    
    def setIteration(self,ivarIndex,index):
        try:
            self.selection[ivarIndex] = index
        except Exception as e:
            logger.warning('Invalid ivarIndex in analysis.ShotsBrowserAnalysis.setSelection({},{})\n{}\n[]'.format(ivarIndex,index,e,traceback.format_exc()))
            raise PauseError
        self.load()
    
    @observe('measurement','shot','showROIs')
    def reload(self,change):
        self.load()
    
    def load(self):
        if self.experimentResults is not None:
            #find the first matching iteration
            m=str(self.measurement)
            s=str(self.shot)
            if 'iterations' in self.experimentResults:
                for i in self.experimentResults['iterations'].itervalues():
                    #find the first iteration that matches all the selected ivar indices
                    if numpy.all(i.attrs['ivarIndex'] == self.selection):
                        try:
                            self.array = i['measurements/{}/data/Hamamatsu/shots/{}'.format(m,s)]
                            self.updateFigure()
                        except Exception as e:
                            logger.warning('Exception trying to plot measurement {}, shot {}, in analysis.ShotsBrowserAnalysis.load()\n{}\n'.format(m,s,e))
                            self.blankFigure()
                        break
    
    def blankFigure(self):
        fig=self.backFigure
        fig.clf()
        super(ShotsBrowserAnalysis,self).updateFigure()
    
    def updateFigure(self):
        fig=self.backFigure
        fig.clf()
        ax=fig.add_subplot(111)
        ax.matshow(self.array, cmap=my_cmap, vmin=self.experiment.imageSumAnalysis.min, vmax=self.experiment.imageSumAnalysis.max)
        ax.set_title('browser')
        if self.showROIs:
            #overlay ROIs
            for ROI in self.experiment.squareROIAnalysis.ROIs:
                mpl_rectangle(ax, ROI)

        super(ShotsBrowserAnalysis,self).updateFigure() #makes a deferred_call to swap_figures()


class ImageSumAnalysis(AnalysisWithFigure):
    data = Member()
    enable = Bool()
    sum_array = Member()  # holds the sum of each shot
    count_array = Member()  # holds the number of measurements summed
    mean_array = Member()  # holds the mean image for each shot
    background_array = Member()
    showROIs = Bool(False)  # should we superimpose ROIs?
    shot = Int()  # which shot to display
    update_lock = Bool(False)
    min_str = Str()
    max_str = Str()
    min = Member()
    max = Member()
    min_minus_bg = Member()
    max_minus_bg = Member()
    #pdf = Member()
    pdf_path = Member()
    subtract_background = Bool()
    iteration = Int()

    def __init__(self, experiment):
        super(ImageSumAnalysis, self).__init__('ImageSumAnalysis', experiment, 'Sums shot0 images as they come in')
        self.properties += ['enable', 'showROIs', 'shot', 'background_array', 'subtract_background', 'min_str',
                            'max_str', 'min', 'max', 'min_minus_bg', 'max_minus_bg']
        self.min = 0
        self.max = 1

    def set_background(self):
        self.background_array = self.mean_array[self.shot]

    def preExperiment(self, experimentResults):
        if self.enable and self.experiment.saveData:
            #self.pdf = PdfPages(os.path.join(self.experiment.path, 'image_mean_{}.pdf'.format(self.experiment.experimentPath)))

            # create the nearly complete path name to save pdfs to.  The iteration and .pdf will be appended.
            pdf_path = os.path.join(self.experiment.path, 'pdf')
            if not os.path.exists(pdf_path):
                os.mkdir(pdf_path)
            self.pdf_path = os.path.join(pdf_path, '{}_image_mean'.format(self.experiment.experimentPath))

    def preIteration(self, iterationResults, experimentResults):
        #clear old data
        self.mean_array = None

    def analyzeMeasurement(self, measurementResults, iterationResults, experimentResults):

        self.iteration = iterationResults.attrs['iteration']

        if 'data/Hamamatsu/shots' in measurementResults:
            if self.mean_array is None:
                #start a sum array of the right shape
                self.sum_array = numpy.array([shot for shot in measurementResults['data/Hamamatsu/shots'].itervalues()], dtype=numpy.uint64)
                self.count_array = numpy.zeros(len(self.sum_array), dtype=numpy.uint64)
                self.mean_array = self.sum_array.astype(numpy.float64)

            else:
                #add new data
                for i, shot in enumerate(measurementResults['data/Hamamatsu/shots'].itervalues()):
                    self.sum_array[i] += shot
                    self.count_array[i] += 1
                    self.mean_array[i] = self.sum_array[i]/self.count_array[i]

            self.update_min_max()
            self.updateFigure()  # only update figure if image was loaded

    def update_min_max(self):
        if (self.mean_array is not None) and (self.shot < len(self.mean_array)):
            #update the min/max that this and other image plots will use
            if self.min_str == '':
                self.min = numpy.amin(self.mean_array[self.shot])
                try:
                    self.min_minus_bg = numpy.amin(self.mean_array[self.shot]-self.background_array)
                except:
                    logger.warning('Could not subtract background array to create min in ImageSumAnalysis.analyzeMeasurement')
            else:
                try:
                    self.min = float(self.min_str)
                    self.min_minus_bg = self.min
                except:
                    logger.warning('Could not cast string to float in to create min in ImageSumAnalysis.analyzeMeasurement')
            if self.max_str == '':
                self.max = numpy.amax(self.mean_array[self.shot])
                try:
                    self.max_minus_bg = numpy.amax(self.mean_array[self.shot]-self.background_array)
                except:
                    logger.warning('Could not subtract background array to create max in ImageSumAnalysis.analyzeMeasurement')
            else:
                try:
                    self.max = float(self.max_str)
                    self.max_minus_bg = self.max
                except:
                    logger.warning('Could not cast string to float in to create max in ImageSumAnalysis.analyzeMeasurement')

    def analyzeIteration(self, iterationResults, experimentResults):
        if self.enable:
            iterationResults['sum_array'] = self.sum_array
            iterationResults['mean_array'] = self.mean_array

            # create image of all shots for pdf
            self.savefig(iterationResults.attrs['iteration'])

    @observe('shot', 'showROIs', 'subtract_background')
    def reload(self, change):
        self.updateFigure()

    @observe('min_str', 'max_str')
    def change_scaling(self, change):
        self.update_min_max()
        self.updateFigure()

    def savefig(self, iteration):
        try:
            # save to PDF
            if self.experiment.saveData:
                for shot in xrange(self.mean_array.shape[0]):

                    fig = plt.figure(figsize=(8, 6))
                    dpi = 80
                    fig.set_dpi(dpi)
                    self.draw_fig(fig, iteration, shot)
                    plt.savefig('{}_{}_{}.pdf'.format(self.pdf_path, iteration, shot),
                                format='pdf', dpi=dpi, transparent=True, bbox_inches='tight',
                                pad_inches=.25, frameon=False)
                    plt.close(fig)
        except Exception as e:
            logger.warning('Problem in HistogramGrid.savefig():\n{}\n{}\n'.format(e, traceback.format_exc()))


    def draw_fig(self, fig, iteration, shot):
        if (self.mean_array is not None) and (shot < len(self.mean_array)):
            #gs = GridSpec(1, 2, width_ratios=[20, 1])
            #ax = fig.add_subplot(gs[0, 0])
            ax = fig.add_subplot(111)

            if self.subtract_background:
                data = self.mean_array[shot] - self.background_array
                min = self.min_minus_bg
                max = self.max_minus_bg
            else:
                data = self.mean_array[shot]
                min = self.min
                max = self.max

            im = ax.matshow(data, cmap=my_cmap, vmin=min, vmax=max)

            #label plot
            fig.suptitle('{} iteration {} shot {} mean'.format(self.experiment.experimentPath, iteration, shot))

            # make a colorbar
            # create an axes on the right side of ax. The width of cax will be 5%
            # of ax and the padding between cax and ax will be fixed at 0.05 inch.
            divider = make_axes_locatable(ax)
            cax = divider.append_axes("right", size="5%", pad=0.05)
            fig.colorbar(im, cax=cax)

            if self.showROIs:
                #overlay ROIs
                for ROI in self.experiment.squareROIAnalysis.ROIs:
                    mpl_rectangle(ax, ROI)

    def updateFigure(self):
        if not self.update_lock:
            try:
                self.update_lock = True

                fig = self.backFigure
                fig.clf()

                self.draw_fig(fig, self.iteration, self.shot)

                super(ImageSumAnalysis, self).updateFigure()
            except Exception as e:
                logger.warning('Problem in ImageSumAnalysis.updateFigure()\n:{}'.format(e))
            finally:
                self.update_lock = False

    #def finalize(self, experimentResults):
    #    if self.enable and self.experiment.saveData:
    #        self.pdf.close()

class SquareROIAnalysis(AnalysisWithFigure):
    """Add up the sums of pixels in a region, and evaluate whether or not an atom is present based on the totals."""

    version = '2014.05.01'
    ROI_rows = Int()
    ROI_columns = Int()
    ROIs = Member()  # a numpy array holding an ROI in each row
    filter_level = Int()
    #left, top, right, bottom, threshold = (0, 1, 2, 3, 4)  # column ordering of ROI boundaries in each ROI in ROIs
    loadingArray = Member()
    enable = Bool()
    cutoffs_from_which_experiment = Str()

    def __init__(self, experiment, ROI_rows=1, ROI_columns=1):
        super(SquareROIAnalysis, self).__init__('SquareROIAnalysis', experiment, 'Does analysis on square regions of interest')
        self.loadingArray = numpy.zeros((0, ROI_rows, ROI_columns), dtype=numpy.bool_)  # blank array that will hold digital representation of atom loading
        self.ROI_rows = ROI_rows
        self.ROI_columns = ROI_columns
        dtype = [('left', numpy.uint16), ('top', numpy.uint16), ('right', numpy.uint16), ('bottom', numpy.uint16), ('threshold', numpy.uint32)]
        self.ROIs = numpy.zeros(ROI_rows*ROI_columns, dtype=dtype)  # initialize with a blank array
        self.properties += ['version', 'ROIs', 'filter_level', 'enable', 'cutoffs_from_which_experiment']

    def sum(self, roi, shot):
        return numpy.sum(shot[roi['top']:roi['bottom'], roi['left']:roi['right']])

    def sums(self, rois, shot):
        return numpy.array([self.sum(roi, shot) for roi in rois], dtype=numpy.uint32)

    def analyzeMeasurement(self, measurementResults, iterationResults, experimentResults):
        if self.enable:
            if ('data/Hamamatsu/shots' in measurementResults):
                #here we want to live update a digital plot of atom loading as it happens

                numShots = len(measurementResults['data/Hamamatsu/shots'])
                # check to see that we got enough shots
                if self.experiment.LabView.camera.enable and (numShots != self.experiment.LabView.camera.shotsPerMeasurement.value):
                    logger.warning('Camera expected {} shots, but instead got {}.'.format(
                        self.experiment.LabView.camera.shotsPerMeasurement.value, numShots))
                    return 3  # hard fail, delete measurement

                numROIs=len(self.ROIs)

                sum_array = numpy.zeros((numShots, numROIs), dtype=numpy.uint32)  # uint32 allows for summing ~65535 regions
                thresholdArray = numpy.zeros((numShots, numROIs), dtype=numpy.bool_)
                #loadingArray = numpy.zeros((numShots, self.ROI_rows, self.ROI_columns), dtype=numpy.bool_)

                #for each image
                for i, (name, shot) in enumerate(measurementResults['data/Hamamatsu/shots'].items()):
                    #calculate sum of pixels in each ROI
                    shot_sums = self.sums(self.ROIs, shot)
                    sum_array[i] = shot_sums

                    #compare each roi to threshold
                    thresholdArray[i] = (shot_sums >= self.ROIs['threshold'])

                self.loadingArray = thresholdArray.reshape((numShots, self.ROI_rows, self.ROI_columns))
                #data will be stored in hdf5 so that save2013style can then append to Camera Data Iteration0 (signal).txt
                measurementResults['analysis/squareROIsums'] = sum_array
                measurementResults['analysis/squareROIthresholded'] = thresholdArray
                self.updateFigure()
                
            # check to see if there were supposed to be images
            elif self.experiment.LabView.camera.enable and (self.experiment.LabView.camera.shotsPerMeasurement.value > 0):
                logger.warning('Camera expected {} shots, but did not get any.'.format(self.experiment.LabView.camera.shotsPerMeasurement.value))
                return 3  # hard fail, delete measurement

    def analyzeIteration(self, iterationResults, experimentResults):
        """
        create a big array of the results from each measurement for convenience
        data is stored in iterationResults['analysis/square_roi/sums']
        as an array of size (measurements x shots x roi) array
        """
        if self.enable:
            measurements = map(int, iterationResults['measurements'].keys())
            measurements.sort()
            iterationResults['analysis/square_roi/sums'] = numpy.array([iterationResults['measurements/{}/analysis/squareROIsums'.format(m)] for m in measurements])

    def updateFigure(self):
        fig = self.backFigure
        fig.clf()
        if self.loadingArray.size > 0:
            n = len(self.loadingArray)
            for i in range(n):
                ax = fig.add_subplot(n, 1, i+1)
                #make the digital plot here
                ax.matshow(self.loadingArray[i], cmap=green_cmap)
                ax.set_title('shot '+str(i))
        super(SquareROIAnalysis, self).updateFigure()


class LoadingFilters(Analysis):
    """This analysis monitors the brightess in the regions of interest, to decide if an atom was loaded or not"""
    version = '2014.05.01'

    enable = Bool()
    text = Str()
    filter_expression = Str()
    filter_level = Int()
    valid = Bool(True)

    def __init__(self, name, experiment, description=''):
        super(LoadingFilters, self).__init__(name, experiment, description)
        self.properties += ['version', 'enable', 'filter_expression', 'filter_level']

    def analyzeMeasurement(self, measurementResults, iterationResults, experimentResults):
        text = 'none'
        if self.enable:
            text = 'okay'
            if self.filter_expression != '':
                if ('analysis/squareROIsums' in measurementResults):

                    #evaluate the boolean expression, with the squareROIsums as 't' in the namespace
                    #This will overwrite any previous value, so we make a copy of the dictionary
                    vars = self.experiment.vars.copy()
                    vars['t'] = measurementResults['analysis/squareROIsums']
                    value, valid = cs_evaluate.evalWithDict(self.filter_expression, varDict=vars)
                    if not valid:
                        #raise an error
                        text = 'Failed to evaluate loading filter: {}:\n'.format(self.filter_expression)
                        logger.error(text)
                        self.set_gui({'text': text,
                                      'valid': False})
                        raise PauseError
                    elif not ((value == True) or (value == False)):
                        #Enforce that the expression must evaluate to a bool
                        text = 'Loading filter must be True or False, but it evaluated to: {}\nfor expression: {}:\n'.format(value, self.filter_expression)
                        logger.error(text)
                        self.set_gui({'text': text,
                                      'valid': False})
                        raise PauseError
                    else:
                        #eval worked, save value
                        measurementResults['analysis/loading_filter'] = value
                        if not value:
                            #Measurement did not pass filter (We do not need to take special action if the filter passes.)
                            text = 'Loading filter failed.'
                            self.set_gui({'text': text,
                                          'valid': True})
                            # User chooses whether or not to delete data.
                            # max takes care of ComboBox returning -1 for no selection
                            return max(0, self.filter_level)
        self.set_gui({'text': text,
                      'valid': True})


class DropFirstMeasurementsFilter(Analysis):
    """This analysis allows the user to drop the first N measurements in an 
    iteration, to ensure that all measurements are done at equivalent conditions
    ."""

    version = '2014.06.12'
    enable = Bool()
    filter_level = Int()
    N = Int()

    def __init__(self, name, experiment, description=''):
        super(DropFirstMeasurementsFilter, self).__init__(name, experiment, description)
        self.properties += ['version', 'enable', 'filter_level', 'N']

    def analyzeMeasurement(self, measurementResults, iterationResults, experimentResults):
        if self.enable:
            i = measurementResults.attrs['measurement']
            if i < self.N:
                # User chooses whether or not to delete data.
                # max takes care of ComboBox returning -1 for no selection
                logger.info('dropping measurement {} of {}'.format(i,self.N))
                return max(0, self.filter_level)

class HistogramAnalysis(AnalysisWithFigure):
    """This class live updates a histogram as data comes in."""
    enable = Bool()
    all_shots_array = Member()
    update_lock = Bool(False)
    list_of_what_to_plot = Str()

    def __init__(self, name, experiment, description=''):
        super(HistogramAnalysis, self).__init__(name, experiment, description)
        self.properties += ['enable', 'list_of_what_to_plot']

    def preIteration(self, iterationResults, experimentResults):
        #reset the histogram data
        self.all_shots_array = None

    def analyzeMeasurement(self, measurementResults, iterationResults, experimentResults):
        if self.enable:
            #every measurement, update a big array of all the ROI sums, then histogram only the requested shot/site
            d = measurementResults['analysis/squareROIsums']
            if self.all_shots_array is None:
                self.all_shots_array = numpy.array([d])
            else:
                self.all_shots_array = numpy.append(self.all_shots_array, numpy.array([d]), axis=0)
            self.updateFigure()

    @observe('list_of_what_to_plot')
    def reload(self, change):
        if self.enable:
            self.updateFigure()

    def updateFigure(self):
        if not self.update_lock:
            try:
                self.update_lock = True
                fig = self.backFigure
                fig.clf()

                if (self.all_shots_array is not None) and (len(self.all_shots_array) > 1):

                    #parse the list of what to plot from a string to a list of numbers
                    try:
                        plotlist = eval(self.list_of_what_to_plot)
                    except Exception as e:
                        logger.warning('Could not eval plotlist in HistogramAnalysis:\n{}\n'.format(e))
                        return

                    ax = fig.add_subplot(111)
                    shots = [i[0] for i in plotlist]
                    rois = [i[1] for i in plotlist]
                    data = self.all_shots_array[:, shots, rois]
                    bins = int(1.2*numpy.rint(numpy.sqrt(len(data))))
                    ax.hist(data, bins, histtype='step', label=['({},{})'.format(i[0], i[1]) for i in plotlist])
                    ax.legend()
                super(HistogramAnalysis, self).updateFigure()
            except Exception as e:
                logger.warning('Problem in HistogramAnalysis.updateFigure()\n:{}'.format(e))
            finally:
                self.update_lock = False


class HistogramGrid(AnalysisWithFigure):
    """This class gives a big histogram grid with 0 and 1 atom cutoffs after every iteration."""
    enable = Bool()
    all_shots_array = Member()
    histogram_results = Member()
    shot = Int()
    #pdf = Member()
    pdf_path = Member()
    bins = Member()
    x_min = Member()
    x_max = Member()
    y_max = Member()
    roi_type = Int(0)
    calculate_new_cutoffs = Bool()
    automatically_use_cutoffs = Bool()
    cutoff_shot_mapping = Str()
    cutoffs_from_which_experiment = Str()

    def __init__(self, name, experiment, description=''):
        super(HistogramGrid, self).__init__(name, experiment, description)
        self.properties += ['enable', 'shot', 'roi_type', 'calculate_new_cutoffs', 'automatically_use_cutoffs',
                            'cutoff_shot_mapping']

    def preExperiment(self, experimentResults):
        if self.enable and self.experiment.saveData:
            #self.pdf = PdfPages(os.path.join(self.experiment.path, 'histogram_grid_{}.pdf'.format(self.experiment.experimentPath)))

            # create the nearly complete path name to save pdfs to.  The iteration and .pdf will be appended.
            pdf_path = os.path.join(self.experiment.path, 'pdf')
            if not os.path.exists(pdf_path):
                os.mkdir(pdf_path)
            self.pdf_path = os.path.join(pdf_path, '{}_histogram_grid'.format(self.experiment.experimentPath))

    #def finalize(self, experimentResults):
    #    if self.enable and self.experiment.saveData:
    #        self.pdf.close()

    def analyzeIteration(self, iterationResults, experimentResults):
        if self.enable:
            if self.roi_type == 0:  # square rois
                # all_shots_array will be shape (measurements,shots,rois)
                all_shots_array = iterationResults['analysis/square_roi/sums'].value

            elif self.roi_type == 1:  # gaussian rois
                # all_shots_array will be shape (measurements,shots,rois)
                all_shots_array = iterationResults['analysis/gaussian_roi/sums'].value

            else:
                logger.error('invalid roi type {} in HistogramGrid.analyzeIteration'.format(self.roi_type))
                raise PauseError

            # perform histogram calculations and fits on all shots and regions
            self.calculate_all_histograms(all_shots_array)

            if self.automatically_use_cutoffs:
                self.use_cutoffs()

            # save data to hdf5
            iterationResults['analysis/histogram_results'] = self.histogram_results

            self.savefig(iterationResults.attrs['iteration'])

            # update the figure to show the histograms for the selected shot
            self.updateFigure()

            # save the figure in a deferred_call, so that it will be sure to have updated first
            #time.sleep(.01)
            #deferred_call(self.savefig)

    @observe('shot')
    def refresh(self, change):
        if self.enable:
            self.updateFigure()

    def savefig(self, iteration):
        try:
            # save to PDF
            if self.experiment.saveData:
                for shot in xrange(self.histogram_results.shape[0]):
                    fig = plt.figure(figsize=(23.6, 12.3))
                    dpi=80
                    fig.set_dpi(dpi)
                    fig.suptitle('{} iteration {} shot {}'.format(self.experiment.experimentPath, iteration, shot))
                    self.histogram_grid_plot(fig, shot,  photoelectronScaling=self.experiment.LabView.camera.photoelectronScaling.value, exposure_time=self.experiment.LabView.camera.exposureTime.value)
                    plt.savefig('{}_{}_{}.pdf'.format(self.pdf_path, iteration, shot),
                                format='pdf', dpi=dpi, transparent=True, bbox_inches='tight',
                                pad_inches=.25, frameon=False)
                    plt.close(fig)
        except Exception as e:
            logger.warning('Problem in HistogramGrid.savefig():\n{}\n{}\n'.format(e, traceback.format_exc()))

    def updateFigure(self):
        try:
            fig = self.backFigure
            fig.clf()

            if self.histogram_results is not None:
                fig.suptitle('shot {}'.format(self.shot))
                if self.experiment.gaussian_roi.multiply_sums_by_photoelectron_scaling:
                    photoelectronScaling = self.experiment.LabView.camera.photoelectronScaling.value
                else:
                    photoelectronScaling = None
                self.histogram_grid_plot(fig, self.shot, photoelectronScaling=photoelectronScaling, exposure_time=self.experiment.LabView.camera.exposureTime.value, )

            super(HistogramGrid, self).updateFigure()

        except Exception as e:
            logger.warning('Problem in HistogramGrid.updateFigure():\n{}\n{}\n'.format(e, traceback.format_exc()))

    def use_cutoffs(self):
        """Set the cutoffs.  Because they are stored in a numpy field, but we need to set them using a deferred_call,
        the whole ROI array is first copied, then updated, then written back to the squareROIAnalysis
        or gaussian_roi."""

        experiment_timestamp = datetime.datetime.fromtimestamp(self.experiment.timeStarted).strftime('%Y_%m_%d_%H_%M_%S')

        if self.roi_type == 0:  # square ROI
            a = self.experiment.squareROIAnalysis.ROIs.copy()
            a['threshold'] = self.histogram_results[self.cutoff_shot_mapping[0]]['cutoff']
            self.experiment.squareROIAnalysis.set_gui({'ROIs': a})
            self.experiment.squareROIAnalysis.cutoffs_from_which_experiment = experiment_timestamp
        elif self.roi_type == 1:  # gaussian ROI
            self.experiment.gaussian_roi.cutoffs = np.zeros(self.histogram_results['cutoff'].shape)
            try:
                mapping = eval(self.cutoff_shot_mapping)
            except:
                logger.warning('Error evaluating HistogramGrid cutoff_shot_mapping')
                return
            for i, x in enumerate(mapping):
                self.experiment.gaussian_roi.cutoffs[i] = self.histogram_results['cutoff'][x]
            self.experiment.gaussian_roi.cutoffs_from_which_experiment = experiment_timestamp
        else:
            logger.warning('invalid roi type {} in HistogramGrid.calculate_histogram'.format(roi_type))
            raise PauseError

    def calculate_all_histograms(self, all_shots_array):
        measurements, shots, rois = all_shots_array.shape

        # Since the number of measurements is the same for each shot and roi, we can compute the number of bins here:
        self.bins = int(numpy.rint(1.5*numpy.sqrt(measurements)))  # choose 1.5*sqrt(N) as the number of bins

        # create arrays to hold results
        my_dtype = numpy.dtype([('histogram', str(self.bins)+'i4'), ('bin_edges', str(self.bins+1)+'f8'), ('error', 'f8'),
                                ('mean1', 'f8'), ('mean2', 'f8'),  ('width1', 'f8'), ('width2', 'f8'),
                                ('amplitude1', 'f8'), ('amplitude2', 'f8'), ('cutoff', 'f8'), ('loading', 'f8'),
                                ('overlap', 'f8')])
        self.histogram_results = numpy.empty((shots, rois), dtype=my_dtype)
        self.histogram_results.fill(numpy.nan)

        # go through each shot and roi and calculate the histograms and gaussian fits
        for shot in xrange(shots):
            for roi in xrange(rois):
                roidata = all_shots_array[:, shot, roi]

                # get old cutoffs
                if self.calculate_new_cutoffs:
                    cutoff = None
                else:
                    if self.roi_type == 0:  # square ROI
                        cutoff = self.experiment.squareROIAnalysis.ROIs[roi]['threshold']
                    elif self.roi_type == 1:  # gaussian ROI
                        cutoff = self.experiment.gaussian_roi.cutoffs[shot, roi]
                    else:
                        logger.warning('invalid roi type {} in HistogramGrid.calculate_histogram'.format(roi_type))
                        raise PauseError

                self.histogram_results[shot, roi] = self.calculate_histogram(roidata, self.bins, cutoff)
                # these all have the same number of measurements, so they will all have the same size

        # make a note of which cutoffs were used
        if self.calculate_new_cutoffs:
            self.cutoffs_from_which_experiment = datetime.datetime.fromtimestamp(self.experiment.timeStarted).strftime('%Y_%m_%d_%H_%M_%S')
        else:
            if self.roi_type == 0:  # square ROI
                self.cutoffs_from_which_experiment = self.experiment.squareROIAnalysis.cutoffs_from_which_experiment
            elif self.roi_type == 1:  # gaussian ROI
                self.cutoffs_from_which_experiment = self.experiment.gaussian_roi.cutoffs_from_which_experiment
            else:
                logger.warning('invalid roi type {} in HistogramGrid.calculate_histogram'.format(roi_type))
                raise PauseError

        # find the min and max
        self.x_min = numpy.nanmin(all_shots_array)
        self.x_max = numpy.nanmax(all_shots_array)
        self.y_max = numpy.nanmax(self.histogram_results['histogram'])

        # TODO: do cutoff finding, analytical overlap and loading in a vectorized fashion

    def gaussian1D(self, x, x0, a, w):
        """returns the height of a gaussian (with mean x0, amplitude, a and width w) at the value(s) x"""
        g = a/(w*numpy.sqrt(2*numpy.pi))*numpy.exp(-0.5*(x-x0)**2/w**2)  # normalize
        g[numpy.isnan(g)] = 0  # eliminate bad elements
        return g

    def two_gaussians(self, x, x0, a0, w0, x1, a1, w1):
        return self.gaussian1D(x, x0, a0, w0) + self.gaussian1D(x, x1, a1, w1)

    def calculate_histogram(self, ROI_sums, bins, cutoff=None):
        """
        Takes a single histogram.

        :param ROI_sums: the data to be histogrammed.  Length = number of measurements
        :param bins: the number of histogram bins to make
        :param cutoff: The cutoff to use.  If None, a new cutoff will be calculated.
        :return: a tuple of histogram results
        """
        # first numerically take histograms
        hist, bin_edges = numpy.histogram(ROI_sums, bins=bins)
        bin_size = (bin_edges[1:]-bin_edges[:-1])
        y = hist

        if cutoff == None:  # find a new cutoff

            x = (bin_edges[1:]+bin_edges[:-1])/2  # take center of each bin as test points (same in number as y)
            best_error = float('inf')

            #TODO: instead of bin edges, use unbinned data for gaussian fits, and consider all datapoints as possible cutoffs

            # use the bin edges as possible cutoff locations
            # now go through each possible cutoff location and fit a gaussian above and below
            # see which cutoff is the best fit
            for j in xrange(1, bins-1):  # leave off 0th and last bin edge to prevent divide by zero on one of the gaussian sums

                #fit a gaussian below the cutoff
                mean1 = numpy.sum(x[:j]*y[:j])/numpy.sum(y[:j])
                r1 = numpy.sqrt((x[:j]-mean1)**2)  # an array of distances from the mean
                width1 = numpy.sqrt(numpy.abs(numpy.sum((r1**2)*y[:j])/numpy.sum(y[:j])))  # the standard deviation
                amplitude1 = numpy.sum(y[:j]*bin_size[:j])  # area under gaussian is 1, so scale by total volume (i.e. the sum of y)
                g1 = self.gaussian1D(x, mean1, amplitude1, width1)

                # fit a gaussian above the cutoff
                mean2 = numpy.sum(x[j:]*y[j:])/numpy.sum(y[j:])
                r2 = numpy.sqrt((x[j:]-mean2)**2) #an array of distances from the mean
                width2 = numpy.sqrt(numpy.abs(numpy.sum((r2**2)*y[j:])/numpy.sum(y[j:]))) #the standard deviation
                amplitude2 = numpy.sum(y[j:]*bin_size[j:]) #area under gaussian is 1, so scale by total volume (i.e. the sum of y * step size)
                g2 = self.gaussian1D(x, mean2, amplitude2, width2)

                # find the total error
                error = numpy.sum(numpy.abs(y-g1-g2))
                if error < best_error:
                    best_error = error
                    best_mean1 = mean1
                    best_mean2 = mean2
                    best_width1 = width1
                    best_width2 = width2
                    best_amplitude1 = amplitude1
                    best_amplitude2 = amplitude2

            # find a better cutoff
            # the cutoff found is for the digital data, not necessarily the best in terms of the gaussian fits
            cutoff = self.analytic_cutoff(best_mean1, best_mean2, best_width1, best_width2, best_amplitude1, best_amplitude2)

            # deprecated because it wasn't analytic:
            # to find a better cutoff:
            # find the lowest point on the sum of the two gaussians
            # go in steps of 1 from peak to peak
            #xc = numpy.arange(best_mean1, best_mean2)
            #y1 = self.gaussian1D(xc, best_mean1, best_amplitude1, best_width1)
            #y2 = self.gaussian1D(xc, best_mean2, best_amplitude2, best_width2)
            #yc = y1 + y2
            #cutoff = xc[numpy.argmin(yc)]

            # calculalate the overlap (non-analytic, so this is deprecated)
            # mins = numpy.amin([y1, y2], axis=0)
            # overlap = numpy.sum(mins) / (numpy.sum(y1) + numpy.sum(y2))

        else:  # use the existing cutoff, unbinned data

            x = ROI_sums

            below = x[x < cutoff]
            above = x[x >= cutoff]

            mean1 = numpy.mean(below)
            mean2 = numpy.mean(above)
            width1 = numpy.std(below)
            width2 = numpy.std(above)

            bin_size = numpy.mean(bin_size)
            amplitude1 = len(below) * np.mean(bin_size)
            amplitude2 = len(above) * np.mean(bin_size)

            # find the fit error to the histogram
            x = (bin_edges[1:]+bin_edges[:-1])/2  # take center of each bin as test points (same in number as y)
            g1 = self.gaussian1D(x, mean1, amplitude1, width1)
            g2 = self.gaussian1D(x, mean2, amplitude2, width2)
            error = numpy.sum(numpy.abs(y-g1-g2))

            # we only have one cutoff test here, so use it
            best_error = error
            best_mean1 = mean1
            best_mean2 = mean2
            best_width1 = width1
            best_width2 = width2
            best_amplitude1 = amplitude1
            best_amplitude2 = amplitude2

        # calculate the loading based on the cuts (updated if specified) and the actual atom data

        total = len(ROI_sums)
        # make a boolean array of loading
        atoms = ROI_sums >= cutoff
        # find the loading for each roi
        loaded = numpy.sum(atoms)

        loading = loaded/total

        # calculalate the overlap
        # use the cumulative normal distribution function to get the overlap analytically
        # see MTL thesis for derivation
        overlap1 = .5*(1 + erf((best_mean1-cutoff)/(best_width1*np.sqrt(2))))
        overlap2 = .5*(1 + erf((cutoff-best_mean2)/(best_width2*np.sqrt(2))))
        overlap = (overlap1*best_amplitude1 + overlap2*best_amplitude2) / min(best_amplitude1, best_amplitude2)

        return hist, bin_edges, best_error, best_mean1, best_mean2, best_width1, best_width2, best_amplitude1, best_amplitude2, cutoff, loading, overlap

    def analytic_cutoff(self, x1, x2, w1, w2, a1, a2):
        """Find the cutoffs analytically.  See MTL thesis for derivation."""

        return numpy.where(w1 == w2, self.intersection_of_two_gaussians_of_equal_width(x1, x2, w1, w2, a1, a2), self.intersection_of_two_gaussians(x1, x2, w1, w2, a1, a2))

    def intersection_of_two_gaussians_of_equal_width(self, x1, x2, w1, w2, a1, a2):
        return (- x1**2 + x2**2 + w1**2/2*numpy.log(a1/a2))/(2*(x2-x1))

    def intersection_of_two_gaussians(self, x1, x2, w1, w2, a1, a2):
        a = w2**2*x1 - w1**2*x2
        # TODO: protect against imaginary root
        b = w1*w2*numpy.sqrt((x1-x2)**2 + (w2**2 - w1**2)*numpy.log(a1/a2)/2.0)
        c = w2**2 - w1**2
        return (a+b)/c  # use the positive root, as that will be the one between x1 and x2

    def histogram_patch(self, ax, x, y, color):
        # create vertices for histogram patch
        #   repeat each x twice, and two different y values
        #   repeat each y twice, at two different x values
        #   extra +1 length of verts array allows for CLOSEPOLY code
        verts = np.zeros((2*len(x)+1, 2))
        verts[0:-1:2, 0] = x
        verts[1:-1:2, 0] = x
        verts[1:-2:2, 1] = y
        verts[2:-2:2, 1] = y
        # create codes for histogram patch
        codes = np.ones(2*len(x)+1, int) * mpl.path.Path.LINETO
        codes[0] = mpl.path.Path.MOVETO
        codes[-1] = mpl.path.Path.CLOSEPOLY
        # create patch and add it to axes
        my_path = mpl.path.Path(verts, codes)
        patch = patches.PathPatch(my_path, facecolor=color, edgecolor=color, alpha=0.5)
        ax.add_patch(patch)

    def two_color_histogram(self, ax, data):

        # plot histogram for data below the cutoff
        # It is intentional that len(x1)=len(y1)+1 and len(x2)=len(y2)+1 because y=0 is added at the beginning and
        # end of the below and above segments when plotted in histogram_patch, and we require 1 more x point than y.
        x = data['bin_edges']
        x1 = x[x < data['cutoff']]  # take only data below the cutoff
        xc = len(x1)
        x1 = numpy.append(x1, data['cutoff'])  # add the cutoff to the end of the 1st patch
        y = data['histogram']
        y1 = y[:xc]  # take the corresponding histogram counts
        x2 = x[xc:]  # take the remaining values that are above the cutoff
        x2 = np.insert(x2, 0, data['cutoff'])  # add the cutoff to the beginning of the 2nd patch
        y2 = y[xc-1:]

        if len(x1) > 1:  # only draw if there is some data (not including cutoff)
            self.histogram_patch(ax, x1, y1, 'b')  # plot the 0 atom peak in blue
        if len(x2) > 1:  # only draw if there is some data (not including cutoff)
            self.histogram_patch(ax, x2, y2, 'r')  # plot the 1 atom peak in red

    def histogram_grid_plot(self, fig, shot, photoelectronScaling=None, exposure_time=None, font=8):
        """Plot a grid of histograms in the same shape as the ROIs."""

        rows = self.experiment.ROI_rows
        columns = self.experiment.ROI_columns
        # create a grid.  The extra row and column hold the row/column averaged data.
        # width_ratios and height_ratios make those extra cells smaller than the graphs.
        gs1 = GridSpec(rows+1, columns+1, left=0.02, bottom=0.05, top=.95, right=.98, wspace=0.2, hspace=0.75,
                       width_ratios=rows*[1]+[.25], height_ratios=columns*[1]+[.25])

        # make histograms for each site
        for i in xrange(rows):
            for j in xrange(columns):
                try:
                    # choose correct saved data
                    n = columns*i+j
                    data = self.histogram_results[shot, n]

                    # create new plot
                    ax = fig.add_subplot(gs1[i, j])

                    self.two_color_histogram(ax, data)

                    ax.set_xlim([self.x_min, self.x_max])
                    ax.set_ylim([0, self.y_max])
                    #ax.set_title(u'{}: {:.0f}\u00B1{:.1f}%'.format(n, data['loading']*100,data['overlap']*100), size=font)
                    ax.text(0.95, 0.85, u'{}: {:.0f}\u00B1{:.1f}%'.format(n, data['loading']*100, data['overlap']*100), horizontalalignment='right', verticalalignment='center', transform=ax.transAxes, fontsize=font)
                    # put x ticks at the center of each gaussian and the cutoff.
                    # The one at x_max just holds 'e3' to show that the values should be multiplied by 1000
                    ax.set_xticks([data['mean1'], data['cutoff'], data['mean2']])
                    ax.set_xticklabels([u'{}\u00B1{:.1f}'.format(int(data['mean1']), data['width1']),
                                        str(int(data['cutoff'])),
                                        u'{}\u00B1{:.1f}'.format(int(data['mean2']), data['width2'])],
                                       size=font, rotation=90)
                    # add this to xticklabels to print gaussian widths:
                        # u'\u00B1{:.1f}'.format(data['width1']/1000)
                        # u'\u00B1{:.1f}'.format(data['width2']/1000)
                    # put y ticks at the peak of each gaussian fit
                    yticks = [0]
                    yticklabels = ['0']
                    ytickleft = [True]
                    ytickright = [False]
                    if (data['width1'] != 0):
                        y1 = data['amplitude1']/(data['width1']*numpy.sqrt(2*numpy.pi))
                        yticks += [y1]
                        yticklabels += [str(int(numpy.rint(y1)))]
                        ytickleft += [True]
                        ytickright += [False]
                    if (data['width2'] != 0):
                        y2 = data['amplitude2']/(data['width2']*numpy.sqrt(2*numpy.pi))
                        yticks += [y2]
                        yticklabels += [str(int(numpy.rint(y2)))]
                        ytickleft += [False]
                        ytickright += [True]
                    ax.set_yticks(yticks)
                    ax.set_yticklabels(yticklabels, size=font)
                    for tick, left, right in zip(ax.yaxis.get_major_ticks(), ytickleft, ytickright):
                        tick.label1On = left
                        tick.label2On = right
                        tick.size = font
                    # plot gaussians
                    x = numpy.linspace(self.x_min, self.x_max, 100)
                    y1 = self.gaussian1D(x, data['mean1'], data['amplitude1'], data['width1'])
                    y2 = self.gaussian1D(x, data['mean2'], data['amplitude2'], data['width2'])
                    ax.plot(x, y1, 'k', x, y2, 'k')
                    # plot cutoff line
                    ax.vlines(data['cutoff'], 0, self.y_max)
                    ax.tick_params(labelsize=font)
                except Exception as e:
                    logger.warning('Could not plot histogram for shot {} roi {}:\n{}\n{}'.format(shot, n, e, traceback.format_exc()))

        #make stats for each row
        for i in xrange(rows):
            ax = fig.add_subplot(gs1[i, columns])
            ax.axis('off')
            ax.text(0.5, 0.5,
                'row {}\navg loading\n{:.0f}%'.format(i, 100*numpy.mean(self.histogram_results['loading'][shot, i*columns:(i+1)*columns])),
                horizontalalignment='center',
                verticalalignment='center',
                transform=ax.transAxes,
                fontsize=font)

        #make stats for each column
        for i in xrange(columns):
            ax = fig.add_subplot(gs1[rows, i])
            ax.axis('off')
            ax.text(0.5, 0.5,
                'column {}\navg loading\n{:.0f}%'.format(i, 100*numpy.mean(self.histogram_results['loading'][shot, i:i+(rows-1)*columns:columns])),
                horizontalalignment='center',
                verticalalignment='center',
                transform=ax.transAxes,
                fontsize=font)

        #make stats for whole array
        ax = fig.add_subplot(gs1[rows, columns])
        ax.axis('off')
        ax.text(0.5, 0.5,
            'array\navg loading\n{:.0f}%'.format(100*numpy.mean(self.histogram_results['loading'][shot])),
            horizontalalignment='center',
            verticalalignment='center',
            transform=ax.transAxes,
            fontsize=font)

        # add note about photoelectron scaling and exposure time
        figtext = 'cutoffs from {}, target # measurements = {}'.format(
            self.cutoffs_from_which_experiment, self.experiment.measurementsPerIteration)
        if photoelectronScaling is not None:
            figtext += ', scaling applied = {} photoelectrons/count'.format(photoelectronScaling)
        if exposure_time is not None:
            figtext += ', exposure_time = {} ms'.format(exposure_time/1000.0)
        fig.text(.05, .985, figtext)

class MeasurementsGraph(AnalysisWithFigure):
    """Plots a region of interest sum after every measurement"""
    enable = Bool()
    data = Member()
    update_lock = Bool(False)
    list_of_what_to_plot = Str()

    def __init__(self, name, experiment, description=''):
        super(MeasurementsGraph, self).__init__(name, experiment, description)
        self.properties += ['enable', 'list_of_what_to_plot']
        self.data = None

    def analyzeMeasurement(self, measurementResults, iterationResults, experimentResults):
        if self.enable:
            #every measurement, update a big array of all the ROI sums, then histogram only the requested shot/site
            if 'analysis/gaussian_roi/sums' in measurementResults:
                d = measurementResults['analysis/gaussian_roi/sums']
            elif 'analysis/squareROIsums' in measurementResults:
                d = measurementResults['analysis/squareROIsums']
            else:
                logger.warning('No data to use in MeasurementsGraph')
                return
            if self.data is None:
                self.data = numpy.array([d])
            else:
                self.data = numpy.append(self.data, numpy.array([d]), axis=0)
            self.updateFigure()

    @observe('list_of_what_to_plot')
    def reload(self, change):
        self.updateFigure()

    def clear(self):
        self.data = None
        self.updateFigure()

    def updateFigure(self):
        if not self.update_lock:
            try:
                self.update_lock = True
                fig = self.backFigure
                fig.clf()

                if self.data is not None:
                    #parse the list of what to plot from a string to a list of numbers
                    try:
                        plotlist = eval(self.list_of_what_to_plot)
                    except Exception as e:
                        logger.warning('Could not eval plotlist in MeasurementsGraph:\n{}\n'.format(e))
                        return
                    #make one plot
                    ax = fig.add_subplot(111)
                    for i in plotlist:
                        try:
                            data = self.data[:, i[0], i[1]]
                        except:
                            logger.warning('Trying to plot data that does not exist in MeasurementsGraph: shot {} roi {}'.format(i[0], i[1]))
                            continue
                        label = '({},{})'.format(i[0], i[1])
                        ax.plot(data, 'o', label=label)
                    #add legend using the labels assigned during ax.plot()
                    ax.legend()
                super(MeasurementsGraph, self).updateFigure()
            except Exception as e:
                logger.warning('Problem in MeasurementsGraph.updateFigure()\n:{}'.format(e))
            finally:
                self.update_lock = False


class IterationsGraph(AnalysisWithFigure):
    """Plots the average of a region of interest sum for an iteration, after each iteration"""
    enable = Bool()
    mean = Member()
    sigma = Member()
    current_iteration_data = Member()
    update_lock = Bool(False)
    list_of_what_to_plot = Str()
    draw_connecting_lines = Bool()
    draw_error_bars = Bool()
    add_only_filtered_data = Bool()
    ymin = Str()
    ymax = Str()
    update_every_measurement = Bool()

    def __init__(self, name, experiment, description=''):
        super(IterationsGraph, self).__init__(name, experiment, description)
        self.properties += ['enable', 'list_of_what_to_plot', 'draw_connecting_lines', 'draw_error_bars', 'ymin',
                            'ymax', 'update_every_measurement']

    def preExperiment(self, experimentResults):
        #erase the old data at the start of the experiment
        self.mean = None
        self.sigma = None

    def preIteration(self, iterationResults, experimentResults):
        self.current_iteration_data = None

    def analyzeMeasurement(self, measurementResults, iterationResults, experimentResults):
        # Check to see if we want to do anything with this data, based on the LoadingFilters.
        # Careful here to use .value, otherwise it will always be True if the dataset exists.
        if self.enable:  # and self.update_every_measurement:
            if (not self.add_only_filtered_data) or (('analysis/loading_filter' in measurementResults) and measurementResults['analysis/loading_filter'].value):

                d = numpy.array([measurementResults['analysis/squareROIsums']])

                if self.current_iteration_data is None:
                    #on first measurement of an iteration, start anew
                    new_iteration = True
                    self.current_iteration_data = d
                else:
                    #else append
                    new_iteration = False
                    self.current_iteration_data = numpy.append(self.current_iteration_data, d, axis=0)

                # average across measurements
                # keepdims gives result with size (1 x shots X rois)
                mean = numpy.mean(self.current_iteration_data, axis=0, keepdims=True)
                #find standard deviation of the mean
                sigma = numpy.std(self.current_iteration_data, axis=0, keepdims=True)/numpy.sqrt(len(self.current_iteration_data))

                if self.mean is None:
                    #on first iteration start anew
                    self.mean = mean
                    self.sigma = sigma
                else:
                    if new_iteration:
                        #append
                        self.mean = numpy.append(self.mean, mean, axis=0)
                        self.sigma = numpy.append(self.sigma, sigma, axis=0)
                    else:
                        #replace last entry
                        self.mean[-1] = mean
                        self.sigma[-1] = sigma
                self.updateFigure()

    # TODO: this needs to be made to update at the iteration update
    """
        def analyzeIteration(self, iterationResults, experimentResults):
            # Check to see if we want to do anything with this data, based on the LoadingFilters.
            # Careful here to use .value, otherwise it will always be True if the dataset exists.
            if self.enable:
                if (not self.add_only_filtered_data) or (('analysis/loading_filter' in measurementResults) and measurementResults['analysis/loading_filter'].value):

                    d = numpy.array([measurementResults['analysis/squareROIsums']])

                    if self.current_iteration_data is None:
                        #on first measurement of an iteration, start anew
                        new_iteration = True
                        self.current_iteration_data = d
                    else:
                        #else append
                        new_iteration = False
                        self.current_iteration_data = numpy.append(self.current_iteration_data, d, axis=0)

                    # average across measurements
                    # keepdims gives result with size (1 x shots X rois)
                    mean = numpy.mean(self.current_iteration_data, axis=0, keepdims=True)
                    #find standard deviation
                    sigma = numpy.std(self.current_iteration_data, axis=0, keepdims=True)/numpy.sqrt(len(self.current_iteration_data))

                    if self.mean is None:
                        #on first iteration start anew
                        self.mean = mean
                        self.sigma = sigma
                    else:
                        if new_iteration:
                            #append
                            self.mean = numpy.append(self.mean, mean, axis=0)
                            self.sigma = numpy.append(self.sigma, sigma, axis=0)
                        else:
                            #replace last entry
                            self.mean[-1] = mean
                            self.sigma[-1] = sigma
                    self.updateFigure()
    """

    @observe('list_of_what_to_plot', 'draw_connecting_lines', 'ymin', 'ymax')
    def reload(self, change):
        self.updateFigure()

    def updateFigure(self):
        if not self.update_lock:
            try:
                self.update_lock = True
                fig = self.backFigure
                fig.clf()

                if self.mean is not None:
                    #parse the list of what to plot from a string to a list of numbers
                    try:
                        plotlist = eval(self.list_of_what_to_plot)
                    except Exception as e:
                        logger.warning('Could not eval plotlist in IterationsGraph:\n{}\n'.format(e))
                        return
                    #make one plot
                    ax = fig.add_subplot(111)
                    for i in plotlist:
                        try:
                            mean = self.mean[:, i[0], i[1]]
                            sigma = self.sigma[:, i[0], i[1]]
                        except:
                            logger.warning('Trying to plot data that does not exist in IterationsGraph: shot {} roi {}'.format(i[0], i[1]))
                            continue
                        label = '({},{})'.format(i[0], i[1])
                        linestyle = '-o' if self.draw_connecting_lines else 'o'
                        if self.draw_error_bars:
                            ax.errorbar(numpy.arange(len(mean)), mean, yerr=sigma, fmt=linestyle, label=label)
                        else:
                            ax.plot(numpy.arange(len(mean)), mean, linestyle, label=label)
                    #adjust the limits so that the data isn't right on the edge of the graph
                    ax.set_xlim(-.5, len(self.mean)+0.5)
                    if self.ymin != '':
                        ax.set_ylim(bottom=float(self.ymin))
                    if self.ymax != '':
                        ax.set_ylim(top=float(self.ymax))
                    #add legend using the labels assigned during ax.plot() or ax.errorbar()
                    ax.legend()
                super(IterationsGraph, self).updateFigure()
            except Exception as e:
                logger.warning('Problem in IterationsGraph.updateFigure()\n{}\n{}\n'.format(e, traceback.format_exc()))
            finally:
                self.update_lock = False


class RetentionGraph(AnalysisWithFigure):
    """Plots the average of a region of interest sum for an iteration, after each iteration"""
    enable = Bool()
    mean = Member()
    sigma = Member()
    current_iteration_data = Member()
    update_lock = Bool(False)
    list_of_what_to_plot = Str()
    draw_connecting_lines = Bool()
    draw_error_bars = Bool()
    add_only_filtered_data = Bool()
    ymin = Str()
    ymax = Str()

    def __init__(self, name, experiment, description=''):
        super(RetentionGraph, self).__init__(name, experiment, description)
        self.properties += ['enable', 'list_of_what_to_plot', 'draw_connecting_lines', 'draw_error_bars', 'ymin', 'ymax']

    def preExperiment(self, experimentResults):
        #erase the old data at the start of the experiment
        self.mean = None
        self.sigma = None

    def preIteration(self, iterationResults, experimentResults):
        self.current_iteration_data = None

    def analyzeIteration(self, iterationResults, experimentResults):
        if self.enable:
            # check to see if retention analysis was done
            if 'analysis/loading_retention' in iterationResults:
                # load retention, and pad arrays with an extra dimension so they can be concatenated
                retention = iterationResults['analysis/loading_retention/retention'].value[np.newaxis]
                sigma = iterationResults['analysis/loading_retention/retention_sigma'].value[np.newaxis]
                if self.mean is None:
                    #on first iteration start anew
                    self.mean = retention
                    self.sigma = sigma
                else:
                    #append
                    self.mean = numpy.append(self.mean, retention, axis=0)
                    self.sigma = numpy.append(self.sigma, sigma, axis=0)
                self.updateFigure()

    def analyzeMeasurement(self, measurementResults, iterationResults, experimentResults):
        pass
        # """Every measurement, update the results.  Plot the ratio of shots with an atom to shots without."""
        # # Check to see if we want to do anything with this data, based on the LoadingFilters.
        # # Careful here to use .value, otherwise it will always be True if the dataset exists.
        # if self.enable:
        #     if (not self.add_only_filtered_data) or (('analysis/loading_filter' in measurementResults) and measurementResults['analysis/loading_filter'].value):
        #
        #         # grab already thresholded data from SquareROIAnalysis
        #         a = measurementResults['analysis/squareROIthresholded']
        #         # add one dimension to the data to help with appending
        #         d = numpy.reshape(a, (1, a.shape[0], a.shape[1]))
        #
        #         if self.current_iteration_data is None:
        #             #on first measurement of an iteration, start anew
        #             new_iteration = True
        #             self.current_iteration_data = d
        #         else:
        #             #else append
        #             new_iteration = False
        #             self.current_iteration_data = numpy.append(self.current_iteration_data, d, axis=0)
        #
        #         # average across measurements
        #         # keepdims gives result with size (1 x shots X rois)
        #         mean = numpy.mean(self.current_iteration_data, axis=0, keepdims=True)
        #         #find the 1 sigma confidence interval using the normal approximation: http://en.wikipedia.org/wiki/Binomial_proportion_confidence_interval
        #         sigma = numpy.sqrt(mean*(1-mean)/len(self.current_iteration_data))
        #
        #         if self.mean is None:
        #             #on first iteration start anew
        #             self.mean = mean
        #             self.sigma = sigma
        #         else:
        #             if new_iteration:
        #                 #append
        #                 self.mean = numpy.append(self.mean, mean, axis=0)
        #                 self.sigma = numpy.append(self.sigma, sigma, axis=0)
        #             else:
        #                 #replace last entry
        #                 self.mean[-1] = mean
        #                 self.sigma[-1] = sigma
        #         self.updateFigure()

    @observe('list_of_what_to_plot', 'draw_connecting_lines', 'draw_error_bars', 'ymin', 'ymax')
    def reload(self, change):
        self.updateFigure()

    def updateFigure(self):
        if not self.update_lock:
            try:
                self.update_lock = True
                fig = self.backFigure
                fig.clf()

                if self.mean is not None:
                    #parse the list of what to plot from a string to a list of numbers
                    try:
                        plotlist = eval(self.list_of_what_to_plot)
                    except Exception as e:
                        logger.warning('Could not eval plotlist in RetentionGraph:\n{}\n'.format(e))
                        return
                    #make one plot
                    ax = fig.add_subplot(111)
                    for i in plotlist:
                        try:
                            mean = self.mean[:, i]
                            sigma = self.sigma[:, i]
                        except:
                            logger.warning('Trying to plot data that does not exist in RetentionGraph: roi {}'.format(i))
                            continue
                        label = '({})'.format(i)
                        linestyle = '-o' if self.draw_connecting_lines else 'o'
                        if self.draw_error_bars:
                            ax.errorbar(numpy.arange(len(mean)), mean, yerr=sigma, fmt=linestyle, label=label)
                        else:
                            ax.plot(numpy.arange(len(mean)), mean, linestyle, label=label)
                    #adjust the limits so that the data isn't right on the edge of the graph
                    ax.set_xlim(-.5, len(self.mean)+0.5)
                    if self.ymin != '':
                        ax.set_ylim(bottom=float(self.ymin))
                    if self.ymax != '':
                        ax.set_ylim(top=float(self.ymax))
                    #add legend using the labels assigned during ax.plot() or ax.errorbar()
                    ax.legend(bbox_to_anchor=(0., 1.02, 1., .102), loc=3, ncol=7, mode="expand", borderaxespad=0.)

                super(RetentionGraph, self).updateFigure()
            except Exception as e:
                logger.warning('Problem in RetentionGraph.updateFigure()\n{}\n{}\n'.format(e, traceback.format_exc()))
            finally:
                self.update_lock = False

class Ramsey(AnalysisWithFigure):
    """Plots the average of a region of interest sum for an iteration, after each iteration.  Can be used with the
    optimizer with the cost function:
    # ramsey experiment optimizer cost function:
    self.yi = -experimentResults['analysis/Ramsey/frequency']
    """

    enable = Bool()
    draw_error_bars = Bool()

    roi = Int()
    time_variable_name = Str()
    amplitude_guess = Float()
    frequency_guess = Float()
    offset_guess = Float()
    decay_guess = Float()

    y = Member()
    t = Member()
    sigma = Member()
    fitParams = Member()

    amplitude = Float()
    frequency = Float()
    offset = Float()
    decay = Float()

    def __init__(self, name, experiment, description=''):
        super(Ramsey, self).__init__(name, experiment, description)
        self.properties += ['enable', 'draw_error_bars', 'roi', 'time_variable_name', 'amplitude_guess', 'frequency_guess', 'offset_guess', 'decay_guess']

    def fitFunc(self, t, amplitude, frequency, offset, decay):
        return amplitude*numpy.cos(2*numpy.pi*frequency*t)*numpy.exp(t/decay)+offset

    def analyzeExperiment(self, experimentResults):
        """For all iterations in this experiment, calculate the retention fraction.  This should result in a cosine
        curve.  Fit a cosine to this, and store the amplitude and frequency."""

        if self.enable:
            num_iterations = len(experimentResults)
            self.y = numpy.zeros(num_iterations, dtype=numpy.float64)
            self.t = numpy.zeros(num_iterations, dtype=numpy.float64)
            self.sigma = numpy.zeros(num_iterations, dtype=numpy.float64)
            for i in xrange(num_iterations):
                # check to see if retention analysis was done
                if 'analysis/loading_retention' not in experimentResults['iterations/{}'.format(i)]:
                    logger.warning('Ramsey analysis: Retention data not present in iteration {}'.format(i))
                    raise PauseError
                # get retention data from the retention analysis
                self.y[i] = experimentResults['iterations/{}/analysis/loading_retention/retention'.format(i)].value
                self.sigma[i] = experimentResults['iterations/{}/analysis/loading_retention/retention_sigma'.format(i)].value
                self.t[i] = experimentResults['iterations/'+str(i)+'/variables/'+self.time_variable_name].value

            # now that we have retention vs. time, do a curve fit
            initial_guess = (self.amplitude_guess, self.frequency_guess, self.offset_guess, self.decay_guess)

            try:
                self.fitParams, fitCovariances = curve_fit(self.fitFunc, self.t, self.y, p0=initial_guess)
            except Exception as e:
                # note the error, set the amplitude to 0 and move on:
                logger.warning("Exception in Ramsey.analyzeExperiment:\n{}\n".format(e))
                # set the results to zero
                self.fitParams = (0, 0, 0, 0)
                fitCovariances = numpy.zeros((4, 4))

            experimentResults['analysis/Ramsey/amplitude'] = self.fitParams[0]
            experimentResults['analysis/Ramsey/frequency'] = self.fitParams[1]
            experimentResults['analysis/Ramsey/offset'] = self.fitParams[2]
            experimentResults['analysis/Ramsey/decay'] = self.fitParams[3]
            experimentResults['analysis/Ramsey/covar'] = fitCovariances
            self.set_gui({'amplitude': self.fitParams[0], 'frequency': self.fitParams[1], 'offset': self.fitParams[2], 'decay': self.fitParams[3]})
            self.updateFigure()

    def optimizer_update_guess(self):
        if self.enable:
            self.set_gui({'amplitude_guess': self.fitParams[0], 'frequency_guess': self.fitParams[1], 'offset_guess': self.fitParams[2], 'decay_guess': self.fitParams[3]})

    def updateFigure(self):
        try:
            fig = self.backFigure
            fig.clf()
            ax = fig.add_subplot(111)

            # plot the data points
            linestyle = 'o'
            if self.draw_error_bars:
                ax.errorbar(self.t, self.y, yerr=self.sigma, fmt=linestyle)
            else:
                ax.plot(self.t, self.y, linestyle)
            #adjust the limits so that the data isn't right on the edge of the graph
            span = numpy.amax(self.t) - numpy.amin(self.t)
            xmin = numpy.amin(self.t)-.02*span
            xmax = numpy.amax(self.t)+.02*span
            ax.set_xlim(xmin, xmax)

            # draw the fit
            t = numpy.linspace(xmin, xmax, 200)
            ax.plot(t, self.fitFunc(t, *self.fitParams), '-')
            super(Ramsey, self).updateFigure()
        except Exception as e:
            logger.warning('Problem in Ramsey.updateFigure()\n{}\n{}\n'.format(e, traceback.format_exc()))

class RetentionAnalysis(Analysis):

    #Text output that can be updated back to the GUI
    enable = Bool()
    text = Str()
    roi_type = Int()

    def __init__(self, name, experiment, description=''):
        super(RetentionAnalysis, self).__init__(name, experiment, description)
        self.properties += ['enable', 'text', 'roi_type']

    def analyzeIteration(self, iterationResults, experimentResults):
        if self.enable:
            if self.roi_type == 0:  # square roi
                cutoffs = self.experiment.squareROIAnalysis.ROIs['threshold']
                ROI_sums = iterationResults['analysis/square_roi/sums'].value
            elif self.roi_type == 1:  # gaussian roi
                cutoffs = self.experiment.gaussian_roi.cutoffs
                ROI_sums = iterationResults['analysis/gaussian_roi/sums'].value
            else:
                logger.warning('invalid roi type {} in RetentionAnalysis.analyzeIteration'.format(roi_type))

            loaded, retained, reloaded, loading, retention, retention_sigma, reloading, text, atoms = self.retention(cutoffs, ROI_sums)

            iterationResults['analysis/loading_retention/loaded'] = loaded
            iterationResults['analysis/loading_retention/retained'] = retained
            iterationResults['analysis/loading_retention/reloaded'] = reloaded
            iterationResults['analysis/loading_retention/loading'] = loading
            iterationResults['analysis/loading_retention/retention'] = retention
            iterationResults['analysis/loading_retention/retention_sigma'] = retention_sigma
            iterationResults['analysis/loading_retention/reloading'] = reloading
            iterationResults['analysis/loading_retention/text'] = text
            iterationResults['analysis/loading_retention/atoms'] = atoms

            self.set_gui({'text': text})

    def retention(self, cutoffs, ROI_sums, rows=7, columns=7):
        # cutoffs has shape (rois)
        # ROI_sums has shape (measurements, shots, rois)

        total = ROI_sums.shape[0]

        # make a boolean array of loading
        atoms = ROI_sums >= cutoffs
        # find the loading for each roi
        loaded = numpy.sum(atoms[:, 0, :], axis=0)
        # find the retention for each roi
        retained = numpy.sum(numpy.logical_and(atoms[:, 0, :], atoms[:, 1, :]), axis=0)
        # find the number of reloaded atoms
        reloaded = numpy.sum(numpy.logical_and(numpy.logical_not(atoms[:, 0, :]), atoms[:, 1, :]), axis=0)

        loading = loaded/total
        retention = retained/loaded
        # find the 1 sigma confidence interval for binomial data using the normal approximation:
        # http://en.wikipedia.org/wiki/Binomial_proportion_confidence_interval
        retention_sigma = numpy.sqrt(retention*(1-retention)/loaded)
        reloading = reloaded/total

        # write results to string
        text = 'total: ' + str(total) +'\n\n'
        text += 'loading:\tmax {:.3f},\tavg {:.3f}\n'.format(numpy.nanmax(loading), numpy.nanmean(loading))
        text += '\n'.join(['\t'.join(map(lambda x: '{:.3f}'.format(x), loading[row*columns:(row+1)*columns])) for row in xrange(rows)]) + '\n\n'
        text += 'retention:\tmax {:.3f},\tavg {:.3f}\n'.format(numpy.nanmax(retention), numpy.nanmean(retention))
        text += '\n'.join(['\t'.join(map(lambda x: '{:.3f}'.format(x), retention[row*columns:(row+1)*columns])) for row in xrange(rows)]) + '\n\n'
        text += 'reloading:\tmax {:.3f},\tavg {:.3f}\n'.format(numpy.nanmax(reloading), numpy.nanmean(reloading))
        text += '\n'.join(['\t'.join(map(lambda x: '{:.3f}'.format(x), reloading[row*columns:(row+1)*columns])) for row in xrange(rows)]) + '\n'

        return loaded, retained, reloaded, loading, retention, retention_sigma, reloading, text, atoms
