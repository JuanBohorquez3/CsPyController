import logging
import numpy
import h5py
import requests

from atom.api import Bool, Str, Member, Int, Float
from instrument_property import Prop, EvalProp, ListProp, FloatProp
from cs_instruments import Instrument
from colors import green_cmap
from time import sleep

logger = logging.getLogger(__name__)


class Rearrange_settings(Prop):
    # must keep track of voltage changes
    jump_time = Float()
    frequency_increment = Float()
    laser_ramp_on_time = Float()
    iter_analysis_base_path = Str()
    frequency_occupation_array = Member()# a numpy array holding an xfrequency, yfrequency, and occupation status in each row
    rows = Int()
    columns = Int()
    gaussian_roi_params = Member()
    s0_thresholds = Member()
    

    def __init__(self, name, experiment, description=''):
        super(Rearrange_settings, self).__init__(name, experiment, description)
        dtype = [('xfrequency', numpy.float16),('yfrequency', numpy.float16),('occupation', numpy.uint16)]
        self.frequency_occupation_array = numpy.zeros(121, dtype=dtype)  # initialize with a blank array
        self.properties += ['jump_time', 'frequency_increment', 'laser_ramp_on_time', 'frequency_occupation_array']
        
        # where we are going to dump data after analysis
        self.iter_analysis_base_path = 'analysis'
        
        # open settings file
        settings = h5py.File('settings.hdf5','r')
        
        # get rows and columns
        self.rows = settings['settings/experiment/ROI_rows'].value
        self.columns = settings['settings/experiment/ROI_columns'].value
        
        # get gaussian roi parameters and append image rows and columns to front of list 
        bottom = eval(settings['settings/experiment/LabView/camera/frameGrabberAcquisitionRegionBottom/function'].value)
        top =  eval(settings['settings/experiment/LabView/camera/frameGrabberAcquisitionRegionTop/function'].value)
        image_rows = bottom - top
        right = eval(settings['settings/experiment/LabView/camera/frameGrabberAcquisitionRegionRight/function'].value)
        left =  eval(settings['settings/experiment/LabView/camera/frameGrabberAcquisitionRegionLeft/function'].value)
        image_columns = right - left
        
        self.gaussian_roi_params = settings['settings/experiment/gaussian_roi/fitParams'].value
        self.gaussian_roi_params = [(image_rows,image_columns)]+list(self.gaussian_roi_params)
        
        # get cutoffs to send to rearranger
        barecutoff = settings['settings/experiment/thresholdROIAnalysis/threshold_array'].value[0]
        self.s0_thresholds = numpy.zeros(self.rows*self.columns)
        for i in range(self.rows * self.columns):
            self.s0_thresholds[i] = barecutoff[i][0]
        self.s0_thresholds[i] = self.s0_thresholds[i]
        
        #close hdf5 file
        settings.close()

    def postIteration(self, iterationResults, experimentResults):
        if self.enable:
           # --- save analysis ---
            data_path = self.iter_analysis_base_path + 'rearrange/frequency_occupation_array'
            iterationResults[data_path] = self.frequency_occupation_array
            data_path = self.iter_analysis_base_path + 'rearranger/laser_ramp_params'
            iterationResults[data_path] = [self.frequency_increment, self.jump_time, self.laser_ramp_on_time]
            
    def update_settings(self):
        # return the new voltage value'
        xfrequencies = numpy.zeros(self.rows*self.columns)
        yfrequencies = numpy.zeros(self.rows*self.columns)
        desired_occupation = numpy.zeros(self.rows*self.columns, dtype = int)
        for x in range(self.rows*self.columns):
            xfrequencies[x] = self.frequency_occupation_array[x][0]
            yfrequencies[x] =  self.frequency_occupation_array[x][1]
            desired_occupation[x] =  self.frequency_occupation_array[x][2]
            print self.xfrequencies
        arduino_dict = {'xfrequencies': list(xfrequencies), 'yfrequencies': list(yfrequencies), 'frequency_increment': self.frequency_increment, 
            'jump_time': self.jump_time, 'laser_ramp_on_time': self.laser_ramp_on_time}
            
        python_dict = {'desired_occupation': list(desired_occupation), 'gaussian_roi_params': self.gaussian_roi_params, 's0_thresholds': list(self.s0_thresholds)}
        
        return python_dict, arduino_dict



class Rearrange(Instrument):
    '''Send data to atom rearranger on PXI crate
    '''
    version = '2018.06.18'
    IP = Str()
    port = Int()



    def __init__(self, name, experiment, description=''):
        super(Rearrange, self).__init__(name, experiment, description='') 
        
        self.properties += ['version', 'IP', 'port','enable']

    def update_values(self):
        rearrange_settings = Rearrange_settings('rearrange_settings', self, description ='')
        return rearrange_settings.update_settings()
        
        
        
    def initialize(self):
        if self.enable:
            self.isInitialized = True

    def start(self):
        self.isDone = True

    def update(self):
        """
        Every iteration, send settings to rearranger program updated positions.
        """
        python_address = 'http://{}:{}/python_settings'.format(self.IP, self.port)
        arduino_address = 'http://{}:{}/arduino_settings'.format(self.IP, self.port)
        if True:
            if True:

                python_dict, arduino_dict= self.update_values()
                #print python_dict
                requests.post(python_address, json=python_dict)
                sleep(0.005)
                requests.post(arduino_address, json=arduino_dict)
            else:
                xfrequencies, yfrequencies, desired_occupation, frequency_increment, jump_time, laser_ramp_on_time, gaussian_roi_params, s0_thresholds = self.update_values()
            
                desired_occupation = numpy.zeros(121)            
                python_dict = {'desired_occupation': desired_occupation} 
                requests.post(python_address, json=python_dict)