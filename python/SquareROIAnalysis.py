"""
SquareROIAnalysis.py
Part of the CsPyController package.

This analysis integrates the signal in rectangular ROIs and saves the data to the
HDF5 file

author = 'Martin Lichtman'
created = '2014.09.08'
modified >= '2014.09.08'
modified >= '2017.05.04'
"""

import logging
from colors import my_cmap, green_cmap

import numpy as np
from atom.api import Bool, Str, Member, Int

from analysis import AnalysisWithFigure

logger = logging.getLogger(__name__)

# get the config file
from __init__ import import_config
config = import_config()

def roi_sum(roi, shot):
    '''Sum over a single ROI'''
    return np.sum(shot[roi['top']:roi['bottom'], roi['left']:roi['right']])

def roi_sums(rois, shot):
    '''Sum over a list of ROIs'''
    return np.array([roi_sum(roi, shot) for roi in rois], dtype=np.uint32) #pylint: disable=E1101

class SquareROIAnalysis(AnalysisWithFigure):
    """Add up the sums of pixels in a region, and evaluate whether or not an 
    atom is present based on the totals.
    """

    version = '2017.05.04'
    ROI_rows = Int()
    ROI_columns = Int()
    ROIs = Member()  # a numpy array holding an ROI in each row
    filter_level = Int()
    enable = Bool()
    cutoffs_from_which_experiment = Str()
    sum_array = Member()
    camera = Member()
    shots_path = Member()
    meas_analysis_path = Member()
    iter_analysis_path = Member()

    def __init__(self, experiment, roi_rows=1, roi_columns=1):
        super(SquareROIAnalysis, self).__init__(
            'SquareROIAnalysis', 
            experiment, 
            'Does analysis on square regions of interest'
        )
        self.ROI_rows = roi_rows
        self.ROI_columns = roi_columns
        dtype = [
            ('left', np.uint16),      #pylint: disable=E1101
            ('top', np.uint16),       #pylint: disable=E1101
            ('right', np.uint16),     #pylint: disable=E1101
            ('bottom', np.uint16),    #pylint: disable=E1101
            ('threshold', np.uint32)  #pylint: disable=E1101
        ]
        self.ROIs = np.zeros(roi_rows*roi_columns, dtype=dtype)  # initialize with a blank array
        self.sum_array = np.zeros((0, roi_rows, roi_columns), dtype=np.uint32)
        self.shots_path = 'data/' + config.get('CAMERA', 'DataGroup') + '/shots'
        self.meas_analysis_path = 'analysis/squareROIsums'
        self.iter_analysis_path = 'analysis/square_roi/sums'

        self.properties += ['version', 'filter_level', 'enable', 'ROIs']

    def find_camera(self):
        '''find camera instrument object in experiment properties tree
        Returns camera object
        '''
        # get the property tree path to the camera object from the configuration file
        prop_tree = config.get('CAMERA', 'CameraObj').split(',')

        camera = self.experiment
        for lvl in prop_tree:
            camera = getattr(camera, lvl)

        # if the camera is stored in a ListProp list then use the index function to retreive it
        camera_idx = config.getint('CAMERA', 'CameraIdx')
        if camera_idx >= 0:
            try:
                camera = camera[camera_idx]
            except ValueError:
                logger.warning(
                    'No camera found at index `%d` in camera list: `%s`. Disabling analysis',
                    camera_idx,
                    '.'.join(prop_tree)
                )
                self.enable = False

        return camera

    def analyzeMeasurement(self, measurementResults, iterationResults, experimentResults):
        if self.enable:
            if self.shots_path in measurementResults:
                #here we want to live update a digital plot of atom loading as it happens
                num_shots = len(measurementResults[self.shots_path])
                if self.camera.enable and (num_shots != self.camera.shotsPerMeasurement.value):
                    logger.warning(
                        'Camera expected %s shots, but instead got %s.',
                        self.camera.shotsPerMeasurement, num_shots
                    )
                    return 3  # hard fail, delete measurement

                num_rois = len(self.ROIs)

                sum_array = np.zeros((num_shots, num_rois), dtype=np.uint32) #pylint: disable=E1101

                #for each image
                for i, (name, shot) in enumerate(measurementResults[self.shots_path].items()):
                    shot_sums = roi_sums(self.ROIs, shot)
                    sum_array[i] = shot_sums

                self.sum_array = sum_array.reshape((num_shots, self.ROI_rows, self.ROI_columns))
                measurementResults[self.meas_analysis_path] = sum_array
                self.updateFigure()

            # check to see if there were supposed to be images
            elif self.camera.enable and (self.camera.shotsPerMeasurement.value > 0):
                logger.warning(
                    'Camera expected %s shots, but did not get any.', 
                    self.camera.shotsPerMeasurement.value
                )
                return 3  # hard fail, delete measurement

    def analyzeIteration(self, iterationResults, experimentResults):
        """
        create a big array of the results from each measurement for convenience
        data is stored in iterationResults['analysis/square_roi/sums']
        as an array of size (measurements x shots x roi) array
        """
        if self.enable:
            meas = map(int, iterationResults['measurements'].keys())
            meas.sort()
            path = 'measurements/{}/' + self.meas_analysis_path
            res = np.array([iterationResults[path.format(m)] for m in meas])
            iterationResults[self.iter_analysis_path] = res

    def fromHDF5(self, hdf):
        ''' I need to override this so I can call the find camera function after the camera
        has been loaded
        '''
        super(SquareROIAnalysis, self).fromHDF5(hdf)
        # I am here because the camera needs to be setup first
        self.camera = self.find_camera()

    def updateFigure(self):
        fig = self.backFigure
        fig.clf()
        if self.sum_array.size > 0:
            n = len(self.sum_array)
            for i in range(n):
                ax = fig.add_subplot(n, 1, i+1)
                #make the digital plot here
                ax.matshow(self.sum_array[i], cmap=green_cmap)
                ax.set_title('shot '+str(i))
        super(SquareROIAnalysis, self).updateFigure()