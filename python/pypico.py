"""pypico.py
Part of the AQuA Cesium Controller software package

author=Matthew Ebert
created=2017-05-25

This instrument communicates with the pypcio server running in another process
using zmq and SCPI commands.
The pypico server abstracts the closed loop control of picomotor positioners.
"""

__author__ = 'Matthew Ebert'
import logging
logger = logging.getLogger(__name__)

from cs_instruments import Instrument
from instrument_property import ListProp, FloatProp
import zmq
from picomotors import Picomotor
from cs_errors import PauseError

# get the config file
from __init__ import import_config
config = import_config()

from atom.api import Float, Str, Int, Member

def is_error_msg(msg):
    error_str = "Error : "
    return msg[:len(error_str)] == error_str

class PyPicomotor(Picomotor):
    current_position = Float()

    def __init__(self, name, experiment, description=''):
        super(PyPicomotor, self).__init__(name, experiment, description)
        self.desired_position = FloatProp('desired_position', experiment, 'the desired position','0')
        self.properties += ['current_position']

    def readPosition(self, socket):
        socket.send('READ:MOT{}'.format(self.motor_number))
        message = socket.recv()
        if is_error_msg(message):
            no_error = False
            msg = 'When reading picomotor angle, recieved error msg: `{}`'
            logger.warn(msg.format(message))
            raise PauseError
        else:
            try:
                self.current_position = float(message)
            except Exception:
                msg = 'Exception when attempting to read motor `{}` position.'
                logger.exception(msg.format(self.motor_number))

    def update(self):
        return 'MOVE:ABS:MOT{}:{} DEG'.format(
            self.motor_number,
            self.desired_position.value
        )

class PyPicoServer(Instrument):
    version = '2017.05.25'
    IP = Str()
    port = Int()
    motors = Member()
    context = Member()
    socket = Member()

    def __init__(self, name, experiment, description=''):
        super(PyPicoServer, self).__init__(name, experiment, description)
        self.motors = ListProp(
            'motors',
            experiment,
            'A list of individual picomotors',
            listElementType=PyPicomotor,
            listElementName='motor'
        )
        self.IP = '127.0.0.1'
        self.port = 5000
        self.properties += ['version', 'IP', 'port', 'motors']

    def initialize(self):
        """Open the zmq socket"""
        if self.enable:
            self.context = zmq.Context()
            self.socket = self.context.socket(zmq.REQ)
            # set socket timeout in ms
            self.socket.RCVTIMEO = config.getint('PYPICO', 'Timeout')
            self.socket.connect('tcp://{}:{}'.format(self.IP, self.port))

            try:
                # read motor positions from server
                self.readPositions()
            except Exception:
                logger.exception('Problem initializing sever communication in pypico.')

    def readPositions(self):
        '''Read the position of all picomotors in degrees'''
        logger.info('Reading picomotor positions...')
        request = "READ:MOT{}" # READ:MOTor#
        no_error = True
        i = 0
        for m in self.motors:
            m.readPosition(self.socket)

    def update(self):
        """Every iteration, send the motors updated positions.
        """
        if self.enable:
            msg = ''
            try:
                for m in self.motors:
                    # the motor class can make up its own commands
                    self.socket.send(m.update())
                    message = self.socket.recv()
                    if is_error_msg(message):
                        msg = 'When moving picomotor `{}`, recieved error msg: `{}`'
                        logger.warn(msg.format(m.motor_number, message))
                        # TODO: check to see if the error is because it didnt
                        # meet the setpoint, within the specified error
                        # if that is the case try again at least once
                        raise PauseError
                    else:
                        m.readPosition(self.socket)
                        msg = (
                            'Motor `{}` moved to position `{}` with no error.'
                            ' Positional error is `{}` DEG.'
                        )
                        logger.info(msg.format(
                            m.motor_number,
                            m.current_position,
                            m.desired_position.value - m.current_position
                        ))

            except Exception as e:
                logger.exception('Problem setting Picomotor position, closing socket.')
                self.socket.close()
                self.isInitialized = False
                raise PauseError
