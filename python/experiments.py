"""experiments.py
This file contains the model to describe and experiment, and the machinery of how an iteration based experiment is run.

author=Martin Lichtman
"""

from __future__ import division
__author__ = 'Martin Lichtman'
import logging
logger = logging.getLogger(__name__)
from cs_errors import PauseError

# import core python modules
import threading, time, datetime, traceback, os, shutil, cStringIO, numpy, h5py

#set numpy print options to limit to 2 digits
numpy.set_printoptions(formatter=dict(float=lambda t: "%.2e" % t))

# Use Atom traits to automate Enaml updating
from atom.api import Int, Float, Str, Member, Bool

# Bring in other files in this package
import cs_evaluate, sound, optimization
from instrument_property import Prop, EvalProp, ListProp, StrProp

class IndependentVariable(EvalProp):
    """A class to hold the independent variables for an experiment.  These are
    the variables that get stepped through during the iterations.  Each 
    independent variable is defined by a valueList which holds an array of values.
    Using this technique, the valueList can be assigned as single value, an arange, linspace,
    logspace, sin(logspace), as complicated as you like, so long as it can be eval()'d and then
    cast to an array."""
    
    valueListStr = Str()
    steps = Member()
    index = Member()
    currentValueStr = Str()
    valueList = Member()
    currentValue = Member()

    # optimizer variables
    optimize = Bool()
    optimizer_initial_step = Float()
    optimizer_min = Float()
    optimizer_max = Float()
    optimizer_end_tolerance = Float()
    
    def __init__(self, name, experiment, description='', function=''):
        super(IndependentVariable, self).__init__(name, experiment, description, function)
        self.steps = 0
        self.index = 0
        self.valueList = numpy.array([]).flatten()
        self.currentValue = None
        self.properties += ['optimize', 'optimizer_initial_step', 'optimizer_min', 'optimizer_max',
                            'optimizer_end_tolerance']

    def evaluate(self):
        """This function evaluates just the independent variables.  We do not update the rest of the experiment,
        although it may depend on this change, because it would be too cumbersome.  There is a button available that
        calls experiment.evaluateAll() to update the whole experiment at will."""
        if self.experiment.allow_evaluation:
            if self.function == '':
                a = None
            else:

                #Evaluate the independent variable.
                #Cast it to a 1D numpy array as part of the evaluation.  If this cannot be done, the function is not
                #valid as an independent variable and an error is returned.
                #Pass in a dictionary with numpy as the keyword np, for the user to create array variables using
                #linspace, arange, etc.

                a = cs_evaluate.evalIvar('array('+self.function+').flatten()', self.experiment.constants)
            if a is None:
                a = numpy.array([]).flatten()
            self.valueList = a
            self.steps = len(a)
            self.valueListStr = str(self.valueList)
            self.setIndex(self.index)

    def setIndex(self, index):
        if self.steps == 0:
            self.currentValue = None
        else:
            if 0 <= index < self.steps:
                self.index = index
            else:
                logger.warning('Index='+str(index)+' out of range for independent variable '+self.name+'. Setting '+self.name+'.index=0\n')
                self.index = 0
            self.currentValue = self.valueList[self.index]
        self.currentValueStr = str(self.currentValue)
        return self.index


class Experiment(Prop):

    version = '2014.04.30'

    #experiment control
    status = Str('idle')
    statusStr = Str()
    valid = Bool(True)  # the window will flash red on error
    pauseAfterIteration = Bool()
    pauseAfterMeasurement = Bool()
    pauseAfterError = Bool()
    saveData = Bool()
    saveSettings = Bool()
    settings_path = Str()
    save_separate_notes = Bool()
    save2013styleFiles = Bool()
    localDataPath = Str()
    networkDataPath = Str()
    copyDataToNetwork = Bool()
    experimentDescriptionFilenameSuffix = Str()
    measurementTimeout = Float()
    measurementsPerIteration = Int()
    willSendEmail = Bool()
    emailAddresses = Str()
    notes = Str()
    enable_sounds = Bool()
    enable_instrument_threads = Bool()

    #iteration traits
    progress = Int()
    progressGUI = Int()
    path = Member()  # full path to current experiment directory
    dailyPath = Member()
    experimentPath = Member()

    iteration = Member()
    iterationStr = Str()
    measurement = Member()
    measurementStr = Str()
    goodMeasurements = Member()
    goodMeasurementsStr = Str()
    totalIterations = Member()

    #time traits
    timeStarted = Float()
    timeStartedStr = Str()
    currentTime = Float()
    currentTimeStr = Str()
    timeElapsed = Float()
    timeElapsedStr = Str()
    totalTime = Float()
    totalTimeStr = Str()
    timeRemaining = Float()
    timeRemainingStr = Str()
    completionTime = Float()
    completionTimeStr = Str()
    
    #variables traits
    dependentVariablesStr = Str()
    constantsStr = Str()
    constantReport = Member()
    variableReport = Member()
    variablesNotToSave = Str()
    
    #list of Analysis objects
    analyses = Member()

    #optimization
    max_iterations = Int()
    optimizer_count = Int()
    optimizer_iteration_count = Int()
    experiment_hdf5 = Member()

    #things we would rather not have to make Atom definitions for, but are forced to by Atom
    timeOutExpired = Member()
    instruments = Member()
    completedMeasurementsByIteration = Member()
    independentVariables = Member()
    ivarNames = Member()
    ivarIndex = Member()
    ivarValueLists = Member()
    ivarSteps = Member()
    constants = Member()
    vars = Member()
    hdf5 = Member()
    measurementResults = Member()
    iterationResults = Member()
    allow_evaluation = Member()
    log = Member()
    log_handler = Member()
    gui = Member()  # a reference to the gui Main, for use in Prop.set_gui
    optimizer = Member()
    ivarBases = Member()

    def __init__(self):
        """Defines a set of instruments, and a sequence of what to do with them."""
        logger.debug('experiment.__init__()')
        self.setup_logger()

        self.allow_evaluation = False

        super(Experiment, self).__init__('experiment', self) #name is 'experiment', associated experiment is self

        #default values
        self.constantReport = StrProp('constantReport', self, 'Important output that does not change with iterations', '""')
        self.variableReport = StrProp('variableReport', self, 'Important output that might change with iterations', '""')
        self.optimizer = optimization.Optimization('optimizer', self, 'updates independent variables to minimize cost function')


        self.instruments = []  # a list of the instruments this experiment has defined
        self.completedMeasurementsByIteration = []
        self.independentVariables = ListProp('independentVariables', self, listElementType=IndependentVariable,
                                             listElementName='independentVariable')
        self.ivarIndex = []
        self.vars = {}
        self.analyses = []

        self.properties += ['version', 'constantsStr', 'independentVariables', 'dependentVariablesStr',
                            'pauseAfterIteration', 'pauseAfterMeasurement', 'pauseAfterError', 'saveData',
                            'saveSettings', 'settings_path', 'save_separate_notes', 'save2013styleFiles',
                            'localDataPath', 'networkDataPath', 'copyDataToNetwork',
                            'experimentDescriptionFilenameSuffix', 'measurementTimeout', 'measurementsPerIteration',
                            'willSendEmail', 'emailAddresses', 'progress', 'progressGUI', 'iteration', 'measurement',
                            'goodMeasurements', 'totalIterations', 'timeStarted', 'currentTime', 'timeElapsed',
                            'timeRemaining', 'totalTime', 'completionTime', 'constantReport', 'variableReport',
                            'variablesNotToSave', 'notes', 'max_iterations', 'enable_sounds',
                            'enable_instrument_threads', 'optimizer', 'optimizer_count', 'optimizer_iteration_count']
        #we do not load in status as a variable, to allow old settings to be loaded without bringing in the status of
        #the saved experiments

    def applyToSelf(self, dict):
        """Used to apply a bunch of variables at once.  This function is called using an Enaml deferred_call so that the
         updates are done in the GUI thread."""

        for key, value in dict.iteritems():
            try:
                setattr(self, key, value)
            except Exception as e:
                logger.warning('Exception applying {} with value {} in experiments.applyToSelf.\n{}'.format(key, value, e))
                raise PauseError

    def autosave(self):
        logger.debug('Saving settings to default settings.hdf5 ...')
        #remove old autosave file
        try:
            os.remove('previous_settings.hdf5')
        except Exception as e:
            logger.debug('Could not delete previous_settings.hdf5:\n'+str(e))
        try:
            os.rename('settings.hdf5','previous_settings.hdf5')
        except Exception as e:
            logger.error('Could not rename old settings.hdf5 to previous_settings.hdf5:\n'+str(e))

        #create file
        f = h5py.File('settings.hdf5', 'w')
        #recursively add all properties
        x = f.create_group('settings')
        self.toHDF5(x)
        f.flush()
        return f
        #you will need to do autosave().close() wherever this is called

    def create_data_files(self):
        """Create a new HDF5 file to store results.  This is done at the beginning of
        every experiment."""

        #if a prior HDF5 results file is open, then close it
        if hasattr(self, 'hdf5') and (self.hdf5 is not None):
            try:
                self.hdf5.flush()
                self.hdf5.close()
            except Exception as e:
                logger.warning('Exception closing hdf5 file.\n'+str(e))
                raise PauseError

        if self.saveData:
            #create a new directory for experiment

            #build the path
            self.dailyPath = datetime.datetime.fromtimestamp(self.timeStarted).strftime('%Y_%m_%d')
            self.experimentPath = datetime.datetime.fromtimestamp(self.timeStarted).strftime('%Y_%m_%d_%H_%M_%S_')+self.experimentDescriptionFilenameSuffix
            self.path = os.path.join(self.localDataPath, self.dailyPath, self.experimentPath)

            #check that it doesn't exist first
            if not os.path.isdir(self.path):
                #create the directory
                #use os.makedirs instead of os.mkdir to create the intermediate dailyPath directory if it does not exist
                os.makedirs(self.path)

            #save to a real file
            self.hdf5 = h5py.File(os.path.join(self.path, 'results.hdf5'), 'a')

        else:
            #hold results only in memory
            self.hdf5 = h5py.File('results.hdf5', 'a', driver='core', backing_store=False)

        #add settings
        if self.saveSettings:

            #start by saving settings
            logger.debug('Autosaving')
            autosave_file = self.autosave()
            logger.debug('Done autosaving')

            try:
                logger.debug('Copying autosave data to current HDF5')
                autosave_file['settings'].copy(autosave_file['settings'], self.hdf5)
            except:
                logger.warning('Problem trying to copy autosave settings to HDF5 results file.')
                raise PauseError
            finally:
                autosave_file.close()
                logger.debug('Autosave closed')

        #store independent variable data for experiment
        t = time.time()
        self.hdf5.attrs['start_time'] = t
        self.hdf5.attrs['start_time_str'] = self.date2str(t)
        self.hdf5.attrs['ivarNames'] = self.ivarNames
        #self.hdf5.attrs['ivarValueLists'] = self.ivarValueLists  # temporarily disabled because HDF5 cannot handle arbitrary length lists of lists
        self.hdf5.attrs['ivarSteps'] = self.ivarSteps

        #create a group to hold iterations in the hdf5 file
        self.hdf5.create_group('iterations')

        #store notes.  They will be stored again at the end of the experiment.
        self.hdf5['notes'] = self.notes

        logger.debug('Finished create_data_files()')

    def create_hdf5_iteration(self):
        #write the iteration settings to the hdf5 file
        self.iterationResults = self.hdf5.create_group('iterations/'+str(self.iteration))
        t = time.time()
        self.iterationResults.attrs['start_time'] = t
        self.iterationResults.attrs['start_time_str'] = self.date2str(t)
        self.iterationResults.attrs['iteration'] = self.iteration
        self.iterationResults.attrs['ivarNames'] = self.ivarNames
        self.iterationResults.attrs['ivarValues'] = [i.currentValue for i in self.independentVariables]
        self.iterationResults.attrs['ivarIndex'] = self.ivarIndex
        self.iterationResults['report'] = self.variableReport.value

        #store the independent and dependent variable space
        v = self.iterationResults.create_group('variables')
        ignoreList = self.variablesNotToSave.split(',')
        for key, value in self.vars.iteritems():
            if key not in ignoreList:
                try:
                    v[key] = value
                except Exception as e:
                    logger.warning('Could not save variable '+key+' as an hdf5 dataset with value: '+str(value)+'\n'+str(e))

    def create_optimizer_iteration(self):
        """
        This method sets up the hdf5 storage for a new optimization loop.  It is called whenever a new iteration is
        started, and then checks to see that we really are at the beginning of a whole optimization loop.
        An hdf5 group is created to store the iterations for only this optimization loop.  Hard links are created so
        that the iteration results will show up both in this new group, and in the iterations directory that stores
        the iterations for all loops.  An optimizer_iteration_count resets every loop so that the results can be stored
        into this new directory counting for zero.
        """

        # if this is a new optimization loop
        experiment_hdf5_path = 'experiments/{}'.format(self.optimizer_count)
        if experiment_hdf5_path not in self.hdf5:
            # create a new group to store all the iterations in this loop
            self.experiment_hdf5 = self.hdf5.create_group(experiment_hdf5_path)
            # reset the optimization_iteration number, which tracks how many iterations are in this loop
            self.optimizer_iteration_count = 0
        # add this iteration to the group
        self.experiment_hdf5['iterations/'+str(self.optimizer_iteration_count)] = self.iterationResults

    def date2str(self, time):
        return datetime.datetime.fromtimestamp(time).strftime('%Y-%m-%d %H:%M:%S')

    def endThread(self):
        """Launches end() in a new thread, to keep GUI free"""
        if self.status == 'running':
            logger.warning('You cannot manually finish an experiment that is still running.  Pause first.')
        else:
            thread = threading.Thread(target=self.end)
            thread.daemon = True
            thread.start()

    def end(self):
        """Finishes the current experiment, and then uploads data"""

        try:
            self.postExperiment()
            self.upload()
        except PauseError:
            self.set_status('paused after error')
        except Exception as e:
            logger.warning('Uncaught Exception in experiment.end:\n{}\n{}'.format(e, traceback.format_exc()))
            self.set_status('paused after error')

    def eval_general(self, string):
        return cs_evaluate.evalWithDict(string, self.vars)

    def eval_bool(self, string):
        value, valid = self.eval_general(string)
        if value is None:
            return value, valid
        else:
            try:
                return bool(value), valid
            except Exception as e:
                logger.warning('Unable to convert string to bool: {}, {}\n{}\n'.format(string, value, e))
                return None, False

    def eval_float(self, string):
        value, valid = self.eval_general(string)
        if value is None:
            return value, valid
        else:
            try:
                return float(value), valid
            except Exception as e:
                logger.warning('Unable to convert string to bool: {}, {}\n{}\n'.format(string, value, e))
                return None, False

    def evaluate(self):
        """Resolve all equation in instruments.  This is overwritten from Prop."""
        if self.allow_evaluation:
            logger.debug('Experiment.evaluate() ...')

            # start with the constants
            self.vars = self.constants.copy()

            # add the independent variables current values to the dict
            self.updateIndependentVariables()
            ivars = dict([(i.name, i.currentValue) for i in self.independentVariables])
            self.vars.update(ivars)

            #evaluate the dependent variable multi-line string
            cs_evaluate.execWithDict(self.dependentVariablesStr, self.vars)

            #evaluate variable report
            #at this time the properties are not all evaluated, so, we must do this one manually
            self.variableReport.evaluate()

            logger.debug('Evaluating instruments ...')
            #re-evaluate all instruments
            for i in self.instruments:
                i.evaluate()  # each instrument will calculate its properties

            self.update_gui()

            logger.debug('Finished evaluate().')

    def evaluate_constants(self):
        if self.allow_evaluation:
            # create a new dictionary and evaluate the constants into it
            self.constants = {}
            cs_evaluate.execWithDict(self.constantsStr, self.constants)

            # reset self.vars so it can be used in evaluating the constantReport
            self.vars = self.constants.copy()

            # evaluate constant report
            #at this time the properties are not all evaluated, so, we must do this one manually
            self.constantReport.evaluate()

    def evaluateAll(self):
        if self.allow_evaluation:
            self.evaluate_constants()
            self.evaluateIndependentVariables()
            self.evaluate()

    def evaluateIndependentVariables(self):
        if self.allow_evaluation:
            logger.debug('Evaluating independent variables ...')

            #make sure ivar functions have been parsed
            self.independentVariables.evaluate()

            #set up independent variables
            self.ivarNames = [i.name for i in self.independentVariables]  # names of independent variables
            self.ivarValueLists = [i.valueList for i in self.independentVariables]
            self.ivarSteps = [i.steps for i in self.independentVariables]
            self.totalIterations = int(numpy.product(self.ivarSteps))

            # figure out how often each ivar will update with iterations (the "base")
            # the first (i.e. top) ivar becomes the "inner loop"
            self.ivarBases = numpy.roll(numpy.cumprod(self.ivarSteps), 1)
            if len(self.ivarBases>0):
                self.ivarBases[0] = 1

    def goThread(self):
        thread = threading.Thread(target=self.go)
        thread.daemon = True
        thread.start()

    def go(self):
        """Pick up the experiment wherever it was left off."""

        #check if we are ready to do an experiment
        if not self.status.startswith('paused'):
            logger.info('Current status is {}. Cannot continue an experiment unless status is paused.'.format(self.status))
            return  # exit
        self.set_status('running')  # prevent another experiment from being started at the same time
        self.set_gui({'valid': True})
        logger.info('running experiment')

        try:  # if there is an error we exit the inner loops and respond appropriately

            # optimization and iteration loop
            logger.debug('Before go() loop: status = {}, and optimizer.is_done = {}'.format(self.status, self.optimizer.is_done))
            while (self.status == 'running') and ((not self.optimizer.enable) or (not self.optimizer.is_done)):
                logger.debug("starting new iteration")

                # at the start of a new iteration, or if we are continuing
                logger.debug("evaluating")
                self.evaluate()  # update ivars to current iteration and re-calculate dependent variables
                logger.debug("updating instruments")
                self.update()  # send current values to hardware

                # only at the start of a new iteration
                if len(self.completedMeasurementsByIteration) <= self.iteration:
                    self.completedMeasurementsByIteration.append(0)  # start a new counter for this iteration
                if not (str(self.iteration) in self.hdf5['iterations']):
                    self.create_hdf5_iteration()  # create an entry in the in hdf5 file
                    self.preIteration()  # reset the analyses

                    # only at the start of a new optimization experiment loop
                    self.create_optimizer_iteration()

                #loop until the desired number of measurements are taken
                while (self.goodMeasurements < self.measurementsPerIteration) and (self.status == 'running'):
                    self.set_gui({'valid': True})  # reset all the red error background graphics to show no-error
                    logger.info('iteration {} measurement {}'.format(self.iteration, self.measurement))
                    self.measure()  # tell all instruments to do the experiment sequence and acquire data
                    self.updateTime()  # update the countdown/countup clocks
                    logger.debug('updating measurement count')

                    #make sure results are written to disk
                    logger.debug('flushing hdf5')
                    self.hdf5.flush()

                    # increment the measurement counter, except at the end
                    if self.goodMeasurements < self.measurementsPerIteration:
                        self.measurement += 1
                    else:
                        break

                    # pause after measurement
                    if self.status == 'running' and self.pauseAfterMeasurement:
                        logger.info('paused after measurement')
                        self.set_status('paused after measurement')
                        self.set_gui({'valid': False})
                        if self.enable_sounds:
                            sound.error_sound()

                    self.update_gui()

                # Measurement loop exited, but that might mean we are paused, or an error.
                # So check to see if we completed the iteration.
                if self.goodMeasurements >= self.measurementsPerIteration:

                    # We have completed this iteration, move on to the next one
                    logger.debug("Finished iteration")

                    self.postIteration()  # run analysis

                    # if this was the last iteration in this optimization loop, then run analysis and run optimizer
                    if (self.iteration % self.totalIterations) == self.totalIterations-1:

                        logger.debug("Finished all iterations")
                        self.postExperiment()  # run analyses
                        self.optimizer.update(self.hdf5, self.experiment_hdf5)  # update optimizer variables
                        if self.optimizer.is_done:
                            # the experiment is finished, run final analysis, upload data, and exit loop
                            for i in self.analyses:
                                i.finalize(self.hdf5)
                            self.optimizer.finalize(self.hdf5)
                            self.upload()
                            break
                        self.optimizer_count += 1

                    # if we didn't end the optimization above, we should advance to the next iteration
                    self.iteration += 1  # increase iteration number
                    self.optimizer_iteration_count += 1
                    self.measurement = 0  # reset measurement count
                    self.goodMeasurements = 0  # reset good measurement count

                    # pause after iteration
                    if self.pauseAfterIteration:
                        if self.status == 'running':
                            logger.info('paused after iteration')
                            self.set_status('paused after iteration')
                            self.set_gui({'valid': False})
                            # play sounds
                            if self.enable_sounds:
                                sound.error_sound()
                        elif self.status == 'paused after measurement':
                            self.set_status('paused after iteration')
                            self.set_gui({'valid': False})
                            # we already played the sounds after the measurement.  Don't play the sounds again.
                        # else the status is idle or error, and we should not downgrade the status to paused

        except PauseError:
            #This should be the only place that PauseError is explicitly handed.
            #All other non-fatal error caught higher up in the experiment chain should
            #gracefully handle the error, then 'raise PauseError' so that the experiment
            #exits out to this point.
            if self.pauseAfterError:
                self.set_status('paused after error')
            self.set_gui({'valid': False})
            if self.enable_sounds:
                sound.error_sound()
        except Exception as e:
            logger.error('Exception during experiment:\n'+str(e)+'\n'+str(traceback.format_exc())+'\n')
            if self.pauseAfterError:
                self.set_status('paused after error')
            self.set_gui({'valid': False})
            if self.enable_sounds:
                sound.error_sound()

    def loadDefaultSettings(self):
        """Look for settings.hdf5 in this directory, and if it exists, load it."""
        logger.debug('Loading default settings ...')

        if os.path.isfile('settings.hdf5'):
            self.load('settings.hdf5')
        else:
            logger.debug('Default settings.hdf5 does not exist.')

    def load(self, path):
        logger.debug('Loading file: '+path)

        #set path as default
        self.settings_path = os.path.dirname(path)

        #Disable any equation evaluation while loading.  We will evaluate everything after.
        if self.allow_evaluation:
            allow_evaluation_was_toggled = True
            self.allow_evaluation = False
        else:
            allow_evaluation_was_toggled = False

        #load hdf5 from a file
        if not os.path.isfile(path):
            logger.debug('Settings file {} does not exist'.format(path))
            raise PauseError

        try:
            f = h5py.File(path, 'r')
        except Exception as e:
            logger.warning('Problem loading HDF5 settings file in experiment.load().\n{}\n{}\n'.format(e, traceback.format_exc()))
            raise PauseError

        settings = f['settings/experiment']

        try:
            self.fromHDF5(settings)
        except Exception as e:
            logger.warning('in experiment.load()\n'+str(e)+'\n'+str(traceback.format_exc()))
            # this is an error, but we will not pass it on, in order to finish loading


        f.close()
        logger.debug('File load done.')

        if allow_evaluation_was_toggled:
            self.allow_evaluation = True

        #now re-evaluate everything
        self.evaluateAll()

    def measure(self):
        """Enables all instruments to begin a measurement.  Sent at the beginning of every measurement.
        Actual output or input from the measurement may yet wait for a signal from another device."""

        logger.debug('starting measurement')
        start_time = time.time()  # record start time of measurement
        self.timeOutExpired = False

        # start each instrument
        for i in self.instruments:
            if i.enable:
                #check that the instruments are initalized
                if not i.isInitialized:
                    print 'experiment.measure() initializing '+i.name
                    i.initialize()  # reinitialize
                    i.update()  # put the settings to where they should be at this iteration
                else:
                    #check that the instrument is not already occupied
                    if not i.isDone:
                        logger.warning('Instrument '+i.name+' is already busy, and will be stopped and restarted.')
                        i.stop()
                    #set a flag to indicate each instrument is now busy
                    i.isDone = False
                    #let each instrument begin measurement
                    #put each in a different thread, so they can proceed simultaneously
                    if self.enable_instrument_threads:
                        threading.Thread(target=i.start).start()
                    else:
                        i.start()
        logger.debug('all instruments started')

        #loop until all instruments are done
        #TODO: can we do this with a callback?
        while (not all([i.isDone for i in self.instruments])) and (self.status == 'running'):
            if time.time() - start_time > self.measurementTimeout:  # break if timeout exceeded
                self.timeOutExpired = True
                logger.warning('The following instruments timed out: '+str([i.name for i in self.instruments if not i.isDone]))
                return  # exit without saving results
            time.sleep(.01)  # wait a bit, then check again
        logger.debug('all instruments done')

        # give each instrument a chance to acquire final data
        for i in self.instruments:
            i.acquire_data()

        # record results to hdf5
        self.measurementResults = self.hdf5.create_group('iterations/'+str(self.iteration)+'/measurements/'+str(self.measurement))
        self.measurementResults.attrs['start_time'] = start_time
        self.measurementResults.attrs['start_time_str'] = self.date2str(start_time)
        self.measurementResults.attrs['measurement'] = self.measurement
        self.measurementResults.create_group('data') #for storing data
        for i in self.instruments:
            #Pass the hdf5 group to each instrument so they can write results to it.  We do it here because h5py is not
            # thread safe, and also this way we avoid saving results for aborted measurements.
            if i.enable:
                i.writeResults(self.measurementResults['data'])

        self.postMeasurement()
        logger.debug('finished measurement')

    def pause_now(self):
        """Pauses experiment as soon as possible.  It is much safer to use Pause after Measurement instead of this.
        One use for this is to set the status to 'paused' when halt was previously selected (setting the status to
        idle).  This will allow for the continuation of an experiment that was accidentally halted."""
        # Manually force the status to idle, to cause the experiment to end
        self.status = 'paused immediate'
        # stop each instrument
        for i in self.instruments:
            i.isDone = True

    def postExperiment(self):
        logger.info('Running postExperiment analyses ...')
        # run analysis
        for i in self.analyses:
            i.postExperiment(self.experiment_hdf5)

    def postIteration(self):
        logger.debug('Starting postIteration()')
        # run analysis
        for i in self.analyses:
            i.postIteration(self.iterationResults, self.hdf5)

    def postMeasurement(self):
        logger.debug('starting post measurement analyses')
        #run analysis
        good = True
        delete = False
        for i in self.analyses:
            a = i.postMeasurement(self.measurementResults, self.iterationResults, self.hdf5)
            if (a is None) or (a == 0):
                continue
            elif a == 1:
                # continue, but do not increment goodMeasurements
                good = False
                continue
            elif a == 2:
                # continue, but do not increment goodMeasurements, delete data when done
                good = False
                delete = True
                continue
            elif a == 3:
                # stop, do not increment goodMeasurements, delete data when done
                good = False
                delete = True
                break
            else:
                logger.warning('bad return value {} in experiment.postMeasurement() for analysis {}: {}'.format(a, i.name, i.description))
        if not self.saveData:
            #we are not saving data so remove the measurement from the hdf5
            delete = True
        if delete:
            m = self.measurementResults.attrs['measurement']  # get the measurement number
            del self.measurementResults  # remove the reference to the bad data
            del self.iterationResults['measurements/'+str(m)]  # really remove the bad data
        if good:
            self.goodMeasurements += 1
            self.completedMeasurementsByIteration[-1] += 1  # add one to the last counter in the list

    def preExperiment(self):
        #run analyses
        for i in self.analyses:
            i.preExperiment(self.hdf5)

    def preIteration(self):
        #run analyses
        for i in self.analyses:
            i.preIteration(self.iterationResults, self.hdf5)

    def reset(self):
        """Reset the iteration variables and timing."""

        #check if we are ready to do an experiment
        if self.status != 'idle':
            logger.info('Current status is {}. Cannot reset experiment unless status is idle.  Try halting first.'.format(self.status))
            return  # exit

        #reset the log
        self.reset_logger()
        logger.info('resetting experiment')
        self.set_gui({'valid': True})

        self.set_status('beginning experiment')

        #reset experiment variables
        self.timeStarted = time.time()
        self.iteration = 0
        self.measurement = 0
        self.goodMeasurements = 0
        self.completedMeasurementsByIteration = []
        self.progress = 0

        self.update_gui()

        # setup data directory and files
        self.create_data_files()

        # evaluate the constants and independent variables
        self.evaluate_constants()
        self.evaluateIndependentVariables()
        self.updateIndependentVariables()
        self.hdf5['constant_report'] = self.constantReport.value

        # run analyses preExperiment
        self.preExperiment()

        # setup optimizer
        self.optimizer.setup(self.hdf5)
        self.optimizer_count = 0

        self.set_status('paused before experiment')

    def reset_logger(self):
        #close old stream
        if self.log is not None:
            self.log.flush()
            self.log.close()
        #create a new one
        self.log = cStringIO.StringIO()
        self.log_handler.stream = self.log

    def resetAndGo(self):
        """Reset the iteration variables and timing, then proceed with an experiment."""
        self.reset()
        self.go()

    def resetAndGoThread(self):
        thread = threading.Thread(target=self.resetAndGo)
        thread.daemon = True
        thread.start()

    def resetThread(self):
        thread = threading.Thread(target=self.reset)
        thread.daemon = True
        thread.start()

    def save(self, path):
        """This function saves all the settings."""

        logger.info('Saving...')

        #set path as default
        self.settings_path = os.path.dirname(path)

        #HDF5
        self.autosave().close()

        #copy to default location
        logger.debug('Copying HDF5 to save path...')
        shutil.copy('settings.hdf5', path)

        #XML
        #logger.debug('Creating XML...')
        #x = self.toXML()
        ##write to the chosen file
        #logger.debug('Writing XML to save path...')
        #f = open(path+'.xml', 'w')
        #f.write(x)
        #f.close()
        #logger.debug('Writing default XML...')
        ##write to the default file
        #f = open('settings.xml', 'w')
        #f.write(x)
        #f.close()

        logger.info('... Save Complete.')

    def set_status(self, s):
        self.status = s
        self.set_gui({'statusStr': s})

    def setup_logger(self):
        #allow logging to a variable
        self.log = cStringIO.StringIO()
        rootlogger = logging.getLogger()
        self.log_handler = logging.StreamHandler(self.log)
        self.log_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(fmt='%(asctime)s - %(threadName)s - %(filename)s.%(funcName)s.%(lineno)s - %(levelname)s\n%(message)s\n', datefmt='%Y/%m/%d %H:%M:%S')
        self.log_handler.setFormatter(formatter)
        rootlogger.addHandler(self.log_handler)

    def stop(self):
        """Stops output as soon as possible.  This is not run during the course of a normal experiment."""
        # Manually force the status to idle, to cause the experiment to end
        self.status = 'idle'
        # stop each instrument
        for i in self.instruments:
            i.isDone = True
            i.stop()
            i.isInitialized = False
        self.set_gui({'statusStr': self.status})

    def time2str(self, time):
        return str(datetime.timedelta(seconds=time))

    def update(self):
        """Sends current settings to the instrument.  This function is run at the beginning of every new iteration.
        Does not explicitly call evaluate, to avoid duplication of effort.
        All calls to evaluate should already have been accomplished."""

        for i in self.instruments:
            if i.enable:
                #check that the instruments are initialized
                if not i.isInitialized:
                    i.initialize()  # reinitialize
                i.update()  # put the settings to where they should be at this iteration

    def update_gui(self):
        logger.debug('experiment.update_gui()')
        self.set_gui({'measurementStr': str(self.measurement),
                    'iterationStr': '{} of {}'.format(self.iteration, self.totalIterations-1),
                    'goodMeasurementsStr': '{} of {}'.format(self.goodMeasurements, self.measurementsPerIteration-1),
                    'statusStr': self.status,
                    'timeStartedStr': self.date2str(self.timeStarted),
                    'currentTimeStr': self.date2str(self.currentTime),
                    'timeElapsedStr': self.time2str(self.timeElapsed),
                    'timeRemainingStr': self.time2str(self.timeRemaining),
                    'totalTimeStr': self.time2str(self.totalTime),
                    'completionTimeStr': self.date2str(self.completionTime),
                    'progressGUI': self.progress
        })

    def updateIndependentVariables(self):
        """takes the iteration number and figures out which index number each independent variable should have"""

        # find the current index for each
        index = (self.iteration//self.ivarBases) % self.ivarSteps

        for i, x in enumerate(self.independentVariables):
           if not x.optimize:
                index[i] = x.setIndex(index[i])  # update each variable object
        self.ivarIndex = index

    def updateTime(self):
        """Updates the GUI clock and recalculates the time-to-completion predictions."""

        logger.debug('experiment.updateTime()')
        self.currentTime = time.time()

        self.timeElapsed = self.currentTime-self.timeStarted

        #calculate time per measurement
        completedMeasurements = sum(self.completedMeasurementsByIteration)
        if self.timeElapsed != 0:
            timePerMeasurement = completedMeasurements/self.timeElapsed
        else:
            timePerMeasurement = 1
        if len(self.completedMeasurementsByIteration) <= 1:
            #if we're still in the first iteration, use the intended number of measurements
            estTotalMeasurements = self.measurementsPerIteration*self.totalIterations
        else:
            #if we're after the first iteration, we have more information to work with, use the actual average number of measurements per iteration
            estTotalMeasurements = numpy.mean(self.completedMeasurementsByIteration[:-1])*self.totalIterations
        if estTotalMeasurements > 0:
            self.progress = int(100*completedMeasurements/estTotalMeasurements)
        else:
            self.progress = 0

        self.timeRemaining = timePerMeasurement*(estTotalMeasurements-completedMeasurements)
        self.totalTime = self.timeElapsed+self.timeRemaining
        self.completionTime = self.timeStarted+self.totalTime

    def upload(self):
        #store the notes again
        logger.info('Storing notes ...')
        del self.hdf5['notes']
        self.hdf5['notes'] = self.notes

        #store the log
        logger.info('Storing log ...')
        self.log.flush()
        self.hdf5['log'] = self.log.getvalue()
        self.hdf5.flush()

        #copy to network
        if self.copyDataToNetwork:
            logger.info('Copying data to network...')
            shutil.copytree(self.path, os.path.join(self.networkDataPath, self.dailyPath, self.experimentPath))

        self.set_status('idle')
        logger.info('Finished Experiment.')
        self.progress = 100
        self.update_gui()
        if self.enable_sounds:
            sound.complete_sound()

    def uploadNowThread(self):
        """Launches upload() in a new thread, to keep GUI free"""
        if self.status == 'running':
            logger.warning('You cannot manually finish an experiment that is still running.  Pause first.')
        else:
            thread = threading.Thread(target=self.upload)
            thread.daemon = True
            thread.start()

    def uploadNow(self):
        """Skip straight to uploading the current data."""

        try:
            self.upload()
        except PauseError:
            self.set_status('paused after error')
        except Exception as e:
            logger.warning('Uncaught Exception in experiment.upload:\n{}\n{}'.format(e, traceback.format_exc()))
            self.set_status('paused after error')
